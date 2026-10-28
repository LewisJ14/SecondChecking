"""Verify a portable OVA without extracting its disk or trusting host paths."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import xml.etree.ElementTree as ET


def sha256(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        result.update(chunk)
    return result.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name and not path.is_absolute() and '\\' not in name
                and ':' not in name
                and all(p not in ('.', '..', '') for p in name.split('/')))


def verify_ova(path):
    path = Path(path)
    with tarfile.open(path, 'r:') as archive:
        members = archive.getmembers()
        names = [item.name for item in members]
        if (not members or len(members) > 64 or len(names) != len(set(names))
                or any(not item.isfile() or not safe_name(item.name)
                       for item in members)):
            raise ValueError('OVA contains invalid, duplicate or non-file members.')
        manifests = [name for name in names if name.endswith('.mf')]
        descriptors = [name for name in names if name.endswith('.ovf')]
        disks = [name for name in names if name.endswith('.vmdk')]
        if len(manifests) != 1 or len(descriptors) != 1 or not disks:
            raise ValueError(
                'OVA must contain a manifest, descriptor and virtual disk.')
        for name in manifests + descriptors:
            if archive.getmember(name).size > 4 * 1024 * 1024:
                raise ValueError('OVA metadata exceeds its size limit.')
        content = archive.extractfile(manifests[0]).read().decode('utf-8-sig')
        expected = {}
        for line in content.splitlines():
            match = re.fullmatch(r'SHA256\s*\((.+)\)\s*=\s*([0-9a-fA-F]{64})',
                                 line.strip())
            if not match or not safe_name(match[1]) or match[1] in expected:
                raise ValueError('OVA needs unique SHA-256 manifest entries.')
            expected[match[1]] = match[2].lower()
        if set(expected) != set(names) - set(manifests):
            raise ValueError('OVA manifest does not cover every payload member.')
        for name, digest in expected.items():
            with archive.extractfile(name) as stream:
                if sha256(stream) != digest:
                    raise ValueError('OVA member failed SHA-256 verification: ' + name)
        descriptor = ET.fromstring(archive.extractfile(descriptors[0]).read())
        references = []
        for node in descriptor.iter():
            if node.tag.rsplit('}', 1)[-1] == 'SharedFolder':
                raise ValueError('OVA must not depend on a host shared folder.')
            for key, value in node.attrib.items():
                if key.rsplit('}', 1)[-1] == 'href':
                    if not safe_name(value) or value not in names:
                        raise ValueError('OVF references an external payload.')
                    references.append(value)
        if not set(disks).issubset(set(references)):
            raise ValueError('OVF does not reference every included disk.')
    with path.open('rb') as stream:
        digest = sha256(stream)
    return {'artifact': path.name, 'size': path.stat().st_size, 'sha256': digest,
            'manifest_members_verified': sorted(expected), 'embedded_disks': disks,
            'host_shared_folders': False, 'external_payload_references': False,
            'verification':
                'passed; actual import/boot must be checked separately'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ova', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = verify_ova(args.ova)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('OVA payload and SHA-256 manifest verified; '
          'import/boot is a separate check.')


if __name__ == '__main__':
    main()
