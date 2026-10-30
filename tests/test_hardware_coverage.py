"""Coverage limits, device absence and explicit operator decisions."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from hardwaretests import usb, wifi, webcam
from services.check_results import start_measurement, review_lines
from services.check_session import CheckDraftStore, result_state
from services.test_coverage import record_coverage, coverage_lines
from ui import keyboard_test
import main_logic


class CoverageTests(unittest.TestCase):
    def test_coverage_draft_readback_and_retest(self):
        results = {'usb': 'pass'}
        record_coverage(results, 'usb', 'Removable detection only', {
            'required_ports': ['Left'], 'observed_ports': {'Left': ['E:']}})
        self.assertIn('Left', ' '.join(review_lines(results)))
        with tempfile.TemporaryDirectory() as directory:
            store = CheckDraftStore(directory)
            # Exercise the durable draft through its public save/load contract.
            state = result_state(results)
            store.save((1, '001'), state, state)
            saved = store.load((1, '001'))
            self.assertEqual(saved['results']['_coverage'], results['_coverage'])
        response = {'found': True, 'test_results': results,
                    'test_overrides': {}, 'test_coverage': results['_coverage'],
                    'provenance_known': True}
        with patch.object(main_logic, 'load_saved_check_results',
                          return_value=response):
            loaded = main_logic.load_test_results(None, 'test', '001')
        self.assertEqual(loaded['_coverage'], results['_coverage'])
        start_measurement(loaded, 'wifi')
        self.assertIn('usb', loaded['_coverage'])
        start_measurement(loaded, 'usb')
        self.assertNotIn('usb', loaded['_coverage'])

    def test_wlan_states_do_not_parse_english(self):
        for interfaces, state in [([], 'unavailable'),
                                  ([{'name': '無線 LAN', 'state': 0}],
                                   'unavailable'),
                                  ([{'name': 'Réseau sans fil', 'state': 4}],
                                   'pass')]:
            with self.subTest(state=state, interfaces=interfaces):
                with patch.object(wifi, 'enumerate_wlan_interfaces',
                                  return_value=interfaces):
                    results, event = {}, threading.Event()
                    def immediate(root, kind, callback, **kwargs):
                        status, detail, entries = wifi.check_wifi_status()
                        callback(dict(state=status, detail=detail, interfaces=entries))
                        return Mock()
                    with patch('services.hardware_job.JobPoller', side_effect=immediate):
                        wifi.run_wifi_test(None, results, {}, completion_event=event)
                    self.assertEqual(results['wifi'], state)
                    self.assertTrue(event.is_set())
                    self.assertIn('connectivity untested',
                                  results['_coverage']['wifi']['scope'])
        with patch.object(wifi, 'enumerate_wlan_interfaces',
                          side_effect=OSError('1062 service stopped')):
            self.assertEqual(wifi.check_wifi_status()[0], 'error')

    def test_wlan_native_buffer_and_handle_cleanup(self):
        class InterfaceList(ctypes.Structure):
            _fields_ = [('count', wintypes.DWORD), ('index', wintypes.DWORD),
                        ('entries', wifi.InterfaceInfo * 1)]
        data = InterfaceList()
        data.count = 1
        data.entries[0].description = '無線 network'
        data.entries[0].state = 4
        api = Mock()

        def open_handle(version, reserved, negotiated, handle):
            ctypes.cast(handle, ctypes.POINTER(wintypes.HANDLE))[0] = 77
            return 0

        def enumerate_interfaces(handle, reserved, output):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = (
                ctypes.addressof(data))
            return 0

        api.WlanOpenHandle.side_effect = open_handle
        api.WlanEnumInterfaces.side_effect = enumerate_interfaces
        with patch.object(wifi.ctypes, 'WinDLL', return_value=api):
            self.assertEqual(wifi.enumerate_wlan_interfaces(),
                             [{'name': '無線 network', 'state': 4}])
            api.WlanFreeMemory.assert_called_once()
            api.WlanCloseHandle.assert_called_once()
            api.reset_mock()
            api.WlanEnumInterfaces.side_effect = None
            api.WlanEnumInterfaces.return_value = 5
            with self.assertRaises(OSError):
                wifi.enumerate_wlan_interfaces()
            api.WlanFreeMemory.assert_not_called()
            api.WlanCloseHandle.assert_called_once()


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class HardwareDialogTests(unittest.TestCase):
    def test_hidden_tk_coverage_controls(self):
        if os.environ.get('SECOND_CHECK_COVERAGE_UI_CHILD') != '1':
            child = subprocess.run(
                [sys.executable, __file__, 'HardwareDialogTests'],
                env=dict(os.environ, SECOND_CHECK_COVERAGE_UI_CHILD='1'),
                capture_output=True, text=True, timeout=60)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        root = tk.Tk()
        root.withdraw()
        original = tk.Toplevel

        def hidden(*args, **kwargs):
            window = original(*args, **kwargs)
            window.withdraw()
            return window

        def button(window, text):
            return next(w for w in descendants(window)
                        if w.winfo_class() in ('TButton', 'Button')
                        and w.cget('text') == text)

        try:
            def immediate_usb(root, kind, callback, **kwargs):
                try:
                    volumes = sorted(usb.removable_volumes())
                    reply = dict(state='complete', volumes=volumes)
                except Exception as exc:
                    reply = dict(state='error', detail=str(exc))
                callback(reply)
                return Mock()
            with patch.object(tk, 'Toplevel', side_effect=hidden), \
                    patch.object(usb, 'JobPoller', side_effect=immediate_usb):
                results, event = {}, threading.Event()
                volumes = set()
                with patch.object(usb, 'removable_volumes',
                                  side_effect=lambda: set(volumes)):
                    dialog = usb.run_usb_test(root, results, {},
                                             completion_event=event)
                    dialog.finish('pass')
                    self.assertFalse(event.is_set())
                    self.assertFalse(dialog.observed)
                    # Simulate each poll without leaving old timers scheduled.
                    def poll():
                        dialog.window.after_cancel(dialog.poll_id)
                        dialog.poll()
                    volumes.add('E: drive')
                    poll()
                    self.assertIn('Connection 1', dialog.observed)
                    self.assertFalse(any(
                        w.winfo_class() in ('TButton', 'Button')
                        and w.cget('text') == 'Confirm this port works'
                        for w in descendants(dialog.window)))
                    poll()  # A drive left connected must not count again.
                    self.assertEqual(len(dialog.observed), 1)
                    volumes.clear()
                    poll()
                    volumes.add('E: drive')
                    poll()
                    self.assertEqual(len(dialog.observed), 2)
                    self.assertFalse(dialog.pass_button.instate(['disabled']))
                    dialog.pass_button.invoke()
                    self.assertTrue(event.is_set())
                    self.assertEqual(results['usb'], 'pass')
                    self.assertEqual(len(results['_coverage']['usb']
                                         ['details']['observed_ports']), 2)
                    self.assertTrue(results['_coverage']['usb']['details']['operator_confirmed_all_ports'])
                    self.assertFalse(results['_coverage']['usb']['details']['port_count_declared'])
                    summary = '\n'.join(coverage_lines(results))
                    self.assertIn('Detected insertions: 2', summary)
                    self.assertIn('Every physical port checked: operator confirmed', summary)
                    self.assertNotIn('Required ports:', summary)

                    dialog = usb.run_usb_test(root, results, {})
                    self.assertFalse(dialog.ports)
                    # The already-connected drive is a baseline, not a new check.
                    self.assertFalse(dialog.observed)
                    with patch.object(usb, 'removable_volumes',
                                      side_effect=OSError('enumeration failed')):
                        poll()
                    self.assertIsNone(dialog.known)
                    self.assertTrue(dialog.pass_button.instate(['disabled']))
                    poll()  # Recovery establishes a baseline, not an insertion.
                    self.assertFalse(dialog.observed)
                    volumes.clear()
                    poll()
                    volumes.update(('E: drive', 'F: second partition'))
                    poll()
                    self.assertEqual(dialog.observed, {
                        'Connection 1': ['E: drive', 'F: second partition']})
                    root.tk.call(dialog.window.protocol('WM_DELETE_WINDOW'))
                    self.assertEqual(results['usb'], 'cancelled')
                    self.assertIsNone(dialog.poll_id)

                with patch.object(usb, 'removable_volumes',
                                  side_effect=OSError('enumeration failed')):
                    dialog = usb.run_usb_test(root, results, {})
                    self.assertTrue(dialog.errors)
                    dialog.finish('error')
                    self.assertEqual(results['usb'], 'error')

                backend = Mock()
                global_tab = root.bind_all('<Tab>')
                with patch.object(keyboard_test, 'keyboard', backend):
                    keyboard_test.run_keyboard_test(root, results, {})
                    window = keyboard_test.keyboard_test_window
                    release = backend.on_release.call_args.args[0]
                    release(SimpleNamespace(name='a', is_keypad=False))
                    root.update()
                    button(window, 'Finish and review').invoke()
                    prompt = next(w for w in root.winfo_children()
                                  if isinstance(w, original))
                    with patch.object(keyboard_test.messagebox, 'showerror') as error:
                        button(prompt, 'Yes').invoke()
                        error.assert_called_once()
                    entry = next(w for w in descendants(prompt)
                                 if isinstance(w, tk.Entry))
                    entry.insert(0, 'Remaining keys checked manually on US layout')
                    button(prompt, 'Yes').invoke()
                    detail = results['_coverage']['keyboard']['details']
                    self.assertEqual(detail['observed_keys'], ['a'])
                    self.assertTrue(detail['missing_keys'])
                    self.assertEqual(results['keyboard'], 'pass')
                    self.assertEqual(root.bind_all('<Tab>'), global_tab)
                    self.assertEqual(backend.unhook.call_count, 2)

                job = Mock()
                job.poll.return_value = dict(state='unavailable', detail='No camera')
                with patch.object(webcam, 'HardwareJob', return_value=job):
                    event.clear()
                    camera = webcam.run_webcam_test(root, results, {},
                                                    completion_event=event)
                    camera.poll()
                    self.assertTrue(event.is_set())
                    self.assertEqual(results['webcam'], 'unavailable')
                    job.close.assert_called()
                    event.clear()
                    camera = webcam.run_webcam_test(root, results, {},
                                                    completion_event=event)
                    root.tk.call(camera.window.protocol('WM_DELETE_WINDOW'))
                    root.update()
                    self.assertEqual(results['webcam'], 'cancelled')
                    self.assertTrue(event.is_set())
                    job.poll.side_effect = RuntimeError('camera API failed')
                    camera = webcam.run_webcam_test(root, results, {})
                    camera.poll()
                    self.assertIn('Camera error', camera.status.get())
                    self.assertNotIn('camera API failed', camera.status.get())
                    self.assertEqual(camera.details['preview_error'], 'camera API failed')
                    camera.retry()
                    self.assertEqual(camera.details['frames_seen'], 0)
                    self.assertTrue(camera.pass_button.instate(['disabled']))
                    camera.finish('error')
                    self.assertEqual(results['webcam'], 'error')
                    job.poll.side_effect = None
                    with tempfile.TemporaryDirectory() as directory:
                        from PIL import Image
                        job.directory = Path(directory)
                        Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8)).save(
                            job.directory / 'frame.jpg')
                        job.process.poll.return_value = None
                        job.poll.return_value = dict(state='preview', camera_index=0,
                                                     frames_seen=1, heartbeat=time.time())
                        camera = webcam.run_webcam_test(root, results, {})
                        camera.poll()
                        camera.pass_button.invoke()
                        self.assertEqual(results['webcam'], 'pass')
                        self.assertEqual(results['_coverage']['webcam']
                                         ['details']['frames_seen'], 1)
        finally:
            for pending in root.tk.splitlist(root.tk.call('after', 'info')):
                root.after_cancel(pending)
            root.destroy()


if __name__ == '__main__':
    unittest.main()
