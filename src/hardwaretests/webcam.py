# hardware_tests/webcam.py
import tkinter as tk
from PIL import Image, ImageTk
import cv2
import threading
from utils.helpers import log_event
from utils.ui_scaling import center_window, center_window_to_content

def run_webcam_test(root, test_results, test_labels, tests_window=None, completion_event=None):
    def finalize(result=None):
        if result is not None:
            test_results["webcam"] = result
            if "webcam_label" in test_labels:
                test_labels["webcam_label"].config(text="✅" if result == "pass" else "❌")
            if tests_window and hasattr(tests_window, "update_icon"):
                tests_window.update_icon("webcam")
        if completion_event and not completion_event.is_set():
            completion_event.set()

    # Create loading popup
    loading_popup = tk.Toplevel(root)
    loading_popup.title("Loading")
    loading_popup.resizable(True, True)
    loading_popup.attributes("-topmost", True)
    loading_popup.configure(bg="#f4f6fa")

    loading_card = tk.Frame(
        loading_popup,
        bg="#ffffff",
        padx=14,
        pady=12,
        highlightbackground="#d7dde8",
        highlightthickness=1,
    )
    loading_card.pack(fill="both", expand=True, padx=8, pady=8)

    loading_label = tk.Label(
        loading_card,
        text="Loading camera",
        font=("Segoe UI", 11, "bold"),
        bg="#ffffff",
        fg="#101828",
    )
    loading_label.pack(expand=True)
    center_window_to_content(loading_popup, min_width=240, min_height=100)

    ellipsis_states = ["", ".", "..", "..."]
    ellipsis_index = [0]

    def animate_ellipsis():
        if not loading_popup.winfo_exists():
            return
        loading_label.config(text="Loading camera" + ellipsis_states[ellipsis_index[0]])
        ellipsis_index[0] = (ellipsis_index[0] + 1) % len(ellipsis_states)
        loading_popup.after(300, animate_ellipsis)

    animate_ellipsis()

    def start_camera():
        def detect_cameras():
            available_cams = []
            for i in range(10):  # Increased range to 10
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                if cap is not None and cap.read()[0]:
                    available_cams.append(i)
                    cap.release()
            return available_cams

        def initialize_camera():
            available_cams = detect_cameras()
            if not available_cams:
                root.after(
                    0,
                    lambda: [
                        loading_popup.destroy(),
                        tk.messagebox.showerror("Webcam Error", "No camera found."),
                        finalize("fail"),
                    ],
                )
                return

            cap = cv2.VideoCapture(available_cams[0], cv2.CAP_DSHOW)
            root.after(0, lambda: open_test_window(cap))

        threading.Thread(target=initialize_camera, daemon=True).start()

    def open_test_window(cap):
        loading_popup.destroy()

        window = tk.Toplevel(root)
        window.title("Webcam Test")
        center_window(window, 700, 560, min_width=420, min_height=360)

        label = tk.Label(window)
        label.pack()

        def update_frame():
            if not cap.isOpened():
                return
            ret, frame = cap.read()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = ImageTk.PhotoImage(Image.fromarray(frame))
                label.img = img
                label.config(image=img)
            if window.winfo_exists():
                window.after(30, update_frame)

        update_frame()

        def on_close():
            try:
                if cap.isOpened():
                    cap.release()
            except Exception as e:
                log_event(f"Error releasing camera: {e}")
            window.destroy()
            prompt_result()

        def prompt_result():
            result_window = tk.Toplevel(root)
            result_window.title("Webcam Test Result")
            result_window.resizable(True, True)
            result_window.configure(bg="#f4f6fa")

            card = tk.Frame(
                result_window,
                bg="#ffffff",
                padx=16,
                pady=16,
                highlightbackground="#d7dde8",
                highlightthickness=1,
            )
            card.pack(fill="both", expand=True, padx=12, pady=12)

            tk.Label(
                card,
                text="Webcam Test Complete",
                font=("Segoe UI", 12, "bold"),
                bg="#ffffff",
                fg="#101828",
            ).pack(pady=(0, 8))
            tk.Label(
                card,
                text="Did the webcam test pass?",
                font=("Segoe UI", 10),
                bg="#ffffff",
                fg="#475467",
            ).pack()
            frame = tk.Frame(card, bg="#ffffff")
            frame.pack(fill="x", pady=(14, 0))
            frame.grid_columnconfigure((0, 1, 2), weight=1, uniform="webcam_result")

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
                    run_webcam_test(
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
            center_window_to_content(result_window, min_width=380, min_height=190)
            yes_button.focus_set()

        window.protocol("WM_DELETE_WINDOW", on_close)

    threading.Thread(target=start_camera, daemon=True).start()
