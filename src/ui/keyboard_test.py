# ui/keyboard_test.py
import tkinter as tk
import tkinter.font as tkfont
import math
from tkinter import messagebox
import traceback
import queue
import threading
from utils.ui_scaling import center_window_to_content, center_window
from ui.scrolling import ScrollableFrame
from services.test_coverage import record_coverage

try:
    import keyboard
except ImportError:  # pragma: no cover - optional dependency
    keyboard = None

SPECIAL_KEYS = {
    "caps lock": "caps lock", "windows": "win", "win": "win", "left windows": "win",
    "right shift": "r-shift", "right ctrl": "r-ctrl", "alt gr": "altgr", "altgr": "altgr",
    "print screen": "prtscr", "prtsc": "prtscr", "prt sc": "prtscr",
    "page up": "page up", "page down": "page down",
    "left": "left", "right": "right", "up": "up", "down": "down",
}

HIGHLIGHT_COLORS = {
    "default": "lightgrey",
    "pressed": "orange",
    "hit": "lightgreen"
}

keyboard_test_window = None
press_hook_id = None
release_hook_id = None

def run_keyboard_test(root, test_results, test_labels, tests_window=None, completion_event=None):
    global keyboard_test_window, press_hook_id, release_hook_id

    def finalize(result=None):
        if result is not None:
            test_results["keyboard"] = result
            if "keyboard_label" in test_labels:
                test_labels["keyboard_label"].config(text=result.upper())
            if tests_window and hasattr(tests_window, "update_icon"):
                root.after(0, lambda: tests_window.update_icon("keyboard"))
        if completion_event and not completion_event.is_set():
            completion_event.set()

    if keyboard is None:
        messagebox.showerror("Keyboard Test Error", "Keyboard module is not available. Install the 'keyboard' package to run this test.")
        finalize("error")
        return

    # Preload the keyboard layout
    def preload_keyboard_layout():
        # Simulate loading the keyboard layout (e.g., from a file or predefined configuration)
        # Replace this with actual logic to load the keyboard layout if needed
        return [
            ["Esc", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"],
            ["~", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "="],
            ["Tab", "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]"],
            ["Caps", "A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'", "Enter"],
            ["Shift", "Z", "X", "C", "V", "B", "N", "M", ",", ".", "/", "Shift"],
            ["Ctrl", "Alt", "Space", "Alt", "Ctrl"]
        ]

    try:
        if keyboard_test_window and keyboard_test_window.winfo_exists():
            keyboard_test_window.lift()
            keyboard_test_window.focus_force()
            return
    except Exception:
        keyboard_test_window = None

    # Preload the layout
    preload_keyboard_layout()

    keyboard_test_window = tk.Toplevel()
    keyboard_test_window.title("Keyboard Test")

    scale = float(root.tk.call('tk', 'scaling')) / (96 / 72)
    center_window(keyboard_test_window, round(1150 * scale), round(650 * scale),
                  min_width=480, min_height=360)
    keyboard_test_window.minsize(480, 360)
    keyboard_test_window.configure(bg='white')

    PRESSED_COLOR = HIGHLIGHT_COLORS["pressed"]
    DEFAULT_COLOR = HIGHLIGHT_COLORS["default"]
    FN_COLOR = "#999999"

    key_widgets = {}
    observed_keys = set()
    key_events = queue.Queue(maxsize=1000)
    stopped = threading.Event()
    poll_id = [None]
    owned_after_ids = []
    numpad_grid_options = {}

    container = tk.Frame(keyboard_test_window, autostyle=False, bg="white")
    container.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    keyboard_test_window.grid_rowconfigure(0, weight=1)
    keyboard_test_window.grid_columnconfigure(0, weight=1)

    # Main keyboard grid (now also holds numpad)
    keyboard_scroll = ScrollableFrame(container, height=340, horizontal=True)
    keyboard_scroll.grid(row=0, column=0, sticky='nsew')
    kb_frame = tk.Frame(keyboard_scroll.content, autostyle=False, bg="white")
    kb_frame.pack(fill='both', expand=True)
    container.grid_rowconfigure(0, weight=1)
    container.grid_columnconfigure(0, weight=1)

    # Show Numpad checkbox
    show_numpad_var = tk.BooleanVar(value=False)
    toggle_checkbox = tk.Checkbutton(container, autostyle=False, text="Show Numpad", variable=show_numpad_var,
                                     command=lambda: toggle_numpad(), bg="white", takefocus=False)
    toggle_checkbox.grid(row=1, column=0, sticky="w", pady=5)

    # Helper for grid-based key placement
    def create_key_button_grid(frame, key, row, column, columnspan=1, rowspan=1, width=6, key_id=None, color=None):
        color = color if color else (FN_COLOR if key.lower() == "fn" else DEFAULT_COLOR)
        font_size = 10
        metrics = tkfont.Font(root=root, family='Arial', size=font_size, weight='bold')
        required = math.ceil(metrics.measure(key) / max(1, metrics.measure('0'))) + 1
        btn = tk.Label(frame, autostyle=False, text=key, width=max(width, required), height=2, relief="raised", borderwidth=1,
                       bg=color, font=("Arial", font_size, "bold"))
        btn.grid(row=row, column=column, columnspan=columnspan, rowspan=rowspan, padx=2, pady=2, sticky="nsew")
        key_widgets[(key_id or key).lower()] = btn
        return btn

    # --- Main Keyboard Layout (ISO/UK/English style) ---
    # Row 0: Function keys
    func_keys = ["Esc", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12", "PrtScr", "Home", "End", "Insert", "Delete"]
    for i, key in enumerate(func_keys):
        create_key_button_grid(kb_frame, key, 0, i, width=6, key_id=SPECIAL_KEYS.get(key.lower(), key))

    # Row 1: Number row
    num_row = ["`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "Backspace"]
    col = 0
    for key in num_row:
        if key == "Backspace":
            create_key_button_grid(kb_frame, key, 1, col, columnspan=2, width=12, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col += 2
        else:
            create_key_button_grid(kb_frame, key, 1, col, width=6, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col += 1

    # Row 2: QWERTY row (no Enter in the list, Enter will be placed after ])
    q_row = ["Tab", "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]"]
    col = 0
    for key in q_row:
        if key == "Tab":
            create_key_button_grid(kb_frame, key, 2, col, columnspan=2, width=8, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col += 2
        else:
            create_key_button_grid(kb_frame, key, 2, col, width=6, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col += 1
    # Double-height Enter key, immediately after ]
    create_key_button_grid(kb_frame, "Enter", 2, col, rowspan=2, width=9, key_id=SPECIAL_KEYS.get("enter", "Enter"))

    # Row 3: ASDF row (add # after ')
    asdf_row = ["Caps Lock", "A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'", "#"]
    col_asdf = 0
    for key in asdf_row:
        if key == "Caps Lock":
            create_key_button_grid(kb_frame, key, 3, col_asdf, columnspan=2, width=9, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col_asdf += 2
        else:
            # Skip the Enter column (which is now col from above)
            if col_asdf == col:
                col_asdf += 1
            create_key_button_grid(kb_frame, key, 3, col_asdf, width=6, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col_asdf += 1

    # Row 4: ZXCV row (Right Shift is 3 keys wide at the end)
    zxcv_row = ["Shift", "Z", "X", "C", "V", "B", "N", "M", ",", ".", "/"]
    col = 0
    for key in zxcv_row:
        if key == "Shift":
            create_key_button_grid(kb_frame, key, 4, col, columnspan=2, width=11, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col += 2
        else:
            create_key_button_grid(kb_frame, key, 4, col, width=6, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col += 1
    # Right Shift (after /), 3 keys wide
    create_key_button_grid(kb_frame, "R-Shift", 4, col, columnspan=3, width=17, key_id=SPECIAL_KEYS.get("r-shift", "R-Shift"))

    # Row 5: Ctrl/Win/Alt/Space (no arrow block here)
    bottom_row = ["Ctrl", "Fn", "Win", "Alt", "Space", "AltGr"]
    col = 0
    for key in bottom_row:
        if key == "Space":
            create_key_button_grid(kb_frame, key, 5, col, columnspan=5, width=30, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col += 5
        else:
            create_key_button_grid(kb_frame, key, 5, col, width=6, key_id=SPECIAL_KEYS.get(key.lower(), key))
            col += 1

    # --- Arrow block and right ctrl, page up/down (separate block, not part of bottom_row) ---
    arrow_start_col = col
    create_key_button_grid(kb_frame, "R-Ctrl", 5, arrow_start_col, width=6, key_id=SPECIAL_KEYS.get("r-ctrl", "R-Ctrl"))
    create_key_button_grid(kb_frame, "PageUp", 5, arrow_start_col + 1, width=6, key_id="page up")
    create_key_button_grid(kb_frame, "↑", 5, arrow_start_col + 2, width=6, key_id="up")
    create_key_button_grid(kb_frame, "PageDown", 5, arrow_start_col + 3, width=6, key_id="page down")
    create_key_button_grid(kb_frame, "←", 6, arrow_start_col + 1, width=6, key_id="left")
    create_key_button_grid(kb_frame, "↓", 6, arrow_start_col + 2, width=6, key_id="down")
    create_key_button_grid(kb_frame, "→", 6, arrow_start_col + 3, width=6, key_id="right")

    # --- Find the column of the "End" key in the function row ---
    end_col = None
    for child in kb_frame.grid_slaves(row=0):
        info = child.grid_info()
        if child.cget("text").lower() == "end":
            end_col = info['column']
            break

    if end_col is None:
        end_col = 16  # fallback if not found

    NUMPAD_START_COL = end_col

    # --- Numpad Layout (starts under End key) ---
    NUMPAD_GRID = [
        ["NumLock", "/", "*", "-"],
        ["7", "8", "9", "+"],
        ["4", "5", "6", "+"],
        ["1", "2", "3", "Enter"],
        ["0", "0", ".", None]
    ]
    for r, row in enumerate(NUMPAD_GRID):
        for c2, key in enumerate(row):
            grid_col = NUMPAD_START_COL + c2
            grid_kwargs = dict(row=r+1, column=grid_col)
            if key is None:
                continue
            if key == "0" and r == 4 and c2 == 0:
                grid_kwargs.update(columnspan=2)
                btn = create_key_button_grid(kb_frame, "0", **grid_kwargs, width=12, key_id="num 0")
                numpad_grid_options[btn] = grid_kwargs
            elif key == "0":
                continue
            elif key == "+" and r == 1:
                grid_kwargs.update(rowspan=2)
                btn = create_key_button_grid(kb_frame, "+", **grid_kwargs, width=6, key_id="num +")
                numpad_grid_options[btn] = grid_kwargs
            elif key == "+":
                continue
            elif key == "Enter" and r == 3:
                grid_kwargs.update(rowspan=2)
                btn = create_key_button_grid(kb_frame, "Enter", **grid_kwargs, width=6, key_id="num enter")
                numpad_grid_options[btn] = grid_kwargs
            elif key == "Enter":
                continue
            else:
                btn = create_key_button_grid(kb_frame, key, **grid_kwargs, width=6, key_id="num " + key.lower())
                numpad_grid_options[btn] = grid_kwargs

    def toggle_numpad():
        for widget in numpad_grid_options:
            if not show_numpad_var.get():
                widget.grid_remove()
            else:
                widget.grid(**numpad_grid_options[widget])
        keyboard_test_window.update_idletasks()
        keyboard_scroll.canvas.configure(width=kb_frame.winfo_reqwidth() + 8,
                                         height=kb_frame.winfo_reqheight() + 8)
        center_window_to_content(keyboard_test_window,
                                 min_width=round(800 * scale),
                                 min_height=round(480 * scale))

    # Configure columns and rows for even sizing
    for i in range(NUMPAD_START_COL + 4):
        kb_frame.grid_columnconfigure(i, weight=1)
    for i in range(7):
        kb_frame.grid_rowconfigure(i, weight=1)

    # Hide numpad keys by default
    owned_after_ids.append(keyboard_test_window.after(0, toggle_numpad))

    coverage_text = tk.StringVar(value='Press each applicable key. Check Fn functions manually.')
    tk.Label(container, autostyle=False, textvariable=coverage_text, wraplength=650,
             bg='white').grid(row=2, column=0, sticky='ew')

    def coverage_details():
        required = {key for key in key_widgets if key != 'fn'
                    and (show_numpad_var.get() or not key.startswith('num '))}
        return {'layout': 'Displayed UK/ISO logical keys',
                'numpad_included': show_numpad_var.get(),
                'required_keys': sorted(required),
                'observed_keys': sorted(observed_keys & required),
                'missing_keys': sorted(required - observed_keys),
                'manual_only': ['Fn', 'firmware/multimedia functions']}

    def note_key(logical_key, widget):
        if (not keyboard_test_window or not keyboard_test_window.winfo_exists()
                or not widget.winfo_exists()):
            return
        observed_keys.add(logical_key)
        widget.config(bg=HIGHLIGHT_COLORS['hit'])
        detail = coverage_details()
        coverage_text.set('{} / {} keys observed; {} missing. '
                          'Finish to review the full missing-key list.'.format(
                              len(detail['observed_keys']), len(detail['required_keys']),
                              len(detail['missing_keys'])))

    # --- Keyboard event handling and cleanup (unchanged) ---
    def on_press(event):
        try:
            if not event.name:
                return
            key_name = event.name.lower()
            logical_key = SPECIAL_KEYS.get(key_name, key_name)
            if event.is_keypad:
                logical_key = "num " + logical_key
            widget = key_widgets.get(logical_key)
            if widget:
                if not stopped.is_set():
                    key_events.put_nowait((logical_key, True))
        except Exception as e:
            print(f"Error on press: {e}")
            traceback.print_exc()

    def on_release(event):
        try:
            if not event.name:
                return
            key_name = event.name.lower()
            logical_key = SPECIAL_KEYS.get(key_name, key_name)
            if event.is_keypad:
                logical_key = "num " + logical_key
            widget = key_widgets.get(logical_key)
            if widget:
                if not stopped.is_set():
                    key_events.put_nowait((logical_key, False))
        except Exception as e:
            print(f"Error on release: {e}")
            traceback.print_exc()

    def block_tab(event):
        return "break"
    keyboard_test_window.bind("<Tab>", block_tab)
    keyboard_test_window.bind("<Shift-Tab>", block_tab)

    def poll_keys():
        poll_id[0] = None
        if stopped.is_set():
            return
        for _ in range(500):
            try:
                logical_key, pressed = key_events.get_nowait()
            except queue.Empty:
                break
            widget = key_widgets.get(logical_key)
            if widget is not None and widget.winfo_exists():
                if pressed:
                    widget.config(bg=PRESSED_COLOR)
                else:
                    note_key(logical_key, widget)
        poll_id[0] = keyboard_test_window.after(25, poll_keys)

    def cleanup_keyboard_hooks():
        global press_hook_id, release_hook_id
        stopped.set()
        if poll_id[0] is not None:
            keyboard_test_window.after_cancel(poll_id[0])
            poll_id[0] = None
        for identifier in owned_after_ids:
            keyboard_test_window.after_cancel(identifier)
        owned_after_ids.clear()
        try:
            if press_hook_id:
                keyboard.unhook(press_hook_id)
                press_hook_id = None
        except Exception:
            pass
        try:
            if release_hook_id:
                keyboard.unhook(release_hook_id)
                release_hook_id = None
        except Exception:
            pass

    def show_result_prompt():
        prompt = tk.Toplevel(root)
        prompt.title("Keyboard Test Result")
        prompt.resizable(True, True)
        details = coverage_details()
        review_scroll = ScrollableFrame(prompt, height=220)
        review_scroll.pack(fill='both', expand=True, padx=10, pady=8)
        summary = tk.Label(review_scroll.content, text='Observed {} / {} keys. Missing: {}\n'
                 'Confirm the physical layout and Fn functions manually.\n'
                 'If passing incomplete capture, explain your manual check.'
                 .format(len(details['observed_keys']),
                         len(details['required_keys']),
                         ', '.join(details['missing_keys']) or 'none'),
                 wraplength=420, justify='left')
        summary.pack(fill='x', pady=10)
        summary.bind('<Configure>', lambda event: summary.config(
            wraplength=max(120, event.width - 16)))
        confirmation = tk.Entry(review_scroll.content, width=36)
        confirmation.pack(fill='x', padx=12, pady=6)
        btn_frame = tk.Frame(prompt)
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1, uniform="keyboard_result")
        def on_response(result):
            reason = confirmation.get().strip()
            if result == 'pass' and details['missing_keys'] and not reason:
                messagebox.showerror('Incomplete key capture',
                                     'Record what you checked manually, or '
                                     'choose Fail, Unavailable or Cancel.')
                return
            if len(reason) > 1000:
                messagebox.showerror('Confirmation too long',
                                     'Use up to 1000 characters.')
                return
            details['manual_confirmation'] = reason
            record_coverage(test_results, 'keyboard',
                            'Logical-key events on the displayed layout; '
                            'manual confirmation and missing keys recorded.',
                            details)
            finalize(result)
            prompt.destroy()
        from ttkbootstrap import ttk
        yes_button = ttk.Button(btn_frame, text="Yes", style="success.TButton", command=lambda: on_response("pass"))
        yes_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(
            btn_frame,
            text="Retry",
            style="info.TButton",
            command=lambda: [
                prompt.destroy(),
                run_keyboard_test(
                    root,
                    test_results,
                    test_labels,
                    tests_window,
                    completion_event=completion_event,
                ),
            ],
        ).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(btn_frame, text="No", style="danger.TButton", command=lambda: on_response("fail")).grid(row=0, column=2, sticky="ew", padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=lambda: on_response("cancelled")).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Button(btn_frame, text="Unavailable", command=lambda: on_response("unavailable")).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        prompt.protocol("WM_DELETE_WINDOW", lambda: on_response("cancelled"))
        if tests_window and hasattr(tests_window, 'register_cancel'):
            tests_window.register_cancel(lambda: on_response('cancelled'))
        center_window_to_content(prompt, min_width=360, min_height=150)
        yes_button.focus_set()

    def on_close(cancelled=True):
        global keyboard_test_window
        cleanup_keyboard_hooks()
        if keyboard_test_window:
            keyboard_test_window.destroy()
            keyboard_test_window = None
        if cancelled:
            record_coverage(test_results, 'keyboard',
                            'Cancelled keyboard capture; incomplete coverage.',
                            coverage_details())
            finalize('cancelled')
        else:
            show_result_prompt()

    tk.Button(container, text='Finish and review',
              command=lambda: on_close(False)).grid(row=3, column=0, sticky='ew')
    tk.Button(container, text='Cancel', command=on_close).grid(
        row=4, column=0, sticky='ew')

    try:
        press_hook_id = keyboard.on_press(on_press, suppress=True)
        release_hook_id = keyboard.on_release(on_release)
    except Exception:
        cleanup_keyboard_hooks()
        keyboard_test_window.destroy()
        keyboard_test_window = None
        finalize('error')
        return

    keyboard_test_window.protocol("WM_DELETE_WINDOW", on_close)
    def destroyed(event):
        if event.widget == keyboard_test_window and not stopped.is_set():
            on_close()
    keyboard_test_window.bind('<Destroy>', destroyed, add='+')
    if tests_window and hasattr(tests_window, 'register_cancel'):
        tests_window.register_cancel(on_close)
    keyboard_test_window.focus_set()
    keyboard_test_window.attributes("-topmost", 1)
    owned_after_ids.append(keyboard_test_window.after(100, lambda: keyboard_test_window.attributes("-topmost", 0)))
    poll_id[0] = keyboard_test_window.after(0, poll_keys)
