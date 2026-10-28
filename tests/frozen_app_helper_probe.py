"""Windowed frozen IPC probe only; never imported by the production entry point.

All hardware/network/maintenance outcomes in child processes are test fixtures.
"""
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from services import app_helper, maintenance
from services.mdm_evidence import evidence
from version import __version__


def child(directory):
    mode = os.environ["SECOND_CHECK_PROBE_CASE"]
    directory = Path(directory)
    from services.hardware_job import write_ready
    write_ready(directory, json.loads((directory / 'request.json').read_text())['kind'])
    # Explicit DEVNULL redirection can create streams even for runw.exe.
    # Force their absence to exercise the windowed worst case.
    sys.stdout = None
    sys.stderr = None
    if mode == "missing":
        return
    if mode == "malformed":
        (directory / "result.json").write_text("invalid-json", encoding="utf-8")
        return
    if mode == "hang":
        time.sleep(60)
        return
    payload = {"update_check_version": 1, "state": "up_to_date",
               "current_version": __version__}
    if mode == "available":
        payload = {"update_check_version": 1, "state": "update_available",
                   "version": "999.0", "download_url": "https://example.invalid/app.exe"}
    def update():
        if mode == "error":
            raise RuntimeError("Mock failure")
        return payload
    app_helper.update_payload = update
    app_helper.mdm_payload = lambda: evidence("no_local_indicators", "Mock local evidence")
    maintenance.run_windows_updates = lambda: None
    if mode == "mismatch":
        original_write = app_helper.write_result
        app_helper.write_result = lambda path, reply: original_write(
            path, dict(reply, request_id=str(uuid4())))
    app_helper.run_worker(directory)


def probe(output):
    results = {"windowed": sys.stdout is None and sys.stderr is None,
               "asset_present": maintenance.windows_update_script().is_file()}
    for mode in ("up_to_date", "available", "mdm", "windows-update", "error",
                 "missing", "malformed", "mismatch", "hang"):
        Path(output).write_text(json.dumps(dict(results, running=mode), indent=2), encoding="utf-8")
        os.environ["SECOND_CHECK_PROBE_CASE"] = mode
        kind = mode if mode in {"mdm", "windows-update"} else "updates"
        try:
            result = app_helper.run_helper(kind, timeout=3 if mode == "hang" else 60)
            if mode == "up_to_date":
                passed = result.get("state") == "up_to_date"
            elif mode == "available":
                passed = result.get("version") == "999.0"
            elif mode == "mdm":
                passed = result.get("tenant_verification") == "not_checked"
            else:
                passed = mode == "windows-update" and result.get("state") == "completed"
        except Exception as exc:
            results[mode + "_diagnostic"] = type(exc).__name__ + ": " + str(exc)
            passed = mode in {"error", "missing", "malformed", "mismatch", "hang"}
        results[mode] = passed
    results["all_passed"] = all(value for key, value in results.items() if not key.endswith("_diagnostic"))
    Path(output).write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if results["all_passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--app-helper":
        try:
            child(sys.argv[2])
        except BaseException as exc:
            Path(sys.argv[2], "probe-error.txt").write_text(
                type(exc).__name__ + ": " + str(exc), encoding="utf-8")
            sys.exit(1)
    elif len(sys.argv) == 3 and sys.argv[1] == "--probe-output":
        sys.exit(probe(sys.argv[2]))
    else:
        sys.exit(2)
