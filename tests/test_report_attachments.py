"""Real fixed-file collection, redaction and server compatibility boundaries."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services import bug_reports, report_attachments as files, runtime
from services.diagnostic_schema import (MAX_BYTES, MAX_ATTACHMENT_BYTES, attachment_text,
                                        attachment_record, envelope)


def event(name, kind=None, at='2026-10-29T13:00:00+00:00'):
    return {'at': at, 'run': 'aabbccddeeff', 'event': name, 'level': 'ERROR',
            'context': {'kind': kind} if kind else {}, 'exceptions': []}


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in (('log_path', lambda: self.root / 'logs.txt'),
                            ('app_directory', lambda: self.root),
                            ('_SECRETS', {'configured-private-value'}),
                            ('_DIAGNOSTICS', runtime.deque(maxlen=60))):
            patcher = patch.object(runtime, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch('win32api.GetSystemDirectory', return_value=str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.panther = self.root / 'Sysprep/Panther'
        self.panther.mkdir(parents=True)

    def test_sysprep_adds_real_utf8_utf16_files_with_useful_text_and_redaction(self):
        text = ('SYSPRP Microsoft.Camera_1.0 failed 0x80073cf2\n'
                'password=unknown-secret email=owner@example.com\n'
                'configured-private-value serial=DEVICE123 computer=DESKTOP-PRIVATE\n'
                'C:\\Users\\PrivatePerson\\Documents\\customer.txt\n'
                'S-1-5-21-123-456-789-1001 fe80::1234:abcd\n'
                '2026-10-29 12:34:56 still useful\n')
        (self.panther / 'setuperr.log').write_text(text, encoding='utf-8')
        (self.panther / 'setupact.log').write_text(text, encoding='utf-16')
        incident = event('sysprep.failed')
        attachments, notes = files.collect_attachments(incident, [incident])
        self.assertEqual(notes, [])
        self.assertEqual({a['name'] for a in attachments},
            {'app-diagnostics.jsonl', 'sysprep-setuperr.log', 'sysprep-setupact.log'})
        for item in attachments[1:]:
            self.assertIn('Microsoft.Camera_1.0 failed 0x80073cf2', item['text'])
            self.assertIn('12:34:56', item['text'])
            for private in ('unknown-secret', 'owner@example.com', 'configured-private-value',
                            'PrivatePerson', 'DEVICE123', 'DESKTOP-PRIVATE', 'fe80::1234:abcd',
                            'S-1-5-21-123-456-789-1001'):
                self.assertNotIn(private, item['text'])
            self.assertEqual(attachment_record(item), item)
            self.assertEqual(item['sha256'], hashlib.sha256(item['text'].encode()).hexdigest())

    def test_camera_report_does_not_attach_earlier_sysprep_files(self):
        earlier = event('sysprep.failed')
        camera = event('camera.preview_failed', at='2026-10-29T13:01:00+00:00')
        incident = event('ui.error', at=camera['at'])
        attachments, _ = files.collect_attachments(incident, [earlier, camera])
        self.assertEqual([a['name'] for a in attachments], ['app-diagnostics.jsonl'])

    def test_missing_sysprep_files_are_reported_without_blocking_upload(self):
        attachments, notes = files.collect_attachments(event('sysprep.failed'), [])
        self.assertEqual(len(attachments), 1)
        self.assertEqual({n['reason'] for n in notes}, {'missing'})
        self.assertEqual(len(notes), 2)

    def test_large_unicode_files_and_total_envelope_stay_bounded(self):
        text = ('诊断错误 0x80073cf2\n' * 12000) + 'last useful line\n'
        for name in ('setupact.log', 'setuperr.log'):
            (self.panther / name).write_text(text, encoding='utf-8')
        incident = runtime.log_diagnostic('sysprep.failed', result='error')
        report = bug_reports.prepare_report(incident)
        self.assertLessEqual(len(json.dumps(report).encode('utf-8')), MAX_BYTES)
        self.assertEqual(len(report['attachments']), 3)
        for item in report['attachments'][1:]:
            self.assertLessEqual(item['size'], MAX_ATTACHMENT_BYTES)
            self.assertTrue(item['truncated'])
            self.assertIn('last useful line', item['text'])

    def test_windows_update_helper_uses_its_relevant_event_extract(self):
        with patch.object(files, '_windows_update_events', return_value='Error 0x80240001 token=private-value'):
            attachments, notes = files.collect_attachments(event('helper.failed', 'windows-update'), [])
        self.assertFalse(notes)
        self.assertEqual(attachments[-1]['name'], 'windows-update-events.log')
        self.assertIn('0x80240001', attachments[-1]['text'])
        self.assertNotIn('private-value', attachments[-1]['text'])

    def test_app_update_state_excludes_extra_journal_fields(self):
        folder = self.root / '.secondchecking-updates/12345678-1234-1234-1234-123456789abc'
        folder.mkdir(parents=True)
        (folder / 'state.json').write_text(json.dumps({'state': 'blocked', 'version': '1.2.3',
            'password': 'do-not-copy', 'command': 'private-command'}))
        attachments, _ = files.collect_attachments(event('update.check_failed'), [])
        item = next(a for a in attachments if a['name'] == 'app-update-state.json')
        self.assertIn('blocked', item['text'])
        self.assertNotIn('do-not-copy', item['text'])
        self.assertNotIn('private-command', item['text'])

    def test_malformed_update_journal_does_not_prevent_reporting(self):
        folder = self.root / '.secondchecking-updates/12345678-1234-1234-1234-123456789abc'
        folder.mkdir(parents=True)
        (folder / 'state.json').write_text('[]')
        attachments, _ = files.collect_attachments(event('update.check_failed'), [])
        self.assertTrue(any(item['name'] == 'app-diagnostics.jsonl' for item in attachments))

    def test_unsupported_names_oversize_duplicate_and_binary_input_are_refused(self):
        incident = event('camera.failed')
        report = {'schema_version': 1, 'report_id': 'a' * 32,
                  'incident': incident, 'events': [], 'build': {}}
        for attachments in ([{'name': '../config.ini', 'text': 'password=secret'}],
                            [{'name': 'sysprep-setuperr.log', 'text': b'binary'}],
                            [{'name': 'sysprep-setuperr.log', 'text': 'x' * (MAX_ATTACHMENT_BYTES + 1)}],
                            [{'name': 'sysprep-setuperr.log', 'text': 'x'}] * 2):
            with self.subTest(attachments=len(attachments)), self.assertRaises(ValueError):
                envelope(dict(report, attachments=attachments))
        self.assertNotIn('attachments', envelope(report))

    def test_old_server_cannot_silently_discard_files(self):
        report = bug_reports.prepare_report(event('camera.failed'))
        capability = Mock(status_code=404)
        capability.json.return_value = {}
        with patch.object(bug_reports, 'service_settings', return_value=('https://fixture.invalid', 'fixture-key')), \
                patch.object(bug_reports.transport, 'get', return_value=capability), \
                patch.object(bug_reports.transport, 'post') as send:
            with self.assertRaisesRegex(RuntimeError, 'Nothing was uploaded'):
                bug_reports.upload_report(report)
            send.assert_not_called()

    def test_redaction_is_idempotent_and_removes_unlabelled_long_secrets(self):
        text = ('access_token="private value"\ncustomer=John Smith\nfor user "Jane Doe"\n'
                'ABCDE-FGHIJ-KLMNO-PQRST-UVWXY\n' + 'A' * 60)
        cleaned = attachment_text(text)
        self.assertEqual(attachment_text(cleaned), cleaned)
        self.assertNotIn('private value', cleaned)
        self.assertNotIn('A' * 60, cleaned)
        for private in ('John', 'Smith', 'Jane', 'Doe', 'ABCDE-FGHIJ-KLMNO-PQRST-UVWXY'):
            self.assertNotIn(private, cleaned)

    def test_local_user_and_machine_names_are_redacted_even_without_labels(self):
        import os
        with patch.dict(os.environ, {'USERNAME': 'PrivateOperator', 'COMPUTERNAME': 'PrivateMachine'}):
            (self.panther / 'setuperr.log').write_text('PrivateOperator on PrivateMachine failed 0x80073cf2')
            attachments, _ = files.collect_attachments(event('sysprep.failed'), [])
        text = json.dumps(attachments)
        self.assertNotIn('PrivateOperator', text)
        self.assertNotIn('PrivateMachine', text)
        self.assertIn('0x80073cf2', text)
