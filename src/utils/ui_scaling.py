import ctypes
import ctypes.wintypes
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
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
            class MonitorInfo(ctypes.Structure):
                _fields_ = [("size", ctypes.wintypes.DWORD),
                            ("monitor", ctypes.wintypes.RECT),
                            ("work", ctypes.wintypes.RECT),
                            ("flags", ctypes.wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.MonitorFromWindow.restype = ctypes.wintypes.HANDLE
            monitor = user32.MonitorFromWindow(
                ctypes.wintypes.HWND(widget.winfo_id()), 2)
            info = MonitorInfo()
            info.size = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(ctypes.wintypes.HANDLE(monitor), ctypes.byref(info)):
                rect = info.work
                return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
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
    width = min(max(min_width, width), max(160, work_width - 40))
    height = min(max(min_height, height), max(120, work_height - 40))
    x = left + max(0, (work_width - width) // 2)
    y = top + max(0, (work_height - height) // 2)
    geometry = f"{width}x{height}{x:+d}{y:+d}"
    window.geometry(geometry)
    # Windows/Tk can replace an initial position with a cascading position
    # during the first native map. Reapply once after that map has settled.
    pending = [None]

    def cancel_position(event):
        if event.widget == window and pending[0] is not None:
            window.after_cancel(pending[0])
            pending[0] = None

    def settle_position():
        pending[0] = None
        if window.winfo_exists():
            window.geometry(f"{x:+d}{y:+d}")

    mapped = [bool(window.winfo_ismapped())]

    def first_map(event):
        if event.widget == window and not mapped[0]:
            mapped[0] = True
            if pending[0] is not None:
                window.after_cancel(pending[0])
            # The first native map can happen after the original 50 ms timer.
            # Anchor this final correction to mapping rather than creation.
            pending[0] = window.after(50, settle_position)

    window.bind('<Destroy>', cancel_position, add='+')
    if not mapped[0]:
        window.bind('<Map>', first_map, add='+')
    pending[0] = window.after(50, settle_position)


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


class LiveDpiController:
    """Refresh existing Tk fonts on the UI thread without replacing check state.

    Tk 8.6 has one scaling value per interpreter. Follow the focused application
    window; physical monitors with different DPI still require bench acceptance.
    """

    def __init__(self, root):
        self.root = root
        self.after_id = None
        self.fonts = {}
        self.dpi = self._window_dpi(root)
        self.work_area = get_work_area(root)
        root.bind('<Destroy>', self._destroyed, add='+')
        if sys.platform == 'win32':
            self.after_id = root.after(250, self._poll)

    @staticmethod
    def _window_dpi(window):
        try:
            return int(ctypes.windll.user32.GetDpiForWindow(
                ctypes.wintypes.HWND(window.winfo_id()))) or 96
        except (AttributeError, OSError, tk.TclError):
            return 96

    def _destroyed(self, event):
        if event.widget is self.root:
            if self.after_id is not None:
                self.root.after_cancel(self.after_id)
                self.after_id = None
    def _normalise_font(self, widget, named):
        if 'font' not in widget.keys():
            return
        specification = str(widget.cget('font'))
        if not specification or specification in named:
            return
        if specification not in self.fonts:
            font = tkfont.Font(root=self.root, font=specification)
            # Force metrics even when Tk copied a stale anonymous font cache.
            font.configure(size=font.cget('size'))
            self.fonts[specification] = font
        widget.configure(font=self.fonts[specification])
        named.add(str(self.fonts[specification]))

    def _refresh_widget_fonts(self):
        # New Text widgets can consume <Map> in their class binding, so scan
        # owned widgets on the same UI timer rather than using a global bind.
        named = set(tkfont.names(self.root))

        def visit(widget):
            self._normalise_font(widget, named)
            for child in widget.winfo_children():
                visit(child)

        visit(self.root)

    def _poll(self):
        self.after_id = None
        try:
            try:
                focused = self.root.focus_displayof()
            except (KeyError, tk.TclError):
                # Native combobox popdowns and recently destroyed widgets can
                # own focus without a corresponding Python Tk widget.
                focused = None
            window = focused.winfo_toplevel() if focused else self.root
            dpi = self._window_dpi(window)
            work_area = get_work_area(window)
            if dpi != self.dpi:
                self.refresh(dpi)
            elif work_area != self.work_area:
                self._fit_windows()
            self._refresh_widget_fonts()
            self.work_area = work_area
        finally:
            if self.root.winfo_exists():
                self.after_id = self.root.after(250, self._poll)

    def refresh(self, dpi):
        if dpi <= 0 or dpi == self.dpi:
            return
        ratio = dpi / self.dpi
        self.dpi = dpi
        self.root.tk.call('tk', 'scaling', dpi / 72)
        # Named fonts invalidate their cached metrics when configured. Merely
        # reassigning a tuple font leaves an existing widget's cache unchanged.
        named = set(tkfont.names(self.root))
        for name in named:
            font = tkfont.nametofont(name, self.root)
            font.configure(size=font.cget('size'))

        def visit(widget):
            self._normalise_font(widget, named)
            if isinstance(widget, ttk.Treeview):
                for column in ('#0',) + tuple(widget['columns']):
                    for option in ('width', 'minwidth'):
                        widget.column(column, **{option: max(1, round(
                            widget.column(column, option) * ratio))})
            for child in widget.winfo_children():
                visit(child)

        visit(self.root)
        style = ttk.Style(self.root)
        font = style.lookup('Treeview', 'font') or 'TkDefaultFont'
        style.configure('Treeview', rowheight=tkfont.Font(
            root=self.root, font=font).metrics('linespace') + 8)
        self.root.update_idletasks()
        self._fit_windows()

    def _fit_windows(self):
        def fit(window):
            if window.winfo_ismapped() and window.state() == 'normal':
                left, top, width, height = get_work_area(window)
                # Geometry dimensions exclude the native frame/title bar.
                border = max(0, window.winfo_rootx() - window.winfo_x())
                frame_width = border * 2
                frame_height = max(0, window.winfo_rooty() - window.winfo_y()) + border
                available_width = max(160, width - frame_width - 40)
                available_height = max(120, height - frame_height - 40)
                minimum_width, minimum_height = window.minsize()
                window.minsize(min(minimum_width, available_width),
                               min(minimum_height, available_height))
                w = min(window.winfo_width(), available_width)
                h = min(window.winfo_height(), available_height)
                x = min(max(left, window.winfo_x()),
                        max(left, left + width - w - frame_width - 20))
                y = min(max(top, window.winfo_y()),
                        max(top, top + height - h - frame_height - 20))
                window.geometry('{}x{}{:+d}{:+d}'.format(w, h, x, y))
            window.event_generate('<<AppDpiChanged>>', when='tail')
            for child in window.winfo_children():
                if isinstance(child, tk.Toplevel):
                    fit(child)

        fit(self.root)
