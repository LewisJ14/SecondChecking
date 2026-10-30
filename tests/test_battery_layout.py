"""The live charge label must fit at narrow widths and enlarged text scales."""

import sys
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app_controller import AppController
import main_logic


class BatteryLayoutTests(unittest.TestCase):
    def test_comparison_keeps_cycles_next_to_health_percentage(self):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        canvas = tk.Canvas(root, autostyle=False)
        canvas.pack(fill='both', expand=True)
        try:
            with patch.object(main_logic, 'log_event'):
                main_logic.render_results(
                    canvas, 'test', 'test', 'DEMO',
                    {'Battery': '31.1% (120 cycles) (Windows battery WMI health)',
                     'Battery 2': '90.0% (240 cycles) (Windows battery WMI health)'},
                    {'Battery': '30%', 'Battery 2': '80%'}, {}, {}, 'tester',
                    False, '', root)
            root.update()
            def texts(widget):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Label):
                        yield child.cget('text')
                    yield from texts(child)
            labels = list(texts(canvas))
            self.assertIn('31.1% (120 cycles)', labels)
            self.assertIn('90.0% (240 cycles)', labels)
            self.assertEqual(canvas._comparison_status['Battery'].cget('text'), 'MATCH')
        finally:
            root.destroy()

    def test_charge_label_fits_without_overlapping_progress(self):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        canvas = tk.Canvas(root, autostyle=False, highlightthickness=0, bd=0)
        canvas.pack(fill='x')
        state = SimpleNamespace(battery_bar_canvas=canvas,
                                _battery_bar_percent=79,
                                _battery_bar_charging=False,
                                _battery_bar_pulse=0.5)
        try:
            for scale in (100, 150, 200, 250):
                root.tk.call('tk', 'scaling', 4 / 3 * scale / 100)
                for width in (220, 340, 800):
                    root.geometry('{}x400'.format(width))
                    root.update()
                    for label in ('Current charge: 79% Discharging',
                                  'Current charge: 90% Charging — 18.4 W',
                                  'Current charge: Unknown (Windows live)',
                                  'Last reading: 73% — refresh unavailable; retrying',
                                  'Overall current charge: 73% AC power — rate unavailable',
                                  'Current charge: 100% Charging'):
                        with self.subTest(scale=scale, width=width, label=label):
                            state._battery_bar_label = label
                            for _ in range(3):
                                AppController._draw_battery_bar(state)
                                root.update()
                            text = canvas.bbox('charge-label')
                            track = canvas.bbox('charge-track')
                            self.assertGreaterEqual(text[0], 0)
                            self.assertLessEqual(text[2], canvas.winfo_width())
                            self.assertLess(text[3], track[1])
                            self.assertLessEqual(track[3], canvas.winfo_height())
                            self.assertEqual(len(canvas.find_withtag('charge-label')), 1)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
