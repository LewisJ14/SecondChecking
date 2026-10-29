"""Camera discovery and reads run in an isolated, cancellable worker."""

import io
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from services.hardware_job import HardwareJob
from services.test_coverage import record_coverage
from utils.ui_scaling import center_window, get_work_area
from ui.scrolling import ScrollableFrame
from services.runtime import log_diagnostic


class CameraTest:
    def __init__(self, root, results, labels, tests_window, completion_event):
        self.results, self.labels = results, labels
        self.panel, self.done = tests_window, completion_event
        self.closed, self.after_id, self.job = False, None, None
        self.details = {'camera_index': None, 'frames_seen': 0}
        self.last_frame = None
        self._frame_image = None
        self._preview_size = None
        self.started_at = time.monotonic()
        self.window = tk.Toplevel(root)
        self.window.title('Webcam Test')
        self.window.protocol('WM_DELETE_WINDOW', self.cancel)
        self.window.bind('<Escape>', lambda event: self.cancel())
        self.window.bind('<Destroy>', self.destroyed, add='+')
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        self.body = ScrollableFrame(self.window, height=260)
        self.body.grid(row=0, column=0, sticky='nsew')
        body = self.body.content
        title_label = ttk.Label(body, text='Camera check', font=('Segoe UI', 16, 'bold'))
        title_label.pack(anchor='w', padx=12, pady=(14, 8))
        actions = ttk.Frame(self.window, padding=12)
        actions.grid(row=1, column=0, sticky='ew')
        self.status = tk.StringVar(value='Discovering camera — Cancel is available.')
        status_label = ttk.Label(body, textvariable=self.status, wraplength=600)
        status_label.pack(fill='x', padx=12, pady=10)
        self.preview = ttk.Label(body)
        self.preview.pack(padx=12, pady=6)
        guidance = ttk.Label(body, text='Inspect a clear, moving image, focus and colours.',
                  wraplength=600)
        guidance.pack(fill='x', padx=12, pady=6)
        self.preview_text = (title_label, status_label, guidance)
        def fit_body(event):
            for label in (status_label, guidance):
                label.configure(wraplength=max(100, event.width - 32))
        self.body.canvas.bind('<Configure>', fit_body, add='+')
        self.pass_button = ttk.Button(actions, text='Pass — live image correct',
                                      style='success.TButton',
                                      command=lambda: self.finish('pass'),
                                      state='disabled')
        for column in range(2):
            actions.columnconfigure(column, weight=1, uniform='camera_actions')
        self.pass_button.grid(row=0, column=0, sticky='ew', padx=4, pady=3)
        ttk.Button(actions, text='Retry camera', command=self.retry).grid(
            row=0, column=1, sticky='ew', padx=4, pady=3)
        for index, (text, state) in enumerate([('Fail — observed image problem', 'fail'),
                            ('Unavailable', 'unavailable'),
                            ('Record test error', 'error'),
                            ('Cancel', 'cancelled')]):
            ttk.Button(actions, text=text,
                       style='danger.Outline.TButton' if state == 'fail' else 'secondary.Outline.TButton',
                       command=lambda s=state: self.finish(s)).grid(
                           row=1 + index // 2, column=index % 2,
                           sticky='ew', padx=4, pady=3)
        if self.panel and hasattr(self.panel, 'register_cancel'):
            self.panel.register_cancel(self.cancel)
        from ui.bug_reports import open_report
        ttk.Button(actions, text='Upload bug report…',
                   command=lambda: open_report(self.window)).grid(
                       row=3, column=0, columnspan=2, sticky='ew', padx=4, pady=3)
        scale = float(root.tk.call('tk', 'scaling')) / (96 / 72)
        center_window(self.window, round(820 * scale), round(680 * scale),
                      min_width=640, min_height=300)
        _, _, work_width, work_height = get_work_area(self.window)
        self.window.minsize(min(640, work_width - 40),
                            min(actions.winfo_reqheight() + 80, work_height - 40))
        self.start()

    def retry(self):
        if self.closed:
            return
        if self.after_id is not None:
            self.window.after_cancel(self.after_id)
            self.after_id = None
        if self.job:
            self.job.close()
        self.details = {'camera_index': None, 'frames_seen': 0}
        self.last_frame = None
        self._frame_image = None
        self._preview_size = None
        self.pass_button.config(state='disabled')
        self.preview.config(image='')
        self.preview.image = None
        self.status.set('Discovering camera — Cancel is available.')
        self.start()

    def start(self):
        try:
            log_diagnostic('camera.started', kind='camera', timeout_seconds=25)
            self.job = HardwareJob('camera', timeout=25)
            self.after_id = self.window.after(40, self.poll)
        except Exception as exc:
            log_diagnostic('camera.start_failed', error=exc, stage='launch')
            self.show_error(str(exc))

    def poll(self):
        if self.after_id is not None:
            self.window.after_cancel(self.after_id)
        self.after_id = None
        if self.closed:
            return
        try:
            reply = self.job.poll()
            if reply:
                if reply['state'] != 'preview':
                    self.show_error(reply.get('detail', 'Camera unavailable.'))
                    if reply['state'] == 'unavailable':
                        self.finish('unavailable')
                    return
                if time.time() - reply['heartbeat'] > 5:
                    raise TimeoutError('Camera stopped returning fresh frames.')
                if self.job.process.poll() is not None:
                    raise RuntimeError('Camera worker stopped.')
                frame = self.job.directory / 'frame.jpg'
                if reply['frames_seen'] != self.last_frame:
                    # Load bytes fully before the worker replaces the file.
                    data = frame.read_bytes()
                    with Image.open(io.BytesIO(data)) as image:
                        self._frame_image = image.copy()
                    self.last_frame = reply['frames_seen']
                    if self.details['frames_seen'] == 0:
                        log_diagnostic('camera.preview_ready', camera_index=reply['camera_index'],
                                       frames_seen=reply['frames_seen'])
                self._fit_preview()
                self.details.update(camera_index=reply['camera_index'],
                                    frames_seen=reply['frames_seen'])
                self.details.pop('preview_error', None)
                self.pass_button.config(state='normal')
                self.status.set('Live camera — inspect before deciding.')
            self.after_id = self.window.after(70, self.poll)
        except Exception as exc:
            log_diagnostic('camera.preview_failed', error=exc, stage='preview',
                           frames_seen=self.details['frames_seen'])
            self.show_error(str(exc))

    def _fit_preview(self):
        if self._frame_image is None:
            return
        text_height = sum(label.winfo_reqheight() for label in self.preview_text)
        width = max(80, self.body.canvas.winfo_width() - 32)
        height = max(60, self.body.canvas.winfo_height() - text_height - 70)
        source_width, source_height = self._frame_image.size
        ratio = min(width / source_width, height / source_height)
        size = (max(1, int(source_width * ratio)),
                max(1, int(source_height * ratio)))
        # New frames always redraw; unchanged frames only redraw after a resize.
        if self._preview_size == (self.last_frame, size):
            return
        image = self._frame_image.resize(size, Image.Resampling.BILINEAR)
        self.preview.image = ImageTk.PhotoImage(image, master=self.window)
        self.preview.config(image=self.preview.image)
        self._preview_size = (self.last_frame, size)

    def show_error(self, detail):
        log_diagnostic('camera.error', state='error',
                       reason='Preview unavailable; retry or record an outcome',
                       frames_seen=self.details['frames_seen'])
        self.details['preview_error'] = detail[:1000]
        self.pass_button.config(state='disabled')
        self.status.set('Camera error. Retry, record Error, Unavailable or Cancel.')
        if self.job:
            self.job.close()

    def finish(self, result):
        if self.closed:
            return
        if result == 'pass':
            # Recheck the worker heartbeat at the moment of confirmation.
            self.poll()
            if self.closed:
                return
            if not self.details['frames_seen'] or self.details.get('preview_error'):
                return
        self.closed = True
        log_diagnostic('camera.finished', result=result,
                       camera_index=self.details['camera_index'],
                       frames_seen=self.details['frames_seen'],
                       elapsed_ms=round((time.monotonic() - self.started_at) * 1000))
        if self.after_id is not None:
            self.window.after_cancel(self.after_id)
            self.after_id = None
        if self.job:
            self.job.close()
        record_coverage(self.results, 'webcam',
                        'Operator preview of first readable DirectShow camera '
                        'in indices 0–9; other cameras untested.', self.details)
        self.results['webcam'] = result
        try:
            if 'webcam_label' in self.labels:
                self.labels['webcam_label'].config(text=result.upper())
            if self.panel:
                self.panel.update_icon('webcam')
        finally:
            if self.done:
                self.done.set()
            self.window.destroy()

    def cancel(self):
        self.finish('cancelled')

    def destroyed(self, event):
        if event.widget == self.window and not self.closed:
            self.cancel()


def run_webcam_test(root, test_results, test_labels, tests_window=None,
                    completion_event=None):
    return CameraTest(root, test_results, test_labels, tests_window,
                      completion_event)
