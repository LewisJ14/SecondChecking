# utils/specs.py
import re
import psutil
import platform
import wmi
import subprocess
import os
import tempfile
from utils.helpers import log_event
import pythoncom

SSD_THRESHOLDS = {
    "4TB": 3900,
    "2TB": 1800,
    "1TB": 900,
    "512GB": 450,
    "256GB": 220,
    "128GB": 110
}

def get_laptop_specs():
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

        for cpu in c.Win32_Processor():
            specs["CPU"] = re.sub(r"w/.*", "", cpu.Name).strip()
            break

        bios = c.Win32_BIOS()[0]
        specs["Serial Number"] = bios.SerialNumber.strip()

        for display in c.Win32_VideoController():
            if display.CurrentHorizontalResolution and display.CurrentVerticalResolution:
                specs["Resolution"] = f"{display.CurrentHorizontalResolution}x{display.CurrentVerticalResolution}"
                break

        os_info = c.Win32_OperatingSystem()[0]
        build_number = int(os_info.BuildNumber)
        specs["Windows"] = "Windows 11" if build_number >= 22000 else "Windows 10"

        system_info = c.Win32_ComputerSystem()[0]
        if "lenovo" in system_info.Manufacturer.lower():
            family = system_info.SystemFamily.strip()
            specs["Model"] = re.sub(r"(?i)ThinkPad\\s*", "", family).strip() or system_info.Model.strip()
        else:
            specs["Model"] = system_info.Model.strip()

        specs["RAM"] = f"{round(psutil.virtual_memory().total / (1024**3))}GB"

        total_disk_size = 0
        drive_type = "HDD"
        for disk in c.Win32_DiskDrive():
            size_gb_actual = int(disk.Size) / (1000**3)
            total_disk_size += size_gb_actual
            caption = disk.Caption.lower()
            media_type = disk.MediaType.lower() if disk.MediaType else ""
            if any(x in caption for x in ["ssd", "nvme", "m.2"]) or "ssd" in media_type:
                drive_type = "SSD"
        specs["Drive Type"] = drive_type

        for label, threshold in SSD_THRESHOLDS.items():
            if total_disk_size >= threshold:
                specs["SSD"] = label
                break
        else:
            specs["SSD"] = f"{round(total_disk_size)}GB"

        healths = get_battery_health()
        specs["Battery"] = f"{healths[0]}%" if isinstance(healths[0], int) else "Unknown"
        if len(healths) > 1:
            specs["Battery 2"] = f"{healths[1]}%" if isinstance(healths[1], int) else "Unknown"

    except Exception as e:
        log_event(f"Exception in get_laptop_specs: {e}")

    pythoncom.CoUninitialize()
    return specs

def get_live_battery_percent():
    try:
        w = wmi.WMI()
        for battery in w.Win32_Battery():
            return int(battery.EstimatedChargeRemaining)
    except Exception as e:
        log_event(f"Error reading live battery percent: {e}")
    return None

def get_battery_health():
    try:
        username = os.getlogin()
        fallback_path = os.path.join("C:\\Users", username, "battery-report.html")
        report_path = os.path.join(tempfile.gettempdir(), "battery-report.html")

        result = subprocess.run(
            ["powercfg", "/batteryreport", "/output", report_path],
            shell=True, capture_output=True
        )

        if result.returncode != 0:
            log_event(f"powercfg failed: {result.stderr.decode(errors='ignore')}")
            return ["Unknown"]

        if os.path.exists(report_path):
            path_to_use = report_path
        elif os.path.exists(fallback_path):
            log_event(f"Battery report not found in temp. Using fallback path: {fallback_path}")
            path_to_use = fallback_path
        else:
            log_event("Battery report not found in either temp or user directory.")
            return ["Unknown"]

        with open(path_to_use, "r", encoding="utf-8") as f:
            html = f.read()
        try:
            os.remove(path_to_use)
        except Exception as e:
            log_event(f"Could not delete battery report file: {e}")

        design_matches = re.findall(r"DESIGN CAPACITY.*?<td>([\d,]+)\s*mWh", html, re.IGNORECASE)
        full_matches = re.findall(r"FULL CHARGE CAPACITY.*?<td>([\d,]+)\s*mWh", html, re.IGNORECASE)

        battery_healths = []
        for d, f in zip(design_matches, full_matches):
            try:
                d_mwh = int(d.replace(",", ""))
                f_mwh = int(f.replace(",", ""))
                percent = int((f_mwh / d_mwh) * 100) if d_mwh else 0
                battery_healths.append(percent)
            except:
                battery_healths.append("Unknown")

        return battery_healths if battery_healths else ["Unknown"]

    except Exception as e:
        log_event(f"Exception in get_battery_health: {e}")
    return ["Unknown"]