# hardware_tests/speaker.py
import tkinter as tk
import winsound
import os
import sys
import threading
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
        recording = sd.rec(
            frames,
            samplerate=MIC_TEST_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocking=False,
        )
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
    return passed, peak, rms, recording.copy()

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
    auto_recording = None

    if sd is not None and np is not None:
        try:
            auto_passed, peak_level, rms_level, auto_recording = perform_auto_microphone_check(audio_path)
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
    result_window.geometry("420x360")
    result_window.resizable(False, False)

    manual_controls_available = sd is not None and np is not None
    from ttkbootstrap import ttk

    manual_state = {
        "stream": None,
        "chunks": [],
        "audio": None,
        "play_thread": None,
    }

    status_var = tk.StringVar()
    status_var.set("Ready for manual verification." if manual_controls_available else "Microphone controls unavailable.")

    def stop_manual_stream():
        stream = manual_state.get("stream")
        if stream is None:
            return
        manual_state["stream"] = None
        try:
            stream.stop()
        except Exception as exc:  # pragma: no cover - hardware dependent
            log_event(f"Error stopping manual recording stream: {exc}")
        try:
            stream.close()
        except Exception as exc:  # pragma: no cover - hardware dependent
            log_event(f"Error closing manual recording stream: {exc}")

    def ensure_audio_stop():
        if sd is None:
            return
        try:  # pragma: no cover - hardware dependent
            sd.stop()
        except Exception as exc:
            log_event(f"Error stopping audio playback: {exc}")

    def play_audio(data, source_label, status_callback=None):
        if sd is None:
            tk.messagebox.showerror("Audio Error", "sounddevice module not available for playback.")
            return
        if data is None or getattr(data, "size", 0) == 0:
            tk.messagebox.showwarning("Playback", f"No {source_label} audio available to play.")
            return

        ensure_audio_stop()

        if status_callback is not None:
            status_callback(f"Playing {source_label}...")

        def _runner():
            try:
                sd.play(data, MIC_TEST_SAMPLE_RATE)
                sd.wait()
            except Exception as exc:  # pragma: no cover - hardware dependent
                log_event(f"Error during {source_label} playback: {exc}")
                root.after(
                    0,
                    lambda err=exc: tk.messagebox.showerror(
                        "Audio Error", f"Failed to play {source_label} audio.\n{err}"
                    ),
                )
                if status_callback is not None:
                    root.after(0, lambda: status_callback(f"Playback failed for {source_label}."))
            else:
                if status_callback is not None:
                    root.after(0, lambda: status_callback(f"Finished playing {source_label}."))

        thread = threading.Thread(target=_runner, daemon=True)
        manual_state["play_thread"] = thread
        thread.start()

    def manual_callback(indata, frames, time_info, status):  # pragma: no cover - hardware dependent
        if status:
            log_event(f"Manual microphone recording status: {status}")
        manual_state["chunks"].append(indata.copy())

    def start_manual_record():
        if not manual_controls_available:
            tk.messagebox.showerror("Microphone", "Manual recording requires numpy and sounddevice.")
            return
        if manual_state.get("stream") is not None:
            return
        ensure_audio_stop()
        manual_state["chunks"] = []
        manual_state["audio"] = None
        try:
            stream = sd.InputStream(
                samplerate=MIC_TEST_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                callback=manual_callback,
            )
            stream.start()
            manual_state["stream"] = stream
            status_var.set("Recording... Press Stop when finished.")
            log_event("Manual microphone recording started.")
        except Exception as exc:  # pragma: no cover - hardware dependent
            log_event(f"Failed to start manual recording: {exc}")
            tk.messagebox.showerror("Microphone", f"Unable to start recording.\n{exc}")

    def stop_manual_record():
        if manual_state.get("stream") is None:
            return
        stream = manual_state.get("stream")
        manual_state["stream"] = None
        try:
            stream.stop()
        except Exception as exc:  # pragma: no cover - hardware dependent
            log_event(f"Error stopping manual recording stream: {exc}")
        try:
            stream.close()
        except Exception as exc:  # pragma: no cover - hardware dependent
            log_event(f"Error closing manual recording stream: {exc}")

        if manual_state["chunks"]:
            try:
                manual_state["audio"] = np.concatenate(manual_state["chunks"], axis=0)
                duration = manual_state["audio"].shape[0] / MIC_TEST_SAMPLE_RATE
                status_var.set(f"Recorded {duration:.1f}s of audio.")
                log_event(f"Manual microphone recording captured ({duration:.2f}s).")
            except Exception as exc:  # pragma: no cover - hardware dependent
                manual_state["audio"] = None
                status_var.set("Recording captured but could not be processed.")
                log_event(f"Failed to process manual recording: {exc}")
        else:
            status_var.set("No audio captured. Try recording again.")

    def play_manual_recording():
        play_audio(manual_state.get("audio"), "manual recording", status_var.set)

    def play_auto_recording():
        play_audio(auto_recording, "automatic recording", status_var.set)

    def handle_response(result):
        stop_manual_stream()
        ensure_audio_stop()
        finalize(result)
        result_window.destroy()

    def retry_test():
        stop_manual_stream()
        ensure_audio_stop()
        result_window.destroy()
        run_speaker_test(
            root,
            test_results,
            test_labels,
            tests_window,
            completion_event=completion_event,
        )

    if auto_message:
        tk.Label(
            result_window,
            text=auto_message,
            font=("Arial", 10),
            wraplength=380,
            justify="center",
        ).pack(padx=10, pady=(10, 5))

    if auto_recording is not None:
        auto_frame = tk.LabelFrame(result_window, text="Automatic recording")
        auto_frame.pack(fill="x", padx=12, pady=(5, 5))
        tk.Label(
            auto_frame,
            text="Listen to the captured microphone audio before deciding.",
            anchor="w",
            justify="left",
            wraplength=360,
        ).pack(padx=10, pady=(6, 2), anchor="w")
        ttk.Button(
            auto_frame,
            text="Play Automatic Capture",
            width=26,
            style="secondary.TButton",
            command=play_auto_recording,
        ).pack(padx=10, pady=(0, 8))

    manual_frame = tk.LabelFrame(result_window, text="Manual microphone test")
    manual_frame.pack(fill="x", padx=12, pady=(0, 5))

    if manual_controls_available:
        tk.Label(
            manual_frame,
            text="Use the controls below to capture a new recording if needed.",
            anchor="w",
            justify="left",
            wraplength=360,
        ).pack(padx=10, pady=(6, 2), anchor="w")

        controls = tk.Frame(manual_frame)
        controls.pack(pady=(0, 6))

        ttk.Button(controls, text="Record", width=12, style="info.TButton", command=start_manual_record).pack(
            side="left", padx=5
        )
        ttk.Button(controls, text="Stop", width=12, style="warning.TButton", command=stop_manual_record).pack(
            side="left", padx=5
        )
        ttk.Button(controls, text="Play", width=12, style="secondary.TButton", command=play_manual_recording).pack(
            side="left", padx=5
        )
    else:
        tk.Label(
            manual_frame,
            text="Manual microphone controls require numpy and sounddevice.",
            anchor="w",
            justify="left",
            wraplength=360,
        ).pack(padx=10, pady=8, anchor="w")

    tk.Label(manual_frame, textvariable=status_var, wraplength=360, justify="left", anchor="w").pack(
        padx=10, pady=(0, 8), anchor="w"
    )

    tk.Label(result_window, text="Did the speaker test pass?", font=("Arial", 11)).pack(pady=(8, 5))
    frame = tk.Frame(result_window)
    frame.pack(pady=(0, 10))

    ttk.Button(frame, text="Yes", width=10, style="success.TButton", command=lambda: handle_response("pass")).pack(
        side="left", padx=5
    )
    ttk.Button(
        frame,
        text="Retry",
        width=10,
        style="info.TButton",
        command=retry_test,
    ).pack(side="left", padx=5)
    ttk.Button(frame, text="No", width=10, style="danger.TButton", command=lambda: handle_response("fail")).pack(
        side="left", padx=5
    )

    result_window.protocol("WM_DELETE_WINDOW", lambda: handle_response("fail"))
