import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
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
    search_order_logic,
)
from utils.specs import reset_specs_cache
from ui.tests import TestsWindow
from update_service import UpdateManifest, UpdateService
from utils.helpers import (
    check_mdm_lock_status,
    get_live_battery_percent,
    is_battery_charging,
    log_event,
)


class AppController:
    def __init__(self, root: tk.Tk):
        reset_specs_cache()
        self.root = root
        self.current_user: Optional[AuthenticatedUser] = None
        self.test_results = {}
        self.test_labels = {}
        self.tests_window = None
        self.update_service = UpdateService()
        self.mdm_status = None
        self._mdm_refresh_started = False
        self._showing_default_specs = True

        width, height, x, y = self._compute_geometry()
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(800, 500)
        self.root.resizable(True, True)

        self.login_panel = LoginPanel(root, self._on_authenticated)

    def _on_authenticated(self, user: Optional[AuthenticatedUser]) -> None:
        if not user:
            log_event("Login cancelled without authentication.")
            self.root.destroy()
            sys.exit(0)

        self.current_user = user
        self._build_ui()

    def _build_ui(self) -> None:
        version_label = self.update_service.current_version
        title = f"Second Checking Tool - Version {version_label}"
        if self.current_user:
            title = f"{title} - {self.current_user.username}"
        self.root.title(title)

        width, height, x, y = self._compute_geometry()
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        default_font = ("Segoe UI", 11)
        self.root.option_add("*Font", default_font)

        style = tb.Style()
        style.theme_use("flatly")

        primary_bg = "#f5f6fa"
        self.root.configure(bg=primary_bg)
        style.configure("Header.TFrame", background="#e0e1e6")

        menubar = tk.Menu(self.root, bg=primary_bg, fg="#222")
        self.root.config(menu=menubar)
        tools_menu = tk.Menu(menubar, tearoff=0, bg=primary_bg, fg="#222")
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Check for App Updates", command=self.check_for_updates)
        tools_menu.add_command(label="Run Windows Updates", command=self.run_windows_update_script)

        header_frame = ttk.Frame(self.root, padding=(10, 10, 10, 10), style="Header.TFrame")
        header_frame.pack(fill="x")

        self.test_panel_button = ttk.Button(
            header_frame,
            text="Test Menu",
            command=self.open_test_panel,
            style="info.TButton",
        )
        self.test_panel_button.grid(row=0, column=0, padx=(0, 10), pady=0, ipady=4, sticky="w")

        self.order_entry = ttk.Entry(header_frame, width=32, font=("Segoe UI", 11))
        self.order_entry.grid(row=0, column=1, padx=(0, 5), pady=0, ipady=4, sticky="ew")
        self.order_entry.bind("<Return>", lambda event: self.run_search())

        self.search_button = ttk.Button(
            header_frame,
            text="Search",
            command=self.run_search,
            style="success.TButton",
        )
        self.search_button.grid(row=0, column=2, padx=(0, 0), pady=0, ipady=4, sticky="w")

        self.version_label = ttk.Label(
            header_frame,
            text=f"Version {self.update_service.current_version}",
            font=("Segoe UI", 9),
            foreground="#555",
        )
        self.version_label.grid(row=0, column=3, padx=(10, 0), pady=0, sticky="e")

        header_frame.grid_columnconfigure(0, weight=0)
        header_frame.grid_columnconfigure(1, weight=1)
        header_frame.grid_columnconfigure(2, weight=0)
        header_frame.grid_columnconfigure(3, weight=0)

        self.canvas = tk.Canvas(self.root, bg="#fff", highlightthickness=0)
        self.canvas.pack(expand=True, fill="both", padx=10, pady=10)
        self.canvas.configure(borderwidth=2, relief="groove")

        self.footer_frame = tk.Frame(
            self.root,
            bg="#ffffff",
            padx=12,
            pady=8,
            highlightbackground="#d7dde8",
            highlightthickness=1,
        )
        self.footer_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.footer_frame.grid_columnconfigure(0, weight=1)
        self.footer_frame.grid_columnconfigure(1, weight=0)

        self.spec_summary_footer = tk.Label(
            self.footer_frame,
            text="",
            font=("Segoe UI", 10, "bold"),
            fg="#1f7a4d",
            bg="#ffffff",
            anchor="w",
            justify="left",
        )
        self.spec_summary_footer.grid(row=0, column=0, sticky="ew")

        self.mdm_footer = tk.Label(
            self.footer_frame,
            text="",
            font=("Segoe UI", 10, "bold"),
            fg="#1f7a4d",
            bg="#ffffff",
            anchor="w",
            justify="left",
        )
        self.mdm_footer.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        self.autopilot_hash_footer = tk.Label(
            self.footer_frame,
            text="",
            font=("Segoe UI", 10, "bold"),
            fg="#475467",
            bg="#ffffff",
            anchor="w",
            justify="left",
        )
        self.autopilot_hash_footer.grid(row=2, column=0, sticky="ew", pady=(2, 0))

        self.battery_footer = tk.Label(
            self.footer_frame,
            text="",
            font=("Segoe UI", 10, "bold"),
            fg="#101828",
            bg="#ffffff",
            anchor="w",
            justify="left",
        )
        self.battery_footer.grid(row=3, column=0, sticky="ew", pady=(6, 0))

        self.battery_bar_canvas = tk.Canvas(
            self.footer_frame,
            height=22,
            bg="#ffffff",
            highlightthickness=0,
            bd=0,
        )
        self.battery_bar_canvas.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        self.order_notes_card = tk.Frame(
            self.footer_frame,
            bg="#f8fafc",
            highlightbackground="#d7dde8",
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        self.order_notes_card.grid(row=0, column=1, rowspan=4, sticky="ne", padx=(12, 0))

        self.order_notes_title = tk.Label(
            self.order_notes_card,
            text="Order Notes",
            font=("Segoe UI", 10, "bold"),
            fg="#101828",
            bg="#f8fafc",
            anchor="w",
            justify="left",
        )
        self.order_notes_title.pack(fill="x", anchor="w")

        self.order_notes_body = tk.Frame(self.order_notes_card, bg="#f8fafc")
        self.order_notes_body.pack(fill="both", expand=False, pady=(4, 0))

        self.order_notes_footer = tk.Text(
            self.order_notes_body,
            height=6,
            width=44,
            font=("Segoe UI", 10),
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
        self._render_laptop_specs()
        self.root.bind("<Configure>", self.on_resize)
        self.root.after(0, self._center_current_window)
        # Automatically check for updates once per launch (silent=no pop-up when up-to-date)
        self.check_for_updates(silent=True)

    def on_resize(self, event):
        pass

    def _compute_geometry(self):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(int(screen_width * 0.85), 1400)
        height = min(int(screen_height * 0.85), 900)
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        return width, height, x, y

    def _center_current_window(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _update_results_footer(
        self,
        summary_text: str,
        summary_color: str,
        mdm_text: str,
        mdm_color: str,
        battery_lines,
    ) -> None:
        log_event(
            "Updating results footer: "
            f"summary='{summary_text}', mdm='{mdm_text}', battery_lines={battery_lines}"
        )
        self.spec_summary_footer.config(text=summary_text, fg=summary_color)
        self.mdm_footer.config(text=mdm_text, fg=mdm_color)
        first_battery_line = battery_lines[0] if battery_lines else "Battery: Unknown"
        extra_lines = battery_lines[1:] if battery_lines and len(battery_lines) > 1 else []
        self.battery_footer.config(text="\n".join(extra_lines))
        self._set_battery_bar(first_battery_line)

    def _set_battery_bar(self, battery_line: str) -> None:
        line = (battery_line or "Battery: Unknown").strip()
        if ":" in line:
            self._battery_bar_name = line.split(":", 1)[0].strip() or "Battery"
        percent_match = re.search(r"(\d+)%", line)
        self._battery_bar_percent = int(percent_match.group(1)) if percent_match else None
        self._battery_bar_charging = "charging" in line.lower()
        if self._battery_bar_percent is None:
            self._battery_bar_label = line
        else:
            base_label = re.sub(r"\s+(charging|discharging)\s*$", "", line, flags=re.IGNORECASE)
            state_label = "Charging" if self._battery_bar_charging else "Discharging"
            self._battery_bar_label = f"{base_label} {state_label}"
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
        self.autopilot_hash_footer.config(text=text or "", fg=color or "#475467")

    def _update_order_notes_footer(self, text: str) -> None:
        notes_value = (text or "").strip() or "No notes attached to this order."
        self.order_notes_footer.configure(state="normal")
        self.order_notes_footer.delete("1.0", "end")
        self.order_notes_footer.insert("1.0", notes_value)
        self.order_notes_footer.configure(state="disabled")

    def _refresh_primary_battery_state(self) -> None:
        try:
            percent = get_live_battery_percent(index=0)
            charging = is_battery_charging(0)
        except Exception:
            return

        changed = (percent != self._battery_bar_percent) or (charging != self._battery_bar_charging)
        self._battery_bar_percent = percent
        self._battery_bar_charging = charging

        if percent is None:
            self._battery_bar_label = f"{self._battery_bar_name}: Unknown"
            return

        state_label = "Charging" if charging else "Discharging"
        self._battery_bar_label = f"{self._battery_bar_name}: {percent}% {state_label}"
        if changed:
            self._battery_bar_pulse = 0.0

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
        canvas.update_idletasks()

        width = max(canvas.winfo_width(), 320)
        bar_width = min(340, width - 8)
        bar_height = 18
        x1 = 2
        y1 = 2
        x2 = x1 + bar_width
        y2 = y1 + bar_height

        canvas.create_rectangle(x1, y1, x2, y2, fill="#edf1f7", outline="#d7dde8")

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

        canvas.create_text(
            x1 + (bar_width // 2),
            y1 + (bar_height // 2),
            text=self._battery_bar_label,
            fill="#101828",
            font=("Segoe UI", 10, "bold"),
        )

    def run_search(self):
        order_id = self.order_entry.get().strip()
        log_event(f"User initiated search for order ID: {order_id}")
        if not order_id or not re.match(r"^[A-Za-z0-9\-]{3,32}$", order_id):
            log_event(f"Invalid order ID entered: {order_id}")
            messagebox.showerror("Invalid Order ID", "Please enter a valid order number (alphanumeric, 3-32 characters).")
            log_event(f"User entered invalid order ID: '{order_id}'")
            return

        log_event(f"User initiated search for order: {order_id}")
        self._showing_default_specs = False
        self._update_hash_capture_status("", "#475467")
        self._update_order_notes_footer("")

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
            self.update_test_result_labels()
            self.test_panel_button.config(state="normal")
            self.search_button.config(state="normal")

        search_order_logic(
            order_id,
            self.canvas,
            self.search_button,
            self.test_results,
            self.test_labels,
            self.root,
            self.current_user.username if self.current_user else None,
            on_complete=reenable_button,
        )

    def _build_helper_command(self, flag: str) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, flag]
        return [sys.executable, os.path.abspath(sys.argv[0]), flag]

    def check_for_updates(self, silent: bool = False):
        def worker():
            try:
                result = subprocess.run(
                    self._build_helper_command("--check-updates"),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except Exception as err:
                log_event(f"App update check process failed: {err}")
                if not silent:
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Update Check Failed",
                            f"Unable to check for updates:\n{err}",
                        ),
                    )
                return

            if result.returncode != 0:
                log_event(
                    f"Update helper exited {result.returncode}: "
                    f"{(result.stderr or result.stdout).strip()}"
                )
                if not silent:
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Update Check Failed",
                            "Unable to check for updates; see log for details.",
                        ),
                    )
                return

            stdout = result.stdout.strip()
            if not stdout:
                if not silent:
                    self.root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "No Updates", "You are already running the latest version."
                        ),
                    )
                return

            try:
                manifest_data = json.loads(stdout)
            except json.JSONDecodeError as exc:
                log_event(f"Failed to parse update helper output: {exc}")
                if not silent:
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Update Check Failed",
                            "Received invalid response from update helper.",
                        ),
                    )
                return

            manifest = UpdateManifest(
                version=manifest_data["version"],
                download_url=manifest_data.get("download_url"),
                release_page=manifest_data.get("release_page"),
                notes=manifest_data.get("notes"),
                metadata=manifest_data.get("metadata", {}),
            )

            notes = (manifest.notes or "No release notes provided.").strip()

            def show_update_prompt():
                message = (
                    f"A new release ({manifest.version}) is available.\n"
                    f"You are running version {self.update_service.current_version}.\n\n"
                    f"{notes}\n\n"
                    "Install it now?"
                )
                if messagebox.askyesno("Update Available", message):
                    try:
                        self.update_service.launch_update(manifest)
                    except Exception as err:
                        log_event(f"App update launch failed: {err}")
                        self.root.after(
                            0,
                            lambda: messagebox.showerror(
                                "Update Failed",
                                f"Failed to install update:\n{err}",
                            ),
                        )
                        return
                    self._shutdown_for_update()

            self.root.after(0, show_update_prompt)

        threading.Thread(target=worker, daemon=True).start()

    def _shutdown_for_update(self):
        log_event("Shutting down to install update.")
        try:
            self.root.quit()
        except tk.TclError:
            pass
        self.root.destroy()
        sys.exit(0)

    def animate_dots(self, count):
        if self.canvas.find_withtag("search_status"):
            dots = "." * (count % 4)
            text = f"Searching{dots}"
            self.canvas.itemconfigure("search_status", text=text)
            self.root.after(500, lambda: self.animate_dots(count + 1))

    def _render_laptop_specs(self):
        self._showing_default_specs = True
        specs = load_laptop_specs()
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
            "activation": "Not Run",
        }
        if self.mdm_status is None:
            self.mdm_status = check_mdm_lock_status()
        mdm_status = self.mdm_status
        def draw():
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

        status = self.mdm_status
        mdm_state = status.get("state", "error")
        mdm_details = status.get("details", "")

        if mdm_state == "locked":
            mdm_text = "Microsoft MDM lock detected."
            if mdm_details:
                mdm_text = f"{mdm_text}\n{mdm_details}"
            mdm_color = "#b42318"
        elif mdm_state == "not_locked":
            mdm_text = "No Microsoft MDM lock detected."
            if mdm_details:
                mdm_text = f"{mdm_text}\n{mdm_details}"
            mdm_color = "#1f7a4d"
        elif mdm_state == "unsupported":
            mdm_text = mdm_details or "Microsoft MDM lock checks are not supported on this platform."
            mdm_color = "#475467"
        else:
            mdm_text = mdm_details or "Unable to retrieve Microsoft MDM lock status."
            mdm_color = "#b54708"

        self.mdm_footer.config(text=mdm_text, fg=mdm_color)

    def _refresh_mdm_status_async(self):
        if self._mdm_refresh_started:
            return
        self._mdm_refresh_started = True

        def worker():
            try:
                result = subprocess.run(
                    self._build_helper_command("--refresh-mdm"),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except Exception as err:
                log_event(f"MDM refresh process failed: {err}")
                return

            if result.returncode != 0:
                log_event(
                    f"MDM refresh helper exited {result.returncode}: "
                    f"{(result.stderr or result.stdout).strip()}"
                )
                return

            stdout = result.stdout.strip()
            if not stdout:
                log_event("MDM refresh helper finished with no status.")
                return

            try:
                status = json.loads(stdout)
            except json.JSONDecodeError as exc:
                log_event(f"Failed to parse MDM refresh output: {exc}")
                return

            self.mdm_status = status
            if self._showing_default_specs:
                self.root.after(0, self._render_laptop_specs)
            else:
                self.root.after(0, self._apply_mdm_status_to_footer_only)

        threading.Thread(target=worker, daemon=True).start()

    def update_test_result_labels(self):
        for result_key, symbol in self.test_results.items():
            label_widget = self.test_labels.get(f"{result_key}_label")
            if label_widget:
                try:
                    if label_widget.winfo_exists():
                        if symbol == "pass":
                            display = "OK"
                        elif symbol == "fail":
                            display = "X"
                        else:
                            display = "Not Run"
                        label_widget.config(text=display)
                    else:
                        self.test_labels[f"{result_key}_label"] = None
                except tk.TclError:
                    self.test_labels[f"{result_key}_label"] = None

    def open_test_panel(self):
        log_event("Opening test panel.")
        if self.tests_window and tk.Toplevel.winfo_exists(self.tests_window):
            log_event("Test panel already open. Bringing it to focus.")
            self.tests_window.lift()
            self.tests_window.focus_force()
            return

        test_keys = ["keyboard", "speaker", "microphone", "display", "webcam", "usb"]
        test_values = [self.test_results.get(k, "Not Run") for k in test_keys]

        if all(v == "Not Run" for v in test_values):
            messagebox.showwarning("Warning", "Not connected to database, failed to load test results.")

        for key in test_keys:
            if key not in self.test_results:
                self.test_results[key] = "Not Run"

        print(f"[DEBUG] Passing activation to UI: {self.test_results.get('activation')}")

        tests_window_instance = TestsWindow(self.root, self.test_results, self.test_labels)
        self.tests_window = tests_window_instance.tests_window

        def on_tests_window_close():
            self.tests_window.destroy()
            self.tests_window = None

        self.tests_window.protocol("WM_DELETE_WINDOW", on_tests_window_close)

    def run_windows_update_script(self):
        def worker():
            try:
                self.update_status("Running Windows Update script...")
                if getattr(sys, "frozen", False):
                    base_path = sys._MEIPASS
                else:
                    base_path = os.path.dirname(os.path.abspath(__file__))
                script_path = os.path.join(base_path, "Script.ps1")
                temp_script = os.path.join(os.environ.get("TEMP", "/tmp"), "Script.ps1")
                shutil.copyfile(script_path, temp_script)

                ps_command = [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    f'Start-Process powershell -ArgumentList \'-NoProfile -ExecutionPolicy Bypass -File "{temp_script}"\' -Verb RunAs -Wait; exit $LASTEXITCODE',
                ]

                subprocess.run(ps_command, check=True)
                self.root.after(0, lambda: messagebox.showinfo(
                    "Windows Update",
                    "Windows Update script has finished.\nCheck Windows Update history for details."
                ))
            except subprocess.CalledProcessError as err:
                msg = f"Windows Update script failed to run:\n{err}"
                self.root.after(0, lambda: messagebox.showerror("Update Error", msg))
            except Exception as err:
                msg = f"Unexpected error running Windows Update script:\n{err}"
                self.root.after(0, lambda: messagebox.showerror("Update Error", msg))
            finally:
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
