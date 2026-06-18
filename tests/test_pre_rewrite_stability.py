import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from db.database import build_retry_sleep_seconds, format_db_unavailable_message
from services.auth_service import normalize_usernames


class AuthServiceTests(unittest.TestCase):
    def test_normalize_usernames_filters_missing_values(self):
        rows = [("alice",), None, ("",), (None,), ("bob",)]

        usernames = normalize_usernames(rows)

        self.assertEqual(usernames, ["alice", "bob"])


class DatabaseHelperTests(unittest.TestCase):
    def test_build_retry_sleep_seconds_scales_by_attempt(self):
        self.assertEqual(build_retry_sleep_seconds(2, 3), 6)

    def test_format_db_unavailable_message_is_clear(self):
        message = format_db_unavailable_message("timeout", 2)

        self.assertIn("The app started, but the database is unavailable.", message)
        self.assertIn("Error connecting to MySQL after 2 attempts", message)
        self.assertIn("timeout", message)

    def test_format_db_unavailable_message_supports_unexpected_errors(self):
        message = format_db_unavailable_message("boom", 1, unexpected=True)

        self.assertIn("Unexpected error connecting to MySQL after 1 attempts", message)


class RuntimeManifestTests(unittest.TestCase):
    def test_runtime_manifest_marks_config_as_user_managed(self):
        manifest = json.loads((REPO_ROOT / "runtime-files.json").read_text(encoding="utf-8"))

        config_entry = next(item for item in manifest if item["target"] == "config.ini")
        logs_entry = next(item for item in manifest if item["target"] == "logs.txt")

        self.assertTrue(config_entry["userManaged"])
        self.assertFalse(config_entry["overwrite"])
        self.assertFalse(logs_entry["userManaged"])
        self.assertTrue(logs_entry["overwrite"])


class AssignSerialLogicTests(unittest.TestCase):
    def test_stock_unit_not_found_no_cancels_without_legacy_assignment(self):
        import main_logic

        cursor = Mock()
        cursor.fetchall.return_value = []

        conn = Mock()
        conn.cursor.return_value = cursor

        with (
            patch.object(main_logic, "get_db_connection", return_value=conn),
            patch.object(main_logic, "extract_details_from_sku", return_value={}),
            patch.object(main_logic, "build_results_footer", return_value=("All listed specs match.", None, None, None, None)),
            patch.object(main_logic, "resolve_order_identity", return_value=(12, "ORD-1")),
            patch.object(main_logic, "capture_autopilot_hash_csv", return_value=r"C:\temp\PF24NEM2.csv"),
            patch.object(
                main_logic,
                "upload_stock_unit_check_report",
                return_value=(False, {"error": "Stock unit not found"}),
            ) as upload_stock_report,
            patch.object(main_logic, "upload_hash_csv") as upload_hash_csv,
            patch.object(main_logic, "show_assign_success_dialog") as show_success,
            patch.object(main_logic.messagebox, "askyesno", return_value=False),
            patch.object(main_logic.messagebox, "showinfo") as showinfo,
        ):
            main_logic.assign_serial_logic(
                order_number="ORD-1",
                serial_number="PF24NEM2",
                specs={},
                test_results={
                    "keyboard": "pass",
                    "speaker": "pass",
                    "microphone": "pass",
                    "display": "pass",
                    "webcam": "pass",
                    "usb": "pass",
                    "wifi": "pass",
                    "activation": "pass",
                },
                sku="SKU-1",
                mdm_status=None,
                assigned_by="tester",
                root=Mock(),
            )

        self.assertEqual(upload_stock_report.call_count, 1)
        upload_hash_csv.assert_not_called()
        show_success.assert_not_called()
        showinfo.assert_called_once()
        conn.commit.assert_not_called()
        executed_sql = "\n".join(str(call.args[0]) for call in cursor.execute.call_args_list)
        self.assertNotIn("INSERT INTO order_serials", executed_sql)


if __name__ == "__main__":
    unittest.main()
