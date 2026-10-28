"""Helper IPC and packaged asset regressions; no real maintenance or hardware I/O."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from services import app_helper as helper, maintenance
from services.mdm_evidence import evidence
from version import __version__


def up_to_date():
    return {"update_check_version": 1, "state": "up_to_date", "current_version": __version__}


class AppHelperTests(unittest.TestCase):
    def worker(self, kind, payload=None, failure=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            request_id = str(uuid4())
            (path / "request.json").write_text(json.dumps({
                "kind": kind, "arguments": {"request_id": request_id}}), encoding="utf-8")
            target = "update_payload" if kind == "updates" else "mdm_payload"
            with patch.object(helper, target, return_value=payload,
                              side_effect=RuntimeError("private-detail") if failure else None), \
                    patch.object(sys, "stdout", None), patch.object(sys, "stderr", None):
                helper.run_worker(path)
            self.assertFalse((path / "result.tmp").exists())
            return json.loads((path / "result.json").read_text(encoding="utf-8")), request_id

    def test_worker_returns_versioned_update_result_without_standard_streams(self):
        for payload in (up_to_date(), {"update_check_version": 1,
                "state": "update_available", "version": "999.0",
                "download_url": "https://example.invalid/app.exe"}):
            reply, request_id = self.worker("updates", payload)
            self.assertEqual(helper.decode_reply(reply, "updates", request_id), payload)

    def test_mdm_retains_qualified_evidence_and_never_claims_tenant_verification(self):
        payload = evidence("no_local_indicators", "Mock registry evidence")
        reply, request_id = self.worker("mdm", payload)
        self.assertEqual(helper.decode_reply(reply, "mdm", request_id), payload)
        for payload in ({}, dict(payload, tenant_verification="verified")):
            reply, request_id = self.worker("mdm", payload)
            with self.assertRaises(helper.HelperError):
                helper.decode_reply(reply, "mdm", request_id)

    def test_error_missing_malformed_and_wrong_request_are_not_success(self):
        reply, request_id = self.worker("updates", failure=True)
        self.assertNotIn("private-detail", json.dumps(reply))
        for value in (reply, {}, [], None, dict(reply, outcome="ok", payload={}),
                      dict(reply, request_id=str(uuid4())), dict(reply, helper_version=2)):
            with self.assertRaises((helper.HelperError, ValueError)):
                helper.decode_reply(value, "updates", request_id)

    def test_parent_timeout_and_failure_always_close_owned_job(self):
        for failure in (TimeoutError("timeout"), RuntimeError("missing result"),
                        json.JSONDecodeError("bad", "x", 0)):
            job = Mock()
            job.poll.side_effect = failure
            with patch.object(helper, "AppHelperJob", return_value=job):
                with self.assertRaises(type(failure)):
                    helper.run_helper("updates")
            job.close.assert_called_once()

    def test_confirmed_payload_requires_successful_child_exit(self):
        for code in (0, 1):
            job = Mock()
            job.poll.return_value = up_to_date()
            job.process.wait.return_value = code
            with patch.object(helper, "AppHelperJob", return_value=job):
                if code == 0:
                    self.assertEqual(helper.run_helper("updates"), up_to_date())
                else:
                    with self.assertRaises(helper.HelperError):
                        helper.run_helper("updates")
            job.close.assert_called_once()

    def test_actual_source_dispatch_without_gui_exits_on_bad_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "request.json").write_text(json.dumps({"kind": "unknown", "arguments": {
                "request_id": str(uuid4())}}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] /
                                    "src/main.py"), "--app-helper", directory],
                                    cwd=directory, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(json.loads((path / "result.json").read_text())["outcome"], "error")

    def test_frozen_job_uses_own_executable_and_unique_request_paths(self):
        jobs = []
        process = Mock()
        process.poll.return_value = 0
        with patch.object(sys, "frozen", True, create=True), \
                patch("services.hardware_job.subprocess.Popen", return_value=process) as launch:
            try:
                for _ in range(2):
                    job = helper.AppHelperJob("mdm")
                    jobs.append(job)
                    self.assertEqual(launch.call_args.args[0], [sys.executable, "--app-helper", str(job.directory)])
                    self.assertEqual(launch.call_args.kwargs["stdout"], subprocess.DEVNULL)
                self.assertNotEqual(jobs[0].directory, jobs[1].directory)
                self.assertNotEqual(jobs[0].request_id, jobs[1].request_id)
            finally:
                for job in jobs:
                    job.close()

    def test_update_check_does_not_run_certificate_maintenance(self):
        from update_service import UpdateService, UpdateManifest
        service = UpdateService()
        with patch.object(service, "fetch_manifest", return_value=UpdateManifest(__version__)), \
                patch("update_service.subprocess.run") as certs:
            self.assertIsNone(service.check_for_updates())
        certs.assert_not_called()


class PackagedMaintenanceTests(unittest.TestCase):
    def test_source_and_frozen_asset_paths_and_missing_script(self):
        self.assertEqual(maintenance.windows_update_script(), Path(__file__).resolve().parents[1] / "src/Script.ps1")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "_MEIPASS", directory, create=True):
            with self.assertRaisesRegex(RuntimeError, "missing"):
                maintenance.windows_update_script()
            script = Path(directory) / "Script.ps1"
            script.write_text("exit 0", encoding="utf-8")
            self.assertEqual(maintenance.windows_update_script(), script)

    def test_maintenance_requires_service_authorization_and_scoped_elevation(self):
        from services import auth_service
        with patch.object(auth_service, "authorize") as authorize, \
                patch.object(maintenance, "check_windows_update_requirements") as requirements, \
                patch.object(maintenance, "run_elevated") as run:
            maintenance.run_windows_updates()
            authorize.assert_called_once_with("maintenance")
            requirements.assert_called_once_with()
            run.assert_called_once_with("windows-update", 1800)
        with patch.object(auth_service, "authorize", side_effect=RuntimeError("locked")), \
                patch.object(maintenance, "run_elevated") as run:
            with self.assertRaisesRegex(RuntimeError, "locked"):
                maintenance.run_windows_updates()
            run.assert_not_called()

    def test_spec_includes_script_and_powershell_parses_without_execution(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn("('src/Script.ps1', '.')", (root / "main.spec").read_text())
        self.assertIn("$ErrorActionPreference = 'Stop'", (root / "src/Script.ps1").read_text())
        # Parser only: no provider/module installation or Windows Update runs.
        path = str(root / "src/Script.ps1").replace("'", "''")
        code = "$tokens=$null; $errors=$null; [System.Management.Automation.Language.Parser]::ParseFile('" + path + "',[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) { exit 1 }"
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0)


class HelperConsumerTests(unittest.TestCase):
    def controller(self):
        import queue
        from app_controller import AppController
        controller = AppController.__new__(AppController)
        callbacks = queue.Queue()
        controller.root = Mock()
        controller.root.after.side_effect = lambda delay, callback: callbacks.put(callback)
        controller.update_service = Mock(current_version=__version__)
        controller._operator_locked = False
        controller._showing_default_specs = True
        controller._search_inflight = False
        controller._mdm_refresh_started = False
        controller._apply_mdm_status_to_footer_only = Mock()
        return controller, callbacks

    def consume(self, callbacks):
        callback = callbacks.get(timeout=3)
        callback()

    def test_updater_uses_file_payload_and_errors_never_become_no_update(self):
        import app_controller
        controller, callbacks = self.controller()
        with patch.object(helper, "run_helper", return_value=up_to_date()) as run, \
                patch.object(app_controller.messagebox, "showinfo") as info:
            controller.check_for_updates()
            self.consume(callbacks)
            self.assertEqual(info.call_args.args[0], "No Updates")
            run.assert_called_once_with("updates", timeout=60)
        with patch.object(helper, "run_helper", side_effect=TimeoutError("timed out")), \
                patch.object(app_controller, "log_event"), \
                patch.object(app_controller.messagebox, "showerror") as error, \
                patch.object(app_controller.messagebox, "showinfo") as info:
            controller.check_for_updates()
            self.consume(callbacks)
            error.assert_called_once()
            info.assert_not_called()

    def test_mdm_timeout_becomes_qualified_error_on_ui_thread(self):
        import app_controller
        controller, callbacks = self.controller()
        with patch.object(helper, "run_helper", side_effect=TimeoutError("timeout")), \
                patch.object(app_controller, "log_event"):
            controller._refresh_mdm_status_async()
            self.consume(callbacks)
        self.assertEqual(controller.mdm_status["state"], "error")
        self.assertEqual(controller.mdm_status["tenant_verification"], "not_checked")
        controller._apply_mdm_status_to_footer_only.assert_called_once()
