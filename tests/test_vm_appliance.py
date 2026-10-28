"""OVA integrity tests use tiny synthetic disks and never boot a VM."""
import hashlib
import io
from pathlib import Path
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_vm_appliance import verify_ova


class ApplianceTests(unittest.TestCase):
    def fixture(self, root, change=None):
        files = {'fixture.ovf': b'<Envelope xmlns:o="http://schemas.dmtf.org/ovf/envelope/1"><References><File o:href="disk.vmdk" /></References></Envelope>',
                 'disk.vmdk': b'disposable virtual disk fixture'}
        manifest = '\n'.join('SHA256 ({}) = {}'.format(name, hashlib.sha256(value).hexdigest())
                             for name, value in files.items()).encode()
        files['fixture.mf'] = manifest
        if change:
            change(files)
        path = root / 'fixture.ova'
        with tarfile.open(path, 'w') as archive:
            for name, data in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        return path

    def test_complete_sha256_payload_passes_without_extracting_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.fixture(root)
            report = verify_ova(path)
            self.assertEqual(report['embedded_disks'], ['disk.vmdk'])
            self.assertEqual(report['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(list(root.iterdir()), [path])

    def test_corrupt_or_missing_disk_fails(self):
        for change in (lambda files: files.update({'disk.vmdk': b'corrupt'}),
                       lambda files: files.pop('disk.vmdk')):
            with TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    verify_ova(self.fixture(Path(directory), change))

    def test_traversal_and_uncovered_payloads_fail(self):
        for name in ('../escape.vmdk', '/absolute', 'C:/host.iso', 'extra.iso'):
            with TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    verify_ova(self.fixture(Path(directory), lambda files: files.update({name: b'fixture'})))

    def test_external_reference_or_shared_folder_fails_even_with_valid_hash(self):
        for xml in (b'<Envelope xmlns:o="urn:test"><File o:href="../host.iso" /></Envelope>',
                    b'<Envelope xmlns:o="urn:test"><File o:href="disk.vmdk"/><SharedFolder hostPath="C:/host" /></Envelope>'):
            def change(files):
                files['fixture.ovf'] = xml
                files['fixture.mf'] = '\n'.join('SHA256 ({}) = {}'.format(name, hashlib.sha256(value).hexdigest())
                                                for name, value in files.items() if not name.endswith('.mf')).encode()
            with TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    verify_ova(self.fixture(Path(directory), change))

    def test_missing_or_weak_manifest_fails(self):
        for change in (lambda files: files.pop('fixture.mf'),
                       lambda files: files.update({'fixture.mf': b'SHA1 (disk.vmdk) = 123'})):
            with TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    verify_ova(self.fixture(Path(directory), change))


if __name__ == '__main__':
    unittest.main()
