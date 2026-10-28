"""Fail when generated/private files or missing application source enter the index."""
import argparse
from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_BINARIES = frozenset({
    'src/assets/BatteryInfoView/BatteryInfoView.exe',
    'src/mysql_native_password.dll',
})
PUBLIC_ASSETS = PUBLIC_BINARIES | frozenset({
    'src/assets/AudioCheck.wav',
    'src/assets/astro-login-hero.png',
    'src/assets/BatteryInfoView/BatteryInfoView.chm',
    'src/assets/BatteryInfoView/readme.txt',
    'src/assets/__init__.py',
})


def forbidden_reason(name):
    path = PurePosixPath(name.replace('\\', '/'))
    parts = [part.lower() for part in path.parts]
    basename = path.name.lower()
    if any(part in {'build', 'dist', '__pycache__', '.secondchecking-updates',
                    'check-drafts', 'pending-operations',
                    'venv', '.venv', 'venv312', '.pytest_cache'} for part in parts):
        return 'generated build/runtime directory'
    if parts and parts[0] == 'assets':
        return 'duplicate runtime assets; canonical inputs live under src/assets'
    if parts[:2] == ['src', 'output']:
        return 'device exports'
    if (basename in {'config.ini', 'last_user.txt', 'logs.txt', 'specs_cache.json',
                     'batteryinfoview.cfg', 'build-identity.json', 'build-record.json',
                     'build-manifest.json', 'version-resource.txt', 'src.zip'}
            or basename.startswith('logs.txt.')
            or basename.endswith(('.log', '.log.1', '.pyc', '.pyo', '.previous',
                                   '.update.lock', '.pem', '.pfx', '.p12'))
            or basename == '.env' or basename.startswith('.env.') and basename != '.env.example'
            or path.as_posix() == 'update.json'):
        return 'private or generated runtime material'
    if path.suffix.lower() in {'.exe', '.dll'} and path.as_posix() not in PUBLIC_BINARIES:
        return 'unapproved binary artifact'
    if parts[:2] == ['src', 'assets'] and path.as_posix() not in PUBLIC_ASSETS:
        return 'unapproved resource in public packaging inputs'
    return None


def required_paths(root):
    names = {'config.example.ini', 'runtime-files.json', 'main.spec', 'compile.ps1',
             'publish-release.ps1', 'requirements.txt', 'app.manifest',
             '.gitignore', '.gitattributes', '.github/workflows/release.yml',
             'src/Script.ps1'} | set(PUBLIC_ASSETS)
    for directory in ('src', 'scripts', 'tests'):
        names.update(path.relative_to(root).as_posix()
                     for path in (root / directory).rglob('*.py'))
    return names


def check_repository(root=ROOT):
    root = Path(root).resolve()
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=str(root), check=True,
                            capture_output=True)
    paths = set(result.stdout.decode('utf-8').strip('\0').split('\0')) - {''}
    errors = [name + ': ' + reason for name in sorted(paths)
              for reason in [forbidden_reason(name)] if reason]
    errors += [name + ': application/build input is not tracked'
               for name in sorted(required_paths(root) - paths)]
    missing = [name for name in required_paths(root) if not (root / name).is_file()]
    errors += [name + ': required input is missing from disk' for name in sorted(missing)]
    if errors:
        raise ValueError('\n'.join(errors))
    return len(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        count = check_repository(args.root)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print('Source tracking check failed:\n' + str(exc), file=sys.stderr)
        return 1
    print('Source tracking check passed: {} tracked files; no classified runtime/private artifacts.'.format(count))
    return 0


if __name__ == '__main__':
    sys.exit(main())
