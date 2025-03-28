# ui/keyboard_test.py
import tkinter as tk
import keyboard

SPECIAL_KEYS = {
    "caps lock": "caps lock", "windows": "win", "win": "win", "left windows": "win",
    "right shift": "r-shift", "right ctrl": "r-ctrl", "alt gr": "altgr", "altgr": "altgr",
    "print screen": "prtscr", "prtsc": "prtscr", "prt sc": "prtscr",
    "page up": "page up", "page down": "page down",
    "left": "←", "right": "→", "up": "↑", "down": "↓",
}

HIGHLIGHT_COLORS = {
    "default": "lightgrey",
    "pressed": "orange",
    "hit": "lightgreen"
}

keyboard_test_window = None
press_hook_id = None
release_hook_id = None

def run_keyboard_test(root, test_results, test_labels):
    global keyboard_test_window, press_hook_id, release_hook_id

    try:
        if keyboard_test_window and keyboard_test_window.winfo_exists():
            keyboard_test_window.lift()
            keyboard_test_window.focus_force()
            return
    except:
        keyboard_test_window = None

    keyboard_test_window = tk.Toplevel()
    keyboard_test_window.title("Keyboard Test")
    keyboard_test_window.geometry("1100x550")
    keyboard_test_window.configure(bg="white")

    PRESSED_COLOR = HIGHLIGHT_COLORS["pressed"]
    HIT_COLOR = HIGHLIGHT_COLORS["hit"]
    DEFAULT_COLOR = HIGHLIGHT_COLORS["default"]
    FN_COLOR = "#999999"

    FN_F_KEYS = ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"]

    KEY_LAYOUT = [
        ["Esc", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12", "Home", "End", "Insert", "Delete"],
        ["`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "Backspace"],
        ["Tab", "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]"],
        ["Caps Lock", "A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'", "#", "Enter"],
        ["Shift", "\\", "Z", "X", "C", "V", "B", "N", "M", ",", ".", "/", "R-Shift"],
        ["Ctrl", "Fn", "Win", "Alt", "Space", "AltGr", "PrtScr", "R-Ctrl"]
    ]

    ARROW_KEYS_LAYOUT = [["Page Up", "↑", "Page Down"], ["←", "↓", "→"]]

    NUMPAD_LAYOUT = [
        ["NumLock", "/", "*", "-"],
        ["7", "8", "9", "+"],
        ["4", "5", "6"],
        ["1", "2", "3", "Enter"],
        ["0", "."]
    ]

    key_widgets = {}

    container = tk.Frame(keyboard_test_window, bg="white")
    container.pack(padx=10, pady=10, fill="both", expand=True, side="left", anchor="n")

    def create_key_button(frame, key, width=6, key_id=None):
        color = FN_COLOR if key.lower() == "fn" else DEFAULT_COLOR
        btn = tk.Label(frame, text=key, width=width, height=2, relief="raised", borderwidth=1,
                       bg=color, font=("Arial", 9, "bold"))
        btn.pack(side="left", padx=2)
        key_widgets[(key_id or key).lower()] = btn

    for row in KEY_LAYOUT:
        row_frame = tk.Frame(container, bg="white")
        row_frame.pack(pady=2, anchor="w")
        for key in row:
            width = 18 if key == "Space" else 10 if key in ["Backspace", "Caps Lock", "Enter", "R-Shift"] else 6
            create_key_button(row_frame, key, width, SPECIAL_KEYS.get(key.lower(), key))

    arrow_frame = tk.Frame(container, bg="white")
    arrow_frame.pack(pady=(6, 0), anchor="w")
    for row in ARROW_KEYS_LAYOUT:
        arrow_row = tk.Frame(arrow_frame, bg="white")
        arrow_row.pack(anchor="w")
        for key in row:
            create_key_button(arrow_row, key, key_id=SPECIAL_KEYS.get(key.lower(), key))

    numpad_frame = tk.Frame(keyboard_test_window, bg="white")
    numpad_frame.pack(side="right", anchor="n", padx=20)

    for row in NUMPAD_LAYOUT:
        row_frame = tk.Frame(numpad_frame, bg="white")
        row_frame.pack(pady=2, anchor="e")
        for key in row:
            create_key_button(row_frame, key, key_id="num " + key)

    show_numpad_var = tk.BooleanVar(value=True)

    def toggle_numpad():
        if show_numpad_var.get():
            numpad_frame.pack(side="right", anchor="n", padx=20)
        else:
            numpad_frame.pack_forget()

    toggle_checkbox = tk.Checkbutton(container, text="Show Numpad", variable=show_numpad_var,
                                     command=toggle_numpad, bg="white", takefocus=False)
    toggle_checkbox.pack(pady=5, anchor="w")

    def on_press(event):
        try:
            if not event.name:
                return
            key_name = event.name.lower()

            if key_name in ["b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m"]:
                for fkey in FN_F_KEYS:
                    if keyboard.is_pressed(fkey):
                        return

            logical_key = SPECIAL_KEYS.get(key_name, key_name)
            if event.is_keypad:
                logical_key = "num " + logical_key

            widget = key_widgets.get(logical_key)
            if widget:
                widget.config(bg=PRESSED_COLOR)
        except Exception as e:
            print(f"Error on press: {e}")

    def on_release(event):
        try:
            if not event.name:
                return
            key_name = event.name.lower()

            if key_name in ["b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m"]:
                for fkey in FN_F_KEYS:
                    if keyboard.is_pressed(fkey):
                        return

            logical_key = SPECIAL_KEYS.get(key_name, key_name)
            if event.is_keypad:
                logical_key = "num " + logical_key

            widget = key_widgets.get(logical_key)
            if widget:
                widget.config(bg=HIT_COLOR)
        except Exception as e:
            print(f"Error on release: {e}")

    press_hook_id = keyboard.on_press(on_press, suppress=True)
    release_hook_id = keyboard.on_release(on_release)

    def cleanup_keyboard_hooks():
        global press_hook_id, release_hook_id
        try:
            if press_hook_id:
                keyboard.unhook(press_hook_id)
                press_hook_id = None
        except KeyError:
            pass
        try:
            if release_hook_id:
                keyboard.unhook(release_hook_id)
                release_hook_id = None
        except KeyError:
            pass

    def show_result_prompt():
        prompt = tk.Toplevel()
        prompt.title("Keyboard Test Result")
        prompt.geometry("300x130")
        prompt.resizable(False, False)

        tk.Label(prompt, text="Did the keyboard test pass?", font=("Arial", 11)).pack(pady=10)
        btn_frame = tk.Frame(prompt)
        btn_frame.pack()

        def on_response(result):
            test_results["keyboard"] = result
            if "keyboard_label" in test_labels:
                test_labels["keyboard_label"].config(text="✅" if result == "pass" else "❌")
            prompt.destroy()

        tk.Button(btn_frame, text="Yes", width=10, bg="lightgreen", command=lambda: on_response("pass")).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Retry", width=10, bg="lightblue", command=lambda: [prompt.destroy(), run_keyboard_test(root, test_results, test_labels)]).pack(side="left", padx=5)
        tk.Button(btn_frame, text="No", width=10, bg="tomato", command=lambda: on_response("fail")).pack(side="left", padx=5)

        prompt.protocol("WM_DELETE_WINDOW", prompt.destroy)

    def on_close():
        global keyboard_test_window
        cleanup_keyboard_hooks()
        if keyboard_test_window:
            keyboard_test_window.destroy()
            keyboard_test_window = None
        show_result_prompt()

    keyboard_test_window.protocol("WM_DELETE_WINDOW", on_close)
    keyboard_test_window.focus_set()
    keyboard_test_window.attributes("-topmost", 1)
    keyboard_test_window.after(100, lambda: keyboard_test_window.attributes("-topmost", 0))