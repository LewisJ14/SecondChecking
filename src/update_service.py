import json
import os
import re
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from utils.helpers import log_event
from version import __version__ as CURRENT_VERSION

DEFAULT_MANIFEST_URL = "https://github.com/your-org/SecondChecking/releases/latest/download/update.json"


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

    @property
    def current_version(self) -> str:
        return CURRENT_VERSION

    def _normalize_version(self, version: str) -> Tuple[int, ...]:
        parts = [int(match) for match in re.findall(r"\d+", version)]
        return tuple(parts)

    def _is_newer(self, remote_version: str) -> bool:
        if not remote_version:
            return False
        try:
            return self._normalize_version(remote_version) > self._normalize_version(
                CURRENT_VERSION
            )
        except ValueError:
            return False

    def fetch_manifest(self) -> UpdateManifest:
        request = urllib.request.Request(
            self.manifest_url,
            headers={"User-Agent": self.user_agent},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
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
        manifest = self.fetch_manifest()
        if self._is_newer(manifest.version):
            log_event(
                f"Update available: {manifest.version} > {self.current_version}."
            )
            return manifest
        log_event("No new update available.")
        return None

    def launch_update(self, manifest: UpdateManifest) -> None:
        target_url = (
            manifest.download_url or manifest.release_page or self.manifest_url
        )
        if not target_url:
            raise ValueError("No download URL available in update manifest.")
        log_event(f"Opening update URL: {target_url}")
        webbrowser.open(target_url)
