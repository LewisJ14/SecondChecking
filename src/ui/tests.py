# ui/tests.py
import tkinter as tk
from tkinter import messagebox
import threading
from utils.specs import get_laptop_specs
from db.database import get_db_connection
from utils.helpers import log_event
from hardwaretests.speaker import run_speaker_test
from hardwaretests.display import run_display_test
from hardwaretests.webcam import run_webcam_test
from hardwaretests.usb import run_usb_test
from ui.keyboard_test import run_keyboard_test
from logic.view_serials_logic import open_serial_viewer as view_serials

class TestsWindow:
    def __init__(self, root, test_results, test_labels):
        self.root = root
        self.test_results = test_results
        self.test_labels = test_labels
        self.tests_window = tk.Toplevel(self.root)
        self.tests_window.title("Hardware Tests")
        self.tests_window.geometry("300x300")

        self.tests_window.protocol("WM_DELETE_WINDOW", self.on_close)

        self.add_test_row("Speaker Test", lambda: run_speaker_test(self.root, self.test_results, self.test_labels), "speaker")
        self.add_test_row("Display Test", lambda: run_display_test(self.root, self.test_results, self.test_labels), "display")
        self.add_test_row("Keyboard Test", lambda: run_keyboard_test(), "keyboard")
        self.add_test_row("Webcam Test", lambda: run_webcam_test(self.root, self.test_results, self.test_labels), "webcam")
        self.add_test_row("USB Test", lambda: run_usb_test(self.root, self.test_results, self.test_labels), "usb")

        threading.Thread(target=self.load_previous_results, daemon=True).start()

    def on_close(self):
        self.tests_window.destroy()

    def get_result_icon(self, test):
        result = self.test_results.get(test)
        return "✅" if result == "pass" else "❌" if result == "fail" else ""

    def add_test_row(self, label, command, key):
        row = tk.Frame(self.tests_window)
        row.pack(pady=10)
        btn = tk.Button(row, text=label, command=command, bg="lightblue", width=15)
        btn.pack(side="left", padx=5)
        lbl = tk.Label(row, text="", font=("Arial", 11))
        lbl.pack(side="left", padx=5)
        self.test_labels[f"{key}_label"] = lbl

    def load_previous_results(self):
        specs = get_laptop_specs()
        serial_number = specs.get("Serial Number", "Unknown")
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT test_keyboard, test_speaker, test_display, test_webcam, test_usb
                FROM order_serials
                WHERE serial_number = %s
            """, (serial_number,))
            row = cursor.fetchone()
            conn.close()

            if row:
                keys = ["keyboard", "speaker", "display", "webcam", "usb"]
                for i, result in enumerate(row):
                    if result in ["pass", "fail"]:
                        self.test_results[keys[i]] = result

            for key in ["keyboard", "speaker", "display", "webcam", "usb"]:
                label_key = f"{key}_label"
                if label_key in self.test_labels:
                    self.test_labels[label_key].config(text=self.get_result_icon(key))
        except Exception as err:
            log_event(f"MySQL error loading test results: {err}")
            self.root.after(0, lambda err=err: messagebox.showerror("Database Error", f"Error loading test results:\n{err}"))