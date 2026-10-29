import json
import queue
import os
import shutil
import subprocess
import sys
import threading
import time
from copy import deepcopy
from ui.scrolling import ScrollableFrame, bind_scrolling
from ui.theme import apply_theme
import tkinter as tk
import tkinter.font as tkfont
from typing import Optional

import re
import ttkbootstrap as tb
from tkinter import messagebox
from ttkbootstrap import ttk

from auth.login import AuthenticatedUser, LoginPanel
from main_logic import (
    build_results_footer,
    load_laptop_specs,
    render_results,
    save_order_note_for_order_id,
    search_order_logic,
)
from utils.specs import reset_specs_cache
from ui.tests import TestsWindow
from services import operator_session, auth_service
from services.maintenance import MaintenanceCancelled, MaintenanceError
from services.check_results import badge_text
from services.check_session import CheckSession, result_state
from services.mdm_evidence import summary as mdm_summary, qualified, evidence as mdm_evidence
from services.measurements import measurement_summary, fresh
from main_logic import start_hash_capture_status_update
from update_service import UpdateManifest, UpdateService
from utils.helpers import (
    check_mdm_lock_status,
    get_live_battery_percent,
    get_live_battery_state,
    is_battery_charging,
    log_event,
)
from utils.ui_scaling import get_work_area


class AppController:
    def __init__(self, root: tk.Tk):
        reset_specs_cache()
        self.root = root
        apply_theme(root)
        self.current_user: Optional[AuthenticatedUser] = None
        self._note_save_inflight = 0
        self._maintenance_running = False
        self._operator_locked = False
        self._update_preparing = False
        self.test_results = {}
        self.test_labels = {}
        self.tests_window = None
        self._tests_runner = None
        self._check_session = CheckSession()
        self._lookup_valid = False
        self._search_inflight = False
        self._search_generation = 0
        self._requested_reference = None
        self._search_after_id = None
        self._visible_specs = None
        self._active_resolved = None
        self._measurement_after_id = None
        self.update_service = UpdateService()
        self.mdm_status = None
        self._mdm_refresh_started = False
        self._showing_default_specs = True
        self.current_order_note_order_id: Optional[int] = None
        self.current_order_note_order_number: Optional[str] = None

        width, height, x, y = self._compute_geometry()
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(800, 500)
        self.root.resizable(True, True)

        self.root.bind("<Destroy>", self._operator_destroyed, add="+")
        self.login_panel = LoginPanel(root, self._on_authenticated)

    def _on_authenticated(self, user: Optional[AuthenticatedUser]) -> None:
        if not user:
            log_event("Login cancelled without authentication.")
            self.root.destroy()
            sys.exit(0)

        self.current_user = user
        self._build_ui()
        self.root.after(800, self._show_update_outcome)

    def _operator_destroyed(self, event):
        if event.widget is self.root:
            self._update_ui_closed = True
            update_poll = getattr(self, "_update_check_after_id", None)
            if update_poll:
                self.root.after_cancel(update_poll)
            pending = getattr(self, '_details_resize_after_id', None)
            if pending:
                self.root.after_cancel(pending)
                self._details_resize_after_id = None
            previous = operator_session.clear()
            if previous:
                threading.Thread(target=auth_service.revoke, args=(previous,), daemon=True).start()

    def _require_operator(self, action):
        if getattr(self, "_update_preparing", False):
            messagebox.showinfo("Update in progress", "Finish or cancel update preparation first.")
            return False
        if getattr(self, "_operator_locked", False) or not operator_session.allowed(action):
            messagebox.showinfo("Sign in required",
                                "Use Operator > Lock / change operator to sign in again.")
            return False
        return True

    def lock_operator(self):
        runner = getattr(self, "_tests_runner", None)
        if (getattr(self, "_update_preparing", False) or self._search_inflight or getattr(self.root, "_assignment_running", False) is True
                or self._note_save_inflight or self._maintenance_running
                or (runner and runner.is_busy())):
            messagebox.showinfo("Bench busy", "Finish the current operation before changing operator.")
            return
        if any(isinstance(child, tk.Toplevel) for child in self.root.winfo_children()):
            messagebox.showinfo("Close open windows", "Save or close open dialogs before changing operator.")
            return
        if not self._preserve_check_draft():
            return
        self._operator_locked = True
        self._lookup_valid = False
        self._showing_default_specs = False
        self._search_generation += 1
        self.current_user = None
        previous = operator_session.clear()
        threading.Thread(target=auth_service.revoke, args=(previous,), daemon=True).start()
        for name in ("_measurement_after_id", "_search_after_id", "_battery_bar_after_id",
                     "_details_resize_after_id"):
            timer = getattr(self, name, None)
            if timer:
                self.root.after_cancel(timer)
                setattr(self, name, None)
        job = getattr(self, "_battery_live_job", None)
        if job:
            job.cancel()
        # A fresh process prevents old callbacks/dialogs adopting a new operator.
        for child in self.root.winfo_children():
            child.destroy()
        self.root.config(menu="")
        self.root.title("SecondChecking — Locked")
        ttk.Label(self.root, text="Locked. Local check drafts are preserved.",
                  padding=20).pack()
        def sign_in_again():
            command = ([sys.executable] if getattr(sys, "frozen", False) else
                       [sys.executable, os.path.join(os.path.dirname(__file__), "main.py")])
            try:
                from services.update_process import fresh_environment
                subprocess.Popen(command, env=fresh_environment(),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                messagebox.showerror("Sign in", "Could not open sign-in. Retry or reopen the app.")
                return
            self.root.destroy()
        ttk.Button(self.root, text="Sign in / change operator", command=sign_in_again).pack(pady=10)
        ttk.Button(self.root, text="Exit", command=self.root.destroy).pack()

    def _build_ui(self) -> None:
        version_label = self.update_service.current_version
        from services.build_identity import display_label
        title = f"Second Checking Tool - Version {version_label} ({display_label()})"
        if self.current_user:
            title = f"{title} - {self.current_user.username}"
        self.root.title(title)

        width, height, x, y = self._compute_geometry()
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # A named default also keeps dialogs opened after a DPI transition at
        # the current scale, rather than reusing an old anonymous font cache.
        self._ui_font = tkfont.Font(root=self.root, family="Segoe UI", size=11)
        self.root.option_add("*Font", self._ui_font)

        style = apply_theme(self.root)

        primary_bg = "#f1f4f8"
        self.root.configure(bg=primary_bg)
        style.configure("Header.TFrame", background="#ffffff")

        menubar = tk.Menu(self.root, autostyle=False, bg=primary_bg, fg="#222")
        self.root.config(menu=menubar)
        tools_menu = tk.Menu(menubar, autostyle=False, tearoff=0, bg=primary_bg, fg="#222")
        operator_menu = tk.Menu(menubar, tearoff=0)
        operator_menu.add_command(label="Lock / change operator", command=self.lock_operator)
        menubar.add_cascade(label="Operator", menu=operator_menu)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Check for App Updates", command=self.check_for_updates)
        tools_menu.add_command(label="Restore previous app version", command=self.restore_previous_update)
        tools_menu.add_command(label="Run Windows Updates", command=self.run_windows_update_script)
        from ui.bug_reports import open_report
        tools_menu.add_separator()
        tools_menu.add_command(label="Upload bug report…", command=lambda: open_report(self.root))

        header_frame = ttk.Frame(self.root, padding=(18, 14, 18, 14), style="Header.TFrame")
        header_frame.pack(fill="x")
        ttk.Label(header_frame, text='ASTRO · Second Checking', style='HeaderTitle.TLabel',
                  font=('Segoe UI', 16, 'bold')).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))

        self.test_panel_button = ttk.Button(
            header_frame,
            text="Test Menu",
            command=self.open_test_panel,
            style="primary.Outline.TButton",
        )
        self.test_panel_button.grid(row=1, column=0, padx=(0, 10), pady=0, sticky="w")

        self.order_reference = tk.StringVar()
        self.order_entry = ttk.Entry(header_frame, textvariable=self.order_reference,
                                     width=32, font=("Arial", 11))
        self.order_entry.configure(width=12)
        self.order_entry.grid(row=1, column=1, padx=(0, 10), pady=0, sticky="ew")
        self.order_entry.bind("<Return>", lambda event: self.run_search())

        self.search_button = ttk.Button(
            header_frame,
            text="Search Order",
            command=self.run_search,
            style="primary.TButton",
        )
        self.search_button.grid(row=1, column=2, sticky="ew")

        self.version_label = ttk.Label(
            header_frame,
            text='{}  ·  Version {}'.format(
                self.current_user.username if self.current_user else 'Operator',
                self.update_service.current_version),
            font=("Arial", 9),
            style='HeaderMuted.TLabel',
        )
        self._version_text = self.version_label.cget("text")
        self.version_label.grid(row=0, column=2, sticky="e", pady=(0, 12))

        self.order_context_label = ttk.Label(
            header_frame, text="No order loaded. Bench checks are kept for this device.",
            wraplength=760,
            style='Header.TLabel',
        )
        self.order_context_label.grid(row=2, column=0, columnspan=2,
                                      sticky="w", pady=(8, 0))
        self.refresh_device_button = ttk.Button(
            header_frame, text="Refresh Device", command=self.refresh_device,
            style="secondary.Outline.TButton",
        )
        self.refresh_device_button.grid(row=2, column=2, sticky="e", pady=(8, 0))
        self.measurement_label = ttk.Label(header_frame, text="Device measurements not captured.",
                                           wraplength=760, style='HeaderMuted.TLabel',
                                           font=('Arial', 9))
        self.measurement_label.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        header_frame.grid_columnconfigure(0, weight=0)
        header_frame.grid_columnconfigure(1, weight=1)
        header_frame.grid_columnconfigure(2, weight=0)
        header_frame.grid_columnconfigure(3, weight=0)

        self.canvas_frame = tk.Frame(self.root, autostyle=False, bg=primary_bg)
        self.canvas_frame.pack(expand=True, fill="both", padx=10, pady=10)
        self.canvas_frame.grid_rowconfigure(0, weight=1)
        self.canvas_frame.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.canvas_frame, autostyle=False, bg="#fff", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.configure(borderwidth=0, relief="flat")

        self.canvas_scrollbar = ttk.Scrollbar(
            self.canvas_frame,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.canvas_scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.canvas_scrollbar.set)
        bind_scrolling(self.canvas)
        self.canvas._sc12_wheel = True

        self.footer_shell = tk.Frame(self.root, autostyle=False, bg='#ffffff')
        self.footer_shell.pack(side='bottom', fill='x', padx=10, pady=(0, 10),
                               before=self.canvas_frame)
        footer_heading = ttk.Frame(self.footer_shell, padding=(12, 8), style='Surface.TFrame')
        footer_heading.pack(fill='x')
        self.footer_overview = ttk.Label(footer_heading, text='Device review and order notes',
                                         style='Surface.TLabel')
        self.footer_overview.pack(side='left', fill='x', expand=True)
        self.footer_toggle = ttk.Button(footer_heading, text='Hide details',
                                        style='secondary.Outline.TButton',
                                        command=self._toggle_footer)
        self.footer_toggle.pack(side='right')
        self.footer_scroll = ScrollableFrame(self.footer_shell, height=135)
        self.footer_scroll.pack(fill='x')
        self.footer_frame = tk.Frame(
            self.footer_scroll.content,
            autostyle=False, bg="#ffffff",
            padx=12,
            pady=8,
            highlightbackground="#d7dde8",
            highlightthickness=1,
        )
        self.footer_frame.pack(fill="x")
        self.footer_frame.grid_columnconfigure(0, weight=1)
        self.footer_frame.grid_columnconfigure(1, weight=0)

        self.spec_summary_footer = tk.Label(
            self.footer_frame,
            autostyle=False, text="",
            font=("Arial", 10, "bold"),
            fg="#1f7a4d",
            bg="#ffffff",
            anchor="w",
            justify="left",
        )
        self.spec_summary_footer.grid(row=0, column=0, sticky="ew")

        self.mdm_footer = tk.Label(
            self.footer_frame,
            autostyle=False, text="",
            font=("Arial", 10, "bold"),
            fg="#1f7a4d",
            bg="#ffffff",
            anchor="w",
            justify="left",
        )
        self.mdm_footer.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.footer_frame.bind("<Configure>", self._resize_mdm_footer)

        self.autopilot_hash_footer = tk.Label(
            self.footer_frame,
            autostyle=False, text="",
            font=("Arial", 10, "bold"),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
        )
        self.autopilot_hash_footer.grid(row=2, column=0, sticky="ew", pady=(2, 0))

        self.battery_footer = tk.Label(
            self.footer_frame,
            autostyle=False, text="",
            font=("Arial", 10, "bold"),
            fg="#101828",
            bg="#ffffff",
            anchor="w",
            justify="left",
        )
        self.battery_footer.grid(row=3, column=0, sticky="ew", pady=(6, 0))

        self.battery_bar_canvas = tk.Canvas(
            self.footer_frame,
            autostyle=False, height=22,
            bg="#ffffff",
            highlightthickness=0,
            bd=0,
        )
        self.battery_bar_canvas.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        self.order_notes_card = tk.Frame(
            self.footer_frame,
            autostyle=False, bg="#f8fafc",
            highlightbackground="#d7dde8",
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        self.order_notes_card.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        self.order_notes_header = tk.Frame(self.order_notes_card, autostyle=False, bg="#f8fafc")
        self.order_notes_header.pack(fill="x", anchor="w")

        self.order_notes_title = tk.Label(
            self.order_notes_header,
            autostyle=False, text="Order Notes",
            font=("Arial", 10, "bold"),
            fg="#101828",
            bg="#f8fafc",
            anchor="w",
            justify="left",
        )
        self.order_notes_title.pack(side="left", fill="x", expand=True, anchor="w")

        self.order_notes_edit_button = ttk.Button(
            self.order_notes_header,
            text="Edit",
            command=self._edit_order_notes,
            style="secondary.TButton",
            state="disabled",
        )
        self.order_notes_edit_button.pack(side="right")

        self.order_notes_body = tk.Frame(self.order_notes_card, autostyle=False, bg="#f8fafc")
        self.order_notes_body.pack(fill="both", expand=False, pady=(4, 0))

        self.order_notes_footer = tk.Text(
            self.order_notes_body,
            autostyle=False, height=3,
            width=1,
            font=("Arial", 10),
            fg="#475467",
            bg="#f8fafc",
            wrap="word",
            bd=0,
            highlightthickness=0,
        )
        self.order_notes_footer.pack(side="left", fill="both", expand=True)

        self.order_notes_scrollbar = ttk.Scrollbar(
            self.order_notes_body,
            orient="vertical",
            command=self.order_notes_footer.yview,
        )
        self.order_notes_scrollbar.pack(side="right", fill="y")
        self.order_notes_footer.configure(yscrollcommand=self.order_notes_scrollbar.set)
        self.order_notes_footer.insert("1.0", "No notes attached to this order.")
        self.order_notes_footer.configure(state="disabled")
        self._battery_bar_after_id = None
        self._battery_bar_percent = None
        self._battery_bar_label = "Battery: Unknown"
        self._battery_bar_name = "Battery"
        self._battery_bar_charging = False
        self._battery_bar_pulse = 0.0
        self._battery_bar_poll_tick = 0

        self.root._update_results_footer = self._update_results_footer
        self.root._update_hash_capture_status = self._update_hash_capture_status
        self.root._update_order_notes_footer = self._update_order_notes_footer
        self.root._check_results_changed = self._preserve_check_draft
        self.root._check_report_saved = self._check_report_saved
        self.root.protocol("WM_DELETE_WINDOW", self._close_app)
        self._details_resize_after_id = None
        self._render_laptop_specs()
        self.root.bind("<Configure>", self.on_resize)
        self.root.after(0, self._center_current_window)
        # Automatically check for updates once per launch (silent=no pop-up when up-to-date)
        self.check_for_updates(silent=True)

    def on_resize(self, event):
        if event.widget in (self.root, self.canvas, self.footer_scroll.content,
                            getattr(self.canvas, '_comparison_content', None)):
            self._schedule_details_resize()
        if event.widget != self.root:
            return
        width = max(240, event.width - 40)
        self.order_context_label.config(wraplength=max(120, width - self.refresh_device_button.winfo_reqwidth() - 20))
        self.measurement_label.config(wraplength=width)
        self.footer_overview.config(wraplength=max(150, width - self.footer_toggle.winfo_reqwidth() - 20))

    def _schedule_details_resize(self):
        if self._details_resize_after_id is None:
            self._details_resize_after_id = self.root.after_idle(self._fit_details_panel)

    def _fit_details_panel(self):
        self._details_resize_after_id = None
        if not self.footer_scroll.winfo_manager():
            return
        details = self.footer_scroll.canvas
        comparison = getattr(self.canvas, '_comparison_content', None)
        baseline = max(80, min(160, int(self.root.winfo_height() * .22)))
        target = baseline
        if comparison is not None and comparison.winfo_exists():
            combined = self.canvas.winfo_height() + details.winfo_height()
            needed = max(120, comparison.winfo_reqheight() + 8)
            spare = max(baseline, combined - needed)
            target = min(max(baseline, self.footer_scroll.content.winfo_reqheight()), spare)
        if int(float(details.cget('height'))) != target:
            details.configure(height=target)

    def _toggle_footer(self):
        if self.footer_scroll.winfo_manager():
            self.footer_scroll.pack_forget()
            self.footer_toggle.config(text='Show details and notes')
        else:
            self.footer_scroll.pack(fill='x')
            self.footer_toggle.config(text='Hide details')
            self._schedule_details_resize()

    def _scroll_results_canvas(self, event) -> str:
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 * int(event.delta / 120)
        self.canvas.yview_scroll(delta, "units")
        return "break"

    def _compute_geometry(self):
        left, top, screen_width, screen_height = get_work_area(self.root)
        scale = float(self.root.tk.call('tk', 'scaling')) / (96 / 72)
        width = min(int(screen_width * .94), round(1400 * scale))
        height = min(int(screen_height * .92), round(900 * scale))
        width = min(max(760, width), screen_width - 40)
        height = min(max(520, height), screen_height - 80)
        x = left + (screen_width - width) // 2
        y = top + (screen_height - height) // 2
        return width, height, x, y

    def _center_current_window(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        left, top, screen_width, screen_height = get_work_area(self.root)
        x = left + max(0, (screen_width - width) // 2)
        y = top + max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _update_results_footer(
        self,
        summary_text: str,
        summary_color: str,
        mdm_text: str,
        mdm_color: str,
        battery_lines,
    ) -> None:
        from services.runtime import log_diagnostic
        log_diagnostic('comparison.footer_updated', count=len(battery_lines),
                       state='match' if summary_text == 'All listed specs match.' else 'review')
        self.spec_summary_footer.config(text=summary_text, fg=summary_color)
        self.footer_overview.config(text=("Review required; MDM NOT VERIFIED — details/notes"
                                          if summary_text != "All listed specs match."
                                          else "Listed specs match; MDM NOT VERIFIED — details/notes"))
        self.mdm_footer.config(text=mdm_text, fg=mdm_color)
        first_battery_line = battery_lines[0] if battery_lines else "Battery: Unknown"
        extra_lines = battery_lines[1:] if battery_lines and len(battery_lines) > 1 else []
        self.battery_footer.config(text="\n".join(extra_lines))
        self._set_battery_bar(first_battery_line)

    def _resize_mdm_footer(self, event):
        width = max(160, event.width - 30)
        for label in (self.spec_summary_footer, self.mdm_footer,
                      self.autopilot_hash_footer, self.battery_footer):
            label.config(wraplength=width)

    def _set_battery_bar(self, battery_line: str) -> None:
        line = (battery_line or "Battery: Unknown").strip()
        if ":" in line:
            self._battery_bar_name = line.split(":", 1)[0].strip() or "Battery"
        percent_match = re.search(r"(\d+)%", line)
        self._battery_bar_percent = int(percent_match.group(1)) if percent_match else None
        self._battery_bar_charging = "— Charging" in line
        self._battery_bar_label = line
        self._battery_bar_pulse = 0.0
        self._draw_battery_bar()
        if self._battery_bar_after_id:
            try:
                self.root.after_cancel(self._battery_bar_after_id)
            except Exception:
                pass
            self._battery_bar_after_id = None
        self._battery_bar_poll_tick = 0
        self._schedule_battery_bar_animation()

    def _update_hash_capture_status(self, text: str, color: str) -> None:
        if getattr(self, "_operator_locked", False):
            return
        self.autopilot_hash_footer.config(text=text or "", fg=color or "#475467")

    def _update_order_notes_footer(
        self,
        text: str,
        order_id: Optional[int] = None,
        order_number: Optional[str] = None,
    ) -> None:
        self.current_order_note_order_id = order_id
        self.current_order_note_order_number = order_number
        self.order_notes_edit_button.configure(state="normal" if order_id else "disabled")
        notes_value = (text or "").strip() or "No notes attached to this order."
        self.order_notes_footer.configure(state="normal")
        self.order_notes_footer.delete("1.0", "end")
        self.order_notes_footer.insert("1.0", notes_value)
        self.order_notes_footer.configure(state="disabled")

    def _edit_order_notes(self) -> None:
        if not self._require_operator("notes"):
            return
        order_id = self.current_order_note_order_id
        if not order_id:
            messagebox.showwarning("Notes", "Search for an order before editing notes.")
            return

        current_text = self.order_notes_footer.get("1.0", "end").strip()
        if current_text.startswith("No notes attached to this "):
            current_text = ""

        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Order Notes")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg="#f1f4f8")
        dialog.minsize(460, 300)

        body = tk.Frame(dialog, autostyle=False, bg="#ffffff", padx=14, pady=14)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        title = "Order Notes"
        if self.current_order_note_order_number:
            title = f"{title} - {self.current_order_note_order_number}"
        tk.Label(
            body,
            autostyle=False, text=title,
            font=("Arial", 11, "bold"),
            fg="#101828",
            bg="#ffffff",
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        editor_frame = tk.Frame(body, autostyle=False, bg="#ffffff")
        editor_frame.pack(fill="both", expand=True)
        editor = tk.Text(
            editor_frame,
            height=10,
            width=64,
            font=("Arial", 10),
            wrap="word",
            undo=True,
        )
        editor.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(editor_frame, orient="vertical", command=editor.yview)
        scrollbar.pack(side="right", fill="y")
        editor.configure(yscrollcommand=scrollbar.set)
        editor.insert("1.0", current_text)

        button_row = tk.Frame(body, autostyle=False, bg="#ffffff")
        button_row.pack(fill="x", pady=(12, 0))

        replies = queue.Queue()
        state = {'closed': False, 'saving': False, 'after': None}
        generation = self._search_generation
        order_number = self.current_order_note_order_number
        status = tk.StringVar(value='Changes are not saved until Save succeeds.')
        ttk.Label(body, textvariable=status, wraplength=480).pack(fill='x')

        def close_dialog() -> None:
            state['closed'] = True
            if state['after'] is not None:
                dialog.after_cancel(state['after'])
                state['after'] = None
            dialog.destroy()

        dialog.protocol('WM_DELETE_WINDOW', close_dialog)

        def poll_save():
            state['after'] = None
            if state['closed']:
                return
            try:
                ok, text, detail = replies.get_nowait()
            except queue.Empty:
                state['after'] = dialog.after(50, poll_save)
                return
            state['saving'] = False
            if not ok:
                editor.config(state='normal')
                save_button.config(state='normal')
                status.set('Save was not confirmed. Your text is retained. '
                           'Reload/check the saved note before retrying after '
                           'a connection error.')
                log_event('Order note save not confirmed; editor contents retained.')
                return
            if (self._lookup_valid and self.current_order_note_order_id == order_id
                    and self._search_generation == generation):
                self._update_order_notes_footer(text, order_id, order_number)
            close_dialog()

        def save_notes() -> None:
            if state['saving']:
                return
            new_text = editor.get('1.0', 'end').strip()
            if (not self._lookup_valid
                    or self.current_order_note_order_id != order_id
                    or self._search_generation != generation):
                status.set('Resolve the order again before saving notes.')
                return
            state['saving'] = True
            self._note_save_inflight = getattr(self, "_note_save_inflight", 0) + 1
            editor.config(state='disabled')
            save_button.config(state='disabled')
            status.set('Saving… Closing this editor stops waiting; it does not '
                       'cancel the submitted database save.')

            def worker():
                try:
                    save_order_note_for_order_id(order_id, new_text)
                except Exception as exc:
                    from services.runtime import log_diagnostic
                    log_diagnostic('order.note_save_failed', error=exc, stage='save')
                    replies.put((False, new_text, str(exc)))
                else:
                    replies.put((True, new_text, ''))
                finally:
                    self._note_save_inflight -= 1
            try:
                threading.Thread(target=worker, daemon=True).start()
            except Exception as exc:
                self._note_save_inflight -= 1
                from services.runtime import log_diagnostic
                log_diagnostic('order.note_save_failed', error=exc, stage='launch')
                replies.put((False, new_text, str(exc)))
            state['after'] = dialog.after(50, poll_save)

        ttk.Button(button_row, text='Close editor', command=close_dialog,
                   style='secondary.TButton').pack(side='right', padx=(8, 0))
        save_button = ttk.Button(button_row, text='Save', command=save_notes,
                                 style='success.TButton')
        save_button.pack(side='right')

        dialog.update_idletasks()
        width = max(520, dialog.winfo_reqwidth())
        height = max(360, dialog.winfo_reqheight())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        editor.focus_set()
        dialog.wait_window()

    def _refresh_primary_battery_state(self) -> None:
        from services.hardware_job import JobPoller
        from services.measurements import battery_power_label
        job = getattr(self, '_battery_live_job', None)
        if job is not None and not job.closed:
            return
        if time.monotonic() < getattr(self, '_battery_next_refresh', 0):
            return
        self._battery_next_refresh = time.monotonic() + 10

        def apply(reply):
            live = reply.get('battery', {}) if reply.get('state') == 'complete' else {}
            percent = live.get('percent')
            charging = live.get('charging') is True
            changed = (percent != self._battery_bar_percent
                       or charging != self._battery_bar_charging)
            self._battery_bar_percent = percent
            self._battery_bar_charging = charging
            if percent is None:
                self._battery_bar_label = 'Current charge: {}'.format(
                    live.get('state', 'unreadable').title())
            else:
                self._battery_bar_label = 'Current charge: {}% {}'.format(
                    percent, battery_power_label(live))
            if changed:
                self._battery_bar_pulse = 0.0

        self._battery_live_job = JobPoller(self.root, 'battery-live', apply, timeout=10)

    def _schedule_battery_bar_animation(self) -> None:
        self._battery_bar_poll_tick += 1
        if self._battery_bar_poll_tick >= 5:
            self._battery_bar_poll_tick = 0
            self._refresh_primary_battery_state()

        if self._battery_bar_percent is not None:
            self._battery_bar_pulse += 0.08
            if self._battery_bar_pulse > 1.0:
                self._battery_bar_pulse = 0.0
        else:
            self._battery_bar_pulse = 0.0

        self._draw_battery_bar()
        self._battery_bar_after_id = self.root.after(60, self._schedule_battery_bar_animation)

    def _draw_battery_bar(self) -> None:
        canvas = self.battery_bar_canvas
        canvas.delete("all")
        width = canvas.winfo_width()
        if width <= 1:
            return
        scale = float(canvas.tk.call('tk', 'scaling')) / (96 / 72)
        padding = max(2, round(4 * scale))
        text_id = canvas.create_text(
            padding, padding, anchor="nw",
            width=max(1, width - 2 * padding),
            text=self._battery_bar_label, fill="#1f3447",
            font=("Arial", 10, "bold"), tags="charge-label",
        )
        text_bounds = canvas.bbox(text_id)
        bar_width = max(1, width - 2 * padding)
        bar_height = max(6, round(8 * scale))
        x1 = padding
        y1 = text_bounds[3] + padding
        x2 = x1 + bar_width
        y2 = y1 + bar_height
        required_height = y2 + padding
        if int(canvas.cget('height')) != required_height:
            canvas.configure(height=required_height)

        canvas.create_rectangle(x1, y1, x2, y2, fill="#edf1f7",
                                outline="#d7dde8", tags="charge-track")

        if self._battery_bar_percent is None:
            fill_width = 0
            fill_color = "#98a2b3"
        else:
            pulse_amplitude = 6.0
            if self._battery_bar_charging:
                display_percent = max(
                    0,
                    min(100, self._battery_bar_percent + (pulse_amplitude * self._battery_bar_pulse)),
                )
            else:
                display_percent = max(
                    0,
                    min(100, self._battery_bar_percent - (pulse_amplitude * self._battery_bar_pulse)),
                )
            fill_width = int(bar_width * display_percent / 100)
            if self._battery_bar_percent >= 70:
                fill_color = "#22b8a0"
            elif self._battery_bar_percent >= 45:
                fill_color = "#f59e0b"
            else:
                fill_color = "#e74c3c"

        if fill_width > 0:
            canvas.create_rectangle(x1, y1, x1 + fill_width, y2, fill=fill_color, outline="")

    def run_search(self):
        if not self._require_operator("read"):
            return
        if getattr(self, "_search_inflight", False) or getattr(self.root, "_assignment_running", False) is True:
            return
        runner = getattr(self, "_tests_runner", None)
        if runner and runner.is_busy():
            messagebox.showinfo("Tests running", "Finish the current hardware test before changing order.")
            return
        order_id = self.order_entry.get().strip()
        log_event(f"User initiated order search for reference: {order_id}")
        if not order_id or not re.match(r"^[A-Za-z0-9\-]{3,32}$", order_id):
            log_event(f"Invalid order ID entered: {order_id}")
            messagebox.showerror("Invalid Reference", "Please enter a valid order number (alphanumeric, 3-32 characters).")
            log_event(f"User entered invalid order ID: '{order_id}'")
            return

        if not self._preserve_check_draft():
            return
        self._invalidate_order_context()

        log_event(f"User initiated search for order: {order_id}")
        self._showing_default_specs = False
        self._update_hash_capture_status("", "#475467")
        self._update_order_notes_footer("")
        if getattr(self, "tests_window", None) and self.tests_window.winfo_exists():
            self._tests_runner.on_close()
            self.tests_window = None

        self._search_inflight = True
        self._search_generation = getattr(self, "_search_generation", 0) + 1
        generation = self._search_generation
        self._requested_reference = order_id
        self.order_entry.config(state="disabled")
        self._set_order_context(f"Searching {order_id}. Existing check drafts are preserved.")
        self.search_button.config(state="disabled")
        self.test_panel_button.config(state="disabled")
        self.canvas.delete("search_status")

        self.search_text_id = self.canvas.create_text(
            self.canvas.winfo_width() // 2,
            20,
            text="Searching",
            font=("Arial", 12, "italic"),
            fill="gray",
            tags="search_status",
        )
        self.animate_dots(0)

        def reenable_button():
            self._finish_device_lookup(generation)

        search_order_logic(
            order_id,
            self.canvas,
            self.search_button,
            self.test_results,
            self.test_labels,
            self.root,
            self.current_user.username if self.current_user else None,
            on_complete=reenable_button,
            on_resolved=lambda resolved: self._accept_order_search(
                generation, order_id, resolved),
        )

    def _set_order_context(self, text):
        label = getattr(self, "order_context_label", None)
        if label is not None:
            label.config(text=text)

    def _preserve_check_draft(self):
        session = getattr(self, "_check_session", None)
        if session is None:
            self._check_session = CheckSession()
            session = self._check_session
        try:
            if session.key is None and result_state(self.test_results) != result_state({}):
                raise ValueError("A device serial is required before these checks can be stored safely.")
            session.preserve(self.test_results)
            if getattr(self, "_lookup_valid", False) and session.key and session.key[0]:
                state = ("Unsaved checks kept as a local draft."
                         if result_state(self.test_results) != session.baseline
                         else "Checks ready.")
                self._set_order_context(
                    f"Loaded order: {session.order_number} | Device: {session.key[1]} | {state}")
            return True
        except (OSError, ValueError) as exc:
            log_event(f"Could not preserve check draft: {exc}")
            messagebox.showerror("Check draft not saved",
                                 "Your checks remain in memory. Navigation was stopped.\n" + str(exc))
            return False

    def _stop_search_animation(self):
        pending = getattr(self, "_search_after_id", None)
        if pending:
            self.root.after_cancel(pending)
            self._search_after_id = None
        self.canvas.delete("search_status")

    def _invalidate_order_context(self):
        self._lookup_valid = False
        self._showing_default_specs = False
        self._stop_search_animation()
        for widget in self.canvas.winfo_children():
            widget.destroy()
        self.canvas.delete("all")
        summary = getattr(self, "spec_summary_footer", None)
        if summary is not None:
            summary.config(text="No resolved order comparison.", fg="#475467")
        self._update_hash_capture_status("", "#475467")
        self.test_panel_button.config(state="disabled")
        self._update_order_notes_footer("")
        self._set_order_context("No order loaded. Submit a search to load an order.")

    def _accept_order_search(self, generation, reference, resolved):
        if (generation != self._search_generation
                or self._requested_reference != reference):
            return
        try:
            session = self._check_session
            draft, conflict = session.candidate(
                resolved["order_id"], resolved["serial_number"], resolved["test_results"])
            if conflict:
                choice = messagebox.askyesnocancel(
                    "Local draft and saved report differ",
                    f"Unsaved checks exist for order {resolved['order_number']} / "
                    f"device {resolved['serial_number']}, but the saved report has changed.\n\n"
                    "Yes: restore the local draft.\nNo: discard it and load the saved report.\nCancel: stop this lookup and keep the draft.",
                )
                if choice is None:
                    return
                if not choice:
                    session.store.discard(tuple(draft["key"]))
                    draft = None
            results = session.activate(
                resolved["order_id"], resolved["order_number"],
                resolved["serial_number"], resolved["test_results"], draft)
            self.test_results.clear()
            self.test_results.update(results)
            self._requested_reference = reference
            self.mdm_status = qualified(resolved["mdm"])
            guard = lambda: (self._lookup_valid
                             and generation == self._search_generation
                             and self._requested_reference == reference)
            render_results(
                self.canvas, resolved["order_number"], resolved["sku"],
                resolved["serial_number"], resolved["specs"], resolved["details"],
                self.test_results, resolved["mdm"],
                self.current_user.username if self.current_user else None,
                True, resolved["notes"], self.root, context_guard=guard,
            )
            if resolved["footer"]:
                self._update_results_footer(*resolved["footer"])
            self._update_order_notes_footer(resolved["notes"], resolved["order_id"],
                                            resolved["order_number"])
            self._lookup_valid = True
            self._active_resolved = deepcopy(resolved)
            self._visible_specs = deepcopy(resolved["specs"])
            self._update_measurement_label()
            suffix = "Local draft restored; not saved to Web-Tools." if draft else "Checks ready; changes are kept locally until assigned."
            self._set_order_context(
                f"Loaded order: {resolved['order_number']} | Device: {resolved['serial_number']} | {suffix}")
            self.test_panel_button.config(state="normal")
            start_hash_capture_status_update(self.root, resolved["serial_number"],
                                             "order search", context_guard=guard)
        except (OSError, ValueError, KeyError, tk.TclError) as exc:
            self._invalidate_order_context()
            messagebox.showerror("Order checks not loaded", str(exc))

    def _check_report_saved(self, order_id, serial, saved_results):
        try:
            self._check_session.confirmed(order_id, serial, saved_results)
            self._preserve_check_draft()
        except (OSError, ValueError) as exc:
            messagebox.showwarning("Check draft cleanup", "The server saved the report, but the local draft could not be cleared.\n" + str(exc))

    def _finish_device_lookup(self, generation):
        if generation != self._search_generation:
            return
        self._search_inflight = False
        self._stop_search_animation()
        self.update_test_result_labels()
        self.test_panel_button.config(state="normal" if self._lookup_valid or self._showing_default_specs else "disabled")
        self.search_button.config(state="normal")
        self.order_entry.config(state="normal")
        button = getattr(self, "refresh_device_button", None)
        if button is not None:
            button.config(state="normal")
        if not self._lookup_valid and not self._showing_default_specs:
            self._set_order_context("Order not resolved. Check drafts are preserved; search again.")

    def _update_measurement_label(self):
        label = getattr(self, "measurement_label", None)
        if label is None:
            return
        pending = getattr(self, "_measurement_after_id", None)
        if pending:
            self.root.after_cancel(pending)
        label.config(text=measurement_summary(self._visible_specs or {}))
        self._measurement_after_id = self.root.after(15000, self._update_measurement_label)

    def refresh_device(self):
        if getattr(self, "_update_preparing", False):
            return
        if self._search_inflight or getattr(self.root, "_assignment_running", False) is True:
            return
        runner = self._tests_runner
        if runner and runner.is_busy():
            messagebox.showinfo("Tests running", "Finish the current hardware test before refreshing measurements.")
            return
        if not self._preserve_check_draft():
            return
        resolved = deepcopy(self._active_resolved) if self._lookup_valid else None
        reference = self._requested_reference if resolved else None
        if self.tests_window and self.tests_window.winfo_exists():
            self._tests_runner.on_close()
            self.tests_window = None
        self._invalidate_order_context()
        self._search_generation += 1
        generation = self._search_generation
        self._search_inflight = True
        self.search_button.config(state="disabled")
        self.order_entry.config(state="disabled")
        self.refresh_device_button.config(state="disabled")
        self._set_order_context("Refreshing device measurements; check drafts are preserved.")

        def worker():
            try:
                specs = load_laptop_specs(force_refresh=True)
                serial = specs.get("Serial Number")
                if not serial or serial == "Unknown" or not fresh(specs):
                    raise ValueError("Fresh device measurements are unavailable.")
                if resolved and serial != resolved["serial_number"]:
                    raise ValueError("Device identity changed. The old draft was kept; search again for this device.")
                mdm = check_mdm_lock_status()
                def apply():
                    if generation != self._search_generation:
                        return
                    try:
                        if resolved:
                            resolved["specs"], resolved["mdm"] = specs, mdm
                            resolved["footer"] = build_results_footer(specs, resolved["details"], mdm)
                            self._accept_order_search(generation, reference, resolved)
                        else:
                            draft, _ = self._check_session.candidate(0, serial, {})
                            results = self._check_session.activate(0, "", serial, {}, draft)
                            self.test_results.clear()
                            self.test_results.update(results)
                            self._visible_specs, self.mdm_status = specs, mdm
                            self._showing_default_specs = True
                            self._search_inflight = False
                            self._render_laptop_specs()
                            self._update_measurement_label()
                            self._set_order_context("No order loaded. Device refreshed; bench checks are kept locally.")
                    except (OSError, ValueError, KeyError, tk.TclError) as exc:
                        self._invalidate_order_context()
                        messagebox.showerror("Device refresh failed", str(exc))
                self.root.after(0, apply)
            except Exception as exc:
                text = str(exc)
                self.root.after(0, lambda: messagebox.showerror("Device refresh failed", text))
            finally:
                self.root.after(0, lambda: self._finish_device_lookup(generation))
        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as exc:
            self._finish_device_lookup(generation)
            messagebox.showerror("Device refresh failed", str(exc))

    def _close_app(self):
        if getattr(self, "_update_preparing", False):
            messagebox.showinfo("Update preparation", "Use Cancel in the update dialog before closing.")
            return
        if getattr(self, "_maintenance_running", False):
            messagebox.showinfo("Maintenance running", "Wait for Windows Update to finish before closing.")
            return
        if getattr(self.root, "_assignment_running", False) is True:
            messagebox.showinfo("Assignment in progress", "Wait for the assignment outcome before closing.")
            return
        runner = getattr(self, "_tests_runner", None)
        if runner and runner.is_busy():
            messagebox.showinfo("Tests running", "Finish the current hardware test before closing.")
            return
        if self._preserve_check_draft():
            self.root.destroy()

    def _set_update_check_status(self, status):
        self._update_check_status = status
        label = getattr(self, 'version_label', None)
        if label is not None:
            label.configure(text=getattr(self, '_version_text', '') + "\n" + status)

    def check_for_updates(self, silent: bool = False):
        if (getattr(self, "_operator_locked", False)
                or getattr(self, '_update_ui_closed', False)):
            return
        if getattr(self, '_update_check_running', False):
            self._update_check_notify = self._update_check_notify or not silent
            return
        self._update_check_running = True
        self._update_check_notify = not silent
        self._set_update_check_status('Checking for app updates…')
        results = queue.Queue()
        current_version = self.update_service.current_version

        def worker():
            from services.app_helper import run_helper, HelperError
            from services.update_integrity import CHECK_FAILURES
            from services.update_result import decode_update_result
            try:
                result = run_helper("updates", timeout=60)
                data = decode_update_result(json.dumps(result), current_version)
                results.put((data, None))
            except Exception as err:
                from services.runtime import log_diagnostic
                log_diagnostic('update.check_failed', error=err, stage='helper')
                detail = (str(err) if isinstance(err, HelperError)
                          and str(err) in CHECK_FAILURES.values()
                          else CHECK_FAILURES['unavailable'])
                results.put((None, detail))

        def poll():
            self._update_check_after_id = None
            if getattr(self, '_update_ui_closed', False):
                return
            try:
                data, error = results.get_nowait()
            except queue.Empty:
                self._update_check_after_id = self.root.after(100, poll)
                return
            self._update_check_running = False
            notify = self._update_check_notify
            if error:
                self._set_update_check_status('Update check failed — use Tools to retry.')
                if notify and not getattr(self, '_operator_locked', False):
                    messagebox.showerror('Update Check Failed', error)
                return
            if data is None:
                self._set_update_check_status('App is up to date')
                if notify and not getattr(self, '_operator_locked', False):
                    messagebox.showinfo('No Updates',
                        'The update service confirmed no newer release for this version.')
                return
            manifest = UpdateManifest(**{
                name: data[name] for name in UpdateManifest.__dataclass_fields__
                if name in data
            })
            self._set_update_check_status('Update available: ' + manifest.version)
            if getattr(self, '_operator_locked', False):
                return
            automatic = self.update_service.can_auto_install(manifest)
            action = ("Download, verify and install it now?" if automatic else
                      "Open the trusted release page? Automatic installation "
                      "requires release hashes and a configured trusted publisher.")
            message = (f"Release {manifest.version} is available.\n"
                       f"Running version: {current_version}.\n\n"
                       f"{(manifest.notes or 'No release notes provided.').strip()}\n\n{action}")
            if messagebox.askyesno("Update Available", message):
                self._begin_update(manifest)

        threading.Thread(target=worker, daemon=True).start()
        self._update_check_after_id = self.root.after(100, poll)

    def _update_busy(self):
        runner = getattr(self, "_tests_runner", None)
        return bool(getattr(self, "_update_preparing", False)
            or getattr(self, "_search_inflight", False)
            or getattr(self, "_note_save_inflight", 0)
            or getattr(self, "_maintenance_running", False)
            or getattr(self.root, "_assignment_running", False) is True
            or (runner and runner.is_busy())
            or any(isinstance(child, tk.Toplevel) for child in self.root.winfo_children()))

    def _show_update_outcome(self):
        if getattr(self, "_operator_locked", False):
            return
        outcome = self.update_service.last_outcome()
        if outcome:
            messagebox.showinfo("App update outcome",
                "Update result: {}. Running version: {}.\n"
                "Local settings and drafts remain in place. If recovery is needed, "
                "use Tools > Restore previous app version; update journals and the "
                "retained backup are beside the application.".format(
                    outcome.replace("_", " "), self.update_service.current_version))

    def restore_previous_update(self):
        if not self._require_operator("maintenance"):
            return
        if messagebox.askyesno("Restore previous version", "Restore the retained previous app version and restart? Local configuration and drafts will stay in place."):
            self._begin_update(None, restore=True)

    def _begin_update(self, manifest, restore=False):
        if self._update_busy():
            messagebox.showinfo("Bench busy", "Finish current work and save/close dialogs before updating.")
            return
        if not self._preserve_check_draft():
            return
        self._update_preparing = True
        self.root._update_preparing = True
        cancel = threading.Event()
        replies = queue.Queue()
        dialog = tk.Toplevel(self.root)
        dialog.title("Preparing app update")
        dialog.transient(self.root)
        status = tk.StringVar(value="Preparing verified update…")
        ttk.Label(dialog, textvariable=status, padding=18, wraplength=440).pack()
        def cancel_request():
            cancel.set()
            status.set("Cancelling… The installed app will be retained.")
        ttk.Button(dialog, text="Cancel", command=cancel_request).pack(pady=12)
        dialog.protocol("WM_DELETE_WINDOW", cancel_request)
        def progress(text):
            replies.put(("progress", text))
        def worker():
            try:
                if restore:
                    result = self.update_service.restore_previous(progress, cancel)
                else:
                    result = self.update_service.launch_update(manifest, progress, cancel)
                replies.put(("done", result))
            except Exception as exc:
                replies.put(("error", str(exc)))
        def poll():
            if not dialog.winfo_exists():
                cancel.set()
                self.update_service.cancel_prepared()
                return
            final = None
            try:
                while True:
                    kind, value = replies.get_nowait()
                    if kind == "progress":
                        status.set(value)
                    else:
                        final = kind, value
                        break
            except queue.Empty:
                pass
            if final is None:
                dialog.after(60, poll)
                return
            self._update_preparing = False
            self.root._update_preparing = False
            dialog.destroy()
            kind, value = final
            if cancel.is_set():
                self.update_service.cancel_prepared()
                return
            if kind == "error":
                self.update_service.cancel_prepared()
                messagebox.showerror("Update not installed", value)
            elif value is True:
                if not self._shutdown_for_update():
                    self.update_service.cancel_prepared()
            # False means a manual release page opened; the app remains running.
        threading.Thread(target=worker, daemon=True).start()
        dialog.after(60, poll)

    def _shutdown_for_update(self):
        runner = getattr(self, "_tests_runner", None)
        if ((runner and runner.is_busy())
                or getattr(self.root, "_assignment_running", False) is True):
            messagebox.showinfo("Bench busy", "Finish the current test or assignment before updating.")
            return
        if not self._preserve_check_draft():
            return
        log_event("Shutting down to install update.")
        try:
            self.root.quit()
        except tk.TclError:
            pass
        self.root.destroy()
        return True

    def animate_dots(self, count):
        if self.canvas.find_withtag("search_status"):
            dots = "." * (count % 4)
            text = f"Searching{dots}"
            self.canvas.itemconfigure("search_status", text=text)
            self._search_after_id = self.root.after(500, lambda: self.animate_dots(count + 1))

    def _render_laptop_specs(self):
        if (not self._showing_default_specs or self._search_inflight
                or self._lookup_valid):
            return
        specs = self._visible_specs
        if not specs or not fresh(specs):
            self.refresh_device()
            return
        if self._check_session.key is None:
            try:
                serial = specs.get("Serial Number")
                draft, _ = self._check_session.candidate(0, serial, self.test_results)
                results = self._check_session.activate(0, "", serial,
                                                       self.test_results, draft)
                self.test_results.clear()
                self.test_results.update(results)
                if draft:
                    self._set_order_context("Local bench draft restored for device " + str(serial))
            except (OSError, ValueError) as exc:
                messagebox.showerror("Bench draft not loaded", str(exc))
        placeholder_details = {
            "Model": "Unknown",
            "CPU": "Unknown",
            "SSD": "Unknown",
            "RAM": "Unknown",
            "Resolution": "Unknown",
            "Windows": "Unknown",
            "Battery": "Unknown",
            "Battery 2": "Unknown",
        }
        placeholder_tests = {
            "keyboard": "Not Run",
            "speaker": "Not Run",
            "microphone": "Not Run",
            "display": "Not Run",
            "webcam": "Not Run",
            "usb": "Not Run",
            "wifi": "Not Run",
            "activation": "Not Run",
        }
        if self.mdm_status is None:
            self.mdm_status = check_mdm_lock_status()
        mdm_status = self.mdm_status
        def draw():
            if not self._showing_default_specs or self._search_inflight:
                return
            self._update_results_footer(
                *build_results_footer(specs, placeholder_details, mdm_status)
            )
            self._update_order_notes_footer("")
            render_results(
                self.canvas,
                "00000",
                "Laptop Spec",
                specs.get("Serial Number", "Unknown"),
                specs,
                placeholder_details,
                placeholder_tests,
                mdm_status,
                None,
                False,
                "",
                self.root,
            )

        self.root.after(100, draw)
        if not self._mdm_refresh_started:
            self._refresh_mdm_status_async()

    def _apply_mdm_status_to_footer_only(self):
        if not self.mdm_status:
            return

        mdm_text, mdm_color = mdm_summary(self.mdm_status)

        self.mdm_footer.config(text=mdm_text, fg=mdm_color)

    def _refresh_mdm_status_async(self):
        if self._mdm_refresh_started:
            return
        self._mdm_refresh_started = True

        def worker():
            try:
                from services.app_helper import run_helper
                status = run_helper("mdm", timeout=30)
            except Exception as err:
                log_event(f"MDM refresh process failed: {err}")
                status = mdm_evidence("error", "Background local evidence refresh failed or timed out.")

            def apply_status():
                if (not getattr(self, "_operator_locked", False)
                        and self._showing_default_specs and not self._search_inflight):
                    self.mdm_status = qualified(status)
                    self._apply_mdm_status_to_footer_only()

            self.root.after(0, apply_status)

        threading.Thread(target=worker, daemon=True).start()

    def update_test_result_labels(self):
        for result_key, symbol in self.test_results.items():
            label_widget = self.test_labels.get(f"{result_key}_label")
            if label_widget:
                try:
                    if label_widget.winfo_exists():
                        display = badge_text(self.test_results, result_key)
                        label_widget.config(text=display)
                    else:
                        self.test_labels[f"{result_key}_label"] = None
                except tk.TclError:
                    self.test_labels[f"{result_key}_label"] = None

    def open_test_panel(self):
        if not self._require_operator("test"):
            return
        log_event("Opening test panel.")
        if self.tests_window and tk.Toplevel.winfo_exists(self.tests_window):
            log_event("Test panel already open. Bringing it to focus.")
            self.tests_window.lift()
            self.tests_window.focus_force()
            return

        test_keys = ["keyboard", "speaker", "microphone", "display", "webcam", "usb", "wifi"]
        for key in test_keys:
            if key not in self.test_results:
                self.test_results[key] = "Not Run"


        tests_window_instance = TestsWindow(
            self.root, self.test_results, self.test_labels,
            operator=self.current_user.username if self.current_user else None,
            authorization_check=self._require_operator,
            context_label=(f"Order: {self._check_session.order_number or 'bench checks'} | "
                           f"Device: {self._check_session.key[1]}"
                           if self._check_session.key else "Bench checks: device not yet identified"),
        )
        self._tests_runner = tests_window_instance
        self.tests_window = tests_window_instance.tests_window

        def on_tests_window_close():
            tests_window_instance.on_close()
            if not tests_window_instance.tests_window.winfo_exists():
                self.tests_window = None

        self.tests_window.protocol("WM_DELETE_WINDOW", on_tests_window_close)

    def run_windows_update_script(self):
        if not self._require_operator("maintenance"):
            return
        if self._update_busy():
            messagebox.showinfo("Bench busy", "Finish current work and close dialogs before maintenance.")
            return
        if not messagebox.askyesno("Install Windows updates", "Check for and install Windows updates on this computer?\n\nWindows will request administrator approval for this action. No automatic restart is requested. Save other work first."):
            return
        self._maintenance_running = True
        def worker():
            try:
                self.update_status("Preparing and running Windows Update...")
                from services.maintenance import run_windows_updates
                run_windows_updates()
                self.root.after(0, lambda: messagebox.showinfo(
                    "Windows Update",
                    "Windows Update script has finished.\nCheck Windows Update history for details."
                ))
            except MaintenanceCancelled as err:
                self.root.after(0, lambda detail=str(err): messagebox.showinfo(
                    "Windows Update cancelled", detail))
            except MaintenanceError as err:
                self.root.after(0, lambda detail=str(err): messagebox.showerror(
                    "Windows Update", detail))
            except Exception:
                log_event("Windows Update failed unexpectedly; successful completion was not confirmed.")
                self.root.after(0, lambda: messagebox.showerror(
                    "Windows Update", "Windows Update could not complete. Retry or ask an administrator to check this machine."))
            finally:
                self._maintenance_running = False
                self.update_status("")

        threading.Thread(target=worker, daemon=True).start()

    def update_status(self, message):
        def apply():
            if hasattr(self, "status_label"):
                self.status_label.config(text=message)
            else:
                self.status_label = tk.Label(self.root, text=message, font=("Arial", 10, "italic"))
                self.status_label.pack(pady=5, fill="x")

        self.root.after(0, apply)
