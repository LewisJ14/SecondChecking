"""Cancellation, stale callbacks, runner summaries and killable workers."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services import hardware_job
from ui.tests import TestsWindow
import ui.tests as test_panel
import app_controller
from ui.tests import TestRun
from services.check_results import start_measurement, record_override


from operator_fixture import sign_in as setUpModule, sign_out as tearDownModule


class CombinedAudioCommitTests(unittest.TestCase):
    def test_both_results_commit_without_repeating_microphone_in_run_all(self):
        panel = SimpleNamespace(test_results=dict(speaker='n/a', microphone='fail'),
                                _attempted=['speaker'], _total=3,
                                _queue=[('microphone', Mock()), ('display', Mock())],
                                update_icon=Mock())
        record_override(panel.test_results, 'microphone', 'pass', 'tester', 'Test reason')
        run = TestRun(panel, 'speaker')
        start_measurement(run.results, 'microphone')
        run.results.update(speaker='fail', microphone='pass',
                           _combined_microphone_attempted=True)
        TestsWindow._commit_run(panel, run)
        self.assertEqual(panel.test_results['speaker'], 'fail')
        self.assertEqual(panel.test_results['microphone'], 'pass')
        self.assertFalse(panel.test_results['_overrides']['microphone'][-1]['active'])
        self.assertEqual(panel._attempted, ['speaker', 'microphone'])
        self.assertEqual([key for key, _ in panel._queue], ['display'])
        self.assertEqual(panel._total, 3)
        self.assertNotIn('_combined_microphone_attempted', panel.test_results)


class HardwareJobTests(unittest.TestCase):
    def test_real_child_dispatch_without_launching_desktop(self):
        job = hardware_job.HardwareJob('unknown-test-command', timeout=10)
        try:
            deadline = time.monotonic() + 10
            reply = None
            while reply is None and time.monotonic() < deadline:
                reply = job.poll()
                time.sleep(.02)
            self.assertEqual(reply['state'], 'error')
            self.assertIn('Unknown hardware job', reply['detail'])
        finally:
            job.close()
        job.process.wait(timeout=3)

    def test_stalled_process_is_terminated_on_timeout(self):
        real_popen = subprocess.Popen

        def sleeper(command, **kwargs):
            return real_popen([sys.executable, '-c',
                               'import time; time.sleep(30)'], **kwargs)
        with patch.object(hardware_job.subprocess, 'Popen', side_effect=sleeper):
            job = hardware_job.HardwareJob('unused')
        job.deadline = 0
        with self.assertRaises(TimeoutError):
            job.poll()
        self.assertTrue(job.closed)
        job.process.wait(timeout=3)
        self.assertIsNotNone(job.process.returncode)
        job.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows process-tree ownership')
    def test_cancel_terminates_owned_descendants(self):
        import win32api
        import win32event
        import win32job
        real_popen = subprocess.Popen
        real_assign = win32job.AssignProcessToJobObject

        def delayed_assign(*args):
            # An immediate spawner must not escape while ownership is attached.
            time.sleep(.3)
            return real_assign(*args)
        with tempfile.TemporaryDirectory() as directory:
            script, pid_file = Path(directory) / 'spawn.py', Path(directory) / 'pid'
            script.write_text(
                'import subprocess, sys, time\n'
                'from pathlib import Path\n'
                'p = subprocess.Popen([sys.executable, "-c", '
                '"import time; time.sleep(30)"])\n'
                'Path(sys.argv[1]).write_text(str(p.pid))\n'
                'time.sleep(30)\n', encoding='utf-8')
            with patch.object(hardware_job.subprocess, 'Popen',
                              side_effect=lambda command, **kw: real_popen(
                                  [sys.executable, str(script), str(pid_file)], **kw)), \
                    patch.object(win32job, 'AssignProcessToJobObject', side_effect=delayed_assign):
                job = hardware_job.HardwareJob('unused')
            handle = None
            try:
                deadline = time.monotonic() + 5
                while not pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(pid_file.exists())
                handle = win32api.OpenProcess(0x00100000, False,
                                             int(pid_file.read_text()))
                job.close()
                self.assertEqual(win32event.WaitForSingleObject(handle, 3000), 0)
            finally:
                job.close()
                job.process.wait(timeout=3)
                if handle:
                    handle.Close()

    def test_frozen_dispatch_uses_file_ipc_and_own_executable(self):
        process = Mock()
        process.poll.return_value = 0
        with patch.object(hardware_job.sys, 'frozen', True, create=True), \
                patch.object(hardware_job.subprocess, 'Popen', return_value=process) as launch:
            job = hardware_job.HardwareJob('wifi')
            command = launch.call_args.args[0]
            self.assertEqual(command[:2], [sys.executable, '--hardware-worker'])
            request = json.loads((job.directory / 'request.json').read_text())
            self.assertEqual(request['kind'], 'wifi')
            hardware_job.write_result(job.directory, dict(state='complete'))
            self.assertEqual(job.poll(), {'state': 'complete'})
            job.close()

    def test_camera_worker_releases_failed_probes_and_active_capture(self):
        import cv2
        import numpy as np
        first, second = Mock(), Mock()
        first.read.return_value = (False, None)
        second.read.side_effect = [(True, np.zeros((10, 10, 3), dtype=np.uint8)),
                                   (False, None)]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cv2, 'VideoCapture', side_effect=[first, second]):
                hardware_job.camera_worker(Path(directory))
            reply = json.loads((Path(directory) / 'result.json').read_text())
            self.assertEqual(reply['state'], 'unavailable')
            first.release.assert_called_once()
            second.release.assert_called_once()
            self.assertTrue((Path(directory) / 'frame.jpg').exists())


class LifecycleUITests(unittest.TestCase):
    def test_hidden_runner_lifecycle_and_background_notes(self):
        if os.environ.get('SECOND_CHECK_LIFECYCLE_CHILD') != '1':
            child = subprocess.run(
                [sys.executable, __file__, 'LifecycleUITests'],
                env=dict(os.environ, SECOND_CHECK_LIFECYCLE_CHILD='1'),
                capture_output=True, text=True, timeout=45)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)
        original = tk.Toplevel

        def hidden(*args, **kwargs):
            window = original(*args, **kwargs)
            window.withdraw()
            return window

        def complete(root, results, labels, context, completion_event=None):
            results[context.key] = 'pass'
            completion_event.set()

        held = {}
        cleaned = Mock()

        def hold(root, results, labels, context, completion_event=None):
            held.update(results=results, context=context, event=completion_event)
            context.register_cancel(cleaned)

        def pump(panel):
            # Let Tk callbacks run without depending on a physical device.
            deadline = time.monotonic() + 2
            while panel.is_busy() and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)

        try:
            with patch.object(tk, 'Toplevel', side_effect=hidden), \
                    patch.object(test_panel, 'current_override', return_value=True):
                results = {'keyboard': 'n/a', 'microphone': 'n/a', 'usb': 'fail'}
                panel = TestsWindow(root, results, {})
                never = Mock()
                panel.test_sequence = [('keyboard', complete),
                                       ('microphone', hold), ('usb', never)]
                panel.run_all_tests()
                root.update()
                self.assertEqual(results['keyboard'], 'pass')
                self.assertTrue(panel.is_busy())
                panel.run_test_threaded(never, 'usb')
                panel.cancel_button.invoke()
                pump(panel)
                cleaned.assert_called_once()
                never.assert_not_called()
                self.assertEqual(results['microphone'], 'cancelled')
                self.assertEqual(results['usb'], 'fail')
                self.assertIn('1 not started', panel.status_label.cget('text'))
                self.assertIn('Results are local', panel.status_label.cget('text'))
                # An old worker cannot modify the shared results or status.
                held['results']['microphone'] = 'pass'
                status = panel.status_label.cget('text')
                held['context'].update_status('late update')
                self.assertEqual(results['microphone'], 'cancelled')
                self.assertEqual(panel.status_label.cget('text'), status)

                panel.run_test_threaded(hold, 'usb')
                run = panel._active_run
                run.deadline = 0
                root.after_cancel(panel._runner_after_id)
                panel._poll_run()
                pump(panel)
                self.assertEqual(results['usb'], 'error')
                self.assertFalse(panel.is_busy())

                def broken(*args, **kwargs):
                    raise RuntimeError('test setup failed')
                panel.run_test_threaded(broken, 'usb')
                pump(panel)
                self.assertEqual(results['usb'], 'error')
                panel.run_test_threaded(complete, 'usb')
                pump(panel)
                self.assertEqual(results['usb'], 'pass')
                self.assertIn('1 pass', panel.status_label.cget('text'))

                # Stop between steps, after completion but before Tk advances.
                panel.test_sequence = [('microphone', hold), ('usb', never)]
                panel.run_all_tests()
                held['results']['microphone'] = 'pass'
                held['event'].set()
                root.after_cancel(panel._runner_after_id)
                panel._poll_run()
                panel.cancel_tests()
                pump(panel)
                never.assert_not_called()
                self.assertFalse(panel.is_busy())
                self.assertEqual(results['microphone'], 'pass')

                panel.run_test_threaded(hold, 'usb')
                panel.on_close()
                self.assertFalse(panel.is_busy())
                self.assertEqual(results['usb'], 'cancelled')
                newer = TestsWindow(root, results, {})
                newer.run_test_threaded(complete, 'usb')
                pump(newer)
                held['results']['usb'] = 'fail'
                self.assertEqual(results['usb'], 'pass')
                newer.run_test_threaded(hold, 'usb')
                newer.tests_window.destroy()
                self.assertFalse(newer.is_busy())
                self.assertEqual(results['usb'], 'cancelled')

                # Cancel inside a step also stops the rest of Run All.
                newer = TestsWindow(root, results, {})
                newer.test_sequence = [('usb', hold), ('microphone', never)]
                newer.run_all_tests()
                held['results']['usb'] = 'cancelled'
                held['event'].set()
                pump(newer)
                never.assert_not_called()
                self.assertIn('Stopped', newer.status_label.cget('text'))
                newer.on_close()

                # Destroying a poller's owner cancels its child and timers.
                owner = hidden(root)
                fake_job = Mock()
                fake_job.poll.return_value = None
                with patch.object(hardware_job, 'HardwareJob', return_value=fake_job):
                    poller = hardware_job.JobPoller(owner, 'unused', Mock())
                    owner.destroy()
                    self.assertTrue(poller.closed)
                    fake_job.close.assert_called_once()

                # A note save cannot block Tk or apply a late result after close.
                controller = app_controller.AppController.__new__(
                    app_controller.AppController)
                controller.root = root
                controller._lookup_valid = True
                controller._search_generation = 1
                controller.current_order_note_order_id = 12
                controller.current_order_note_order_number = 'test'
                controller.order_notes_footer = Mock()
                controller.order_notes_footer.get.return_value = 'Old note'
                controller._update_order_notes_footer = Mock()
                gate, finished = threading.Event(), threading.Event()

                def saver(order_id, text):
                    gate.wait(2)
                    finished.set()

                def edit_actions():
                    dialog = next(w for w in root.winfo_children()
                                  if isinstance(w, original))
                    def walk(widget):
                        for child in widget.winfo_children():
                            yield child
                            yield from walk(child)
                    buttons = [w for w in walk(dialog)
                               if w.winfo_class() == 'TButton']
                    next(w for w in buttons if w.cget('text') == 'Save').invoke()
                    self.assertFalse(finished.is_set())
                    dialog.after(50, lambda: next(w for w in buttons
                                 if w.cget('text') == 'Close editor').invoke())
                root.after(0, edit_actions)
                with patch.object(app_controller, 'save_order_note_for_order_id',
                                  side_effect=saver):
                    controller._edit_order_notes()
                    gate.set()
                    self.assertTrue(finished.wait(2))
                    root.update()
                controller._update_order_notes_footer.assert_not_called()
                def failed_edit():
                    dialog = next(w for w in root.winfo_children()
                                  if isinstance(w, original))
                    def walk(widget):
                        for child in widget.winfo_children():
                            yield child
                            yield from walk(child)
                    widgets = list(walk(dialog))
                    save = next(w for w in widgets if w.winfo_class() == 'TButton'
                                and w.cget('text') == 'Save')
                    close = next(w for w in widgets if w.winfo_class() == 'TButton'
                                 and w.cget('text') == 'Close editor')
                    editor = next(w for w in widgets if isinstance(w, tk.Text))
                    editor.insert('end', ' changed text')
                    save.invoke()
                    deadline = time.monotonic() + 3
                    def check_failure():
                        # Wait for the worker reply and Tk's queue poll rather
                        # than assuming a background thread finishes in 150ms.
                        if (editor.cget('state') == 'disabled'
                                and time.monotonic() < deadline):
                            dialog.after(20, check_failure)
                            return
                        try:
                            self.assertEqual(editor.cget('state'), 'normal')
                            self.assertIn('changed text', editor.get('1.0', 'end'))
                            self.assertTrue(save.instate(['!disabled']))
                            controller._search_generation += 1
                            save.invoke()  # Stale reference must not resubmit.
                        finally:
                            close.invoke()
                    dialog.after(20, check_failure)
                root.after(0, failed_edit)
                with patch.object(app_controller, 'save_order_note_for_order_id',
                                  side_effect=RuntimeError('DB unavailable')) as save:
                    controller._edit_order_notes()
                    save.assert_called_once()
                controller._update_order_notes_footer.assert_not_called()
                # Live battery polling is throttled and never reads WMI on Tk.
                controller._battery_bar_percent = None
                controller._battery_bar_charging = False
                callback = None
                def battery_job(root, kind, complete, **kwargs):
                    nonlocal callback
                    self.assertEqual(kind, 'battery-live')
                    callback = complete
                    return Mock(closed=False)
                with patch.object(hardware_job, 'JobPoller', side_effect=battery_job) as launch:
                    controller._refresh_primary_battery_state()
                    controller._refresh_primary_battery_state()
                    launch.assert_called_once()
                    callback(dict(state='complete', battery={
                        'percent': 72, 'charging': True, 'power_state': 'Charging'}))
                    self.assertEqual(controller._battery_bar_percent, 72)
                    self.assertIn('Charging', controller._battery_bar_label)
                    for reply in (
                            dict(state='error', detail='worker timeout'),
                            dict(state='complete', battery={'state': 'unreadable'}),
                            dict(state='complete', battery=None),
                            dict(state='complete', battery={'percent': float('nan')})):
                        callback(reply)
                        self.assertEqual(controller._battery_bar_percent, 72)
                        self.assertIn('Last reading: 72%', controller._battery_bar_label)
                        self.assertIn('retrying', controller._battery_bar_label)
                        self.assertNotIn('Charging', controller._battery_bar_label)
                        self.assertFalse(controller._battery_bar_charging)
                    callback(dict(state='complete', battery={
                        'percent': 73, 'charging': None, 'aggregate': True,
                        'power_state': 'AC power (charging unconfirmed)'}))
                    self.assertEqual(controller._battery_bar_percent, 73)
                    self.assertIn('Overall current charge', controller._battery_bar_label)
                    self.assertNotIn('Last reading', controller._battery_bar_label)
                    callback(dict(state='complete', battery={'state': 'absent'}))
                    self.assertIsNone(controller._battery_bar_percent)
                    self.assertIn('No battery detected', controller._battery_bar_label)
                    callback(dict(state='error'))
                    self.assertIn('Unavailable', controller._battery_bar_label)
                self.assertFalse(errors, errors)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
