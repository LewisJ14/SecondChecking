from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services import listing_capture
from services.measurements import utc_now


class ListingCaptureTests(unittest.TestCase):
    def test_windows_measurements_do_not_claim_panel_capability(self):
        measurements = {
            "Serial Number": " 001-AB ", "Manufacturer": "Lenovo", "Model": "ThinkPad T14",
            "CPU": "Intel Core i5", "RAM": "16GB", "SSD": "256GB NVMe SSD",
            "Windows": "Windows 11 Pro", "Resolution": "1920x1080",
            "Graphics": ["Intel Iris Xe Graphics"],
            "Battery": "87.0%", "Battery Evidence": {
                "source": "Windows battery WMI",
                "batteries": [{"health_percent": 87, "designed_capacity": "50000",
                               "full_capacity": "43500"}],
            },
            "Measurements": {"checked_at": utc_now()},
        }
        capture = listing_capture.build_capture(measurements, "no_local_indicators")
        self.assertEqual(capture["serial_number"], "001-AB")
        self.assertEqual(capture["specs"]["installed_windows"], "Windows 11 Pro")
        self.assertEqual(capture["specs"]["gpu"], "Intel Iris Xe Graphics")
        self.assertNotIn("resolution", capture["specs"])
        self.assertEqual(capture["evidence"]["current_resolution"], "1920x1080")
        self.assertEqual(capture["evidence"]["batteries"][0]["design_capacity"], "50000")
        self.assertNotIn("condition", capture)
        measurements["Measurements"]["checked_at"] = "2020-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "Fresh Windows measurements"):
            listing_capture.build_capture(measurements, "unknown")

    def test_save_uses_operator_session_and_checks_the_receipt(self):
        base = "https://astro.example.test"
        session = listing_capture.operator_session
        session.install(base, {
            "user": {"id": 1, "username": "Operator", "role": "user", "permissions": ["test"]},
            "session_token": "test-token", "expires_in": 30,
        })
        self.addCleanup(session.clear)
        payload = {"capture_id": "capture"}
        receipt = {"success": True, "capture_id": "capture", "draft_id": 42,
                   "draft_url": "/orders/listing-drafts/42", "state": "draft"}
        response = SimpleNamespace(status_code=200, json=lambda: receipt)

        with patch.object(listing_capture, "service_settings", return_value=(base, "test-key")), \
                patch.object(listing_capture.transport, "post", return_value=response) as post:
            result, url = listing_capture.submit_capture(payload)
            self.assertEqual(result, receipt)
            self.assertEqual(url, base + receipt["draft_url"])
            post.assert_called_once_with(base + "/api/second-check/listing-captures", headers={
                "X-Second-Check-Key": "test-key", "X-Second-Check-Session": "test-token",
            }, json=payload, timeout=20)
            receipt["draft_url"] = "//another-host.example.test/orders/listing-drafts/42"
            with self.assertRaisesRegex(RuntimeError, "invalid capture receipt"):
                listing_capture.submit_capture(payload)
