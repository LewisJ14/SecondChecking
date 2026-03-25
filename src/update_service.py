import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

from utils.helpers import log_event
from version import __version__ as CURRENT_VERSION

DEFAULT_MANIFEST_URL = "https://github.com/lewisj14/SecondChecking/releases/latest/download/update.json"

UPDATE_SCRIPT_CONTENT = r"""
param(
    [Parameter(Mandatory=$true)][string]$NewExePath,
    [Parameter(Mandatory=$true)][string]$TargetExePath,
    [switch]$LaunchAfter
)

function Wait-ForUnlock {
    param($Path)
    if (-not (Test-Path $Path)) {
        return
    }
    for ($attempt = 0; $attempt -lt 360; $attempt++) {
        try {
            $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            $stream.Close()
            return
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Timeout waiting for $Path to become available."
}

function Ensure-Directory {
    param($Path)
    $dir = Split-Path $Path
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
}

Wait-ForUnlock -Path $TargetExePath
Ensure-Directory -Path $TargetExePath

if (Test-Path $TargetExePath) {
    Remove-Item -Force $TargetExePath
}

Move-Item -Force $NewExePath $TargetExePath

if ($LaunchAfter.IsPresent) {
    Start-Process -FilePath $TargetExePath
}
"""


@dataclass
class UpdateManifest:
    version: str
    download_url: Optional[str] = None
    release_page: Optional[str] = None
    notes: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)


class UpdateService:
    """Simple updater that looks for a manifest describing the latest release."""

    def __init__(self, manifest_url: Optional[str] = None, timeout: int = 8):
        self.manifest_url = (
            manifest_url
            or os.getenv("APP_UPDATE_MANIFEST_URL")
            or DEFAULT_MANIFEST_URL
        )
        self.timeout = timeout
        self.user_agent = f"SecondChecking/{CURRENT_VERSION}"
        self._certs_refreshed = False

    @property
    def current_version(self) -> str:
        return CURRENT_VERSION

    def _normalize_version(self, version: str) -> Tuple[int, ...]:
        parts = [int(match) for match in re.findall(r"\d+", version)]
        return tuple(parts)

    def _is_running_packaged(self) -> bool:
        return getattr(sys, "frozen", False)

    def _current_executable(self) -> Path:
        if self._is_running_packaged():
            return Path(sys.executable)
        return Path(sys.argv[0]).resolve()

    def _update_temp_dir(self) -> Path:
        temp_dir = Path(tempfile.gettempdir()) / "SecondCheckingUpdater"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def _download_update(self, url: str, version: str) -> Path:
        temp_dir = self._update_temp_dir()
        target_path = temp_dir / f"SecondChecking-{version}.exe"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = response.read()
        target_path.write_bytes(data)
        log_event(f"Downloaded update {version} to {target_path}.")
        return target_path

    def _write_update_script(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        script_path = directory / "apply_update.ps1"
        script_path.write_text(UPDATE_SCRIPT_CONTENT.strip(), encoding="utf-8")
        return script_path

    def _can_auto_update(self) -> bool:
        return self._is_running_packaged() and sys.platform == "win32"

    def _windows_no_window_creationflags(self) -> int:
        if sys.platform == "win32":
            return subprocess.CREATE_NO_WINDOW
        return 0

    def _spawn_update_script(self, script_path: Path, downloaded_exe: Path) -> None:
        target_exe = self._current_executable()
        args = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-NewExePath",
            str(downloaded_exe),
            "-TargetExePath",
            str(target_exe),
            "-LaunchAfter",
        ]
        subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=self._windows_no_window_creationflags(),
        )

    def _is_newer(self, remote_version: str) -> bool:
        if not remote_version:
            return False
        try:
            return self._normalize_version(remote_version) > self._normalize_version(
                CURRENT_VERSION
            )
        except ValueError:
            return False

    def _maybe_refresh_root_certs(self) -> None:
        if self._certs_refreshed:
            return
        certutil = shutil.which("certutil")
        if not certutil:
            log_event("certutil not found; skipping root cert refresh.")
            self._certs_refreshed = True
            return
        temp_dir = self._update_temp_dir()
        sst_path = temp_dir / "roots.sst"
        try:
            log_event("Refreshing Windows root certificates via certutil.")
            subprocess.run(
                [certutil, "-generateSSTFromWU", str(sst_path)],
                check=True,
                capture_output=True,
                text=True,
                creationflags=self._windows_no_window_creationflags(),
            )
            subprocess.run(
                [certutil, "-addstore", "-f", "root", str(sst_path)],
                check=True,
                capture_output=True,
                text=True,
                creationflags=self._windows_no_window_creationflags(),
            )
            log_event("Root certificate store refreshed.")
        except subprocess.CalledProcessError as exc:
            log_event(
                f"Root cert refresh failed (exit {exc.returncode}): "
                f"{exc.stderr or exc.stdout or exc}"
            )
        finally:
            self._certs_refreshed = True
            if sst_path.exists():
                try:
                    sst_path.unlink()
                except OSError:
                    pass

    def fetch_manifest(self) -> UpdateManifest:
        request = urllib.request.Request(
            self.manifest_url,
            headers={"User-Agent": self.user_agent},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8-sig")
        except urllib.error.URLError as exc:
            log_event(f"Update manifest download failed: {exc}")
            raise

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            log_event(f"Failed to parse update manifest: {exc}")
            raise

        version = (data.get("version") or data.get("tag") or "").strip()
        if not version:
            raise ValueError("Update manifest does not declare a version.")

        manifest = UpdateManifest(
            version=version,
            download_url=data.get("download_url") or data.get("url"),
            release_page=data.get("release_page") or data.get("release_url"),
            notes=data.get("notes") or data.get("release_notes"),
            metadata=data.get("metadata") or {},
        )
        log_event(f"Fetched update manifest for version {manifest.version}.")
        return manifest

    def check_for_updates(self) -> Optional[UpdateManifest]:
        self._maybe_refresh_root_certs()
        manifest = self.fetch_manifest()
        if self._is_newer(manifest.version):
            log_event(
                f"Update available: {manifest.version} > {self.current_version}."
            )
            return manifest
        log_event("No new update available.")
        return None

    def launch_update(self, manifest: UpdateManifest) -> None:
        if manifest.download_url and self._can_auto_update():
            log_event(f"Downloading update from {manifest.download_url}")
            downloaded = self._download_update(manifest.download_url, manifest.version)
            script_path = self._write_update_script(downloaded.parent)
            self._spawn_update_script(script_path, downloaded)
            log_event("Update helper launched.")
            return

        target_url = manifest.release_page or manifest.download_url or self.manifest_url
        if not target_url:
            raise ValueError("No download URL available in update manifest.")
        log_event(f"Opening update URL: {target_url}")
        webbrowser.open(target_url)
