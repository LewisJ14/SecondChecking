"""The desktop always uses order search, even with legacy trade settings."""

import gc
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app_controller
import main_logic
from app_controller import AppController


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


from operator_fixture import sign_in as setUpModule, sign_out as tearDownModule


class OrderSearchTests(unittest.TestCase):
    def test_search_dispatches_only_to_orders_with_legacy_mode_attribute(self):
        controller = AppController.__new__(AppController)
        controller.current_mode = "trade"  # State left by an older client.
        controller.order_entry = Mock()
        controller.order_entry.get.return_value = "test"
        controller.root = Mock()
        controller.canvas = Mock()
        controller.canvas.winfo_width.return_value = 900
        controller.canvas.winfo_children.return_value = []
        controller.search_button = Mock()
        controller.test_panel_button = Mock()
        controller.test_results = {}
        controller.test_labels = {}
        controller.current_user = SimpleNamespace(username="tester")
        controller.animate_dots = Mock()
        controller._update_hash_capture_status = Mock()
        controller._update_order_notes_footer = Mock()
        controller.update_test_result_labels = Mock()
        with patch.object(app_controller, "search_order_logic") as search:
            with patch.object(app_controller, "log_event"):
                controller.run_search()
        self.assertEqual(search.call_args.args[0], "test")
        self.assertEqual(search.call_args.args[6], "tester")
        search.call_args.kwargs["on_complete"]()
        controller.search_button.config.assert_called_with(state="normal")

    def test_invalid_reference_never_starts_a_search(self):
        controller = AppController.__new__(AppController)
        controller.root = Mock()
        controller._preserve_check_draft = Mock(return_value=True)
        controller._invalidate_order_context = Mock()
        controller.order_entry = Mock()
        controller.order_entry.get.return_value = "bad reference!"
        with patch.object(app_controller, "search_order_logic") as search:
            with patch.object(app_controller.messagebox, "showerror") as error:
                with patch.object(app_controller, "log_event"):
                    controller.run_search()
        search.assert_not_called()
        self.assertIn("order number", error.call_args.args[1])


class OrderInterfaceTests(unittest.TestCase):
    def test_header_and_notes_are_orders_only_without_loading_saved_mode(self):
        if not os.environ.get("SECOND_CHECK_ORDER_UI_TEST_CHILD"):
            # ttkbootstrap caches its style for the lifetime of one Tk app.
            # Exercise a real fresh app, independently of other tests' roots.
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "OrderInterfaceTests.test_header_and_notes_are_orders_only_without_loading_saved_mode"],
                env=dict(os.environ, SECOND_CHECK_ORDER_UI_TEST_CHILD="1"),
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        gc.collect()
        root = tk.Tk()
        root.withdraw()
        try:
            with patch.object(app_controller, "reset_specs_cache"):
                with patch.object(app_controller, "LoginPanel"):
                    with patch.object(app_controller, "UpdateService") as service:
                        service.return_value.current_version = "test"
                        controller = AppController(root)
            controller._render_laptop_specs = Mock()
            controller.check_for_updates = Mock()
            controller._center_current_window = Mock()
            controller._refresh_primary_battery_state = Mock()
            controller._build_ui()
            self.assertEqual(controller.search_button.cget("text"), "Search Order")
            self.assertFalse(hasattr(controller, "mode_selector"))
            controller._update_order_notes_footer("", 1, "test")
            self.assertEqual(
                controller.order_notes_footer.get("1.0", "end").strip(),
                "No notes attached to this order.",
            )
            with patch.object(main_logic, "start_serial_assignment") as start:
                with patch.object(main_logic, "assign_serial_logic") as assign:
                    with patch.object(main_logic, "open_serial_viewer") as view:
                        with patch.object(main_logic, "log_event"):
                            app_controller.render_results(
                                controller.canvas, "test", "SKU", "001234",
                                {}, {}, {}, {}, "tester", True, "", root,
                            )
                        actions = {
                            w.cget("text"): w
                            for w in _descendants(controller.canvas)
                            if w.winfo_class() == "TButton"
                        }
                        actions["Assign Serial"].invoke()
                        start.call_args.args[2]()
                        self.assertEqual(assign.call_args.args[:2], ("test", "001234"))
                        actions["View Serials"].invoke()
                        view.assert_called_once_with("test", assigned_by="tester")
        finally:
            for callback in root.tk.call("after", "info"):
                root.tk.call("after", "cancel", callback)
            root.destroy()
            gc.collect()


if __name__ == "__main__":
    unittest.main()
