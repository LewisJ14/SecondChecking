# hardware_tests/speaker.py
import tkinter as tk
import winsound
from pathlib import Path
import os
import sys
from utils.helpers import log_event

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # <-- Go up one level

def run_speaker_test(root, test_results, test_labels, tests_window=None):
    audio_path = os.path.join(base_path, "assets", "AudioCheck.wav")
    if not os.path.exists(audio_path):
        tk.messagebox.showerror("File Not Found", "AudioCheck.wav not found in assets directory.")
        return

    try:
        winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
    except RuntimeError as e:
        log_event(f"Speaker hardware error: {e}")
        tk.messagebox.showerror("Audio Error", "No audio device found or audio playback failed.")
        return
    except FileNotFoundError as e:
        log_event(f"Audio file not found: {e}")
        tk.messagebox.showerror("Audio Error", "Audio file missing.")
        return
    except Exception as e:
        log_event(f"Error playing audio: {e}")
        tk.messagebox.showerror("Audio Error", f"Failed to play audio:\n{e}")
        return

    result_window = tk.Toplevel(root)
    result_window.title("Speaker Test Result")
    result_window.geometry("300x130")
    result_window.resizable(False, False)

    tk.Label(result_window, text="Did the speaker test pass?", font=("Arial", 11)).pack(pady=10)
    frame = tk.Frame(result_window)
    frame.pack()

    def handle_response(result):
        test_results["speaker"] = result
        if "speaker_label" in test_labels:
            test_labels["speaker_label"].config(text="✅" if result == "pass" else "❌")
        if tests_window and hasattr(tests_window, "update_icon"):
            tests_window.update_icon("speaker")
        result_window.destroy()

    from ttkbootstrap import ttk
    ttk.Button(frame, text="Yes", width=10, style="success.TButton", command=lambda: handle_response("pass")).pack(side="left", padx=5)
    ttk.Button(frame, text="Retry", width=10, style="info.TButton", command=lambda: [result_window.destroy(), run_speaker_test(root, test_results, test_labels, tests_window)]).pack(side="left", padx=5)
    ttk.Button(frame, text="No", width=10, style="danger.TButton", command=lambda: handle_response("fail")).pack(side="left", padx=5)

    result_window.protocol("WM_DELETE_WINDOW", result_window.destroy)