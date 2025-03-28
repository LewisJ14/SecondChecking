# app_controller.py
import tkinter as tk
from ui.tests import TestsWindow
from main_logic import search_order_logic
import threading

class AppController:
    def __init__(self, root):
        self.root = root
        self.root.title("Second Checking Tool")
        self.root.geometry("800x500")

        self.test_results = {}
        self.test_labels = {}

        # Top frame for header
        header_frame = tk.Frame(self.root)
        header_frame.pack(fill="x", pady=(5, 0))
        header_frame.grid_columnconfigure(0, weight=1)
        header_frame.grid_columnconfigure(1, weight=0)
        header_frame.grid_columnconfigure(2, weight=1)

        # Test Menu button (left-aligned)
        self.test_panel_button = tk.Button(
            header_frame,
            text="Test Menu",
            command=self.open_test_panel,
            bg="lightblue",
            font=("Arial", 9),
            width=10,
            height=1
        )
        self.test_panel_button.grid(row=0, column=0, padx=10, sticky="w")

        # Search container (centered in full app width)
        search_container = tk.Frame(header_frame)
        search_container.grid(row=0, column=1)

        self.search_frame = tk.Frame(search_container)
        self.search_frame.pack()

        self.order_entry = tk.Entry(self.search_frame, width=40, font=("Arial", 10))
        self.order_entry.pack(side="left", padx=5)
        self.order_entry.bind("<Return>", lambda event: self.run_search())

        self.search_button = tk.Button(self.search_frame, text="Search", command=self.run_search)
        self.search_button.pack(side="left")

        # Invisible button (right-aligned, same size as Test Menu)
        invisible_button = tk.Label(
            header_frame,
            text="",
            width=10,
            height=1
        )
        invisible_button.grid(row=0, column=2, padx=10, sticky="e")

        # Canvas for results
        self.canvas = tk.Canvas(self.root, bg="white", highlightthickness=0)
        self.canvas.pack(expand=True, fill="both", padx=10, pady=10)

    def run_search(self):
        order_id = self.order_entry.get().strip()
        if not order_id:
            return

        self.search_button.config(state="disabled")
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
            self.search_button.config(state="normal")
            self.update_test_result_labels()

        def run_logic():
            search_order_logic(order_id, self.canvas, self.search_button, self.test_results, self.test_labels, self.root)
            self.root.after(100, reenable_button)

        threading.Thread(target=run_logic, daemon=True).start()

    def animate_dots(self, count):
        if self.canvas.find_withtag("search_status"):
            dots = "." * (count % 4)
            text = f"🔍 Searching{dots}"
            self.canvas.itemconfigure("search_status", text=text)
            self.root.after(500, lambda: self.animate_dots(count + 1))

    def update_test_result_labels(self):
        for test, result in self.test_results.items():
            label_key = f"{test}_label"
            if label_key in self.test_labels:
                symbol = "✅" if result == "pass" else "❌"
                self.test_labels[label_key].config(text=symbol)

    def open_test_panel(self):
        TestsWindow(self.root, self.test_results, self.test_labels)