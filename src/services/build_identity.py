"""Read packaged build identity without configuration, GUI or device imports."""
import json
from pathlib import Path
import sys


def read_identity():
    if not getattr(sys, "frozen", False):
        return None
    path = Path(sys._MEIPASS) / "build-identity.json"
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    from version import __version__
    if value.get("identity_version") != 1 or value.get("version") != __version__:
        raise ValueError("Packaged build identity does not match the app version.")
    return value


def display_label():
    try:
        identity = read_identity()
        if identity is None:
            return "source"
        return ("review " if identity["review_only"] else "build ") + identity["build_id"][:8]
    except (OSError, ValueError, KeyError, AttributeError):
        return "build identity unavailable"


def write_report(destination):
    identity = read_identity()
    if identity is None:
        raise ValueError("Build identity report requires a packaged executable.")
    report = {"identity": identity, "packaged": True}
    Path(destination).write_text(json.dumps(report, indent=2), encoding="utf-8")
