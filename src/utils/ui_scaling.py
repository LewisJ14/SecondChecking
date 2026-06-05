import ctypes
import ctypes.wintypes
import sys
import tkinter as tk
from typing import Tuple


def enable_windows_dpi_awareness() -> None:
    """Let Windows give Tk real DPI-aware dimensions instead of bitmap scaling."""

    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def get_work_area(widget: tk.Misc) -> Tuple[int, int, int, int]:
    """Return usable desktop bounds, excluding taskbar where Windows exposes it."""

    if sys.platform == "win32":
        try:
            rect = ctypes.wintypes.RECT()
        except AttributeError:
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            rect = RECT()
        try:
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def center_window(window: tk.Toplevel, width: int, height: int, *, min_width: int = 320, min_height: int = 200) -> None:
    """Size and center a window within the usable desktop area."""

    left, top, work_width, work_height = get_work_area(window)
    width = max(min_width, min(width, max(min_width, work_width - 40)))
    height = max(min_height, min(height, max(min_height, work_height - 40)))
    x = left + max(0, (work_width - width) // 2)
    y = top + max(0, (work_height - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def center_window_to_content(window: tk.Toplevel, *, min_width: int = 320, min_height: int = 180) -> None:
    """Center a dialog after geometry managers have calculated its requested size."""

    window.update_idletasks()
    center_window(
        window,
        window.winfo_reqwidth(),
        window.winfo_reqheight(),
        min_width=min_width,
        min_height=min_height,
    )
