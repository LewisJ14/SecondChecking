"""Saved evidence, honest empty states and report reader lifecycle."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services.saved_report import format_saved_report
from services.update_result import decode_update_result
from services.check_results import TEST_KEYS
from ui import saved_report
import ui.tests as test_panel
import app_controller
import main
from utils import helpers
from services import operator_session
from operator_fixture import sign_in


def sample():
    return dict(
        success=True, found=True, saved_report_version=1, data_state='saved_report',
        order_id=12, order_number='ORDER-A', serial_number='001234', sku='SKU',
        report_id=5, checked_by='tester', checked_at='2026-10-22T12:00:00Z',
        test_results=dict.fromkeys(TEST_KEYS, 'pass'), provenance_known=True,
        test_overrides={'wifi': [dict(active=False, measured_result='unavailable',
                        previous_result='unavailable', result='fail', operator='first',
                        at='2026-10-22T11:00:00Z', reason='Earlier explanation'),
                        dict(active=True, measured_result='unavailable',
                        previous_result='fail', result='pass', operator='tester',
                        at='2026-10-22T12:00:00Z', reason='Bench adapter checked')]},
        test_coverage={'usb': {'details': {'required_ports': ['Left', 'Right']}}},
        specs={'Battery': '86%', 'Battery 2': '83%', 'CPU': 'Intel Core'},
        assignment={'id': 8, 'status': 'reserved', 'assigned_by': 'tester'},
        receipt={'operation_id': 'saved-operation', 'report_id': 5},
        battery_evidence={'batteries': [{'health_percent': 86}, {'health_percent': 83}]},
        battery_capture={'filename': 'battery.csv', 'source': 'BatteryInfoView'},
        storage_inventory={'devices': [{'device_id': 'disk0'}]},
        storage_review={'policy': 'physical_configuration', 'matched': True},
        device_measurements={'checked_at': '2026-10-22T12:00:00Z', 'source': 'WMI'},
        mdm_evidence={'state': 'no_local_indicators', 'tenant_verification': 'not_checked'},
        assignment_review={'operator': 'tester', 'reason': 'Bench exception'},
    )


from operator_fixture import sign_in as setUpModule, sign_out as tearDownModule


class SavedReportTests(unittest.TestCase):
    def test_unconfirmed_saved_lookup_is_an_error_not_an_empty_device(self):
        response = Mock(status_code=200)
        with patch.object(helpers, '_load_webtools_api_config',
                          return_value=('https://isolated', 'test-key')), \
                patch.object(helpers.requests, 'get', return_value=response) as get:
            response.json.return_value = {'success': True}
            with self.assertRaises(ValueError):
                helpers.load_saved_check_results('ORDER-A', '001234')
            response.json.return_value = {'success': True, 'found': False}
            self.assertFalse(helpers.load_saved_check_results('ORDER-A', '001234')['found'])
            self.assertEqual(get.call_args.kwargs['params'],
                             {'order_number': 'ORDER-A', 'serial_number': '001234'})

    def test_every_result_and_saved_provenance_are_present(self):
        text = format_saved_report(sample(), 'ORDER-A', '001234')
        for key in TEST_KEYS:
            self.assertIn(key.title() + ':', text)
        for marker in ('OVERRIDDEN PASS', 'ACTIVE', 'SUPERSEDED', 'Earlier explanation',
                       'Bench adapter checked', 'saved-operation', '86%', '83%',
                       'BatteryInfoView', 'physical_configuration', 'disk0',
                       'TENANT STATUS NOT VERIFIED', 'Bench exception', 'Left',
                       'Checked by: tester', 'Checked at (as recorded): 2026-10-22'):
            self.assertIn(marker, text)

    def test_legacy_and_no_current_assignment_do_not_infer_a_new_report(self):
        legacy = sample()
        legacy.update(data_state='legacy_serial_only', provenance_known=False,
                      history_unknown=list(TEST_KEYS), receipt=None, report_id=None,
                      checked_by=None, checked_at=None, test_coverage={}, test_overrides={})
        text = format_saved_report(legacy, 'ORDER-A', '001234')
        self.assertIn('LEGACY DATA ONLY', text)
        self.assertIn('HISTORY UNKNOWN', text)
        self.assertIn('Checked at (as recorded): Not recorded', text)
        missing = format_saved_report(dict(success=True, found=False), 'ORDER-A', '001234')
        self.assertIn('No current assignment/report', missing)
        self.assertNotIn('Keyboard: PASS', missing)

    def test_wrong_identity_or_unconfirmed_response_cannot_be_displayed_as_report(self):
        for changes in ({'serial_number': '1234'}, {'order_number': 'OTHER'},
                        {'saved_report_version': None}, {'found': None},
                        {'success': False}, {'test_results': []}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    format_saved_report(dict(sample(), **changes), 'ORDER-A', '001234')
        alias = dict(sample(), order_number='PC-0001', lookup_reference='ORDER-A')
        text = format_saved_report(alias, 'ORDER-A', '001234')
        self.assertIn('Order: PC-0001 (ID 12; lookup ORDER-A)', text)

    def test_update_results_require_explicit_success(self):
        for result in ('', ' ', '{}', '[]', 'null', '{bad',
                       '{"state":"up_to_date"}',
                       '{"update_check_version":1,"state":"unknown"}',
                       '{"update_check_version":1,"state":"up_to_date","current_version":"other"}'):
            with self.subTest(result=result):
                with self.assertRaises((ValueError, TypeError)):
                    decode_update_result(result, '1.0')
        self.assertIsNone(decode_update_result(json.dumps(dict(
            update_check_version=1, state='up_to_date', current_version='1.0')), '1.0'))
        self.assertEqual(decode_update_result('{"version":"2.0"}', '1.0')['version'], '2.0')

    def test_headless_helper_emits_confirmed_no_update_and_available_states(self):
        with patch('update_service.UpdateService') as service, patch.object(main, 'log_event'):
            service.return_value.current_version = '1.0'
            service.return_value.check_for_updates.return_value = None
            output = io.StringIO()
            with redirect_stdout(output):
                main.run_headless_update_check()
            self.assertIsNone(decode_update_result(output.getvalue(), '1.0'))
            service.return_value.check_for_updates.return_value = SimpleNamespace(
                version='2.0', download_url='https://example.invalid/update',
                release_page=None, notes='Changes', metadata={})
            output = io.StringIO()
            with redirect_stdout(output):
                main.run_headless_update_check()
            self.assertEqual(decode_update_result(output.getvalue(), '1.0')['state'],
                             'update_available')


class SavedReportUITests(unittest.TestCase):
    def test_hidden_read_retry_timeout_close_and_fresh_session_states(self):
        if os.environ.get('SECOND_CHECK_REPORT_UI_CHILD') != '1':
            child = subprocess.run(
                [sys.executable, __file__, 'SavedReportUITests'],
                env=dict(os.environ, SECOND_CHECK_REPORT_UI_CHILD='1'),
                capture_output=True, text=True, timeout=40)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)
        original = tk.Toplevel
        def hidden(*args, **kwargs):
            dialog = original(*args, **kwargs)
            dialog.withdraw()
            return dialog

        def ready(dialog):
            deadline = time.monotonic() + 3
            while str(dialog.retry.cget('state')) == 'disabled' and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertEqual(str(dialog.retry.cget('state')), 'normal')

        try:
            with patch.object(tk, 'Toplevel', side_effect=hidden):
                with patch.object(saved_report, 'load_saved_check_results',
                                  side_effect=[RuntimeError('Service offline'), sample()]) as load:
                    dialog = saved_report.open_saved_report(root, 'ORDER-A', '001234')
                    ready(dialog)
                    self.assertIn('unavailable', dialog.status.get())
                    self.assertIn('Service offline', dialog.text.get('1.0', 'end'))
                    dialog.retry.invoke()
                    ready(dialog)
                    self.assertIn('SAVED CHECKS', dialog.text.get('1.0', 'end'))
                    self.assertEqual(load.call_args.args, ('ORDER-A', '001234'))
                    self.assertEqual(dialog.text.cget('state'), 'disabled')
                    dialog.close()

                with patch.object(saved_report, 'load_saved_check_results',
                                  side_effect=operator_session.SignInRequired()):
                    dialog = saved_report.open_saved_report(root, 'ORDER-A', '001234')
                    deadline = time.monotonic() + 3
                    while 'Sign-in required' not in dialog.status.get() and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.01)
                    self.assertIn('Sign-in required', dialog.status.get())
                    self.assertIn('Operator > Lock / change operator', dialog.text.get('1.0', 'end'))
                    self.assertNotIn('SAVED CHECKS', dialog.text.get('1.0', 'end'))
                    self.assertEqual(str(dialog.retry.cget('state')), 'disabled')
                    dialog.close()

                gate, started, finished = threading.Event(), threading.Event(), threading.Event()
                calls = []
                def loader(order, serial):
                    calls.append(serial)
                    if len(calls) == 1:
                        started.set()
                        gate.wait(3)
                        finished.set()
                        return dict(sample(), report_id=999)
                    return sample()
                with patch.object(saved_report, 'load_saved_check_results', side_effect=loader):
                    dialog = saved_report.open_saved_report(root, 'ORDER-A', '001234')
                    self.assertTrue(started.wait(2))
                    dialog.window.after_cancel(dialog.after_id)
                    dialog.deadline = 0
                    dialog.poll()
                    self.assertIn('timed out', dialog.status.get())
                    dialog.retry.invoke()
                    ready(dialog)
                    self.assertIn('Report ID: 5', dialog.text.get('1.0', 'end'))
                    dialog.close()
                    gate.set()
                    self.assertTrue(finished.wait(2))
                    root.update()
                    self.assertIsNone(dialog.after_id)

                controller = app_controller.AppController.__new__(app_controller.AppController)
                controller.root = root
                controller.tests_window = None
                controller.test_results = dict.fromkeys(TEST_KEYS, 'Not Run')
                controller.test_labels = {}
                controller.current_user = None
                controller._check_session = SimpleNamespace(key=None, order_number='')
                with patch.object(test_panel, 'current_override', return_value=True), \
                        patch.object(app_controller.messagebox, 'showwarning') as warning:
                    controller.open_test_panel()
                    self.assertIn('No checks recorded', controller._tests_runner.status_label.cget('text'))
                    warning.assert_not_called()
                    controller._tests_runner.on_close()
                self.assertFalse(errors, errors)
        finally:
            root.destroy()


class SavedReportSessionTests(unittest.TestCase):
    def setUp(self):
        sign_in()

    def tearDown(self):
        sign_in()

    def test_local_expiry_does_not_send_an_unauthenticated_read(self):
        with patch.object(helpers, '_load_webtools_api_config',
                          return_value=('https://isolated', 'private-key')), \
                patch.object(operator_session.time, 'monotonic',
                             return_value=time.monotonic() + 4000), \
                patch.object(helpers.transport, 'get') as get:
            with self.assertRaises(operator_session.SignInRequired):
                helpers.load_saved_check_results('ORDER-A', '001234')
            get.assert_not_called()
        self.assertFalse(operator_session.snapshot())

    def test_unauthorized_read_invalidates_only_current_session_and_redacts_error(self):
        response = Mock(status_code=401)
        response.raise_for_status.side_effect = helpers.requests.HTTPError('private-key token URL')
        with patch.object(helpers, '_load_webtools_api_config',
                          return_value=('https://isolated', 'private-key')), \
                patch.object(helpers.transport, 'get', return_value=response):
            with self.assertRaises(operator_session.SignInRequired) as caught:
                helpers.load_saved_check_results('ORDER-A', '001234')
        self.assertFalse(operator_session.snapshot())
        self.assertIn('Sign in again', str(caught.exception))
        self.assertNotIn('private-key', str(caught.exception))
        response.raise_for_status.assert_not_called()

    def test_late_unauthorized_read_cannot_clear_a_new_operator(self):
        previous = operator_session.generation()
        def reply(*args, **kwargs):
            sign_in()
            return Mock(status_code=401)
        with patch.object(helpers, '_load_webtools_api_config',
                          return_value=('https://isolated', 'key')), \
                patch.object(helpers.transport, 'get', side_effect=reply):
            with self.assertRaises(operator_session.SignInRequired):
                helpers.load_saved_check_results('ORDER-A', '001234')
        self.assertGreater(operator_session.generation(), previous)
        self.assertTrue(operator_session.allowed('read'))

    def test_permission_error_does_not_discard_valid_operator(self):
        response = Mock(status_code=403)
        response.raise_for_status.side_effect = helpers.requests.HTTPError('Forbidden')
        with patch.object(helpers, '_load_webtools_api_config',
                          return_value=('https://isolated', 'key')), \
                patch.object(helpers.transport, 'get', return_value=response):
            with self.assertRaises(helpers.requests.HTTPError):
                helpers.load_saved_check_results('ORDER-A', '001234')
        self.assertTrue(operator_session.allowed('read'))


if __name__ == '__main__':
    unittest.main()
