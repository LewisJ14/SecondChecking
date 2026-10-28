"""Use real hidden Tk widgets to check exact identifiers at action boundaries."""

from contextlib import ExitStack
import gc
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from logic import view_serials_logic as viewer


class SerialTextTests(unittest.TestCase):
    def test_text_and_database_byte_values_keep_every_character(self):
        for serial in [
            "001234",
            "000000",
            "0",
            "000ABC",
            "1e04",
            "123456789012345678901234567890",
            "É0001",
        ]:
            for value in [
                serial,
                serial.encode("utf-8"),
                bytearray(serial.encode("utf-8")),
                memoryview(serial.encode("utf-8")),
            ]:
                with self.subTest(value=value):
                    self.assertEqual(viewer._serial_text(value), serial)

    def test_invalid_values_cannot_be_converted_to_a_different_identifier(
        self,
    ):
        for value in [None, 1234, 0, False, "", "  ", b"001\xff234"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    viewer._serial_text(value)


class SerialViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gc.collect()
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        cls.root = None
        gc.collect()

    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from SerialViewerTests.descendants(child)

    def run_viewer(
        self, rows, action, *, invalid=False, no_mutation=False,
        remove_response=None, load_error=False,
    ):
        root = self.root
        original_toplevel = tk.Toplevel
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchall.side_effect = [rows, rows[:-1]]
        if load_error:
            cursor.fetchall.side_effect = RuntimeError("Test database offline")
        cursor.fetchone.return_value = (
            "SKU",
            "i5",
            "8GB",
            "256GB",
            "T480",
            "1920x1080",
            "Windows 11",
            "90%",
            None,
            "not_locked",
            "",
        )
        state = {"started": False, "complete": False, "errors": []}

        def hidden_window(*args, **kwargs):
            window = original_toplevel(*args, **kwargs)
            window.withdraw()
            return window

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(viewer.tk, "Toplevel", side_effect=hidden_window)
            )
            stack.enter_context(
                patch.object(
                    viewer, "get_db_connection", return_value=connection
                )
            )
            remove = stack.enter_context(
                patch.object(
                    viewer,
                    "unassign_order_serial",
                    return_value=remove_response or (True, {"success": True}),
                )
            )
            stack.enter_context(
                patch.object(viewer.messagebox, "askyesno", return_value=True)
            )
            info = stack.enter_context(
                patch.object(viewer.messagebox, "showinfo")
            )
            error = stack.enter_context(
                patch.object(viewer.messagebox, "showerror")
            )
            stack.enter_context(patch.object(viewer, "log_event"))
            self.open_report = stack.enter_context(patch.object(viewer, "open_saved_report"))
            window = viewer.open_serial_viewer("ORD-A", assigned_by="tester")
            tree = next(
                w
                for w in self.descendants(window)
                if isinstance(w, ttk.Treeview)
            )
            buttons = {
                w.cget("text"): w
                for w in self.descendants(window)
                if isinstance(w, tk.Button)
            }

            def tick():
                try:
                    if invalid and error.called:
                        self.assertFalse(tree.get_children())
                        self.assertFalse(remove.called)
                        state["complete"] = True
                        root.quit()
                        return
                    ready_empty = any(
                        isinstance(w, tk.Label) and str(w.cget("text")).startswith(
                            ("No serials are", "Could not load")
                        )
                        for w in self.descendants(window)
                    )
                    if not state["started"] and (
                        tree.get_children() or ready_empty
                    ):
                        state["started"] = True
                        action(tree, buttons, cursor, info)
                        if no_mutation:
                            state["complete"] = True
                            root.quit()
                            return
                    if remove_response and not remove_response[0] and error.called:
                        self.assertTrue(tree.get_children())
                        state["complete"] = True
                        root.quit()
                        return
                    if (
                        state["started"]
                        and remove.called
                        and str(buttons["Remove"].cget("state")) == "disabled"
                        and cursor.fetchall.call_count == 2
                        and len(tree.get_children()) == min(
                            viewer.SERIALS_PER_PAGE, len(rows) - 1
                        )
                    ):
                        state["complete"] = True
                        root.quit()
                        return
                    root.after(10, tick)
                except Exception as exc:
                    state["errors"].append(exc)
                    root.quit()

            root.after(10, tick)
            timeout = root.after(4000, root.quit)
            try:
                root.mainloop()
            finally:
                # Dispose the hidden test windows' pending focus callbacks
                # before Tk deletes their registered commands.
                for callback in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", callback)
                window.destroy()
            self.assertFalse(state["errors"], state["errors"])
            self.assertTrue(
                state["complete"], "Viewer action did not complete"
            )
            if not invalid and not load_error and not (
                remove_response and not remove_response[0]
            ):
                error.assert_not_called()
            connection.commit.assert_not_called()
            return remove

    def test_view_and_remove_preserve_zero_only_and_long_numeric_serials(self):
        for serial in [
            "001234",
            "000000",
            "0",
            "000ABC",
            "1e04",
            "123456789012345678901234567890",
        ]:
            with self.subTest(serial=serial):

                def action(tree, buttons, cursor, info):
                    tree.selection_set(tree.get_children()[0])
                    tree.event_generate("<<TreeviewSelect>>")
                    buttons["View Report"].invoke()
                    self.assertEqual(
                        self.open_report.call_args.args[1:], ("ORD-A", serial)
                    )
                    self.open_report.assert_called_once()
                    buttons["Remove"].invoke()

                remove = self.run_viewer([(serial, "SKU", None)], action)
                remove.assert_called_once_with("ORD-A", serial, "tester")

    def test_database_bytes_remain_exact_in_both_actions(self):
        for value in [b"001234", bytearray(b"001234"), memoryview(b"001234")]:
            with self.subTest(value=value):

                def action(tree, buttons, cursor, info):
                    tree.selection_set(tree.get_children()[0])
                    tree.event_generate("<<TreeviewSelect>>")
                    buttons["View Report"].invoke()
                    self.assertEqual(
                        self.open_report.call_args.args[1:], ("ORD-A", "001234")
                    )
                    buttons["Remove"].invoke()

                remove = self.run_viewer([(value, b"SKU", None)], action)
                remove.assert_called_once_with("ORD-A", "001234", "tester")

    def test_page_changes_rebuild_the_identity_mapping(self):
        rows = [(f"{i:06}", "SKU", None) for i in range(21)]

        def action(tree, buttons, cursor, info):
            buttons["Next"].invoke()
            buttons["Previous"].invoke()
            buttons["Next"].invoke()
            tree.selection_set(tree.get_children()[0])
            tree.event_generate("<<TreeviewSelect>>")
            buttons["View Report"].invoke()
            self.assertEqual(
                self.open_report.call_args.args[1:], ("ORD-A", "000020")
            )
            buttons["Remove"].invoke()

        remove = self.run_viewer(rows, action)
        remove.assert_called_once_with("ORD-A", "000020", "tester")

    def test_malformed_database_serials_are_not_selectable(self):
        self.run_viewer(
            [(b"001\xff234", "SKU", None)], lambda *args: None, invalid=True
        )

    def test_empty_and_failed_lists_cannot_view_or_remove(self):
        for load_error in (False, True):
            with self.subTest(load_error=load_error):
                def action(tree, buttons, cursor, info):
                    self.assertFalse(tree.get_children())
                    if load_error:
                        labels = [
                            w.cget("text") for w in self.descendants(tree.winfo_toplevel())
                            if isinstance(w, tk.Label)
                        ]
                        self.assertIn("Unavailable", labels)
                        self.assertNotIn("Loading...", labels)
                    for name in ("Remove", "View Report", "Previous", "Next"):
                        self.assertEqual(buttons[name].cget("state"), "disabled")
                        buttons[name].invoke()
                    self.assertEqual(buttons['Reload list'].cget('state'), 'normal')
                    info.assert_not_called()

                remove = self.run_viewer(
                    [], action, no_mutation=True, load_error=load_error
                )
                remove.assert_not_called()

    def test_actions_require_current_selection_after_page_change(self):
        def action(tree, buttons, cursor, info):
            self.assertEqual(buttons["Remove"].cget("state"), "disabled")
            tree.selection_set(tree.get_children()[0])
            tree.event_generate("<<TreeviewSelect>>")
            self.assertEqual(buttons["Remove"].cget("state"), "normal")
            buttons["Next"].invoke()
            self.assertEqual(buttons["Remove"].cget("state"), "disabled")
            buttons["Remove"].invoke()
            buttons["View Report"].invoke()
            info.assert_not_called()

        remove = self.run_viewer(
            [(f"{i:06}", "SKU", None) for i in range(21)],
            action, no_mutation=True,
        )
        remove.assert_not_called()

    def test_recovered_removal_is_labelled_as_historical(self):
        def action(tree, buttons, cursor, info):
            tree.selection_set(tree.get_children()[0])
            tree.event_generate("<<TreeviewSelect>>")
            buttons["Remove"].invoke()
            self.receipt_info = info

        self.run_viewer(
            [("001234", "SKU", None)], action,
            remove_response=(True, {"success": True, "recovered_pending": True}),
        )
        self.assertEqual(
            self.receipt_info.call_args.args[0], "Previous Removal Confirmed"
        )
        self.assertIn("historical receipt", self.receipt_info.call_args.args[1])

    def test_rejected_removal_retains_exact_serial_and_does_not_write_sql(self):
        def action(tree, buttons, cursor, info):
            tree.selection_set(tree.get_children()[0])
            tree.event_generate("<<TreeviewSelect>>")
            buttons["Remove"].invoke()

        remove = self.run_viewer(
            [("001234", "SKU", None)], action,
            remove_response=(False, {"error": "Assignment has changed"}),
        )
        remove.assert_called_once_with("ORD-A", "001234", "tester")

    def test_closing_during_load_does_not_schedule_tk_from_worker(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        connection = Mock()

        def fetch():
            started.set()
            release.wait(2)
            return [("001234", "SKU", None)]

        connection.cursor.return_value.fetchall.side_effect = fetch
        connection.close.side_effect = finished.set
        errors = []
        root = self.root
        original_handler = root.report_callback_exception
        root.report_callback_exception = lambda *args: errors.append(args)
        with patch.object(viewer, "get_db_connection", return_value=connection):
            window = viewer.open_serial_viewer("ORD-A", assigned_by="tester")
            window.withdraw()

            def tick():
                if started.is_set() and window.winfo_exists():
                    window.destroy()
                    release.set()
                if finished.is_set():
                    root.quit()
                else:
                    root.after(10, tick)

            root.after(10, tick)
            root.after(3000, root.quit)
            try:
                root.mainloop()
                self.assertTrue(finished.is_set())
                self.assertFalse(errors)
            finally:
                release.set()
                root.report_callback_exception = original_handler
                for callback in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", callback)
                if window.winfo_exists():
                    window.destroy()


if __name__ == "__main__":
    unittest.main()
