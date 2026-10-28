import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.check_results import (
    TEST_KEYS, badge_text, clear_override, needs_reason, record_override,
    review_lines, snapshot, start_measurement,
)
import main_logic
import test_review_fixes


class ResultHistoryTests(unittest.TestCase):
    def test_override_preserves_measurement_and_superseded_decisions(self):
        results = dict.fromkeys(TEST_KEYS, "pass")
        results["wifi"] = "unavailable"
        record_override(results, "wifi", "pass", "tester", "External adapter checked")
        self.assertEqual(badge_text(results, "wifi"), "OVERRIDDEN PASS")
        self.assertTrue(needs_reason(results))
        record_override(results, "wifi", "fail", "reviewer", "Adapter disconnected")
        events = results["_overrides"]["wifi"]
        self.assertEqual(events[-1]["measured_result"], "unavailable")
        self.assertEqual(events[-1]["previous_result"], "pass")
        self.assertFalse(events[0]["active"])
        clear_override(results, "wifi")
        results["wifi"] = "pass"
        self.assertEqual(badge_text(results, "wifi"), "PASS")
        self.assertFalse(needs_reason(results))
        self.assertEqual(len(snapshot(results)[1]["wifi"]), 2)

    def test_empty_override_reason_or_identity_never_changes_result(self):
        for operator, reason in [("tester", " "), (None, "checked")]:
            results = {"wifi": "fail"}
            with self.assertRaises(ValueError):
                record_override(results, "wifi", "pass", operator, reason)
            self.assertEqual(results, {"wifi": "fail"})

    def test_retest_clears_only_its_own_unknown_legacy_history(self):
        results = {"wifi": "pass", "_history_unknown": ["wifi", "keyboard"],
                   "_provenance_unknown": True}
        self.assertIn("HISTORY UNKNOWN", badge_text(results, "wifi"))
        start_measurement(results, "wifi")
        self.assertEqual(badge_text(results, "wifi"), "PASS")
        self.assertEqual(results["_history_unknown"], ["keyboard"])
        self.assertTrue(results["_provenance_unknown"])

    def test_summary_distinguishes_non_pass_outcomes_and_activation(self):
        results = dict(zip(TEST_KEYS, ["fail", "cancelled", "unavailable",
                                     "error", "Not Run", "pass", "pass", "fail"]))
        summary = "\n".join(review_lines(results))
        for expected in ["Failed: Keyboard, Activation", "Cancelled: Speaker",
                         "Unavailable: Microphone", "Incomplete: Webcam",
                         "Test errors: Display"]:
            self.assertIn(expected, summary)

    def test_readback_restores_wifi_override_and_fresh_search_clears_history(self):
        results = {"wifi": "fail"}
        record_override(results, "wifi", "pass", "tester", "Verified manually")
        with patch.object(main_logic, "load_saved_check_results", return_value={
            "found": True, "provenance_known": True,
            "test_results": {"wifi": "pass"},
            "test_overrides": results["_overrides"],
        }):
            loaded = main_logic.load_test_results(Mock(), "ORDER", "00123")
        self.assertEqual(badge_text(loaded, "wifi"), "OVERRIDDEN PASS")
        with patch.object(main_logic, "load_saved_check_results",
                          return_value={"found": False}):
            loaded.update(main_logic.load_test_results(Mock(), "OTHER", "00123"))
        self.assertEqual(loaded["_overrides"], {})
        self.assertEqual(loaded["wifi"], "Not Run")


class AssignmentReviewTests(unittest.TestCase):
    setUp = test_review_fixes.AssignmentTests.setUp
    assign_order = test_review_fixes.AssignmentTests.assign_order
    assert_no_direct_assignment = test_review_fixes.AssignmentTests.assert_no_direct_assignment

    def test_failed_check_requires_reason_and_cancel_never_uploads(self):
        self.results["keyboard"] = "fail"
        with patch.object(main_logic, "prompt_assignment_review", return_value=None) as prompt:
            with patch.object(main_logic, "upload_stock_unit_check_report") as upload:
                self.assign_order()
        self.assertIn("Failed: Keyboard", prompt.call_args.args[1])
        upload.assert_not_called()

    def test_reason_and_snapshot_are_uploaded_with_override(self):
        self.results["wifi"] = "unavailable"
        record_override(self.results, "wifi", "pass", "tester", "Bench adapter checked")
        self.results["activation"] = "cancelled"
        self.results['_coverage'] = {'usb': {
            'version': 1, 'checked_at': '2026-10-22T12:00:00Z',
            'scope': 'Removable detection only',
            'details': {'required_ports': ['Left'],
                        'observed_ports': {'Left': ['E:']}}}}
        with patch.object(main_logic, "prompt_assignment_review", return_value="Bench exception approved"):
            with patch.object(main_logic, "upload_stock_unit_check_report",
                              return_value=(True, {"success": True})) as upload:
                self.assign_order()
        saved = upload.call_args.kwargs
        self.assertEqual(saved["assignment_review"]["reason"], "Bench exception approved")
        self.assertEqual(saved["test_results"]["activation"], "cancelled")
        self.assertEqual(saved["test_overrides"]["wifi"][0]["measured_result"], "unavailable")
        self.assertEqual(saved['test_coverage'], self.results['_coverage'])
        self.assert_no_direct_assignment()
