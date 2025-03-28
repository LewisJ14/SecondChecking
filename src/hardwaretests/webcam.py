# hardware_tests/webcam.py
import tkinter as tk
from PIL import Image, ImageTk
import cv2
import threading

def run_webcam_test(root, test_results, test_labels):
    # Create loading popup
    loading_popup = tk.Toplevel(root)
    loading_popup.title("Loading")
    loading_popup.geometry("220x80")
    loading_popup.resizable(False, False)
    loading_popup.attributes("-topmost", True)

    loading_label = tk.Label(loading_popup, text="Loading camera", font=("Arial", 11))
    loading_label.pack(expand=True, pady=15)

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
        available_cams = []
        for i in range(5):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap is not None and cap.read()[0]:
                available_cams.append(i)
                cap.release()

        if not available_cams:
            loading_popup.destroy()
            tk.messagebox.showerror("Webcam Error", "No camera found.")
            return

        cap = cv2.VideoCapture(available_cams[0], cv2.CAP_DSHOW)

        def open_test_window():
            loading_popup.destroy()

            window = tk.Toplevel(root)
            window.title("Webcam Test")
            window.geometry("640x520")

            label = tk.Label(window)
            label.pack()

            def update_frame():
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
                cap.release()
                window.destroy()
                prompt_result()

            def prompt_result():
                result_window = tk.Toplevel(root)
                result_window.title("Webcam Test Result")
                result_window.geometry("300x130")
                result_window.resizable(False, False)

                tk.Label(result_window, text="Did the webcam test pass?", font=("Arial", 11)).pack(pady=10)
                frame = tk.Frame(result_window)
                frame.pack()

                def handle_response(result):
                    test_results["webcam"] = result
                    if "webcam_label" in test_labels:
                        test_labels["webcam_label"].config(text="✅" if result == "pass" else "❌")
                    result_window.destroy()

                tk.Button(frame, text="Yes", width=10, bg="lightgreen", command=lambda: handle_response("pass")).pack(side="left", padx=5)
                tk.Button(frame, text="Retry", width=10, bg="lightblue", command=lambda: [result_window.destroy(), run_webcam_test(root, test_results, test_labels)]).pack(side="left", padx=5)
                tk.Button(frame, text="No", width=10, bg="tomato", command=lambda: handle_response("fail")).pack(side="left", padx=5)

                result_window.protocol("WM_DELETE_WINDOW", result_window.destroy)

            window.protocol("WM_DELETE_WINDOW", on_close)

        root.after(0, open_test_window)

    threading.Thread(target=start_camera, daemon=True).start()