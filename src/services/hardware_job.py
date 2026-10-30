"""Owned, killable native I/O jobs. Children never touch the Tk application."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time


_MISSING = object()
_READ_PENDING = object()
FILE_ACCESS_RETRY_SECONDS = 1.0


class WorkerResultTooLarge(ValueError):
    pass


class HardwareJob:
    max_result_bytes = None

    def __init__(self, kind, arguments=None, timeout=20, audio=None,
                 worker_flag="--hardware-worker", command_factory=None, environment=None):
        self.directory = Path(tempfile.mkdtemp(prefix='secondchecking-hardware-'))
        self.process = None
        self.process_group = None
        self.kind = kind
        self.operation_timeout = timeout
        self.awaiting_startup = command_factory is None
        self.deadline = time.monotonic() + (30 if self.awaiting_startup else timeout)
        self.cleanup_complete = threading.Event()
        self.closed = False
        self._blocked_reads = {}
        try:
            (self.directory / 'request.json').write_text(json.dumps({
                'kind': kind, 'arguments': arguments or {}}), encoding='utf-8')
            if audio is not None:
                import numpy as np
                np.save(str(self.directory / 'input.npy'), audio,
                        allow_pickle=False)
            command = [sys.executable]
            if not getattr(sys, 'frozen', False):
                command.append(str(Path(__file__).resolve().parents[1] / 'main.py'))
            command += [worker_flag, str(self.directory)]
            if command_factory is not None:
                command = command_factory(self.directory)
            child_environment = (dict(os.environ) if environment is None
                                 else dict(environment))
            if command_factory is None and getattr(sys, 'frozen', False):
                # PyInstaller <6.9 clears this before entering Python. Restore it
                # only for owned workers so they reuse our unpacked runtime.
                # Newer bootloaders inherit their own worker metadata as usual.
                unpacked = getattr(sys, '_MEIPASS', None)
                if unpacked:
                    child_environment['_MEIPASS2'] = str(unpacked)
                child_environment.pop('PYINSTALLER_RESET_ENVIRONMENT', None)
            elif command_factory is not None:
                # Independent update probes must unpack separately, but only
                # inside this job's directory, which we own after termination.
                runtime = self.directory / 'runtime'
                runtime.mkdir()
                child_environment.update(TEMP=str(runtime), TMP=str(runtime))
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            if os.name == 'nt':
                # Attach ownership before any child code can spawn descendants.
                creationflags |= 0x00000004  # Windows CREATE_SUSPENDED
            self.process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=child_environment,
                creationflags=creationflags)
            if os.name == 'nt' and isinstance(getattr(self.process, '_handle', None), int):
                import win32job
                group = win32job.CreateJobObject(None, '')
                try:
                    limits = win32job.QueryInformationJobObject(
                        group, win32job.JobObjectExtendedLimitInformation)
                    limits['BasicLimitInformation']['LimitFlags'] |= (
                        win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
                    win32job.SetInformationJobObject(
                        group, win32job.JobObjectExtendedLimitInformation, limits)
                    win32job.AssignProcessToJobObject(group, int(self.process._handle))
                    self.process_group = group
                    import psutil
                    psutil.Process(self.process.pid).resume()
                except Exception:
                    group.Close()
                    self.process_group = None
                    if self.process.poll() is None:
                        raise
        except Exception:
            self.close()
            raise

    def _check_deadline(self):
        if time.monotonic() > self.deadline:
            self.close()
            raise TimeoutError('Hardware worker startup timed out.' if self.awaiting_startup
                               else 'Hardware operation timed out.')

    def _read_message(self, filename):
        """Retry sharing/access failures across polls, never by sleeping on Tk."""
        path = self.directory / filename
        try:
            if filename == 'result.json' and self.max_result_bytes is not None:
                with path.open('rb') as stream:
                    content = stream.read(self.max_result_bytes + 1)
                if len(content) > self.max_result_bytes:
                    raise WorkerResultTooLarge('Helper result exceeds the size limit.')
                content = content.decode('utf-8')
            else:
                content = path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return _MISSING
        except OSError as exc:
            if not isinstance(exc, PermissionError) and getattr(exc, 'winerror', None) not in (32, 33):
                raise
            now = time.monotonic()
            limit = self._blocked_reads.setdefault(filename, now + FILE_ACCESS_RETRY_SECONDS)
            if now >= limit:
                label = 'startup acknowledgement' if filename == 'ready.json' else 'result'
                raise RuntimeError('The check could not read its {}. '
                                   'Access stayed unavailable; retry the check.'.format(label)) from exc
            return _READ_PENDING
        self._blocked_reads.pop(filename, None)
        return json.loads(content)

    def poll(self):
        if self.closed:
            return None
        self._check_deadline()
        reply = self._read_message('result.json')
        if reply is not _MISSING and reply is not _READ_PENDING:
            self._check_deadline()
            if self.kind == 'camera' and reply.get('state') == 'preview':
                frames = reply.get('frames_seen')
                heartbeat = reply.get('heartbeat')
                if (type(frames) is not int or frames < 1
                        or type(heartbeat) not in (int, float)
                        or not 0 <= time.time() - heartbeat <= 5):
                    raise RuntimeError('Camera stopped returning fresh frames.')
                if frames > getattr(self, '_camera_frames_seen', 0):
                    self._camera_frames_seen = frames
                    self.awaiting_startup = False
                    self.deadline = time.monotonic() + 5
            return reply
        if self.awaiting_startup:
            message = self._read_message('ready.json')
            if message is not _MISSING and message is not _READ_PENDING:
                self._check_deadline()
                if message != {'worker_ready_version': 1, 'kind': self.kind}:
                    raise RuntimeError('Hardware worker returned invalid startup acknowledgement.')
                self.awaiting_startup = False
                self.deadline = time.monotonic() + self.operation_timeout
        self._check_deadline()
        if reply is _READ_PENDING:
            # A finished worker can still have a briefly inaccessible final file.
            return None
        if self.process.poll() is not None:
            # The worker may have published its final file after our first read.
            reply = self._read_message('result.json')
            self._check_deadline()
            if reply is _READ_PENDING:
                return None
            if reply is not _MISSING:
                return reply
            raise RuntimeError('Hardware worker exited without a result.')
        return None

    def close(self):
        if self.closed:
            return
        self.closed = True
        process = self.process
        group, self.process_group = self.process_group, None
        completed = (self.directory / 'result.json').exists()

        def terminate():
            nonlocal group
            if group is not None:
                group.Close()
                group = None
            elif process is not None and process.poll() is None:
                process.terminate()

        if not completed:
            terminate()

        def reap():
            try:
                if process is not None:
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        terminate()
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=2)
            finally:
                # Completed one-file helpers get a bounded normal exit before
                # their group is closed. Cancellation still terminates at once.
                terminate()
                target = self.directory.resolve()
                temporary_root = Path(tempfile.gettempdir()).resolve()
                if (target.parent == temporary_root
                        and target.name.startswith('secondchecking-hardware-')):
                    for attempt in range(30):
                        try:
                            shutil.rmtree(str(target))
                            break
                        except FileNotFoundError:
                            break
                        except OSError:
                            time.sleep(.1)
                self.cleanup_complete.set()

        threading.Thread(target=reap, daemon=True).start()


def write_result(directory, value):
    temporary = directory / 'result.tmp'
    temporary.write_text(json.dumps(value), encoding='utf-8')
    replace_file(temporary, directory / 'result.json')


def write_ready(directory, kind):
    directory = Path(directory)
    temporary = directory / 'ready.tmp'
    temporary.write_text(json.dumps({'worker_ready_version': 1, 'kind': kind}),
                         encoding='utf-8')
    replace_file(temporary, directory / 'ready.json')


def replace_file(source, destination):
    # Windows may briefly hold a reader's file handle without delete sharing.
    for attempt in range(20):
        try:
            os.replace(str(source), str(destination))
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.005)


class JobPoller:
    """Poll IPC on Tk; every native call happens inside the owned process."""

    def __init__(self, root, kind, callback, timeout=20, arguments=None,
                 audio=None):
        self.root, self.callback = root, callback
        self.closed, self.after_id, self.job = False, None, None
        self.destroy_binding = None
        try:
            self.job = HardwareJob(kind, arguments, timeout, audio)
        except Exception as exc:
            self.error = str(exc)
        else:
            self.error = None
        try:
            self.after_id = root.after(30, self.poll)
            self.destroy_binding = root.bind('<Destroy>', self.destroyed, add='+')
        except Exception:
            if self.job:
                self.job.close()
            raise

    def destroyed(self, event):
        if event.widget == self.root:
            self.cancel()

    def poll(self):
        self.after_id = None
        if self.closed:
            return
        try:
            if self.error:
                raise RuntimeError(self.error)
            reply = self.job.poll()
        except Exception as exc:
            reply = dict(state='error', detail=str(exc))
        if reply is None:
            self.after_id = self.root.after(30, self.poll)
            return
        try:
            self.callback(reply)
        finally:
            self.cancel()

    def cancel(self):
        if self.closed:
            return
        self.closed = True
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        if self.job is not None:
            self.job.close()
        if self.destroy_binding and self.root.winfo_exists():
            self.root.unbind('<Destroy>', self.destroy_binding)
        self.destroy_binding = None


def run_worker(directory):
    directory = Path(directory)
    try:
        request = json.loads((directory / 'request.json').read_text(encoding='utf-8'))
        kind, args = request['kind'], request['arguments']
        write_ready(directory, kind)
        if kind == 'wifi':
            from hardwaretests.wifi import check_wifi_status
            state, detail, interfaces = check_wifi_status()
            result = dict(state=state, detail=detail, interfaces=interfaces)
        elif kind == 'usb':
            from hardwaretests.usb import removable_volumes
            result = dict(state='complete', volumes=sorted(removable_volumes()))
        elif kind == 'audio-devices':
            from hardwaretests.speaker import audio_device_inventory
            result = audio_device_inventory()
        elif kind == 'audio-combined':
            import numpy as np
            from hardwaretests.speaker import combined_audio_check
            audio, result = combined_audio_check(**args)
            if audio is not None:
                np.save(str(directory / 'recording.npy'), audio, allow_pickle=False)
        elif kind == 'audio-auto':
            import numpy as np
            from hardwaretests.speaker import automatic_microphone_check
            audio, rate, passed = automatic_microphone_check(**args)
            np.save(str(directory / 'recording.npy'), audio, allow_pickle=False)
            result = dict(state='complete', rate=rate, automatic_pass=passed)
        elif kind == 'audio':
            import numpy as np
            from hardwaretests.speaker import AudioOperation
            operation = AudioOperation()
            try:
                audio = directory / 'input.npy'
                data = np.load(str(audio), allow_pickle=False) if audio.exists() else None
                operation.start(data=data, **args)
                while not operation.done.wait(.05):
                    if time.monotonic() > operation.deadline:
                        raise TimeoutError('Audio stream timed out.')
                if operation.error or operation.frames != operation.expected_frames:
                    raise RuntimeError(operation.error or 'Incomplete audio stream.')
                if args.get('recording'):
                    np.save(str(directory / 'recording.npy'),
                            operation.recording(), allow_pickle=False)
                result = dict(state='complete', rate=operation.rate)
            finally:
                operation.close()
        elif kind == 'camera':
            camera_worker(directory)
            return
        elif kind == 'activation':
            from utils.helpers import check_activation_status
            subprocess.run(['cscript.exe', '//Nologo',
                            r'C:\Windows\System32\slmgr.vbs', '/ato'],
                           capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            result = dict(state='pass' if check_activation_status() else 'fail')
        elif kind == 'product-key':
            reply = subprocess.run([
                'powershell', '-NoProfile', '-NonInteractive', '-Command',
                '(Get-CimInstance SoftwareLicensingService).OA3xOriginalProductKey'],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            key = reply.stdout.strip()
            if reply.returncode or not key:
                raise RuntimeError('No product key returned.')
            result = dict(state='complete', key=key)
        elif kind == 'battery-live':
            from utils.helpers import get_battery_bar_state
            result = dict(state='complete', battery=get_battery_bar_state())
        else:
            raise ValueError('Unknown hardware job.')
        write_result(directory, result)
    except Exception as exc:
        from services.runtime import log_diagnostic
        log_diagnostic('hardware.worker_failed', error=exc,
                       kind=locals().get('kind', 'unknown'), stage='native_io')
        write_result(directory, dict(state='error', detail=str(exc)[:1000]))


def camera_worker(directory):
    import cv2
    capture = None
    try:
        for index in range(10):
            capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            ret, frame = capture.read()
            if ret:
                break
            capture.release()
            capture = None
        else:
            write_result(directory, dict(state='unavailable',
                         detail='No readable camera. Check privacy, drivers and connection.'))
            return
        frames = 0
        while ret:
            height, width = frame.shape[:2]
            scale = min(1, 640 / width, 420 / height)
            if scale < 1:
                frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
            ok, jpeg = cv2.imencode('.jpg', frame)
            if not ok:
                raise RuntimeError('Could not encode camera frame.')
            temporary = directory / 'frame.tmp'
            temporary.write_bytes(jpeg.tobytes())
            replace_file(temporary, directory / 'frame.jpg')
            frames += 1
            write_result(directory, dict(state='preview', camera_index=index,
                                        frames_seen=frames, heartbeat=time.time()))
            time.sleep(.06)
            ret, frame = capture.read()
        write_result(directory, dict(state='unavailable',
                     detail='Camera stopped returning live frames.'))
    finally:
        if capture is not None:
            capture.release()
