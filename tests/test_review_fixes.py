import configparser
import os
import queue
import sys
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import main_logic
from services.mdm_evidence import evidence
from utils import helpers


class ConfigurationTests(unittest.TestCase):
    def test_api_key_configuration_and_environment_precedence(self):
        config = configparser.ConfigParser()
        config["webtools"] = {
            "base_url": "https://example.invalid/",
            "second_check_key": "configured-key",
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(helpers, "load_config", return_value=config))
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            self.assertEqual(helpers._load_webtools_api_config(),
                             ("https://example.invalid", "configured-key"))
            os.environ["SECOND_CHECK_KEY"] = "environment-key"
            self.assertEqual(helpers._load_webtools_api_config()[1], "environment-key")

    def test_missing_key_prevents_network_upload(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(helpers, "load_config",
                                            return_value=configparser.ConfigParser()))
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            stack.enter_context(patch.object(helpers, "log_event"))
            post = stack.enter_context(patch.object(helpers.requests, "post"))
            ok, response = helpers.upload_stock_unit_check_report(
                order_id=1, order_number="ORD-1", serial_number="TEST",
                sku="SKU", specs={}, test_results={},
            )
        self.assertFalse(ok)
        self.assertEqual(response["error"], "missing API key")
        post.assert_not_called()


class StorageTests(unittest.TestCase):
    def test_equivalent_capacities(self):
        for expected, detected in [("1TB", "1000GB"), ("2TB", "2000GB"),
                                   ("512GB", "512GB"), ("1TB", "1024GB")]:
            with self.subTest(expected=expected, detected=detected):
                self.assertTrue(helpers.storage_specs_are_compatible(expected, detected))

    def test_different_and_unknown_capacities(self):
        self.assertFalse(helpers.storage_specs_are_compatible("1TB", "512GB"))
        self.assertFalse(helpers.storage_specs_are_compatible("1TB", "Unknown"))


class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.conn = Mock()
        self.cursor = self.conn.cursor.return_value
        self.cursor.fetchall.return_value = []
        self.results = dict.fromkeys([
            "keyboard", "speaker", "microphone", "display", "webcam", "usb",
            "wifi", "activation",
        ], "pass")
        for name, value in {
            "get_db_connection": self.conn,
            "check_mdm_lock_status": evidence("no_local_indicators", "No local indicators"),
            "extract_details_from_sku": {},
            "build_results_footer": ("All listed specs match.", None, None, None, None),
            "resolve_order_identity": (12, "ORD-1"),
            "capture_autopilot_hash_csv": None,
            "get_latest_batteryinfoview_report": {"content": "test"},
        }.items():
            self.stack.enter_context(patch.object(main_logic, name, return_value=value))
        self.stack.enter_context(patch.object(main_logic, "prompt_assignment_review", return_value=""))
        self.stack.enter_context(patch.object(main_logic, "refresh_assignment_specs", side_effect=lambda specs, serial: dict(specs)))
        self.success = self.stack.enter_context(
            patch.object(main_logic, "show_assign_success_dialog"))
        self.error = self.stack.enter_context(patch.object(main_logic.messagebox, "showerror"))
        self.stack.enter_context(patch.object(main_logic, "log_event"))

    def assign_order(self):
        main_logic.assign_serial_logic("ORD-1", "TEST", {}, self.results,
                                       "SKU", None, "tester", Mock())

    def assert_no_direct_assignment(self):
        self.conn.commit.assert_not_called()
        for call in self.cursor.execute.call_args_list:
            self.assertFalse(call.args[0].lstrip().upper().startswith(("INSERT", "DELETE", "UPDATE")))

    def test_rejected_or_timed_out_upload_never_saves_or_reports_success(self):
        for reason in ["Unauthorized", "missing API key", "timeout", "Failed to save report"]:
            with self.subTest(reason=reason):
                with patch.object(main_logic, "upload_stock_unit_check_report",
                                  return_value=(False, {"error": reason})):
                    self.assign_order()
                self.assert_no_direct_assignment()
                self.success.assert_not_called()
                self.assertIn(reason, self.error.call_args.args[1])

    def test_success_uses_api_without_duplicate_database_write(self):
        with patch.object(main_logic, "upload_stock_unit_check_report",
                          return_value=(True, {"success": True})):
            self.assign_order()
        self.success.assert_called_once()
        self.error.assert_not_called()
        self.assert_no_direct_assignment()

    def test_missing_hash_is_in_the_recorded_reason_review_before_upload(self):
        with patch.object(main_logic, "prompt_assignment_review", return_value="Hash capture unavailable; reviewed") as review, \
                patch.object(main_logic, "upload_stock_unit_check_report", return_value=(True, {"success": True})) as upload:
            self.assign_order()
        self.assertTrue(review.call_args.args[2])
        self.assertIn("hash was not captured", review.call_args.args[1])
        evidence = upload.call_args.kwargs["assignment_review"]
        self.assertEqual(evidence["reason"], "Hash capture unavailable; reviewed")
        self.assertTrue(any("hash was not captured" in warning for warning in evidence["warnings"]))

    def test_failed_stock_creation_does_not_fall_back(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(main_logic.messagebox, "askyesno", return_value=True))
            upload = stack.enter_context(patch.object(
                main_logic, "upload_stock_unit_check_report", side_effect=[
                    (False, {"error": "Stock unit not found"}),
                    (False, {"error": "Failed to save report"}),
                ]))
            self.assign_order()
        self.assertTrue(upload.call_args.kwargs["create_stock_unit"])
        self.assert_no_direct_assignment()
        self.success.assert_not_called()
        self.error.assert_called_once()




class AssignmentThreadTests(unittest.TestCase):
    def test_worker_keeps_ui_free_and_marshals_dialogs_to_main_thread(self):
        callbacks = queue.Queue()
        root = SimpleNamespace(after=lambda delay, callback: callbacks.put(callback))
        button = Mock()
        progress = Mock()
        started = threading.Event()
        release = threading.Event()
        worker_threads = []
        dialog_threads = []

        def dialog():
            dialog_threads.append(threading.current_thread())
            return True

        def assignment():
            worker_threads.append(threading.current_thread())
            started.set()
            release.wait(5)
            self.assertTrue(main_logic._call_on_ui(root, dialog))

        with patch.object(main_logic.tk, "Toplevel", return_value=progress):
            with patch.object(main_logic.ttk, "Label"):
                main_logic.start_serial_assignment(root, button, assignment)
                self.assertTrue(started.wait(5))
                duplicate = Mock()
                main_logic.start_serial_assignment(root, button, duplicate)
                duplicate.assert_not_called()
                self.assertTrue(root._assignment_running)
                release.set()
                callbacks.get(timeout=5)()  # Dialog runs on the test/UI thread.
                callbacks.get(timeout=5)()  # Completion restores the controls.

        self.assertIsNot(worker_threads[0], threading.main_thread())
        self.assertEqual(dialog_threads, [threading.main_thread()])
        self.assertFalse(root._assignment_running)
        button.configure.assert_called_with(state="normal")
        progress.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
