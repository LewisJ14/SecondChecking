# app_controller.py
import tkinter as tk
from ui.tests import TestsWindow
from main_logic import search_order_logic

class AppController:
    def __init__(self, root):
        self.root = root
        self.root.title("Second Checking Tool")
        self.root.geometry("800x500")

        self.test_results = {}
        self.test_labels = {}

        self.search_frame = tk.Frame(self.root)
        self.search_frame.pack(pady=10)

        self.order_entry = tk.Entry(self.search_frame, width=20)
        self.order_entry.pack(side="left", padx=5)
        self.search_button = tk.Button(self.search_frame, text="Search", command=self.run_search)
        self.search_button.pack(side="left")

        self.canvas = tk.Canvas(self.root, bg="white", highlightthickness=0)
        self.canvas.pack(expand=True, fill="both", padx=10, pady=10)

        self.test_panel_button = tk.Button(self.root, text="Open Test Panel", command=self.open_test_panel, bg="lightblue", font=("Arial", 11))
        self.test_panel_button.pack(pady=10)

    def run_search(self):
        order_id = self.order_entry.get().strip()
        if not order_id:
            return
        search_order_logic(order_id, self.canvas, self.search_button, self.test_results, self.test_labels, self.root)

    def open_test_panel(self):
        TestsWindow(self.root, self.test_results, self.test_labels)