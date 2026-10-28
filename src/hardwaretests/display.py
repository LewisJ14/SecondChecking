# hardware_tests/display.py
import tkinter as tk
from utils.ui_scaling import center_window_to_content
from services.test_coverage import record_coverage

def run_display_test(root, test_results, test_labels, tests_window=None, completion_event=None):
    visited = []
    def finalize(result=None):
        if result is not None:
            record_coverage(test_results, 'display',
                            'Operator colour-screen inspection on the current '
                            'screen; native resolution and other panels untested.',
                            {'colours_shown': list(visited),
                             'inspect_for': ['dead/stuck pixels', 'lines',
                                             'flicker', 'uneven lighting']})
            test_results["display"] = result
            if "display_label" in test_labels:
                test_labels["display_label"].config(text=result.upper())
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
        visited.append(colors[0])
        instructions = tk.Label(window, autostyle=False, text='Inspect for dead/stuck pixels, '
                                'lines, flicker and uneven lighting.\n'
                                'Click, Space or Enter: next colour (1/5). '
                                'Escape: Cancel.\nCurrent screen only; '
                                'native-panel capability is not measured.',
                                bg='white', fg='black', padx=10, pady=6)
        instructions.pack(side='bottom', pady=15)

        def next_color(event=None):
            index[0] += 1
            if index[0] >= len(colors):
                window.destroy()
                prompt_result()
            else:
                window.configure(bg=colors[index[0]])
                visited.append(colors[index[0]])
                instructions.config(text='Inspect {} ({}/5). Click, Space or '
                                    'Enter: next. Escape: Cancel. Look for '
                                    'pixels, lines, flicker and uneven lighting.'
                                    .format(colors[index[0]], index[0] + 1))

        def escape_exit(event=None):
            window.destroy()
            finalize("cancelled")

        if tests_window and hasattr(tests_window, 'register_cancel'):
            tests_window.register_cancel(escape_exit)

        def prompt_result():
            result_window = tk.Toplevel(root)
            result_window.title("Display Test Result")
            result_window.resizable(True, True)
            result_window.configure(bg="#f4f6fa")

            card = tk.Frame(
                result_window,
                autostyle=False, bg="#ffffff",
                padx=16,
                pady=16,
                highlightbackground="#d7dde8",
                highlightthickness=1,
            )
            card.pack(fill="both", expand=True, padx=12, pady=12)

            tk.Label(
                card,
                autostyle=False, text="Display Test Complete",
                font=("Segoe UI", 12, "bold"),
                bg="#ffffff",
                fg="#101828",
            ).pack(pady=(0, 8))
            tk.Label(
                card,
                autostyle=False, text="Did all five colour screens look correct? This checks the current screen only.",
                wraplength=380,
                font=("Segoe UI", 10),
                bg="#ffffff",
                fg="#475467",
            ).pack()
            frame = tk.Frame(card, autostyle=False, bg="#ffffff")
            frame.pack(fill="x", pady=(14, 0))
            frame.grid_columnconfigure((0, 1, 2), weight=1, uniform="display_result")

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
                    run_display_test(
                        root,
                        test_results,
                        test_labels,
                        tests_window,
                        completion_event=completion_event,
                    ),
                ],
            ).grid(row=0, column=1, sticky="ew", padx=5)
            ttk.Button(frame, text="No", style="danger.TButton", command=lambda: handle_response("fail")).grid(row=0, column=2, sticky="ew", padx=(5, 0))

            ttk.Button(frame, text="Cancel", command=lambda: handle_response("cancelled")).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
            result_window.protocol("WM_DELETE_WINDOW", lambda: handle_response("cancelled"))
            if tests_window and hasattr(tests_window, 'register_cancel'):
                tests_window.register_cancel(lambda: handle_response('cancelled'))
            center_window_to_content(result_window, min_width=380, min_height=190)
            yes_button.focus_set()

        window.bind("<space>", next_color)
        window.bind("<Return>", next_color)
        window.bind("<Button-1>", next_color)
        window.bind("<Escape>", escape_exit)
        window.protocol("WM_DELETE_WINDOW", escape_exit)
    except Exception as e:
        tk.messagebox.showerror("Display Test Error", f"An error occurred: {e}")
        finalize("error")
