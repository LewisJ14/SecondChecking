"""Operational diagnostics retain evidence without exception arguments or secrets."""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services import runtime


class DiagnosticTests(unittest.TestCase):
    def test_exception_chain_codes_and_locations_without_private_arguments(self):
        try:
            try:
                raise PermissionError(13, 'private-password customer@example.com')
            except PermissionError as cause:
                raise RuntimeError('private-response-body') from cause
        except RuntimeError as error:
            report = runtime.exception_report(error)
        text = json.dumps(report)
        self.assertNotIn('private-password', text)
        self.assertNotIn('private-response-body', text)
        self.assertNotIn('customer@example.com', text)
        self.assertEqual(report[1]['errno'], 13)
        self.assertTrue(report[0]['frames'])

    def test_text_redacts_credentials_identifiers_urls_and_log_injection(self):
        with patch.object(runtime, '_SECRETS', {'configured-secret'}), \
                patch.dict(os.environ, {'SECOND_CHECK_KEY': 'environment-secret'}):
            text = runtime.redact_text(
                'password="quoted secret" token=opaque configured-secret '
                'environment-secret Bearer abc.def user@example.com '
                'https://example.com/private?sig=signedvalue '
                'Serial Number: DEVICE123 username=Alice '
                '192.168.1.188 AA:BB:CC:DD:EE:FF '
                'C:\\Users\\Alice\\private.ini\nforged-entry')
        for private in ('quoted secret', 'opaque', 'configured-secret',
                        'environment-secret', 'abc.def', 'user@example.com',
                        'signedvalue', 'DEVICE123', 'Alice', '192.168.1.188',
                        'AA:BB:CC:DD:EE:FF'):
            self.assertNotIn(private, text)
        self.assertNotIn('\n', text)

    def test_structured_log_allowlist_context_and_no_raw_exception(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'logs.txt'
            with patch.object(runtime, 'log_path', return_value=path):
                try:
                    raise TimeoutError('private-argument')
                except TimeoutError as error:
                    runtime.log_diagnostic('camera.preview_failed', error=error,
                                           stage='preview', frames_seen=12,
                                           password='private-password',
                                           response='private-body')
            text = path.read_text()
        self.assertIn('[ERROR]', text)
        self.assertIn('run=', text)
        self.assertIn('TimeoutError', text)
        self.assertIn('frames_seen', text)
        self.assertNotIn('private-', text)


if __name__ == '__main__':
    unittest.main()
