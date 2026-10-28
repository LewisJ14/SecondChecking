"""SC21 tests: local TLS fixtures and mocked elevation, never real maintenance."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from services import transport, configuration, maintenance, auth_service
from db import database


class TransportTests(unittest.TestCase):
    def test_plaintext_is_denied_before_password_or_token_can_be_sent(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(transport.requests, 'request') as send:
            for url in ('http://service.invalid', 'http://127.0.0.1', 'http://localhost'):
                with self.assertRaises(transport.TransportError):
                    transport.request('POST', url + '/login', json={'password': 'fixture'})
            send.assert_not_called()

    def test_http_exception_requires_explicit_literal_loopback(self):
        with patch.dict(os.environ, {'SECOND_CHECK_ALLOW_HTTP_LOOPBACK': '1'}):
            transport.validate_url('http://127.0.0.1:1234')
            transport.validate_url('http://[::1]:1234')
            for url in ('http://192.168.1.1', 'http://localhost', 'http://127.0.0.1.evil.invalid'):
                with self.assertRaises(transport.TransportError):
                    transport.validate_url(url)

    def test_credentials_fragment_query_and_ambiguous_paths_are_rejected(self):
        for url in ('https://user:password@service.invalid', 'https://service.invalid?secret',
                    'https://service.invalid#fragment', 'https://service.invalid/%2e%2e/path',
                    'https://service.invalid\\evil', 'https://service.invalid:bad'):
            with self.assertRaises(transport.TransportError):
                transport.validate_url(url)

    def test_callers_cannot_disable_tls_or_enable_redirects(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(transport.requests, 'post', return_value=Mock(status_code=200)) as send:
            transport.post('https://service.invalid/login', verify=False, allow_redirects=True)
        self.assertIs(send.call_args.kwargs['verify'], True)
        self.assertIs(send.call_args.kwargs['allow_redirects'], False)
        self.assertEqual(send.call_args.kwargs['timeout'], 15)

    def test_tls_and_connection_errors_are_redacted(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(transport.requests, 'get', side_effect=transport.requests.exceptions.SSLError('password-fixture token-fixture')):
            with self.assertRaises(transport.TransportError) as error:
                transport.get('https://service.invalid')
        self.assertNotIn('password-fixture', str(error.exception))
        self.assertNotIn('token-fixture', str(error.exception))

    def test_custom_ca_must_be_an_existing_absolute_file(self):
        for value in ('', 'relative.pem', r'C:\not-existing-sc21-ca.pem'):
            with patch.dict(os.environ, {'SECOND_CHECK_CA_BUNDLE': value}), \
                    patch.object(transport.requests, 'get') as send:
                with self.assertRaises(transport.TransportError):
                    transport.get('https://service.invalid')
                send.assert_not_called()

    def test_database_connections_require_verified_tls_in_both_paths(self):
        from unittest.mock import MagicMock
        settings = {'host': 'database.invalid', 'user': 'fixture', 'password': 'fixture', 'database': 'fixture'}
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        with patch.object(database, 'load_database_settings', return_value=settings), \
                patch.object(configuration, 'read_config', return_value=__import__('configparser').ConfigParser()), \
                patch.dict(os.environ, {}, clear=True), \
                patch.object(database.MySQLdb, 'connect', return_value=connection) as connect, \
                patch.object(database, 'validate_schema'):
            database.check_database_connection()
            database.get_db_connection(show_errors=False)
        self.assertEqual(connect.call_count, 2)
        for call in connect.call_args_list:
            self.assertEqual(call.kwargs['ssl_mode'], 'VERIFY_IDENTITY')
            self.assertIs(call.kwargs['local_infile'], False)

    def test_database_plaintext_override_cannot_target_remote_hosts(self):
        with patch.dict(os.environ, {'DB_ALLOW_INSECURE_LOOPBACK': '1'}):
            self.assertEqual(configuration.database_tls_options('127.0.0.1')['ssl_mode'], 'DISABLED')
            for host in ('db.invalid', '192.168.1.1', 'localhost'):
                with self.assertRaises(configuration.ConfigurationError):
                    configuration.database_tls_options(host)


class MaintenanceBoundaryTests(unittest.TestCase):
    def test_only_fixed_actions_can_reach_uac(self):
        with patch.object(maintenance, '_shell_execute') as launch:
            for action in ('powershell', 'cmd', 'arbitrary.ps1', 'sysprep /generalize', '../script'):
                with self.assertRaises(ValueError):
                    maintenance.run_elevated(action)
            launch.assert_not_called()

    def test_fresh_service_permission_is_required_for_both_actions(self):
        with patch.object(auth_service, 'authorize', side_effect=RuntimeError('locked')), \
                patch.object(maintenance, '_shell_execute') as launch:
            for action in (maintenance.run_windows_updates, maintenance.run_sysprep_shutdown):
                with self.assertRaisesRegex(RuntimeError, 'locked'):
                    action()
            launch.assert_not_called()

    def test_approval_cancellation_does_not_claim_success(self):
        import pywintypes
        import winerror
        for error in (OSError(winerror.ERROR_CANCELLED, 'cancelled'),
                      pywintypes.error(winerror.ERROR_CANCELLED, 'ShellExecuteEx', 'cancelled')):
            with patch.object(maintenance, '_shell_execute', side_effect=error):
                with self.assertRaisesRegex(maintenance.MaintenanceCancelled, 'cancelled'):
                    maintenance.run_elevated('sysprep')

    def test_other_startup_failures_are_not_reported_as_cancellation(self):
        with patch.object(maintenance, '_shell_execute', side_effect=OSError(5, 'private detail')):
            with self.assertRaises(maintenance.MaintenanceError) as caught:
                maintenance.run_elevated('sysprep')
        self.assertNotIsInstance(caught.exception, maintenance.MaintenanceCancelled)
        self.assertNotIn('private detail', str(caught.exception))

    def test_missing_module_stops_before_uac(self):
        with patch.object(auth_service, 'authorize') as authorize, \
                patch.object(maintenance.subprocess, 'run', return_value=Mock(
                    returncode=0, stdout='SC_UPDATE_MODULE_MISSING\n')) as probe, \
                patch.object(maintenance, '_shell_execute') as elevate:
            with self.assertRaisesRegex(maintenance.MaintenanceError, 'provision PSWindowsUpdate'):
                maintenance.run_windows_updates()
        authorize.assert_called_once_with('maintenance')
        elevate.assert_not_called()
        options = probe.call_args.kwargs
        self.assertEqual(options['timeout'], 15)
        command = base64.b64decode(probe.call_args.args[0][-1]).decode('utf-16-le')
        self.assertIn("GetFolderPath('ProgramFiles')", command)
        self.assertIn('Get-Module -ListAvailable', command)
        self.assertNotIn('Install-Module', command)
        self.assertNotIn('Get-WindowsUpdate', command)

    def test_restricted_policy_stops_before_elevation_without_changing_policy(self):
        with patch.object(auth_service, 'authorize') as authorize, \
                patch.object(maintenance.subprocess, 'run', return_value=Mock(
                    returncode=0, stdout='SC_UPDATE_POLICY_RESTRICTED\n')) as probe, \
                patch.object(maintenance, '_shell_execute') as elevate:
            with self.assertRaisesRegex(maintenance.MaintenanceError, 'policy blocks loading') as caught:
                maintenance.run_windows_updates()
        authorize.assert_called_once_with('maintenance')
        elevate.assert_not_called()
        self.assertIn('has not changed the policy', str(caught.exception))
        command = base64.b64decode(probe.call_args.args[0][-1]).decode('utf-16-le')
        self.assertIn('Get-ExecutionPolicy', command)
        self.assertNotIn('Set-ExecutionPolicy', command)
        self.assertNotIn('-ExecutionPolicy', probe.call_args.args[0])
        self.assertNotIn('Import-Module', command)

    def test_ready_module_continues_to_fixed_elevated_action(self):
        with patch.object(auth_service, 'authorize'), \
                patch.object(maintenance.subprocess, 'run', return_value=Mock(
                    returncode=0, stdout='SC_UPDATE_MODULE_READY\n')), \
                patch.object(maintenance, 'run_elevated') as elevate:
            maintenance.run_windows_updates(timeout=42)
        elevate.assert_called_once_with('windows-update', 42)

    def test_unknown_or_timed_out_preflight_does_not_elevate(self):
        for outcome in (Mock(returncode=0, stdout=''),
                        Mock(returncode=0, stdout='private unexpected output'),
                        Mock(returncode=1, stdout='SC_UPDATE_MODULE_READY'),
                        Mock(returncode=1, stdout='SC_UPDATE_POLICY_RESTRICTED'),
                        subprocess.TimeoutExpired('probe', 15)):
            with patch.object(auth_service, 'authorize'), \
                    patch.object(maintenance.subprocess, 'run') as probe, \
                    patch.object(maintenance, '_shell_execute') as elevate:
                if isinstance(outcome, Exception):
                    probe.side_effect = outcome
                else:
                    probe.return_value = outcome
                with self.assertRaisesRegex(maintenance.MaintenanceError, 'Could not check') as caught:
                    maintenance.run_windows_updates()
                self.assertNotIn('private', str(caught.exception))
                elevate.assert_not_called()

    def test_denied_authorization_does_not_run_preflight(self):
        with patch.object(auth_service, 'authorize', side_effect=RuntimeError('locked')), \
                patch.object(maintenance.subprocess, 'run') as probe:
            with self.assertRaisesRegex(RuntimeError, 'locked'):
                maintenance.run_windows_updates()
        probe.assert_not_called()

    def test_gui_expected_outcomes_are_clear_and_reset_busy_state(self):
        with patch.dict(sys.modules, {'wmi': Mock()}):
            import app_controller
        for error, title, info in (
            (maintenance.MaintenanceCancelled('Administrator approval was cancelled.'),
             'Windows Update cancelled', True),
            (maintenance.MaintenanceError('Ask an administrator to provision PSWindowsUpdate.'),
             'Windows Update', False),
        ):
            controller = app_controller.AppController.__new__(app_controller.AppController)
            controller._require_operator = Mock(return_value=True)
            controller._update_busy = Mock(return_value=False)
            controller._maintenance_running = False
            controller.update_status = Mock()
            controller.root = Mock()
            controller.root.after.side_effect = lambda delay, callback: callback()
            def start_thread(**kwargs):
                thread = Mock()
                thread.start.side_effect = kwargs['target']
                return thread
            with patch.object(app_controller.messagebox, 'askyesno', return_value=True), \
                    patch.object(app_controller.messagebox, 'showinfo') as show_info, \
                    patch.object(app_controller.messagebox, 'showerror') as show_error, \
                    patch.object(app_controller.threading, 'Thread', side_effect=start_thread), \
                    patch.object(maintenance, 'run_windows_updates', side_effect=error):
                controller.run_windows_update_script()
            (show_info if info else show_error).assert_called_once_with(title, str(error))
            (show_error if info else show_info).assert_not_called()
            self.assertFalse(controller._maintenance_running)

    def test_exit_failure_timeout_and_success_close_only_owned_handle(self):
        import win32event
        import win32process
        for wait, code, message in ((win32event.WAIT_TIMEOUT, 0, 'unconfirmed'),
                                    (win32event.WAIT_OBJECT_0, 1, 'failed'),
                                    (win32event.WAIT_OBJECT_0, 0, None)):
            handle = Mock()
            with patch.object(maintenance, '_shell_execute', return_value=handle), \
                    patch.object(win32event, 'WaitForSingleObject', return_value=wait), \
                    patch.object(win32process, 'GetExitCodeProcess', return_value=code):
                if message:
                    with self.assertRaisesRegex(RuntimeError, message):
                        maintenance.run_elevated('sysprep', timeout=1)
                else:
                    maintenance.run_elevated('sysprep', timeout=1)
            handle.Close.assert_called_once()

    def test_elevation_uses_system_powershell_fixed_script_no_credentials(self):
        from win32com.shell import shell
        with patch.object(shell, 'ShellExecuteEx', return_value={'hProcess': 'fixture-handle'}) as launch:
            self.assertEqual(maintenance._shell_execute(maintenance.action_script('sysprep')), 'fixture-handle')
        options = launch.call_args.kwargs
        self.assertEqual(options['lpVerb'], 'runas')
        self.assertTrue(options['lpFile'].lower().endswith('windowspowershell\\v1.0\\powershell.exe'))
        command = base64.b64decode(options['lpParameters'].split()[-1]).decode('utf-16-le')
        self.assertIn('/oobe /shutdown', command)
        self.assertNotIn('/generalize', command)
        self.assertNotIn('taskkill', command.lower())
        self.assertNotIn('Second-Check-Key', command)
        self.assertIn('Global\\SecondCheckingMaintenance', command)

    def test_normal_gui_does_not_request_elevation(self):
        import xml.etree.ElementTree as ET
        node = ET.parse(ROOT / 'app.manifest').find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
        self.assertEqual(node.get('level'), 'asInvoker')
        self.assertIn('uac_admin=False', (ROOT / 'main.spec').read_text())
        script = maintenance.action_script('windows-update')
        self.assertNotIn('Install-Module', script)
        self.assertNotIn('Install-PackageProvider', script)
        self.assertIn('-IgnoreReboot', script)
        self.assertIn("GetFolderPath('ProgramFiles')", script)

    def test_windows_update_decline_keeps_the_bench_unchanged(self):
        with patch.dict(sys.modules, {'wmi': Mock()}):
            import app_controller
        controller = app_controller.AppController.__new__(app_controller.AppController)
        controller._require_operator = Mock(return_value=True)
        controller._update_busy = Mock(return_value=False)
        controller._maintenance_running = False
        with patch.object(app_controller.messagebox, 'askyesno', return_value=False), \
                patch.object(app_controller.threading, 'Thread') as start:
            controller.run_windows_update_script()
        start.assert_not_called()
        self.assertFalse(controller._maintenance_running)


OPENSSL = Path(r'C:\Program Files\Git\usr\bin\openssl.exe')


@unittest.skipUnless(OPENSSL.exists(), 'OpenSSL required for temporary TLS fixtures')
class LiveTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.cert = Path(cls.temp.name) / 'localhost.pem'
        cls.key = Path(cls.temp.name) / 'key.pem'
        subprocess.run([str(OPENSSL), 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(cls.key), '-out', str(cls.cert), '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'],
                       check=True, capture_output=True, timeout=30)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.server.received.append(dict(self.headers))
                self.send_response(302 if self.path == '/redirect' else 200)
                if self.path == '/redirect':
                    self.send_header('Location', 'https://never-contact.invalid/credential-target')
                self.end_headers()
                self.wfile.write(b'{"success":true}')

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.received = []
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cls.cert), str(cls.key))
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'https://localhost:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def test_trusted_temporary_ca_succeeds_without_system_trust_changes(self):
        with patch.dict(os.environ, {'SECOND_CHECK_CA_BUNDLE': str(self.cert), 'NO_PROXY': '*'}):
            response = transport.get(self.base, timeout=3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'success': True})

    def test_untrusted_and_wrong_hostname_certificates_are_rejected(self):
        with patch.dict(os.environ, {'NO_PROXY': '*'}):
            os.environ.pop('SECOND_CHECK_CA_BUNDLE', None)
            with self.assertRaises(transport.TransportError):
                transport.get(self.base, timeout=3)
        with patch.dict(os.environ, {'SECOND_CHECK_CA_BUNDLE': str(self.cert), 'NO_PROXY': '*'}):
            with self.assertRaises(transport.TransportError):
                transport.get(self.base.replace('localhost', '127.0.0.1'), timeout=3)

    def test_live_redirect_is_not_followed_with_session_credentials(self):
        before = len(self.server.received)
        with patch.dict(os.environ, {'SECOND_CHECK_CA_BUNDLE': str(self.cert), 'NO_PROXY': '*'}):
            with self.assertRaisesRegex(transport.TransportError, 'redirect'):
                transport.get(self.base + '/redirect', headers={
                    'X-Second-Check-Key': 'fixture', 'X-Second-Check-Session': 'fixture-token'}, timeout=3)
        self.assertEqual(len(self.server.received), before + 1)


if __name__ == '__main__':
    unittest.main()
