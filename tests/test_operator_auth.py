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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from services import operator_session as session, auth_service
from operator_fixture import sign_in


class OperatorSessionTests(unittest.TestCase):
    def tearDown(self):
        session.clear()

    def test_memory_only_session_scopes_headers_permissions_and_expiry(self):
        sign_in()
        self.assertTrue(session.allowed("remove"))
        self.assertTrue(session.allowed("maintenance"))
        self.assertFalse(session.allowed("manage_users"))
        self.assertEqual(session.headers("https://other.invalid"), {})
        self.assertIn("X-Second-Check-Session", session.headers("https://isolated/"))
        with patch.object(session.time, "monotonic", return_value=time.monotonic() + 4000):
            self.assertFalse(session.allowed("assign"))
            self.assertEqual(session.headers("https://isolated"), {})
        generation = session.generation()
        old = session.clear()
        self.assertTrue(old)
        self.assertGreater(session.generation(), generation)
        self.assertFalse(session.allowed("test"))

    def test_reset_and_malformed_sessions_cannot_grant_permissions(self):
        with self.assertRaises(ValueError):
            session.install("https://isolated", {"user": {"id": 1}})
        session.install("https://isolated", {"session_token": "reset", "expires_in": 60,
            "reset_required": True, "user": {"id": 1, "username": "tester",
            "role": "user", "permissions": ["assign"]}})
        self.assertFalse(session.allowed("assign"))

    def test_authentication_uses_server_and_keeps_hashes_out_of_client(self):
        body = {"session_token": "secret-token", "expires_in": 60,
                "reset_required": False, "user": {"id": 1, "username": "tester",
                "role": "user", "permissions": ["test"]}}
        with patch.object(auth_service, "api_request", return_value=("https://isolated", body)) as api:
            result, error = auth_service.authenticate("tester", "password")
            self.assertIsNone(error)
            self.assertIs(result, body)
            self.assertEqual(api.call_args.args[2], {"username": "tester", "password": "password"})
        self.assertFalse(hasattr(auth_service, "fetch_user_record"))
        self.assertFalse(hasattr(auth_service, "get_db_connection"))

    def test_network_errors_redact_credentials_and_401_clears_session(self):
        from utils import helpers
        sign_in()
        with patch.object(auth_service, "service_settings", return_value=("https://isolated", "private-key")), \
                patch.object(auth_service.requests, "request", side_effect=auth_service.requests.ConnectionError("private-key secret-token")):
            with self.assertRaises(RuntimeError) as caught:
                auth_service.api_request("GET", "/session")
            self.assertNotIn("private-key", str(caught.exception))
        with patch.object(auth_service, "service_settings", return_value=("https://isolated", "private-key")), \
                patch.object(auth_service.requests, "request", return_value=Mock(status_code=401, json=lambda: {})):
            with self.assertRaises(RuntimeError):
                auth_service.api_request("GET", "/session")
        self.assertFalse(session.allowed("test"))

    def test_note_save_uses_authenticated_service_and_no_database_write(self):
        import main_logic
        with patch.object(auth_service, "api_request", return_value=("https://isolated", {"success": True})) as api:
            main_logic.save_order_note_for_order_id(12, "note")
        api.assert_called_once_with("POST", "/notes/12", {"notes": "note"})

    def test_late_unauthorized_response_does_not_clear_new_session(self):
        from utils import helpers
        sign_in()
        def response(*args, **kwargs):
            sign_in()
            return Mock(status_code=401, json=lambda: {})
        with patch.object(auth_service, "service_settings", return_value=("https://isolated", "key")), \
                patch.object(auth_service.requests, "request", side_effect=response):
            with self.assertRaises(RuntimeError):
                auth_service.api_request("GET", "/session")
        self.assertTrue(session.allowed("test"))

    def test_unauthenticated_assignment_does_not_create_a_pending_request(self):
        from services import assignment_api
        with patch.object(assignment_api.requests, "get", return_value=Mock(status_code=401)), \
                patch.object(assignment_api, "_pending_directory") as pending:
            ok, body = assignment_api.post_assignment(
                "https://isolated", "key", "/api/stock_units/check-report", {})
        self.assertFalse(ok)
        self.assertIn("Sign in again", body["error"])
        pending.assert_not_called()

    def test_official_hardware_queue_rechecks_permission_before_start(self):
        from ui.tests import TestsWindow
        panel = TestsWindow.__new__(TestsWindow)
        panel._authorization_check = Mock(return_value=False)
        panel._cancel_auto_wifi = Mock()
        panel._start_queue([], False)
        panel._authorization_check.assert_called_once_with("test")
        panel._cancel_auto_wifi.assert_not_called()


class OperatorInterfaceTests(unittest.TestCase):
    def test_login_request_and_lock_are_responsive_and_preserve_drafts(self):
        if not os.environ.get("SECOND_CHECK_AUTH_UI_CHILD"):
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                     "OperatorInterfaceTests"],
                env=dict(os.environ, SECOND_CHECK_AUTH_UI_CHILD="1"),
                capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        from auth.login import LoginPanel
        import app_controller
        root = tk.Tk()
        root.withdraw()
        try:
            panel = LoginPanel.__new__(LoginPanel)
            panel.parent = root
            panel.frame = tk.Frame(root)
            finished = []
            release = threading.Event()
            worker_threads = []
            def operation():
                worker_threads.append(threading.get_ident())
                release.wait(3)
                return "response"
            panel._start_request(operation, finished.append)
            root.update()
            self.assertFalse(finished)
            release.set()
            deadline = time.monotonic() + 2
            while not finished and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertEqual(finished, ["response"])
            self.assertNotEqual(worker_threads, [threading.get_ident()])
            panel.frame.destroy()
            sign_in()
            c = app_controller.AppController.__new__(app_controller.AppController)
            c.root = root
            c.current_user = SimpleNamespace(username="tester")
            c._search_inflight = False
            c._search_generation = 0
            c._note_save_inflight = 0
            c._maintenance_running = False
            c._preserve_check_draft = Mock(return_value=True)
            with patch.object(auth_service, "revoke"), patch.object(app_controller.subprocess, "Popen") as spawn:
                c.lock_operator()
                self.assertTrue(c._operator_locked)
                self.assertFalse(session.allowed("assign"))
                self.assertIsNone(c.current_user)
                c._preserve_check_draft.assert_called_once()
                buttons = [w for w in root.winfo_children() if isinstance(w, app_controller.ttk.Button)]
                buttons[0].invoke()
                spawn.assert_called_once()
        finally:
            session.clear()
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == "__main__":
    unittest.main()
