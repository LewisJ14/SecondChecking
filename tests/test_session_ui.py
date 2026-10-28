"""Real Tk acceptance for draft restoration and stale action removal."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app_controller
import main_logic
from app_controller import AppController
from services.check_results import TEST_KEYS
from services.check_session import CheckDraftStore, CheckSession
from services.mdm_evidence import evidence
from services.storage import inventory, inventory_label
from services.measurements import utc_now


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


from operator_fixture import sign_in as setUpModule, sign_out as tearDownModule


class SessionInterfaceTests(unittest.TestCase):
    def test_edits_keep_loaded_order_and_submitted_lookup_restores_draft(self):
        if not os.environ.get("SECOND_CHECK_SESSION_UI_CHILD"):
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "SessionInterfaceTests.test_edits_keep_loaded_order_and_submitted_lookup_restores_draft"],
                env=dict(os.environ, SECOND_CHECK_SESSION_UI_CHILD="1"),
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        root = tk.Tk()
        root.withdraw()
        try:
            with TemporaryDirectory() as directory:
                with patch.object(app_controller, "reset_specs_cache"):
                    with patch.object(app_controller, "LoginPanel"):
                        with patch.object(app_controller, "UpdateService") as service:
                            service.return_value.current_version = "test"
                            c = AppController(root)
                c.current_user = SimpleNamespace(username="tester")
                c._render_laptop_specs = Mock()
                c.check_for_updates = Mock()
                c._center_current_window = Mock()
                c._refresh_primary_battery_state = Mock()
                c._build_ui()
                for state in ("no_local_indicators", "local_indicators", "error"):
                    c.mdm_status = evidence(state, "Local registry observation")
                    c._apply_mdm_status_to_footer_only()
                    self.assertIn("NOT VERIFIED", c.mdm_footer.cget("text"))
                    self.assertNotIn("registry", c.mdm_footer.cget("text"))
                    self.assertNotIn("Captured:", c.mdm_footer.cget("text"))
                    self.assertNotEqual(c.mdm_footer.cget("fg"), "#1f7a4d")
                c._check_session = CheckSession(CheckDraftStore(directory))
                c.order_reference.set("external-A")
                c._search_generation = 1
                c._requested_reference = "external-A"
                data = {
                    "order_id": 10, "order_number": "ORDER-A",
                    "serial_number": "00123", "sku": "SKU", "specs": {},
                    "details": {}, "mdm": {}, "notes": "", "footer": None,
                    "test_results": dict.fromkeys(TEST_KEYS, "n/a"),
                }
                with patch.object(app_controller, "start_hash_capture_status_update"):
                    c._accept_order_search(1, "external-A", data)
                    root.update()
                    old_actions = [w for w in _descendants(c.canvas) if w.winfo_class() == "TButton"]
                    self.assertEqual(len(old_actions), 2)
                    c._lookup_valid = False
                    with patch.object(main_logic, "start_serial_assignment") as assign:
                        with patch.object(main_logic, "open_serial_viewer") as view:
                            with patch.object(main_logic.messagebox, "showwarning") as warning:
                                for button in old_actions:
                                    button.invoke()
                    assign.assert_not_called()
                    view.assert_not_called()
                    self.assertEqual(warning.call_count, 2)
                    c._lookup_valid = True
                    texts = [w.cget("text") for w in _descendants(c.canvas)
                             if w.winfo_class() == "Label"]
                    self.assertTrue(any("Order: ORDER-A" in text for text in texts))
                    c.test_results["keyboard"] = "fail"
                    c.order_reference.set("bad!")
                    self.assertTrue(c._lookup_valid)
                    self.assertTrue(all(button.winfo_exists() for button in old_actions))
                    self.assertIn('Loaded order: ORDER-A', c.order_context_label.cget('text'))
                    with patch.object(main_logic, 'start_serial_assignment') as assign, \
                            patch.object(main_logic, 'open_serial_viewer') as view:
                        for button in old_actions:
                            button.invoke()
                    assign.assert_called_once()
                    view.assert_called_once_with('ORDER-A', assigned_by='tester')
                    with patch.object(app_controller.messagebox, "showerror"):
                        c.run_search()
                    self.assertTrue(c._lookup_valid)
                    self.assertTrue(all(button.winfo_exists() for button in old_actions))
                    c.order_reference.set("missing")
                    with patch.object(app_controller, "search_order_logic") as search:
                        c.run_search()
                        search.call_args.kwargs["on_complete"]()
                    self.assertTrue(all(not button.winfo_exists() for button in old_actions))
                    self.assertEqual(c._check_session.store.load((10, "00123"))["results"]["keyboard"], "fail")
                    self.assertFalse(c._search_inflight)
                    self.assertFalse(c.canvas.find_withtag("search_status"))
                    self.assertEqual(c.canvas.winfo_children(), [])
                    self.assertEqual(str(c.test_panel_button.cget("state")), "disabled")
                    c.order_reference.set("external-A")
                    with patch.object(app_controller, "search_order_logic") as search:
                        c.run_search()
                        search.call_args.kwargs["on_resolved"](data)
                        search.call_args.kwargs["on_complete"]()
                    self.assertTrue(c._lookup_valid)
                    self.assertEqual(c.test_results["keyboard"], "fail")
                    self.assertIn("Local draft restored", c.order_context_label.cget("text"))
                    self.assertEqual(len([w for w in _descendants(c.canvas) if w.winfo_class() == "TButton"]), 2)
                    raw = inventory([
                        SimpleNamespace(DeviceID="disk0", Size=512000000000, SerialNumber="one"),
                        SimpleNamespace(DeviceID="disk1", Size=512000000000, SerialNumber="two"),
                    ])
                    data["specs"] = {"SSD": inventory_label(raw), "Storage": raw}
                    data["details"] = {"SSD": "512GB"}
                    c._accept_order_search(c._search_generation, "external-A", data)
                    self.assertEqual(c.canvas._comparison_status["SSD"].cget("text"), "REVIEW")
                    data["details"]["SSD"] = "512GB+512GB"
                    c._accept_order_search(c._search_generation, "external-A", data)
                    self.assertEqual(c.canvas._comparison_status["SSD"].cget("text"), "MATCH")
                    refreshed = dict(data["specs"], **{
                        "Serial Number": "00123", "Resolution": "1280x720",
                        "Measurements": {"version": 1, "checked_at": utc_now(),
                                         "battery_source": "Fixture"},
                        "Battery": "Unreadable (battery health)",
                    })
                    thread = lambda target, **kwargs: SimpleNamespace(start=target)
                    c.order_reference.set('unsubmitted-next-order')
                    with patch.object(app_controller.threading, "Thread", side_effect=thread):
                        with patch.object(app_controller, "load_laptop_specs", return_value=refreshed) as capture:
                            with patch.object(app_controller, "check_mdm_lock_status", return_value=evidence("no_local_indicators", "Fixture")):
                                c.refresh_device_button.invoke()
                                self.assertTrue(c._search_inflight)
                                root.update()
                    capture.assert_called_once_with(force_refresh=True)
                    self.assertFalse(c._search_inflight)
                    self.assertTrue(c._lookup_valid)
                    self.assertEqual(c._requested_reference, 'external-A')
                    self.assertEqual(c.order_entry.get(), 'unsubmitted-next-order')
                    self.assertIn('Loaded order: ORDER-A', c.order_context_label.cget('text'))
                    self.assertEqual(c.test_results["keyboard"], "fail")
                    self.assertEqual(c._visible_specs["Resolution"], "1280x720")
                    self.assertIn("Age:", c.measurement_label.cget("text"))
                    self.assertNotIn("WMI", c.measurement_label.cget("text"))
                    self.assertEqual(c._visible_specs["Measurements"]["battery_source"], "Fixture")
        finally:
            for callback in root.tk.call("after", "info"):
                root.tk.call("after", "cancel", callback)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
