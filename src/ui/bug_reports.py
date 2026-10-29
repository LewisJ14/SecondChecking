"""Central error dialogs and an explicit diagnostic preview/upload flow."""
import json
import queue
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from ttkbootstrap import ttk

from services import runtime
from services.bug_reports import prepare_report, upload_report


def open_report(parent, incident=None):
    """No upload occurs until the operator presses Upload in this preview."""
    try:
        report = prepare_report(incident)
    except Exception as error:
        runtime.log_diagnostic('support.prepare_failed', error=error)
        messagebox.showinfo('Bug report unavailable',
                            'Could not prepare diagnostics. Please retry.', parent=parent)
        return
    window = tk.Toplevel(parent)
    previous_grab = parent.grab_current()
    window.title('Upload bug report')
    window.transient(parent.winfo_toplevel())
    window.geometry('780x620')
    window.minsize(400, 300)
    window.columnconfigure(0, weight=1)
    window.rowconfigure(2, weight=1)
    ttk.Label(window, text='Review bug report', font=('Segoe UI', 16, 'bold')).grid(
        row=0, column=0, sticky='w', padx=16, pady=(16, 8))
    label = ttk.Label(window, text='Uploads to your configured Web-Tools service. Includes code locations, '
                      'error codes, build details and recent diagnostic events. No configuration files, '
                      'raw logs, screenshots, audio, order data or device identifiers are attached.',
                      wraplength=720, justify='left')
    label.grid(row=1, column=0, sticky='ew', padx=16, pady=(0, 12))
    label.bind('<Configure>', lambda event: label.configure(wraplength=max(100, event.width)))
    preview = ScrolledText(window, wrap='word', height=14, font=('Consolas', 10))
    preview.grid(row=2, column=0, sticky='nsew', padx=16)
    preview.insert('1.0', json.dumps(report, indent=2))
    preview.configure(state='disabled')
    status = tk.StringVar(value='Nothing has been uploaded.')
    status_label = ttk.Label(window, textvariable=status, wraplength=720)
    status_label.grid(row=3, column=0, sticky='ew', padx=16, pady=12)
    status_label.bind('<Configure>', lambda event: status_label.configure(wraplength=max(100, event.width)))
    actions = ttk.Frame(window)
    actions.grid(row=4, column=0, sticky='ew', padx=16, pady=(0, 16))
    replies = queue.Queue()
    busy = {'value': False}

    def close():
        if not busy['value']:
            window.destroy()
            if previous_grab is not None and previous_grab.winfo_exists():
                previous_grab.grab_set()

    def poll():
        try:
            success, value = replies.get_nowait()
        except queue.Empty:
            window.after(80, poll)
            return
        busy['value'] = False
        cancel.configure(state='normal')
        if success:
            status.set('Uploaded. Report reference: ' + value)
            cancel.configure(text='Close')
        else:
            status.set(value + ' Nothing was discarded; you can retry this report.')
            send.configure(state='normal', text='Retry upload')

    def send_report():
        if busy['value']:
            return
        busy['value'] = True
        send.configure(state='disabled')
        cancel.configure(state='disabled')
        status.set('Uploading…')

        def worker():
            try:
                reference = upload_report(report)
            except Exception as error:
                runtime.log_diagnostic('support.upload_failed', error=error)
                # Only our deliberately safe service messages reach the UI.
                message = str(error) if isinstance(error, RuntimeError) else 'Could not upload the report.'
                replies.put((False, message))
            else:
                replies.put((True, reference))
        threading.Thread(target=worker, daemon=True).start()
        window.after(80, poll)

    send = ttk.Button(actions, text='Upload bug report', command=send_report,
                      style='success.TButton')
    send.pack(side='left')
    cancel = ttk.Button(actions, text='Cancel', command=close)
    cancel.pack(side='right')
    window.protocol('WM_DELETE_WINDOW', close)
    # Clamp to the usable monitor, including high scaling and smaller screens.
    from utils.ui_scaling import center_window
    center_window(window, 780, 620, min_width=300, min_height=240)
    window.grab_set()
    window.focus_set()
    return window


class ErrorReporting:
    def __init__(self, root):
        self.root = root
        self.pending = queue.Queue(maxsize=1)
        self.previous = messagebox.showerror
        self.latest = None
        self.closed = False
        self.original_thread_hook = threading.excepthook
        self.thread_hook = lambda args: self.exception(
            'thread.unhandled_exception', args.exc_value, 'background')
        threading.excepthook = self.thread_hook
        self.wrapper = self.show_error
        messagebox.showerror = self.wrapper
        root.report_callback_exception = lambda kind, error, trace: self.exception(
            'ui.callback_failed', error, 'tk_callback')
        root.bind('<Destroy>', self._destroyed, add='+')
        self.timer = root.after(100, self._poll)

    def exception(self, event, error, stage):
        incident = runtime.log_diagnostic(event, error=error, stage=stage)
        self.latest = incident
        self._enqueue('Unexpected error',
                      'This action could not finish. Your existing check results are retained. '
                      'You can upload a bug report to help investigate.', {}, incident)

    def _enqueue(self, title, message, options, incident):
        try:
            self.pending.put_nowait((title, message, options, incident))
        except queue.Full:
            pass

    def show_error(self, title=None, message=None, **options):
        error = sys.exc_info()[1]
        incident = runtime.log_diagnostic('ui.error', error=error, stage='error_dialog')
        if error is None:
            incident['exceptions'] = [{'type': 'ReportedError', 'frames': [
                '{}:{}:{}'.format(Path(frame.filename).name, frame.lineno, frame.name)
                for frame in traceback.extract_stack()[-10:-1]]}]
            # Normalize frames before persisting/exporting (no paths or source).
            from services.diagnostic_schema import event_record
            incident = event_record(incident)
            runtime._write_diagnostic(incident)
        self.latest = incident
        if threading.current_thread() is not threading.main_thread():
            self._enqueue(title, message, options, incident)
            return 'ok'
        return self._dialog(title, message, options, incident)

    def _dialog(self, title, message, options, incident):
        if self.closed:
            return 'ok'
        parent = options.get('parent') or self.root
        try:
            if not parent.winfo_exists():
                parent = self.root
            previous_grab = self.root.grab_current()
            dialog = tk.Toplevel(parent)
            dialog.title(title or 'Error')
            dialog.transient(parent.winfo_toplevel())
            body = ttk.Frame(dialog, padding=18)
            body.pack(fill='both', expand=True)
            text = ScrolledText(body, wrap='word', height=7, width=56,
                                font=('Segoe UI', 10))
            text.insert('1.0', str(message or 'This action could not finish.')[:16000])
            text.configure(state='disabled')
            text.pack(fill='both', expand=True, pady=(0, 16))
            actions = ttk.Frame(body)
            actions.pack(fill='x')
            ttk.Button(actions, text='Upload bug report…',
                       command=lambda: open_report(dialog, incident)).pack(side='left')
            ok = ttk.Button(actions, text='OK', command=dialog.destroy)
            ok.pack(side='right', padx=(20, 0))
            dialog.update_idletasks()
            dialog.minsize(300, 140)
            from utils.ui_scaling import center_window
            center_window(dialog, 620, 350, min_width=300, min_height=180)
            dialog.bind('<Return>', lambda event: dialog.destroy())
            dialog.bind('<Escape>', lambda event: dialog.destroy())
            dialog.grab_set()
            ok.focus_set()
            dialog.wait_window()
            if previous_grab is not None and previous_grab.winfo_exists():
                previous_grab.grab_set()
        except tk.TclError:
            if not self.closed:
                return self.previous(title, message, **options)
        return 'ok'

    def _poll(self):
        if self.closed:
            return
        try:
            item = self.pending.get_nowait()
        except queue.Empty:
            pass
        else:
            self._dialog(*item)
        if not self.closed:
            self.timer = self.root.after(100, self._poll)

    def _destroyed(self, event):
        if event.widget is self.root:
            self.closed = True
            try:
                self.root.after_cancel(self.timer)
            except tk.TclError:
                pass
            if messagebox.showerror == self.wrapper:
                messagebox.showerror = self.previous
            if threading.excepthook == self.thread_hook:
                threading.excepthook = self.original_thread_hook


def install(root):
    if not getattr(root, '_error_reporting', None):
        root._error_reporting = ErrorReporting(root)
    return root._error_reporting
