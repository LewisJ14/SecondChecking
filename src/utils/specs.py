# utils/specs.py
import json
import re
import time
import tempfile
import threading
from copy import deepcopy
import psutil
import wmi
import subprocess
import os
from pathlib import Path
from typing import Optional
from services.storage import inventory_label
from services.measurements import fresh, utc_now, parse_battery_csv, battery_labels
from services.measurements import pair_windows_batteries
from utils.helpers import log_event, ensure_batteryinfoview, get_app_dir
import pythoncom
import configparser
import getpass
import sys

from services.configuration import read_config, ConfigurationError

try:
    config = read_config()
except ConfigurationError:
    config = configparser.ConfigParser(interpolation=None)

SPECS_CACHE_TTL = 300  # seconds


def _specs_cache_path() -> Path:
    return Path(get_app_dir()) / "specs_cache.json"


def _load_cached_specs() -> Optional[dict]:
    path = _specs_cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ts = float(data.get("timestamp", 0))
        if not 0 <= time.time() - ts <= SPECS_CACHE_TTL:
            return None
        specs = data.get("specs")
        if isinstance(specs, dict) and fresh(specs, SPECS_CACHE_TTL):
            log_event("Loaded cached laptop specs.")
            return specs
    except Exception as exc:
        log_event(f"Failed to load specs cache: {exc}")
    return None


def _save_specs_cache(specs: dict) -> None:
    path = _specs_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"timestamp": time.time(), "specs": specs}), encoding="utf-8")
    except Exception as exc:
        log_event(f"Failed to save specs cache: {exc}")


def _strip_thinkpad_prefix(value: Optional[str]) -> str:
    """Remove a leading ThinkPad/Thinkpad token if it appears at the start."""
    if not value:
        return ""
    sanitized = value.strip()
    match = re.match(r"(?i)^thinkpad(?:[\s\-]+)?", sanitized)
    if match:
        sanitized = sanitized[match.end():].strip()
    return sanitized

def get_ssd_thresholds():
    # Retrieve SSD thresholds from the configuration file or use hardcoded defaults
    try:
        thresholds_str = config.get('hardware', 'ssd_thresholds', fallback="4TB:3900,2TB:1800,1TB:900,512GB:450,256GB:220,128GB:110")
        thresholds = {}
        for pair in thresholds_str.split(','):
            label, val = pair.split(':')
            thresholds[label.strip()] = float(val.strip())
        return thresholds
    except Exception as e:
        log_event("Invalid hardware.ssd_thresholds; using default thresholds.")
        # Fallback to hardcoded defaults
        return {
            "4TB": 3900,
            "2TB": 1800,
            "1TB": 900,
            "512GB": 450,
            "256GB": 220,
            "128GB": 110
        }

SSD_THRESHOLDS = get_ssd_thresholds()

def parse_cpu_family_and_model(cpu_name):
    """
    Extracts the CPU family and model from a CPU name string.
    Examples:
        Intel(R) Core(TM) i5-8350U CPU @ 1.70GHz -> i5-8350U
        Intel(R) Core(TM) i7-1165G7 -> i7-1165G7
        AMD Ryzen 5 3500U -> Ryzen 5 3500U
        AMD Ryzen 7 5800H -> Ryzen 7 5800H
    """
    cpu_name = cpu_name.strip()
    cpu_name = re.sub(r"with\s+[\w\-]+\s+Graphics", "", cpu_name, flags=re.IGNORECASE).strip()
    # Intel Core iX-YYYY
    intel = re.search(r'(i[3579]-[A-Za-z0-9]+)', cpu_name, re.IGNORECASE)
    if intel:
        return intel.group(1)
    # AMD Ryzen <series> (capture up to CPU/@ or end)
    amd = re.search(r'(Ryzen\s[\w\-\s]+?)(?:\s+CPU|\s*@|$)', cpu_name, re.IGNORECASE)
    if amd:
        return amd.group(1).strip()
    # Fallback: just return the first 2 words
    return cpu_name


def format_windows_caption(os_info) -> str:
    caption = str(getattr(os_info, "Caption", "") or "").strip()
    caption = re.sub(r"^Microsoft\s+", "", caption, flags=re.IGNORECASE)
    caption = re.sub(r"\s+", " ", caption).strip()
    if caption:
        return caption

    try:
        build_number = int(os_info.BuildNumber)
    except (TypeError, ValueError):
        return "Unknown"
    return "Windows 11" if build_number >= 22000 else "Windows 10"

_laptop_specs_cache = None
_latest_batteryinfoview_report = None
_latest_battery_evidence = {}
_specs_lock = threading.RLock()

def reset_specs_cache() -> None:
    """Clear the in-memory cache and remove the persisted specs cache file."""
    global _laptop_specs_cache
    _laptop_specs_cache = None
    cache_path = _specs_cache_path()
    if cache_path.exists():
        try:
            cache_path.unlink()
        except Exception as exc:
            log_event(f"Failed to delete specs cache file: {exc}")

def capture_storage(client):
    """Capture every physical disk, independent of partitions or mount points."""
    from services.storage import inventory

    type_errors = []
    try:
        provider = wmi.WMI(namespace=r"root\Microsoft\Windows\Storage")
        typed = list(provider.MSFT_PhysicalDisk())
    except Exception as exc:
        typed = []
        type_errors.append("Media/bus provider unavailable: " + str(exc))
    try:
        disks = list(client.Win32_DiskDrive())
        return inventory(disks, typed, type_errors)
    except Exception as exc:
        result = inventory([], type_errors=type_errors)
        result["errors"].append("Physical disk query failed: " + str(exc))
        return result


def get_laptop_specs(force_refresh=False):
    with _specs_lock:
        return _get_laptop_specs(force_refresh)


def _get_laptop_specs(force_refresh=False):
    global _laptop_specs_cache, _latest_battery_evidence, _latest_batteryinfoview_report
    if _laptop_specs_cache is not None and not force_refresh and fresh(_laptop_specs_cache, SPECS_CACHE_TTL):
        log_event("Returning cached laptop specs.")
        return deepcopy(_laptop_specs_cache)

    if not force_refresh:
        cached_specs = _load_cached_specs()
        if cached_specs:
            _laptop_specs_cache = deepcopy(cached_specs)
            return deepcopy(_laptop_specs_cache)

    log_event("Fetching laptop specs...")
    _latest_battery_evidence = {}
    _latest_batteryinfoview_report = None
    pythoncom.CoInitialize()
    specs = {
        "Serial Number": "Unknown",
        "CPU": "Unknown",
        "RAM": "Unknown",
        "SSD": "Unknown",
        "Drive Type": "Unknown",
        "Model": "Unknown",
        "Resolution": "Unknown",
        "Windows": "Unknown",
        "Battery": "Unknown",
        "Battery 2": None
    }

    try:
        c = wmi.WMI()
        log_event("Initialized WMI interface.")

        for cpu in c.Win32_Processor():
            specs["CPU"] = parse_cpu_family_and_model(cpu.Name)
            log_event(f"Detected CPU: {specs['CPU']}")
            break

        bios = c.Win32_BIOS()[0]
        specs["Serial Number"] = bios.SerialNumber.strip()
        log_event(f"Detected Serial Number: {specs['Serial Number']}")

        for display in c.Win32_VideoController():
            if display.CurrentHorizontalResolution and display.CurrentVerticalResolution:
                specs["Resolution"] = f"{display.CurrentHorizontalResolution}x{display.CurrentVerticalResolution}"
                log_event(f"Detected Resolution: {specs['Resolution']}")
                break

        os_info = c.Win32_OperatingSystem()[0]
        specs["Windows"] = format_windows_caption(os_info)
        log_event(f"Detected Windows Version: {specs['Windows']}")

        system_info = c.Win32_ComputerSystem()[0]
        manufacturer = (system_info.Manufacturer or "").lower()
        family_model = _strip_thinkpad_prefix(getattr(system_info, "SystemFamily", ""))
        detected_model = _strip_thinkpad_prefix(getattr(system_info, "Model", ""))
        fallback_model = (system_info.Model or "").strip()
        if "lenovo" in manufacturer:
            specs["Model"] = family_model or detected_model or fallback_model
        else:
            specs["Model"] = detected_model or fallback_model
        log_event(f"Detected Model: {specs['Model']}")

        specs["RAM"] = f"{round(psutil.virtual_memory().total / (1024**3))}GB"
        log_event(f"Detected RAM: {specs['RAM']}")

        storage = capture_storage(c)
        specs["Storage"] = storage
        specs["SSD"] = inventory_label(storage)
        kinds = {disk["kind"] for disk in storage["disks"] if not disk["excluded"]}
        specs["Drive Type"] = " / ".join(sorted(kinds)) if kinds else "Unknown"

        healths = get_battery_health(client=c)
        if not healths:
            specs["Battery"] = "Unknown"
            log_event("Detected Battery Health: Unknown")
        else:
            specs["Battery"] = healths[0] if isinstance(healths[0], str) else "Unknown"
            log_event(f"Detected Battery Health: {specs['Battery']}")
            for index, entry in enumerate(healths[1:], start=2):
                stats = entry if isinstance(entry, str) else "Unknown"
                specs[f"Battery {index}"] = stats
                log_event(f"Detected Battery {index} Health: {stats}")

    except Exception as e:
        from services.runtime import log_diagnostic
        log_diagnostic('device.capture_failed', error=e, stage='inventory')
        raise
    finally:
        pythoncom.CoUninitialize()

    specs["Battery Evidence"] = deepcopy(_latest_battery_evidence)
    specs["_battery_report"] = deepcopy(_latest_batteryinfoview_report)
    specs["Measurements"] = {
        "version": 1, "checked_at": utc_now(),
        "battery_source": _latest_battery_evidence.get("source", "Unknown"),
        "sources": {"Resolution": "Win32_VideoController current mode; panel capability unverified",
                    "Windows": "Win32_OperatingSystem edition; activation is a separate test",
                    "Storage": "Win32_DiskDrive / optional MSFT_PhysicalDisk",
                    "Battery": _latest_battery_evidence.get("source", "Unknown")},
    }
    _laptop_specs_cache = deepcopy(specs)
    _save_specs_cache(specs)
    log_event("Laptop specs fetched successfully.")
    return specs

def get_live_battery_percent():
    try:
        w = wmi.WMI()
        for battery in w.Win32_Battery():
            return int(battery.EstimatedChargeRemaining)
    except Exception as e:
        log_event(f"Error reading live battery percent: {e}")
    return None

def get_latest_batteryinfoview_report():
    report = _latest_batteryinfoview_report
    if isinstance(report, dict) and fresh({"Measurements": report}, SPECS_CACHE_TTL):
        return deepcopy(report)
    return None


def capture_batteryinfoview_report():
    global _latest_batteryinfoview_report
    _latest_batteryinfoview_report = None
    exe_path = os.path.abspath(ensure_batteryinfoview())
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with tempfile.TemporaryDirectory(prefix="secondchecking-battery-") as directory:
        csv_path = os.path.join(directory, "battery.csv")
        subprocess.run([exe_path, "/scomma", csv_path], check=True,
                       creationflags=flags, timeout=30, cwd=directory)
        if not os.path.isfile(csv_path):
            raise ValueError("BatteryInfoView did not produce a fresh export.")
        raw = Path(csv_path).read_bytes()
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            content = raw.decode("utf-16")
        else:
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                content = raw.decode("cp1252")
    _latest_batteryinfoview_report = {
        "filename": "battery.csv", "content": content,
        "checked_at": utc_now(), "source": "BatteryInfoView /scomma",
    }
    return deepcopy(_latest_batteryinfoview_report)


def get_battery_health_batteryinfoview(expected_count=None):
    global _latest_battery_evidence
    try:
        report = capture_batteryinfoview_report()
        entries = parse_battery_csv(report["content"])
        if expected_count and len(entries) != expected_count:
            entries = [{"index": index + 1, "state": "unreadable",
                        "reason": "Battery count differs between inventory and export"}
                       for index in range(max(expected_count, len(entries))) ]
        _latest_battery_evidence = {
            "state": "measured" if all(row.get("state") == "measured" for row in entries) else "unreadable",
            "checked_at": report["checked_at"], "source": report["source"],
            "batteries": entries,
        }
        return battery_labels(entries)
    except Exception as exc:
        _latest_battery_evidence = {"state": "unreadable", "checked_at": utc_now(),
                                    "source": "BatteryInfoView", "error": str(exc),
                                    "batteries": []}
        log_event("Battery health capture unavailable: " + str(exc))
        return ["Unreadable (battery health)"] * max(expected_count or 1, 1)


def get_battery_health(client=None):
    global _latest_batteryinfoview_report, _latest_battery_evidence
    _latest_batteryinfoview_report = None
    expected = None
    try:
        rows = list((client or wmi.WMI()).Win32_Battery())
        expected = len(rows)
        if not rows:
            _latest_battery_evidence = {"state": "absent", "checked_at": utc_now(),
                                        "source": "Win32_Battery", "batteries": []}
            return ["Absent (Windows battery inventory)"]
    except Exception as exc:
        log_event("Windows battery inventory unavailable: " + str(exc))
    try:
        capacities = wmi.WMI(namespace=r"root\wmi")
        static = [{key: getattr(row, key, None)
                   for key in ("InstanceName", "DesignedCapacity", "Capabilities")}
                  for row in capacities.BatteryStaticData()
                  if getattr(row, "Active", True)]
        full = [{key: getattr(row, key, None)
                 for key in ("InstanceName", "FullChargedCapacity")}
                for row in capacities.BatteryFullChargedCapacity()
                if getattr(row, "Active", True)]
    except Exception as exc:
        log_event("Windows battery capacity provider unavailable: " + str(exc))
        return get_battery_health_batteryinfoview(expected)
    try:
        cycles = [{key: getattr(row, key, None)
                   for key in ("InstanceName", "CycleCount")}
                  for row in capacities.BatteryCycleCount()
                  if getattr(row, "Active", True)]
    except Exception:
        # Cycle reporting is optional and must not discard valid capacities.
        cycles = []
    try:
        entries = pair_windows_batteries(static, full, expected, cycles)
    except ValueError as exc:
        # An unavailable provider may use the legacy export; malformed identities
        # must never cause selected-pack data to be copied across multiple packs.
        log_event("Windows battery capacity capture unavailable: " + str(exc))
        if not static and not full:
            return get_battery_health_batteryinfoview(expected)
        entries = [{"index": index + 1, "state": "unreadable", "reason": str(exc)}
                   for index in range(max(expected or 1, len(static), len(full)))]
    stamp = utc_now()
    _latest_battery_evidence = {
        "state": "measured" if all(row["state"] == "measured" for row in entries)
        else "unreadable", "checked_at": stamp,
        "source": "Windows battery WMI", "batteries": entries,
    }
    _latest_batteryinfoview_report = {
        "filename": "battery-wmi.json", "checked_at": stamp,
        "source": "Windows battery WMI",
        "content": json.dumps({"static": static, "full": full, "cycles": cycles,
                               "evidence": _latest_battery_evidence}, sort_keys=True),
    }
    return battery_labels(entries, source="Windows battery WMI")
