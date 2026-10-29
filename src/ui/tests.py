# ui/tests.py
import time
from services.runtime import log_diagnostic
from collections import Counter
from copy import deepcopy
import threading
import tkinter as tk
from ui.scrolling import bind_scrolling
from tkinter import messagebox

from ttkbootstrap import ttk

from hardwaretests.display import run_display_test
from hardwaretests.speaker import run_speaker_test, run_microphone_test
from hardwaretests.usb import run_usb_test
from hardwaretests.webcam import run_webcam_test
from hardwaretests.wifi import run_wifi_test
from ui.keyboard_test import run_keyboard_test
from services.check_results import (badge_text, start_measurement,
                                    current_override, record_override, normalise)
from utils.helpers import log_event
from utils.ui_scaling import center_window, center_window_to_content, get_work_area


class TestsWindow:
    def __init__(self, root, test_results, test_labels, operator=None,
                 context_label=None, authorization_check=None):
        self.root = root
        self.test_results = test_results
        self.test_labels = test_labels
        self.operator = operator
        self.context_label = context_label
        self._authorization_check = authorization_check
        self.test_buttons = {}
        self.test_sequence = []
        self._running_all = False
        self._pending_tests = 0
        self._wifi_after_id = None
        self._active_run = None
        self._runner_after_id = None
        self._closed = False
        self._aux_jobs = []

        self.tests_window = tk.Toplevel(self.root)
        self.tests_window.title("Hardware Tests")
        self.tests_window.configure(bg="#f1f4f8")

        _, _, screen_width, screen_height = get_work_area(self.tests_window)
        scale = float(self.tests_window.tk.call('tk', 'scaling')) / (96 / 72)
        width = min(screen_width - 40, round(1000 * scale))
        height = min(screen_height - 80, round(1000 * scale))
        center_window(self.tests_window, width, height, min_width=520, min_height=520)
        self.tests_window.minsize(min(520, width), min(520, height))
        self.tests_window.resizable(True, True)
        self.tests_window.protocol("WM_DELETE_WINDOW", self.on_close)
        self.tests_window.bind("<Destroy>", self._destroyed, add="+")

        self.main_frame = tk.Frame(self.tests_window, autostyle=False, bg="#f1f4f8")
        self.main_frame.pack(fill="both", expand=True, padx=16, pady=16)

        self._build_header()

        list_shell = tk.Frame(self.main_frame, autostyle=False, bg="#f1f4f8")
        self.list_shell = list_shell
        list_shell.pack(fill="both", expand=True)
        list_shell.grid_columnconfigure(0, weight=1)
        list_shell.grid_rowconfigure(0, weight=1)

        self.tests_canvas = tk.Canvas(list_shell, autostyle=False, bg="#f1f4f8", highlightthickness=0, bd=0)
        self.tests_canvas.grid(row=0, column=0, sticky="nsew")

        self.tests_scrollbar = ttk.Scrollbar(list_shell, orient="vertical", command=self.tests_canvas.yview)
        self.tests_scrollbar.grid(row=0, column=1, sticky="ns")
        self.tests_canvas.configure(yscrollcommand=self.tests_scrollbar.set)

        self.tests_container = tk.Frame(self.tests_canvas, autostyle=False, bg="#f1f4f8")
        self.tests_window_id = self.tests_canvas.create_window((0, 0), window=self.tests_container, anchor="nw")
        bind_scrolling(self.tests_canvas, self.tests_container)
        self.tests_container.bind("<Configure>", self._sync_scroll_region)
        self.tests_canvas.bind("<Configure>", self._sync_canvas_width)

        self.add_test_row("Speaker Test", run_speaker_test, "speaker")
        self.add_test_row("Microphone Test", run_microphone_test, "microphone")
        self.add_test_row("Display Test", run_display_test, "display")
        self.add_test_row("Keyboard Test", run_keyboard_test, "keyboard")
        self.add_test_row("Webcam Test", run_webcam_test, "webcam")
        self.add_test_row("USB Test", run_usb_test, "usb")
        self.add_activation_row()
        self.add_section_header("Automatic Hardware Tests")
        self.add_auto_test_row("Wi-Fi adapter", run_wifi_test, "wifi", "Detects an enabled WLAN adapter only. Connection, signal and speed are not tested.")

        self._build_footer()
        if not current_override(self.test_results, "wifi"):
            self._wifi_after_id = self.tests_window.after(
                250, lambda: self.run_test_threaded(run_wifi_test, "wifi"))

    def _sync_scroll_region(self, event=None):
        self.tests_canvas.configure(scrollregion=self.tests_canvas.bbox("all"))

    def _sync_canvas_width(self, event):
        self.tests_canvas.itemconfigure(self.tests_window_id, width=event.width)

    def _build_header(self):
        header_card = tk.Frame(
            self.main_frame,
            autostyle=False, bg="#1f7f52",
            padx=18,
            pady=16,
            highlightbackground="#1f7f52",
            highlightthickness=1,
        )
        header_card.pack(fill="x", pady=(0, 14))

        self.context_header = tk.Label(
            header_card,
            autostyle=False, text="Hardware Tests",
            font=("Segoe UI", 16, "bold"),
            fg="white",
            bg="#1f7f52",
        )
        self.context_header.pack(anchor="w")
        self.context_description = tk.Label(
            header_card,
            autostyle=False, text=self.context_label or "Run quick checks individually or complete the full validation pass.",
            font=("Arial", 10),
            fg="#e1f2e8",
            bg="#1f7f52",
            justify="left",
            wraplength=500,
        )
        self.context_description.pack(anchor="w", pady=(6, 0))
        header_card.bind('<Configure>', lambda event:
                         self.context_description.config(
                             wraplength=max(100, event.width - 40)))

    def _build_footer(self):
        action_card = tk.Frame(
            self.main_frame,
            autostyle=False, bg="#ffffff",
            padx=12,
            pady=12,
            highlightbackground="#dce6f2",
            highlightthickness=1,
        )
        action_card.pack(side="bottom", fill="x", pady=(14, 0), before=self.list_shell)
        action_card.columnconfigure((0, 1), weight=1, uniform='actions')

        self.run_all_button = ttk.Button(
            action_card,
            text="Run All Tests",
            command=self.run_all_tests,
            style="primary.TButton",
        )
        self.run_all_button.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        self.cancel_button = ttk.Button(
            action_card, text="Stop tests", style='secondary.Outline.TButton',
            command=self.cancel_tests, state="disabled")
        self.cancel_button.grid(row=0, column=1, sticky='ew', padx=(6, 0))

        self.status_label = tk.Label(
            action_card,
            autostyle=False, text=("No checks recorded in this session yet. Run a check to begin."
                  if all(normalise(self.test_results.get(key)) == "n/a"
                         for key in ("keyboard", "speaker", "microphone", "display",
                                     "webcam", "usb", "wifi", "activation"))
                  else "Existing results in this session. Assign the device to save its report."),
            font=("Arial", 10),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
        )
        self.status_label.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        self.status_label.bind('<Configure>', lambda event:
                               self.status_label.config(
                                   wraplength=max(100, event.width - 4)))
        from ui.bug_reports import open_report
        ttk.Button(action_card, text='Upload bug report…',
                   command=lambda: open_report(self.tests_window)).grid(
                       row=2, column=0, columnspan=2, sticky='ew', pady=(8, 0))

    def _result_visuals(self, result):
        if result == "pass":
            return ("PASS", "#e7f6ec", "#1f7a4d")
        if result == "fail":
            return ("FAIL", "#fdeaea", "#b42318")
        if result in {"cancelled", "unavailable", "error"}:
            return (result.upper(), "#fff4d6", "#854d0e")
        return ("PENDING", "#eef2f6", "#475467")

    def _button_style_for_result(self, result):
        if result == "pass":
            return "success.Outline.TButton"
        if result == "fail":
            return "danger.Outline.TButton"
        return "primary.Outline.TButton"

    def _apply_result_badge(self, label_widget, result):
        text, background, foreground = self._result_visuals(result)
        label_widget.config(text=text, bg=background, fg=foreground)

    def _create_row_card(self):
        row = tk.Frame(
            self.tests_container,
            autostyle=False, bg="#ffffff",
            padx=12,
            pady=10,
            highlightbackground="#dce6f2",
            highlightthickness=1,
        )
        row.pack(fill="x", pady=(0, 10))
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=0)
        def wrap(event):
            width = self.tests_canvas.winfo_width()
            if width <= 1:
                return
            for label in row.winfo_children():
                if isinstance(label, tk.Label) and label.grid_info().get('row') in (1, 2):
                    label.config(wraplength=max(100, width - 32))
        row.bind('<Configure>', wrap)
        return row

    def add_section_header(self, text):
        section = tk.Frame(self.tests_container, autostyle=False, bg="#f1f4f8", pady=4)
        section.pack(fill="x", pady=(4, 8))
        tk.Label(
            section,
            autostyle=False, text=text,
            font=("Arial", 11, "bold"),
            fg="#1f7f52",
            bg="#f1f4f8",
            anchor="w",
        ).pack(fill="x")

    def _cancel_auto_wifi(self):
        if self._wifi_after_id:
            self.tests_window.after_cancel(self._wifi_after_id)
            self._wifi_after_id = None

    def run_test_threaded(self, test_func, key):
        if self.is_busy() or self._closed:
            return
        self._start_queue([(key, test_func)], False)

    def is_busy(self):
        return (self._running_all or self._pending_tests > 0
                or self._runner_after_id is not None)

    def _start_queue(self, sequence, all_tests):
        authorize = getattr(self, "_authorization_check", None)
        if authorize and not authorize("test"):
            return
        self._cancel_auto_wifi()
        self._running_all = all_tests
        self._queue = list(sequence)
        self._attempted = []
        self._total = len(sequence)
        self._stopped = False
        self.run_all_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self._set_test_buttons_state("disabled")
        self._advance()

    def _advance(self):
        self._runner_after_id = None
        if self._closed:
            return
        authorize = getattr(self, "_authorization_check", None)
        if authorize and not authorize("test"):
            self._stopped = True
            self._finish_sequence()
            return
        if self._stopped or not self._queue:
            self._finish_sequence()
            return
        key, test_func = self._queue.pop(0)
        self._pending_tests = 1
        self._attempted.append(key)
        run = TestRun(self, key)
        log_diagnostic('test.started', kind=key)
        self._active_run = run
        start_measurement(run.results, key)
        self.update_status("Running {} ({}/{}) — Cancel stops the remaining checks."
                           .format(key, len(self._attempted), self._total))
        try:
            handle = test_func(self.root, run.results, {}, run,
                               completion_event=run.done)
            if handle is not None and hasattr(handle, 'cancel'):
                run.register_cancel(handle.cancel)
        except Exception as exc:
            log_diagnostic('test.start_failed', error=exc, kind=key, stage='launch')
            run.results[key] = 'error'
            run.done.set()
        self._poll_run()

    def _poll_run(self):
        self._runner_after_id = None
        run = self._active_run
        if self._closed or run is None:
            return
        if not run.done.is_set() and time.monotonic() > run.deadline:
            log_event('Hardware test {} exceeded its five-minute limit.'
                      .format(run.key))
            run.stop('error')
            self._stopped = True
        if not run.done.is_set():
            self._runner_after_id = self.root.after(40, self._poll_run)
            return
        if (normalise(run.results.get(run.key)) == 'cancelled' or
                (run.key == 'speaker' and run.results.get('_combined_microphone_attempted')
                 and normalise(run.results.get('microphone')) == 'cancelled')):
            self._stopped = True
        self._commit_run(run)
        self._active_run = None
        self._pending_tests = 0
        self._restore_focus()
        self._runner_after_id = self.root.after(0, self._advance)

    def _commit_run(self, run):
        if run.committed:
            return
        run.committed = True
        run.active = False
        keys = [run.key]
        if run.key == 'speaker' and run.results.get('_combined_microphone_attempted'):
            keys.append('microphone')
            if 'microphone' not in self._attempted:
                self._attempted.append('microphone')
            if not any(key == 'microphone' for key, _ in self._queue):
                self._total += 1
            self._queue = [(key, function) for key, function in self._queue
                           if key != 'microphone']
        for key in keys:
            self.test_results[key] = normalise(run.results.get(key))
            log_diagnostic('test.finished', kind=key, result=self.test_results[key])
            for name in ('_overrides', '_coverage'):
                values = self.test_results.setdefault(name, {})
                if key in run.results.get(name, {}):
                    values[key] = deepcopy(run.results[name][key])
                else:
                    values.pop(key, None)
            unknown = self.test_results.get('_history_unknown', [])
            self.test_results['_history_unknown'] = [k for k in unknown if k != key]
            self.update_icon(key)
        self.test_results['_provenance_unknown'] = bool(
            self.test_results['_history_unknown'])

    def cancel_tests(self):
        if not self.is_busy():
            return
        self._stopped = True
        if self._active_run:
            self._active_run.stop('cancelled')
        if self._runner_after_id:
            self.root.after_cancel(self._runner_after_id)
            self._runner_after_id = None
        if self._active_run:
            self._poll_run()
        else:
            self._finish_sequence()

    def _finish_sequence(self):
        self._pending_tests = 0
        self._running_all = False
        self.cancel_button.config(state='disabled')
        self.run_all_button.config(state='normal')
        self._set_test_buttons_state('normal')
        counts = Counter(normalise(self.test_results.get(k)) for k in self._attempted)
        summary = ', '.join('{} {}'.format(n, state) for state, n in sorted(counts.items()))
        skipped = self._total - len(self._attempted)
        self.update_status('{}: {}. {} not started (previous results retained). '
                           'Results are local; assign the device to save its report.'
                           .format('Stopped' if self._stopped else 'Completed',
                                   summary or 'no checks', skipped))
        self._restore_focus()

    def _restore_focus(self):
        if not self._closed and self.tests_window.winfo_exists():
            self.tests_window.lift()
            self.tests_window.focus_set()

    def run_all_tests(self):
        if self.is_busy() or self._closed or not self.test_sequence:
            return
        self._start_queue(self.test_sequence, True)

    def _set_test_buttons_state(self, state):
        def apply():
            for btn in self.test_buttons.values():
                if btn.winfo_exists():
                    btn.config(state=state)

        apply()

    def update_icon(self, key):
        def apply():
            result = self.test_results.get(key)
            label_key = f"{key}_label"
            label_widget = self.test_labels.get(label_key)
            if label_widget and label_widget.winfo_exists():
                self._apply_result_badge(label_widget, result)
                label_widget.config(text=badge_text(self.test_results, key),
                                    wraplength=130, justify="right")

            btn = self.test_buttons.get(key)
            if btn and btn.winfo_exists():
                btn.config(style=self._button_style_for_result(result))
            changed = getattr(self.root, "_check_results_changed", None)
            if callable(changed):
                changed()

        apply()

    def _destroyed(self, event):
        if event.widget == self.tests_window and not self._closed:
            self.on_close()

    def on_close(self):
        if self._closed:
            return
        self._closed = True
        self._stopped = True
        if self._active_run:
            self._active_run.stop('cancelled')
            self._commit_run(self._active_run)
            self._active_run = None
        self._cancel_auto_wifi()
        if self._runner_after_id:
            self.root.after_cancel(self._runner_after_id)
            self._runner_after_id = None
        for job in self._aux_jobs:
            job.cancel()
        self._aux_jobs.clear()
        self._pending_tests = 0
        self._running_all = False
        if self.tests_window.winfo_exists():
            self.tests_window.destroy()

    def get_result_icon(self, test):
        return badge_text(self.test_results, test)

    def view_product_key(self):
        def show_product_key_dialog(key):
            dialog = tk.Toplevel(self.tests_window)
            dialog.title("Windows Product Key")
            dialog.resizable(False, False)
            dialog.transient(self.tests_window)
            dialog.grab_set()

            body = tk.Frame(dialog, autostyle=False, bg="#ffffff", padx=16, pady=16)
            body.pack(fill="both", expand=True)

            tk.Label(
                body,
                autostyle=False, text="OEM Key:",
                font=("Arial", 10, "bold"),
                bg="#ffffff",
                fg="#101828",
                anchor="w",
            ).pack(fill="x")

            key_entry = ttk.Entry(body, font=("Arial", 10), width=max(34, len(key) + 2))
            key_entry.pack(fill="x", pady=(6, 14))
            key_entry.insert(0, key)
            key_entry.configure(state="readonly")

            status_label = tk.Label(
                body,
                autostyle=False, text="",
                font=("Arial", 9),
                bg="#ffffff",
                fg="#1f7a4d",
                anchor="w",
            )
            status_label.pack(fill="x")

            button_row = tk.Frame(body, autostyle=False, bg="#ffffff")
            button_row.pack(fill="x", pady=(8, 0))

            def copy_key():
                self.root.clipboard_clear()
                self.root.clipboard_append(key)
                self.root.update()
                status_label.config(text="Copied to clipboard.")
                log_event("Windows product key copied to clipboard.")

            ttk.Button(button_row, text="OK", command=dialog.destroy, style="secondary.TButton").pack(
                side="right", padx=(8, 0)
            )
            copy_button = ttk.Button(
                button_row,
                text="Copy to Clipboard",
                command=copy_key,
                style="info.TButton",
            )
            copy_button.pack(side="right")

            center_window_to_content(dialog, min_width=430, min_height=170)
            copy_button.focus_set()

        from services.hardware_job import JobPoller

        def complete(reply):
            if self._closed:
                return
            if reply.get('state') == 'complete':
                show_product_key_dialog(reply['key'])
            else:
                messagebox.showerror('Product key', 'Failed to retrieve product key.')

        self._aux_jobs.append(JobPoller(self.tests_window, 'product-key',
                                        complete, timeout=15))

    def attempt_activation(self):
        from services.hardware_job import JobPoller
        if self.is_busy() or self._closed:
            return

        def activate(root, results, labels, context, completion_event=None):
            def complete(reply):
                results['activation'] = reply.get('state', 'error')
                completion_event.set()
            job = JobPoller(root, 'activation', complete, timeout=25)
            def cancel():
                job.cancel()
                results['activation'] = 'cancelled'
                completion_event.set()
            context.register_cancel(cancel)
        self.run_test_threaded(activate, 'activation')

    def update_status(self, message):
        if not self._closed and self.status_label.winfo_exists():
            self.status_label.config(text=message or 'Ready to run hardware checks.',
                                     justify='left')

    def add_activation_row(self):
        row = self._create_row_card()
        status = self.test_results.get("activation")

        btn = ttk.Button(
            row,
            text="Activation",
            command=self.show_activation_dialog,
            style=self._button_style_for_result(status),
            width=16,
        )
        btn.grid(row=0, column=0, sticky="w")

        description = tk.Label(
            row,
            autostyle=False, text="Windows license check and reactivation",
            font=("Arial", 10),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        description.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        lbl = tk.Label(
            row,
            font=("Arial", 9, "bold"),
            padx=10,
            pady=4,
            bd=0,
        )
        lbl.grid(row=0, column=1, sticky="e")
        self._apply_result_badge(lbl, status)

        self.test_labels["activation_label"] = lbl
        self.test_buttons["activation"] = btn
        self.update_icon("activation")

    def add_auto_test_row(self, label, test_func, key, description_text):
        row = self._create_row_card()
        result = self.test_results.get(key)

        btn = ttk.Button(
            row,
            text=label,
            command=lambda: self.run_test_threaded(test_func, key),
            style=self._button_style_for_result(result),
            width=16,
        )
        btn.grid(row=0, column=0, sticky="w")

        description = tk.Label(
            row,
            autostyle=False, text=description_text,
            font=("Arial", 10),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        description.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        override_btn = ttk.Button(
            row,
            text="Override",
            command=lambda: self.show_override_dialog(key, label),
            style="warning.TButton",
            width=10,
        )
        override_btn.grid(row=1, column=0, sticky="w", pady=(6, 0))

        lbl = tk.Label(
            row,
            font=("Arial", 9, "bold"),
            padx=10,
            pady=4,
            bd=0,
        )
        lbl.grid(row=0, column=1, sticky="e")
        self._apply_result_badge(lbl, result)

        self.test_labels[f"{key}_label"] = lbl
        self.test_buttons[key] = btn
        self.test_sequence.append((key, test_func))
        self.update_icon(key)

    def show_override_dialog(self, key, label):
        from services.operator_session import allowed
        if not allowed("override"):
            messagebox.showinfo("Sign in required", "Sign in again before recording an override.")
            return
        if self.is_busy() or self._closed:
            return
        self._cancel_auto_wifi()
        dialog = tk.Toplevel(self.tests_window)
        dialog.title(f"Override {label}")
        dialog.resizable(False, False)
        dialog.transient(self.tests_window)
        dialog.grab_set()

        body = tk.Frame(dialog, autostyle=False, bg="#ffffff", padx=14, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            autostyle=False, text=f"Manually set {label} result (operator: {self.operator or 'not signed in'}).\nA reason is required:",
            font=("Arial", 10, "bold"),
            bg="#ffffff",
        ).pack(anchor="w", pady=(0, 10))

        reason_entry = ttk.Entry(body, width=52)
        reason_entry.pack(fill="x", pady=(0, 10))
        reason_entry.focus_set()

        def set_result(value):
            if not allowed("override"):
                messagebox.showinfo("Sign in required", "Sign in again before saving this override.")
                return
            if self.is_busy() or self._closed:
                return
            try:
                record_override(self.test_results, key, value,
                                self.operator, reason_entry.get())
            except ValueError as exc:
                messagebox.showerror("Override not saved", str(exc), parent=dialog)
                return
            log_event(f"{label} manually overridden to {value}.")
            self.update_icon(key)
            dialog.destroy()

        ttk.Button(body, text="Pass", command=lambda: set_result("pass"), style="success.TButton").pack(fill="x", pady=4)
        ttk.Button(body, text="Fail", command=lambda: set_result("fail"), style="danger.TButton").pack(fill="x", pady=4)
        ttk.Button(body, text="Not Run", command=lambda: set_result("n/a"), style="secondary.TButton").pack(fill="x", pady=4)
        ttk.Button(body, text="Cancel", command=dialog.destroy).pack(fill="x", pady=4)

        center_window_to_content(dialog, min_width=320, min_height=180)

    def show_activation_dialog(self):
        if self.is_busy() or self._closed:
            return
        dialog = tk.Toplevel(self.tests_window)
        dialog.title("Windows Activation")

        dialog.resizable(True, True)
        dialog.transient(self.tests_window)
        dialog.grab_set()

        body = tk.Frame(dialog, autostyle=False, bg="#ffffff", padx=14, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            autostyle=False, text="Choose an activation option:",
            font=("Arial", 10, "bold"),
            bg="#ffffff",
        ).pack(anchor="w", pady=(0, 10))

        ttk.Button(
            body,
            text="View Product Key",
            command=self.view_product_key,
            style="info.TButton",
        ).pack(fill="x", pady=4)

        ttk.Button(
            body,
            text="Reactivate (BIOS Key)",
            command=lambda: [self.attempt_activation(), dialog.destroy()],
            style="success.TButton",
        ).pack(fill="x", pady=4)
        center_window_to_content(dialog, min_width=340, min_height=180)

    def add_test_row(self, label, test_func, key):
        row = self._create_row_card()
        result = self.test_results.get(key)

        btn = ttk.Button(
            row,
            text=label,
            command=lambda: self.run_test_threaded(test_func, key),
            style=self._button_style_for_result(result),
            width=16,
        )
        btn.grid(row=0, column=0, sticky="w")

        description = tk.Label(
            row,
            autostyle=False, text="Interactive check",
            font=("Arial", 10),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        description.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        lbl = tk.Label(
            row,
            font=("Arial", 9, "bold"),
            padx=10,
            pady=4,
            bd=0,
        )
        lbl.grid(row=0, column=1, sticky="e")
        self._apply_result_badge(lbl, result)

        self.test_labels[f"{key}_label"] = lbl
        self.test_buttons[key] = btn
        self.test_sequence.append((key, test_func))
        self.update_icon(key)

    def add_status_row(self, label, key):
        row = self._create_row_card()

        tk.Label(
            row,
            autostyle=False, text=label,
            font=("Arial", 10, "bold"),
            fg="#101828",
            bg="#ffffff",
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        description = tk.Label(
            row,
            autostyle=False, text="Auto-detected",
            font=("Arial", 10),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        description.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        lbl = tk.Label(
            row,
            font=("Arial", 9, "bold"),
            padx=10,
            pady=4,
            bd=0,
        )
        lbl.grid(row=0, column=1, sticky="e")
        self._apply_result_badge(lbl, self.test_results.get(key))

        self.test_labels[f"{key}_label"] = lbl
        self.update_icon(key)


class TestRun:
    """Per-attempt staging prevents late callbacks changing a newer session."""

    def __init__(self, panel, key):
        self.panel, self.key = panel, key
        self.results = deepcopy(panel.test_results)
        self.results.pop('_combined_microphone_attempted', None)
        self.done = threading.Event()
        self.deadline = time.monotonic() + 300
        self.cancel_callback = None
        self.active = True
        self.committed = False

    def register_cancel(self, callback):
        if self.active:
            self.cancel_callback = callback

    def stop(self, result):
        if not self.active or self.done.is_set():
            return
        try:
            if self.cancel_callback:
                self.cancel_callback()
        except Exception as exc:
            log_event('Test cleanup failed: {}'.format(exc))
            result = 'error'
        self.results[self.key] = result
        from services.test_coverage import record_coverage
        evidence = self.results.get('_coverage', {}).get(self.key)
        if evidence is None:
            record_coverage(self.results, self.key,
                            'Attempt ended by the test runner; incomplete '
                            'coverage, not a measured hardware pass.',
                            {'runner_exit': result})
        else:
            evidence['details']['runner_exit'] = result
        self.done.set()

    def update_icon(self, key):
        # Commit once, after completion, on the Tk thread.
        pass

    def update_status(self, message):
        if self.active and message:
            self.panel.update_status(message)
