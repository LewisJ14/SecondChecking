"""Verify successive USB insertions without a predeclared port checklist."""

import tkinter as tk
from tkinter import ttk

from services.test_coverage import record_coverage
from services.hardware_job import JobPoller
from utils.ui_scaling import center_window_to_content, get_work_area
from ui.scrolling import ScrollableFrame


def removable_volumes():
    import win32file

    drives = win32file.GetLogicalDrives()
    volumes = set()
    for index in range(26):
        if drives & (1 << index):
            drive = '{}:\\'.format(chr(65 + index))
            if win32file.GetDriveType(drive) == win32file.DRIVE_REMOVABLE:
                path = win32file.QueryDosDevice(drive.rstrip('\\'))
                volumes.add('{} — {}'.format(drive, path))
    return volumes


class USBTestDialog:
    def __init__(self, root, results, labels, tests_window, completion_event):
        self.results, self.labels = results, labels
        self.tests_window, self.completion_event = tests_window, completion_event
        self.closed, self.poll_id = False, None
        self.job = None
        self.known = None
        self.ports, self.observed, self.errors = [], {}, []
        self.window = tk.Toplevel(root)
        self.window.title('USB port checklist')
        self.window.protocol('WM_DELETE_WINDOW', self.cancel)
        self.window.bind('<Escape>', lambda event: self.cancel())
        self.window.bind('<Destroy>', self.destroyed, add='+')
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        self.body = ScrollableFrame(self.window, height=300)
        self.body.grid(row=0, column=0, sticky='nsew', padx=14, pady=8)
        body = self.body.content
        ttk.Label(body, text='USB ports', font=('Segoe UI', 16, 'bold')).pack(
            anchor='w', pady=(8, 10))
        actions = ttk.Frame(self.window, padding=12)
        actions.grid(row=1, column=0, sticky='ew')
        guidance = ttk.Label(body, text=(
            'Use a known-good removable USB flash drive. Unplug it, then insert it '
            'in a port. Each connection is recorded automatically. '
            'Unplug and repeat in every physical USB port. '
            'Finish only after you have checked every port.'),
            wraplength=540)
        guidance.pack(fill='x', pady=6)
        self.listbox = tk.Listbox(body, height=6, exportselection=False)
        self.listbox.pack(fill='both', expand=True)
        self.status = tk.StringVar(value='Unplug the test drive, then insert it in a port.')
        status_label = ttk.Label(body, textvariable=self.status, wraplength=540)
        status_label.pack(fill='x', pady=8)
        def fit_body(event):
            for label in (guidance, status_label):
                label.configure(wraplength=max(100, event.width - 16))
        self.body.canvas.bind('<Configure>', fit_body, add='+')
        self.pass_button = ttk.Button(actions, text='Finish — I checked every USB port',
                                      style='success.TButton',
                                      command=lambda: self.finish('pass'))
        self.pass_button.pack(fill='x', pady=3)
        from ui.bug_reports import open_report
        ttk.Button(actions, text='Upload bug report…',
                   command=lambda: open_report(self.window)).pack(fill='x', pady=3)
        for text, state in [('Fail — observed port problem', 'fail'),
                            ('Unavailable / no test media', 'unavailable'),
                            ('Record test error', 'error'),
                            ('Cancel', 'cancelled')]:
            ttk.Button(actions, text=text,
                       style='danger.Outline.TButton' if state == 'fail' else 'secondary.Outline.TButton',
                       command=lambda s=state:
                       self.finish(s)).pack(fill='x', pady=3)
        self._refresh()
        if tests_window and hasattr(tests_window, 'register_cancel'):
            tests_window.register_cancel(self.cancel)
        self.poll(initial=True)
        center_window_to_content(self.window, min_width=570, min_height=460)
        _, _, work_width, work_height = get_work_area(self.window)
        self.window.minsize(min(570, work_width - 40),
                            min(actions.winfo_reqheight() + 80, work_height - 40))

    def _refresh(self):
        self.listbox.delete(0, tk.END)
        for port in self.ports:
            self.listbox.insert(tk.END, '{} — {}'.format(
                port, 'DETECTED' if port in self.observed else 'NOT CHECKED'))
        complete = bool(self.observed) and self.known is not None
        self.pass_button.configure(state='normal' if complete else 'disabled')

    def poll(self, initial=False):
        self.poll_id = None
        if self.closed:
            return

        def complete(reply):
            if self.closed:
                return
            if reply['state'] == 'complete':
                current = set(reply['volumes'])
                if not initial and self.known is not None:
                    inserted = current - self.known
                    if inserted:
                        connection = 'Connection {}'.format(len(self.observed) + 1)
                        self.ports.append(connection)
                        self.observed[connection] = sorted(inserted)
                        self.status.set('USB drive detected and recorded. Unplug '
                                        'and move to the next port.')
                    elif self.known - current:
                        self.status.set('Drive removed. Insert it in the next port, '
                                        'or finish if every port has been checked.')
                elif not initial:
                    self.status.set('Drive detection resumed. Unplug the test drive, '
                                    'then insert it in the next port.')
                self.known = current
            else:
                detail = reply.get('detail', 'Enumeration failed.')[:500]
                if detail not in self.errors:
                    self.errors.append(detail)
                    self.errors = self.errors[-10:]
                self.known = None
                self.status.set('Cannot detect USB drives. Retry, record Error or Cancel.')
            self._refresh()
            self.poll_id = self.window.after(1000, self.poll)

        self.job = JobPoller(self.window, 'usb', complete, timeout=10)

    def finish(self, result):
        if self.closed or (result == 'pass' and (
                not self.observed or self.known is None)):
            return
        if result == 'error' and not self.errors:
            self.status.set('No USB error has been observed.')
            return
        self.closed = True
        if self.job:
            self.job.cancel()
        if self.poll_id is not None:
            self.window.after_cancel(self.poll_id)
            self.poll_id = None
        record_coverage(self.results, 'usb',
                        'Automatically detected insertions; operator confirms '
                        'all physical ports checked at Finish. Removable-volume '
                        'detection only; port uniqueness and other functions unverified.',
                        {'operator_confirmed_all_ports': result == 'pass',
                         'automatic_insertion_detection': True,
                         'port_count_declared': False,
                         'observed_ports': self.observed, 'errors': self.errors})
        self.results['usb'] = result
        try:
            if 'usb_label' in self.labels:
                self.labels['usb_label'].config(text=result.upper())
            if self.tests_window:
                self.tests_window.update_icon('usb')
        finally:
            if self.completion_event:
                self.completion_event.set()
            self.window.destroy()

    def cancel(self):
        self.finish('cancelled')

    def destroyed(self, event):
        if event.widget == self.window and not self.closed:
            self.cancel()


def run_usb_test(root, test_results, test_labels, tests_window=None,
                 completion_event=None):
    return USBTestDialog(root, test_results, test_labels,
                         tests_window, completion_event)
