from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.mdm_evidence import evidence, qualified, summary, needs_review
from services import assignment_api
from utils import helpers
import main_logic
import test_review_fixes


class RegistryEvidenceTests(unittest.TestCase):
    def capture(self, values=None, open_error=None, correlation_error=None):
        values = values or {}
        def open_key(parent, name, *args):
            if name == "EstablishedCorrelations":
                if correlation_error:
                    raise correlation_error
                return "correlations"
            if open_error:
                raise open_error
            return "autopilot"

        def query(handle, name):
            value = values.get(name)
            if isinstance(value, Exception):
                raise value
            if value is None:
                raise FileNotFoundError(name)
            return value, 1

        registry = SimpleNamespace(
            HKEY_LOCAL_MACHINE="HKLM", KEY_READ=1, KEY_WOW64_64KEY=256,
            OpenKey=Mock(side_effect=open_key), QueryValueEx=Mock(side_effect=query),
            CloseKey=Mock(),
        )
        with patch.dict(sys.modules, winreg=registry):
            with patch.object(helpers.sys, "platform", "win32"):
                with patch.object(helpers, "log_event"):
                    result = helpers.check_mdm_lock_status()
        self.assertEqual(result["tenant_verification"], "not_checked")
        self.assertIsNotNone(datetime.fromisoformat(result["checked_at"]).utcoffset())
        self.assertEqual(registry.OpenKey.call_args_list[0].args[3], 257)
        return result, registry

    def test_missing_key_and_empty_key_are_only_negative_local_observations(self):
        for options in ({"open_error": FileNotFoundError()}, {}):
            result, _ = self.capture(**options)
            self.assertEqual(result["state"], "no_local_indicators")
            text, color = summary(result)
            self.assertIn("does not establish", text)
            self.assertIn("NOT VERIFIED", text)
            self.assertNotEqual(color, "#1f7a4d")

    def test_domain_or_correlation_alone_counts_as_evidence_not_a_proven_lock(self):
        for name in ("CloudAssignedTenantId", "CloudAssignedTenantDomain",
                     "EntDMID", "ZTDRegistrationID"):
            result, registry = self.capture({name: "observed-value"})
            self.assertEqual(result["state"], "local_indicators")
            self.assertEqual(result["observations"], {name: "observed-value"})
            self.assertTrue(needs_review(result))
            self.assertEqual(registry.CloseKey.call_count, 2)

    def test_permission_errors_and_partial_reads_cannot_report_no_indicators(self):
        for options in (
            {"open_error": PermissionError("denied")},
            {"values": {"CloudAssignedTenantId": PermissionError("denied")}},
            {"correlation_error": PermissionError("denied")},
            {"values": {"CloudAssignedTenantId": 123}},
        ):
            result, _ = self.capture(**options)
            self.assertEqual(result["state"], "error")
            self.assertTrue(result["read_errors"])
        result, _ = self.capture({"CloudAssignedTenantId": "id",
                                  "ZTDRegistrationID": PermissionError("denied")})
        self.assertEqual(result["state"], "local_indicators")
        self.assertTrue(result["read_errors"])

    def test_refresh_is_read_only_and_does_not_treat_policy_refresh_as_verification(self):
        with patch.object(helpers, "run_mdm_policy_commands") as policy:
            with patch.object(helpers, "check_mdm_lock_status", return_value={"test": True}):
                self.assertEqual(helpers.refresh_mdm_lock_status(), {"test": True})
        policy.assert_not_called()
        with patch.object(helpers.sys, "platform", "linux"):
            self.assertEqual(helpers.check_mdm_lock_status()["state"], "unsupported")

    def test_legacy_and_malformed_status_never_becomes_tenant_clear(self):
        for status in (None, [], {"state": "not_locked"}, {"state": "locked"},
                       {"evidence_version": 1, "state": []}):
            result = qualified(status)
            self.assertEqual(result["state"], "unknown")
            self.assertIsNone(result["checked_at"])
            self.assertIn("NOT VERIFIED", summary(result)[0])

    def test_repeat_capture_time_does_not_change_retry_intent_but_evidence_does(self):
        first = {"mdm": evidence("no_local_indicators", "No indicators")}
        second = {"mdm": dict(first["mdm"], checked_at="another capture time")}
        self.assertEqual(assignment_api._intent_hash("order", first),
                         assignment_api._intent_hash("order", second))
        second["mdm"]["state"] = "error"
        self.assertNotEqual(assignment_api._intent_hash("order", first),
                            assignment_api._intent_hash("order", second))


class AssignmentMdmTests(unittest.TestCase):
    setUp = test_review_fixes.AssignmentTests.setUp
    assign_order = test_review_fixes.AssignmentTests.assign_order

    def test_final_review_uploads_fresh_qualified_evidence_and_requires_reason(self):
        current = evidence("local_indicators", "Domain observed",
                           observations={"CloudAssignedTenantDomain": "example.invalid"})
        with ExitStack() as stack:
            stack.enter_context(patch.object(main_logic, "check_mdm_lock_status", return_value=current))
            prompt = stack.enter_context(patch.object(main_logic, "prompt_assignment_review", return_value="Quarantined for investigation"))
            upload = stack.enter_context(patch.object(main_logic, "upload_stock_unit_check_report", return_value=(True, {"success": True})))
            main_logic.assign_serial_logic("ORD-1", "TEST", {}, self.results, "SKU",
                                           {"state": "not_locked"}, "tester", Mock())
        self.assertTrue(prompt.call_args.args[2])
        self.assertIn("Tenant registration / enrolment: NOT VERIFIED", prompt.call_args.args[1])
        self.assertEqual(upload.call_args.kwargs["mdm_status"], current)
        self.assertEqual(upload.call_args.kwargs["assignment_review"]["reason"], "Quarantined for investigation")
