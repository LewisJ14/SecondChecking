"""Release provenance guards use disposable files and mocked build/upload boundaries."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
import release_package as release
from services import build_identity


class ReleaseIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'repo'
        self.root.mkdir()
        (self.root / 'src').mkdir()
        (self.root / 'scripts').mkdir()
        (self.root / 'tests').mkdir()
        (self.root / 'src/version.py').write_text('__version__ = "1.2.3"\n')
        for name in release.BUILD_FILES + release.ASSETS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
        (self.root / 'requirements.txt').write_text('')
        self.patch = patch.object(release, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.state = {'version': '1.2.3', 'tag': 'v1.2.3', 'commit': 'a' * 40,
                      'dirty': False, 'review_only': False, 'source_sha256': {'src/version.py': 'b' * 64}}
        self.identity = dict(self.state, identity_version=1, build_id='fixture-id')
        self.output = Path(self.temp.name).resolve() / 'build'
        (self.output / 'dist').mkdir(parents=True)
        self.artifact = self.output / 'dist/main.exe'
        self.artifact.write_bytes(b'MZfixture executable')
        release.write_json(self.output / 'build-record.json', {'identity': self.identity,
                           'unsigned_sha256': release.digest(self.artifact),
                           'unsigned_size': self.artifact.stat().st_size})

    def prepare(self):
        with patch.object(release, 'source_state', return_value=self.state), \
                patch.object(release, 'embedded_identity', return_value=self.identity), \
                patch.dict(os.environ, {'APP_UPDATE_SIGNER_SHA256': ''}):
            assets = release.prepare(self.output, 'v1.2.3', 'Fixture notes')
        (assets / 'release-notes.txt').write_text('Fixture notes')
        return assets

    def test_version_is_parsed_without_executing_source(self):
        (self.root / 'src/version.py').write_text('raise RuntimeError("must not execute")\n__version__="1.2.3"')
        self.assertEqual(release.load_version(), '1.2.3')
        for value in ('01.2.3', 'v1.2.3', '1.2', '1.2.70000', '1.2.3-rc1'):
            (self.root / 'src/version.py').write_text('__version__=' + repr(value))
            with self.assertRaises(ValueError):
                release.load_version()

    def test_tag_dirty_and_commit_guards(self):
        with patch.object(release, 'git', side_effect=['a' * 40, ' M src/main.py']):
            with self.assertRaisesRegex(ValueError, 'clean checkout'):
                release.source_state('v1.2.3')
        with patch.object(release, 'git', side_effect=['a' * 40, '', 'c' * 40]):
            with self.assertRaisesRegex(ValueError, 'HEAD'):
                release.source_state('v1.2.3')
        with self.assertRaisesRegex(ValueError, 'tag'):
            release.source_state('v1.2.4')
        with patch.object(release, 'git', side_effect=['a' * 40, '?? src/new.py']):
            self.assertTrue(release.source_state('v1.2.3', True)['review_only'])

    def test_moved_tag_rejects_build_at_the_previously_tested_commit(self):
        def fixture_git(*args):
            return subprocess.run(
                ['git', '-c', 'user.name=Release fixture',
                 '-c', 'user.email=fixture@example.invalid',
                 '-c', 'commit.gpgsign=false'] + list(args),
                cwd=str(self.root), check=True, capture_output=True,
                text=True).stdout.strip()

        # Use a disposable real repository: a later checkout must stay on the
        # tested SHA, and source_state must reject a tag moved to another SHA.
        fixture_git('init')
        fixture_git('add', '.')
        fixture_git('commit', '-m', 'Tested source')
        tested = fixture_git('rev-parse', 'HEAD')
        fixture_git('-c', 'tag.gpgsign=false', 'tag', '-a', 'v1.2.3',
                    '-m', 'Fixture release')
        with patch('check_source_policy.check_repository'):
            self.assertEqual(release.source_state('v1.2.3')['commit'], tested)
            (self.root / 'src/main.py').write_text('# Later untested change\n')
            fixture_git('add', '.')
            fixture_git('commit', '-m', 'Untested source')
            fixture_git('-c', 'tag.gpgsign=false', 'tag', '-f', 'v1.2.3')
            fixture_git('checkout', '--detach', tested)
            with self.assertRaisesRegex(ValueError, 'HEAD'):
                release.source_state('v1.2.3')
            self.assertEqual(fixture_git('rev-parse', 'HEAD'), tested)

    def test_hashes_include_new_source_and_assets_without_runtime_private_files(self):
        (self.root / 'src/new.py').write_text('new source')
        (self.root / 'src/config.ini').write_text('private config')
        (self.root / 'src/logs.txt').write_text('private log')
        before = release.source_hashes()
        self.assertIn('src/new.py', before)
        self.assertIn(release.ASSETS[-1], before)
        self.assertNotIn('src/config.ini', before)
        self.assertNotIn('src/logs.txt', before)
        (self.root / 'src/new.py').write_text('changed source')
        self.assertNotEqual(before, release.source_hashes())

    def test_build_fails_if_inputs_change_during_packaging(self):
        output = Path(self.temp.name).resolve() / 'new-build'
        changed = dict(self.state, source_sha256={'different': 'hash'})
        with patch.object(release, 'check_dependencies'), \
                patch.object(release, 'source_state', side_effect=[self.state, changed]), \
                patch.object(release, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'changed during'):
                release.build(output, 'v1.2.3')
        self.assertIn('--distpath', command.call_args.args[0])
        self.assertFalse((output / 'build-record.json').exists())
        self.assertEqual(self.artifact.read_bytes(), b'MZfixture executable')

    def test_build_never_reuses_existing_output_or_checkout(self):
        with patch.object(release, 'check_dependencies'), \
                patch.object(release, 'source_state', return_value=self.state), \
                patch.object(release, 'run') as command:
            with self.assertRaises(FileExistsError):
                release.build(self.output, 'v1.2.3')
            with self.assertRaises(ValueError):
                release.build(self.root / 'dist', 'v1.2.3')
            command.assert_not_called()

    def test_build_identity_round_trips_into_the_executable(self):
        output = Path(self.temp.name).resolve() / 'new-build'

        def package(command, **kwargs):
            (output / 'dist').mkdir()
            (output / 'dist/main.exe').write_bytes(b'MZfixture')

        with patch.object(release, 'check_dependencies'), \
                patch.object(release, 'source_state', return_value=self.state), \
                patch.object(release, 'run', side_effect=package), \
                patch.object(release, 'embedded_identity', side_effect=lambda path: json.loads(
                    (output / 'build-identity.json').read_text())):
            release.build(output, 'v1.2.3')
        record = json.loads((output / 'build-record.json').read_text())
        self.assertEqual(record['identity']['version'], '1.2.3')
        self.assertTrue(record['identity']['dependencies'])

    def test_prepare_hashes_actual_executable_and_keeps_original(self):
        assets = self.prepare()
        manifest = json.loads((assets / 'update.json').read_text())
        target = assets / 'SecondChecking-1.2.3.exe'
        self.assertEqual(manifest['sha256'], release.digest(target))
        self.assertEqual(manifest['size'], target.stat().st_size)
        self.assertEqual(target.read_bytes(), self.artifact.read_bytes())
        self.assertEqual(manifest['metadata']['commit'], self.state['commit'])
        with patch.object(release, 'source_state', return_value=self.state), \
                patch.object(release, 'embedded_identity', return_value=self.identity):
            self.assertEqual(release.verify_bundle(assets, 'v1.2.3'), target)

    def test_stale_source_or_mismatched_embedded_version_cannot_be_renamed(self):
        with patch.object(release, 'source_state', return_value=dict(self.state, version='1.2.4')):
            with self.assertRaisesRegex(ValueError, 'current source'):
                release.prepare(self.output, 'v1.2.4')
        with patch.object(release, 'source_state', return_value=self.state), \
                patch.object(release, 'embedded_identity', return_value=dict(self.identity, version='1.2.4')):
            with self.assertRaisesRegex(ValueError, 'different source'):
                release.prepare(self.output, 'v1.2.3')
        self.assertFalse((self.output / 'release').exists())

    def test_modified_artifact_requires_a_valid_pinned_signature(self):
        self.artifact.write_bytes(b'MZchanged after build')
        with patch.object(release, 'source_state', return_value=self.state), \
                patch.object(release, 'embedded_identity', return_value=self.identity), \
                patch.dict(os.environ, {'APP_UPDATE_SIGNER_SHA256': ''}), \
                patch('services.update_integrity.verify_publisher', side_effect=ValueError('untrusted')) as verify:
            with self.assertRaisesRegex(ValueError, 'untrusted'):
                release.prepare(self.output, 'v1.2.3')
            verify.assert_called_once()
        self.assertFalse((self.output / 'release').exists())

    def test_tampered_manifest_artifact_and_notes_block_upload(self):
        assets = self.prepare()
        originals = {path: path.read_bytes() for path in assets.iterdir()}
        for path, original in originals.items():
            path.write_bytes(b'tampered')
            with patch.object(release, 'source_state', return_value=self.state), \
                    patch.object(release, 'embedded_identity', return_value=self.identity), \
                    patch.object(release, 'run') as remote:
                with self.assertRaises((ValueError, KeyError)):
                    release.publish(assets, 'v1.2.3')
                remote.assert_not_called()
            path.write_bytes(original)

    def test_review_build_is_never_publishable(self):
        assets = self.prepare()
        record = json.loads((assets / 'build-manifest.json').read_text())
        record['identity']['review_only'] = True
        release.write_json(assets / 'build-manifest.json', record)
        with patch.object(release, 'source_state', return_value=self.state), \
                patch.object(release, 'run') as remote:
            with self.assertRaisesRegex(ValueError, 'clean'):
                release.publish(assets, 'v1.2.3')
            remote.assert_not_called()

    def test_wrong_remote_tag_or_existing_release_prevents_mutation(self):
        assets = self.prepare()
        with patch.object(release, 'verify_bundle', return_value=self.artifact), \
                patch.object(release, 'git', return_value=self.state['commit']), \
                patch.object(release, 'run', return_value=Mock(stdout='wrong')) as remote:
            with self.assertRaisesRegex(ValueError, 'Remote tag'):
                release.publish(assets, 'v1.2.3')
            self.assertEqual(remote.call_count, 1)
        with patch.object(release, 'verify_bundle', return_value=self.artifact), \
                patch.object(release, 'git', return_value=self.state['commit']), \
                patch.object(release, 'run', return_value=Mock(stdout=self.state['commit'])) as remote, \
                patch.object(release.subprocess, 'run', return_value=Mock(returncode=0)):
            with self.assertRaisesRegex(ValueError, 'already exists'):
                release.publish(assets, 'v1.2.3')
            self.assertEqual(remote.call_count, 1)

    def test_upload_creates_draft_with_verified_tag_and_all_assets(self):
        assets = self.prepare()
        with patch.object(release, 'verify_bundle', return_value=self.artifact), \
                patch.object(release, 'git', return_value=self.state['commit']), \
                patch.object(release, 'run', return_value=Mock(stdout=self.state['commit'])) as remote, \
                patch.object(release.subprocess, 'run', return_value=Mock(returncode=1)):
            release.publish(assets, 'v1.2.3')
        command = remote.call_args.args[0]
        for argument in ('--draft', '--verify-tag', '--notes-file', str(assets / 'build-manifest.json')):
            self.assertIn(argument, command)
        self.assertNotIn('--clobber', command)

    def test_identity_reporting_is_headless_and_checks_embedded_version(self):
        from version import __version__
        identity = dict(self.identity, version=__version__)
        release.write_json(self.output / 'build-identity.json', identity)
        destination = self.output / 'report.json'
        with patch.object(build_identity.sys, 'frozen', True, create=True), \
                patch.object(build_identity.sys, '_MEIPASS', str(self.output), create=True):
            build_identity.write_report(destination)
            self.assertEqual(json.loads(destination.read_text())['identity'], identity)
            identity['version'] = '999.0.0'
            release.write_json(self.output / 'build-identity.json', identity)
            with self.assertRaises(ValueError):
                build_identity.write_report(destination)


if __name__ == '__main__':
    unittest.main()
