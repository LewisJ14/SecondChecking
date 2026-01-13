import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple

from werkzeug.security import check_password_hash, generate_password_hash

from db.database import get_db_connection
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


def _fetch_usernames() -> List[str]:
    conn = get_db_connection()
    if not conn:
        log_event("Unable to load username list; database connection failed.")
        return []

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM user ORDER BY username ASC")
        rows = cursor.fetchall()
        return [row[0] for row in rows if row and row[0]]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _fetch_user_row(username: str) -> Optional[Tuple]:
    conn = get_db_connection()
    if not conn:
        log_event(f"Database connection failed when looking up user '{username}'.")
        return None

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
                SELECT id, email, role, username, password_hash, must_reset_password
                FROM user
                WHERE username = %s
            """,
            (username,),
        )
        row = cursor.fetchone()
        if row:
            log_event(f"Fetched user row for '{username}'.")
        else:
            log_event(f"No user found for '{username}'.")
        return row
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _update_password(user_id: int, raw_password: str) -> None:
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Unable to connect to the database to update password.")

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
                UPDATE user
                SET password_hash = %s, must_reset_password = FALSE
                WHERE id = %s
            """,
            (generate_password_hash(raw_password), user_id),
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


class PasswordResetDialog:
    MIN_LENGTH = 8

    def __init__(self, parent: tk.Tk):
        self.top = tk.Toplevel(parent)
        self.top.title("Reset Password")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.resizable(False, False)
        self.top.geometry("320x180")

        self.password_var = tk.StringVar()
        self.confirm_var = tk.StringVar()
        self.result: Optional[str] = None

        tk.Label(self.top, text="Enter a new password:").pack(pady=(15, 5))
        tk.Entry(self.top, textvariable=self.password_var, show="*").pack(fill="x", padx=20)
        tk.Label(self.top, text="Confirm new password:").pack(pady=(10, 5))
        tk.Entry(self.top, textvariable=self.confirm_var, show="*").pack(fill="x", padx=20)

        tk.Button(self.top, text="Save", command=self._on_save, fg="white", bg="#198754").pack(pady=15)
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
        self.frame = tk.Frame(parent, bg="#f0f0f0")
        self.frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        container = tk.Frame(self.frame, bg="white", bd=1, relief="solid")
        container.place(relx=0.5, rely=0.35, anchor="center")
        container.configure(width=420, height=260)
        container.pack_propagate(False)

        tk.Label(container, text="Login", font=("Segoe UI", 12, "bold")).pack(pady=(10, 6))
        tk.Label(container, text="Username").pack(pady=(4, 2))

        usernames = _fetch_usernames()
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()

        self.username_combo = ttk.Combobox(
            container,
            textvariable=self.username_var,
            state="readonly",
            values=usernames,
            width=30,
        )
        self.username_combo.pack(padx=10)

        if usernames:
            last_user = _load_last_user()
            if last_user and last_user in usernames:
                self.username_combo.current(usernames.index(last_user))
            else:
                self.username_combo.current(0)
        else:
            tk.Label(container, text="No users available.", fg="red").pack(pady=(4, 4))
            self.username_combo.config(state="disabled")

        tk.Label(container, text="Password").pack(pady=(10, 2))
        tk.Entry(container, textvariable=self.password_var, show="*", width=33).pack(padx=10)

        button_frame = tk.Frame(container, bg="white")
        button_frame.pack(pady=(10, 12))

        self.login_button = tk.Button(
            button_frame,
            text="Log In",
            command=self._attempt_login,
            fg="white",
            bg="#0d6efd",
            width=10,
        )
        self.login_button.pack(side="left", padx=5)
        if not usernames:
            self.login_button.config(state="disabled")

        tk.Button(
            button_frame,
            text="Exit",
            command=self._cancel,
            fg="white",
            bg="#dc3545",
            width=10,
        ).pack(side="left", padx=5)

        self.frame.bind("<Return>", lambda event: self._attempt_login())

    def _attempt_login(self) -> None:
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not self.username_combo["values"]:
            messagebox.showwarning("No Users", "No available users to log in.")
            return
        if not username or not password:
            messagebox.showwarning("Missing Credentials", "Username and password are required.")
            return

        log_event(f"Login attempt for '{username}'.")
        try:
            row = _fetch_user_row(username)
        except Exception as exc:
            log_event(f"Login query failed: {exc}")
            messagebox.showerror("Login Failed", f"Unable to verify credentials: {exc}")
            return

        if not row:
            log_event(f"Login failed for '{username}': username not found.")
            messagebox.showerror("Login Failed", "Invalid username or password.")
            return

        user_id, email, role, username_from_db, password_hash, must_reset_flag = row
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

    def _finish(self, user: Optional[AuthenticatedUser]) -> None:
        self.frame.destroy()
        if self.on_complete:
            self.on_complete(user)

    def _cancel(self) -> None:
        log_event("Login cancelled by user.")
        self._finish(None)
