"""Build isolated, identifiable Windows artifacts; publication is explicit."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
REPO = "lewisj14/SecondChecking"
ASSETS = ("src/Script.ps1", "src/assets/AudioCheck.wav",
          "src/assets/astro-login-hero.png",
          "src/assets/BatteryInfoView/BatteryInfoView.exe")
BUILD_FILES = ("main.spec", "app.manifest", "requirements.txt", "compile.ps1",
               "publish-release.ps1", ".github/workflows/release.yml",
               ".gitignore", ".gitattributes", "config.example.ini", "runtime-files.json")


def run(command, **kwargs):
    return subprocess.run(command, check=True, cwd=str(ROOT), **kwargs)


def git(*arguments):
    return run(["git"] + list(arguments), capture_output=True,
               text=True).stdout.strip()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            value.update(chunk)
    return value.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")


def load_version():
    tree = ast.parse((ROOT / "src/version.py").read_text(encoding="utf-8-sig"))
    versions = [node.value.value for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__version__"
                        for t in node.targets)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)]
    if len(versions) != 1 or not re.fullmatch(
            r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", versions[0]):
        raise ValueError("Declare exactly one major.minor.patch version.")
    if any(int(p) > 65535 for p in versions[0].split(".")):
        raise ValueError("Version exceeds Windows resource limits.")
    return versions[0]


def source_hashes():
    files = {ROOT / name for name in BUILD_FILES + ASSETS}
    for directory in ("src", "scripts", "tests"):
        files.update((ROOT / directory).rglob("*.py"))
    result = {}
    for path in sorted(files):
        if path.is_symlink() or ROOT not in path.resolve().parents:
            raise ValueError("Build inputs must be regular repository files.")
        result[path.relative_to(ROOT).as_posix()] = digest(path)
    return result


def source_state(tag, allow_dirty=False):
    version = load_version()
    if tag != "v" + version:
        raise ValueError("Release tag must match src/version.py exactly.")
    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=normal"))
    if not allow_dirty:
        if dirty:
            raise ValueError("Release requires a clean checkout; review builds may use --allow-dirty.")
        if git("rev-parse", tag + "^{commit}") != commit:
            raise ValueError("Release tag does not identify HEAD.")
    hashes = source_hashes()
    if not allow_dirty:
        from check_source_policy import check_repository
        check_repository(ROOT)
    if not allow_dirty and not set(hashes).issubset(set(git("ls-files").splitlines())):
        raise ValueError("Release build inputs must all be tracked by Git.")
    return {"version": version, "tag": tag, "commit": commit,
            "dirty": dirty, "review_only": allow_dirty,
            "source_sha256": hashes}


def check_dependencies():
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, expected = line.strip().split("==")
        if importlib.metadata.version(name) != expected:
            raise ValueError("Installed dependency does not match requirements: " + name)


def version_resource(version, destination):
    parts = tuple(int(p) for p in version.split(".")) + (0,)
    # The numeric file version is also checked without starting the GUI/UAC.
    value = ("VSVersionInfo(ffi=FixedFileInfo(filevers={0!r}, prodvers={0!r}, "
             "mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), "
             "kids=[StringFileInfo([StringTable('040904B0', ["
             "StringStruct('FileVersion', {1!r}), StringStruct('ProductVersion', {1!r}), "
             "StringStruct('ProductName', 'SecondChecking')])]), "
             "VarFileInfo([VarStruct('Translation', [1033, 1200])])])").format(parts, version)
    Path(destination).write_text(value, encoding="utf-8")


def embedded_identity(artifact):
    from PyInstaller.archive.readers import CArchiveReader
    import pefile
    archive = CArchiveReader(str(artifact))
    identity = json.loads(archive.extract("build-identity.json").decode("utf-8"))
    image = pefile.PE(str(artifact))
    try:
        if image.OPTIONAL_HEADER.Subsystem != 2:
            raise ValueError("Release must be a windowed Windows executable.")
        info = image.VS_FIXEDFILEINFO[0]
        parts = (info.FileVersionMS >> 16, info.FileVersionMS & 65535,
                 info.FileVersionLS >> 16, info.FileVersionLS & 65535)
        if parts != tuple(int(p) for p in identity["version"].split(".")) + (0,):
            raise ValueError("Windows file version differs from embedded build identity.")
    finally:
        image.close()
    return identity


def build(output, tag, allow_dirty=False):
    check_dependencies()
    state = source_state(tag, allow_dirty)
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Use a dedicated build output directory outside the checkout.")
    output.mkdir(parents=True, exist_ok=False)
    identity = dict(state, identity_version=1, build_id=str(uuid4()),
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    python=sys.version.split()[0],
                    dependencies=sorted([d.metadata['Name'], d.version]
                                        for d in importlib.metadata.distributions()
                                        if d.metadata['Name']))
    write_json(output / "build-identity.json", identity)
    version_resource(state["version"], output / "version-resource.txt")
    environment = dict(os.environ,
                       SECOND_CHECKING_BUILD_IDENTITY=str(output / "build-identity.json"),
                       SECOND_CHECKING_VERSION_RESOURCE=str(output / "version-resource.txt"))
    run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", str(output / "dist"), "--workpath", str(output / "work"),
         str(ROOT / "main.spec")], env=environment)
    if source_state(tag, allow_dirty) != state:
        raise ValueError("Source changed during the build; artifacts cannot be released.")
    artifact = output / "dist/main.exe"
    if embedded_identity(artifact) != identity:
        raise ValueError("Built executable has the wrong embedded identity.")
    write_json(output / "build-record.json", {"identity": identity,
               "unsigned_sha256": digest(artifact), "unsigned_size": artifact.stat().st_size})
    return output


def manifest_for(artifact, version, notes, metadata=None, signer=None):
    value = {"version": version, "sha256": digest(artifact),
             "size": Path(artifact).stat().st_size,
             "download_url": "https://github.com/" + REPO + "/releases/download/v" + version +
                             "/SecondChecking-" + version + ".exe",
             "release_page": "https://github.com/" + REPO + "/releases/tag/v" + version,
             "notes": notes, "metadata": metadata or {}}
    if signer:
        value["signer_sha256"] = signer
    return value


def prepare(output, tag, notes="", artifact=None, allow_dirty=False):
    output = Path(output).resolve()
    record = json.loads((output / "build-record.json").read_text(encoding="utf-8"))
    identity = record["identity"]
    state = source_state(tag, allow_dirty)
    if any(identity.get(key) != value for key, value in state.items()):
        raise ValueError("Build identity does not match the current source/tag/review status.")
    artifact = Path(artifact).resolve() if artifact else output / "dist/main.exe"
    if embedded_identity(artifact) != identity:
        raise ValueError("Executable was built from different source or version.")
    pin = os.environ.get("APP_UPDATE_SIGNER_SHA256", "").strip().lower()
    if pin or digest(artifact) != record["unsigned_sha256"]:
        sys.path.insert(0, str(ROOT / "src"))
        from services.update_integrity import verify_publisher
        verify_publisher(artifact, pin)
    assets = output / "release"
    assets.mkdir(exist_ok=False)
    target = assets / ("SecondChecking-" + identity["version"] + ".exe")
    shutil.copyfile(artifact, target)
    if digest(target) != digest(artifact):
        raise ValueError("Artifact changed during preparation.")
    metadata = {"build_id": identity["build_id"], "commit": identity["commit"],
                "dirty": identity["dirty"], "review_only": identity["review_only"]}
    write_json(assets / "update.json", manifest_for(target, identity["version"], notes, metadata, pin))
    write_json(assets / "build-manifest.json", {"identity": identity,
               "artifact": target.name, "sha256": digest(target),
               "size": target.stat().st_size, "signer_sha256": pin or None})
    return assets


def verify_bundle(assets, tag):
    assets = Path(assets).resolve()
    record = json.loads((assets / "build-manifest.json").read_text())
    identity = record["identity"]
    state = source_state(tag)
    if identity.get("review_only") is not False or any(
            identity.get(key) != value for key, value in state.items()):
        raise ValueError("Only a clean, matching tagged build can be published.")
    name = "SecondChecking-" + state["version"] + ".exe"
    artifact = assets / name
    if (record["artifact"] != name or digest(artifact) != record["sha256"]
            or artifact.stat().st_size != record["size"]
            or embedded_identity(artifact) != identity):
        raise ValueError("Prepared artifact no longer matches its build manifest.")
    update = json.loads((assets / "update.json").read_text())
    expected = manifest_for(artifact, state["version"], update["notes"],
                            update["metadata"], record["signer_sha256"])
    if update != expected:
        raise ValueError("Update manifest does not match the prepared artifact.")
    if (assets / "release-notes.txt").read_text(encoding="utf-8") != update["notes"]:
        raise ValueError("Prepared release notes changed.")
    return artifact


def publish(assets, tag):
    artifact = verify_bundle(assets, tag)
    # Require the remote tag to identify this exact commit; never create/move tags.
    remote = run(["gh", "api", "repos/" + REPO + "/commits/" + tag,
                  "--jq", ".sha"], capture_output=True, text=True).stdout.strip()
    if remote != git("rev-parse", "HEAD"):
        raise ValueError("Remote tag differs from the verified build commit.")
    # Do not overwrite an existing release, delete it, or silently clobber assets.
    existing = subprocess.run(["gh", "release", "view", tag, "--repo", REPO],
                              cwd=str(ROOT), capture_output=True)
    if existing.returncode == 0:
        raise ValueError("Release already exists; review it instead of overwriting assets.")
    assets = Path(assets)
    run(["gh", "release", "create", tag, str(artifact),
         str(assets / "build-manifest.json"), str(assets / "update.json"),
         "--repo", REPO, "--verify-tag", "--draft", "--title", "SecondChecking " + tag,
         "--notes-file", str(assets / "release-notes.txt")])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "prepare", "publish"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--tag")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="Mark a local review build permanently ineligible for publication.")
    parser.add_argument("--artifact", help="Final signed executable from the same build.")
    parser.add_argument("--notes-file", type=Path)
    args = parser.parse_args(argv)
    tag = args.tag or "v" + load_version()
    if args.command == "build":
        result = build(args.output, tag, args.allow_dirty)
    elif args.command == "prepare":
        notes = args.notes_file.read_text(encoding="utf-8") if args.notes_file else ""
        result = prepare(args.output, tag, notes, args.artifact, args.allow_dirty)
        (result / "release-notes.txt").write_text(notes, encoding="utf-8")
    else:
        if args.allow_dirty or args.artifact:
            parser.error("Publication cannot bypass build verification.")
        result = publish(Path(args.output) / "release", tag)
    print("Completed:", result or "draft release")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("Release operation failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
