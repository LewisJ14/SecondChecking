"""Audio independence, explicit listening and owned-stream cleanup."""

import os
from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from hardwaretests import speaker


class StopCallback(Exception):
    pass


class AudioBackendTests(unittest.TestCase):
    def test_unsupported_sample_rate_converts_on_same_output_endpoint(self):
        import wave
        sample = Path(speaker.__file__).resolve().parents[1] / 'assets' / 'AudioCheck.wav'
        with wave.open(str(sample), 'rb') as audio:
            duration = audio.getnframes() / audio.getframerate()
        backend = self.backend()
        backend.PortAudioError = speaker.sd.PortAudioError
        backend.query_devices.return_value = {'default_samplerate': 48000}
        backend.check_output_settings.side_effect = [speaker.sd.PortAudioError(
            'Invalid sample rate', -9997), None]
        with patch.object(speaker, 'sd', backend):
            operation = speaker.AudioOperation()
            operation.start(8)
            args = backend.OutputStream.call_args.kwargs
            self.assertEqual(args['device'], 8)
            self.assertEqual(args['samplerate'], 48000)
            self.assertEqual(args['channels'], 2)
            self.assertAlmostEqual(operation.expected_frames / 48000, duration, places=4)
            operation.close()

    def test_rate_conversion_preserves_pitch_duration_and_stereo(self):
        for source, target in ((32000, 48000), (48000, 44100)):
            t = np.arange(source) / source
            original = np.column_stack((.5 * np.sin(2 * np.pi * 440 * t),
                                        .25 * np.sin(2 * np.pi * 880 * t)))
            converted = speaker.resample_audio(original, source, target)
            self.assertEqual(converted.shape, (target, 2))
            for channel, frequency, amplitude in ((0, 440, .5), (1, 880, .25)):
                spectrum = abs(np.fft.rfft(converted[:, channel]))
                self.assertEqual(np.argmax(spectrum), frequency)
                self.assertAlmostEqual(float(max(converted[:, channel])), amplitude, places=4)

    def test_unsupported_native_rate_stops_without_switching_device(self):
        backend = self.backend()
        backend.PortAudioError = speaker.sd.PortAudioError
        backend.check_output_settings.side_effect = speaker.sd.PortAudioError('Unsupported')
        with patch.object(speaker, 'sd', backend):
            operation = speaker.AudioOperation()
            with self.assertRaises(speaker.sd.PortAudioError):
                operation.start(8)
        backend.OutputStream.assert_not_called()

    def test_windows_default_endpoints_are_resolved_instead_of_first_devices(self):
        backend = Mock()
        backend.default.device = (0, 0)
        backend.query_devices.return_value = [
            dict(max_input_channels=1, max_output_channels=2),
            dict(max_input_channels=1, max_output_channels=0),
            dict(max_input_channels=0, max_output_channels=2)]
        backend.query_hostapis.return_value = [
            dict(name='MME', default_input_device=0, default_output_device=0),
            dict(name='Windows WASAPI', default_input_device=1, default_output_device=2)]
        with patch.object(speaker, 'sd', backend), patch.object(speaker.sys, 'platform', 'win32'):
            inventory = speaker.audio_device_inventory()
        self.assertEqual(inventory['default_input'], 1)
        self.assertEqual(inventory['default_output'], 2)
        backend.query_hostapis.return_value[-1]['default_input_device'] = -1
        with patch.object(speaker, 'sd', backend), patch.object(speaker.sys, 'platform', 'win32'):
            self.assertIsNone(speaker.audio_device_inventory()['default_input'])
        # Without WASAPI, use PortAudio's configured system defaults, never index zero.
        backend.query_hostapis.return_value = []
        backend.default.device = (1, 2)
        with patch.object(speaker, 'sd', backend):
            self.assertEqual(speaker.audio_device_inventory()['default_output'], 2)

    def test_combined_playback_survives_mic_failure_and_detects_sound(self):
        for mode in ('sound', 'silence', 'input-error', 'no-input'):
            with self.subTest(mode=mode):
                capture, playback = Mock(), Mock()
                for operation in (capture, playback):
                    operation.done.wait.return_value = True
                    operation.error = None
                    operation.frames = operation.expected_frames = 100
                capture.rate = 8000
                capture.recording.return_value = np.full(100, .03 if mode == 'sound' else 0)
                if mode == 'input-error':
                    capture.start.side_effect = RuntimeError('Input unavailable')
                with patch.object(speaker, 'AudioOperation', side_effect=[capture, playback]):
                    audio, reply = speaker.combined_audio_check(
                        None if mode == 'no-input' else 2, 4)
                self.assertEqual(reply['automatic_pass'], mode == 'sound')
                self.assertEqual(bool(reply['microphone_error']),
                                 mode in ('input-error', 'no-input'))
                playback.start.assert_called_once_with(4, level=1.0)
                capture.close.assert_called_once()
                playback.close.assert_called_once()

    def test_automatic_mic_accepts_sound_and_falls_back_for_silence(self):
        for amplitude, expected in ((.03, True), (.006, True), (0, False)):
            with self.subTest(amplitude=amplitude):
                capture, playback = Mock(), Mock()
                for operation in (capture, playback):
                    operation.done.wait.return_value = True
                    operation.error = None
                    operation.frames = operation.expected_frames = 100
                capture.rate = 8000
                capture.recording.return_value = np.full(100, amplitude)
                with patch.object(speaker, 'AudioOperation',
                                  side_effect=[capture, playback]):
                    audio, rate, passed = speaker.automatic_microphone_check(2, 4)
                self.assertEqual(passed, expected)
                self.assertEqual(rate, 8000)
                capture.start.assert_called_once_with(2, recording=True)
                playback.start.assert_called_once_with(4, level=1.0)
                capture.close.assert_called_once()
                playback.close.assert_called_once()

    def test_automatic_mic_error_closes_both_streams(self):
        capture, playback = Mock(), Mock()
        playback.start.side_effect = RuntimeError('Output unavailable')
        with patch.object(speaker, 'AudioOperation',
                          side_effect=[capture, playback]):
            with self.assertRaisesRegex(RuntimeError, 'Output unavailable'):
                speaker.automatic_microphone_check(2, 4)
        capture.close.assert_called_once()
        playback.close.assert_called_once()

    def test_original_sample_preserves_stereo_and_sample_rate(self):
        import wave
        sample = Path(speaker.__file__).resolve().parents[1] / 'assets' / 'AudioCheck.wav'
        with wave.open(str(sample), 'rb') as audio:
            expected = np.frombuffer(audio.readframes(audio.getnframes()),
                                     dtype='<i2').reshape(-1, 2) / 32768.0
        backend = self.backend()
        with patch.object(speaker, 'sd', backend):
            operation = speaker.AudioOperation()
            operation.start(12)
            args = backend.OutputStream.call_args.kwargs
            self.assertEqual(args['samplerate'], 32000)
            self.assertEqual(args['channels'], 2)
            output = np.zeros(expected.shape, dtype='float32')
            with self.assertRaises(StopCallback):
                args['callback'](output, len(output), None, False)
            np.testing.assert_allclose(output, expected, atol=1e-7)
            operation.close()

    def backend(self):
        backend = Mock()
        backend.CallbackStop = StopCallback
        backend.query_devices.return_value = {'default_samplerate': 8000}
        return backend

    def test_playback_explicit_device_attenuation_and_cleanup(self):
        backend = self.backend()
        with patch.object(speaker, 'sd', backend):
            operation = speaker.AudioOperation()
            operation.start(12, data=np.ones(5), rate=8000, level=1)
            args = backend.OutputStream.call_args.kwargs
            self.assertEqual(args['device'], 12)
            output = np.ones((8, 1), dtype='float32')
            with self.assertRaises(StopCallback):
                args['callback'](output, 8, None, False)
            np.testing.assert_allclose(output[:5], 1.0)
            np.testing.assert_array_equal(output[5:], 0)
            operation.close()
            operation.close()
            backend.OutputStream.return_value.abort.assert_called_once()
            backend.OutputStream.return_value.close.assert_called_once()
            backend.stop.assert_not_called()
            self.assertNotIn('default', backend._mock_children)

    def test_capture_is_bounded_noise_never_decides_a_result(self):
        backend = self.backend()
        with patch.object(speaker, 'sd', backend):
            operation = speaker.AudioOperation()
            operation.start(6, recording=True)
            args = backend.InputStream.call_args.kwargs
            self.assertEqual(args['device'], 6)
            noise = np.full((40000, 1), .9, dtype='float32')
            with self.assertRaises(StopCallback):
                args['callback'](noise, len(noise), None, False)
            self.assertEqual(len(operation.recording()), 32000)
            self.assertFalse(hasattr(operation, 'passed'))
            operation.close()

    def test_failed_start_and_abort_still_close_stream(self):
        backend = self.backend()
        backend.OutputStream.return_value.start.side_effect = RuntimeError(
            'busy')
        with patch.object(speaker, 'sd', backend):
            operation = speaker.AudioOperation()
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                operation.start(1)
            backend.OutputStream.return_value.close.assert_called_once()
            operation.stream = Mock()
            stream = operation.stream
            stream.abort.side_effect = RuntimeError('gone')
            with self.assertRaisesRegex(RuntimeError, 'gone'):
                operation.close()
            stream.close.assert_called_once()


class AudioDialogTests(unittest.TestCase):
    def test_hidden_tk_audio_controls(self):
        if os.environ.get('SECOND_CHECK_AUDIO_UI_CHILD') != '1':
            environment = dict(os.environ, SECOND_CHECK_AUDIO_UI_CHILD='1')
            child = subprocess.run(
                [sys.executable, __file__, 'AudioDialogTests'],
                env=environment, capture_output=True, text=True, timeout=45)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        root = tk.Tk()
        root.withdraw()
        backend = Mock()
        backend.query_devices.return_value = [
            {'name': 'Built-in speakers', 'max_input_channels': 0,
             'max_output_channels': 2},
            {'name': 'Built-in mic', 'max_input_channels': 1,
             'max_output_channels': 0},
            {'name': 'USB audio', 'max_input_channels': 1,
             'max_output_channels': 2}]
        class DevicePoller:
            def __init__(self, root, kind, callback, **kwargs):
                try:
                    devices = backend.query_devices()
                except Exception as exc:
                    callback(dict(state='error', detail=str(exc)))
                else:
                    callback(dict(state='complete', devices=devices, default_input=2, default_output=2))
            def cancel(self):
                pass

        try:
            with patch.object(speaker, 'JobPoller', DevicePoller):
                results = {'speaker': 'n/a', 'microphone': 'fail'}
                event = threading.Event()
                dialog = speaker.run_speaker_test(
                    root, results, {}, completion_event=event)
                dialog.window.withdraw()
                dialog.finish('pass')
                self.assertFalse(event.is_set())
                self.assertTrue(dialog.pass_button.instate(['disabled']))
                with patch.object(dialog.operation, 'start') as start:
                    dialog.play_button.invoke()
                    self.assertEqual(start.call_args.args[0], 2)
                    self.assertEqual(start.call_args.kwargs['level'], 1.0)
                    self.assertTrue(dialog.busy)
                    self.assertTrue(dialog.pass_button.instate(['disabled']))
                dialog.window.after_cancel(dialog.poll_id)
                # Completing playback only enables a decision; never auto-pass.
                dialog.operation.done.set()
                dialog.operation.automatic_pass = True
                dialog._poll(False)
                self.assertEqual(results['speaker'], 'n/a')
                self.assertTrue(dialog.pass_button.instate(['!disabled']))
                dialog.pass_button.invoke()
                self.assertTrue(event.is_set())
                self.assertEqual(
                    results, {'speaker': 'pass', 'microphone': 'pass',
                              '_history_unknown': [], '_provenance_unknown': False})
                results.clear()
                results.update(speaker='pass', microphone='fail')

                # A failed combined attempt opens manual mic fallback only
                # after the independent speaker decision, keeping the run open.
                event.clear()
                dialog = speaker.run_speaker_test(root, results, {}, completion_event=event)
                with patch.object(dialog.operation, 'start') as start:
                    dialog.play_button.invoke()
                    self.assertTrue(start.call_args.kwargs['combined'])
                    self.assertEqual(start.call_args.kwargs['input_device'], 2)
                dialog.window.after_cancel(dialog.poll_id)
                dialog.operation.done.set()
                dialog._poll(False)
                with patch.object(speaker, 'AudioTestDialog') as fallback:
                    dialog.pass_button.invoke()
                self.assertFalse(event.is_set())
                self.assertTrue(fallback.call_args.kwargs['manual_fallback'])
                manual = speaker.AudioTestDialog(
                    root, results, {}, 'microphone', completion_event=event,
                    manual_fallback=True)
                self.assertTrue(manual.record_button.instate(['!disabled']))
                manual.played = True
                manual.finish('pass')
                self.assertTrue(event.is_set())
                self.assertEqual(results['speaker'], 'pass')
                self.assertEqual(results['microphone'], 'pass')
                results.clear()
                results.update(speaker='pass', microphone='fail')

                dialog = speaker.run_microphone_test(root, results, {})
                dialog.window.withdraw()
                # Loud noise is recorded, but cannot enable pass before replay.
                dialog.operation.audio = np.ones(1000)
                dialog.operation.done.set()
                dialog._poll(True)
                self.assertTrue(dialog.pass_button.instate(['disabled']))
                self.assertEqual(results['microphone'], 'fail')
                dialog.operation.done.set()
                dialog._poll(False)
                self.assertTrue(dialog.pass_button.instate(['!disabled']))
                dialog.output_choice.set('0: Built-in speakers')
                dialog.changed()
                self.assertTrue(dialog.pass_button.instate(['disabled']))
                self.assertIsNone(dialog.audio)
                dialog.fail_button.invoke()
                self.assertEqual(
                    results, {'speaker': 'pass', 'microphone': 'fail'})

                # Cancel during an active operation releases only its stream.
                event.clear()
                dialog = speaker.run_speaker_test(
                    root, results, {}, completion_event=event)
                stream = Mock()
                dialog.operation.job = stream
                dialog.busy = True
                root.tk.call(dialog.window.protocol('WM_DELETE_WINDOW'))
                stream.close.assert_called_once()
                stream.close.assert_called_once()
                self.assertTrue(event.is_set())
                self.assertEqual(results['speaker'], 'cancelled')
                self.assertEqual(results['microphone'], 'fail')

                # A stalled/failed stream cannot enable Pass; cleanup on error.
                dialog = speaker.run_speaker_test(root, results, {})
                dialog.operation.job = Mock()
                stream = dialog.operation.job
                stream.poll.return_value = None
                dialog.busy = True
                dialog.operation.deadline = 0
                dialog._poll(False)
                self.assertIn('timed out', dialog.status.get())
                stream.close.assert_called_once()
                self.assertTrue(dialog.pass_button.instate(['disabled']))
                dialog.error_button.invoke()
                self.assertEqual(results['speaker'], 'error')
                self.assertEqual(results['microphone'], 'fail')

                # Automatic sound detection passes only the microphone.
                dialog = speaker.run_microphone_test(root, results, {})
                self.assertTrue(dialog.record_button.instate(['disabled']))
                with patch.object(dialog.operation, 'start') as start:
                    dialog.auto_button.invoke()
                    self.assertEqual(start.call_args.args[0], 2)
                    self.assertEqual(start.call_args.kwargs['automatic_output'], 2)
                dialog.window.after_cancel(dialog.poll_id)
                dialog.operation.audio = np.ones(1000)
                dialog.operation.automatic_pass = True
                dialog.operation.done.set()
                dialog._poll(True)
                self.assertEqual(results['microphone'], 'pass')
                self.assertEqual(results['speaker'], 'error')

                # Silence leaves the result unchanged and enables manual fallback.
                dialog = speaker.run_microphone_test(root, results, {})
                with patch.object(dialog.operation, 'start'):
                    dialog.auto_button.invoke()
                dialog.window.after_cancel(dialog.poll_id)
                dialog.operation.audio = np.zeros(1000)
                dialog.operation.done.set()
                dialog._poll(True)
                self.assertEqual(results['microphone'], 'pass')
                self.assertTrue(dialog.record_button.instate(['!disabled']))
                self.assertTrue(dialog.pass_button.instate(['disabled']))
                self.assertIn('did not detect', dialog.status.get())
                dialog._error('Disconnected')
                self.assertTrue(dialog.record_button.instate(['!disabled']))
                dialog.cancel()

                # Missing output does not classify the microphone as failed.
                backend.query_devices.return_value = []
                dialog = speaker.run_microphone_test(root, results, {})
                self.assertFalse(dialog.available)
                self.assertTrue(dialog.play_button.instate(['disabled']))
                dialog.finish('unavailable')
                self.assertEqual(results['microphone'], 'unavailable')
                self.assertEqual(results['speaker'], 'error')

                backend.query_devices.side_effect = RuntimeError('PortAudio')
                dialog = speaker.run_speaker_test(root, results, {})
                self.assertIn('unavailable', dialog.status.get())
                self.assertNotIn('PortAudio', dialog.status.get())
                dialog.cancel()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
