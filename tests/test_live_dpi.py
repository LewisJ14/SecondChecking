"""Live font transitions retain widget identities and unsaved operator input."""

from pathlib import Path
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from utils.ui_scaling import LiveDpiController, center_window


class LiveDpiTests(unittest.TestCase):
    def test_native_focus_without_python_widget_does_not_interrupt_polling(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(LiveDpiController, '_window_dpi', return_value=96):
                controller = LiveDpiController(root)
                root.after_cancel(controller.after_id)
                controller.after_id = None
                with patch.object(root, 'focus_displayof', side_effect=KeyError('native-popdown')):
                    controller._poll()
                self.assertIsNotNone(controller.after_id)
        finally:
            root.destroy()

    def test_initial_native_position_is_reapplied_and_cancelled_on_close(self):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        dialog = tk.Toplevel(root)
        dialog.attributes('-alpha', 0)
        destroyed = []
        dialog.bind('<Destroy>', lambda event: destroyed.append(event.widget), add='+')
        try:
            with patch('utils.ui_scaling.get_work_area', return_value=(0, 0, 1280, 800)):
                center_window(dialog, 900, 650)
            # Reproduce Windows choosing its default cascade after creation.
            dialog.geometry('900x650+300+300')
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                root.update()
                if dialog.winfo_x() == 190 and dialog.winfo_y() == 75:
                    break
                time.sleep(.01)
            self.assertEqual((dialog.winfo_x(), dialog.winfo_y()), (190, 75))
            before = set(root.tk.splitlist(root.tk.call('after', 'info')))
            center_window(dialog, 900, 650)
            dialog.destroy()
            root.update()
            self.assertIn(dialog, destroyed)
            self.assertEqual(set(root.tk.splitlist(root.tk.call('after', 'info'))), before)
        finally:
            root.destroy()

    def test_round_trip_refreshes_existing_fonts_and_preserves_draft(self):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        root.geometry('800x600+0+0')
        root.tk.call('tk', 'scaling', 96 / 72)
        with patch.object(LiveDpiController, '_window_dpi', return_value=96):
            controller = LiveDpiController(root)
        if controller.after_id:
            root.after_cancel(controller.after_id)
            controller.after_id = None
        try:
            default_font = tkfont.Font(root=root, family='Segoe UI', size=11)
            root.option_add('*Font', default_font)
            label = tk.Label(root, text='Current check', font=('Segoe UI', 11))
            label.pack()
            entry = ttk.Entry(root)
            entry.insert(0, 'test — unsaved note')
            entry.pack()
            tree = ttk.Treeview(root, columns=('serial',), show='headings')
            tree.column('serial', width=200, stretch=False)
            tree.insert('', 'end', iid='serial-001', values=('000001',))
            tree.selection_set('serial-001')
            tree.pack()
            dialog = tk.Toplevel(root)
            action = ttk.Button(dialog, text='Cancel')
            action.pack()
            transitions = []
            root.bind('<<AppDpiChanged>>', lambda e: transitions.append(e.widget))
            root.update()
            original_height = label.winfo_reqheight()
            for dpi in (144, 192, 240, 120, 96):
                controller.refresh(dpi)
                root.update()
                fresh = tk.Label(root, text='Current check', font=('Segoe UI', 11))
                fresh.pack()
                root.update_idletasks()
                self.assertEqual(label.winfo_reqheight(), fresh.winfo_reqheight())
                fresh.destroy()
                self.assertEqual(entry.get(), 'test — unsaved note')
                self.assertEqual(tree.selection(), ('serial-001',))
                self.assertEqual(tree.item('serial-001', 'values'), ('000001',))
                self.assertEqual(tree.column('serial', 'width'), round(200 * dpi / 96))
                metrics = tkfont.Font(root=root, font=label['font'])
                self.assertGreaterEqual(label.winfo_reqheight(), metrics.metrics('linespace'))
                self.assertTrue(action.winfo_exists())
                fresh_button = ttk.Button(dialog, text='Cancel')
                fresh_button.pack()
                root.update_idletasks()
                self.assertEqual(action.winfo_reqheight(), fresh_button.winfo_reqheight())
                fresh_button.destroy()
                new_default = tk.Label(dialog, text='New dialog label')
                new_default.pack()
                root.update_idletasks()
                self.assertEqual(tkfont.Font(root=root, font=new_default['font']).metrics(
                    'linespace'), metrics.metrics('linespace'))
                new_default.destroy()
                report = tk.Text(dialog, font=('Segoe UI', 11), height=2)
                report.pack()
                controller._refresh_widget_fonts()
                root.update()
                self.assertIn(str(report['font']), tkfont.names(root))
                self.assertEqual(tkfont.Font(root=root, font=report['font']).metrics(
                    'linespace'), metrics.metrics('linespace'))
                report.destroy()
            self.assertEqual(label.winfo_reqheight(), original_height)
            self.assertEqual(len(transitions), 5)
            controller.refresh(96)
            root.update()
            self.assertEqual(len(transitions), 5)
        finally:
            timer = controller.after_id
            root.destroy()
            self.assertIsNone(controller.after_id)
            if timer:
                self.assertNotIn(timer, root.tk.call('after', 'info'))

    def test_native_poll_timer_is_removed_with_root(self):
        root = tk.Tk()
        root.withdraw()
        with patch.object(LiveDpiController, '_window_dpi', return_value=96):
            controller = LiveDpiController(root)
        timer = controller.after_id
        root.update_idletasks()
        root.destroy()
        self.assertIsNone(controller.after_id)
        if timer:
            self.assertNotIn(timer, root.tk.call('after', 'info'))

    def test_smaller_work_area_rebounds_open_dialog_without_dpi_change(self):
        root = tk.Tk()
        root.attributes('-alpha', 0)
        root.geometry('900x700+500+200')
        dialog = tk.Toplevel(root)
        dialog.geometry('800x600+600+300')
        root.update()
        with patch.object(LiveDpiController, '_window_dpi', return_value=96):
            controller = LiveDpiController(root)
        if controller.after_id:
            root.after_cancel(controller.after_id)
            controller.after_id = None
        try:
            with patch('utils.ui_scaling.get_work_area', return_value=(0, 0, 640, 480)), \
                    patch.object(controller, '_window_dpi', return_value=96):
                controller._poll()
                # Native Windows geometry commits can arrive after Tk's first
                # event flush, especially while other windows are rendering.
                deadline = time.monotonic() + 2
                while True:
                    root.update_idletasks()
                    root.update()
                    if all(w.winfo_rootx() + w.winfo_width() <= 640 and
                           w.winfo_rooty() + w.winfo_height() <= 480
                           for w in (root, dialog)):
                        break
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(.01)
            for window in (root, dialog):
                self.assertGreaterEqual(window.winfo_x(), 0)
                self.assertGreaterEqual(window.winfo_y(), 0)
                self.assertLessEqual(window.winfo_rootx() + window.winfo_width(), 640)
                self.assertLessEqual(window.winfo_rooty() + window.winfo_height(), 480)
            self.assertEqual(controller.dpi, 96)
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()


