# utils/specs.py
import json
import re
import time
import psutil
import wmi
import subprocess
import os
from pathlib import Path
from typing import Optional
from utils.helpers import log_event, ensure_batteryinfoview, get_app_dir
import pythoncom
import configparser
import getpass
import sys

config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), '..', 'config.ini'))

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
        if time.time() - ts > SPECS_CACHE_TTL:
            return None
        specs = data.get("specs")
        if isinstance(specs, dict):
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
        log_event(f"Error reading SSD thresholds from config: {e}")
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

_laptop_specs_cache = None

def get_laptop_specs(force_refresh=False):
    global _laptop_specs_cache
    if _laptop_specs_cache is not None and not force_refresh:
        log_event("Returning cached laptop specs.")
        return _laptop_specs_cache.copy()

    if not force_refresh:
        cached_specs = _load_cached_specs()
        if cached_specs:
            _laptop_specs_cache = cached_specs.copy()
            return _laptop_specs_cache.copy()

    log_event("Fetching laptop specs...")
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
        build_number = int(os_info.BuildNumber)
        specs["Windows"] = "Windows 11" if build_number >= 22000 else "Windows 10"
        log_event(f"Detected Windows Version: {specs['Windows']}")

        system_info = c.Win32_ComputerSystem()[0]
        if "lenovo" in system_info.Manufacturer.lower():
            family = system_info.SystemFamily.strip()
            specs["Model"] = re.sub(r"(?i)ThinkPad\\s*", "", family).strip() or system_info.Model.strip()
        else:
            specs["Model"] = system_info.Model.strip()
        log_event(f"Detected Model: {specs['Model']}")

        specs["RAM"] = f"{round(psutil.virtual_memory().total / (1024**3))}GB"
        log_event(f"Detected RAM: {specs['RAM']}")

        # --- Improved SSD/Drive Size Calculation ---
        drive_sizes = []
        drive_type = "HDD"
        physical_drives = {}
        for disk in c.Win32_DiskDrive():
            # Skip USB/removable drives
            if hasattr(disk, "InterfaceType") and disk.InterfaceType and disk.InterfaceType.upper() == "USB":
                continue
            if hasattr(disk, "MediaType") and disk.MediaType and "removable" in disk.MediaType.lower():
                continue
            # Get size in GB
            if disk.Size:
                size_gb = int(int(disk.Size) / (1000 ** 3))
                physical_drives[disk.DeviceID] = size_gb
                caption = disk.Caption.lower()
                media_type = disk.MediaType.lower() if disk.MediaType else ""
                if any(x in caption for x in ["ssd", "nvme", "m.2"]) or "ssd" in media_type:
                    drive_type = "SSD"

        # Map logical disks to physical disks and only count those on non-removable drives
        for partition in c.Win32_DiskPartition():
            for logical in partition.associators("Win32_LogicalDiskToPartition"):
                # Find the physical drive for this partition
                for disk in c.Win32_DiskDrive():
                    for part in disk.associators("Win32_DiskDriveToDiskPartition"):
                        if part.DeviceID == partition.DeviceID and disk.DeviceID in physical_drives:
                            # Only add size if not already counted
                            if physical_drives[disk.DeviceID] not in drive_sizes:
                                drive_sizes.append(physical_drives[disk.DeviceID])

        if drive_sizes:
            specs["SSD"] = "+".join(f"{size}GB" for size in drive_sizes)
            specs["Drive Type"] = drive_type
            log_event(f"Detected SSD: {specs['SSD']} ({specs['Drive Type']})")

        healths = get_battery_health()
        specs["Battery"] = f"{healths[0]}" if isinstance(healths[0], str) else "Unknown"
        if len(healths) > 1:
            specs["Battery 2"] = f"{healths[1]}" if isinstance(healths[1], str) else "Unknown"
        log_event(f"Detected Battery Health: {specs['Battery']}")

    except Exception as e:
        log_event(f"Exception in get_laptop_specs: {e}")
        raise
    finally:
        pythoncom.CoUninitialize()

    _laptop_specs_cache = specs.copy()
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

# --- BatteryInfoView fallback ---
def get_battery_health_batteryinfoview():
    try:
        exe_path = ensure_batteryinfoview()
        csv_path = os.path.join(os.environ.get("TEMP", "/tmp"), "batteryinfoview.csv")
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        cmd = [exe_path, "/scomma", csv_path]
        subprocess.run(cmd, check=True, creationflags=creationflags)
        if not os.path.exists(csv_path):
            log_event("BatteryInfoView CSV not created.")
            return ["Unknown (batteryinfoview)"]
        with open(csv_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        # Find the line with "Designed Capacity" and "Full Charged Capacity"
        designed = None
        full = None
        for line in lines:
            if "Designed Capacity" in line:
                try:
                    match = re.search(r"(\d+)", line)
                    if match:
                        designed = int(match.group(1))
                    else:
                        log_event(f"Designed Capacity not found in line: {line}")
                except Exception as e:
                    log_event(f"Error parsing Designed Capacity: {e} in line: {line}")
            if "Full Charged Capacity" in line:
                try:
                    match = re.search(r"(\d+)", line)
                    if match:
                        full = int(match.group(1))
                    else:
                        log_event(f"Full Charged Capacity not found in line: {line}")
                except Exception as e:
                    log_event(f"Error parsing Full Charged Capacity: {e} in line: {line}")
        if designed and full:
            percent = int((full / designed) * 100)
            log_event(f"BatteryInfoView: Designed={designed}, Full={full}, Health={percent}%")
            return [f"{percent}% (batteryinfoview)"]
        else:
            log_event(f"BatteryInfoView parsing failed: Designed={designed}, Full={full}")
            return ["Unknown (batteryinfoview)"]
    except Exception as e:
        log_event(f"BatteryInfoView failed: {e}")
        return ["Unknown (batteryinfoview)"]

# --- Main battery health function ---
def get_battery_health():
    log_event("Gathering battery health via BatteryInfoView.")
    return get_battery_health_batteryinfoview()
