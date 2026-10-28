"""Windowed fixture probe for SC18; never used by the production entry point."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest

from services.update_process import health_worker
from test_update_safety import TransactionTests

if __name__ == "__main__":
    result_path = Path(sys.argv[1])
    result = unittest.TestResult()
    unittest.defaultTestLoader.loadTestsFromTestCase(TransactionTests).run(result)
    with TemporaryDirectory() as directory:
        request = Path(directory) / "request.json"
        request.write_text(json.dumps({"arguments": {"nonce": "frozen-probe"}}), encoding="utf-8")
        health_worker(directory)
        health = json.loads((Path(directory) / "result.json").read_text(encoding="utf-8"))
    report = {"windowed": sys.stdout is None and sys.stderr is None,
              "transaction_tests": result.testsRun, "tests_passed": result.wasSuccessful(),
              "failures": [item[0].id() for item in result.failures + result.errors],
              "packaged_health": health.get("success") is True and health.get("packaged") is True,
              "health_nonce": health.get("nonce") == "frozen-probe",
              "no_gui_created": tk._default_root is None,
              "fixture_signer_and_launch_boundaries": True}
    report["all_passed"] = all(report[key] for key in
        ("windowed", "tests_passed", "packaged_health", "health_nonce", "no_gui_created"))
    result_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    sys.exit(0 if report["all_passed"] else 1)
