import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services import assignment_api as api


def reply(status=200, **body):
    return Mock(status_code=status, json=lambda: body)


class AssignmentTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pending = Path(self.temp.name)
        self.patch(api, "_pending_directory", return_value=self.pending)
        self.patch(api.time, "sleep")
        self.get = self.patch(
            api.requests,
            "get",
            return_value=reply(success=True, transactional_assignments=1, operator_sessions=1),
        )
        self.post = self.patch(api.requests, "post")
        self.payload = {
            "serial_number": "001234",
            "order_number": "ORD-A",
            "checked_at": "old",
        }

    def patch(self, obj, name, **kwargs):
        patcher = patch.object(obj, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def send(self, **kwargs):
        return api.post_assignment(
            "https://isolated",
            "test-key",
            "/api/stock_units/check-report",
            self.payload,
            **kwargs
        )

    def success(self, *args, **kwargs):
        return reply(success=True, operation_id=kwargs["json"]["operation_id"])

    def test_timeout_retries_the_exact_operation(self):
        sent = []

        def post(*args, **kwargs):
            sent.append(kwargs["json"].copy())
            if len(sent) == 1:
                raise api.requests.Timeout("response lost")
            return self.success(*args, **kwargs)

        self.post.side_effect = post
        self.assertTrue(self.send()[0])
        self.assertEqual(sent[0], sent[1])
        self.assertFalse(list(self.pending.glob("*.json")))

    def test_result_policy_requires_matching_server_before_sending(self):
        self.payload["result_policy_version"] = 1
        ok, error = self.send()
        self.assertFalse(ok)
        self.assertIn("recorded result reviews", error["error"])
        self.post.assert_not_called()

    def test_local_mdm_evidence_requires_matching_server_before_sending(self):
        self.payload["mdm"] = {"evidence_version": 1}
        ok, error = self.send()
        self.assertFalse(ok)
        self.assertIn("qualified local MDM evidence", error["error"])
        self.post.assert_not_called()

    def test_review_time_is_not_a_changed_decision_but_reason_is(self):
        first = dict(self.payload, assignment_review={
            "operator": "tester", "at": "first", "reason": "Bench approved",
        })
        newer = dict(first, assignment_review=dict(first["assignment_review"], at="later"))
        self.assertEqual(api._intent_hash("report", first), api._intent_hash("report", newer))
        newer["assignment_review"]["reason"] = "A different decision"
        self.assertNotEqual(api._intent_hash("report", first), api._intent_hash("report", newer))

    def test_restart_keeps_uncertain_request_and_reconciles_receipt(self):
        self.post.side_effect = api.requests.Timeout("offline")
        self.get.side_effect = [
            reply(success=True, transactional_assignments=1, operator_sessions=1),
            reply(404, success=False),
        ]
        ok, error = self.send()
        self.assertFalse(ok)
        stored = json.loads(next(self.pending.glob("*.json")).read_text())
        self.assertNotIn("test-key", json.dumps(stored))
        self.assertEqual(
            error["operation_id"], stored["payload"]["operation_id"]
        )
        self.payload["checked_at"] = "new capture time"
        self.get.side_effect = [
            reply(success=True, transactional_assignments=1, operator_sessions=1),
            reply(success=True, operation_id=error["operation_id"]),
        ]
        self.post.reset_mock()
        self.assertTrue(self.send()[0])
        self.post.assert_not_called()

    def test_changed_target_cannot_be_reported_as_old_success(self):
        self.post.side_effect = api.requests.Timeout("offline")
        self.get.side_effect = [
            reply(success=True, transactional_assignments=1, operator_sessions=1),
            reply(404, success=False),
        ]
        self.assertFalse(self.send()[0])
        self.payload["order_number"] = "ORD-B"
        self.get.side_effect = [
            reply(success=True, transactional_assignments=1, operator_sessions=1),
            reply(404, success=False),
        ]
        self.post.side_effect = self.success
        ok, result = self.send()
        self.assertFalse(ok)
        self.assertIn("Previous operation was confirmed", result["error"])
        self.assertEqual(
            self.post.call_args.kwargs["json"]["order_number"], "ORD-A"
        )

    def test_reassignment_needs_confirmation_and_token(self):
        calls = []

        def post(*args, **kwargs):
            calls.append(kwargs["json"].copy())
            if len(calls) == 1:
                return reply(
                    409,
                    success=False,
                    code="assignment_conflict",
                    conflicts=["order ORD-B"],
                    reassignment_token="snapshot",
                )
            return self.success(*args, **kwargs)

        self.post.side_effect = post
        prompt = Mock(return_value=True)
        self.assertTrue(self.send(reassignment_prompt=prompt)[0])
        prompt.assert_called_once_with(["order ORD-B"])
        self.assertEqual(calls[1]["reassignment_token"], "snapshot")
        self.assertNotEqual(calls[0]["operation_id"], calls[1]["operation_id"])

    def test_declined_move_does_not_post_again(self):
        self.post.return_value = reply(
            409,
            success=False,
            code="assignment_conflict",
            conflicts=["order ORD-B"],
            reassignment_token="snapshot",
        )
        self.assertFalse(self.send(reassignment_prompt=lambda _: False)[0])
        self.assertEqual(self.post.call_count, 1)
        self.assertFalse(list(self.pending.glob("*.json")))

    def test_old_server_cannot_receive_a_mutation(self):
        self.get.return_value = reply(404)
        self.assertFalse(self.send()[0])
        self.post.assert_not_called()

    def test_unrecognised_receipt_keeps_the_pending_operation(self):
        self.post.return_value = reply(success=True, operation_id="wrong-id")
        self.assertFalse(self.send()[0])
        self.assertTrue(list(self.pending.glob("*.json")))

    def test_another_process_cannot_replace_an_in_flight_journal(self):
        path = self.pending / "device.json"
        with api._journal_lock(path):
            with self.assertRaises(OSError):
                with api._journal_lock(path):
                    self.fail("Second lock should be rejected")
        with api._journal_lock(path):
            pass

    def test_retired_endpoint_cannot_receive_a_new_mutation(self):
        ok, error = api.post_assignment(
            "https://isolated", "test-key",
            "/jobs/api/second-check/trade-report", self.payload,
        )
        self.assertFalse(ok)
        self.assertIn("order operations only", error["error"])
        self.get.assert_not_called()
        self.post.assert_not_called()
        self.assertFalse(list(self.pending.glob("*.json")))

    def test_pending_retired_request_is_never_resent_or_discarded(self):
        self.post.side_effect = api.requests.Timeout("offline")
        self.get.side_effect = [
            reply(success=True, transactional_assignments=1, operator_sessions=1),
            reply(404, success=False),
        ]
        self.assertFalse(self.send()[0])
        path = next(self.pending.glob("*.json"))
        stored = json.loads(path.read_text())
        stored["endpoint"] = "/jobs/api/second-check/trade-report"
        stored["intent"] = "retired-workflow"
        path.write_text(json.dumps(stored))
        self.post.reset_mock()
        self.get.side_effect = [
            reply(success=True, transactional_assignments=1, operator_sessions=1),
            reply(404, success=False),
        ]
        ok, error = self.send()
        self.assertFalse(ok)
        self.assertIn("retired workflow", error["error"])
        self.post.assert_not_called()
        self.assertEqual(json.loads(path.read_text()), stored)

        # An existing server receipt can be reconciled without resending it,
        # but must not be reported as success for the new order request.
        self.get.side_effect = [
            reply(success=True, transactional_assignments=1, operator_sessions=1),
            reply(success=True, operation_id=stored["payload"]["operation_id"]),
        ]
        ok, error = self.send()
        self.assertFalse(ok)
        self.assertIn("Previous operation was confirmed", error["error"])
        self.post.assert_not_called()
        self.assertFalse(path.exists())


class SerialRemovalTests(unittest.TestCase):
    def test_hidden_serial_viewer_removes_the_exact_identifier_via_api(self):
        from logic import view_serials_logic as viewer

        root = tk.Tk()
        root.withdraw()
        original_toplevel = tk.Toplevel
        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchall.side_effect = [[("001234", "SKU", None)], []]
        errors = []
        completed = []
        started = []

        def hidden_window(*args, **kwargs):
            window = original_toplevel(*args, **kwargs)
            window.withdraw()
            return window

        def children(widget):
            for child in widget.winfo_children():
                yield child
                yield from children(child)

        with patch.object(
            viewer.tk, "Toplevel", side_effect=hidden_window
        ), patch.object(
            viewer, "get_db_connection", return_value=connection
        ), patch.object(
            viewer,
            "unassign_order_serial",
            return_value=(True, {"success": True}),
        ) as remove, patch.object(
            viewer.messagebox, "askyesno", return_value=True
        ) as confirm, patch.object(
            viewer.messagebox, "showerror"
        ) as show_error, patch.object(
            viewer, "log_event"
        ):
            window = viewer.open_serial_viewer("ORD-A", assigned_by="tester")
            self.assertEqual(window.title(), "Assigned Serial Numbers — ORD-A")

            def check():
                try:
                    tree = next(
                        w
                        for w in children(window)
                        if isinstance(w, ttk.Treeview)
                    )
                    items = tree.get_children()
                    if not started and items:
                        # Tk changes the displayed value; the API must still
                        # receive the original six-character identifier.
                        self.assertEqual(
                            tree.item(items[0])["values"][0], 1234
                        )
                        tree.selection_set(items[0])
                        tree.event_generate("<<TreeviewSelect>>")
                        started.append(True)
                        next(
                            w
                            for w in children(window)
                            if isinstance(w, tk.Button)
                            and w.cget("text") == "Remove"
                        ).invoke()
                    if started and not items and remove.called:
                        completed.append(True)
                        root.quit()
                        return
                    root.after(10, check)
                except Exception as exc:
                    errors.append(exc)
                    root.quit()

            root.after(10, check)
            root.after(4000, root.quit)
            try:
                root.mainloop()
            finally:
                for callback in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", callback)
                root.destroy()
            self.assertFalse(errors, errors)
            self.assertTrue(completed, "Serial removal did not complete")
            remove.assert_called_once_with("ORD-A", "001234", "tester")
            confirm.assert_called_once_with(
                "Confirm", "Remove serial '001234' from order 'ORD-A'?"
            )
            show_error.assert_not_called()
            connection.commit.assert_not_called()
            for call in cursor.execute.call_args_list:
                self.assertTrue(
                    call.args[0].lstrip().upper().startswith("SELECT")
                )


if __name__ == "__main__":
    unittest.main()
