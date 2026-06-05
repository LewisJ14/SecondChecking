# ui/tests.py
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox

from ttkbootstrap import ttk

from hardwaretests.display import run_display_test
from hardwaretests.speaker import run_speaker_test
from hardwaretests.usb import run_usb_test
from hardwaretests.webcam import run_webcam_test
from hardwaretests.wifi import run_wifi_test
from ui.keyboard_test import run_keyboard_test
from utils.helpers import check_activation_status, log_event
from utils.ui_scaling import center_window, center_window_to_content, get_work_area


class TestsWindow:
    def __init__(self, root, test_results, test_labels):
        self.root = root
        self.test_results = test_results
        self.test_labels = test_labels
        self.test_buttons = {}
        self.test_sequence = []
        self._running_all = False

        self.tests_window = tk.Toplevel(self.root)
        self.tests_window.title("Hardware Tests")
        self.tests_window.configure(bg="#f4f6fa")

        _, _, screen_width, screen_height = get_work_area(self.tests_window)
        width = min(620, max(520, int(screen_width * 0.36)))
        height = min(760, max(560, int(screen_height * 0.78)))
        center_window(self.tests_window, width, height, min_width=520, min_height=520)
        self.tests_window.minsize(min(520, width), min(520, height))
        self.tests_window.resizable(True, True)
        self.tests_window.protocol("WM_DELETE_WINDOW", self.on_close)

        self.main_frame = tk.Frame(self.tests_window, bg="#f4f6fa")
        self.main_frame.pack(fill="both", expand=True, padx=16, pady=16)

        self._build_header()

        list_shell = tk.Frame(self.main_frame, bg="#f4f6fa")
        list_shell.pack(fill="both", expand=True)
        list_shell.grid_columnconfigure(0, weight=1)
        list_shell.grid_rowconfigure(0, weight=1)

        self.tests_canvas = tk.Canvas(list_shell, bg="#f4f6fa", highlightthickness=0, bd=0)
        self.tests_canvas.grid(row=0, column=0, sticky="nsew")

        self.tests_scrollbar = ttk.Scrollbar(list_shell, orient="vertical", command=self.tests_canvas.yview)
        self.tests_scrollbar.grid(row=0, column=1, sticky="ns")
        self.tests_canvas.configure(yscrollcommand=self.tests_scrollbar.set)

        self.tests_container = tk.Frame(self.tests_canvas, bg="#f4f6fa")
        self.tests_window_id = self.tests_canvas.create_window((0, 0), window=self.tests_container, anchor="nw")
        self.tests_container.bind("<Configure>", self._sync_scroll_region)
        self.tests_canvas.bind("<Configure>", self._sync_canvas_width)

        self.add_test_row("Speaker Test", run_speaker_test, "speaker")
        self.add_status_row("Microphone (auto)", "microphone")
        self.add_test_row("Display Test", run_display_test, "display")
        self.add_test_row("Keyboard Test", run_keyboard_test, "keyboard")
        self.add_test_row("Webcam Test", run_webcam_test, "webcam")
        self.add_test_row("USB Test", run_usb_test, "usb")
        self.add_activation_row()
        self.add_section_header("Automatic Hardware Tests")
        self.add_auto_test_row("Wi-Fi Test", run_wifi_test, "wifi", "Checks Windows can see an available Wi-Fi adapter.")

        self._build_footer()
        self.tests_window.after(250, lambda: self.run_test_threaded(run_wifi_test, "wifi"))

    def _sync_scroll_region(self, event=None):
        self.tests_canvas.configure(scrollregion=self.tests_canvas.bbox("all"))

    def _sync_canvas_width(self, event):
        self.tests_canvas.itemconfigure(self.tests_window_id, width=event.width)

    def _build_header(self):
        header_card = tk.Frame(
            self.main_frame,
            bg="#1f2a37",
            padx=18,
            pady=16,
            highlightbackground="#1f2a37",
            highlightthickness=1,
        )
        header_card.pack(fill="x", pady=(0, 14))

        tk.Label(
            header_card,
            text="Hardware Tests",
            font=("Segoe UI", 16, "bold"),
            fg="white",
            bg="#1f2a37",
        ).pack(anchor="w")
        tk.Label(
            header_card,
            text="Run quick checks individually or complete the full validation pass.",
            font=("Segoe UI", 10),
            fg="#d0d5dd",
            bg="#1f2a37",
            justify="left",
            wraplength=500,
        ).pack(anchor="w", pady=(6, 0))

    def _build_footer(self):
        action_card = tk.Frame(
            self.main_frame,
            bg="#ffffff",
            padx=12,
            pady=12,
            highlightbackground="#d7dde8",
            highlightthickness=1,
        )
        action_card.pack(side="bottom", fill="x", pady=(14, 0))

        self.run_all_button = ttk.Button(
            action_card,
            text="Run All Tests",
            command=self.run_all_tests,
            style="primary.TButton",
        )
        self.run_all_button.pack(fill="x", ipady=6)

        self.status_label = tk.Label(
            action_card,
            text="Ready to run hardware checks.",
            font=("Segoe UI", 10, "italic"),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
        )
        self.status_label.pack(fill="x", pady=(10, 0))

    def _result_visuals(self, result):
        if result == "pass":
            return ("PASS", "#e7f6ec", "#1f7a4d")
        if result == "fail":
            return ("FAIL", "#fdeaea", "#b42318")
        return ("PENDING", "#eef2f6", "#475467")

    def _button_style_for_result(self, result):
        if result == "pass":
            return "success.TButton"
        if result == "fail":
            return "danger.TButton"
        return "secondary.TButton"

    def _apply_result_badge(self, label_widget, result):
        text, background, foreground = self._result_visuals(result)
        label_widget.config(text=text, bg=background, fg=foreground)

    def _create_row_card(self):
        row = tk.Frame(
            self.tests_container,
            bg="#ffffff",
            padx=12,
            pady=10,
            highlightbackground="#d7dde8",
            highlightthickness=1,
        )
        row.pack(fill="x", pady=(0, 10))
        row.grid_columnconfigure(0, minsize=160, weight=0)
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, minsize=88, weight=0)
        row.grid_columnconfigure(3, minsize=88, weight=0)
        return row

    def add_section_header(self, text):
        section = tk.Frame(self.tests_container, bg="#f4f6fa", pady=4)
        section.pack(fill="x", pady=(4, 8))
        tk.Label(
            section,
            text=text,
            font=("Segoe UI", 11, "bold"),
            fg="#1f2a37",
            bg="#f4f6fa",
            anchor="w",
        ).pack(fill="x")

    def run_test_threaded(self, test_func, key):
        threading.Thread(target=lambda: self._execute_test(test_func, key), daemon=True).start()

    def _execute_test(self, test_func, key):
        completion_event = threading.Event()

        def invoke_test():
            try:
                test_func(
                    self.root,
                    self.test_results,
                    self.test_labels,
                    self,
                    completion_event=completion_event,
                )
            except Exception as err:
                log_event(f"Error running {key} test: {err}")
                self.test_results[key] = "fail"
                completion_event.set()
                self.root.after(
                    0,
                    lambda: messagebox.showerror(
                        "Test Error",
                        f"An error occurred during the {key} test.",
                    ),
                )

        try:
            self.update_status(f"Running {key} test...")
            self.root.after(0, invoke_test)
        finally:
            completion_event.wait()
            self.update_icon(key)
            self.update_status("")

    def run_all_tests(self):
        if self._running_all or not self.test_sequence:
            return

        self._running_all = True
        self.run_all_button.config(state="disabled")
        self._set_test_buttons_state("disabled")

        def run_sequence():
            try:
                for key, test_func in self.test_sequence:
                    self._execute_test(test_func, key)
            finally:
                self.update_status("")
                self._set_test_buttons_state("normal")
                self.root.after(0, lambda: self.run_all_button.config(state="normal"))
                self._running_all = False

        threading.Thread(target=run_sequence, daemon=True).start()

    def _set_test_buttons_state(self, state):
        def apply():
            for btn in self.test_buttons.values():
                btn.config(state=state)

        self.root.after(0, apply)

    def update_icon(self, key):
        def apply():
            result = self.test_results.get(key)
            label_key = f"{key}_label"
            label_widget = self.test_labels.get(label_key)
            if label_widget:
                self._apply_result_badge(label_widget, result)

            btn = self.test_buttons.get(key)
            if btn:
                btn.config(style=self._button_style_for_result(result))

        self.root.after(0, apply)

    def on_close(self):
        self.tests_window.destroy()

    def get_result_icon(self, test):
        text, _, _ = self._result_visuals(self.test_results.get(test))
        return text

    def view_product_key(self):
        def show_product_key_dialog(key):
            dialog = tk.Toplevel(self.tests_window)
            dialog.title("Windows Product Key")
            dialog.resizable(False, False)
            dialog.transient(self.tests_window)
            dialog.grab_set()

            body = tk.Frame(dialog, bg="#ffffff", padx=16, pady=16)
            body.pack(fill="both", expand=True)

            tk.Label(
                body,
                text="OEM Key:",
                font=("Segoe UI", 10, "bold"),
                bg="#ffffff",
                fg="#101828",
                anchor="w",
            ).pack(fill="x")

            key_entry = ttk.Entry(body, font=("Segoe UI", 10), width=max(34, len(key) + 2))
            key_entry.pack(fill="x", pady=(6, 14))
            key_entry.insert(0, key)
            key_entry.configure(state="readonly")

            status_label = tk.Label(
                body,
                text="",
                font=("Segoe UI", 9),
                bg="#ffffff",
                fg="#1f7a4d",
                anchor="w",
            )
            status_label.pack(fill="x")

            button_row = tk.Frame(body, bg="#ffffff")
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

        def run():
            try:
                result = subprocess.run(
                    [
                        "powershell",
                        "-Command",
                        "(Get-WmiObject -query 'select * from SoftwareLicensingService').OA3xOriginalProductKey",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                key = result.stdout.strip()
                if not key:
                    raise Exception("No product key found.")
                self.root.after(
                    0,
                    lambda: show_product_key_dialog(key),
                )
            except Exception as err:
                log_event(f"Product key retrieval error: {err}")
                self.root.after(
                    0,
                    lambda: messagebox.showerror("Error", "Failed to retrieve product key."),
                )

        threading.Thread(target=run, daemon=True).start()

    def attempt_activation(self):
        def run():
            try:
                self.update_status("Attempting activation...")
                subprocess.run(
                    [
                        "cscript.exe",
                        "//Nologo",
                        "C:\\Windows\\System32\\slmgr.vbs",
                        "/ato",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.test_results["activation"] = "pass" if check_activation_status() else "fail"
                log_event(f"[DEBUG] Passing activation to UI: {self.test_results['activation']}")
                self.update_icon("activation")
                if self.test_results["activation"] == "pass":
                    self.root.after(
                        0,
                        lambda: [
                            messagebox.showinfo("Activation", "Windows activation succeeded."),
                            self.tests_window.lift(),
                            self.tests_window.focus_force(),
                        ],
                    )
                else:
                    self.root.after(
                        0,
                        lambda: [
                            messagebox.showerror("Activation", "Windows activation failed."),
                            self.tests_window.lift(),
                            self.tests_window.focus_force(),
                        ],
                    )
            except Exception as err:
                log_event(f"Activation error: {err}")
                self.test_results["activation"] = "fail"
                self.update_icon("activation")
                self.root.after(
                    0,
                    lambda: [
                        messagebox.showerror("Activation", "An error occurred during activation."),
                        self.tests_window.lift(),
                        self.tests_window.focus_force(),
                    ],
                )
            finally:
                self.update_status("")

        threading.Thread(target=run, daemon=True).start()

    def update_status(self, message):
        self.root.after(
            0,
            lambda: self.status_label.config(text=message or "Ready to run hardware checks."),
        )

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
            text="Windows license check and reactivation",
            font=("Segoe UI", 10),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        description.grid(row=0, column=1, sticky="ew", padx=(12, 12))

        lbl = tk.Label(
            row,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
            bd=0,
        )
        lbl.grid(row=0, column=2, sticky="e")
        self._apply_result_badge(lbl, status)

        self.test_labels["activation_label"] = lbl
        self.test_buttons["activation"] = btn

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
            text=description_text,
            font=("Segoe UI", 10),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        description.grid(row=0, column=1, sticky="ew", padx=(12, 12))

        override_btn = ttk.Button(
            row,
            text="Override",
            command=lambda: self.show_override_dialog(key, label),
            style="warning.TButton",
            width=10,
        )
        override_btn.grid(row=0, column=2, sticky="e", padx=(0, 10))

        lbl = tk.Label(
            row,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
            bd=0,
        )
        lbl.grid(row=0, column=3, sticky="e")
        self._apply_result_badge(lbl, result)

        self.test_labels[f"{key}_label"] = lbl
        self.test_buttons[key] = btn
        self.test_sequence.append((key, test_func))

    def show_override_dialog(self, key, label):
        dialog = tk.Toplevel(self.tests_window)
        dialog.title(f"Override {label}")
        dialog.resizable(False, False)
        dialog.transient(self.tests_window)
        dialog.grab_set()

        body = tk.Frame(dialog, bg="#ffffff", padx=14, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text=f"Manually set {label} result:",
            font=("Segoe UI", 10, "bold"),
            bg="#ffffff",
        ).pack(anchor="w", pady=(0, 10))

        def set_result(value):
            self.test_results[key] = value
            log_event(f"{label} manually overridden to {value}.")
            self.update_icon(key)
            dialog.destroy()

        ttk.Button(body, text="Pass", command=lambda: set_result("pass"), style="success.TButton").pack(fill="x", pady=4)
        ttk.Button(body, text="Fail", command=lambda: set_result("fail"), style="danger.TButton").pack(fill="x", pady=4)
        ttk.Button(body, text="Not Run", command=lambda: set_result("Not Run"), style="secondary.TButton").pack(fill="x", pady=4)

        center_window_to_content(dialog, min_width=320, min_height=180)

    def show_activation_dialog(self):
        dialog = tk.Toplevel(self.tests_window)
        dialog.title("Windows Activation")

        dialog.resizable(True, True)
        dialog.transient(self.tests_window)
        dialog.grab_set()

        body = tk.Frame(dialog, bg="#ffffff", padx=14, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Choose an activation option:",
            font=("Segoe UI", 10, "bold"),
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
            text="Interactive check",
            font=("Segoe UI", 10),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        description.grid(row=0, column=1, sticky="ew", padx=(12, 12))

        lbl = tk.Label(
            row,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
            bd=0,
        )
        lbl.grid(row=0, column=2, sticky="e")
        self._apply_result_badge(lbl, result)

        self.test_labels[f"{key}_label"] = lbl
        self.test_buttons[key] = btn
        self.test_sequence.append((key, test_func))

    def add_status_row(self, label, key):
        row = self._create_row_card()

        tk.Label(
            row,
            text=label,
            font=("Segoe UI", 10, "bold"),
            fg="#101828",
            bg="#ffffff",
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        description = tk.Label(
            row,
            text="Auto-detected",
            font=("Segoe UI", 10),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        description.grid(row=0, column=1, sticky="ew", padx=(12, 12))

        lbl = tk.Label(
            row,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
            bd=0,
        )
        lbl.grid(row=0, column=2, sticky="e")
        self._apply_result_badge(lbl, self.test_results.get(key))

        self.test_labels[f"{key}_label"] = lbl
