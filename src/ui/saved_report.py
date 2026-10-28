"""Cancellable read-only report loading; only Tk polling updates widgets."""

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from services.saved_report import format_saved_report
from services.operator_session import SignInRequired
from utils.helpers import load_saved_check_results, log_event
from utils.ui_scaling import center_window


class SavedReportDialog:
    def __init__(self, parent, order_number, serial_number):
        self.order, self.serial = order_number, serial_number
        self.closed, self.after_id, self.generation = False, None, 0
        self.replies = queue.Queue()
        self.window = tk.Toplevel(parent)
        self.window.title('Saved report — ' + serial_number)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda event: self.close())
        self.window.bind('<Destroy>', self.destroyed, add='+')
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)
        self.status = tk.StringVar(value='')
        ttk.Label(self.window, textvariable=self.status, wraplength=640).grid(
            row=0, column=0, sticky='ew', padx=12, pady=8)
        self.text = ScrolledText(self.window, wrap='word', width=70, height=22,
                                 state='disabled', font=('Arial', 10),
                                 autostyle=False, bg='#ffffff', fg='#0f172a',
                                 relief='flat', padx=18, pady=16,
                                 highlightthickness=1, highlightbackground='#dce6f2')
        self.text.grid(row=1, column=0, sticky='nsew', padx=12)
        actions = ttk.Frame(self.window)
        actions.grid(row=2, column=0, sticky='ew', padx=12, pady=10)
        self.retry = ttk.Button(actions, text='Reload / Retry', command=self.load,
                                 style='secondary.Outline.TButton')
        self.retry.pack(side='left')
        ttk.Button(actions, text='Close', command=self.close,
                   style='secondary.Outline.TButton').pack(side='right')
        center_window(self.window, 760, 650, min_width=440, min_height=300)
        self.load()

    def show(self, text):
        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', text)
        self.text.config(state='disabled')

    def load(self):
        if self.closed:
            return
        if self.after_id:
            self.window.after_cancel(self.after_id)
            self.after_id = None
        self.generation += 1
        generation = self.generation
        self.deadline = time.monotonic() + 20
        self.retry.config(state='disabled')
        self.status.set('Loading saved report for {} / {}…'.format(self.order, self.serial))
        self.show('Waiting for Web-Tools. Close stops waiting without changing any saved data.')
        def worker():
            try:
                response = load_saved_check_results(self.order, self.serial)
                text = format_saved_report(response, self.order, self.serial)
                self.replies.put((generation, True, text, response.get('data_state')))
            except SignInRequired as exc:
                self.replies.put((generation, False, str(exc), 'sign_in_required'))
            except Exception as exc:
                log_event('Saved report read failed: {}'.format(exc))
                self.replies.put((generation, False, str(exc), 'error'))
        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as exc:
            self.replies.put((generation, False, str(exc), 'error'))
        self.after_id = self.window.after(40, self.poll)

    def poll(self):
        self.after_id = None
        if self.closed:
            return
        try:
            while True:
                generation, ok, text, state = self.replies.get_nowait()
                if generation != self.generation:
                    continue
                if state == 'sign_in_required':
                    self.retry.config(state='disabled')
                    self.status.set('Sign-in required — close this report and sign in again.')
                    self.show(text)
                    return
                self.retry.config(state='normal')
                self.status.set(('Legacy data only — check history is unknown.'
                                 if state == 'legacy_serial_only' else
                                 'No current saved assignment/report.'
                                 if state == 'no_current_assignment' else
                                 'Saved report loaded — read-only.') if ok else
                                'Report unavailable. Check service access/connection and Retry.')
                self.show(text if ok else 'Could not load the saved report.\n' + text)
                return
        except queue.Empty:
            pass
        if time.monotonic() > self.deadline:
            self.generation += 1
            self.retry.config(state='normal')
            self.status.set('Report request timed out. Retry or close.')
            self.show('No report was confirmed; saved results have not been replaced.')
            return
        self.after_id = self.window.after(40, self.poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.generation += 1
        if self.after_id:
            self.window.after_cancel(self.after_id)
            self.after_id = None
        if self.window.winfo_exists():
            self.window.destroy()

    def destroyed(self, event):
        if event.widget == self.window:
            self.close()


def open_saved_report(parent, order_number, serial_number):
    return SavedReportDialog(parent, order_number, serial_number)
