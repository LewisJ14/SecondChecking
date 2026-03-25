import json
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
