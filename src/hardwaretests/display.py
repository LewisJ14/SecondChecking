# hardware_tests/display.py
import tkinter as tk

def run_display_test(root, test_results, test_labels, tests_window=None, completion_event=None):
    def finalize(result=None):
        if result is not None:
            test_results["display"] = result
            if "display_label" in test_labels:
                test_labels["display_label"].config(text="✅" if result == "pass" else "❌")
            if tests_window and hasattr(tests_window, "update_icon"):
                tests_window.update_icon("display")
        if completion_event and not completion_event.is_set():
            completion_event.set()

    try:
        colors = ["red", "green", "blue", "white", "black"]
        index = [0]
        window = tk.Toplevel(root)
        window.attributes("-fullscreen", True)
        window.configure(bg=colors[index[0]])

        def next_color(event=None):
            index[0] += 1
            if index[0] >= len(colors):
                window.destroy()
                prompt_result()
            else:
                window.configure(bg=colors[index[0]])

        def escape_exit(event=None):
            window.destroy()
            prompt_result()

        def prompt_result():
            result_window = tk.Toplevel(root)
            result_window.title("Display Test Result")
            result_window.geometry("300x130")
            result_window.resizable(False, False)

            tk.Label(result_window, text="Did the display test pass?", font=("Arial", 11)).pack(pady=10)
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
                    run_display_test(
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

        window.bind("<Key>", next_color)
        window.bind("<Button-1>", next_color)
        window.bind("<Escape>", escape_exit)
        window.protocol("WM_DELETE_WINDOW", escape_exit)
    except Exception as e:
        tk.messagebox.showerror("Display Test Error", f"An error occurred: {e}")
        finalize("fail")
