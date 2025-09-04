# Entry point for the Second Checking Tool application
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import ttkbootstrap as tb
from app_controller import AppController

if __name__ == "__main__":
    try:
        root = tb.Window(themename="flatly")
        app = AppController(root)
        root.mainloop()
    except Exception as e:
        import traceback
        with open("startup_error.log", "w") as f:
            f.write(traceback.format_exc())
        raise
