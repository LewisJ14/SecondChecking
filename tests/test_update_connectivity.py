"""Updater trust, safe failure reporting and asynchronous UI regressions."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from services import update_integrity as integrity, app_helper
from update_service import UpdateService
import test_app_helpers as consumers
from test_app_helpers import up_to_date


class UpdateConnectivityTests(unittest.TestCase):
    def test_real_tk_event_loop_updates_status_without_worker_tk_calls(self):
        program = r'''
import sys, tkinter as tk
from unittest.mock import Mock, patch
sys.path.insert(0, 'src')
from app_controller import AppController
from services import app_helper
from version import __version__
root = tk.Tk()
root.withdraw()
controller = AppController.__new__(AppController)
controller.root = root
controller.update_service = Mock(current_version=__version__)
controller.version_label = tk.Label(root)
controller._version_text = 'Version ' + __version__
reply = {'update_check_version': 1, 'state': 'up_to_date',
         'current_version': __version__}
def verify():
    if controller._update_check_running:
        root.after(20, verify)
        return
    assert controller.version_label.cget('text').endswith('App is up to date')
    root.quit()
with patch.object(app_helper, 'run_helper', return_value=reply):
    controller.check_for_updates(silent=True)
    root.after(20, verify)
    root.after(3000, root.quit)
    root.mainloop()
assert not controller._update_check_running
root.destroy()
'''
        completed = subprocess.run([sys.executable, '-c', program],
            cwd=str(Path(__file__).resolve().parents[1]), capture_output=True,
            text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_certificate_failure_is_preserved_without_private_details(self):
        failure = URLError(ssl.SSLCertVerificationError(1, 'private-url-token'))
        with patch('update_service.open_release', side_effect=failure):
            with self.assertRaises(integrity.UpdateCheckError) as caught:
                UpdateService().fetch_manifest()
        self.assertEqual(caught.exception.reason, 'certificate')
        self.assertNotIn('private', str(caught.exception))
        reply = {'helper_version': 1, 'request_id': 'fixture', 'kind': 'updates',
                 'outcome': 'error', 'error_code': 'certificate',
                 'error': 'private-url-token'}
        with self.assertRaises(app_helper.HelperError) as error:
            app_helper.decode_reply(reply, 'updates', 'fixture')
        self.assertEqual(str(error.exception), integrity.CHECK_FAILURES['certificate'])

    @unittest.skipUnless(Path(r'C:\Program Files\Git\usr\bin\openssl.exe').exists(),
                         'OpenSSL fixture generator unavailable')
    def test_packaged_roots_work_without_system_roots_and_hostname_stays_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cert, key = root / 'cert.pem', root / 'key.pem'
            subprocess.run([r'C:\Program Files\Git\usr\bin\openssl.exe',
                'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
                '-out', str(cert), '-keyout', str(key)], check=True,
                capture_output=True, timeout=20)

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'fixture')

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                # Isolate the trust regression; production origin restrictions
                # remain separately covered by the release safety suite.
                with patch.object(integrity, 'safe_url'), \
                        patch.object(integrity.certifi, 'where', return_value=str(cert)), \
                        patch.object(integrity.ssl, 'create_default_context',
                            side_effect=lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)), \
                        patch.dict(os.environ, {'NO_PROXY': '*'}):
                    port = server.server_port
                    with integrity.open_release('https://localhost:%s/' % port) as response:
                        self.assertEqual(response.read(), b'fixture')
                    with self.assertRaises(URLError) as error:
                        integrity.open_release('https://127.0.0.1:%s/' % port)
                    self.assertTrue(integrity.certificate_failure(error.exception))
                    trust = integrity.release_tls_context()
                    self.assertTrue(trust.check_hostname)
                    self.assertEqual(trust.verify_mode, ssl.CERT_REQUIRED)
                    with patch.object(integrity, 'release_tls_context', return_value=
                                      ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)):
                        with self.assertRaises(URLError) as untrusted:
                            integrity.open_release('https://localhost:%s/' % port)
                        self.assertTrue(integrity.certificate_failure(untrusted.exception))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


class UpdateStatusTests(unittest.TestCase):
    controller = consumers.HelperConsumerTests.controller
    consume = consumers.HelperConsumerTests.consume

    def test_startup_failure_visible_and_manual_retry_succeeds(self):
        import app_controller
        controller, callbacks = self.controller()
        with patch.object(app_helper, 'run_helper', side_effect=TimeoutError()), \
                patch.object(app_controller.messagebox, 'showerror') as error:
            controller.check_for_updates(silent=True)
            self.consume(callbacks)
            self.assertIn('failed', controller._update_check_status)
            self.assertFalse(controller._update_check_running)
            error.assert_not_called()
        with patch.object(app_helper, 'run_helper', return_value=up_to_date()), \
                patch.object(app_controller.messagebox, 'showinfo') as info:
            controller.check_for_updates()
            self.consume(callbacks)
            info.assert_called_once()
            self.assertEqual(controller._update_check_status, 'App is up to date')

    def test_available_versioned_reply_opens_update_prompt(self):
        import app_controller
        controller, callbacks = self.controller()
        reply = {'update_check_version': 1, 'state': 'update_available',
                 'version': '9.0.0', 'notes': 'Fixture release'}
        controller._begin_update = Mock()
        with patch.object(app_helper, 'run_helper', return_value=reply), \
                patch.object(app_controller.messagebox, 'askyesno', return_value=True):
            controller.check_for_updates(silent=True)
            self.consume(callbacks)
        self.assertEqual(controller._begin_update.call_args.args[0].version, '9.0.0')

    def test_manual_click_during_startup_coalesces_and_uses_ui_thread(self):
        import app_controller
        controller, callbacks = self.controller()
        ready, release = threading.Event(), threading.Event()
        ui_thread = threading.get_ident()
        controller.root.after.side_effect = lambda delay, callback: (
            self.assertEqual(threading.get_ident(), ui_thread), callbacks.put(callback))[1]

        def pending(*args, **kwargs):
            ready.set()
            release.wait(3)
            return up_to_date()

        with patch.object(app_helper, 'run_helper', side_effect=pending) as run, \
                patch.object(app_controller.messagebox, 'showinfo') as info:
            controller.check_for_updates(silent=True)
            self.assertTrue(ready.wait(3))
            controller.check_for_updates()
            release.set()
            self.consume(callbacks)
            run.assert_called_once()
            info.assert_called_once()

    def test_late_result_does_not_touch_closed_window(self):
        import app_controller
        controller, callbacks = self.controller()
        with patch.object(app_helper, 'run_helper', return_value=up_to_date()), \
                patch.object(app_controller.messagebox, 'showinfo') as info:
            controller.check_for_updates()
            controller._update_ui_closed = True
            self.consume(callbacks)
            info.assert_not_called()
