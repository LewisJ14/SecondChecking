"""Independent, operator-confirmed audio checks with owned audio streams."""

import threading
import time
import sys
import wave
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from utils.helpers import log_event
from utils.ui_scaling import center_window_to_content
from services.hardware_job import HardwareJob, JobPoller
from services.check_results import start_measurement
from ui.scrolling import ScrollableFrame

try:
    import numpy as np
    import sounddevice as sd
except ImportError:  # Optional dependencies in an incomplete installation.
    np = None
    sd = None


def audio_device_inventory():
    """Resolve Windows default endpoints in the same process as enumeration."""
    devices = list(sd.query_devices())
    host_apis = list(sd.query_hostapis())
    defaults = tuple(int(index) for index in sd.default.device)
    if sys.platform == 'win32':
        for api in host_apis:
            if api['name'].casefold() == 'windows wasapi':
                defaults = (int(api['default_input_device']),
                            int(api['default_output_device']))
                break
    result = dict(state='complete', devices=devices,
                  host_api_names=[api['name'] for api in host_apis])
    for key, index, channels in (('default_input', defaults[0], 'max_input_channels'),
                                 ('default_output', defaults[1], 'max_output_channels')):
        result[key] = index if 0 <= index < len(devices) and devices[index][channels] > 0 else None
    return result


def resample_audio(data, source_rate, target_rate):
    """Convert the stream format while preserving duration, pitch and channels."""
    count = max(1, round(len(data) * target_rate / source_rate))
    spectrum = np.fft.rfft(data, axis=0)
    converted = np.zeros((count // 2 + 1, data.shape[1]), dtype=spectrum.dtype)
    shared = min(len(data), count)
    converted[:shared // 2 + 1] = spectrum[:shared // 2 + 1]
    if shared % 2 == 0 and count != len(data):
        converted[shared // 2] *= 2 if count < len(data) else .5
    result = np.fft.irfft(converted, n=count, axis=0) * count / len(data)
    return np.clip(result, -1, 1).astype('float32')


class AudioOperation:
    """One bounded capture/playback; never alters OS volume or sd.default."""

    def __init__(self):
        self.stream = None
        self.done = threading.Event()
        self.chunks = []
        self.frames = 0
        self.expected_frames = 0
        self.error = None
        self.rate = 0
        self.deadline = 0

    def start(self, device, recording=False, data=None, rate=None, level=1.0):
        self.close()
        self.done.clear()
        self.error = None
        self.chunks = []
        self.frames = 0
        info = sd.query_devices(device)
        self.rate = int(rate or info['default_samplerate'])
        if recording:
            limit = int(self.rate * 4)
        else:
            if data is None:
                base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) \
                    else Path(__file__).resolve().parents[1]
                with wave.open(str(base / 'assets' / 'AudioCheck.wav'), 'rb') as audio:
                    if audio.getsampwidth() != 2:
                        raise ValueError('Speaker sample must use 16-bit PCM.')
                    self.rate = audio.getframerate()
                    data = np.frombuffer(audio.readframes(audio.getnframes()),
                                         dtype='<i2').astype('float32')
                    data = data.reshape(-1, audio.getnchannels()) / 32768.0
            data = np.asarray(data, dtype='float32')
            if data.ndim == 1:
                data = data.reshape(-1, 1)
            if not data.size or not np.isfinite(data).all():
                raise ValueError('No valid audio to play.')
            try:
                sd.check_output_settings(device=device, samplerate=self.rate,
                                         channels=data.shape[1], dtype='float32')
            except sd.PortAudioError:
                target_rate = int(info['default_samplerate'])
                if target_rate == self.rate:
                    raise
                sd.check_output_settings(device=device, samplerate=target_rate,
                                         channels=data.shape[1], dtype='float32')
                from services.runtime import log_diagnostic
                log_diagnostic('audio.rate_converted', source_rate=self.rate,
                               sample_rate=target_rate, channels=data.shape[1])
                data = resample_audio(data, self.rate, target_rate)
                self.rate = target_rate
            # Attenuate only: do not amplify quiet/background recordings.
            data = data * min(max(float(level), 0.01), 1.0)
            limit = len(data)
        self.deadline = time.monotonic() + limit / self.rate + 5
        self.expected_frames = limit

        def callback(buffer, frames, timing, status):
            if status:
                self.error = str(status)
            count = min(frames, limit - self.frames)
            if recording:
                self.chunks.append(buffer[:count, 0].copy())
            else:
                buffer.fill(0)
                buffer[:count] = data[self.frames:self.frames + count]
            self.frames += count
            if self.frames >= limit:
                raise sd.CallbackStop()

        factory = sd.InputStream if recording else sd.OutputStream
        try:
            self.stream = factory(
                device=device, samplerate=self.rate,
                channels=1 if recording else data.shape[1],
                dtype='float32', callback=callback,
                finished_callback=self.done.set)
            self.stream.start()
        except Exception:
            self.close()
            raise

    def close(self):
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()

    def recording(self):
        return np.concatenate(self.chunks) if self.chunks else None


def automatic_microphone_check(input_device, output_device, level=1.0):
    """Listen while playing the sample; sound levels alone may pass the mic."""
    capture, playback = AudioOperation(), AudioOperation()
    try:
        capture.start(input_device, recording=True)
        playback.start(output_device, level=level)
        for operation in (capture, playback):
            while not operation.done.wait(.05):
                if time.monotonic() > operation.deadline:
                    raise TimeoutError('Automatic microphone check timed out.')
            if operation.error or operation.frames != operation.expected_frames:
                raise RuntimeError(operation.error or 'Incomplete audio stream.')
        audio = capture.recording()
        if audio is None or not audio.size or not np.isfinite(audio).all():
            raise RuntimeError('No valid microphone data captured.')
        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(np.square(audio))))
        return audio, capture.rate, peak >= .02 or rms >= .005
    finally:
        try:
            capture.close()
        finally:
            playback.close()


def combined_audio_check(input_device, output_device, level=1.0):
    """Play speakers even if microphone capture is unavailable or fails."""
    capture, playback = AudioOperation(), AudioOperation()
    microphone_error, audio = None, None
    try:
        try:
            if input_device is None:
                raise RuntimeError('No microphone input is available.')
            capture.start(input_device, recording=True)
        except Exception as exc:
            microphone_error = str(exc)
        playback.start(output_device, level=level)
        while not playback.done.wait(.05):
            if time.monotonic() > playback.deadline:
                raise TimeoutError('Speaker playback timed out.')
        if playback.error or playback.frames != playback.expected_frames:
            raise RuntimeError(playback.error or 'Incomplete speaker playback.')
        if microphone_error is None:
            try:
                while not capture.done.wait(.05):
                    if time.monotonic() > capture.deadline:
                        raise TimeoutError('Microphone capture timed out.')
                if capture.error or capture.frames != capture.expected_frames:
                    raise RuntimeError(capture.error or 'Incomplete microphone capture.')
                audio = capture.recording()
                if audio is None or not audio.size or not np.isfinite(audio).all():
                    raise RuntimeError('No valid microphone data captured.')
            except Exception as exc:
                microphone_error = str(exc)
        passed = bool(microphone_error is None and (
            np.max(np.abs(audio)) >= .02 or
            np.sqrt(np.mean(np.square(audio))) >= .005))
        return audio, dict(state='complete', rate=capture.rate,
                           automatic_pass=passed, microphone_error=microphone_error)
    finally:
        try:
            capture.close()
        finally:
            playback.close()


class IsolatedAudioOperation:
    def __init__(self):
        self.job = None
        self.done = threading.Event()
        self.error = None
        self.rate = 0
        self.frames = self.expected_frames = 0
        self.deadline = 0
        self.audio = None
        self.automatic_pass = False
        self.microphone_error = None

    def start(self, device, recording=False, data=None, rate=None, level=1.0,
              automatic_output=None, combined=False, input_device=None):
        self.close()
        self.done.clear()
        self.error, self.audio = None, None
        self.automatic_pass = False
        self.microphone_error = None
        self.frames, self.expected_frames = 0, 1
        self.deadline = time.monotonic() + 15
        if combined:
            self.job = HardwareJob('audio-combined', dict(input_device=input_device,
                                   output_device=device, level=level), timeout=15)
        elif automatic_output is not None:
            self.job = HardwareJob('audio-auto', dict(input_device=device,
                                   output_device=automatic_output, level=level),
                                   timeout=15)
        else:
            self.job = HardwareJob('audio', dict(device=device, recording=recording,
                                   rate=rate, level=level), timeout=15, audio=data)

    def poll(self):
        if self.job is None or self.done.is_set():
            return
        reply = self.job.poll()
        if reply is None:
            return
        if reply['state'] != 'complete':
            self.error = reply.get('detail', 'Audio worker failed.')
        else:
            self.frames = self.expected_frames
            self.rate = reply['rate']
            self.automatic_pass = reply.get('automatic_pass', False)
            self.microphone_error = reply.get('microphone_error')
            path = self.job.directory / 'recording.npy'
            if path.exists():
                self.audio = np.load(str(path), allow_pickle=False)
        self.done.set()

    def recording(self):
        return self.audio

    def close(self):
        if self.job is not None:
            self.job.close()
            self.job = None


class AudioTestDialog:
    def __init__(self, root, results, labels, key, tests_window=None,
                 completion_event=None, manual_fallback=False):
        self.root = root
        self.results, self.labels, self.key = results, labels, key
        self.tests_window = tests_window
        self.completion_event = completion_event
        self.operation = IsolatedAudioOperation()
        self.device_job = None
        self.audio = None
        self.audio_rate = None
        self.played = False
        self.closed = False
        self.poll_id = None
        self.busy = False
        self.last_error = False
        self.automatic = False
        self.manual_allowed = manual_fallback or key != 'microphone'
        self.manual_fallback = manual_fallback
        self.combined_pending = False
        self.microphone_needs_manual = False
        self.window = tk.Toplevel(root)
        self.window.title('Speaker and microphone check' if key == 'speaker'
                          else 'Microphone check')
        self.window.protocol('WM_DELETE_WINDOW', self.cancel)
        self.window.bind('<Escape>', lambda event: self.cancel())
        self.window.bind('<Destroy>', self._destroyed, add='+')
        self.status = tk.StringVar(value='Select the device to test.')
        self.level = tk.DoubleVar(value=100)
        self.inputs, self.outputs = {}, {}
        error = None
        surface = ScrollableFrame(self.window, height=420)
        surface.pack(fill='both', expand=True, padx=16, pady=(16, 0))
        body = ttk.Frame(surface.content, padding=18, style='Surface.TFrame')
        body.pack(fill='both', expand=True)
        def wrap_body(event):
            for child in body.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(wraplength=max(100, event.width - 40))
        surface.canvas.bind('<Configure>', wrap_body, add='+')
        ttk.Label(body, text='Speaker & microphone' if key == 'speaker' else 'Microphone',
                  style='HeaderTitle.TLabel', font=('Segoe UI', 16, 'bold')).pack(
                      anchor='w', pady=(0, 10))
        instructions = (
            'Automatic detection did not pass. Record a short phrase, play it '
            'back, then confirm whether it is clear. You can also retry automatic detection.'
            if manual_fallback else
            'Start the automatic check: the sample plays while the microphone '
            'listens. If unsuccessful, record and replay a phrase manually.'
            if key == 'microphone' else
            'Play the sample while the microphone listens automatically. '
            'Confirm that the speakers sound clear. If microphone detection '
            'fails, a manual check follows.')
        ttk.Label(body, text=instructions, wraplength=490,
                  style='Surface.TLabel').pack(fill='x', pady=(0, 14))
        self.selectors = []
        self.input_choice = tk.StringVar()
        self.output_choice = tk.StringVar()
        self._selector(body, 'Microphone input', self.inputs,
                       self.input_choice)
        self._selector(body, 'Playback output', self.outputs,
                       self.output_choice)
        ttk.Label(body, text='Playback level (1–100%; starts at 100%)',
                  style='Surface.TLabel').pack()
        ttk.Scale(body, from_=1, to=100, variable=self.level).pack(fill='x')
        self.record_button = None
        self.auto_button = None
        if key == 'microphone':
            self.auto_button = ttk.Button(
                body, text='Start automatic microphone check',
                command=self.auto_check)
            self.auto_button.pack(pady=5)
            self.record_button = ttk.Button(
                body, text='Record phrase (4 seconds)', command=self.record)
            self.record_button.pack(pady=5)
        self.play_button = ttk.Button(body, text='Play recording' if
                                      key == 'microphone' else 'Test speakers and microphone',
                                      command=self.play)
        self.play_button.pack(pady=5)
        ttk.Label(body, textvariable=self.status, wraplength=490,
                  style='Surface.TLabel').pack(fill='x', pady=12)
        actions = ttk.Frame(self.window, padding=16)
        actions.pack(fill='x')
        for column in range(3):
            actions.columnconfigure(column, weight=1, uniform='decision')
        self.pass_button = ttk.Button(actions, text='Pass', style='success.TButton',
                                      command=lambda: self.finish('pass'))
        self.pass_button.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        self.fail_button = ttk.Button(actions, text='Fail', style='danger.Outline.TButton',
                                      command=lambda: self.finish('fail'))
        self.fail_button.grid(row=0, column=1, sticky='ew', padx=6)
        self.error_button = ttk.Button(body, text='Record test error',
                                       style='secondary.Outline.TButton',
                                       command=lambda: self.finish('error'))
        self.error_button.pack(fill='x', pady=3)
        from ui.bug_reports import open_report
        ttk.Button(body, text='Upload bug report…',
                   command=lambda: open_report(self.window)).pack(fill='x', pady=3)
        ttk.Button(body, text='Unavailable / unable to verify',
                   style='secondary.Outline.TButton',
                   command=lambda: self.finish('unavailable')).pack(
                       fill='x', pady=3)
        ttk.Button(actions, text='Cancel', style='secondary.Outline.TButton',
                   command=self.cancel).grid(row=0, column=2, sticky='ew', padx=(6, 0))
        self.available = bool(self.outputs and
                              (key == 'speaker' or self.inputs) and not error)
        self.last_error = bool(error)
        if not self.available:
            self.status.set(error or 'Required audio device is unavailable. '
                            'Reconnect it and reopen this test.')
        self._controls()
        if tests_window and hasattr(tests_window, 'register_cancel'):
            tests_window.register_cancel(self.cancel)
        scale = float(self.window.tk.call('tk', 'scaling')) / (96 / 72)
        center_window_to_content(self.window, min_width=round(580 * scale),
                                 min_height=round(620 * scale))
        self.status.set('Finding audio devices — Cancel is available.')
        self.device_job = JobPoller(self.window, 'audio-devices',
                                    self.devices_ready, timeout=15)

    def devices_ready(self, reply):
        if self.closed:
            return
        if reply['state'] != 'complete':
            self.last_error = True
            self.status.set('Audio devices unavailable.')
        else:
            for index, device in enumerate(reply['devices']):
                name = '{}: {}'.format(index, device['name'])
                api = device.get('hostapi')
                api_names = reply.get('host_api_names', [])
                if type(api) is int and 0 <= api < len(api_names):
                    name += ' [{}]'.format(api_names[api])
                if device['max_input_channels'] > 0:
                    self.inputs[name] = index
                if device['max_output_channels'] > 0:
                    self.outputs[name] = index
            self.selectors[0].config(values=list(self.inputs))
            self.input_choice.set(next((name for name, index in self.inputs.items()
                                        if index == reply.get('default_input')), ''))
            self.selectors[-1].config(values=list(self.outputs))
            self.output_choice.set(next((name for name, index in self.outputs.items()
                                         if index == reply.get('default_output')), ''))
            self.available = bool(self.outputs and (
                self.key == 'speaker' or self.inputs))
            self.status.set('Windows default devices selected. You can choose another device.'
                            if self.output_choice.get() and self.input_choice.get() else
                            'Select an available playback output and microphone.'
                            if self.available else 'Required audio device is '
                            'unavailable; reconnect it and reopen this test.')
        self._controls()

    def _selector(self, body, label, devices, variable):
        ttk.Label(body, text=label, style='Surface.TLabel').pack(anchor='w')
        selector = ttk.Combobox(body, textvariable=variable,
                                values=list(devices), state='readonly',
                                width=65)
        selector.pack(fill='x', pady=(0, 8))
        if devices:
            variable.set(next(iter(devices)))
        selector.bind('<<ComboboxSelected>>', self.changed)
        self.selectors.append(selector)

    def changed(self, event=None):
        self.audio = None
        self.audio_rate = None
        self.played = False
        if self.key == 'speaker' and self.combined_pending:
            self.results['microphone'] = 'n/a'
            self.microphone_needs_manual = True
        self.manual_allowed = self.manual_fallback or self.key != 'microphone'
        self.status.set('Device changed. Repeat this check before passing.')
        self._controls()

    def _controls(self):
        ready = (self.available and not self.busy
                 and self.output_choice.get() in self.outputs
                 and (self.key == 'speaker' or self.input_choice.get() in self.inputs))
        for selector in self.selectors:
            selector.configure(state='disabled' if self.busy else 'readonly')
        if self.record_button:
            self.record_button.configure(
                state='normal' if ready and self.manual_allowed else 'disabled')
        if self.auto_button:
            self.auto_button.configure(state='normal' if ready else 'disabled')
        self.play_button.configure(state='normal' if ready and (
            self.key == 'speaker' or self.audio is not None) else 'disabled')
        self.pass_button.configure(state='normal' if ready and self.played
                                   else 'disabled')
        self.fail_button.configure(state='disabled' if self.busy else 'normal')
        self.error_button.configure(state='normal' if self.last_error and
                                    not self.busy else 'disabled')

    def record(self):
        if not self.manual_allowed:
            return
        self.automatic = False
        self.audio = None
        self.played = False
        self._start(True)

    def play(self):
        self.automatic = False
        self.played = False
        if self.key == 'speaker' and not self.busy and self.available:
            self.combined_pending = True
            self.microphone_needs_manual = True
            if self.tests_window is not None:
                self.results['_combined_microphone_attempted'] = True
            start_measurement(self.results, 'microphone')
            self.results['microphone'] = 'n/a'
        self._start(False)

    def auto_check(self):
        if self.busy or not self.available:
            return
        self.automatic = True
        self.audio = None
        self.audio_rate = None
        self.played = False
        self._start(True)

    def _start(self, recording):
        if self.busy or not self.available:
            return
        try:
            self.last_error = False
            device = (self.inputs[self.input_choice.get()] if recording else
                      self.outputs[self.output_choice.get()])
            options = {}
            if self.automatic:
                options['automatic_output'] = self.outputs[self.output_choice.get()]
            if self.key == 'speaker':
                options.update(combined=True,
                               input_device=self.inputs.get(self.input_choice.get()))
            self.operation.start(device, recording=recording,
                                 data=None if recording else self.audio,
                                 rate=None if recording else self.audio_rate,
                                 level=self.level.get() / 100, **options)
            self.busy = True
            self.status.set('Playing sample and listening automatically...'
                            if self.automatic else
                            'Recording — speak now...' if recording else
                            'Playing... Listen before deciding.')
            self._controls()
            self.poll_id = self.window.after(50, self._poll, recording)
        except Exception as exc:
            self._error(exc)

    def _poll(self, recording):
        self.poll_id = None
        if self.closed:
            return
        try:
            self.operation.poll()
        except Exception as exc:
            self._error(exc)
            return
        if not self.operation.done.is_set():
            if time.monotonic() > self.operation.deadline:
                self._error('Audio device timed out.')
            else:
                self.poll_id = self.window.after(50, self._poll, recording)
            return
        try:
            self.operation.close()
            if self.operation.error:
                raise RuntimeError(self.operation.error)
            if self.operation.frames != self.operation.expected_frames:
                raise RuntimeError('Audio stream ended before completion.')
            self.busy = False
            if recording:
                self.audio = self.operation.recording()
                self.audio_rate = self.operation.rate
                if self.audio is None or not self.audio.size:
                    raise RuntimeError('No microphone data captured.')
                if self.automatic:
                    if self.operation.automatic_pass:
                        self.played = True
                        self.finish('pass')
                        return
                    self.manual_allowed = True
                    self.status.set('Automatic check did not detect enough sound. '
                                    'Record a phrase, then play it back for a manual check.')
                else:
                    self.status.set('Recorded. Play back and listen for your phrase.')
            else:
                self.played = True
                if self.key == 'speaker' and self.combined_pending:
                    self.microphone_needs_manual = not self.operation.automatic_pass
                    if not self.microphone_needs_manual:
                        self.results['microphone'] = 'pass'
                    self.status.set('Playback finished. Microphone: {}. '
                                    'Confirm whether the speakers sounded clear.'.format(
                                        'automatic PASS' if not self.microphone_needs_manual
                                        else 'manual check needed after the speaker decision'))
                else:
                    self.status.set('Playback finished. Confirm what you heard.')
            self._controls()
        except Exception as exc:
            self._error(exc)

    def _error(self, error):
        self.played = False
        self.busy = False
        self.last_error = True
        if self.automatic:
            self.manual_allowed = True
        try:
            self.operation.close()
        except Exception as exc:
            log_event('Audio cleanup failed: {}'.format(exc))
        from services.runtime import log_diagnostic
        log_diagnostic('audio.check_failed', error=error if isinstance(error, Exception) else None,
                       stage='audio', state='error')
        prefix = ('Audio check timed out.' if isinstance(error, TimeoutError)
                  or str(error) == 'Audio device timed out.' else 'Audio error.')
        self.status.set(prefix + ' Retry, record the error, or mark '
                        'Unavailable if verification is not possible.')
        if self.automatic:
            self.status.set('Automatic check could not complete. '
                            'Try again or record and replay a phrase manually.')
        self._controls()

    def finish(self, result):
        if self.closed or (result == 'pass' and (
                not self.played or self.busy or not self.available)):
            return
        self.closed = True
        if self.device_job:
            self.device_job.cancel()
        if self.poll_id is not None:
            self.window.after_cancel(self.poll_id)
            self.poll_id = None
        try:
            self.operation.close()
        except Exception as exc:
            log_event('Audio cleanup failed: {}'.format(exc))
            result = 'error'
        try:
            self.results[self.key] = result
            if self.key == 'speaker' and self.combined_pending and result == 'cancelled':
                self.results['microphone'] = 'cancelled'
            label = self.labels.get(self.key + '_label')
            if label:
                label.config(text=result.upper())
            if self.tests_window:
                self.tests_window.update_icon(self.key)
        finally:
            manual_next = (self.key == 'speaker' and self.combined_pending and
                           self.microphone_needs_manual and result in ('pass', 'fail', 'error'))
            if self.completion_event and not manual_next:
                self.completion_event.set()
            if self.window.winfo_exists():
                self.window.destroy()
            if manual_next:
                AudioTestDialog(self.root, self.results, self.labels, 'microphone',
                                self.tests_window, self.completion_event,
                                manual_fallback=True)

    def cancel(self):
        self.finish('cancelled')

    def _destroyed(self, event):
        if event.widget == self.window and not self.closed:
            self.cancel()


def run_speaker_test(root, test_results, test_labels, tests_window=None,
                     completion_event=None):
    return AudioTestDialog(root, test_results, test_labels, 'speaker',
                           tests_window, completion_event)


def run_microphone_test(root, test_results, test_labels, tests_window=None,
                        completion_event=None):
    return AudioTestDialog(root, test_results, test_labels, 'microphone',
                           tests_window, completion_event)
