from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.storage import (
    compare_storage, inventory, inventory_label, parse_configuration,
    resolve_requirement, sku_storage,
)
from services.mdm_evidence import evidence
from services import assignment_api
from utils import specs, helpers
import main_logic
import test_review_fixes


def disk(device="disk0", size=512_000_000_000, serial="s0", **extra):
    values = dict(DeviceID=device, Size=size, SerialNumber=serial,
                  InterfaceType="SCSI", MediaType="Fixed hard disk media",
                  Model="Measured device", PNPDeviceID="SCSI\\DISK")
    values.update(extra)
    return SimpleNamespace(**values)


def typed(serial="s0", media=4, bus=11):
    return SimpleNamespace(SerialNumber=serial, MediaType=media, BusType=bus)


class StorageComparisonTests(unittest.TestCase):
    def test_drive_configuration_not_total_or_first_capacity(self):
        for wanted, found, matches in (
            ("512GB", "512GB+512GB", False),
            ("1TB", "512GB+512GB", False),
            ("512GB+1TB", "1TB+512GB", True),
            ("2x512GB SSD", "512GB SSD+512GB SSD", True),
            ("512GB+1TB", "512GB+512GB", False),
            ("1TB", "1000GB", True), ("1TB", "1024GB", True),
            ("512GiB", "512GB", False),
            ("1TiB", "1024GiB", True),
            ("512GB SSD", "512GB HDD", False),
            ("512GB SSD", "512GB", False),
            ("512GB SSD", "512GB NVMe SSD", True),
            ("NVMe SSD 512GB", "512GB SSD", False),
            ("Unknown", "Unknown", False),
            ("512GB or 1TB", "512GB", False),
            ("512GB+Unknown", "512GB", False),
            ("999" * 400 + "TB", "512GB", False),
        ):
            with self.subTest(wanted=wanted[:40], found=found):
                self.assertEqual(compare_storage(wanted, found)[0], matches)

    def test_real_bytes_tolerance_and_unknown_type(self):
        captured = inventory([disk(size=512_110_190_592)], [typed()])
        self.assertTrue(compare_storage("512GB SSD", "ignored", captured)[0])
        for capacity in (480_000_000_000, 500_000_000_000):
            self.assertFalse(compare_storage("512GB SSD", "ignored",
                                            inventory([disk(size=capacity)], [typed()]))[0])
        unknown = inventory([disk()])
        self.assertTrue(compare_storage("512GB", "ignored", unknown)[0])
        self.assertFalse(compare_storage("512GB SSD", "ignored", unknown)[0])

    def test_generic_and_typed_equal_size_drives_match_without_order_bias(self):
        captured = inventory([disk(), disk("disk1", serial="s1")],
                             [typed(), typed("s1", 3)])
        self.assertTrue(compare_storage("512GB+512GB SSD", "ignored", captured)[0])
        self.assertFalse(compare_storage("2x512GB SSD", "ignored", captured)[0])

    def test_sku_parser_retains_every_storage_component_and_type(self):
        keywords = ["512SSD", "256SSD", "1TBSSD", "1TB"]
        for sku, count in (
            ("DELL-8RAM-512SSD+512SSD-AGRADE", 2),
            ("DELL_8GBRAM_512SSD_1TBHDD", 2),
            ("DELL-8GB-256SSD", 1),
            ("DELL-2x512GB SSD", 2),
        ):
            self.assertEqual(len(parse_configuration(sku_storage(sku, keywords))), count)
        self.assertIsNone(sku_storage("DELL-8GBRAM", keywords))
        self.assertIn("Ambiguous", resolve_requirement("512GB", "512SSD+512SSD"))
        self.assertEqual(resolve_requirement("512GB", "512SSD"), "512SSD")

    def test_retry_ignores_capture_time_but_preserves_changed_drive_configuration(self):
        first = {"specs": {"Storage": inventory([disk()])},
                 "storage_review": {"captured_at": "first", "matched": True}}
        copy = deepcopy(first)
        second = deepcopy(first)
        second["specs"]["Storage"]["checked_at"] = "later"
        second["storage_review"]["captured_at"] = "later"
        self.assertEqual(assignment_api._intent_hash("order", first),
                         assignment_api._intent_hash("order", second))
        self.assertEqual(first, copy)
        second["specs"]["Storage"]["disks"].append(inventory([disk("disk1")])["disks"][0])
        self.assertNotEqual(assignment_api._intent_hash("order", first),
                            assignment_api._intent_hash("order", second))


class StorageCaptureTests(unittest.TestCase):
    def test_equal_size_unpartitioned_drives_are_both_included(self):
        client = Mock()
        client.Win32_DiskDrive.return_value = [disk(), disk("disk1", serial="s1")]
        provider = Mock()
        provider.MSFT_PhysicalDisk.return_value = [typed(), typed("s1")]
        with patch.object(specs.wmi, "WMI", return_value=provider):
            captured = specs.capture_storage(client)
        self.assertEqual(inventory_label(captured), "512GB SSD + 512GB SSD")
        client.Win32_DiskDrive.assert_called_once()
        client.Win32_DiskPartition.assert_not_called()
        self.assertEqual([entry["device_id"] for entry in captured["disks"]], ["disk0", "disk1"])

    def test_usb_uasp_pnp_and_removable_media_are_excluded_but_retained(self):
        captured = inventory([
            disk(), disk("usb", serial="usb", InterfaceType="USB"),
            disk("uasp", serial="uasp"),
            disk("pnp", serial="pnp", PNPDeviceID="USBSTOR\\DISK"),
            disk("card", serial="card", MediaType="Removable Media"),
        ], [typed(), typed("uasp", bus=7)])
        self.assertEqual(inventory_label(captured), "512GB SSD")
        self.assertEqual(sum(row["excluded"] for row in captured["disks"]), 4)

    def test_invalid_capacity_duplicate_id_or_missing_id_requires_review(self):
        for rows in ([disk(size=None)], [disk(), disk()], [disk(device="")]):
            captured = inventory(rows, [typed()])
            self.assertTrue(captured["errors"])
            self.assertEqual(inventory_label(captured), "Unknown")
            self.assertFalse(compare_storage("512GB", "512GB", captured)[0])

    def test_type_provider_failure_does_not_invent_hdd_or_hide_capacity(self):
        client = Mock()
        client.Win32_DiskDrive.return_value = [disk()]
        with patch.object(specs.wmi, "WMI", side_effect=OSError("provider unavailable")):
            captured = specs.capture_storage(client)
        self.assertEqual(inventory_label(captured), "512GB")
        self.assertEqual(captured["disks"][0]["kind"], "Unknown")
        self.assertTrue(captured["type_errors"])

    def test_full_spec_scan_retains_inventory_and_uses_each_physical_drive(self):
        client, provider = Mock(), Mock()
        client.Win32_Processor.return_value = []
        client.Win32_BIOS.return_value = [SimpleNamespace(SerialNumber="DEVICE")]
        client.Win32_VideoController.return_value = []
        client.Win32_OperatingSystem.return_value = [SimpleNamespace(Caption="Windows 11")]
        client.Win32_ComputerSystem.return_value = [SimpleNamespace(Manufacturer="Test", Model="Test", SystemFamily="")]
        client.Win32_DiskDrive.return_value = [disk(), disk("disk1", serial="s1")]
        provider.MSFT_PhysicalDisk.return_value = [typed(), typed("s1", 3)]
        with ExitStack() as stack:
            stack.enter_context(patch.object(specs.wmi, "WMI", side_effect=[client, provider]))
            stack.enter_context(patch.object(specs.pythoncom, "CoInitialize"))
            stack.enter_context(patch.object(specs.pythoncom, "CoUninitialize"))
            stack.enter_context(patch.object(specs, "get_battery_health", return_value=[]))
            stack.enter_context(patch.object(specs, "_save_specs_cache"))
            stack.enter_context(patch.object(specs, "_laptop_specs_cache", None))
            result = specs.get_laptop_specs(force_refresh=True)
        self.assertEqual(result["SSD"], "512GB SSD + 512GB HDD")
        self.assertEqual(len(result["Storage"]["disks"]), 2)


class StorageAssignmentTests(unittest.TestCase):
    setUp = test_review_fixes.AssignmentTests.setUp

    def test_final_review_uses_resolved_item_requirement_and_preserves_inventory(self):
        captured = inventory([disk(), disk("disk1", serial="s1")], [typed(), typed("s1")])
        measured = {"SSD": inventory_label(captured), "Storage": captured}
        with patch.object(main_logic, "prompt_assignment_review", return_value="Assigned for correction") as prompt:
            with patch.object(main_logic, "upload_stock_unit_check_report", return_value=(True, {})) as upload:
                main_logic.assign_serial_logic("ORD-1", "TEST", measured, self.results,
                                               "SKU", None, "tester", Mock(),
                                               expected_details={"SSD": "512GB SSD"})
        self.assertTrue(prompt.call_args.args[2])
        self.assertIn("Expected 1 physical drive(s), found 2", prompt.call_args.args[1])
        self.assertEqual(upload.call_args.kwargs["specs"]["Storage"], captured)
        self.assertFalse(upload.call_args.kwargs["storage_review"]["matched"])
