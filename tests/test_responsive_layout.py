"""Real Tk geometry and interaction at small sizes and multiple font scales."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import app_controller
import main_logic
from ui import keyboard_test
from ui.tests import TestsWindow
import ui.tests as test_panel
from services.check_results import TEST_KEYS
from services.mdm_evidence import evidence
from ui.scrolling import ScrollableFrame
from auth import login
from hardwaretests import webcam, usb
from logic import view_serials_logic as serial_viewer
import time


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


from operator_fixture import sign_in as setUpModule, sign_out as tearDownModule


class InitialWindowLayoutTests(unittest.TestCase):
    def test_initial_windows_reserve_space_for_content(self):
        scenario = os.environ.get('SECOND_CHECK_INITIAL_LAYOUT')
        if not scenario:
            for width, height, scale in ((1280, 800, 100), (1920, 1080, 150),
                                         (2256, 1504, 150), (2880, 1920, 200),
                                         (3840, 2160, 200), (3840, 2160, 250)):
                with self.subTest(width=width, height=height, scale=scale):
                    child = subprocess.run(
                        [sys.executable, __file__, 'InitialWindowLayoutTests'],
                        env=dict(os.environ, SECOND_CHECK_INITIAL_LAYOUT=
                                 '{},{},{}'.format(width, height, scale)),
                        capture_output=True, text=True, timeout=35)
                    self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        width, height, scale = map(int, scenario.split(','))
        root = app_controller.tb.Window(themename='flatly')
        root.attributes('-alpha', 0)
        root.maxsize(5000, 4000)
        root.tk.call('tk', 'scaling', 4 / 3 * scale / 100)
        try:
            with patch.object(app_controller, 'get_work_area', return_value=(0, 0, width, height)), \
                    patch.object(app_controller, 'reset_specs_cache'), \
                    patch.object(app_controller, 'LoginPanel'), \
                    patch.object(app_controller, 'UpdateService') as service:
                service.return_value.current_version = 'layout-test'
                controller = app_controller.AppController(root)
                controller.current_user = SimpleNamespace(username='tester')
                controller._render_laptop_specs = Mock()
                controller._refresh_primary_battery_state = Mock()
                controller.check_for_updates = Mock()
                controller._build_ui()
                root.update()
                self.assertLessEqual(root.winfo_width(), width - 40)
                self.assertLessEqual(root.winfo_height(), height - 80)
                self.assertGreaterEqual(controller.canvas.winfo_height(), height * .35)
            with patch.object(test_panel, 'get_work_area', return_value=(0, 0, width, height)), \
                    patch('utils.ui_scaling.get_work_area', return_value=(0, 0, width, height)), \
                    patch.object(test_panel, 'current_override', return_value=True):
                panel = TestsWindow(root, dict.fromkeys(TEST_KEYS, 'n/a'), {},
                                    context_label='Order: bench checks | Device: FRANVZCPA76292002N')
                panel.tests_window.maxsize(5000, 4000)
                panel.tests_window.attributes('-alpha', 0)
                panel.update_status('Completed: 1 pass. 0 not started (previous results retained). '
                                    'Results are local; assign the device to save its report.')
                root.update()
                self.assertLessEqual(panel.tests_window.winfo_width(), width - 40)
                self.assertLessEqual(panel.tests_window.winfo_height(), height - 80)
                rows = panel.tests_container.winfo_children()
                self.assertGreaterEqual(panel.tests_canvas.winfo_height(),
                                        sum(row.winfo_height() for row in rows[:2]))
                self.assertGreaterEqual(int(panel.status_label.cget('wraplength')),
                                        panel.status_label.winfo_width() - 5)
                self.assertTrue(panel.run_all_button.winfo_ismapped())
                panel.on_close()
        finally:
            for pending in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', pending)
            root.destroy()


class VisualThemeTests(unittest.TestCase):
    def test_explicit_card_colours_survive_theme_initialisation(self):
        if os.environ.get('SECOND_CHECK_THEME_CHILD') != '1':
            child = subprocess.run(
                [sys.executable, __file__, 'VisualThemeTests'],
                env=dict(os.environ, SECOND_CHECK_THEME_CHILD='1'),
                capture_output=True, text=True, timeout=30)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        from ui.theme import apply_theme
        root = app_controller.tb.Window(themename='flatly')
        root.withdraw()
        try:
            style = apply_theme(root)
            with patch.object(login.LoginPanel, '_load_usernames_async'):
                form = login.LoginPanel(root, Mock())
            self.assertEqual(form.login_card.cget('background'), 'white')
            self.assertEqual(form.login_button.cget('background'), '#1f7f52')
            self.assertEqual(form.login_button.cget('foreground'), 'white')
            self.assertIsNotNone(form._hero_original)
            self.assertIn('Arial', str(style.lookup('Treeview', 'font')))
            with patch.object(test_panel, 'current_override', return_value=True):
                panel = TestsWindow(root, dict.fromkeys(TEST_KEYS, 'n/a'), {})
            self.assertEqual(panel.context_header.cget('background'), '#1f7f52')
            self.assertEqual(panel.context_header.cget('foreground'), 'white')
            style.theme_use('flatly')
            apply_theme(root)
            self.assertEqual(panel.context_header.cget('background'), '#1f7f52')
            self.assertEqual(style.lookup('primary.TButton', 'foreground'), '#ffffff')
            panel.on_close()
        finally:
            for pending in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', pending)
            root.destroy()


class LoginLayoutTests(unittest.TestCase):
    def test_sign_in_controls_fit_or_scroll_into_view(self):
        scale = os.environ.get('SECOND_CHECK_LOGIN_SCALE')
        if not scale:
            for percent in (100, 125, 150, 200, 250):
                with self.subTest(scale=percent):
                    child = subprocess.run(
                        [sys.executable, __file__, 'LoginLayoutTests'],
                        env=dict(os.environ, SECOND_CHECK_LOGIN_SCALE=str(percent)),
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        root = app_controller.tb.Window(themename='flatly')
        root.geometry('1400x900+0+0')
        root.minsize(800, 500)
        root.attributes('-alpha', 0)
        root.tk.call('tk', 'scaling', 4 / 3 * int(scale) / 100)
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)
        try:
            before = root.bind('<FocusIn>')
            with patch.object(login.LoginPanel, '_load_usernames_async'), \
                    patch.object(login, 'get_work_area', return_value=(0, 0, 1800, 1120)), \
                    patch.object(login, '_load_last_user', return_value='tester'):
                panel = login.LoginPanel(root, Mock())
            panel._finish_username_load(['tester', 'review_operator_with_a_deliberately_long_name'], None)
            root.update()
            self.assertLessEqual(root.winfo_height(),
                                 max(560, panel.login_card.winfo_reqheight() + 80))
            self.assertLessEqual(root.winfo_height(), 1080)
            self.assertLessEqual(root.winfo_width(), 1760)
            controls = (panel.username_combo, panel.password_entry, panel.login_button,
                        panel.retry_button, panel.exit_button)
            for control in controls:
                self.assertGreater(control.winfo_height(), 15)
                self.assertGreaterEqual(control.winfo_rootx(), panel.login_canvas.winfo_rootx())
                self.assertLessEqual(control.winfo_rootx() + control.winfo_width(),
                                     panel.login_canvas.winfo_rootx() + panel.login_canvas.winfo_width())
                self.assertGreaterEqual(control.winfo_rooty(), panel.login_canvas.winfo_rooty())
                self.assertLessEqual(control.winfo_rooty() + control.winfo_height(),
                                     panel.login_canvas.winfo_rooty() + panel.login_canvas.winfo_height())
            # Long asynchronous errors and manual shrinking need scrolling, not
            # a clipped final action row or a hidden password field.
            root.geometry('480x360+0+0')
            panel._finish_username_load([], 'Unable to reach Web-Tools. ' * 12)
            root.update()
            self.assertFalse(panel.hero.winfo_manager())
            self.assertGreater(panel.login_card.winfo_height(), panel.login_canvas.winfo_height())
            for control in controls:
                self.assertGreaterEqual(control.winfo_rootx(), panel.login_canvas.winfo_rootx())
                self.assertLessEqual(control.winfo_rootx() + control.winfo_width(),
                                     panel.login_canvas.winfo_rootx() + panel.login_canvas.winfo_width())
            panel._finish_username_load(['tester'], None)
            root.update()
            for control in (panel.password_entry, panel.login_button, panel.exit_button):
                control.focus_force()
                control.event_generate('<FocusIn>')
                root.update()
                self.assertGreaterEqual(control.winfo_rooty(), panel.login_canvas.winfo_rooty())
                self.assertLessEqual(control.winfo_rooty() + control.winfo_height(),
                                     panel.login_canvas.winfo_rooty() + panel.login_canvas.winfo_height())
            panel._set_login_busy(True)
            root.update()
            self.assertEqual(str(panel.login_button.cget('state')), 'disabled')
            panel._set_login_busy(False)
            panel._finish(None)
            root.update()
            self.assertEqual(root.bind('<FocusIn>'), before)
            self.assertFalse(errors, errors)
            # Inspect the reset form without changing any account password.
            with patch.object(tk.Toplevel, 'wait_window'):
                reset = login.PasswordResetDialog(root)
            root.update()
            for control in descendants(reset.top):
                if isinstance(control, (tk.Entry, tk.Button)):
                    self.assertGreater(control.winfo_height(), 15)
                    self.assertGreaterEqual(control.winfo_rooty(), reset.top.winfo_rooty())
                    self.assertLessEqual(control.winfo_rooty() + control.winfo_height(),
                                         reset.top.winfo_rooty() + reset.top.winfo_height())
            reset._on_cancel()
        finally:
            root.destroy()


class ActionFooterLayoutTests(unittest.TestCase):
    def test_async_content_cannot_displace_actions_or_hide_identifiers(self):
        scale = os.environ.get('SECOND_CHECK_ACTION_SCALE')
        if not scale:
            for percent in (100, 150, 200, 250):
                with self.subTest(scale=percent):
                    child = subprocess.run(
                        [sys.executable, __file__, 'ActionFooterLayoutTests'],
                        env=dict(os.environ, SECOND_CHECK_ACTION_SCALE=str(percent)),
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            return
        root = app_controller.tb.Window(themename='flatly')
        root.attributes('-alpha', 0)
        root.tk.call('tk', 'scaling', 4 / 3 * int(scale) / 100)
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)

        def footer_visible(window, buttons):
            root.update()
            for button in buttons:
                self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
                self.assertGreaterEqual(button.winfo_rooty(), window.winfo_rooty())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                     window.winfo_rooty() + window.winfo_height())
                self.assertGreaterEqual(button.winfo_rootx(), window.winfo_rootx())
                self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                     window.winfo_rootx() + window.winfo_width())
        try:
            with patch.object(webcam, 'HardwareJob'):
                camera = webcam.CameraTest(root, {}, {}, None, None)
                camera.window.attributes('-alpha', 0)
                root.update()
                camera.show_error('Long native camera failure. ' * 120)
                image = tk.PhotoImage(width=1200, height=900)
                camera.preview.configure(image=image)
                camera.window.geometry('700x550+0+0')
                footer_visible(camera.window, camera.pass_button.master.winfo_children())
                self.assertGreater(camera.body.content.winfo_height(), camera.body.canvas.winfo_height())
                camera.cancel()
                self.assertEqual(camera.results['webcam'], 'cancelled')
            callbacks = []
            def deferred(window, kind, callback, **kwargs):
                callbacks.append(callback)
                return Mock()
            with patch.object(usb, 'JobPoller', side_effect=deferred):
                ports = usb.USBTestDialog(root, {}, {}, None, None)
                ports.window.attributes('-alpha', 0)
                root.update()
                callbacks[-1](dict(state='error', detail='Long removable-volume error. ' * 80))
                ports.window.geometry('700x550+0+0')
                footer_visible(ports.window, ports.pass_button.master.winfo_children())
                self.assertNotIn('Long removable-volume error', ports.status.get())
                self.assertTrue(ports.errors)
                ports.cancel()
                self.assertEqual(ports.results['usb'], 'cancelled')
            serial = '0001234567890123456789012345678901234567890'
            sku = 'FULL-SKU-' * 35
            connection = Mock()
            connection.cursor.return_value.fetchall.return_value = [(serial, sku, '26/10/2026 12:00')]
            with patch.object(serial_viewer, 'get_db_connection', return_value=connection):
                viewer = serial_viewer.open_serial_viewer('test', 'tester')
                viewer.attributes('-alpha', 0)
                tree = next(w for w in descendants(viewer) if isinstance(w, serial_viewer.ttk.Treeview))
                deadline = time.monotonic() + 3
                while not tree.get_children() and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.01)
                self.assertTrue(tree.get_children())
                tree.selection_set(tree.get_children()[0])
                tree.event_generate('<<TreeviewSelect>>')
                viewer.geometry('740x500+0+0')
                buttons = [w for w in descendants(viewer) if isinstance(w, tk.Button)]
                footer_visible(viewer, buttons)
                detail = next(w for w in descendants(viewer) if isinstance(w, tk.Text))
                self.assertIn(serial, detail.get('1.0', 'end'))
                self.assertIn(sku, detail.get('1.0', 'end'))
                self.assertGreater(tree.column('Serial Number', 'width'), 120)
                viewer.destroy()
            self.assertFalse(errors, errors)
        finally:
            root.destroy()


class ResponsiveLayoutTests(unittest.TestCase):
    def test_size_and_scaling_matrix(self):
        scale = os.environ.get('SECOND_CHECK_LAYOUT_SCALE')
        if not scale:
            entries = []
            for percent in (100, 125, 150, 200):
                with self.subTest(scale=percent):
                    child = subprocess.run(
                        [sys.executable, __file__, 'ResponsiveLayoutTests'],
                        env=dict(os.environ, SECOND_CHECK_LAYOUT_SCALE=str(percent)),
                        capture_output=True, text=True, timeout=40)
                    self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
                    line = next(line for line in child.stdout.splitlines()
                                if line.startswith('LAYOUT_EVIDENCE '))
                    entries.extend(json.loads(line.split(' ', 1)[1]))
            output = os.environ.get('SECOND_CHECK_LAYOUT_EVIDENCE')
            if output:
                Path(output).write_text(json.dumps(entries, indent=2), encoding='utf-8')
            return
        root = tk.Tk()
        root.attributes('-alpha', 0)
        root.tk.call('tk', 'scaling', 4 / 3 * int(scale) / 100)
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)
        rows = []
        try:
            with patch.object(app_controller, 'reset_specs_cache'), \
                    patch.object(app_controller, 'LoginPanel'), \
                    patch.object(app_controller, 'UpdateService') as service:
                service.return_value.current_version = 'layout-test'
                controller = app_controller.AppController(root)
            controller.current_user = SimpleNamespace(username='tester')
            controller._render_laptop_specs = Mock()
            controller._refresh_primary_battery_state = Mock()
            controller._center_current_window = Mock()
            controller.check_for_updates = Mock()
            controller._build_ui()
            controller._update_order_notes_footer('Long note ' * 100, 1, 'test')
            controller._update_results_footer(
                'Review ' * 60, '#b42318', 'NOT VERIFIED: local MDM evidence ' * 10,
                '#854d0e', ['Battery current charge: unknown'])
            for width, height in ((1024, 768), (1366, 768)):
                root.geometry('{}x{}+0+0'.format(width, height))
                root.update()
                specs = dict(Model='Long model description ' * 5,
                             CPU='Intel Core processor ' * 4,
                             SSD='512GB SSD + 512GB SSD', RAM='16GB',
                             Resolution='1920x1080', Windows='Windows 11 Pro',
                             Battery='85%', **{'Battery 2': '82%'})
                main_logic.render_results(
                    controller.canvas, 'ORDER-001234', 'LONG SKU TITLE ' * 18,
                    '001234567890', specs, specs, {}, {}, 'tester', True, '', root)
                root.update()
                content = controller.canvas._comparison_content
                labels = [w for w in content.winfo_children() if isinstance(w, tk.Label)]
                title = next(w for w in labels if w.cget('text').startswith('SKU:'))
                identity = next(w for w in labels if w.cget('text').startswith('Order:'))
                actions = [w for w in descendants(content) if w.winfo_class() == 'TButton']
                self.assertEqual(len(actions), 2)
                self.assertGreaterEqual(title.winfo_y(), actions[0].master.winfo_y()
                                        + actions[0].master.winfo_height())
                self.assertGreaterEqual(actions[0].master.winfo_y(),
                                        identity.winfo_y() + identity.winfo_height())
                self.assertLessEqual(title.winfo_width(), controller.canvas.winfo_width())
                self.assertGreaterEqual(controller.canvas.winfo_height(), 120)
                self.assertLessEqual(controller.footer_scroll.winfo_height(), 190)
                self.assertTrue(controller.footer_toggle.winfo_ismapped())
                self.assertTrue(controller.footer_scroll.winfo_ismapped())
                # Every comparison cell must remain within its table.
                table = controller.canvas._comparison_status['SSD'].master
                for label in table.winfo_children():
                    self.assertLessEqual(label.winfo_x() + label.winfo_width(),
                                         table.winfo_width() + 2)
                    self.assertLessEqual(table.winfo_width(), content.winfo_width())
                # Wheel events over a label route to this surface, not a global list.
                before = controller.canvas.yview()
                title.event_generate('<MouseWheel>', delta=-120)
                root.update()
                self.assertGreater(controller.canvas.yview()[0], before[0])
                controller.canvas.yview_moveto(1)
                actions[0].focus_force()
                actions[0].event_generate('<FocusIn>')
                root.update()
                self.assertGreaterEqual(actions[0].winfo_rooty(), controller.canvas.winfo_rooty())
                self.assertLessEqual(actions[0].winfo_rooty() + actions[0].winfo_height(),
                                     controller.canvas.winfo_rooty() + controller.canvas.winfo_height())
                controller.footer_toggle.invoke()
                root.update()
                self.assertFalse(controller.footer_scroll.winfo_manager())
                controller.footer_toggle.invoke()
                root.update()
                rows.append(dict(scale_percent=int(scale), width=width, height=height,
                                 comparison_height=controller.canvas.winfo_height(),
                                 footer_height=controller.footer_scroll.winfo_height(),
                                 title_height=title.winfo_height()))

            # A tall window must give unused comparison space to the details.
            factor = int(scale) / 100
            root.maxsize(6000, 5000)
            root.geometry('{}x{}+0+0'.format(round(1600 * factor),
                                            round(1200 * factor)))
            specs = dict(Model='Test laptop', CPU='Intel Core i5', SSD='512GB SSD',
                         RAM='16GB', Resolution='1920x1080', Windows='Windows 11',
                         Battery='85%')
            main_logic.render_results(controller.canvas, 'test', 'Test SKU',
                                      '001234', specs, specs, {}, {}, 'tester',
                                      True, '', root)
            controller._update_results_footer(
                '\n'.join(['Review required'] * 12), '#b42318',
                'MDM NOT VERIFIED', '#854d0e', ['Battery charge: 85%'])
            root.update()
            self.assertGreater(controller.footer_scroll.canvas.winfo_height(), 200)
            self.assertGreaterEqual(controller.canvas.winfo_height(),
                                    controller.canvas._comparison_content.winfo_reqheight())
            expanded_height = controller.footer_scroll.canvas.winfo_height()
            controller._update_results_footer('Ready', '#1f7a4d',
                                               'MDM NOT VERIFIED', '#854d0e', [])
            root.update()
            self.assertLess(controller.footer_scroll.canvas.winfo_height(), expanded_height)

            with patch.object(test_panel, 'current_override', return_value=True):
                panel = TestsWindow(root, dict.fromkeys(TEST_KEYS, 'n/a'), {})
                panel.tests_window.attributes('-alpha', 0)
                panel.tests_window.geometry('640x700+0+0')
                root.update()
                for row in panel.tests_container.winfo_children():
                    for widget in row.winfo_children():
                        self.assertLessEqual(widget.winfo_x() + widget.winfo_width(),
                                             row.winfo_width() + 2)
                sample = panel.test_labels['usb_label']
                before = panel.tests_canvas.yview()
                sample.event_generate('<MouseWheel>', delta=-120)
                root.update()
                self.assertGreater(panel.tests_canvas.yview()[0], before[0])
                self.assertTrue(panel.cancel_button.winfo_ismapped())
                panel.on_close()

            old_tab = root.bind_all('<Tab>')
            with patch.object(keyboard_test, 'keyboard', Mock()):
                keyboard_test.run_keyboard_test(root, {}, {})
                window = keyboard_test.keyboard_test_window
                window.attributes('-alpha', 0)
                window.geometry('900x650+0+0')
                root.update()
                surface = next(w for w in descendants(window)
                               if isinstance(w, ScrollableFrame))
                keys = [w for w in descendants(surface) if isinstance(w, tk.Label)]
                import tkinter.font as font
                numpad_toggle = next(w for w in descendants(window)
                                     if isinstance(w, tk.Checkbutton)
                                     and w.cget('text') == 'Show Numpad')
                for include_numpad in (False, True):
                    if include_numpad:
                        numpad_toggle.invoke()
                        window.geometry('900x650+0+0')
                        root.update()
                    visible_keys = [key for key in keys if key.winfo_ismapped()]
                    self.assertTrue(visible_keys)
                    for key in visible_keys:
                        metrics = font.Font(root=root, font=key.cget('font'))
                        self.assertGreaterEqual(key.winfo_width(),
                                                metrics.measure(key.cget('text')))
                    if include_numpad:
                        self.assertTrue(all(key.winfo_ismapped() for key in keys))
                self.assertGreater(surface.canvas.bbox('all')[2], surface.canvas.winfo_width())
                before = surface.canvas.xview()
                keys[0].event_generate('<Shift-MouseWheel>', delta=-120)
                root.update()
                self.assertGreater(surface.canvas.xview()[0], before[0])
                finish = next(w for w in descendants(window)
                              if w.winfo_class() == 'Button'
                              and w.cget('text') == 'Finish and review')
                self.assertLessEqual(finish.winfo_rooty() + finish.winfo_height(),
                                     window.winfo_rooty() + window.winfo_height())
                root.tk.call(window.protocol('WM_DELETE_WINDOW'))
                root.update()
                self.assertEqual(root.bind_all('<Tab>'), old_tab)
                controller.order_entry.focus_force()
                root.update()
                self.assertEqual(root.focus_get(), controller.order_entry)
            self.assertFalse(errors, errors)
            print('LAYOUT_EVIDENCE ' + json.dumps(rows))
        finally:
            for pending in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', pending)
            root.destroy()


if __name__ == '__main__':
    unittest.main()
