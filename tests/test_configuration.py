import configparser
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from services import configuration as config
from db import database
from utils import helpers


class FreshConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.env = {"DB_HOST": "localhost", "DB_USER": "tester",
                    "DB_PASSWORD": "literal%password", "DB_NAME": "test",
                    "SECOND_CHECK_BASE_URL": "https://example.invalid",
                    "SECOND_CHECK_KEY": "test-key"}

    def test_environment_only_with_no_database_section(self):
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(config.database_settings(configparser.ConfigParser())[
                "password"], "literal%password")
            self.assertEqual(config.webtools_settings(configparser.ConfigParser()),
                             ("https://example.invalid", "test-key"))

    def test_file_only_literal_percent_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.ini"
            path.write_text("[database]\nhost=localhost\nuser=tester\n"
                            "password=literal%password\ndatabase=test\n"
                            "[webtools]\nbase_url=https://example.invalid\n"
                            "second_check_key=test-key\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                loaded = config.read_config(path)
                self.assertEqual(config.database_settings(loaded), {
                    "host": "localhost", "user": "tester",
                    "password": "literal%password", "database": "test"})
                self.assertEqual(config.webtools_settings(loaded)[1], "test-key")
                with patch.dict(os.environ, {"DB_PASSWORD": "override"}):
                    self.assertEqual(config.database_settings(loaded)["password"], "override")
                with patch.dict(os.environ, {"DB_PASSWORD": ""}):
                    with self.assertRaisesRegex(config.ConfigurationError, "DB_PASSWORD"):
                        config.database_settings(loaded)

    def test_missing_and_invalid_fields_do_not_echo_values(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(config.ConfigurationError, "DB_HOST.*DB_NAME"):
                config.database_settings(configparser.ConfigParser())
        for url in ("bad-secret-url", "https://user:private@example.invalid",
                    "https://example.invalid:secret", "https://example.invalid/?secret"):
            with patch.dict(os.environ, dict(self.env, SECOND_CHECK_BASE_URL=url), clear=True):
                with self.assertRaises(config.ConfigurationError) as caught:
                    config.webtools_settings(configparser.ConfigParser())
                self.assertNotIn(url, str(caught.exception))
                self.assertIn("SECOND_CHECK_BASE_URL", str(caught.exception))

    def test_broken_ini_and_explicit_missing_file_are_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.ini"
            with self.assertRaises(config.ConfigurationError):
                config.read_config(path)
            path.write_text("secret-password-without-section", encoding="utf-8")
            with self.assertRaises(config.ConfigurationError) as caught:
                config.read_config(path)
            self.assertNotIn("secret-password", str(caught.exception))

    def test_source_and_frozen_paths_ignore_current_directory(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.config_path(), Path(__file__).resolve().parents[1] / "config.ini")
            with patch.object(sys, "frozen", True, create=True), patch.object(
                    sys, "executable", r"C:\test\secondchecker.exe"):
                self.assertEqual(config.config_path(), Path(r"C:\test\config.ini"))

    def test_probe_only_selects_and_closes_even_on_failure(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (1,)
        with patch.object(database, "load_database_settings", return_value={
                "host": "host", "user": "user", "password": "secret", "database": "test"}), \
                patch.object(database.MySQLdb, "connect", return_value=conn), \
                patch.object(database, "ensure_schema") as schema:
            database.check_database_connection()
            cursor.execute.assert_called_once_with("SELECT 1")
            schema.assert_not_called()
            conn.close.assert_called_once()
            cursor.execute.side_effect = RuntimeError("secret")
            with self.assertRaises(RuntimeError) as caught:
                database.check_database_connection()
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(conn.close.call_count, 2)

    def test_relative_ca_moves_with_exe_and_ignores_cwd_and_config_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deploy = root / 'original'
            (deploy / 'certificates').mkdir(parents=True)
            (deploy / 'certificates/mysql-ca.pem').write_text('public test CA')
            private = root / 'external-config.ini'
            private.write_text('[database]\nssl_ca=certificates/mysql-ca.pem\n')
            unrelated = root / 'unrelated'
            unrelated.mkdir()
            for name in ('original', 'moved app'):
                if name != 'original':
                    deploy = deploy.rename(root / name)
                with patch.dict(os.environ, {'SECOND_CHECK_CONFIG': str(private)}, clear=True), \
                        patch.object(sys, 'frozen', True, create=True), \
                        patch.object(sys, 'executable', str(deploy / 'main.exe')), \
                        patch('pathlib.Path.cwd', return_value=unrelated):
                    options = config.database_tls_options('db.example', config.read_config())
                    self.assertEqual(options['ssl']['ca'],
                                     str((deploy / 'certificates/mysql-ca.pem').resolve()))
                    self.assertEqual(options['ssl_mode'], 'VERIFY_IDENTITY')
                    self.assertFalse(options['local_infile'])

    def test_ca_absolute_override_and_missing_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ca = root / 'external.pem'
            ca.write_text('public test CA')
            settings = configparser.ConfigParser()
            settings.read_dict({'database': {'ssl_ca': 'certificates/missing.pem'}})
            with patch.dict(os.environ, {'DB_SSL_CA': str(ca)}, clear=True):
                self.assertEqual(config.database_tls_options('db.example', settings)[
                    'ssl']['ca'], str(ca.resolve()))
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, 'executable', str(root / 'main.exe')):
                with self.assertRaisesRegex(config.ConfigurationError, 'relative paths'):
                    config.database_tls_options('db.example', settings)

    def test_connection_errors_never_log_driver_credentials(self):
        with patch.object(database, "load_database_settings", return_value={
                "host": "host", "user": "user", "password": "secret", "database": "test"}), \
                patch.object(database.MySQLdb, "connect", side_effect=RuntimeError("secret")), \
                patch.object(database, "log_event") as log:
            self.assertIsNone(database.get_db_connection(retries=1, show_errors=False))
            self.assertNotIn("secret", str(log.call_args_list))

    def test_login_configuration_retry_uses_service_without_database(self):
        from services import auth_service
        with patch.object(auth_service, "service_settings", return_value=("", "")), \
                patch.object(auth_service.requests, "request") as request:
            rows, error = auth_service.fetch_usernames()
            self.assertEqual(rows, [])
            self.assertIn("SECOND_CHECK_BASE_URL", error)
            request.assert_not_called()
        with patch.object(auth_service, "api_request", return_value=("https://isolated", {
                "success": True, "usernames": ["tester"]})):
            self.assertEqual(auth_service.fetch_usernames(), (["tester"], None))
        self.assertFalse(hasattr(auth_service, "get_db_connection"))

    def test_clean_headless_start_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.ini"
            path.write_text("", encoding="utf-8")
            env = dict(os.environ)
            for key in self.env:
                env.pop(key, None)
            env["SECOND_CHECK_CONFIG"] = str(path)
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] /
                                    "src/main.py"), "--check-config"], cwd=tmp, env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn("DB_HOST", result.stdout)
            self.assertNotIn("Traceback", result.stderr)

    def test_sku_fallback_without_optional_search_section(self):
        with patch.object(helpers, "load_config", return_value=configparser.ConfigParser()):
            details = helpers._extract_details_from_sku_keywords("unconfigured-model")
        self.assertEqual(details["CPU"], "Unknown")
        self.assertEqual(details["Model"], "Unknown")
