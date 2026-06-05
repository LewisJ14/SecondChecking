# hardware_tests/usb.py
import tkinter as tk
from utils.ui_scaling import center_window, center_window_to_content

def run_usb_test(root, test_results, test_labels, tests_window=None, completion_event=None):
    def finalize(result=None):
        if result is not None:
            test_results["usb"] = result
            if "usb_label" in test_labels:
                test_labels["usb_label"].config(text="✅" if result == "pass" else "❌")
            if tests_window and hasattr(tests_window, "update_icon"):
                tests_window.update_icon("usb")
        if completion_event and not completion_event.is_set():
            completion_event.set()

    try:
        import win32file
    except ImportError:
        tk.messagebox.showerror("Missing Dependency", "win32file is required for USB test.")
        finalize("fail")
        return

    window = tk.Toplevel(root)
    window.title("USB Test")
    center_window(window, 340, 340, min_width=300, min_height=280)
    label = tk.Label(window, text="Plug in a USB device", font=("Arial", 10))
    label.pack(pady=10)
    listbox = tk.Listbox(window)
    listbox.pack(expand=True, fill="both", padx=10, pady=10)

    def get_usb_devices():
        try:
            drives = win32file.GetLogicalDrives()
        except Exception as e:
            tk.messagebox.showerror("USB Error", f"Failed to enumerate USB devices:\n{e}")
            return set()
        devices = set()
        for i in range(26):
            if drives & (1 << i):
                drive_letter = f"{chr(65 + i)}:\\"
                try:
                    if win32file.GetDriveType(drive_letter) == win32file.DRIVE_REMOVABLE:
                        device_path = win32file.QueryDosDevice(drive_letter.rstrip("\\"))
                        devices.add(f"{drive_letter} - {device_path}")
                except Exception:
                    continue
        return devices

    known = get_usb_devices()
    listbox.insert(tk.END, *sorted(known))

    def poll():
        updated = get_usb_devices()
        new = updated - known
        if new:
            for dev in new:
                listbox.insert(tk.END, dev)
            known.update(new)
        if window.winfo_exists():
            window.after(1000, poll)  # Increased interval to 1000ms

    poll()

    def on_close():
        window.destroy()
        prompt_result()

    def prompt_result():
        result_window = tk.Toplevel(root)
        result_window.title("USB Test Result")
        result_window.resizable(True, True)

        tk.Label(result_window, text="Did the USB test pass?", font=("Arial", 11)).pack(pady=10)
        frame = tk.Frame(result_window)
        frame.pack(fill="x", padx=12, pady=(0, 12))
        frame.grid_columnconfigure((0, 1, 2), weight=1, uniform="usb_result")

        def handle_response(result):
            finalize(result)
            result_window.destroy()

        from ttkbootstrap import ttk
        yes_button = ttk.Button(frame, text="Yes", style="success.TButton", command=lambda: handle_response("pass"))
        yes_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(
            frame,
            text="Retry",
            style="info.TButton",
            command=lambda: [
                result_window.destroy(),
                run_usb_test(
                    root,
                    test_results,
                    test_labels,
                    tests_window,
                    completion_event=completion_event,
                ),
            ],
        ).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(frame, text="No", style="danger.TButton", command=lambda: handle_response("fail")).grid(row=0, column=2, sticky="ew", padx=(5, 0))

        result_window.protocol("WM_DELETE_WINDOW", lambda: handle_response("fail"))
        result_window.bind("<Return>", lambda event: handle_response("pass"))
        center_window_to_content(result_window, min_width=360, min_height=150)
        yes_button.focus_set()

    window.protocol("WM_DELETE_WINDOW", on_close)
