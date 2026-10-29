"""Validated releases and two-phase, recoverable application updates."""
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Dict, Optional
from uuid import uuid4
import webbrowser

from services.update_integrity import (MAX_BINARY, MAX_MANIFEST, REPOSITORY,
    UpdateError, UpdateCheckError, certificate_failure, download, file_hash,
    open_release, safe_url, signer_pin, verify_content, verify_publisher,
    version_tuple)
from services.update_transaction import (copy_atomic, load_plan, previous_plan,
    read_json, write_json)
from utils.helpers import log_event
from version import __version__ as CURRENT_VERSION

DEFAULT_MANIFEST_URL = "https://github.com/" + REPOSITORY + "/releases/latest/download/update.json"


@dataclass
class UpdateManifest:
    version: str
    download_url: Optional[str] = None
    release_page: Optional[str] = None
    notes: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
    sha256: Optional[str] = None
    size: Optional[int] = None
    signer_sha256: Optional[str] = None


def parse_manifest(data):
    import re
    if not isinstance(data, dict):
        raise UpdateError("Release manifest must be an object.")
    version = data.get("version", data.get("tag"))
    version_tuple(version)
    version = version.lstrip("v")
    base = "https://github.com/" + REPOSITORY + "/releases/"
    page = data.get("release_page") or data.get("release_url") or base + "tag/v" + version
    if safe_url(page) != base + "tag/v" + version:
        raise UpdateError("Release page does not match the declared version.")
    url = data.get("download_url") or data.get("url")
    if url and safe_url(url) != base + "download/v" + version + "/SecondChecking-" + version + ".exe":
        raise UpdateError("Download does not match the trusted release/version.")
    notes = data.get("notes")
    notes = "" if notes is None else notes
    metadata = data.get("metadata")
    metadata = {} if metadata is None else metadata
    if not isinstance(notes, str) or len(notes) > 16000 or not isinstance(metadata, dict):
        raise UpdateError("Invalid release notes or metadata.")
    digest, size, signer = data.get("sha256"), data.get("size"), data.get("signer_sha256")
    for value in (digest, signer):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value)):
            raise UpdateError("Invalid release SHA-256 value.")
    if size is not None and (type(size) is not int or not 0 < size <= MAX_BINARY):
        raise UpdateError("Invalid release binary size.")
    return UpdateManifest(version, url, page, notes, metadata,
                          digest.lower() if digest else None, size,
                          signer.lower() if signer else None)


class UpdateService:
    def __init__(self, manifest_url=None, timeout=8):
        self.manifest_url = manifest_url or os.getenv("APP_UPDATE_MANIFEST_URL") or DEFAULT_MANIFEST_URL
        self.timeout = timeout
        self.prepared = None

    @property
    def current_version(self):
        return CURRENT_VERSION

    def _normalize_version(self, version):
        return version_tuple(version)

    def _is_newer(self, version):
        return version_tuple(version) > version_tuple(self.current_version)

    def _is_running_packaged(self):
        return bool(getattr(sys, "frozen", False))

    def _current_executable(self):
        return Path(sys.executable).resolve()

    def _can_auto_update(self):
        return self._is_running_packaged() and sys.platform == "win32"

    def _windows_no_window_creationflags(self):
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def fetch_manifest(self):
        try:
            with open_release(self.manifest_url, self.timeout) as response:
                raw = response.read(MAX_MANIFEST + 1)
            if len(raw) > MAX_MANIFEST:
                raise UpdateError("Release manifest exceeds its size limit.")
            return parse_manifest(json.loads(raw.decode("utf-8-sig")))
        except UpdateError as exc:
            from services.runtime import log_diagnostic
            log_diagnostic('update.manifest_rejected', error=exc, stage='validation')
            raise
        except Exception as exc:
            from services.runtime import log_diagnostic
            log_diagnostic('update.manifest_fetch_failed', error=exc, stage='download')
            reason = ('certificate' if certificate_failure(exc) else
                      'invalid_release' if isinstance(exc, (ValueError, UnicodeError))
                      else 'network')
            raise UpdateCheckError(reason) from None

    def check_for_updates(self):
        manifest = self.fetch_manifest()
        return manifest if self._is_newer(manifest.version) else None

    def can_auto_install(self, manifest):
        try:
            manifest = parse_manifest(asdict(manifest))
            pin = signer_pin()
            return bool(self._can_auto_update() and pin and manifest.download_url
                        and manifest.sha256 and manifest.size
                        and (manifest.signer_sha256 is None or manifest.signer_sha256 == pin))
        except (UpdateError, TypeError):
            return False

    def prepare_update(self, manifest, progress=lambda text: None, cancel=None):
        from services.update_process import check_health
        if not self._is_newer(manifest.version):
            raise UpdateError("Automatic installation requires a newer release.")
        target = self._current_executable()
        pin = signer_pin()
        progress("Verifying installed publisher…")
        verify_publisher(target, pin)
        identifier = str(uuid4())
        directory = target.parent / ".secondchecking-updates" / identifier
        directory.mkdir(parents=True)
        write_json(directory / "state.json", {"state": "downloading", "transaction_id": identifier})
        try:
            candidate = download(manifest, directory, progress, cancel)
            progress("Verifying downloaded publisher…")
            verify_publisher(candidate, pin)
            progress("Checking staged app version and startup…")
            check_health(candidate, manifest.version)
            if cancel is not None and cancel.is_set():
                raise UpdateError("Update preparation cancelled; installed copy retained.")
            original = file_hash(target)
            copy_atomic(target, directory / "updater.exe", original)
            verify_publisher(directory / "updater.exe", pin)
            plan = {"plan_version": 1, "id": identifier, "target_name": target.name,
                    "version": manifest.version, "from_version": self.current_version,
                    "sha256": manifest.sha256, "size": manifest.size,
                    "signer_sha256": pin, "original_sha256": original,
                    "original_size": target.stat().st_size}
            path = directory / "plan.json"
            write_json(path, plan)
            write_json(directory / "state.json", {"state": "prepared", "transaction_id": identifier})
            return path
        except Exception:
            write_json(directory / "state.json", {"state": "failed_retained", "transaction_id": identifier})
            raise

    def cancel_prepared(self):
        if self.prepared:
            path, launch_id = self.prepared
            write_json(path.parent / "cancel.json", {"launch_id": launch_id})

    def start_prepared(self, path, restore=False, cancel=None):
        import psutil
        from services.update_process import fresh_environment
        import win32con
        import win32file
        plan, directory, target = load_plan(path)
        helper = directory / "updater.exe"
        launch_id = str(uuid4())
        write_json(directory / "launch.json", {"launch_id": launch_id,
            "parent_pid": os.getpid(), "parent_started": psutil.Process().create_time()})
        self.prepared = (Path(path), launch_id)
        # Deny writes/deletion between verification and process startup.
        handle = win32file.CreateFile(str(helper), win32con.GENERIC_READ,
            win32con.FILE_SHARE_READ, None, win32con.OPEN_EXISTING,
            win32con.FILE_ATTRIBUTE_NORMAL, None)
        process = None
        try:
            verify_content(helper, plan["original_sha256"], plan["original_size"])
            verify_publisher(helper, signer_pin())
            process = subprocess.Popen([str(helper), "--restore-update" if restore else "--apply-update", str(path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=self._windows_no_window_creationflags(), env=fresh_environment())
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("Update handoff cancelled; installed copy retained.")
                ready = directory / "handoff.json"
                if ready.exists():
                    result = read_json(ready)
                    if result.get("launch_id") == launch_id and result.get("ready") is True:
                        if process.poll() is not None:
                            raise UpdateError("Update worker exited during handoff.")
                        return True
                if process.poll() is not None:
                    raise UpdateError("Update worker could not accept the handoff.")
                time.sleep(.05)
            raise UpdateError("Update worker did not confirm readiness; installed copy retained.")
        except Exception:
            self.cancel_prepared()
            if process is not None and process.poll() is None:
                process.terminate()
            raise
        finally:
            handle.Close()

    def launch_update(self, manifest, progress=lambda text: None, cancel=None):
        manifest = parse_manifest(asdict(manifest))
        if not self.can_auto_install(manifest):
            if not webbrowser.open(manifest.release_page):
                raise UpdateError("Could not open the trusted release page.")
            return False
        path = self.prepare_update(manifest, progress, cancel)
        from services.auth_service import authorize
        authorize("maintenance")
        progress("Preparing a verified restart…")
        return self.start_prepared(path, cancel=cancel)

    def last_outcome(self):
        path = previous_plan(self._current_executable())
        if path is None:
            return None
        try:
            state = read_json(path.parent / "state.json")
            current = state.get("state")
            if current not in {"installed", "rolled_back", "failed_retained",
                               "recovery_required", "rollback_restart_failed",
                               "installing", "restarting", "blocked"}:
                return None
            if current in {"installing", "restarting"}:
                import psutil
                try:
                    process = psutil.Process(state["worker_pid"])
                    if abs(process.create_time() - state["worker_started"]) < .01:
                        return None
                except (psutil.NoSuchProcess, KeyError):
                    pass
                current = "interrupted"
            notice = path.parent / "notice.json"
            if notice.exists() and read_json(notice).get("state") == current:
                return None
            write_json(notice, {"state": current})
            return current
        except (OSError, ValueError, KeyError):
            return None

    def restore_previous(self, progress=lambda text: None, cancel=None):
        path = previous_plan(self._current_executable())
        if path is None:
            raise UpdateError("No retained previous version is available.")
        from services.auth_service import authorize
        authorize("maintenance")
        progress("Preparing previous-version recovery…")
        return self.start_prepared(path, restore=True, cancel=cancel)
