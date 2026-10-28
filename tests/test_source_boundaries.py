"""Source/index policy and service imports, tested without live services or hardware."""
import configparser
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
import check_source_policy as policy
from services import configuration, runtime


class SourcePolicyTests(unittest.TestCase):
    def test_runtime_and_private_paths_are_rejected(self):
        paths = ['build/main/main.pkg', 'dist/config.ini', 'config.ini',
                 'src/db/config.ini', 'src/startup_error.log', 'logs.txt.1',
                 'last_user.txt', 'src.zip', 'update.json', 'src/assets/BatteryInfoView/BatteryInfoView.cfg',
                 'assets/BatteryInfoView/BatteryInfoView.exe', 'other.exe',
                 '.env.production', 'signing.pfx', 'private.pem',
                 '.secondchecking-updates/id/plan.json', 'check-drafts/id.json',
                 'pending-operations/id.json', 'src/output/device.csv']
        for name in paths:
            with self.subTest(name=name):
                self.assertIsNotNone(policy.forbidden_reason(name))

    def test_public_resources_examples_and_review_documents_are_allowed(self):
        for name in list(policy.PUBLIC_ASSETS) + ['config.example.ini',
                'src/services/configuration.py', 'tests/test_source_boundaries.py',
                'docs/sc19-release-evidence.json', 'docs/sc20-source-boundaries.md',
                'scripts/release_package.py', 'main.spec', '.env.example']:
            with self.subTest(name=name):
                self.assertIsNone(policy.forbidden_reason(name))

    def fixture(self, root):
        subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
        for name in policy.required_paths(root):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('public fixture')
        subprocess.run(['git', 'add', '--all'], cwd=str(root), check=True)

    def test_real_index_distinguishes_preserved_private_file_from_tracked_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / 'config.ini').write_bytes(b'private fixture config')
            self.assertGreater(policy.check_repository(root), 0)
            subprocess.run(['git', 'add', 'config.ini'], cwd=str(root), check=True)
            with self.assertRaisesRegex(ValueError, 'config.ini'):
                policy.check_repository(root)
            subprocess.run(['git', 'rm', '--cached', '--quiet', 'config.ini'], cwd=str(root), check=True)
            self.assertEqual((root / 'config.ini').read_bytes(), b'private fixture config')
            policy.check_repository(root)

    def test_new_source_and_missing_resource_cannot_be_silently_omitted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            path = root / 'src/new_service.py'
            path.write_text('new source')
            with self.assertRaisesRegex(ValueError, 'not tracked'):
                policy.check_repository(root)
            subprocess.run(['git', 'add', str(path)], cwd=str(root), check=True)
            policy.check_repository(root)
            (root / 'src/assets/AudioCheck.wav').unlink()
            with self.assertRaisesRegex(ValueError, 'missing from disk'):
                policy.check_repository(root)

    def test_cli_failure_is_nonzero_without_reading_private_content(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / 'config.ini').write_text('credential-fixture-never-output')
            subprocess.run(['git', 'add', 'config.ini'], cwd=str(root), check=True)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/check_source_policy.py'),
                                     '--root', str(root)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn('config.ini', result.stderr)
            self.assertNotIn('credential-fixture-never-output', result.stderr)

    def test_ignore_rules_cover_local_runtime_files_and_keep_examples_visible(self):
        names = ['config.ini', 'src/assets/BatteryInfoView/BatteryInfoView.cfg',
                 'logs.txt.1', 'last_user.txt', 'src.zip', 'update.json',
                 '.secondchecking-updates/fixture/plan.json', 'check-drafts/fixture.json',
                 'pending-operations/fixture.json', 'publisher.pfx']
        # --no-index checks the rules even before cached runtime entries are removed.
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin', '-z'],
                                input=('\0'.join(names) + '\0').encode(), cwd=str(ROOT),
                                capture_output=True, check=True)
        self.assertEqual(set(result.stdout.decode().strip('\0').split('\0')), set(names))
        result = subprocess.run(['git', 'check-ignore', '--no-index', 'config.example.ini'],
                                cwd=str(ROOT), capture_output=True)
        self.assertEqual(result.returncode, 1)


class ServiceBoundaryTests(unittest.TestCase):
    def test_fresh_auth_and_database_imports_do_not_load_gui_or_hardware(self):
        code = '''import json, sys
sys.path.insert(0, sys.argv[1])
import services.auth_service
import db.database
blocked = ['tkinter', 'wmi', 'cv2', 'numpy', 'utils.helpers', 'app_controller', 'main_logic']
print(json.dumps([name for name in blocked if name in sys.modules]))
'''
        result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'src')],
                                capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout), [])

    def test_headless_database_failure_keeps_gui_out_and_redacts_credentials(self):
        code = '''import json, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from db import database
with patch.object(database, 'load_database_settings', return_value={'host':'fixture', 'user':'fixture', 'password':'private-fixture', 'database':'fixture'}), patch.object(database.MySQLdb, 'connect', side_effect=RuntimeError('private-fixture')), patch.object(database, 'log_event') as log:
    assert database.get_db_connection(retries=1, show_errors=False) is None
    assert 'private-fixture' not in str(log.call_args_list)
assert 'tkinter' not in sys.modules
print('headless database failure passed')
'''
        result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'src')],
                                capture_output=True, text=True, timeout=10, check=True)
        self.assertIn('passed', result.stdout)

    def test_api_configuration_failure_is_safe_and_service_owned(self):
        with patch.object(configuration, 'read_config', side_effect=configuration.ConfigurationError('private-fixture')):
            with self.assertRaises(RuntimeError) as caught:
                configuration.service_settings()
        self.assertNotIn('private-fixture', str(caught.exception))
        self.assertIn('SECOND_CHECK_KEY', str(caught.exception))

    def test_api_configuration_uses_environment_precedence(self):
        config = configparser.ConfigParser()
        config['webtools'] = {'base_url': 'https://old.invalid', 'second_check_key': 'old'}
        with patch.object(configuration, 'read_config', return_value=config), \
                patch.dict(os.environ, {'SECOND_CHECK_BASE_URL': 'https://fixture.invalid/', 'SECOND_CHECK_KEY': 'fixture-key'}):
            self.assertEqual(configuration.service_settings(), ('https://fixture.invalid', 'fixture-key'))

    def test_logging_with_no_stdout_survives_an_unwritable_destination(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'not-created' / 'logs.txt'
            with patch.object(runtime, 'log_path', return_value=path), \
                    patch.object(sys, 'stdout', None), patch.object(sys, 'stderr', None):
                runtime.log_event('fixture')
            self.assertFalse(path.exists())

    def test_logging_rotation_preserves_the_previous_log(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'logs.txt'
            path.write_bytes(b'x' * (5 * 1024 * 1024 + 1))
            with patch.object(runtime, 'log_path', return_value=path):
                runtime.log_event('new fixture entry')
            self.assertIn('new fixture entry', path.read_text())
            self.assertEqual(path.with_name('logs.txt.1').stat().st_size, 5 * 1024 * 1024 + 1)

    def test_source_battery_tool_uses_canonical_asset_without_download(self):
        from utils import helpers
        with patch.object(helpers.urllib.request, 'urlretrieve') as download:
            path = helpers.ensure_batteryinfoview()
        self.assertEqual(Path(path), ROOT / 'src/assets/BatteryInfoView/BatteryInfoView.exe')
        download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
