"""Utilities for managing system audio levels during hardware tests."""

from __future__ import annotations

import sys
from typing import Dict

from utils.helpers import log_event

try:
    import ctypes
except Exception:  # pragma: no cover - ctypes is always available on CPython
    ctypes = None  # type: ignore[assignment]


WM_APPCOMMAND = 0x0319
HWND_BROADCAST = 0xFFFF

APPCOMMAND_VOLUME_DOWN = 0x0009
APPCOMMAND_VOLUME_UP = 0x000A
APPCOMMAND_MICROPHONE_VOLUME_DOWN = 0x001D
APPCOMMAND_MICROPHONE_VOLUME_UP = 0x001E


def _send_volume_command(command: int, repeats: int) -> bool:
    """Send a WM_APPCOMMAND to adjust a system audio control."""

    if ctypes is None:
        log_event("ctypes not available; cannot adjust system audio levels.")
        return False

    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - depends on OS availability
        log_event(f"Windows user32 APIs unavailable for volume control: {exc}")
        return False

    success = True
    for _ in range(repeats):
        try:
            user32.SendMessageW(HWND_BROADCAST, WM_APPCOMMAND, 0, command << 16)
        except Exception as exc:  # pragma: no cover - Windows specific behaviour
            log_event(f"Failed to send volume command {command:#04x}: {exc}")
            success = False
            break
    return success


def set_audio_levels_to_maximum() -> Dict[str, bool]:
    """Raise speaker and microphone levels to 100% on supported systems."""

    results = {"speaker": False, "microphone": False}

    if sys.platform != "win32":  # pragma: no cover - executed on Windows only
        log_event("Skipping volume adjustments: supported on Windows systems only.")
        return results

    # Drive each slider all the way down and back up to guarantee 100% output.
    if _send_volume_command(APPCOMMAND_VOLUME_DOWN, 50) and _send_volume_command(
        APPCOMMAND_VOLUME_UP, 50
    ):
        log_event("Set speaker output volume to maximum for speaker test.")
        results["speaker"] = True
    else:
        log_event("Unable to force speaker output volume to maximum.")

    if _send_volume_command(
        APPCOMMAND_MICROPHONE_VOLUME_DOWN, 50
    ) and _send_volume_command(APPCOMMAND_MICROPHONE_VOLUME_UP, 50):
        log_event("Set microphone input level to maximum for speaker test.")
        results["microphone"] = True
    else:
        log_event("Unable to force microphone input level to maximum.")

    return results

