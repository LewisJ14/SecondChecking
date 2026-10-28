"""Compatibility entry point for the shared verified release pipeline."""
import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_package import manifest_for, write_json

ROOT = Path(__file__).resolve().parents[1]


def write_manifest(repo, version, notes):
    """Write content metadata; publication additionally requires build identity."""
    if repo.lower() != 'lewisj14/secondchecking':
        raise ValueError('Release repository does not match the updater trust policy.')
    path = ROOT / 'update.json'
    write_json(path, manifest_for(ROOT / 'dist' / ('SecondChecking-' + version + '.exe'), version, notes))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--tag')
    parser.add_argument('--notes-file')
    parser.add_argument('--artifact')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--publish', action='store_true', help='Create a new draft release after verification.')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.force:
        parser.error('Release replacement is disabled; use a new version/tag.')
    command = [sys.executable, str(ROOT / 'scripts/release_package.py')]
    common = ['--output', args.output]
    if args.tag:
        common += ['--tag', args.tag]
    if args.build:
        subprocess.run(command + ['build'] + common, check=True)
    prepare = command + ['prepare'] + common
    if args.notes_file:
        prepare += ['--notes-file', args.notes_file]
    if args.artifact:
        prepare += ['--artifact', args.artifact]
    subprocess.run(prepare, check=True)
    if args.publish:
        subprocess.run(command + ['publish'] + common, check=True)


if __name__ == '__main__':
    main()
