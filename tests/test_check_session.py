from copy import deepcopy
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import app_controller
from app_controller import AppController
import main_logic
from services.check_results import TEST_KEYS, record_override
from services.check_session import CheckDraftStore, CheckSession, result_state


from operator_fixture import sign_in as setUpModule, sign_out as tearDownModule


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CheckDraftStore(self.temp.name)
        self.session = CheckSession(self.store)
        self.saved = dict.fromkeys(TEST_KEYS, "n/a")

    def test_repeat_search_and_restart_restore_exact_device_order_draft(self):
        current = self.session.activate(10, "ORDER-A", "00123", self.saved)
        current["keyboard"] = "fail"
        record_override(current, "wifi", "pass", "tester", "Checked on bench")
        self.session.preserve(current)
        restarted = CheckSession(self.store)
        draft, conflict = restarted.candidate(10, "00123", self.saved)
        self.assertFalse(conflict)
        restored = restarted.activate(10, "ORDER-A", "00123", self.saved, draft)
        self.assertEqual(result_state(restored), result_state(current))
        self.assertIsNone(restarted.candidate(11, "OTHER", self.saved)[0])
        self.assertIsNone(restarted.candidate(10, "123", self.saved)[0])
        self.assertIsNone(restarted.candidate(10, "00124", self.saved)[0])

    def test_different_order_never_inherits_previous_order_checks(self):
        a = self.session.activate(10, "A", "00123", self.saved)
        a["keyboard"] = "fail"
        self.session.preserve(a)
        b = self.session.activate(11, "B", "00123", self.saved)
        self.assertEqual(b["keyboard"], "n/a")
        self.assertEqual(self.session.candidate(10, "00123", self.saved)[0]["results"]["keyboard"], "fail")

    def test_bench_draft_moves_only_to_the_matching_device_order(self):
        bench = self.session.activate(0, "", "00123", self.saved)
        bench["usb"] = "pass"
        self.session.preserve(bench)
        self.assertIsNone(self.session.candidate(10, "OTHER", self.saved)[0])
        draft, conflict = self.session.candidate(10, "00123", self.saved)
        self.assertFalse(conflict)
        loaded = self.session.activate(10, "A", "00123", self.saved, draft)
        self.assertEqual(loaded["usb"], "pass")
        self.assertIsNone(self.store.load((0, "00123")))
        self.assertIsNone(self.session.candidate(11, "00123", self.saved)[0])

    def test_changed_server_report_is_detected_without_overwriting_draft(self):
        current = self.session.activate(10, "A", "00123", self.saved)
        current["usb"] = "fail"
        self.session.preserve(current)
        newer = dict(self.saved, keyboard="pass")
        draft, conflict = self.session.candidate(10, "00123", newer)
        self.assertTrue(conflict)
        self.assertEqual(draft["results"]["usb"], "fail")
        self.assertEqual(self.store.load((10, "00123"))["baseline"], result_state(self.saved))

    def test_confirmed_upload_clears_draft_but_keeps_later_edits_dirty(self):
        current = self.session.activate(10, "A", "00123", self.saved)
        current["usb"] = "fail"
        self.session.preserve(current)
        uploaded = deepcopy(current)
        current["keyboard"] = "pass"
        self.session.confirmed(10, "00123", uploaded)
        self.assertIsNone(self.store.load((10, "00123")))
        self.session.preserve(current)
        self.assertEqual(self.store.load((10, "00123"))["results"]["keyboard"], "pass")

    def test_invalid_draft_is_preserved_and_raises(self):
        path = self.store._path((10, "00123"))
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.session.candidate(10, "00123", self.saved)
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


class SearchContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        c = self.controller = AppController.__new__(AppController)
        c.root = Mock()
        c.root._assignment_running = False
        c.canvas = Mock()
        c.canvas.winfo_children.return_value = []
        c.canvas.winfo_width.return_value = 900
        c.order_entry = Mock()
        c.order_entry.get.return_value = "external-A"
        c.search_button = Mock()
        c.test_panel_button = Mock()
        c.order_context_label = Mock()
        c.test_results = dict.fromkeys(TEST_KEYS, "n/a")
        c.test_labels = {}
        c.tests_window = None
        c.current_user = SimpleNamespace(username="tester")
        c._check_session = CheckSession(CheckDraftStore(self.temp.name))
        c._lookup_valid = False
        c._search_generation = 0
        c._requested_reference = "external-A"
        c._search_inflight = False
        c._update_order_notes_footer = Mock()
        c._update_hash_capture_status = Mock()
        c._update_results_footer = Mock()
        c.animate_dots = Mock()
        c.update_test_result_labels = Mock()
        self.resolved = {
            "order_id": 10, "order_number": "ORDER-A", "serial_number": "00123",
            "sku": "SKU", "specs": {}, "details": {}, "mdm": {}, "notes": "",
            "footer": None, "test_results": dict(c.test_results),
        }

    def test_failed_lookup_preserves_draft_and_removes_old_actions(self):
        c = self.controller
        c._check_session.activate(10, "ORDER-A", "00123", c.test_results)
        c.test_results["keyboard"] = "fail"
        old_button = Mock()
        c.canvas.winfo_children.return_value = [old_button]
        c._lookup_valid = True
        with patch.object(app_controller, "search_order_logic") as search:
            c.run_search()
        old_button.destroy.assert_called_once()
        self.assertFalse(c._lookup_valid)
        search.call_args.kwargs["on_complete"]()
        self.assertFalse(c._search_inflight)
        c.test_panel_button.config.assert_called_with(state="disabled")
        c.canvas.delete.assert_any_call("search_status")
        self.assertEqual(c._check_session.store.load((10, "00123"))["results"]["keyboard"], "fail")

    def test_resolved_context_survives_edits_but_rejects_new_submissions(self):
        c = self.controller
        c._search_generation = 2
        with patch.object(app_controller, "render_results") as render:
            with patch.object(app_controller, "start_hash_capture_status_update"):
                c._accept_order_search(1, "external-A", self.resolved)
                render.assert_not_called()
                c._accept_order_search(2, "external-A", self.resolved)
        self.assertTrue(c._lookup_valid)
        self.assertEqual(render.call_args.args[1], "ORDER-A")
        guard = render.call_args.kwargs["context_guard"]
        self.assertTrue(guard())
        c.order_entry.get.return_value = "OTHER"
        self.assertTrue(guard())
        self.assertTrue(c._lookup_valid)
        c.test_results['usb'] = 'fail'
        with patch.object(app_controller, 'search_order_logic') as search:
            c.run_search()
        self.assertEqual(search.call_args.args[0], 'OTHER')
        self.assertFalse(guard())
        self.assertFalse(c._lookup_valid)
        self.assertEqual(c._check_session.store.load((10, '00123'))['results']['usb'], 'fail')
        with patch.object(app_controller, 'render_results') as render:
            c._accept_order_search(2, 'external-A', self.resolved)
        render.assert_not_called()

    def test_write_failure_stops_navigation_and_keeps_results(self):
        c = self.controller
        c._check_session.activate(10, "ORDER-A", "00123", c.test_results)
        c.test_results["usb"] = "fail"
        with patch.object(c._check_session.store, "save", side_effect=OSError("disk full")):
            with patch.object(app_controller.messagebox, "showerror"):
                with patch.object(app_controller, "search_order_logic") as search:
                    c.run_search()
        search.assert_not_called()
        self.assertEqual(c.test_results["usb"], "fail")

    def test_active_hardware_test_blocks_context_switch_even_after_panel_close(self):
        c = self.controller
        c._tests_runner = SimpleNamespace(is_busy=lambda: True)
        with patch.object(app_controller.messagebox, "showinfo"):
            with patch.object(app_controller, "search_order_logic") as search:
                c.run_search()
        search.assert_not_called()

    def test_delayed_bench_render_cannot_replace_an_order_lookup(self):
        c = self.controller
        c._showing_default_specs = False
        with patch.object(app_controller, "load_laptop_specs") as load:
            c._render_laptop_specs()
        load.assert_not_called()
        c.root.after.assert_not_called()

    def test_conflicting_draft_restore_discard_and_cancel(self):
        c = self.controller
        for choice in (None, True, False):
            with self.subTest(choice=choice):
                c._lookup_valid = False
                c._search_generation = 2
                baseline = dict.fromkeys(TEST_KEYS, "n/a")
                local = dict(baseline, usb="fail")
                c._check_session.store.save((10, "00123"), local, baseline)
                self.resolved["test_results"] = dict(baseline, keyboard="pass")
                with patch.object(app_controller.messagebox, "askyesnocancel", return_value=choice):
                    with patch.object(app_controller, "render_results") as render:
                        with patch.object(app_controller, "start_hash_capture_status_update"):
                            c._accept_order_search(2, "external-A", self.resolved)
                if choice is None:
                    render.assert_not_called()
                    self.assertFalse(c._lookup_valid)
                    self.assertIsNotNone(c._check_session.store.load((10, "00123")))
                elif choice:
                    self.assertEqual(c.test_results["usb"], "fail")
                else:
                    self.assertEqual(c.test_results["keyboard"], "pass")
                    self.assertIsNone(c._check_session.store.load((10, "00123")))


class LookupIsolationTests(unittest.TestCase):
    def test_worker_does_not_mutate_visible_results_before_delivery(self):
        queued = []
        root = SimpleNamespace(after=lambda delay, callback: queued.append(callback))
        visible = {"keyboard": "fail"}
        conn = Mock()
        callback = Mock()
        thread = lambda target, **kwargs: SimpleNamespace(start=target)
        with ExitStack() as stack:
            stack.enter_context(patch.object(main_logic.threading, "Thread", side_effect=thread))
            for name, value in {
                "get_db_connection": conn,
                "resolve_order_by_order_number": (10, "ORDER-A"),
                "load_order_candidates_for_order_id": [{"label": "SKU", "sku": "SKU"}],
                "load_order_note_for_order_id": "",
                "prompt_for_sku_selection": "SKU",
                "load_laptop_specs": {"Serial Number": "00123"},
                "load_test_results": {"keyboard": "pass"},
                "check_activation_status": True,
                "extract_details_from_sku": {}, "check_mdm_lock_status": {},
            }.items():
                stack.enter_context(patch.object(main_logic, name, return_value=value))
            main_logic.search_order_logic(
                "external-A", Mock(), Mock(), visible, {}, root,
                on_complete=Mock(), on_resolved=callback)
        self.assertEqual(visible, {"keyboard": "fail"})
        callback.assert_not_called()
        for action in queued:
            action()
        self.assertEqual(visible, {"keyboard": "fail"})
        self.assertEqual(callback.call_args.args[0]["test_results"]["keyboard"], "pass")

    def test_lookup_failure_paths_complete_without_replacing_checks(self):
        for failure in ("database", "notfound", "fallback", "empty", "cancel", "report"):
            with self.subTest(failure=failure), ExitStack() as stack:
                queued = []
                root = SimpleNamespace(after=lambda delay, action: queued.append(action))
                visible = {"keyboard": "fail"}
                done, resolved = Mock(), Mock()
                thread = lambda target, **kwargs: SimpleNamespace(start=target)
                stack.enter_context(patch.object(main_logic.threading, "Thread", side_effect=thread))
                for name, value in {
                    "get_db_connection": None if failure == "database" else Mock(),
                    "resolve_order_by_order_number": None if failure in {"notfound", "fallback"} else (10, "A"),
                    "prompt_for_marketplace_search": failure == "fallback",
                    "resolve_order_by_external_id": None,
                    "load_order_candidates_for_order_id": [] if failure == "empty" else [{"label": "SKU", "sku": "SKU"}],
                    "load_order_note_for_order_id": "",
                    "prompt_for_sku_selection": None if failure == "cancel" else "SKU",
                    "load_laptop_specs": {"Serial Number": "00123"},
                }.items():
                    stack.enter_context(patch.object(main_logic, name, return_value=value))
                stack.enter_context(patch.object(main_logic, "load_test_results", side_effect=ValueError("report unavailable")))
                stack.enter_context(patch.object(main_logic.messagebox, "showerror"))
                stack.enter_context(patch.object(main_logic.messagebox, "showinfo"))
                main_logic.search_order_logic("external-A", Mock(), Mock(), visible,
                                             {}, root, on_complete=done,
                                             on_resolved=resolved)
                for action in queued:
                    action()
                done.assert_called_once()
                resolved.assert_not_called()
                self.assertEqual(visible, {"keyboard": "fail"})
