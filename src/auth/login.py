import tkinter as tk
import threading
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import List, Optional

from werkzeug.security import check_password_hash

from services.auth_service import fetch_user_record, fetch_usernames, update_password as update_user_password
from utils.helpers import get_app_dir, log_event


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
        bordercolor="#c9d4e0",
        lightcolor="#c9d4e0",
        darkcolor="#c9d4e0",
        padding=(10, 8),
    )
    style.map(
        "LoginField.TEntry",
        bordercolor=[("focus", "#0d6efd")],
        lightcolor=[("focus", "#0d6efd")],
        darkcolor=[("focus", "#0d6efd")],
    )

    style.configure(
        "LoginSelect.TCombobox",
        fieldbackground="white",
        background="white",
        foreground="#1f2937",
        bordercolor="#c9d4e0",
        lightcolor="#c9d4e0",
        darkcolor="#c9d4e0",
        arrowcolor="#344054",
        padding=(10, 8),
    )
    style.map(
        "LoginSelect.TCombobox",
        fieldbackground=[("readonly", "white"), ("disabled", "#f3f6fa")],
        background=[("readonly", "white"), ("disabled", "#f3f6fa")],
        foreground=[("readonly", "#1f2937"), ("disabled", "#7a8696")],
        bordercolor=[("focus", "#0d6efd"), ("readonly focus", "#0d6efd")],
        lightcolor=[("focus", "#0d6efd"), ("readonly focus", "#0d6efd")],
        darkcolor=[("focus", "#0d6efd"), ("readonly focus", "#0d6efd")],
        arrowcolor=[("disabled", "#98a2b3")],
    )


class PasswordResetDialog:
    MIN_LENGTH = 8

    def __init__(self, parent: tk.Tk):
        self.top = tk.Toplevel(parent)
        self.top.title("Reset Password")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.resizable(False, False)
        self.top.geometry("360x220")
        self.top.configure(bg="#eef2f7")

        self.password_var = tk.StringVar()
        self.confirm_var = tk.StringVar()
        self.result: Optional[str] = None

        container = tk.Frame(self.top, bg="white", bd=1, relief="solid")
        container.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            container,
            text="Set a New Password",
            font=("Segoe UI", 12, "bold"),
            bg="white",
        ).pack(pady=(14, 4))
        tk.Label(
            container,
            text=f"Use at least {self.MIN_LENGTH} characters.",
            font=("Segoe UI", 9),
            fg="#5b6573",
            bg="white",
        ).pack(pady=(0, 10))

        tk.Label(container, text="New password", anchor="w", bg="white").pack(fill="x", padx=20)
        password_entry = tk.Entry(container, textvariable=self.password_var, show="*", relief="solid", bd=1)
        password_entry.pack(fill="x", padx=20, pady=(4, 8), ipady=4)

        tk.Label(container, text="Confirm password", anchor="w", bg="white").pack(fill="x", padx=20)
        confirm_entry = tk.Entry(container, textvariable=self.confirm_var, show="*", relief="solid", bd=1)
        confirm_entry.pack(fill="x", padx=20, pady=(4, 12), ipady=4)

        action_row = tk.Frame(container, bg="white")
        action_row.pack(pady=(0, 14))

        tk.Button(action_row, text="Cancel", command=self._on_cancel, width=10).pack(side="left", padx=6)
        tk.Button(action_row, text="Save", command=self._on_save, fg="white", bg="#198754", width=10).pack(side="left", padx=6)

        password_entry.focus_set()
        confirm_entry.bind("<Return>", lambda event: self._on_save())
        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)
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
        self.on_complete = on_complete
        self._usernames: List[str] = []
        self._login_in_progress = False
        self.parent.title("Second Checking - Sign In")
        self._configure_login_window()
        _configure_entry_styles()
        self.frame = tk.Frame(parent, bg="#e7edf5")
        self.frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        shadow = tk.Frame(self.frame, bg="#cfd8e3", bd=0)
        shadow.place(relx=0.5, rely=0.5, anchor="center", width=548, height=448)

        container = tk.Frame(shadow, bg="white", bd=0, highlightthickness=1, highlightbackground="#d6dde8")
        container.place(x=10, y=10, width=528, height=428)
        container.pack_propagate(False)

        accent_bar = tk.Frame(container, bg="#0d6efd", height=8)
        accent_bar.pack(fill="x", side="top")

        tk.Label(
            container,
            text="Second Checking",
            font=("Segoe UI", 18, "bold"),
            bg="white",
            fg="#1f2937",
        ).pack(pady=(28, 6))
        tk.Label(
            container,
            text="Sign in to continue with device checks and order processing.",
            font=("Segoe UI", 10),
            bg="white",
            fg="#5b6573",
            wraplength=420,
            justify="center",
        ).pack(pady=(0, 22))

        form = tk.Frame(container, bg="white")
        form.pack(fill="x", padx=44)

        tk.Label(form, text="Username", anchor="w", bg="white", fg="#344054").pack(fill="x", pady=(0, 4))

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
            textvariable=self.status_var,
            fg="#5b6573",
            bg="white",
            wraplength=420,
            justify="left",
            anchor="w",
        )
        self.status_label.pack(fill="x", pady=(6, 16))

        tk.Label(form, text="Password", anchor="w", bg="white", fg="#344054").pack(fill="x", pady=(0, 4))
        password_entry = ttk.Entry(form, textvariable=self.password_var, show="*", style="LoginField.TEntry")
        password_entry.pack(fill="x")

        primary_button_frame = tk.Frame(container, bg="white")
        primary_button_frame.pack(fill="x", padx=44, pady=(28, 10))

        self.login_button = tk.Button(
            primary_button_frame,
            text="Log In",
            command=self._attempt_login,
            fg="white",
            bg="#0d6efd",
            activebackground="#0b5ed7",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            pady=8,
        )
        self.login_button.pack(fill="x")
        self.login_button.config(state="disabled")

        secondary_button_frame = tk.Frame(container, bg="white")
        secondary_button_frame.pack(pady=(0, 12))

        self.retry_button = tk.Button(
            secondary_button_frame,
            text="Retry",
            command=self._load_usernames_async,
            fg="white",
            bg="#6c757d",
            width=11,
            relief="flat",
        )
        self.retry_button.pack(side="left", padx=6)
        self.retry_button.config(state="disabled")

        tk.Button(
            secondary_button_frame,
            text="Exit",
            command=self._cancel,
            fg="white",
            bg="#dc3545",
            width=11,
            relief="flat",
        ).pack(side="left", padx=6)

        footer = tk.Label(
            container,
            text="If the database is offline, you can retry without restarting the app.",
            font=("Segoe UI", 8),
            fg="#667085",
            bg="white",
        )
        footer.pack(side="bottom", pady=(0, 20))

        self.frame.bind("<Return>", lambda event: self._attempt_login())
        password_entry.bind("<Return>", lambda event: self._attempt_login())
        self._load_usernames_async()

    def _configure_login_window(self) -> None:
        screen_width = self.parent.winfo_screenwidth()
        screen_height = self.parent.winfo_screenheight()
        width = min(max(int(screen_width * 0.48), 760), 920)
        height = min(max(int(screen_height * 0.58), 560), 700)
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.parent.geometry(f"{width}x{height}+{x}+{y}")
        self.parent.minsize(760, 560)

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

        def worker() -> None:
            usernames, error_message = fetch_usernames()
            self.parent.after(0, lambda: self._finish_username_load(usernames, error_message))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_login_lookup_result(self, username: str, row, error_message: Optional[str]) -> None:
        self._set_login_busy(False)

        if error_message:
            messagebox.showerror("Login Failed", error_message)
            return

        if not row:
            log_event(f"Login failed for '{username}': username not found.")
            messagebox.showerror("Login Failed", "Invalid username or password.")
            return

        user_id, email, role, username_from_db, password_hash, must_reset_flag = row
        password = self.password_var.get()
        if not check_password_hash(password_hash, password):
            log_event(f"Login failed for '{username}': invalid password.")
            messagebox.showerror("Login Failed", "Invalid username or password.")
            return

        if must_reset_flag:
            dialog = PasswordResetDialog(self.parent)
            if not dialog.result:
                log_event(f"Password reset required for '{username_from_db}' but was cancelled.")
                messagebox.showinfo("Password Required", "Password reset is required to continue.")
                return
            try:
                _update_password(user_id, dialog.result)
                log_event(f"Password reset completed for '{username_from_db}'.")
            except Exception as exc:
                log_event(f"Failed to update password for user {username_from_db}: {exc}")
                messagebox.showerror("Password Reset Failed", f"Unable to update password: {exc}")
                return

        self.user = AuthenticatedUser(
            id=user_id,
            username=username_from_db,
            email=email,
            role=role,
        )
        log_event(f"User '{username_from_db}' logged in successfully.")
        _store_last_user(username_from_db)
        self._finish(self.user)

    def _attempt_login(self) -> None:
        if self._login_in_progress:
            return
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not self._usernames:
            messagebox.showwarning("Database Unavailable", "No users are loaded. Check the database connection and retry.")
            return
        if not username or not password:
            messagebox.showwarning("Missing Credentials", "Username and password are required.")
            return

        log_event(f"Login attempt for '{username}'.")
        self._set_login_busy(True)

        def worker() -> None:
            row, error_message = fetch_user_record(username)
            self.parent.after(0, lambda: self._handle_login_lookup_result(username, row, error_message))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, user: Optional[AuthenticatedUser]) -> None:
        self.frame.destroy()
        if self.on_complete:
            self.on_complete(user)

    def _cancel(self) -> None:
        log_event("Login cancelled by user.")
        self._finish(None)
