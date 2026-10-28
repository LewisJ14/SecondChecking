"""Run staged/installed executables with owned startup limits."""
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from services.hardware_job import HardwareJob, write_result
from services.update_integrity import UpdateError


def fresh_environment():
    # Independent one-file processes must not inherit the old extraction directory.
    result = {key: value for key, value in os.environ.items()
              if not key.startswith("_PYI_") and key != "_MEIPASS2"}
    result["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return result


def health_worker(directory):
    import sys
    from version import __version__
    request = json.loads((Path(directory) / "request.json").read_text(encoding="utf-8"))
    try:
        import app_controller  # Importability only: no GUI/hardware/database actions.
        from services.maintenance import windows_update_script
        windows_update_script()
        success = True
    except Exception:
        success = False
    write_result(Path(directory), {"health_version": 1,
        "nonce": request["arguments"].get("nonce"), "version": __version__,
        "packaged": bool(getattr(sys, "frozen", False)), "success": success})


def check_health(executable, version):
    nonce = str(uuid4())
    job = HardwareJob("update-health", {"nonce": nonce}, timeout=45,
                      environment=fresh_environment(),
                      command_factory=lambda directory: [str(executable),
                          "--update-healthcheck", str(directory)])
    try:
        while True:
            result = job.poll()
            if result is not None:
                if (not isinstance(result, dict) or result.get("health_version") != 1
                        or result.get("nonce") != nonce or result.get("version") != version
                        or result.get("packaged") is not True or result.get("success") is not True):
                    raise UpdateError("Staged app failed its version/startup health check.")
                if job.process.wait(timeout=5) != 0:
                    raise UpdateError("Staged app exited unsuccessfully.")
                return
            time.sleep(.03)
    finally:
        job.close()


def launch_confirmed(executable, plan_path, expected_version):
    from services.update_transaction import read_json
    directory = Path(plan_path).parent
    report_path = directory / "startup.json"
    if report_path.exists():
        report_path.unlink()
    plan = read_json(plan_path)
    job = HardwareJob("update-startup", timeout=60, environment=fresh_environment(),
                      command_factory=lambda unused: [str(executable),
                          "--update-startup", str(plan_path)])
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if report_path.exists():
                report = read_json(report_path)
                if (report.get("nonce") != plan["id"] or report.get("version") != expected_version
                        or report.get("startup_version") != 1):
                    raise UpdateError("Restart returned an invalid startup confirmation.")
                if job.process.poll() is not None:
                    raise UpdateError("Restarted app exited before confirmation.")
                # The confirmed GUI must survive the installer process exiting.
                if job.process_group is not None:
                    import win32job
                    group = job.process_group
                    limits = win32job.QueryInformationJobObject(group, win32job.JobObjectExtendedLimitInformation)
                    limits['BasicLimitInformation']['LimitFlags'] &= ~win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                    win32job.SetInformationJobObject(group, win32job.JobObjectExtendedLimitInformation, limits)
                    group.Close()
                    job.process_group = None
                job.process = None
                return
            if job.process.poll() is not None:
                raise UpdateError("Restarted app exited without a startup confirmation.")
            time.sleep(.05)
        raise UpdateError("Restart did not confirm startup within the time limit.")
    finally:
        job.close()
