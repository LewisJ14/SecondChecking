# Entry point for the Second Checking Tool application
import argparse
import json
import os
import sys

if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Dispatch before importing the desktop controller. Frozen windowed executables
# use files for IPC because their stdout/stderr may be unavailable.
if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--hardware-worker':
    from services.hardware_job import run_worker
    run_worker(sys.argv[2])
    sys.exit(0)

if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--app-helper':
    from services.app_helper import run_worker
    run_worker(sys.argv[2])
    sys.exit(0)

if __name__ == '__main__' and len(sys.argv) == 3:
    if sys.argv[1] == '--build-info':
        from services.build_identity import write_report
        write_report(sys.argv[2])
        sys.exit(0)
    if sys.argv[1] == '--update-healthcheck':
        from services.update_process import health_worker
        health_worker(sys.argv[2])
        sys.exit(0)
    if sys.argv[1] in ('--apply-update', '--restore-update'):
        from services.update_transaction import worker
        sys.exit(worker(sys.argv[2], restore=sys.argv[1] == '--restore-update'))

# A clean-start check also works without importing Tk or device collectors.
if __name__ == '__main__' and sys.argv[1:] in (['--check-config'], ['--check-schema']):
    from services.configuration import validate_configuration, ConfigurationError
    from db.schema import SchemaCompatibilityError
    try:
        validate_configuration()
        from db.database import check_database_connection
        check_database_connection(check_schema=sys.argv[1] == "--check-schema")
        print("Configuration valid; database SELECT 1 succeeded. API connectivity is untested.")
        if sys.argv[1] == "--check-schema":
            print("Desktop database schema contract 2 satisfied.")
    except (ConfigurationError, SchemaCompatibilityError) as exc:
        print(str(exc))
        sys.exit(1)
    except Exception:
        print("Database check failed. Check settings, network access and server permissions.")
        sys.exit(1)
    sys.exit(0)

import ttkbootstrap as tb
from app_controller import AppController
from utils.helpers import get_app_dir, log_event
from utils.ui_scaling import enable_windows_dpi_awareness, LiveDpiController


def run_headless_update_check() -> None:
    """Run the updater without starting the GUI and emit any manifest as JSON."""

    from services.app_helper import update_payload
    print(json.dumps(update_payload()))


def run_headless_mdm_refresh() -> None:
    """Read local Autopilot evidence and print its qualified status."""

    log_event("Running headless MDM refresh.")
    from utils.helpers import refresh_mdm_lock_status

    status = refresh_mdm_lock_status()
    print(json.dumps(status))


def main() -> None:
    enable_windows_dpi_awareness()

    parser = argparse.ArgumentParser(description="Second Checking Tool")
    parser.add_argument("--check-updates", action="store_true", help="run the update checker and exit")
    parser.add_argument(
        "--refresh-mdm",
        action="store_true",
        help="refresh MDM policy and return lock status without launching the UI",
    )
    parser.add_argument("--update-startup", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.check_updates:
        run_headless_update_check()
        return
    if args.refresh_mdm:
        run_headless_mdm_refresh()
        return

    try:
        log_event("Starting application after authenticating via login panel.")
        root = tb.Window(themename="flatly")
        from services.runtime import log_diagnostic
        from services.build_identity import read_identity
        from version import __version__
        build = read_identity() or {}
        log_diagnostic('application.started', version=build.get('version', __version__),
                       build=str(build.get('build_id') or build.get('commit') or 'source').replace('-', ''))
        root.report_callback_exception = lambda kind, error, trace: log_diagnostic(
            'ui.callback_failed', error=error, stage='tk_callback')
        import threading
        threading.excepthook = lambda args: log_diagnostic(
            'thread.unhandled_exception', error=args.exc_value, stage='background')
        root._live_dpi = LiveDpiController(root)
        app = AppController(root)
        root.update_idletasks()
        if args.update_startup:
            from services.update_transaction import confirm_startup
            confirm_startup(args.update_startup)
        root.mainloop()
    except Exception as exc:
        from services.runtime import log_diagnostic, exception_report
        log_diagnostic('application.startup_failed', error=exc, stage='startup')
        startup_error_path = os.path.join(get_app_dir(), "startup_error.log")
        with open(startup_error_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(exception_report(exc), indent=2))
        raise


if __name__ == "__main__":
    main()
