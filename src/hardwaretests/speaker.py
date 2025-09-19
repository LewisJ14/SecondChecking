# hardware_tests/speaker.py
import tkinter as tk
import winsound
import os
import sys
from utils.helpers import log_event

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional dependency
    np = None

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - optional dependency
    sd = None


MIC_TEST_DURATION = 3.5
MIC_TEST_SAMPLE_RATE = 44100
MIC_TEST_PEAK_THRESHOLD = 0.02
MIC_TEST_RMS_THRESHOLD = 0.005


class MicrophoneTestError(Exception):
    """Raised when the automatic microphone verification cannot be completed."""


class AudioPlaybackError(Exception):
    """Raised when the speaker audio cannot be played during the automatic check."""


def perform_auto_microphone_check(audio_path):
    """Record microphone input while playing the speaker test audio."""

    if sd is None or np is None:
        missing = []
        if sd is None:
            missing.append("sounddevice")
        if np is None:
            missing.append("numpy")
        raise MicrophoneTestError(
            f"Automatic microphone check unavailable (missing {' and '.join(missing)} module(s))."
        )

    try:
        frames = int(MIC_TEST_DURATION * MIC_TEST_SAMPLE_RATE)
        recording = sd.rec(frames, samplerate=MIC_TEST_SAMPLE_RATE, channels=1, blocking=False)
    except Exception as exc:  # pragma: no cover - hardware dependent
        raise MicrophoneTestError(f"Unable to access the microphone: {exc}") from exc

    try:
        winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
    except Exception as exc:  # pragma: no cover - hardware dependent
        sd.stop()
        raise AudioPlaybackError(exc) from exc

    try:
        sd.wait()
    except Exception as exc:  # pragma: no cover - hardware dependent
        raise MicrophoneTestError(f"Microphone recording failed: {exc}") from exc

    if recording is None or recording.size == 0:
        raise MicrophoneTestError("Microphone returned no data during recording.")

    peak = float(np.max(np.abs(recording)))
    rms = float(np.sqrt(np.mean(np.square(recording))))
    passed = peak >= MIC_TEST_PEAK_THRESHOLD or rms >= MIC_TEST_RMS_THRESHOLD
    return passed, peak, rms

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # <-- Go up one level

def run_speaker_test(root, test_results, test_labels, tests_window=None, completion_event=None):
    audio_path = os.path.join(base_path, "assets", "AudioCheck.wav")
    if not os.path.exists(audio_path):
        tk.messagebox.showerror("File Not Found", "AudioCheck.wav not found in assets directory.")
        if completion_event and not completion_event.is_set():
            test_results["speaker"] = "fail"
            test_results["microphone"] = "fail"
            completion_event.set()
        return

    if "microphone" not in test_results:
        test_results["microphone"] = "Not Run"

    def finalize(result=None):
        if result is not None:
            test_results["speaker"] = result
            test_results["microphone"] = result
            if "speaker_label" in test_labels:
                test_labels["speaker_label"].config(text="✅" if result == "pass" else "❌")
            if "microphone_label" in test_labels:
                test_labels["microphone_label"].config(text="✅" if result == "pass" else "❌")
            if tests_window and hasattr(tests_window, "update_icon"):
                tests_window.update_icon("speaker")
                tests_window.update_icon("microphone")
        if completion_event and not completion_event.is_set():
            completion_event.set()

    auto_attempted = False
    auto_passed = False
    auto_message = None
    peak_level = None
    rms_level = None
    playback_performed = False

    if sd is not None and np is not None:
        try:
            auto_passed, peak_level, rms_level = perform_auto_microphone_check(audio_path)
            auto_attempted = True
            playback_performed = True
        except AudioPlaybackError as exc:
            log_event(f"Error playing audio during automatic speaker test: {exc}")
            tk.messagebox.showerror("Audio Error", f"Failed to play audio:\n{exc}")
            return
        except MicrophoneTestError as exc:
            auto_message = str(exc)
            log_event(f"Automatic microphone test unavailable: {exc}")
    else:
        missing = []
        if sd is None:
            missing.append("sounddevice")
        if np is None:
            missing.append("numpy")
        auto_message = (
            "Automatic microphone check unavailable (missing "
            + " and ".join(missing)
            + " module(s)). Please confirm manually."
        )
        log_event(auto_message)

    if auto_attempted and auto_passed:
        detail = "" if peak_level is None else f"\nPeak level: {peak_level:.3f}\nRMS level: {rms_level:.3f}"
        tk.messagebox.showinfo("Speaker Test", "Automatic speaker and microphone test passed." + detail)
        log_event(
            "Speaker test passed automatically"
            + (f" (peak={peak_level:.4f}, rms={rms_level:.4f})" if peak_level is not None else "")
        )
        finalize("pass")
        return

    if not playback_performed:
        try:
            winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
        except RuntimeError as e:
            log_event(f"Speaker hardware error: {e}")
            tk.messagebox.showerror("Audio Error", "No audio device found or audio playback failed.")
            finalize("fail")
            return
        except FileNotFoundError as e:
            log_event(f"Audio file not found: {e}")
            tk.messagebox.showerror("Audio Error", "Audio file missing.")
            finalize("fail")
            return
        except Exception as e:
            log_event(f"Error playing audio: {e}")
            tk.messagebox.showerror("Audio Error", f"Failed to play audio:\n{e}")
            finalize("fail")
            return

    if auto_attempted and not auto_passed:
        auto_message = "Automatic microphone check did not detect the speaker output. Please complete the manual verification."
        if peak_level is not None and rms_level is not None:
            log_event(f"Automatic speaker test failed (peak={peak_level:.4f}, rms={rms_level:.4f}).")
        else:
            log_event("Automatic speaker test failed without level data.")
    elif auto_message is None:
        auto_message = "Automatic microphone check unavailable. Please confirm manually."

    if test_results.get("speaker") != "pass":
        test_results["speaker"] = "fail"
        test_results["microphone"] = "fail"
        if "speaker_label" in test_labels:
            test_labels["speaker_label"].config(text="❌")
        if "microphone_label" in test_labels:
            test_labels["microphone_label"].config(text="❌")
        if tests_window and hasattr(tests_window, "update_icon"):
            tests_window.update_icon("speaker")
            tests_window.update_icon("microphone")

    result_window = tk.Toplevel(root)
    result_window.title("Speaker Test Result")
    result_window.geometry("360x200")
    result_window.resizable(False, False)

    if auto_message:
        tk.Label(
            result_window,
            text=auto_message,
            font=("Arial", 10),
            wraplength=320,
            justify="center",
        ).pack(padx=10, pady=(10, 5))

    tk.Label(result_window, text="Did the speaker test pass?", font=("Arial", 11)).pack(pady=5)
    frame = tk.Frame(result_window)
    frame.pack(pady=(0, 10))

    def handle_response(result):
        finalize(result)
        result_window.destroy()

    from ttkbootstrap import ttk

    ttk.Button(frame, text="Yes", width=10, style="success.TButton", command=lambda: handle_response("pass")).pack(
        side="left", padx=5
    )
    ttk.Button(
        frame,
        text="Retry",
        width=10,
        style="info.TButton",
        command=lambda: [
            result_window.destroy(),
            run_speaker_test(
                root,
                test_results,
                test_labels,
                tests_window,
                completion_event=completion_event,
            ),
        ],
    ).pack(side="left", padx=5)
    ttk.Button(frame, text="No", width=10, style="danger.TButton", command=lambda: handle_response("fail")).pack(
        side="left", padx=5
    )

    result_window.protocol("WM_DELETE_WINDOW", lambda: handle_response("fail"))
