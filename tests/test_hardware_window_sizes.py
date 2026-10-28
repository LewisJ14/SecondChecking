"""Initial dialog sizing with real Tk widgets and synthetic hardware boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from hardwaretests import webcam
from ui import keyboard_test
from ui.scrolling import ScrollableFrame
from ui.theme import apply_theme


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class HardwareWindowSizeTests(unittest.TestCase):
    def test_initial_keyboard_and_camera_fit_content_or_available_work_area(self):
        scenario = os.environ.get('SC_HARDWARE_WINDOW_SIZE')
        if not scenario:
            for width, height, scale in ((1280, 800, 100), (1920, 1080, 100),
                                         (1920, 1080, 150), (2880, 1920, 200),
                                         (2880, 1920, 250), (3840, 2160, 200)):
                with self.subTest(width=width, height=height, scale=scale):
                    result = subprocess.run([sys.executable, __file__],
                        env=dict(os.environ, SC_HARDWARE_WINDOW_SIZE=json.dumps(
                            [width, height, scale])), capture_output=True,
                        text=True, timeout=35)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        width, height, scale = json.loads(scenario)
        root = tk.Tk()
        apply_theme(root)
        root.attributes('-alpha', 0)
        root.tk.call('tk', 'scaling', 4 / 3 * scale / 100)
        original = tk.Toplevel
        def invisible(*args, **kwargs):
            window = original(*args, **kwargs)
            window.attributes('-alpha', 0)
            window.maxsize(6000, 4000)
            return window
        try:
            with patch.object(tk, 'Toplevel', side_effect=invisible), \
                    patch('utils.ui_scaling.get_work_area', return_value=(0, 0, width, height)), \
                    patch.object(webcam, 'get_work_area', return_value=(0, 0, width, height)):
                with patch.object(keyboard_test, 'keyboard', Mock()):
                    keyboard_test.run_keyboard_test(root, {}, {})
                    window = keyboard_test.keyboard_test_window
                    root.update()
                    surface = next(w for w in descendants(window) if isinstance(w, ScrollableFrame))
                    self.assertLessEqual(window.winfo_width(), width - 40)
                    self.assertLessEqual(window.winfo_height(), height - 40)
                    if window.winfo_reqheight() <= height - 40:
                        self.assertGreaterEqual(surface.canvas.winfo_height(),
                                                surface.content.winfo_reqheight())
                    if surface.content.winfo_reqwidth() <= width - 80:
                        self.assertLessEqual(surface.canvas.bbox('all')[2],
                                             surface.canvas.winfo_width() + 2)
                    else:
                        self.assertGreaterEqual(window.winfo_width(), width - 42)
                    for button in descendants(window):
                        if button.winfo_class() == 'Button':
                            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                                 window.winfo_rooty() + window.winfo_height())
                    next(w for w in descendants(window) if w.winfo_class() == 'Button'
                         and w.cget('text') == 'Cancel').invoke()
                with TemporaryDirectory() as directory:
                    job = Mock()
                    job.directory = Path(directory)
                    job.process.poll.return_value = None
                    Image.new('RGB', (640, 420), '#808080').save(job.directory / 'frame.jpg')
                    job.poll.return_value = dict(state='preview', camera_index=0,
                                                 frames_seen=1, heartbeat=time.time())
                    with patch.object(webcam, 'HardwareJob', return_value=job):
                        camera = webcam.CameraTest(root, {}, {}, None, None)
                        root.update()
                        camera.poll()
                        root.update()
                        job.poll.return_value.update(frames_seen=2, heartbeat=time.time())
                        camera.poll()
                        root.update()
                        self.assertLessEqual(camera.window.winfo_width(), width - 40)
                        visible_text = ' '.join(w.cget('text') for w in camera.preview_text)
                        self.assertNotIn('indices', visible_text)
                        self.assertNotIn('camera 0', camera.status.get())
                        self.assertEqual(camera.details['camera_index'], 0)
                        self.assertLessEqual(camera.window.winfo_height(), height - 40)
                        effective_scale = float(root.tk.call('tk', 'scaling')) / (96 / 72)
                        self.assertLessEqual(camera.window.winfo_width(), round(820 * effective_scale) + 2)
                        self.assertLessEqual(camera.window.winfo_height(), round(680 * effective_scale) + 2)
                        self.assertLessEqual(camera.body.content.winfo_reqheight(),
                                             camera.body.canvas.winfo_height() + 2)
                        available_height = (camera.body.canvas.winfo_height()
                                            - sum(w.winfo_reqheight() for w in camera.preview_text) - 70)
                        available_width = camera.body.canvas.winfo_width() - 32
                        image = camera.preview.image
                        self.assertAlmostEqual(image.width() / image.height(), 640 / 420, delta=.02)
                        self.assertTrue(abs(image.width() - available_width) <= 2
                                        or abs(image.height() - available_height) <= 2)
                        if available_width > 640 and available_height > 420:
                            self.assertGreater(image.width(), 640)
                        for button in camera.pass_button.master.winfo_children():
                            self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                camera.window.winfo_rooty() + camera.window.winfo_height())
                        camera.cancel()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
