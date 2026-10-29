import tkinter as tk
import threading
import sys
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import List, Optional


from services.auth_service import (authenticate, fetch_usernames, revoke,
                                   update_password as update_user_password)
from services import operator_session
from queue import Queue, Empty
from utils.helpers import get_app_dir, log_event
from utils.ui_scaling import center_window, center_window_to_content, get_work_area
from ui.scrolling import bind_scrolling
from ui.theme import apply_theme
from PIL import Image, ImageTk


@dataclass
class AuthenticatedUser:
    id: int
    username: str
    email: str
    role: str


def _last_user_file_path() -> Path:
    return Path(get_app_dir()) / "last_user.txt"


def _load_last_user() -> Optional[str]:
    path = _last_user_file_path()
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except Exception as exc:
        log_event(f"Failed to read last_user marker: {exc}")
        return None


def _store_last_user(username: str) -> None:
    path = _last_user_file_path()
    try:
        path.write_text(username, encoding="utf-8")
    except Exception as exc:
        log_event(f"Failed to persist last_user marker: {exc}")


def _update_password(user_id: int, raw_password: str) -> None:
    update_user_password(user_id, raw_password)


def _configure_entry_styles() -> None:
    style = ttk.Style()
    style.configure(
        "LoginField.TEntry",
        fieldbackground="white",
        bordercolor="#dce6f2",
        lightcolor="#dce6f2",
        darkcolor="#dce6f2",
        padding=(10, 8),
    )
    style.map(
        "LoginField.TEntry",
        bordercolor=[("focus", "#1f7f52")],
        lightcolor=[("focus", "#1f7f52")],
        darkcolor=[("focus", "#1f7f52")],
    )

    style.configure(
        "LoginSelect.TCombobox",
        fieldbackground="white",
        background="white",
        foreground="#0f172a",
        bordercolor="#dce6f2",
        lightcolor="#dce6f2",
        darkcolor="#dce6f2",
        arrowcolor="#344054",
        padding=(10, 8),
    )
    style.map(
        "LoginSelect.TCombobox",
        fieldbackground=[("readonly", "white"), ("disabled", "#f3f6fa")],
        background=[("readonly", "white"), ("disabled", "#f3f6fa")],
        foreground=[("readonly", "#0f172a"), ("disabled", "#7a8696")],
        bordercolor=[("focus", "#1f7f52"), ("readonly focus", "#1f7f52")],
        lightcolor=[("focus", "#1f7f52"), ("readonly focus", "#1f7f52")],
        darkcolor=[("focus", "#1f7f52"), ("readonly focus", "#1f7f52")],
        arrowcolor=[("disabled", "#98a2b3")],
    )


class PasswordResetDialog:
    MIN_LENGTH = 8

    def __init__(self, parent: tk.Tk):
        self.top = tk.Toplevel(parent)
        self.top.title("Reset Password")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.resizable(True, True)
        self.top.configure(bg="#eef2f7")

        self.password_var = tk.StringVar()
        self.confirm_var = tk.StringVar()
        self.result: Optional[str] = None

        container = tk.Frame(self.top, autostyle=False, bg="white", bd=1, relief="solid")
        container.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            container,
            autostyle=False, text="Set a New Password",
            font=("Segoe UI", 12, "bold"),
            bg="white",
        ).pack(pady=(14, 4))
        tk.Label(
            container,
            autostyle=False, text=f"Use at least {self.MIN_LENGTH} characters.",
            font=("Arial", 9),
            fg="#64748b",
            bg="white",
        ).pack(pady=(0, 10))

        tk.Label(container, autostyle=False, text="New password", anchor="w", bg="white").pack(fill="x", padx=20)
        password_entry = tk.Entry(container, textvariable=self.password_var, show="*", relief="solid", bd=1)
        password_entry.pack(fill="x", padx=20, pady=(4, 8), ipady=4)

        tk.Label(container, autostyle=False, text="Confirm password", anchor="w", bg="white").pack(fill="x", padx=20)
        confirm_entry = tk.Entry(container, textvariable=self.confirm_var, show="*", relief="solid", bd=1)
        confirm_entry.pack(fill="x", padx=20, pady=(4, 12), ipady=4)

        action_row = tk.Frame(container, autostyle=False, bg="white")
        action_row.pack(pady=(0, 14))

        tk.Button(action_row, text="Cancel", command=self._on_cancel, width=10).pack(side="left", padx=6)
        tk.Button(action_row, autostyle=False, text="Save", command=self._on_save, fg="white", bg="#198754", width=10).pack(side="left", padx=6)

        password_entry.focus_set()
        confirm_entry.bind("<Return>", lambda event: self._on_save())
        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)
        center_window_to_content(self.top, min_width=380, min_height=260)
        self.top.focus_force()
        self.top.wait_window()

    def _on_save(self) -> None:
        password = self.password_var.get()
        confirm = self.confirm_var.get()
        if not password:
            messagebox.showwarning("Password Required", "Please enter a new password.")
            return
        if len(password) < self.MIN_LENGTH:
            messagebox.showwarning(
                "Password Too Short",
                f"Password must be at least {self.MIN_LENGTH} characters.",
            )
            return
        if password != confirm:
            messagebox.showwarning("Mismatch", "Both password fields must match.")
            return

        self.result = password
        self.top.destroy()

    def _on_cancel(self) -> None:
        self.top.destroy()


class LoginPanel:
    def __init__(self, parent: tk.Tk, on_complete):
        self.parent = parent
        apply_theme(parent)
        self.on_complete = on_complete
        self._usernames: List[str] = []
        self._login_in_progress = False
        self.parent.title("Second Checking - Sign In")
        self._dpi_binding = parent.bind('<<AppDpiChanged>>',
                                       self._dpi_changed, add='+')
        _configure_entry_styles()
        self.frame = tk.Frame(parent, autostyle=False, bg="#f1f4f8")
        self.frame.bind('<Destroy>', self._remove_dpi_binding, add='+')
        self.frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.login_canvas = tk.Canvas(self.frame, autostyle=False, bg="#f1f4f8", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=self.login_canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.login_canvas.pack(side="left", fill="both", expand=True)
        self.login_canvas.configure(yscrollcommand=scrollbar.set)
        container = tk.Frame(self.login_canvas, autostyle=False, bg="white", bd=0,
                             highlightthickness=1, highlightbackground="#dce6f2")
        self.login_card = container
        self._card_item = self.login_canvas.create_window(0, 0, window=container, anchor="n")
        bind_scrolling(self.login_canvas, container)
        self.form_card = tk.Frame(container, autostyle=False, bg='white')
        self.form_card.grid(row=0, column=0, sticky='nsew')
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=6)
        container.columnconfigure(1, weight=5)
        self.hero = tk.Frame(container, autostyle=False, bg='#1f7f52', padx=24, pady=24)
        self.hero.grid(row=0, column=1, sticky='nsew')
        self.hero_title = tk.Label(self.hero, autostyle=False, text='Welcome to ASTRO',
                                   bg='#1f7f52', fg='white',
                                   font=('Segoe UI', 20, 'bold'), justify='left', anchor='w')
        self.hero_caption = tk.Label(self.hero, autostyle=False,
                                     text='Second Checking\nDevice checks, reports and order processing.',
                                     bg='#1f7f52', fg='#e1f2e8', font=('Arial', 11),
                                     justify='left', anchor='w')
        self.hero_caption.pack(side='bottom', fill='x', pady=(8, 0))
        self.hero_title.pack(side='bottom', fill='x', pady=(14, 8))
        self.hero_image = tk.Label(self.hero, autostyle=False, bg='#1f7f52')
        self.hero_image.pack(fill='both', expand=True)
        self._hero_original = None
        self._hero_size = None
        self._hero_photo = None
        self._hero_visible = None
        base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
        try:
            with Image.open(base / 'assets' / 'astro-login-hero.png') as image:
                self._hero_original = image.convert('RGBA')
        except OSError:
            # Decorative artwork never blocks authentication.
            pass
        container = self.form_card

        accent_bar = tk.Frame(container, autostyle=False, bg="#1f7f52", height=4)
        accent_bar.pack(fill="x", side="top")
        brand = tk.Label(container, autostyle=False, text='ASTRO  /  Second Checking',
                         font=('Arial', 11, 'bold'), bg='white', fg='#1f7f52', anchor='w')
        brand.pack(fill='x', padx=44, pady=(24, 0))

        heading = tk.Label(
            container,
            autostyle=False, text="Sign in",
            font=("Segoe UI", 22, "bold"),
            bg="white",
            fg="#0f172a",
        )
        heading.pack(fill="x", padx=20, pady=(28, 6))
        subtitle = tk.Label(
            container,
            autostyle=False, text="Sign in to continue with device checks and order processing.",
            font=("Arial", 10),
            bg="white",
            fg="#64748b",
            wraplength=420,
            justify="center",
        )
        subtitle.pack(fill="x", padx=20, pady=(0, 22))

        form = tk.Frame(container, autostyle=False, bg="white")
        form.pack(fill="x", padx=44)

        tk.Label(form, autostyle=False, text="Username", anchor="w", bg="white", fg="#344054").pack(fill="x", pady=(0, 4))

        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Loading users...")

        self.username_combo = ttk.Combobox(
            form,
            textvariable=self.username_var,
            state="readonly",
            values=[],
            width=44,
            style="LoginSelect.TCombobox",
        )
        self.username_combo.pack(fill="x", ipady=4)
        self.username_combo.config(state="disabled")

        self.status_label = tk.Label(
            form,
            autostyle=False, textvariable=self.status_var,
            fg="#64748b",
            bg="white",
            wraplength=420,
            justify="left",
            anchor="w",
        )
        self.status_label.pack(fill="x", pady=(6, 16))

        tk.Label(form, autostyle=False, text="Password", anchor="w", bg="white", fg="#344054").pack(fill="x", pady=(0, 4))
        password_entry = ttk.Entry(form, textvariable=self.password_var, show="*", style="LoginField.TEntry")
        self.password_entry = password_entry
        password_entry.pack(fill="x")

        primary_button_frame = tk.Frame(container, autostyle=False, bg="white")
        primary_button_frame.pack(fill="x", padx=44, pady=(28, 10))

        self.login_button = tk.Button(
            primary_button_frame,
            autostyle=False, text="Log In",
            command=self._attempt_login,
            fg="white",
            bg="#1f7f52",
            activebackground="#17643f",
            activeforeground="white",
            relief="flat",
            font=("Arial", 10, "bold"),
            pady=8,
        )
        self.login_button.pack(fill="x")
        self.login_button.config(state="disabled")

        secondary_button_frame = tk.Frame(container, autostyle=False, bg="white")
        secondary_button_frame.pack(fill="x", padx=44, pady=(0, 12))
        secondary_button_frame.columnconfigure((0, 1), weight=1, uniform="actions")

        self.retry_button = tk.Button(
            secondary_button_frame,
            autostyle=False, text="Retry",
            command=self._load_usernames_async,
            fg="#334155",
            bg="#e2e8f0",
            width=11,
            relief="flat",
        )
        self.retry_button.grid(row=0, column=0, sticky="ew", padx=6)
        self.retry_button.config(state="disabled")

        self.exit_button = tk.Button(
            secondary_button_frame,
            autostyle=False, text="Exit",
            command=self._cancel,
            fg="#334155",
            bg="#e2e8f0",
            width=11,
            relief="flat",
        )
        self.exit_button.grid(row=0, column=1, sticky="ew", padx=6)
        from ui.bug_reports import open_report
        ttk.Button(secondary_button_frame, text='Upload bug report…',
                   command=lambda: open_report(self.parent)).grid(
                       row=1, column=0, columnspan=2, sticky='ew', padx=6, pady=(8, 0))

        footer = tk.Label(
            container,
            autostyle=False, text="If Web-Tools is unavailable, you can retry without restarting the app.",
            font=("Arial", 8),
            fg="#667085",
            bg="white",
            wraplength=420,
        )
        footer.pack(fill="x", padx=20, pady=(0, 20))
        self._wrapping_labels = (brand, heading, subtitle, self.status_label, footer)
        self._login_window_sized = False
        self._login_sizing_scheduled = False
        self.login_canvas.bind("<Configure>", self._fit_login_card)
        container.bind("<Configure>", self._fit_login_card)
        # A mapped canvas schedules sizing after the theme's first layout pass.
        self.parent.after_idle(self._configure_login_window)

        self.frame.bind("<Return>", lambda event: self._attempt_login())
        password_entry.bind("<Return>", lambda event: self._attempt_login())
        self._load_usernames_async()

    def _remove_dpi_binding(self, event):
        if event.widget is self.frame:
            # Dispose Tk image resources on the UI thread with the login form.
            self._hero_photo = None
            self._hero_original = None
        if event.widget is self.frame and self._dpi_binding:
            self.parent.unbind('<<AppDpiChanged>>', self._dpi_binding)
            self._dpi_binding = None

    def _dpi_changed(self, event):
        if self.frame.winfo_exists():
            self._fit_login_card()

    def _configure_login_window(self) -> None:
        if not self.frame.winfo_exists():
            return
        self._login_sizing_scheduled = False
        if self.login_canvas.winfo_width() <= 1:
            return
        self._login_window_sized = True
        self.parent.update_idletasks()
        left, top, screen_width, screen_height = get_work_area(self.parent)
        width = min(max(760, self._preferred_card_width() + 80), max(160, screen_width - 40))
        self.parent.geometry(f"{width}x{min(560, max(120, screen_height - 40))}")
        self.login_canvas.itemconfigure(self._card_item, width=max(100, width - 80))
        self.parent.update_idletasks()
        height = min(max(560, self.login_card.winfo_reqheight() + 64),
                     max(120, screen_height - 40))
        x = left + (screen_width - width) // 2
        y = top + (screen_height - height) // 2
        self.parent.geometry(f"{width}x{height}{x:+d}{y:+d}")
        self.parent.minsize(min(480, width), min(360, height))

    def _preferred_card_width(self):
        scale = float(self.parent.tk.call("tk", "scaling")) / (96 / 72)
        work_width = get_work_area(self.parent)[2]
        return round((960 if work_width >= 1100 * scale else 528) * scale)

    def _fit_login_card(self, event=None):
        """Keep natural-height content inside a bounded, focus-scrollable viewport."""
        width = max(1, self.login_canvas.winfo_width())
        height = max(1, self.login_canvas.winfo_height())
        card_width = max(100, min(self._preferred_card_width(), width - 48))
        self.login_canvas.itemconfigure(self._card_item, width=card_width)
        scale = float(self.parent.tk.call('tk', 'scaling')) / (96 / 72)
        show_hero = card_width >= 880 * scale
        if show_hero != self._hero_visible:
            self._hero_visible = show_hero
            if show_hero:
                self.hero.grid()
                self.login_card.columnconfigure(1, weight=5)
            else:
                self.hero.grid_remove()
                self.login_card.columnconfigure(1, weight=0)
        form_width = max(100, int(card_width * 6 / 11) if show_hero else card_width)
        if show_hero:
            hero_width = max(100, card_width - form_width - 48)
            for label in (self.hero_title, self.hero_caption):
                label.configure(wraplength=hero_width)
            size = (min(round(320 * scale), hero_width), round(300 * scale))
            if self._hero_original is not None and size != self._hero_size:
                artwork = self._hero_original.copy()
                artwork.thumbnail(size, Image.Resampling.LANCZOS)
                self._hero_photo = ImageTk.PhotoImage(artwork, master=self.parent)
                self.hero_image.configure(image=self._hero_photo)
                self._hero_size = size
        for label in self._wrapping_labels:
            # The status label sits inside the form's larger side margins.
            inset = 100 if label == self.status_label else 48
            label.configure(wraplength=max(40, form_width - inset))
        self.login_button.configure(wraplength=max(40, form_width - 110))
        card_height = self.login_card.winfo_reqheight()
        y = max(24, (height - card_height) // 2)
        self.login_canvas.coords(self._card_item, width / 2, y)
        self.login_canvas.configure(scrollregion=(0, 0, width, max(height, card_height + 48)))
        if width > 1 and not self._login_window_sized and not self._login_sizing_scheduled:
            self._login_sizing_scheduled = True
            self.parent.after_idle(self._configure_login_window)

    def _set_login_busy(self, is_busy: bool) -> None:
        self._login_in_progress = is_busy
        if is_busy:
            self.login_button.config(text="Verifying credentials...")
            self.login_button.config(state="disabled")
            self.retry_button.config(state="disabled")
            self.username_combo.config(state="disabled")
            self.status_var.set("")
            self.status_label.config(fg="#666")
            return

        self.login_button.config(text="Log In")
        self.retry_button.config(state="normal")
        self.status_var.set("")
        self.status_label.config(fg="#666")
        if self._usernames:
            self.login_button.config(state="normal")
            self.username_combo.config(state="readonly")
        else:
            self.login_button.config(state="disabled")
            self.username_combo.config(state="disabled")

    def _set_username_choices(self, usernames: List[str]) -> None:
        self._usernames = usernames
        self.username_combo["values"] = usernames
        if not usernames:
            self.username_var.set("")
            self.username_combo.config(state="disabled")
            self.login_button.config(state="disabled")
            return

        self.username_combo.config(state="readonly")
        last_user = _load_last_user()
        if last_user and last_user in usernames:
            self.username_combo.current(usernames.index(last_user))
        else:
            self.username_combo.current(0)
        self.login_button.config(state="normal")

    def _finish_username_load(self, usernames: List[str], error_message: Optional[str]) -> None:
        if error_message:
            self.status_var.set(error_message)
            self.status_label.config(fg="#b02a37")
            self._set_username_choices([])
            self.retry_button.config(state="normal")
            return

        if not usernames:
            self.status_var.set("No users available.")
            self.status_label.config(fg="#b02a37")
            self._set_username_choices([])
            self.retry_button.config(state="normal")
            return

        self.status_var.set("")
        self.status_label.config(fg="#666")
        self._set_username_choices(usernames)
        self.retry_button.config(state="normal")

    def _load_usernames_async(self) -> None:
        self.status_var.set("Loading users...")
        self.status_label.config(fg="#666")
        self.login_button.config(text="Log In")
        self.retry_button.config(state="disabled")
        self._login_in_progress = False
        self.login_button.config(state="disabled")
        self.username_combo.config(state="disabled")

        self._start_request(fetch_usernames,
                            lambda result: self._finish_username_load(*result))

    def _start_request(self, operation, callback):
        replies = Queue()
        def worker():
            try:
                replies.put((True, operation()))
            except Exception:
                replies.put((False, "Authentication request failed; retry."))
        def poll():
            if not self.frame.winfo_exists():
                return
            try:
                success, result = replies.get_nowait()
            except Empty:
                self.parent.after(40, poll)
                return
            callback(result if success else (None, result))
        threading.Thread(target=worker, daemon=True).start()
        self.parent.after(40, poll)

    def _handle_login_result(self, result):
        self._set_login_busy(False)
        body, error = result
        self.password_var.set("")
        if error or not body:
            messagebox.showerror("Login Failed", error or "Unable to sign in.")
            return
        user = body["user"]
        if body.get("reset_required"):
            dialog = PasswordResetDialog(self.parent)
            if not dialog.result:
                previous = operator_session.clear()
                threading.Thread(target=revoke, args=(previous,), daemon=True).start()
                self.status_var.set("Password reset is required before sign-in.")
                return
            self._set_login_busy(True)
            def reset():
                try:
                    update_user_password(user["id"], dialog.result)
                    return True, None
                except RuntimeError as exc:
                    return None, str(exc)
            def completed(result):
                self._set_login_busy(False)
                operator_session.clear()
                if result[1]:
                    messagebox.showerror("Password Reset Failed", result[1])
                else:
                    self.status_var.set("Password changed. Sign in with the new password.")
            self._start_request(reset, completed)
            return
        self.user = AuthenticatedUser(id=user["id"], username=user["username"],
                                      email=user.get("email"), role=user["role"])
        _store_last_user(user["username"])
        self._finish(self.user)

    def _attempt_login(self):
        if self._login_in_progress:
            return
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not username or not password:
            messagebox.showwarning("Missing Credentials", "Username and password are required.")
            return
        self._set_login_busy(True)
        self._start_request(lambda: authenticate(username, password), self._handle_login_result)

    def _finish(self, user: Optional[AuthenticatedUser]) -> None:
        self.frame.destroy()
        if self.on_complete:
            self.on_complete(user)

    def _cancel(self) -> None:
        previous = operator_session.clear()
        threading.Thread(target=revoke, args=(previous,), daemon=True).start()
        log_event("Login cancelled by user.")
        self._finish(None)
