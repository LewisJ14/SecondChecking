"""Preview a fresh Windows scan and save it to Astro."""
from queue import Empty, Queue
from threading import Thread
import tkinter as tk
import webbrowser

from ttkbootstrap import ttk

from services.listing_capture import build_capture, submit_capture
from utils.helpers import check_mdm_lock_status
from utils.specs import listing_feature_evidence


def open_listing_capture(root, load_specs):
    dialog = tk.Toplevel(root)
    dialog.title("Create listing draft")
    dialog.transient(root)
    dialog.resizable(False, False)
    dialog.grab_set()

    body = ttk.Frame(dialog, padding=20)
    body.pack(fill="both", expand=True)
    preview = ttk.Label(body, wraplength=480, justify="left")
    preview.pack(anchor="w")
    status = ttk.Label(body, wraplength=480, justify="left")
    status.pack(anchor="w", pady=(12, 0))
    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(12, 0))
    close_button = ttk.Button(actions, text="Close", command=dialog.destroy)
    close_button.pack(side="right")
    save_button = ttk.Button(actions, text="Save draft")
    save_button.pack(side="right", padx=(0, 8))

    def run(work, finished, message):
        outcome = Queue(maxsize=1)
        status.configure(text=message)
        save_button.configure(state="disabled")
        close_button.configure(state="disabled")
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)

        def worker():
            try:
                outcome.put((work(), None))
            except Exception as exc:
                outcome.put((None, str(exc)))

        def poll():
            try:
                result, error = outcome.get_nowait()
            except Empty:
                dialog.after(100, poll)
                return
            close_button.configure(state="normal")
            dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
            finished(result, error)

        Thread(target=worker, daemon=True).start()
        dialog.after(100, poll)

    def scan():
        specs = load_specs(force_refresh=True)
        return build_capture(specs, check_mdm_lock_status()["state"],
                             listing_feature_evidence())

    def confirm(payload, error):
        if error is not None:
            status.configure(text=error)
            save_button.configure(text="Scan again", command=start_scan, state="normal")
            return
        specs = payload["specs"]
        preview.configure(text="\n".join(filter(None, (
            f"{specs['manufacturer']} {specs['model']}",
            f"Serial {payload['serial_number']}",
            " · ".join(filter(None, (specs["cpu"], specs["ram"], specs["storage"]))),
            specs["installed_windows"],
        ))))
        status.configure(text="Confirm the serial, then save. Add photos and review condition in Astro.")

        def saved(reply, save_error):
            if save_error is not None:
                status.configure(text=save_error)
                save_button.configure(text="Retry save", state="normal")
                return
            result, draft_url = reply
            status.configure(text=f"Astro listing #{result['draft_id']} · {result['state'].replace('_', ' ').title()}")
            save_button.configure(text="Open in Astro", state="normal",
                                  command=lambda: webbrowser.open(draft_url))

        def save():
            run(lambda: submit_capture(payload), saved, "Saving the listing capture to Astro…")

        save_button.configure(text="Save draft", command=save, state="normal")

    def start_scan():
        run(scan, confirm, "Reading the laptop's Windows measurements…")

    start_scan()
