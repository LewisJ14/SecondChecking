from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import time
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.measurements import (capture_age, fresh, parse_battery_csv, utc_now,
                                   pair_windows_batteries, battery_labels)
from services import assignment_api
from services.check_session import CheckSession, CheckDraftStore
from utils import specs, helpers
import app_controller
from app_controller import AppController
import main_logic
import test_check_session


def snapshot(serial="DEVICE"):
    return {"Serial Number": serial, "Resolution": "1920x1080",
            "Measurements": {"version": 1, "checked_at": utc_now(),
                             "battery_source": "BatteryInfoView"}}


class BatteryParsingTests(unittest.TestCase):
    def test_cycles_stay_with_their_pack_when_records_are_reversed(self):
        static = [dict(InstanceName=name, DesignedCapacity=1000, Capabilities=0)
                  for name in ('A', 'B')]
        full = [dict(InstanceName=name, FullChargedCapacity=311)
                for name in ('B', 'A')]
        cycles = [dict(InstanceName='b', CycleCount=240),
                  dict(InstanceName='a', CycleCount=120)]
        entries = pair_windows_batteries(static, full, 2, cycles)
        self.assertEqual([row['cycle_count'] for row in entries], [120, 240])
        self.assertTrue(battery_labels(entries)[0].startswith('31.1% (120 cycles)'))
        for invalid in (0, -1, None, True, 0xffffffff, '120'):
            cycles[1]['CycleCount'] = invalid
            entry = pair_windows_batteries(static, full, 2, cycles)[0]
            self.assertEqual(entry['state'], 'measured')
            self.assertNotIn('cycle_count', entry)
            self.assertIn('(cycles unavailable)', battery_labels([entry])[0])
        cycles = [dict(InstanceName='a', CycleCount=120)] * 2
        self.assertNotIn('cycle_count', pair_windows_batteries(static, full, 2, cycles)[0])

    def test_csv_cycles_preserve_both_row_and_column_pack_alignment(self):
        for content in (
            'Designed Capacity,1000 mWh,1000 mWh\n'
            'Full Charged Capacity,311 mWh,900 mWh\n'
            'Number of charge/discharge cycles,120,240\n',
            'Designed Capacity,Full Charged Capacity,Number of charge/discharge cycles\n'
            '1000 mWh,311 mWh,120\n1000 mWh,900 mWh,240\n',
        ):
            entries = parse_battery_csv(content)
            self.assertEqual([row['cycle_count'] for row in entries], [120, 240])
            self.assertEqual(entries[0]['health_percent'], 31.1)
        entries = parse_battery_csv('Designed Capacity,1000 mWh,1000 mWh\n'
                                   'Full Charged Capacity,311 mWh,900 mWh\n'
                                   'Number of charge/discharge cycles,,240\n')
        self.assertNotIn('cycle_count', entries[0])
        self.assertEqual(entries[1]['cycle_count'], 240)

    def test_windows_instances_pair_reversed_records_with_distinct_health(self):
        static = [dict(InstanceName=name, DesignedCapacity=100, Capabilities=0)
                  for name in ("PACK-A", "PACK-B")]
        full = [dict(InstanceName="pack-b", FullChargedCapacity=50),
                dict(InstanceName="pack-a", FullChargedCapacity=90)]
        entries = pair_windows_batteries(static, full, 2)
        self.assertEqual([row["health_percent"] for row in entries], [90, 50])
        self.assertEqual([row["instance_name"] for row in entries], ["pack-a", "pack-b"])

    def test_windows_missing_duplicate_unknown_and_relative_capacities(self):
        static = [dict(InstanceName=name, DesignedCapacity=100, Capabilities=0)
                  for name in ("A", "B")]
        full = [dict(InstanceName="B", FullChargedCapacity=0)]
        entries = pair_windows_batteries(static, full, 2)
        self.assertEqual(entries[0]["state"], "unreadable")
        self.assertEqual(entries[1]["health_percent"], 0)
        self.assertEqual(pair_windows_batteries(static, full + full)[1]["state"], "unreadable")
        for value in (0xffffffff, None, -1):
            full[0]["FullChargedCapacity"] = value
            self.assertEqual(pair_windows_batteries(static, full)[1]["state"], "unreadable")
        full[0]["FullChargedCapacity"] = 50
        static[1]["Capabilities"] = 0x40000000
        self.assertEqual(pair_windows_batteries(static, full)[1]["unit"], "relative")
        self.assertTrue(all(row["state"] == "unreadable"
                            for row in pair_windows_batteries(static, full, 3)))
        with self.assertRaises(ValueError):
            pair_windows_batteries([dict(DesignedCapacity=100)], full)

    def test_vertical_csv_preserves_columns_and_quoted_thousands(self):
        parsed = parse_battery_csv('Battery Name,Main,Secondary\nDesigned Capacity,"50,000 mWh","40,000 mWh"\nFull Charged Capacity,"45,000 mWh","20,000 mWh"\n')
        self.assertEqual([row["health_percent"] for row in parsed], [90, 50])

    def test_decimal_comma_semicolon_and_horizontal_exports(self):
        for content in (
            'Designed Capacity;"50.000,0 mWh"\nFull Charged Capacity;"45.000,0 mWh"\n',
            'Battery Name,Designed Capacity,Full Charged Capacity\nMain,"50,5 mWh","45,45 mWh"\n',
            'Designed Capacity\t50000 mWh\nFull Charged Capacity\t45000 mWh\n',
        ):
            self.assertAlmostEqual(parse_battery_csv(content)[0]["health_percent"], 90)

    def test_missing_slot_zero_capacity_and_bad_units_do_not_shift_batteries(self):
        parsed = parse_battery_csv('Designed Capacity,50000 mWh,40000 mWh\nFull Charged Capacity,,20000 mWh\n')
        self.assertEqual(parsed[0]["state"], "unreadable")
        self.assertEqual(parsed[1]["health_percent"], 50)
        for content in (
            'Designed Capacity,0 mWh\nFull Charged Capacity,100 mWh\n',
            'Designed Capacity,50000 mWh\nFull Charged Capacity,45000 mAh\n',
            'Designed Capacity,50000 mWh\nDesigned Capacity,40000 mWh\nFull Charged Capacity,45000 mWh\n',
            'Unknown localized label,123\n', '',
        ):
            self.assertEqual(parse_battery_csv(content)[0]["state"], "unreadable")
        zero = parse_battery_csv('Designed Capacity,50000 mWh\nFull Charged Capacity,0 mWh\n')
        self.assertEqual(zero[0]["health_percent"], 0)
        self.assertIsNone(helpers.parse_percent("Unreadable battery 2"))
        self.assertEqual(helpers.parse_percent("69,5% health"), 69.5)


class BatteryCaptureTests(unittest.TestCase):
    def test_native_capture_preserves_both_instances_and_report(self):
        inventory = Mock()
        inventory.Win32_Battery.return_value = [object(), object()]
        provider = Mock()
        provider.BatteryStaticData.return_value = [
            SimpleNamespace(InstanceName=name, DesignedCapacity=100, Capabilities=0)
            for name in ("A", "B")]
        provider.BatteryFullChargedCapacity.return_value = [
            SimpleNamespace(InstanceName=name, FullChargedCapacity=value)
            for name, value in (("B", 50), ("A", 90))]
        provider.BatteryCycleCount.return_value = [
            SimpleNamespace(InstanceName=name, CycleCount=value)
            for name, value in (("B", 240), ("A", 120))]
        with patch.object(specs.wmi, "WMI", return_value=provider), \
                patch.object(specs, "capture_batteryinfoview_report") as legacy:
            labels = specs.get_battery_health(inventory)
        self.assertEqual(labels, ["90.0% (120 cycles) (Windows battery WMI health)",
                                  "50.0% (240 cycles) (Windows battery WMI health)"])
        legacy.assert_not_called()
        report = specs.get_latest_batteryinfoview_report()
        self.assertEqual(report["filename"], "battery-wmi.json")
        self.assertEqual(len(json.loads(report["content"])["evidence"]["batteries"]), 2)
        provider.BatteryCycleCount.side_effect = RuntimeError('unsupported')
        with patch.object(specs.wmi, "WMI", return_value=provider), \
                patch.object(specs, "capture_batteryinfoview_report") as legacy:
            labels = specs.get_battery_health(inventory)
        self.assertTrue(labels[0].startswith('90.0% (cycles unavailable)'))
        legacy.assert_not_called()

    def test_unavailable_native_provider_uses_conservative_legacy_capture(self):
        inventory = Mock()
        inventory.Win32_Battery.return_value = [object(), object()]
        with patch.object(specs.wmi, "WMI", side_effect=RuntimeError("unsupported")), \
                patch.object(specs, "get_battery_health_batteryinfoview", return_value=["legacy"]) as legacy:
            self.assertEqual(specs.get_battery_health(inventory), ["legacy"])
        legacy.assert_called_once_with(2)

    def test_exports_have_unique_paths_timeout_and_capture_time(self):
        paths = []
        def export(command, **kwargs):
            self.assertEqual(kwargs["timeout"], 30)
            path = Path(command[-1])
            paths.append(path)
            self.assertFalse(path.exists())
            path.write_text('Designed Capacity,50000 mWh\nFull Charged Capacity,45000 mWh\n')
        with patch.object(specs, "ensure_batteryinfoview", return_value="C:/bundled/BatteryInfoView.exe"):
            with patch.object(specs.subprocess, "run", side_effect=export):
                for _ in range(2):
                    report = specs.capture_batteryinfoview_report()
                    # Windows wall-clock APIs can differ at sub-millisecond precision.
                    captured = datetime.fromisoformat(report["checked_at"])
                    with patch("services.measurements.time.time",
                               return_value=captured.timestamp() + 1):
                        self.assertTrue(fresh({"Measurements": report}))
        self.assertNotEqual(paths[0], paths[1])
        self.assertTrue(all(not path.exists() for path in paths))

    def test_utf16_export_is_decoded_without_dropping_characters(self):
        def export(command, **kwargs):
            Path(command[-1]).write_bytes('Battery Name,"Main – battery"\nDesigned Capacity,50000 mWh\nFull Charged Capacity,45000 mWh\n'.encode("utf-16"))
        with patch.object(specs, "ensure_batteryinfoview", return_value="C:/tool.exe"):
            with patch.object(specs.subprocess, "run", side_effect=export):
                report = specs.capture_batteryinfoview_report()
        self.assertIn("Main – battery", report["content"])
        self.assertEqual(parse_battery_csv(report["content"])[0]["health_percent"], 90)

    def test_timeout_and_missing_export_cannot_reuse_previous_report(self):
        for effect in (subprocess.TimeoutExpired("tool", 30), None):
            with ExitStack() as stack:
                stack.enter_context(patch.object(specs, "_latest_batteryinfoview_report", {"content": "old"}))
                stack.enter_context(patch.object(specs, "ensure_batteryinfoview", return_value="C:/tool.exe"))
                stack.enter_context(patch.object(specs.subprocess, "run", side_effect=effect))
                result = specs.get_battery_health_batteryinfoview(2)
                self.assertEqual(result, ["Unreadable (battery health)"] * 2)
                self.assertIsNone(specs.get_latest_batteryinfoview_report())

    def test_absent_inventory_is_distinct_from_unreadable_export(self):
        client = Mock()
        client.Win32_Battery.return_value = []
        with patch.object(specs, "capture_batteryinfoview_report") as capture:
            self.assertIn("Absent", specs.get_battery_health(client)[0])
        capture.assert_not_called()
        self.assertEqual(specs._latest_battery_evidence["state"], "absent")

    def test_bundled_tool_path_does_not_depend_on_working_directory(self):
        with TemporaryDirectory() as directory:
            exe = Path(directory) / "assets/BatteryInfoView/BatteryInfoView.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"fixture")
            with patch.object(helpers.sys, "frozen", True, create=True), \
                    patch.object(helpers.sys, "_MEIPASS", directory, create=True), \
                    patch.object(helpers, "get_app_dir", return_value=str(Path(directory) / "unrelated")):
                self.assertEqual(Path(helpers.ensure_batteryinfoview()).resolve(), exe.resolve())

    def test_ac_power_is_not_a_charging_confirmation(self):
        client = Mock()
        client.Win32_Battery.return_value = [SimpleNamespace(EstimatedChargeRemaining=80, BatteryStatus=2)]
        with patch.object(helpers, "_ensure_wmi_instance", return_value=client), \
                patch.object(helpers, "_read_native_battery_state", return_value=None):
            state = helpers.get_live_battery_state()
            self.assertIsNone(state["charging"])
            self.assertIn("unconfirmed", state["power_state"])
            client.Win32_Battery.return_value[0].BatteryStatus = 6
            self.assertTrue(helpers.is_battery_charging())


class MeasurementCacheTests(unittest.TestCase):
    def test_immediate_capture_uses_the_same_clock_and_timestamp_precision(self):
        # This epoch rounds up when converted to datetime microseconds. Direct
        # subtraction of the unrounded float would wrongly reject it as future.
        epoch = 1792777015.5753338
        with patch("services.measurements.time.time", return_value=epoch):
            current = snapshot()
            self.assertEqual(capture_age(current), 0)
            self.assertTrue(fresh(current))
            with TemporaryDirectory() as directory:
                path = Path(directory) / "specs_cache.json"
                with patch.object(specs, "_specs_cache_path", return_value=path):
                    specs._save_specs_cache(current)
                    self.assertEqual(specs._load_cached_specs(), current)

    def test_age_preserves_expiry_and_future_rejection_at_microsecond_boundary(self):
        epoch = 1792777015.5753338
        with patch("services.measurements.time.time", return_value=epoch):
            current = snapshot()
        for delta, expected_age, expected_fresh in (
                (0, 0, True), (300, 300, True),
                (300.000002, 300.000002, False), (-0.000002, None, False)):
            with self.subTest(delta=delta), patch(
                    "services.measurements.time.time", return_value=epoch + delta):
                self.assertEqual(capture_age(current), expected_age)
                self.assertEqual(fresh(current), expected_fresh)

    def test_disk_cache_rejects_expired_future_or_unqualified_captures(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "specs_cache.json"
            with patch.object(specs, "_specs_cache_path", return_value=path):
                path.write_text(json.dumps({"timestamp": time.time(), "specs": snapshot()}))
                self.assertIsNotNone(specs._load_cached_specs())
                for stamp, measured in ((time.time() - 301, snapshot()),
                                        (time.time() + 60, snapshot()),
                                        (time.time(), {"Serial Number": "legacy"})):
                    path.write_text(json.dumps({"timestamp": stamp, "specs": measured}))
                    self.assertIsNone(specs._load_cached_specs())

    def test_memory_cache_expires_and_fresh_returns_are_independent(self):
        current = snapshot()
        with patch.object(specs, "_laptop_specs_cache", current):
            result = specs.get_laptop_specs()
            result["Measurements"]["checked_at"] = "changed"
            self.assertEqual(current["Measurements"]["checked_at"], specs.get_laptop_specs()["Measurements"]["checked_at"])
        old = snapshot()
        old["Measurements"]["checked_at"] = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
        with ExitStack() as stack:
            stack.enter_context(patch.object(specs, "_laptop_specs_cache", old))
            stack.enter_context(patch.object(specs, "_load_cached_specs", return_value=None))
            stack.enter_context(patch.object(specs.pythoncom, "CoInitialize"))
            stack.enter_context(patch.object(specs.pythoncom, "CoUninitialize"))
            probe = stack.enter_context(patch.object(specs.wmi, "WMI", side_effect=OSError("new scan requested")))
            with self.assertRaises(OSError):
                specs.get_laptop_specs()
            probe.assert_called_once()

    def test_future_or_missing_capture_times_are_not_fresh(self):
        future = snapshot()
        future["Measurements"]["checked_at"] = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        self.assertFalse(fresh(future))
        self.assertFalse(fresh({}))

    def test_assignment_forces_capture_and_checks_serial(self):
        with patch.object(main_logic, "load_laptop_specs", return_value=snapshot()) as load:
            self.assertEqual(main_logic.refresh_assignment_specs({}, "DEVICE")["Serial Number"], "DEVICE")
            load.assert_called_once_with(force_refresh=True)
        with patch.object(main_logic, "load_laptop_specs", return_value=snapshot("OTHER")):
            with self.assertRaises(ValueError):
                main_logic.refresh_assignment_specs({}, "DEVICE")

    def test_retry_capture_time_changes_do_not_change_evidence_intent(self):
        first = {"specs": snapshot(), "battery_report": {"checked_at": utc_now(), "content": "same"}}
        second = deepcopy(first)
        second["specs"]["Measurements"]["checked_at"] = "later"
        second["battery_report"]["checked_at"] = "later"
        self.assertEqual(assignment_api._intent_hash("order", first), assignment_api._intent_hash("order", second))
        second["battery_report"]["content"] = "different measurements"
        self.assertNotEqual(assignment_api._intent_hash("order", first), assignment_api._intent_hash("order", second))

    def test_unreadable_battery_and_current_mode_never_get_unqualified_match(self):
        values = {"Battery": "Unreadable battery 2", "Resolution": "1920x1080"}
        with patch.object(main_logic, "get_live_battery_state", return_value={"percent": None, "state": "unreadable", "power_state": "Unknown"}):
            footer = main_logic.build_results_footer(values, {"Battery": "70%", "Resolution": "1920x1080"}, {})[0]
        self.assertIn("health is unavailable", footer)
        self.assertIn("native panel capability is unverified", footer)


class DeviceRefreshFailureTests(unittest.TestCase):
    setUp = test_check_session.SearchContextTests.setUp

    def prepare_controller(self):
        c = self.controller
        c._active_resolved = deepcopy(self.resolved)
        c._lookup_valid = True
        c._tests_runner = None
        c.refresh_device_button = Mock()
        c._check_session.activate(10, "ORDER-A", "00123", c.test_results)
        c.test_results["keyboard"] = "fail"
        return c

    def test_changed_serial_does_not_attach_draft_to_new_device(self):
        c = self.prepare_controller()
        queued = []
        c.root.after.side_effect = lambda delay, action: queued.append(action)
        thread = lambda target, **kwargs: SimpleNamespace(start=target)
        with ExitStack() as stack:
            stack.enter_context(patch.object(app_controller.threading, "Thread", side_effect=thread))
            stack.enter_context(patch.object(app_controller, "load_laptop_specs", return_value=snapshot("OTHER")))
            error = stack.enter_context(patch.object(app_controller.messagebox, "showerror"))
            c.refresh_device()
            for action in queued:
                action()
        self.assertFalse(c._lookup_valid)
        self.assertFalse(c._search_inflight)
        self.assertEqual(c._check_session.key, (10, "00123"))
        self.assertEqual(c.test_results["keyboard"], "fail")
        self.assertIn("Device identity changed", error.call_args.args[1])

    def test_worker_start_failure_restores_controls_and_keeps_draft(self):
        c = self.prepare_controller()
        with patch.object(app_controller.threading, "Thread", side_effect=RuntimeError("worker unavailable")):
            with patch.object(app_controller.messagebox, "showerror"):
                c.refresh_device()
        self.assertFalse(c._search_inflight)
        c.refresh_device_button.config.assert_called_with(state="normal")
        self.assertIsNotNone(c._check_session.store.load((10, "00123")))
