"""A scrollable final report review, before any assignment request is sent."""

import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from ttkbootstrap import ttk

from utils.ui_scaling import center_window


def prompt_assignment_review(root, summary, reason_required):
    result = [None]
    dialog = tk.Toplevel(root)
    dialog.title("Review assignment")
    dialog.transient(root)
    dialog.grab_set()
    center_window(dialog, 650, 560, min_width=460, min_height=400)
    dialog.grid_columnconfigure(0, weight=1)
    dialog.grid_rowconfigure(0, weight=1)

    report = ScrolledText(dialog, wrap="word", height=16, width=65,
                          font=("Arial", 10), padx=16, pady=16,
                          autostyle=False, bg='#ffffff', fg='#0f172a',
                          relief='flat', highlightthickness=1,
                          highlightbackground='#dce6f2')
    report.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
    report.insert("1.0", summary)
    report.configure(state="disabled")

    tk.Label(dialog, text=("Reason for proceeding (required):" if reason_required
                           else "All checks passed. Confirm assignment below."),
             anchor="w").grid(row=1, column=0, sticky="ew", padx=12)
    reason = tk.Text(dialog, height=3, wrap="word", font=("Arial", 10))
    if reason_required:
        reason.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 8))
        reason.focus_set()

    def accept():
        value = reason.get("1.0", "end-1c").strip() if reason_required else ""
        if reason_required and (not value or len(value) > 2000):
            messagebox.showerror("Reason required",
                                 "Enter a reason of 1–2000 characters.",
                                 parent=dialog)
            reason.focus_set()
            return
        result[0] = value
        dialog.destroy()

    actions = tk.Frame(dialog)
    actions.grid(row=3, column=0, sticky="ew", padx=12, pady=12)
    ttk.Button(actions, text="Cancel", command=dialog.destroy,
               style='secondary.Outline.TButton').pack(side="right")
    ttk.Button(actions, text=("Assign with recorded reason" if reason_required
                              else "Assign"), command=accept,
               style="primary.TButton").pack(side="right", padx=(0, 8))
    dialog.bind("<Escape>", lambda event: dialog.destroy())
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    root.wait_window(dialog)
    return result[0]
