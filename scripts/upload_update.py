"""
Helper to upload a built release artifact and update manifest to GitHub.

This script mirrors the PowerShell workflow without requiring a Windows shell.
It reads `src/version.py`, renames `dist/main.exe` to `SecondChecking-<version>.exe`,
writes `update.json`, and uses the GitHub CLI (`gh`) to create or update the
release that the app’s auto-updater consumes.

Usage:
  python scripts/upload_update.py [--notes NOTES] [--force] [--build]
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def run_command(*cmd: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        check=check,
    )


def load_version() -> str:
    spec = importlib.util.spec_from_file_location("version", ROOT / "src" / "version.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load src/version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    version = getattr(module, "__version__", "").strip()
    if not version:
        raise RuntimeError("src/version.py does not expose __version__")
    return version


def find_repo_slug() -> str:
    output = run_command("git", "remote", "get-url", "origin").stdout.strip()
    match = re.search(r"[:/](.+?)(?:\.git)?$", output)
    if not match:
        raise RuntimeError("Unable to determine GitHub repository slug.")
    return match.group(1)


def ensure_gh_cli():
    try:
        run_command("gh", "--version")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("GitHub CLI ('gh') is required and was not found.") from exc


def build_if_requested(run_build: bool):
    if not run_build:
        return
    print("Running compile.ps1 to refresh dist/main.exe...")
    try:
        run_command(
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "compile.ps1"),
            "-SkipInstall",
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("Failed to run compile.ps1") from exc


def write_manifest(repo: str, version: str, notes: str) -> Path:
    tag = f"v{version}"
    exe_name = f"SecondChecking-{version}.exe"
    manifest = {
        "version": version,
        "download_url": f"https://github.com/{repo}/releases/download/{tag}/{exe_name}",
        "release_page": f"https://github.com/{repo}/releases/tag/{tag}",
        "notes": notes,
        "metadata": {"generated_at": datetime.datetime.utcnow().isoformat() + "Z"},
    }
    manifest_path = ROOT / "update.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def prepare_artifact(version: str) -> Path:
    exe_source = ROOT / "dist" / "main.exe"
    if not exe_source.exists():
        raise RuntimeError("dist/main.exe not found; run the build first.")
    target = ROOT / "dist" / f"SecondChecking-{version}.exe"
    shutil.copy2(exe_source, target)
    return target


def release_exists(tag: str) -> bool:
    result = run_command("gh", "release", "view", tag, check=False)
    return result.returncode == 0


def delete_release(tag: str):
    run_command("gh", "release", "delete", tag, "--yes")


def upload_release(tag: str, artifact: Path, manifest: Path, notes: str, force: bool):
    if release_exists(tag):
        if force:
            print(f"Deleting existing release {tag} (--force).")
            delete_release(tag)
        else:
            print(f"Updating release {tag}")
            run_command("gh", "release", "upload", tag, str(artifact), str(manifest), "--clobber")
            run_command("gh", "release", "edit", tag, "--notes", notes)
            return

    print(f"Creating release {tag}")
    run_command(
        "gh",
        "release",
        "create",
        tag,
        str(artifact),
        str(manifest),
        "--title",
        f"SecondChecking {tag[1:]}",
        "--notes",
        notes,
    )


def main():
    parser = argparse.ArgumentParser(description="Upload update artifacts to GitHub.")
    parser.add_argument("--notes", default="", help="Release notes to embed in GitHub release.")
    parser.add_argument(
        "--build",
        action="store_true",
        help="Run compile.ps1 (with -SkipInstall) before uploading.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force recreate the GitHub release if it already exists.",
    )
    parser.add_argument(
        "--repo",
        help="GitHub repo slug (owner/repo). Defaults to the origin remote.",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    ensure_gh_cli()
    version = load_version()
    tag = f"v{version}"
    repo = args.repo or find_repo_slug()

    build_if_requested(args.build)

    artifact = prepare_artifact(version)
    manifest_path = write_manifest(repo, version, args.notes or f"Release {version}")

    upload_release(tag, artifact, manifest_path, args.notes or f"Release {version}", args.force)


if __name__ == "__main__":
    main()
