# hardware_tests/usb.py
import tkinter as tk

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
    window.geometry("300x300")
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
        result_window.geometry("300x130")
        result_window.resizable(False, False)

        tk.Label(result_window, text="Did the USB test pass?", font=("Arial", 11)).pack(pady=10)
        frame = tk.Frame(result_window)
        frame.pack()

        def handle_response(result):
            finalize(result)
            result_window.destroy()

        from ttkbootstrap import ttk
        ttk.Button(frame, text="Yes", width=10, style="success.TButton", command=lambda: handle_response("pass")).pack(side="left", padx=5)
        ttk.Button(
            frame,
            text="Retry",
            width=10,
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
        ).pack(side="left", padx=5)
        ttk.Button(frame, text="No", width=10, style="danger.TButton", command=lambda: handle_response("fail")).pack(side="left", padx=5)

        result_window.protocol("WM_DELETE_WINDOW", lambda: handle_response("fail"))

    window.protocol("WM_DELETE_WINDOW", on_close)
