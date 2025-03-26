# hardware_tests/speaker.py
import tkinter as tk
import winsound
from pathlib import Path
import os
from utils.helpers import log_event

def run_speaker_test(root, test_results, test_labels):
    audio_path = Path(__file__).resolve().parent.parent / "assets" / "AudioCheck.wav"
    if not audio_path.exists():
        tk.messagebox.showerror("File Not Found", "AudioCheck.wav not found in script directory.")
        return

    try:
        audio_path = Path(__file__).resolve().parent.parent / "assets" / "AudioCheck.wav"
        winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
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
        result_window.destroy()

    tk.Button(frame, text="Yes", width=10, bg="lightgreen", command=lambda: handle_response("pass")).pack(side="left", padx=5)
    tk.Button(frame, text="Retry", width=10, bg="lightblue", command=lambda: [result_window.destroy(), run_speaker_test(root, test_results, test_labels)]).pack(side="left", padx=5)
    tk.Button(frame, text="No", width=10, bg="tomato", command=lambda: handle_response("fail")).pack(side="left", padx=5)

    result_window.protocol("WM_DELETE_WINDOW", result_window.destroy)