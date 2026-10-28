"""Regression coverage for startup budgets and owned frozen-runtime cleanup."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.hardware_job import HardwareJob, write_ready, write_result
from services import app_helper


@contextmanager
def deny_reads(path):
    import win32file
    import win32con
    handle = win32file.CreateFile(str(path), win32con.GENERIC_READ, 0, None,
                                  win32con.OPEN_EXISTING, 0, None)
    try:
        yield
    finally:
        handle.Close()


class WorkerRuntimeTests(unittest.TestCase):
    def mock_job(self, helper=False, timeout=2):
        process = Mock()
        process.poll.return_value = None
        with patch('services.hardware_job.subprocess.Popen', return_value=process):
            return (app_helper.AppHelperJob('updates', timeout) if helper
                    else HardwareJob('test', timeout=timeout))

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing semantics')
    def test_persistent_access_failure_has_one_budget_without_sleeping_on_tk(self):
        for filename in ('ready.json', 'result.json'):
            job = self.mock_job()
            job.deadline = 200
            write_ready(job.directory, 'test') if filename == 'ready.json' else write_result(
                job.directory, {'state': 'complete'})
            try:
                with deny_reads(job.directory / filename), \
                        patch('services.hardware_job.time.monotonic', return_value=100) as clock, \
                        patch('services.hardware_job.time.sleep') as sleep:
                    self.assertIsNone(job.poll())
                    clock.return_value = 100.6
                    self.assertIsNone(job.poll())
                    clock.return_value = 101.01
                    with self.assertRaisesRegex(RuntimeError, 'Access stayed unavailable'):
                        job.poll()
                    self.assertEqual(job.deadline, 200)
                    sleep.assert_not_called()
            finally:
                job.close()
                self.assertTrue(job.cleanup_complete.wait(5))

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing semantics')
    def test_startup_and_operation_deadlines_win_over_file_access_retry(self):
        for acknowledged in (False, True):
            job = self.mock_job(timeout=.2)
            job.deadline = 200
            try:
                write_ready(job.directory, 'test')
                with patch('services.hardware_job.time.monotonic', return_value=100) as clock:
                    if acknowledged:
                        self.assertIsNone(job.poll())
                        self.assertFalse(job.awaiting_startup)
                        write_result(job.directory, {'state': 'complete'})
                        filename = 'result.json'
                    else:
                        job.deadline = 100.2
                        filename = 'ready.json'
                    with deny_reads(job.directory / filename):
                        self.assertIsNone(job.poll())
                        clock.return_value = 100.3
                        with self.assertRaisesRegex(TimeoutError,
                                'operation timed out' if acknowledged else 'startup timed out'):
                            job.poll()
                        self.assertTrue(job.closed)
                self.assertTrue(job.cleanup_complete.wait(5))
            finally:
                job.close()

    def test_malformed_messages_are_not_treated_as_file_access_failures(self):
        for filename, content, error in (
                ('ready.json', '{bad', json.JSONDecodeError),
                ('ready.json', '{"wrong":"identity"}', RuntimeError),
                ('result.json', '{bad', json.JSONDecodeError)):
            job = self.mock_job()
            try:
                (job.directory / filename).write_text(content, encoding='utf-8')
                with self.assertRaises(error):
                    job.poll()
            finally:
                job.close()
                self.assertTrue(job.cleanup_complete.wait(5))

    def test_exit_race_rechecks_a_result_published_after_the_first_read(self):
        job = self.mock_job()
        def exit_after_publication():
            write_result(job.directory, {'state': 'complete'})
            job.process.poll.side_effect = None
            job.process.poll.return_value = 0
            return 0
        job.process.poll.side_effect = exit_after_publication
        try:
            self.assertEqual(job.poll(), {'state': 'complete'})
        finally:
            job.close()
            self.assertTrue(job.cleanup_complete.wait(5))

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing semantics')
    def test_helper_size_limit_is_enforced_after_a_locked_result_recovers(self):
        job = self.mock_job(helper=True)
        try:
            write_result(job.directory, {'content': 'x' * app_helper.MAX_RESULT_BYTES})
            with deny_reads(job.directory / 'result.json'):
                self.assertIsNone(job.poll())
            with self.assertRaisesRegex(app_helper.HelperError, 'size limit'):
                job.poll()
        finally:
            job.close()
            self.assertTrue(job.cleanup_complete.wait(5))

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing semantics')
    def test_locked_ack_and_result_recover_without_losing_an_exited_result(self):
        import win32file
        import win32con
        process = Mock()
        process.poll.return_value = None
        with patch('services.hardware_job.subprocess.Popen', return_value=process):
            job = HardwareJob('test', timeout=2)
        handle = None
        try:
            write_ready(job.directory, 'test')
            handle = win32file.CreateFile(str(job.directory / 'ready.json'),
                win32con.GENERIC_READ, 0, None, win32con.OPEN_EXISTING, 0, None)
            startup_deadline = job.deadline
            self.assertIsNone(job.poll())
            self.assertTrue(job.awaiting_startup)
            self.assertEqual(job.deadline, startup_deadline)
            handle.Close()
            handle = None
            self.assertIsNone(job.poll())
            self.assertFalse(job.awaiting_startup)
            write_result(job.directory, {'state': 'complete'})
            handle = win32file.CreateFile(str(job.directory / 'result.json'),
                win32con.GENERIC_READ, 0, None, win32con.OPEN_EXISTING, 0, None)
            process.poll.return_value = 0
            self.assertIsNone(job.poll())
            handle.Close()
            handle = None
            self.assertEqual(job.poll(), {'state': 'complete'})
        finally:
            if handle is not None:
                handle.Close()
            job.close()
            self.assertTrue(job.cleanup_complete.wait(5))

    def test_frozen_workers_reuse_parent_without_mutating_process_environment(self):
        process = Mock()
        process.poll.return_value = 0
        with tempfile.TemporaryDirectory() as unpacked, \
                patch.object(sys, 'frozen', True, create=True), \
                patch.object(sys, '_MEIPASS', unpacked, create=True), \
                patch.dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'), \
                patch('services.hardware_job.subprocess.Popen', return_value=process) as launch:
            job = HardwareJob('wifi')
            try:
                child = launch.call_args.kwargs['env']
                self.assertEqual(child['_MEIPASS2'], unpacked)
                self.assertNotIn('PYINSTALLER_RESET_ENVIRONMENT', child)
                self.assertEqual(os.environ['PYINSTALLER_RESET_ENVIRONMENT'], '1')
                self.assertTrue(Path(unpacked).is_dir())
            finally:
                job.close()
                self.assertTrue(job.cleanup_complete.wait(5))
            self.assertTrue(Path(unpacked).is_dir())

    def test_startup_delay_does_not_consume_native_operation_budget(self):
        real_popen = subprocess.Popen
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'worker.py'
            script.write_text(
                'import json, sys, time\nfrom pathlib import Path\n'
                'p=Path(sys.argv[-1])\ntime.sleep(.3)\n'
                '(p/"ready.tmp").write_text(json.dumps('
                '{"worker_ready_version":1,"kind":"test"}))\n'
                '(p/"ready.tmp").replace(p/"ready.json")\n'
                'time.sleep(.05)\n'
                '(p/"result.tmp").write_text(json.dumps({"state":"complete"}))\n'
                '(p/"result.tmp").replace(p/"result.json")\n',
                encoding='utf-8')
            with patch('services.hardware_job.subprocess.Popen', side_effect=
                       lambda command, **kw: real_popen(
                           [sys.executable, str(script), command[-1]], **kw)):
                job = HardwareJob('test', timeout=.2)
            started = time.monotonic()
            try:
                reply = None
                while reply is None and time.monotonic() - started < 5:
                    reply = job.poll()
                    time.sleep(.01)
                self.assertEqual(reply, {'state': 'complete'})
                self.assertGreater(time.monotonic() - started, .3)
            finally:
                job.close()
                self.assertTrue(job.cleanup_complete.wait(5))

    def test_acknowledged_worker_still_has_a_bounded_operation(self):
        process = Mock()
        process.poll.return_value = None
        with patch('services.hardware_job.subprocess.Popen', return_value=process):
            job = HardwareJob('test', timeout=.01)
        try:
            write_ready(job.directory, 'test')
            self.assertIsNone(job.poll())
            self.assertFalse(job.awaiting_startup)
            job.deadline = 0
            with self.assertRaisesRegex(TimeoutError, 'operation timed out'):
                job.poll()
            process.terminate.assert_called()
        finally:
            job.close()
            self.assertTrue(job.cleanup_complete.wait(5))

    def test_independent_probe_unpack_files_are_removed_after_forced_timeout(self):
        with tempfile.TemporaryDirectory() as outside:
            sentinel = Path(outside) / 'keep'
            sentinel.write_text('unrelated')
            job = HardwareJob('independent', command_factory=lambda directory: [
                sys.executable, '-c',
                'import os,time;from pathlib import Path;'
                '(Path(os.environ["TEMP"])/"unpacked.dll").write_bytes(b"x"*8192);'
                'time.sleep(30)'])
            target = job.directory
            try:
                deadline = time.monotonic() + 5
                while not (target / 'runtime/unpacked.dll').exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((target / 'runtime/unpacked.dll').exists())
                job.deadline = 0
                with self.assertRaises(TimeoutError):
                    job.poll()
                self.assertTrue(job.cleanup_complete.wait(6))
                self.assertFalse(target.exists())
                self.assertEqual(sentinel.read_text(), 'unrelated')
            finally:
                job.close()


if __name__ == '__main__':
    unittest.main()
