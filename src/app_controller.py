# app_controller.py
import tkinter as tk
from ttkbootstrap import ttk
from ui.tests import TestsWindow
from main_logic import search_order_logic
from utils.helpers import log_event
from tkinter import messagebox
import threading
import re
import sys
import os
import shutil
import subprocess
import ttkbootstrap as tb

class AppController:
    def __init__(self, root):
        # Initialize the main application window and its components
        self.root = root
        self.test_results = {}
        self.test_labels = {}
        self.tests_window = None
        self.root.title("Second Checking Tool")

        # --- Responsive window setup ---
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        width = min(int(screen_width * 0.7), 1200)
        height = min(int(screen_height * 0.7), 800)
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(800, 500)
        self.root.resizable(True, True)

        # Set default font
        default_font = ("Segoe UI", 11)
        self.root.option_add("*Font", default_font)

        # Set ttkbootstrap theme (optional: pick your favorite)
        style = tb.Style()
        style.theme_use('flatly')  # Try 'flatly', 'cosmo', 'superhero', etc.

        # Colors
        primary_bg = "#f5f6fa"
        self.root.configure(bg=primary_bg)

        style.configure("Header.TFrame", background="#e0e1e6")

        # Menu bar
        menubar = tk.Menu(self.root, bg=primary_bg, fg="#222")
        self.root.config(menu=menubar)
        tools_menu = tk.Menu(menubar, tearoff=0, bg=primary_bg, fg="#222")
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Run Windows Updates", command=self.run_windows_update_script)

        # Header frame (responsive)
        header_frame = ttk.Frame(self.root, padding=(10, 10, 10, 10), style="Header.TFrame")
        header_frame.pack(fill="x")

        # Test Menu button (left) - use a friendly info color
        self.test_panel_button = ttk.Button(
            header_frame,
            text="Test Menu",
            command=self.open_test_panel,
            style="info.TButton"  # Blue, friendly and clear
        )
        self.test_panel_button.grid(row=0, column=0, padx=(0, 10), pady=0, ipady=4, sticky="w")

        # Search Entry (center)
        self.order_entry = ttk.Entry(header_frame, width=32, font=("Segoe UI", 11))
        self.order_entry.grid(row=0, column=1, padx=(0, 5), pady=0, ipady=4, sticky="ew")
        self.order_entry.bind("<Return>", lambda event: self.run_search())

        # Search Button (right of entry) - use a friendly success color
        self.search_button = ttk.Button(
            header_frame,
            text="Search",
            command=self.run_search,
            style="success.TButton"  # Green, positive action
        )
        self.search_button.grid(row=0, column=2, padx=(0, 0), pady=0, ipady=4, sticky="w")

        # Make the entry expand in the middle
        header_frame.grid_columnconfigure(0, weight=0)
        header_frame.grid_columnconfigure(1, weight=1)
        header_frame.grid_columnconfigure(2, weight=0)

        # Canvas for results (responsive)
        self.canvas = tk.Canvas(self.root, bg="#fff", highlightthickness=0)
        self.canvas.pack(expand=True, fill="both", padx=10, pady=10)
        self.canvas.configure(borderwidth=2, relief="groove")

        # Bind resizing to redraw or adjust layout if needed
        self.root.bind("<Configure>", self.on_resize)

    def on_resize(self, event):
        # Example: clear and redraw canvas or adjust widget sizes if needed
        # You can expand this for more complex layouts
        pass

    def run_search(self):
        # Perform a search for the given order ID and update the UI
        order_id = self.order_entry.get().strip()
        log_event(f"User initiated search for order ID: {order_id}")
        if not order_id or not re.match(r"^[A-Za-z0-9\-]{3,32}$", order_id):
            log_event(f"Invalid order ID entered: {order_id}")
            messagebox.showerror("Invalid Order ID", "Please enter a valid order number (alphanumeric, 3-32 characters).")
            log_event(f"User entered invalid order ID: '{order_id}'")
            return

        log_event(f"User initiated search for order: {order_id}")

        self.search_button.config(state="disabled")
        self.test_panel_button.config(state="disabled")
        self.canvas.delete("search_status")

        self.search_text_id = self.canvas.create_text(
            self.canvas.winfo_width() // 2,
            20,
            text="🔍 Searching",
            font=("Arial", 12, "italic"),
            fill="gray",
            tags="search_status"
        )
        self.animate_dots(0)

        def reenable_button():
            self.update_test_result_labels()
            self.test_panel_button.config(state="normal")
            self.search_button.config(state="normal")

        def run_logic():
            search_order_logic(order_id, self.canvas, self.search_button, self.test_results, self.test_labels, self.root)
            self.root.after(100, reenable_button)

        threading.Thread(target=run_logic, daemon=True).start()

    def animate_dots(self, count):
        # Animate the "Searching" text with dots to indicate progress
        if self.canvas.find_withtag("search_status"):
            dots = "." * (count % 4)
            text = f"🔍 Searching{dots}"
            self.canvas.itemconfigure("search_status", text=text)
            self.root.after(500, lambda: self.animate_dots(count + 1))

    def update_test_result_labels(self):
        # Update the test result labels in the UI based on the latest results
        for label_key, symbol in self.test_results.items():
            label_widget = self.test_labels.get(label_key)
            if label_widget:
                try:
                    # Only update if the widget still exists
                    if str(label_widget) in label_widget.winfo_toplevel().tk.call('winfo', 'children', '.'):
                        label_widget.config(text=symbol)
                    else:
                        self.test_labels[label_key] = None
                except tk.TclError:
                    self.test_labels[label_key] = None

    def open_test_panel(self):
        # Open the test panel window to display test results
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
                if getattr(sys, 'frozen', False):
                    base_path = sys._MEIPASS
                else:
                    base_path = os.path.dirname(os.path.abspath(__file__))
                script_path = os.path.join(base_path, "Script.ps1")
                temp_script = os.path.join(os.environ.get("TEMP", "/tmp"), "Script.ps1")
                shutil.copyfile(script_path, temp_script)

                ps_command = [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-Command",
                    f'Start-Process powershell -ArgumentList \'-NoProfile -ExecutionPolicy Bypass -File "{temp_script}"\' -Verb RunAs -Wait; exit $LASTEXITCODE'
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
                self.update_status("")  # Clear status

        threading.Thread(target=worker, daemon=True).start()

    def update_status(self, message):
        if hasattr(self, "status_label"):
            self.status_label.config(text=message)
        else:
            self.status_label = tk.Label(self.root, text=message, font=("Arial", 10, "italic"))
            self.status_label.pack(pady=5, fill="x")
