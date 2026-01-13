# Entry point for the Second Checking Tool application
import sys
import os

if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ttkbootstrap as tb
from app_controller import AppController
from utils.helpers import log_event

if __name__ == "__main__":
    try:
        log_event("Starting application after authenticating via login panel.")
        root = tb.Window(themename="flatly")
        app = AppController(root)
        root.mainloop()
    except Exception:
        import traceback
        with open("startup_error.log", "w") as f:
            f.write(traceback.format_exc())
        raise
