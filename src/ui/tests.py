# ui/tests.py
import tkinter as tk
from tkinter import messagebox
import threading
import subprocess
from hardwaretests.speaker import run_speaker_test
from hardwaretests.display import run_display_test
from hardwaretests.webcam import run_webcam_test
from hardwaretests.usb import run_usb_test
from ui.keyboard_test import run_keyboard_test
from utils.helpers import check_activation_status, log_event
from ttkbootstrap import ttk

class TestsWindow:
    def __init__(self, root, test_results, test_labels):
        self.root = root
        self.test_results = test_results
        self.test_labels = test_labels
        self.test_buttons = {}  # Store references to test buttons
        self.tests_window = tk.Toplevel(self.root)
        self.tests_window.title("Hardware Tests")

        # --- Set a more compact fixed size and center the window ---
        width = 280
        height = 340
        screen_width = self.tests_window.winfo_screenwidth()
        screen_height = self.tests_window.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.tests_window.geometry(f"{width}x{height}+{x}+{y}")
        self.tests_window.minsize(260, 200)
        self.tests_window.resizable(True, True)

        self.tests_window.protocol("WM_DELETE_WINDOW", self.on_close)

        # Use a frame with pack and expand/fill for responsiveness
        self.main_frame = tk.Frame(self.tests_window)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.add_test_row("Speaker Test", lambda: self.run_test_threaded(run_speaker_test, "speaker"), "speaker")
        self.add_test_row("Display Test", lambda: self.run_test_threaded(run_display_test, "display"), "display")
        self.add_test_row("Keyboard Test", lambda: self.run_test_threaded(run_keyboard_test, "keyboard"), "keyboard")
        self.add_test_row("Webcam Test", lambda: self.run_test_threaded(run_webcam_test, "webcam"), "webcam")
        self.add_test_row("USB Test", lambda: self.run_test_threaded(run_usb_test, "usb"), "usb")
        self.add_activation_row()

        # Make all rows expand horizontally
        for child in self.main_frame.winfo_children():
            child.pack_configure(fill="x", expand=True)

    def run_test_threaded(self, test_func, key):
        def run():
            try:
                self.update_status(f"Running {key} test...")
                test_func(self.root, self.test_results, self.test_labels, self)  # Pass self!
                self.update_icon(key)
            except Exception as e:
                log_event(f"Error running {key} test: {e}")
                self.test_results[key] = "fail"
                self.update_icon(key)
                messagebox.showerror("Test Error", f"An error occurred during the {key} test.")
            finally:
                self.update_status("")  # Clear status
        threading.Thread(target=run, daemon=True).start()

    def update_icon(self, key):
        icon = "✅" if self.test_results.get(key) == "pass" else "❌" if self.test_results.get(key) == "fail" else "Not Run"
        label_key = f"{key}_label"
        if label_key in self.test_labels:
            self.test_labels[label_key].config(text=icon)
        # Update button style as well
        btn = self.test_buttons.get(key)
        if btn:
            result = self.test_results.get(key)
            if result == "pass":
                btn.config(style="success.TButton")
            elif result == "fail":
                btn.config(style="danger.TButton")
            else:
                btn.config(style="info.TButton")

    def on_close(self):
        self.tests_window.destroy()

    def get_result_icon(self, test):
        result = self.test_results.get(test)
        return "✅" if result == "pass" else "❌" if result == "fail" else "Not Run"

    def view_product_key(self):
        def run():
            try:
                result = subprocess.run(
                    ['powershell', '-Command', "(Get-WmiObject -query 'select * from SoftwareLicensingService').OA3xOriginalProductKey"],
                    capture_output=True, text=True, timeout=10
                )
                key = result.stdout.strip()
                if not key:
                    raise Exception("No product key found.")
                self.root.after(0, lambda: messagebox.showinfo("Windows Product Key", f"OEM Key: {key}"))
            except Exception as e:
                log_event(f"Product key retrieval error: {e}")
                self.root.after(0, lambda: messagebox.showerror("Error", "Failed to retrieve product key."))
        threading.Thread(target=run, daemon=True).start()

    def attempt_activation(self):
        def run():
            try:
                self.update_status("Attempting activation...")
                subprocess.run(
                    ['cscript.exe', '//Nologo', 'C:\\Windows\\System32\\slmgr.vbs', '/ato'],
                    capture_output=True, text=True, timeout=15
                )
                # Check activation status
                self.test_results["activation"] = "pass" if check_activation_status() else "fail"
                log_event(f"[DEBUG] Passing activation to UI: {self.test_results['activation']}")
                icon = "✅" if self.test_results["activation"] == "pass" else "❌"
                self.root.after(0, lambda: self.test_labels["activation_label"].config(text=icon))
                # Update activation button style
                btn = self.test_buttons.get("activation")
                if btn:
                    status = self.test_results["activation"]
                    if status == "pass":
                        btn.config(style="success.TButton")
                    elif status == "fail":
                        btn.config(style="danger.TButton")
                    else:
                        btn.config(style="secondary.TButton")
                # Show result dialog and re-raise tests window
                if self.test_results["activation"] == "pass":
                    self.root.after(0, lambda: [messagebox.showinfo("Activation", "Windows activation succeeded."),
                                                self.tests_window.lift(), self.tests_window.focus_force()])
                else:
                    self.root.after(0, lambda: [messagebox.showerror("Activation", "Windows activation failed."),
                                                self.tests_window.lift(), self.tests_window.focus_force()])
            except Exception as e:
                log_event(f"Activation error: {e}")
                self.root.after(0, lambda: self.test_labels["activation_label"].config(text="❌"))
                btn = self.test_buttons.get("activation")
                if btn:
                    btn.config(style="danger.TButton")
                self.root.after(0, lambda: [messagebox.showerror("Activation", "An error occurred during activation."),
                                            self.tests_window.lift(), self.tests_window.focus_force()])
            finally:
                self.update_status("")  # Clear status
        threading.Thread(target=run, daemon=True).start()

    def update_status(self, message):
        # Add a status label or update an existing one
        if hasattr(self, "status_label"):
            self.status_label.config(text=message)
        else:
            self.status_label = tk.Label(self.main_frame, text=message, font=("Arial", 10, "italic"))
            self.status_label.pack(pady=5, fill="x")

    def add_activation_row(self):
        row = tk.Frame(self.main_frame)
        row.pack(pady=10, fill="x", expand=True)
        status = self.test_results.get("activation", "fail")
        if status == "pass":
            style = "success.TButton"
        elif status == "fail":
            style = "danger.TButton"
        else:
            style = "secondary.TButton"
        btn = ttk.Button(row, text="Activation", command=self.show_activation_dialog, style=style, width=15)
        btn.pack(side="left", padx=5)
        icon = "✅" if status == "pass" else "❌"
        lbl = tk.Label(row, text=icon, font=("Arial", 11))
        lbl.pack(side="left", padx=5)
        self.test_labels["activation_label"] = lbl
        self.test_buttons["activation"] = btn

    def show_activation_dialog(self):
        dialog = tk.Toplevel(self.tests_window)
        dialog.title("Windows Activation")
        # Responsive: center and set min size
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        width = 300
        height = 120
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.minsize(250, 100)
        dialog.transient(self.tests_window)
        dialog.grab_set()

        label = tk.Label(dialog, text="Choose an activation option:")
        label.pack(pady=10)

        view_btn = ttk.Button(dialog, text="View Product Key", command=self.view_product_key, style="info.TButton")
        view_btn.pack(pady=5, fill="x", expand=True)

        activate_btn = ttk.Button(dialog, text="Reactivate (BIOS Key)", command=lambda: [self.attempt_activation(), dialog.destroy()], style="success.TButton")
        activate_btn.pack(pady=5, fill="x", expand=True)

    def add_test_row(self, label, command, key):
        row = tk.Frame(self.main_frame)
        row.pack(pady=10, fill="x", expand=True)
        result = self.test_results.get(key)
        if result == "pass":
            style = "success.TButton"
        elif result == "fail":
            style = "danger.TButton"
        else:
            style = "secondary.TButton"
        btn = ttk.Button(row, text=label, command=command, style=style, width=15)
        btn.pack(side="left", padx=5)
        icon = "✅" if result == "pass" else "❌" if result == "fail" else "Not Run"
        lbl = tk.Label(row, text=icon, font=("Arial", 11))
        lbl.pack(side="left", padx=5)
        self.test_labels[f"{key}_label"] = lbl
        self.test_buttons[key] = btn