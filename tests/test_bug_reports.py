"""Support evidence stays useful without raw customer/configuration content."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services import bug_reports, runtime
from services.diagnostic_schema import envelope


class BugReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = patch.object(runtime, 'log_path', return_value=Path(self.temp.name) / 'logs.txt')
        self.path.start()
        self.addCleanup(self.path.stop)
        self.memory = patch.object(runtime, '_DIAGNOSTICS', runtime.deque(maxlen=60))
        self.memory.start()
        self.addCleanup(self.memory.stop)
        capability = Mock(status_code=200)
        capability.json.return_value = {'attachments_version': 1}
        ready = patch.object(bug_reports.transport, 'get', return_value=capability)
        ready.start()
        self.addCleanup(ready.stop)

    def report(self):
        try:
            raise OSError(13, 'secret-password customer@example.com C:\\Users\\Owner')
        except OSError as error:
            incident = runtime.log_diagnostic('camera.preview_failed', error=error,
                stage='preview', camera_index=0, response='private-body', serial='DEVICE-123')
        return bug_reports.prepare_report(incident)

    def test_preview_preserves_codes_locations_and_drops_private_content(self):
        report = self.report()
        text = json.dumps(report)
        self.assertIn('13', text)
        self.assertIn('test_bug_reports.py', text)
        for private in ('secret-password', 'customer@example.com', 'Owner',
                        'private-body', 'DEVICE-123'):
            self.assertNotIn(private, text)
        self.assertTrue(report['events'])

    def test_legacy_and_malformed_logs_are_never_exported(self):
        runtime.log_path().write_text('password=legacy-secret customer data')
        runtime.diagnostic_path().write_text('not-json\n' + json.dumps({'password': 'secret'}))
        self.assertEqual(runtime.recent_diagnostics(), [])
        self.assertNotIn('legacy-secret', json.dumps(bug_reports.prepare_report()))

    def test_schema_rejects_attachments_and_arbitrary_fields_from_uploaded_evidence(self):
        report = self.report()
        report.update(config='private-password', screenshots=['private'], notes='private')
        report['incident']['context']['password'] = 'private-password'
        report['incident']['exceptions'][0]['message'] = 'private-password'
        report['incident']['exceptions'][0]['frames'].append('C:\\Users\\Owner\\secret.py:1:run')
        self.assertNotIn('private-password', json.dumps(envelope(report)))
        self.assertNotIn('Owner', json.dumps(envelope(report)))

    def test_known_secrets_are_removed_even_from_token_shaped_context(self):
        with patch.object(runtime, '_SECRETS', {'tokenLikeSecret'}):
            record = runtime.log_diagnostic('test.failed', reason='tokenLikeSecret')
        self.assertNotIn('tokenLikeSecret', json.dumps(record))

    def test_upload_uses_configured_transport_and_retries_frozen_reference(self):
        report = self.report()
        response = Mock(status_code=200)
        response.json.return_value = {'success': True, 'report_id': report['report_id'],
                                      'attachment_count': len(report['attachments'])}
        with patch.object(bug_reports, 'service_settings', return_value=('https://fixture.invalid', 'fixture-key')), \
                patch.object(bug_reports.operator_session, 'headers', return_value={}), \
                patch.object(bug_reports.transport, 'post', return_value=response) as sender:
            for _ in range(2):
                self.assertEqual(bug_reports.upload_report(report), report['report_id'])
            self.assertEqual(sender.call_args.kwargs['json']['report_id'], report['report_id'])
            self.assertEqual(sender.call_args.kwargs['headers']['X-Second-Check-Key'], 'fixture-key')
            self.assertNotIn('verify', sender.call_args.kwargs)

    def test_rejected_upload_does_not_claim_success_or_change_report(self):
        report = self.report()
        before = json.dumps(report, sort_keys=True)
        response = Mock(status_code=503)
        response.json.return_value = {'success': False}
        with patch.object(bug_reports, 'service_settings', return_value=('https://fixture.invalid', 'fixture-key')), \
                patch.object(bug_reports.transport, 'post', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'migration'):
                bug_reports.upload_report(report)
        self.assertEqual(before, json.dumps(report, sort_keys=True))

    def test_log_write_failure_still_leaves_memory_evidence(self):
        with patch.object(runtime, 'diagnostic_path', return_value=Path(self.temp.name) / 'missing' / 'diagnostics.jsonl'):
            runtime.log_diagnostic('support.disk_failed', stage='write')
            self.assertTrue(runtime.recent_diagnostics())

    def test_report_refreshes_late_sysprep_codes_without_attaching_panther_text(self):
        runtime.log_diagnostic('maintenance.finished', kind='sysprep', exit_code=1)
        with patch('services.maintenance.collect_sysprep_diagnostics') as collect:
            bug_reports.prepare_report()
        collect.assert_called_once_with()

    def test_sysprep_extracts_native_codes_without_package_names_or_log_text(self):
        from services import maintenance
        root = Path(self.temp.name) / 'Sysprep' / 'Panther'
        root.mkdir(parents=True)
        from datetime import datetime
        stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        (root / 'setuperr.log').write_text(stamp + ', Error SYSPRP private-package-for-user failed 0x80073cf2')
        (root / 'setupact.log').write_text('')
        with patch('win32api.GetSystemDirectory', return_value=self.temp.name):
            maintenance.collect_sysprep_diagnostics()
        events = runtime.recent_diagnostics()
        self.assertTrue(any(event['context'].get('native_code') == 0x80073cf2 for event in events))
        self.assertNotIn('private-package-for-user', json.dumps(events))


class BugReportDialogTests(unittest.TestCase):
    def test_file_preparation_keeps_preview_responsive_and_upload_explicit(self):
        if self.child():
            return
        import threading
        import time
        from ui.bug_reports import open_report
        release = threading.Event()
        report = {'report_id': 'a' * 32, 'attachments': [{'name': 'sysprep-setuperr.log',
            'text': '0x80073cf2\nUseful Windows error', 'size': 34, 'truncated': False}]}
        def prepare(*args):
            release.wait(5)
            return report
        def buttons(widget):
            result = []
            for child in widget.winfo_children():
                if child.winfo_class() == 'TButton':
                    result.append(child)
                result.extend(buttons(child))
            return result
        try:
            with patch('ui.bug_reports.prepare_report', side_effect=prepare), \
                    patch('ui.bug_reports.upload_report') as sender:
                window = open_report(self.root)
                send = next(b for b in buttons(window) if b.cget('text') == 'Upload bug report')
                ticks = []
                self.root.after(10, lambda: ticks.append(True))
                deadline = time.monotonic() + 2
                while not ticks and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
                self.assertTrue(ticks)
                self.assertIn('disabled', send.state())
                release.set()
                deadline = time.monotonic() + 3
                while 'disabled' in send.state() and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
                self.assertNotIn('disabled', send.state())
                sender.assert_not_called()
                window.destroy()
        finally:
            release.set()

    def test_sign_in_has_retry_and_exit_but_no_report_action(self):
        if self.child():
            return
        from auth.login import LoginPanel
        with patch.object(LoginPanel, '_load_usernames_async'):
            LoginPanel(self.root, Mock())
            self.root.update_idletasks()
        labels = []
        def walk(widget):
            for child in widget.winfo_children():
                if child.winfo_class() in ('Button', 'TButton'):
                    labels.append(str(child.cget('text')))
                walk(child)
        walk(self.root)
        self.assertIn('Retry', labels)
        self.assertIn('Exit', labels)
        self.assertFalse(any('bug report' in label.lower() for label in labels))

    def setUp(self):
        if os.environ.get('SC_BUG_REPORT_UI_CHILD') != '1':
            return
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(lambda: (self.root.update_idletasks(), self.root.destroy()))

    def child(self):
        if os.environ.get('SC_BUG_REPORT_UI_CHILD') == '1':
            return False
        import subprocess
        result = subprocess.run([sys.executable, __file__,
            'BugReportDialogTests.' + self._testMethodName],
            env=dict(os.environ, SC_BUG_REPORT_UI_CHILD='1'),
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return True

    def test_preview_cancel_never_uploads_and_install_restores_error_handler(self):
        if self.child():
            return
        from ui.bug_reports import install, open_report
        from tkinter import messagebox
        original = messagebox.showerror
        service = install(self.root)
        self.assertEqual(messagebox.showerror, service.wrapper)
        with patch('ui.bug_reports.upload_report') as sender:
            window = open_report(self.root)
            self.root.update_idletasks()
            window.destroy()
            sender.assert_not_called()
        self.root.update_idletasks()
        self.root.destroy()
        self.assertEqual(messagebox.showerror, original)
        self._cleanups.clear()

    def test_error_dialog_has_report_button_without_uploading_automatically(self):
        if self.child():
            return
        from ui.bug_reports import install
        service = install(self.root)
        seen = []

        def inspect():
            def walk(widget):
                for child in widget.winfo_children():
                    if child.winfo_class() == 'TButton':
                        seen.append(child.cget('text'))
                    walk(child)
            walk(self.root)
            for child in self.root.winfo_children():
                if child.winfo_class() == 'Toplevel':
                    child.destroy()
        self.root.after(100, inspect)
        with patch('ui.bug_reports.upload_report') as sender:
            self.assertEqual(service.show_error('Error', 'Local error message'), 'ok')
            sender.assert_not_called()
        self.assertIn('Upload bug report…', seen)


if __name__ == '__main__':
    unittest.main()
