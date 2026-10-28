"""SC18 uses disposable files and mocked publisher/launch boundaries."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import update_service as updater
from services import update_integrity as integrity, update_transaction as transaction
from services.update_process import fresh_environment
from version import __version__

PIN = "a" * 64
OLD = b"MZ" + b"working-original" * 20
NEW = b"MZ" + b"candidate-update" * 20
ROOT = "https://github.com/lewisj14/SecondChecking/releases/"


def manifest_data(version="9.0.0"):
    return {"version": version, "download_url": ROOT + "download/v" + version + "/SecondChecking-" + version + ".exe",
            "release_page": ROOT + "tag/v" + version,
            "sha256": hashlib.sha256(NEW).hexdigest(), "size": len(NEW)}


class Response(io.BytesIO):
    def __init__(self, data, length=None):
        super().__init__(data)
        self.headers = {} if length is None else {"Content-Length": str(length)}


class ReleaseValidationTests(unittest.TestCase):
    def test_rejects_wrong_origin_plaintext_credentials_and_encoded_traversal(self):
        for value in ("http://github.com/lewisj14/SecondChecking/releases/latest/download/update.json",
                      "https://evil.invalid/update.json", "https://github.com/other/repo/releases/x",
                      "https://user:secret@github.com/lewisj14/SecondChecking/releases/x",
                      ROOT + "%2e%2e/other", ROOT + "../other", ROOT + "tag/v1.0.0?token=secret"):
            with self.assertRaises(integrity.UpdateError) as caught:
                integrity.safe_url(value)
            self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(integrity.safe_url(ROOT + "latest/download/update.json"), ROOT + "latest/download/update.json")
        integrity.safe_url("https://release-assets.githubusercontent.com/asset?sig=opaque", redirect=True)
        with self.assertRaises(integrity.UpdateError):
            integrity.safe_url("http://release-assets.githubusercontent.com/asset", redirect=True)

    def test_strict_manifest_versions_types_hashes_size_and_artifact_identity(self):
        self.assertEqual(updater.parse_manifest(manifest_data()).version, "9.0.0")
        for changes in ({"version": "9.0.0-injected"}, {"version": "../9.0.0"},
                        {"version": "01.2.3"}, {"size": True}, {"size": integrity.MAX_BINARY + 1},
                        {"sha256": "not-a-hash"}, {"notes": []},
                        {"download_url": ROOT + "download/v9.0.0/another.exe"},
                        {"release_page": ROOT + "tag/v8.0.0"}):
            with self.assertRaises(integrity.UpdateError):
                updater.parse_manifest(dict(manifest_data(), **changes))
        for value in ([], None, "invalid"):
            with self.assertRaises(integrity.UpdateError):
                updater.parse_manifest(value)

    def test_manifest_size_and_decode_errors_cannot_be_no_update(self):
        service = updater.UpdateService()
        for body in (b"x" * (integrity.MAX_MANIFEST + 1), b"broken-json", b"[]"):
            with patch.object(updater, "open_release", return_value=Response(body)):
                with self.assertRaises(integrity.UpdateError):
                    service.check_for_updates()
        with patch.object(service, "fetch_manifest", return_value=updater.UpdateManifest(__version__)):
            self.assertIsNone(service.check_for_updates())

    def test_manual_fallback_never_requests_shutdown_or_download(self):
        service = updater.UpdateService()
        with patch.object(service, "_can_auto_update", return_value=True), \
                patch.dict(os.environ, {"APP_UPDATE_SIGNER_SHA256": ""}), \
                patch.object(updater.webbrowser, "open", return_value=True) as browser, \
                patch.object(service, "prepare_update") as prepare:
            self.assertFalse(service.launch_update(updater.parse_manifest(manifest_data())))
            prepare.assert_not_called()
            browser.assert_called_once_with(ROOT + "tag/v9.0.0")
        with patch.object(updater.webbrowser, "open", return_value=False):
            with self.assertRaises(integrity.UpdateError):
                service.launch_update(updater.UpdateManifest("9.0.0"))

    def test_newer_release_requires_pinned_publisher_hash_and_size(self):
        service = updater.UpdateService()
        with patch.object(service, "_can_auto_update", return_value=True), \
                patch.dict(os.environ, {"APP_UPDATE_SIGNER_SHA256": PIN}):
            self.assertTrue(service.can_auto_install(updater.parse_manifest(manifest_data())))
            self.assertFalse(service.can_auto_install(updater.UpdateManifest("9.0.0")))
            with self.assertRaises(integrity.UpdateError):
                service.prepare_update(updater.parse_manifest(manifest_data("0.0.1")))

    def test_download_streams_exact_content_and_rejects_corruption_or_interruption(self):
        release = updater.parse_manifest(manifest_data())
        with TemporaryDirectory() as directory:
            for body, length, good in ((NEW, len(NEW), True), (b"x" * len(NEW), len(NEW), False),
                                       (NEW[:-1], None, False), (NEW + b"extra", None, False),
                                       (NEW, len(NEW) + 1, False)):
                with patch.object(integrity, "open_release", return_value=Response(body, length)):
                    if good:
                        path = integrity.download(release, directory)
                        self.assertEqual(path.read_bytes(), NEW)
                        path.unlink()
                    else:
                        with self.assertRaises(integrity.UpdateError):
                            integrity.download(release, directory)
                        self.assertFalse((Path(directory) / "candidate.exe").exists())
                        self.assertFalse((Path(directory) / "candidate.part").exists())

    def test_cancelled_download_and_network_failure_leave_no_partial(self):
        release = updater.parse_manifest(manifest_data())
        cancelled = threading.Event()
        cancelled.set()
        with TemporaryDirectory() as directory:
            with patch.object(integrity, "open_release", return_value=Response(NEW)):
                with self.assertRaisesRegex(integrity.UpdateError, "cancelled"):
                    integrity.download(release, directory, cancel=cancelled)
            response = Response(NEW)
            response.read = Mock(side_effect=[NEW[:10], OSError("interrupted")])
            with patch.object(integrity, "open_release", return_value=response):
                with self.assertRaises(OSError):
                    integrity.download(release, directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_signature_requires_valid_chain_and_matching_certificate_fingerprint(self):
        for status, digest, accepted in (("Valid", PIN, True), ("NotSigned", PIN, False),
                                          ("Valid", "b" * 64, False)):
            result = Mock(returncode=0, stdout=json.dumps({"status": status, "certificate_sha256": digest}))
            with patch.object(integrity.subprocess, "run", return_value=result):
                if accepted:
                    integrity.verify_publisher("candidate.exe", PIN)
                else:
                    with self.assertRaises(integrity.UpdateError):
                        integrity.verify_publisher("candidate.exe", PIN)

    def test_real_windows_signature_check_rejects_unsigned_fixture_without_installing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "unsigned.exe"
            path.write_bytes(NEW)
            with self.assertRaises(integrity.UpdateError):
                integrity.verify_publisher(path, PIN)

    def test_independent_frozen_process_drops_old_extraction_environment(self):
        with patch.dict(os.environ, {"_MEIPASS2": "old", "_PYI_ARCHIVE_FILE": "old", "DB_HOST": "fixture"}):
            env = fresh_environment()
            self.assertNotIn("_MEIPASS2", env)
            self.assertNotIn("_PYI_ARCHIVE_FILE", env)
            self.assertEqual(env["DB_HOST"], "fixture")
            self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_download_has_an_overall_deadline(self):
        with TemporaryDirectory() as directory, \
                patch.object(integrity, "open_release", return_value=Response(NEW)), \
                patch.object(integrity.time, "monotonic", side_effect=[0, 181]):
            with self.assertRaisesRegex(integrity.UpdateError, "time limit"):
                integrity.download(updater.parse_manifest(manifest_data()), directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_helper_payload_keeps_verified_release_identity_fields(self):
        from services.app_helper import update_payload
        release = updater.parse_manifest(manifest_data())
        with patch.object(updater, "UpdateService") as service:
            service.return_value.check_for_updates.return_value = release
            payload = update_payload()
        self.assertEqual(payload["sha256"], release.sha256)
        self.assertEqual(payload["size"], release.size)
        self.assertEqual(payload["version"], release.version)

    def test_python_release_manifest_hashes_the_actual_artifact(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("sc18_release_writer", root / "scripts/upload_update.py")
        writer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(writer)
        with TemporaryDirectory() as directory, patch.object(writer, "ROOT", Path(directory)):
            (Path(directory) / "dist").mkdir()
            (Path(directory) / "dist/SecondChecking-9.0.0.exe").write_bytes(NEW)
            path = writer.write_manifest("lewisj14/SecondChecking", "9.0.0", "Fixture release")
            release = updater.parse_manifest(json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual(release.sha256, hashlib.sha256(NEW).hexdigest())
            self.assertEqual(release.size, len(NEW))

    def test_health_probe_rejects_wrong_nonce_version_packaging_or_process_exit(self):
        from services import update_process
        for change in ({}, {"nonce": "wrong"}, {"version": "8.0.0"},
                       {"packaged": False}, {"success": False}, {"health_version": 2}):
            job = Mock()
            job.process.wait.return_value = 0
            def create(kind, args, **kwargs):
                job.poll.return_value = dict({"health_version": 1, "nonce": args["nonce"],
                    "version": "9.0.0", "packaged": True, "success": True}, **change)
                return job
            with patch.object(update_process, "HardwareJob", side_effect=create):
                if change:
                    with self.assertRaises(integrity.UpdateError):
                        update_process.check_health("fixture.exe", "9.0.0")
                else:
                    update_process.check_health("fixture.exe", "9.0.0")
            job.close.assert_called_once()


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.target = self.root / "main.exe"
        self.target.write_bytes(OLD)
        (self.root / "config.ini").write_bytes(b"private-config-fixture")
        (self.root / "drafts.json").write_bytes(b"retained-draft-fixture")
        self.identifier = str(uuid4())
        self.directory = self.root / ".secondchecking-updates" / self.identifier
        self.directory.mkdir(parents=True)
        (self.directory / "candidate.exe").write_bytes(NEW)
        (self.directory / "updater.exe").write_bytes(OLD)
        self.path = self.directory / "plan.json"
        self.plan = {"plan_version": 1, "id": self.identifier, "target_name": "main.exe",
                     "version": "9.0.0", "from_version": __version__,
                     "sha256": integrity.file_hash(self.directory / "candidate.exe"), "size": len(NEW),
                     "original_sha256": integrity.file_hash(self.target), "original_size": len(OLD),
                     "signer_sha256": PIN}
        transaction.write_json(self.path, self.plan)
        self.backup = transaction.backup_path(self.target, self.identifier)
        self.verifier = Mock()
        self.health = Mock()
        self.launch = Mock()
        p = patch.dict(os.environ, {"APP_UPDATE_SIGNER_SHA256": PIN})
        p.start()
        self.addCleanup(p.stop)

    def apply(self, **kwargs):
        return transaction.apply_plan(self.path, verifier=self.verifier,
                                       health=self.health, launcher=self.launch, **kwargs)

    def assert_data_unchanged(self):
        self.assertEqual((self.root / "config.ini").read_bytes(), b"private-config-fixture")
        self.assertEqual((self.root / "drafts.json").read_bytes(), b"retained-draft-fixture")

    def test_success_retains_original_and_records_confirmed_version(self):
        self.assertEqual(self.apply(), "installed")
        self.assertEqual(self.target.read_bytes(), NEW)
        self.assertEqual(self.backup.read_bytes(), OLD)
        self.assertEqual(transaction.read_json(self.directory / "state.json")["version"], "9.0.0")
        self.launch.assert_called_once_with(self.target, self.path, "9.0.0")
        self.assert_data_unchanged()

    def test_corrupt_staged_content_never_replaces_current_copy(self):
        (self.directory / "candidate.exe").write_bytes(b"corrupted")
        self.assertEqual(self.apply(), "failed_retained")
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assert_data_unchanged()

    def test_publisher_or_staged_health_failure_retains_working_app(self):
        for boundary in (self.verifier, self.health):
            boundary.side_effect = integrity.UpdateError("fixture rejection")
            self.assertEqual(self.apply(), "failed_retained")
            self.assertEqual(self.target.read_bytes(), OLD)
            boundary.side_effect = None
        self.assert_data_unchanged()

    def test_locked_or_denied_replace_keeps_installed_copy_and_backup(self):
        replace = transaction.os.replace
        def denied(source, destination):
            if Path(destination) == self.target:
                self.assertEqual(self.target.read_bytes(), OLD)
                raise PermissionError("locked")
            return replace(source, destination)
        with patch.object(transaction.os, "replace", side_effect=denied):
            self.assertEqual(self.apply(), "failed_retained")
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assertEqual(self.backup.read_bytes(), OLD)
        self.assert_data_unchanged()

    def test_failed_restart_restores_old_copy_and_launches_it(self):
        self.launch.side_effect = [integrity.UpdateError("restart failed"), None]
        self.assertEqual(self.apply(), "rolled_back")
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assertEqual(self.backup.read_bytes(), OLD)
        self.assertEqual(self.launch.call_args.args[2], __version__)
        self.assert_data_unchanged()

    def test_post_replace_health_failure_rolls_back(self):
        self.health.side_effect = [None, integrity.UpdateError("health failed")]
        self.assertEqual(self.apply(), "rolled_back")
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assert_data_unchanged()

    def test_power_loss_after_atomic_replace_is_recovered_from_durable_journal(self):
        replace = transaction.os.replace
        def interrupted(source, destination):
            replace(source, destination)
            if Path(destination) == self.target:
                raise SystemExit("simulated power loss")
        with patch.object(transaction.os, "replace", side_effect=interrupted):
            with self.assertRaises(SystemExit):
                self.apply()
        self.assertEqual(transaction.read_json(self.directory / "state.json")["state"], "installing")
        self.assertEqual(self.target.read_bytes(), NEW)
        self.assertEqual(self.apply(), "rolled_back")
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assert_data_unchanged()

    def test_missing_target_and_explicit_recovery_use_verified_retained_backup(self):
        self.backup.write_bytes(OLD)
        self.target.unlink()  # Disposable fixture only, simulating an interrupted filesystem operation.
        self.assertEqual(self.apply(), "rolled_back")
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assertEqual(self.apply(restore=True), "rolled_back")
        self.assert_data_unchanged()

    def test_unknown_target_or_corrupt_backup_is_not_overwritten(self):
        self.target.write_bytes(b"external-change")
        with self.assertRaises(integrity.UpdateError):
            self.apply()
        self.assertEqual(self.target.read_bytes(), b"external-change")
        self.target.write_bytes(NEW)
        self.backup.write_bytes(b"bad-backup")
        with self.assertRaises(integrity.UpdateError):
            self.apply(restore=True)
        self.assertEqual(self.target.read_bytes(), NEW)

    def test_real_target_lock_refuses_concurrent_update(self):
        with transaction.target_lock(self.target):
            with self.assertRaises(integrity.UpdateError):
                with transaction.target_lock(self.target):
                    self.fail("Concurrent updater acquired an active lock")

    def test_helper_handoff_is_verified_while_executable_is_write_locked(self):
        service = updater.UpdateService()
        process = Mock()
        process.poll.return_value = None
        def spawn(*args, **kwargs):
            with self.assertRaises(PermissionError):
                with (self.directory / "updater.exe").open("wb") as stream:
                    stream.write(b"tamper")
            launch = transaction.read_json(self.directory / "launch.json")
            transaction.write_json(self.directory / "handoff.json", {"launch_id": launch["launch_id"], "ready": True})
            return process
        with patch.object(updater, "verify_publisher"), patch.object(updater.subprocess, "Popen", side_effect=spawn):
            self.assertTrue(service.start_prepared(self.path))
        self.assertEqual((self.directory / "updater.exe").read_bytes(), OLD)
        self.assertEqual(self.target.read_bytes(), OLD)
        service.cancel_prepared()
        self.assertIn("launch_id", transaction.read_json(self.directory / "cancel.json"))

    def test_failed_or_stale_handoff_does_not_close_or_replace_application(self):
        service = updater.UpdateService()
        transaction.write_json(self.directory / "handoff.json", {"launch_id": "stale", "ready": True})
        with patch.object(updater, "verify_publisher"), \
                patch.object(updater.subprocess, "Popen", return_value=Mock(poll=lambda: 1)):
            with self.assertRaises(integrity.UpdateError):
                service.start_prepared(self.path)
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assertTrue((self.directory / "cancel.json").is_file())

    def test_prepare_failure_leaves_running_copy_and_settings_untouched(self):
        service = updater.UpdateService()
        with patch.object(service, "_can_auto_update", return_value=True), \
                patch.object(service, "_current_executable", return_value=self.target), \
                patch.object(updater, "verify_publisher"), \
                patch.object(updater, "download", side_effect=OSError("interrupted")), \
                patch.object(service, "start_prepared") as start:
            with self.assertRaises(OSError):
                service.launch_update(updater.parse_manifest(manifest_data()))
            start.assert_not_called()
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assert_data_unchanged()

    def test_restart_confirmation_rejects_stale_nonce_and_early_exit(self):
        from services import update_process
        for wrong_nonce in (True, False):
            job = Mock()
            job.process_group = None
            job.process.poll.return_value = None if wrong_nonce else 1
            def create(*args, **kwargs):
                if wrong_nonce:
                    transaction.write_json(self.directory / "startup.json", {
                        "startup_version": 1, "nonce": "wrong", "version": "9.0.0"})
                return job
            with patch.object(update_process, "HardwareJob", side_effect=create):
                with self.assertRaises(integrity.UpdateError):
                    update_process.launch_confirmed(self.target, self.path, "9.0.0")
            job.close.assert_called_once()


class UpdateUITests(unittest.TestCase):
    def test_manual_failure_success_and_cancel_leave_the_correct_ui_state(self):
        if not os.environ.get("SECOND_CHECK_UPDATE_UI_CHILD"):
            child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "UpdateUITests.test_manual_failure_success_and_cancel_leave_the_correct_ui_state"],
                env=dict(os.environ, SECOND_CHECK_UPDATE_UI_CHILD="1"), capture_output=True, text=True, timeout=25)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        import app_controller
        root = tk.Tk()
        root.withdraw()
        try:
            for response, shuts_down in ((False, False), (RuntimeError("verification failed"), False), (True, True)):
                controller = app_controller.AppController.__new__(app_controller.AppController)
                controller.root = root
                controller.update_service = Mock()
                controller.update_service.launch_update.side_effect = response if isinstance(response, Exception) else None
                controller.update_service.launch_update.return_value = response
                controller._preserve_check_draft = Mock(return_value=True)
                controller._shutdown_for_update = Mock(return_value=True)
                with patch.object(app_controller.messagebox, "showerror"):
                    controller._begin_update(updater.UpdateManifest("9.0.0"))
                    deadline = time.monotonic() + 3
                    while controller._update_preparing and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.01)
                self.assertFalse(controller._update_preparing)
                self.assertEqual(controller._shutdown_for_update.called, shuts_down)
                self.assertTrue(root.winfo_exists())
        finally:
            root.destroy()

    def test_cancel_preparation_is_responsive_and_aborts_handoff(self):
        if not os.environ.get("SECOND_CHECK_UPDATE_UI_CHILD"):
            child = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                "UpdateUITests.test_cancel_preparation_is_responsive_and_aborts_handoff"],
                env=dict(os.environ, SECOND_CHECK_UPDATE_UI_CHILD="1"),
                capture_output=True, text=True, timeout=20)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        import app_controller
        root = tk.Tk()
        root.withdraw()
        release = threading.Event()
        try:
            controller = app_controller.AppController.__new__(app_controller.AppController)
            controller.root = root
            controller._preserve_check_draft = Mock(return_value=True)
            controller._shutdown_for_update = Mock()
            controller.update_service = Mock()
            def download(*args):
                release.wait(3)
                return True
            controller.update_service.launch_update.side_effect = download
            controller._begin_update(updater.UpdateManifest("9.0.0"))
            ticks = []
            root.after(10, lambda: ticks.append(True))
            deadline = time.monotonic() + 1
            while not ticks and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            self.assertTrue(ticks)
            self.assertTrue(controller._update_preparing)
            dialog = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel))
            button = next(w for w in dialog.winfo_children() if isinstance(w, app_controller.ttk.Button))
            button.invoke()
            release.set()
            deadline = time.monotonic() + 2
            while controller._update_preparing and time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            controller._shutdown_for_update.assert_not_called()
            controller.update_service.cancel_prepared.assert_called()
        finally:
            release.set()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
