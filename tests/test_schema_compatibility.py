import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from db import database
from db.schema import REQUIRED_COLUMNS, SchemaCompatibilityError, validate_schema
from utils import helpers


def rows():
    return [(table, column) for table, columns in REQUIRED_COLUMNS.items()
            for column in columns]


class SchemaCompatibilityTests(unittest.TestCase):
    def connection(self, data=None):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.fetchall.return_value = (
            rows() if data is None else data)
        return conn

    def test_supported_schema_only_reads_metadata(self):
        conn = self.connection()
        validate_schema(conn, "private-database")
        cursor = conn.cursor.return_value.__enter__.return_value
        sql, params = cursor.execute.call_args.args
        self.assertTrue(sql.startswith("SELECT "))
        self.assertNotIn("private-database", sql)
        self.assertEqual(params[0], "private-database")
        conn.commit.assert_not_called()
        self.assertEqual(cursor.execute.call_count, 1)

    def test_bytes_and_extra_columns_are_supported(self):
        data = [(table.encode(), column.encode()) for table, column in rows()]
        data.append((b"user", b"newer_server_column"))
        validate_schema(self.connection(data), "test")

    def test_missing_required_table_and_column_fail_without_writes(self):
        for data, expected in (([], "dropdown_option (table)"),
                               ([r for r in rows() if r != ("dropdown_option", "name")],
                                "dropdown_option.name"),
                               ([r for r in rows() if r != ("order_serials", "test_wifi")],
                                "order_serials.test_wifi")):
            conn = self.connection(data)
            with self.assertRaisesRegex(SchemaCompatibilityError, "0d9e0f1a2b3c") as caught:
                validate_schema(conn, "private-database")
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn("private-database", str(caught.exception))
            conn.commit.assert_not_called()

    def test_metadata_permission_error_is_safe_and_fails_closed(self):
        conn = self.connection()
        conn.cursor.side_effect = RuntimeError("secret-password")
        with self.assertRaises(SchemaCompatibilityError) as caught:
            validate_schema(conn, "test")
        self.assertNotIn("secret-password", str(caught.exception))
        self.assertIn("read access", str(caught.exception))

    def test_normal_connection_closes_incompatible_schema_without_retry(self):
        conn = self.connection([])
        with patch.object(database, "load_database_settings", return_value={
                "host": "host", "user": "user", "password": "secret", "database": "test"}), \
                patch.object(database.MySQLdb, "connect", return_value=conn) as connect, \
                patch.object(database, "log_event"), patch("time.sleep") as sleep:
            with self.assertRaises(SchemaCompatibilityError):
                database.get_db_connection(show_errors=False)
            connect.assert_called_once()
            conn.close.assert_called_once()
            sleep.assert_not_called()

    def test_normal_supported_connection_and_compatibility_alias_never_commit(self):
        conn = self.connection()
        with patch.object(database, "load_database_settings", return_value={
                "host": "host", "user": "user", "password": "secret", "database": "test"}), \
                patch.object(database.MySQLdb, "connect", return_value=conn), \
                patch.object(database, "log_event"):
            self.assertIs(database.get_db_connection(show_errors=False), conn)
            database.ensure_schema(conn, "test")
        conn.commit.assert_not_called()
        conn.close.assert_not_called()
        for call in conn.cursor.return_value.__enter__.return_value.execute.call_args_list:
            self.assertTrue(call.args[0].startswith("SELECT "))

    def test_login_user_list_no_longer_reads_password_hashes_or_schema(self):
        from services import auth_service
        self.assertFalse(hasattr(auth_service, "get_db_connection"))
        with patch.object(auth_service, "api_request", return_value=("https://isolated", {
                "success": True, "usernames": ["tester"]})):
            self.assertEqual(auth_service.fetch_usernames(), (["tester"], None))

    def test_explicit_probe_can_check_schema_and_always_closes(self):
        conn = self.connection([])
        conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        with patch.object(database, "load_database_settings", return_value={
                "host": "host", "user": "user", "password": "secret", "database": "test"}), \
                patch.object(database.MySQLdb, "connect", return_value=conn):
            with self.assertRaises(SchemaCompatibilityError):
                database.check_database_connection(check_schema=True)
        conn.close.assert_called_once()
        conn.commit.assert_not_called()


    def test_interactive_failure_shows_upgrade_error_and_returns_no_connection(self):
        conn = self.connection([])
        with patch.object(database, "load_database_settings", return_value={
                "host": "host", "user": "user", "password": "secret", "database": "test"}), \
                patch.object(database.MySQLdb, "connect", return_value=conn), \
                patch.object(database, "log_event"), \
                patch.object(database, "_show_error") as show:
            self.assertIsNone(database.get_db_connection(show_errors=True))
            self.assertEqual(show.call_args.args[0], "Database upgrade required")
            self.assertIn("0d9e0f1a2b3c", show.call_args.args[1])
        conn.close.assert_called_once()
