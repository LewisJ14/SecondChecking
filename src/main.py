# Entry point for the Second Checking Tool application
import argparse
import json
import os
import sys

if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ttkbootstrap as tb
from app_controller import AppController
from utils.helpers import get_app_dir, log_event


def run_headless_update_check() -> None:
    """Run the updater without starting the GUI and emit any manifest as JSON."""

    log_event("Running headless update checker.")
    from update_service import UpdateManifest, UpdateService

    service = UpdateService()
    manifest = service.check_for_updates()
    if not manifest:
        return

    payload = {
        "version": manifest.version,
        "download_url": manifest.download_url,
        "release_page": manifest.release_page,
        "notes": manifest.notes,
        "metadata": manifest.metadata,
    }
    print(json.dumps(payload))


def run_headless_mdm_refresh() -> None:
    """Trigger an MDM policy refresh and print the resulting lock status."""

    log_event("Running headless MDM refresh.")
    from utils.helpers import refresh_mdm_lock_status

    status = refresh_mdm_lock_status()
    print(json.dumps(status))


def main() -> None:
    parser = argparse.ArgumentParser(description="Second Checking Tool")
    parser.add_argument("--check-updates", action="store_true", help="run the update checker and exit")
    parser.add_argument(
        "--refresh-mdm",
        action="store_true",
        help="refresh MDM policy and return lock status without launching the UI",
    )
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
        app = AppController(root)
        root.mainloop()
    except Exception:
        import traceback

        startup_error_path = os.path.join(get_app_dir(), "startup_error.log")
        with open(startup_error_path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
