"""Release origin, content and Windows publisher checks."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit, unquote
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "lewisj14/SecondChecking"
MAX_MANIFEST = 65536
MAX_BINARY = 512 * 1024 * 1024


class UpdateError(RuntimeError):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise UpdateError("Release version must use major.minor.patch.")
    return tuple(int(part) for part in value.lstrip("v").split("."))


def safe_url(value, redirect=False):
    if not isinstance(value, str):
        raise UpdateError("Release URL is invalid.")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.port in (None, 443)
                 and not parsed.username and not parsed.password
                 and not parsed.fragment and not any(c.isspace() for c in value))
    except ValueError:
        valid = False
    if not valid:
        raise UpdateError("Release URLs must use HTTPS without embedded credentials.")
    if any(part in {".", ".."} for part in unquote(parsed.path).split("/")):
        raise UpdateError("Release URL contains an invalid path.")
    host = parsed.hostname or ""
    if host == "github.com":
        prefix = "/" + REPOSITORY + "/"
        if (not parsed.path[:len(prefix)].casefold() == prefix.casefold()
                or not parsed.path[len(prefix):].startswith("releases/")
                or parsed.query):
            raise UpdateError("Release URL is outside the trusted repository.")
        # GitHub owner/repository names are case insensitive; asset paths are not.
        value = parsed._replace(path=prefix + parsed.path[len(prefix):]).geturl()
    elif not (redirect and host.endswith(".githubusercontent.com")):
        raise UpdateError("Release URL host is not trusted.")
    return value


class TrustedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl, redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_release(url, timeout=8):
    safe_url(url)
    response = build_opener(TrustedRedirects()).open(
        Request(url, headers={"User-Agent": "SecondChecking-Updater"}), timeout=timeout)
    try:
        safe_url(response.geturl(), redirect=True)
    except Exception:
        response.close()
        raise
    return response


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def signer_pin():
    value = os.environ.get("APP_UPDATE_SIGNER_SHA256", "").strip().lower()
    if value and not re.fullmatch(r"[0-9a-f]{64}", value):
        raise UpdateError("APP_UPDATE_SIGNER_SHA256 must be a certificate SHA-256 fingerprint.")
    return value


def verify_publisher(path, expected):
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected or ""):
        raise UpdateError("Configure a trusted publisher certificate before automatic installation.")
    literal = str(Path(path).resolve()).replace("'", "''")
    command = ("$ErrorActionPreference='Stop'; $s=Get-AuthenticodeSignature -LiteralPath '"
               + literal + "'; $h=''; if ($s.SignerCertificate) { "
               "$a=[Security.Cryptography.SHA256]::Create(); try { "
               "$h=([BitConverter]::ToString($a.ComputeHash($s.SignerCertificate.RawData))).Replace('-','').ToLowerInvariant()"
               " } finally { $a.Dispose() } }; "
               "@{status=[string]$s.Status;certificate_sha256=$h}|ConvertTo-Json -Compress")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                                 "-Command", command], capture_output=True, text=True,
                                timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        report = json.loads(result.stdout)
        valid = (result.returncode == 0 and report.get("status") == "Valid"
                 and report.get("certificate_sha256", "").lower() == expected.lower())
    except Exception:
        valid = False
    if not valid:
        raise UpdateError("Executable publisher verification failed; the installed app was retained.")


def verify_content(path, digest, size):
    path = Path(path)
    if path.stat().st_size != size or file_hash(path) != digest:
        raise UpdateError("Update size or SHA-256 does not match the release manifest.")
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise UpdateError("Downloaded content is not a Windows executable.")


def download(manifest, directory, progress=lambda text: None, cancel=None):
    target = Path(directory) / "candidate.exe"
    partial = target.with_suffix(".part")
    deadline = time.monotonic() + 180
    received = 0
    digest = hashlib.sha256()
    try:
        with open_release(manifest.download_url) as response, partial.open("xb") as output:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != manifest.size:
                raise UpdateError("Download length does not match the release manifest.")
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("Update download cancelled; the installed app was retained.")
                if time.monotonic() > deadline:
                    raise UpdateError("Update download exceeded its time limit.")
                chunk = response.read(65536)
                if not chunk:
                    break
                received += len(chunk)
                if received > manifest.size or received > MAX_BINARY:
                    raise UpdateError("Download exceeds the declared size limit.")
                output.write(chunk)
                digest.update(chunk)
                progress("Downloading update: {} / {} MiB".format(
                    received // (1024 * 1024), manifest.size // (1024 * 1024)))
            output.flush()
            os.fsync(output.fileno())
        if received != manifest.size or digest.hexdigest() != manifest.sha256:
            raise UpdateError("Download was incomplete or corrupt; the installed app was retained.")
        os.replace(str(partial), str(target))
        verify_content(target, manifest.sha256, manifest.size)
        return target
    except Exception:
        for path in (partial, target):
            if path.exists():
                path.unlink()
        raise
