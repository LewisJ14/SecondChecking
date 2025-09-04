# utils/specs.py
import re
import psutil
import wmi
import subprocess
import os
from utils.helpers import log_event, ensure_batteryinfoview
import pythoncom
import configparser
import getpass
import sys

config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), '..', 'config.ini'))

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
    # Intel Core iX-YYYY
    intel = re.search(r'(i[3579]-[A-Za-z0-9]+)', cpu_name, re.IGNORECASE)
    if intel:
        return intel.group(1)
    # AMD Ryzen X YYYY
    amd = re.search(r'(Ryzen\s*[3579]\s*\d+[A-Za-z0-9]*)', cpu_name, re.IGNORECASE)
    if amd:
        return amd.group(1).replace("  ", " ")
    # Fallback: just return the first 2 words
    return " ".join(cpu_name.split()[:2])

_laptop_specs_cache = None

def get_laptop_specs(force_refresh=False):
    global _laptop_specs_cache
    if _laptop_specs_cache is not None and not force_refresh:
        log_event("Returning cached laptop specs.")
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
    # Retrieve battery health using multiple fallback methods
    try:
        # Attempt to parse battery health from an HTML report
        temp_path = os.path.join(os.environ.get("TEMP", "/tmp"), "battery-report.html")
        user_path = os.path.join("C:\\Users", getpass.getuser(), "battery-report.html")
        html = None

        if os.path.exists(temp_path):
            with open(temp_path, encoding="utf-8", errors="ignore") as f:
                html = f.read()
        elif os.path.exists(user_path):
            with open(user_path, encoding="utf-8", errors="ignore") as f:
                html = f.read()

        if html:
            if "No batteries are currently installed" in html:
                log_event("Battery report: No batteries are currently installed.")
                return ["No battery installed"]

            # Try to parse design and full charge capacity
            design_matches = re.findall(r"DESIGN CAPACITY.*?<td>([\d,]+)\s*mWh", html, re.IGNORECASE)
            full_matches = re.findall(r"FULL CHARGE CAPACITY.*?<td>([\d,]+)\s*mWh", html, re.IGNORECASE)

            if design_matches and full_matches:
                battery_healths = []
                for design, full in zip(design_matches, full_matches):
                    try:
                        design = int(design.replace(",", ""))
                        full = int(full.replace(",", ""))
                        percent = int((full / design) * 100)
                        battery_healths.append(f"{percent}%")
                    except Exception as e:
                        log_event(f"Battery health calculation error: {e}")
                        battery_healths.append("Unknown")
                return battery_healths

            log_event("Battery health parsing failed: No matches found in HTML.")

    except Exception as e:
        log_event(f"Battery health HTML parsing failed: {e}")

    # Fallback to BatteryInfoView if HTML parsing fails
    biv_health = get_battery_health_batteryinfoview()
    return biv_health