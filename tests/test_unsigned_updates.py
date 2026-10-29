"""Automatic updates without signing, retaining content and recovery checks."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import update_service as updater
from services import update_integrity as integrity, update_transaction as transaction
from version import __version__

OLD = b'MZ' + b'working-original-fixture' * 20
NEW = b'MZ' + b'new-version-fixture' * 20
BASE = 'https://github.com/lewisj14/SecondChecking/releases/'


class UnsignedUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / 'SecondChecking.exe'
        self.target.write_bytes(OLD)
        (self.root / 'config.ini').write_bytes(b'private-config-fixture')
        (self.root / 'drafts.json').write_bytes(b'private-draft-fixture')
        patcher = patch.dict(os.environ, {'APP_UPDATE_SIGNER_SHA256': ''})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.service = updater.UpdateService()
        self.release = updater.parse_manifest({
            'version': '9.0.0', 'sha256': hashlib.sha256(NEW).hexdigest(),
            'size': len(NEW), 'release_page': BASE + 'tag/v9.0.0',
            'download_url': BASE + 'download/v9.0.0/SecondChecking-9.0.0.exe'})

    def make_plan(self):
        identifier = str(uuid4())
        self.directory = self.root / '.secondchecking-updates' / identifier
        self.directory.mkdir(parents=True)
        (self.directory / 'candidate.exe').write_bytes(NEW)
        (self.directory / 'updater.exe').write_bytes(OLD)
        self.plan = {'plan_version': 1, 'id': identifier,
            'target_name': self.target.name, 'version': '9.0.0',
            'from_version': __version__, 'sha256': hashlib.sha256(NEW).hexdigest(),
            'size': len(NEW), 'original_sha256': hashlib.sha256(OLD).hexdigest(),
            'original_size': len(OLD), 'signer_sha256': ''}
        self.path = self.directory / 'plan.json'
        transaction.write_json(self.path, self.plan)

    def assert_settings_retained(self):
        self.assertEqual((self.root / 'config.ini').read_bytes(), b'private-config-fixture')
        self.assertEqual((self.root / 'drafts.json').read_bytes(), b'private-draft-fixture')

    def test_packaged_update_downloads_prepares_and_hands_off_without_browser(self):
        def download(release, directory, *args):
            path = directory / 'candidate.exe'
            path.write_bytes(NEW)
            return path

        with patch.object(self.service, '_can_auto_update', return_value=True), \
                patch.object(self.service, '_current_executable', return_value=self.target), \
                patch.object(updater, 'download', side_effect=download), \
                patch.object(updater, 'verify_publisher') as signer, \
                patch('services.update_process.check_health'), \
                patch('services.auth_service.authorize') as authorize, \
                patch.object(self.service, 'start_prepared', return_value=True) as handoff, \
                patch.object(updater.webbrowser, 'open') as browser:
            self.assertTrue(self.service.can_auto_install(self.release))
            self.assertTrue(self.service.launch_update(self.release))
        signer.assert_not_called()
        browser.assert_not_called()
        authorize.assert_called_once_with('maintenance')
        path = handoff.call_args.args[0]
        plan = transaction.read_json(path)
        self.assertEqual(plan['signer_sha256'], '')
        self.assertEqual((path.parent / 'updater.exe').read_bytes(), OLD)
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assert_settings_retained()

    def test_unsigned_atomic_install_and_manual_restore_retain_settings(self):
        self.make_plan()
        signer, health, launch = Mock(), Mock(), Mock()
        with patch.object(transaction, 'verify_publisher', signer):
            self.assertEqual(transaction.apply_plan(self.path, health=health,
                             launcher=launch), 'installed')
            self.assertEqual(self.target.read_bytes(), NEW)
            self.assertEqual(transaction.apply_plan(self.path, restore=True,
                             health=health, launcher=launch), 'rolled_back')
        signer.assert_not_called()
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assert_settings_retained()

    def test_failed_unsigned_restart_rolls_back(self):
        self.make_plan()
        launch = Mock(side_effect=[integrity.UpdateError('fixture failure'), None])
        self.assertEqual(transaction.apply_plan(self.path, health=Mock(),
                         launcher=launch), 'rolled_back')
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assert_settings_retained()

    def test_owned_unsigned_worker_accepts_handoff_and_replaces_target(self):
        self.make_plan()
        transaction.write_json(self.directory / 'launch.json', {'launch_id': str(uuid4())})
        apply = transaction.apply_plan
        with patch.object(sys, 'executable', str(self.directory / 'updater.exe')), \
                patch.object(transaction, 'verify_publisher') as signer, \
                patch.object(transaction, 'wait_for_parent'), \
                patch.object(transaction, 'apply_plan', side_effect=lambda path, restore=False:
                    apply(path, restore=restore, health=Mock(), launcher=Mock())):
            self.assertEqual(transaction.worker(self.path), 0)
        signer.assert_not_called()
        self.assertTrue(transaction.read_json(self.directory / 'handoff.json')['ready'])
        self.assertEqual(self.target.read_bytes(), NEW)
        self.assertEqual(transaction.backup_path(self.target, self.plan['id']).read_bytes(), OLD)
        self.assert_settings_retained()

    def test_corrupted_unsigned_worker_cannot_accept_handoff(self):
        self.make_plan()
        (self.directory / 'updater.exe').write_bytes(b'MZcorrupt-helper')
        with patch.object(sys, 'executable', str(self.directory / 'updater.exe')), \
                patch.object(transaction, 'apply_plan') as apply:
            self.assertEqual(transaction.worker(self.path), 1)
        apply.assert_not_called()
        self.assertFalse((self.directory / 'handoff.json').exists())
        self.assertEqual(self.target.read_bytes(), OLD)

    def test_corrupt_unsigned_download_never_replaces_running_app(self):
        self.make_plan()
        (self.directory / 'candidate.exe').write_bytes(b'MZcorrupt')
        health, launch = Mock(), Mock()
        self.assertEqual(transaction.apply_plan(self.path, health=health,
                         launcher=launch), 'failed_retained')
        health.assert_not_called()
        self.assertEqual(self.target.read_bytes(), OLD)
        self.assert_settings_retained()

    def test_publisher_setting_cannot_be_removed_or_invented_by_journal(self):
        self.make_plan()
        for configured, declared in (('a' * 64, ''), ('', 'a' * 64), ('', None)):
            with self.subTest(configured=bool(configured), declared=bool(declared)), \
                    patch.dict(os.environ, {'APP_UPDATE_SIGNER_SHA256': configured}):
                self.plan['signer_sha256'] = declared
                transaction.write_json(self.path, self.plan)
                with self.assertRaises(integrity.UpdateError):
                    transaction.apply_plan(self.path, health=Mock(), launcher=Mock())
                with patch.object(updater.subprocess, 'Popen') as spawn:
                    with self.assertRaises(integrity.UpdateError):
                        self.service.start_prepared(self.path)
                    spawn.assert_not_called()
        self.assertEqual(self.target.read_bytes(), OLD)

    def test_invalid_publisher_configuration_does_not_enable_unsigned_mode(self):
        with patch.dict(os.environ, {'APP_UPDATE_SIGNER_SHA256': 'invalid'}), \
                patch.object(self.service, '_can_auto_update', return_value=True):
            self.assertFalse(self.service.can_auto_install(self.release))
            with self.assertRaises(integrity.UpdateError):
                self.service.prepare_update(self.release)

    def test_changed_baseline_during_download_is_not_used_as_updater(self):
        def download(release, directory, *args):
            path = directory / 'candidate.exe'
            path.write_bytes(NEW)
            self.target.write_bytes(b'MZexternally-changed')
            return path

        with patch.object(self.service, '_current_executable', return_value=self.target), \
                patch.object(updater, 'download', side_effect=download), \
                patch('services.update_process.check_health'), \
                patch.object(self.service, 'start_prepared') as handoff:
            with self.assertRaises(integrity.UpdateError):
                self.service.prepare_update(self.release)
            handoff.assert_not_called()
        self.assertEqual(list(self.root.rglob('updater.exe')), [])
        self.assert_settings_retained()
