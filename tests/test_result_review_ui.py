"""Exercise actual Tk controls in a fresh, hidden interpreter."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hardwaretests.display import run_display_test
from services.check_results import TEST_KEYS, record_override
from ui import assignment_review
from ui.tests import TestsWindow


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


from operator_fixture import sign_in as setUpModule, sign_out as tearDownModule


class ReviewInterfaceTests(unittest.TestCase):
    def test_override_reason_review_cancel_and_display_close(self):
        if not os.environ.get("SECOND_CHECK_RESULT_UI_CHILD"):
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "ReviewInterfaceTests.test_override_reason_review_cancel_and_display_close"],
                env=dict(os.environ, SECOND_CHECK_RESULT_UI_CHILD="1"),
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        root = tk.Tk()
        root.withdraw()
        original_toplevel = tk.Toplevel

        def hidden_toplevel(*args, **kwargs):
            window = original_toplevel(*args, **kwargs)
            window.withdraw()
            return window

        try:
            with patch.object(tk, "Toplevel", side_effect=hidden_toplevel):
                with patch.object(TestsWindow, "run_test_threaded"):
                    results = dict.fromkeys(TEST_KEYS, "pass")
                    results["wifi"] = "fail"
                    record_override(results, "wifi", "pass", "tester", "Bench checked")
                    panel = TestsWindow(root, results, {}, operator="tester")
                    root.update()
                    self.assertEqual(panel.test_labels["wifi_label"].cget("text"), "OVERRIDDEN PASS")
                    panel.show_override_dialog("wifi", "Wi-Fi")
                    dialog = next(w for w in descendants(panel.tests_window)
                                  if isinstance(w, original_toplevel))
                    widgets = list(descendants(dialog))
                    reason = next(w for w in widgets if w.winfo_class() == "TEntry")
                    fail = next(w for w in widgets if w.winfo_class() == "TButton"
                                and w.cget("text") == "Fail")
                    with patch("ui.tests.messagebox.showerror") as error:
                        fail.invoke()
                        error.assert_called_once()
                    self.assertEqual(results["wifi"], "pass")
                    reason.insert(0, "External adapter failed")
                    fail.invoke()
                    root.update()
                    self.assertEqual(panel.test_labels["wifi_label"].cget("text"), "OVERRIDDEN FAIL")
                    self.assertEqual(len(results["_overrides"]["wifi"]), 2)
                    panel.tests_window.destroy()

                def confirm_review(dialog):
                    widgets = list(descendants(dialog))
                    reason = next(w for w in widgets if isinstance(w, tk.Text)
                                  and int(w.cget("height")) == 3)
                    assign = next(w for w in widgets if w.winfo_class() == "TButton"
                                  and w.cget("text") == "Assign with recorded reason")
                    with patch.object(assignment_review.messagebox, "showerror") as error:
                        assign.invoke()
                        error.assert_called_once()
                    self.assertTrue(dialog.winfo_exists())
                    reason.insert("1.0", "Assigned for repair")
                    assign.invoke()

                with patch.object(root, "wait_window", side_effect=confirm_review):
                    self.assertEqual(assignment_review.prompt_assignment_review(
                        root, "Failed: Keyboard\nCancelled: USB", True), "Assigned for repair")

                def cancel_review(dialog):
                    root.tk.call(dialog.protocol("WM_DELETE_WINDOW"))

                with patch.object(root, "wait_window", side_effect=cancel_review):
                    self.assertIsNone(assignment_review.prompt_assignment_review(
                        root, "Failed: Keyboard", True))

                display_results = {}
                run_display_test(root, display_results, {})
                window = next(w for w in root.winfo_children()
                              if isinstance(w, original_toplevel))
                advance = re.search(r'\[([^\s]+)', window.bind("<Button-1>")).group(1)
                for _ in range(5):
                    root.tk.call(advance)
                prompt = next(w for w in root.winfo_children()
                              if isinstance(w, original_toplevel))
                root.tk.call(prompt.protocol("WM_DELETE_WINDOW"))
                self.assertEqual(display_results["display"], "cancelled")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
