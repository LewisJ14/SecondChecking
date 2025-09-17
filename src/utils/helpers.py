import configparser
import subprocess
import os
import datetime
import re
import wmi
import sys
import zipfile
import urllib.request
import hashlib
from typing import Dict

def log_event(message):
    log_path = "logs.txt"
    try:
        # Log rotation: if log file > 5MB, rotate
        if os.path.exists(log_path) and os.path.getsize(log_path) > 5 * 1024 * 1024:
            if os.path.exists(log_path + ".1"):
                os.remove(log_path + ".1")
            os.rename(log_path, log_path + ".1")
        # Append the log message with a timestamp
        with open(log_path, "a", encoding="utf-8") as log_file:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Failed to log event: {e}")

def get_config_path():
    # Determine the path to the configuration file
    if getattr(sys, 'frozen', False):  # If running as a PyInstaller executable
        return os.path.join(os.path.dirname(sys.executable), 'config.ini')
    else:
        # Go up one directory from src/ when running as a script
        return os.path.join(os.path.dirname(__file__), '..', 'config.ini')

def load_config():
    log_event("Loading configuration file...")
    config = configparser.ConfigParser()
    try:
        config.read(get_config_path())
        log_event("Configuration file loaded successfully.")
    except Exception as e:
        log_event(f"Error loading configuration file: {e}")
        raise
    return config

def parse_percent(text):
    try:
        # Extract a percentage value from the given text
        match = re.search(r"-?\d+(\.\d+)?", text)
        if match:
            return int(float(match.group()))
    except Exception as e:
        log_event(f"parse_percent error: {e} for input: {text}")
    return None

def check_activation_status():
    """
    Check if Windows is permanently activated using slmgr.vbs /xpr.
    Returns True if activated, False otherwise.
    """
    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            ['cscript.exe', '//Nologo', 'C:\\Windows\\System32\\slmgr.vbs', '/xpr'],
            capture_output=True, text=True, timeout=10, creationflags=creationflags
        )
        output = result.stdout.lower()
        # Check for the activation confirmation message
        if "permanently activated" in output:
            return True
        log_event(f"[DEBUG] slmgr /xpr output: {output}")
    except Exception as e:
        log_event(f"check_activation_status error: {e}")
    return False


def is_internet_available(timeout: int = 5) -> bool:
    """Return True when outbound HTTP requests succeed within the timeout."""

    test_urls = (
        "https://www.msftconnecttest.com/connecttest.txt",
        "https://www.google.com/generate_204",
    )

    failures = []
    for url in test_urls:
        try:
            with urllib.request.urlopen(url, timeout=timeout):
                return True
        except Exception as exc:  # noqa: BLE001 - logging the specific failure
            failures.append(f"{url}: {exc}")
    for failure in failures:
        log_event(f"Internet connectivity probe failed: {failure}")
    return False


def check_mdm_lock_status() -> Dict[str, str]:
    """Inspect Autopilot registry values to determine Microsoft MDM lock status."""

    if sys.platform != "win32":
        message = "Microsoft MDM lock checks are only available on Windows."
        log_event(message)
        return {"state": "unsupported", "details": message}

    import winreg  # type: ignore[import]

    autopilot_key_path = r"SOFTWARE\Microsoft\Provisioning\Diagnostics\Autopilot"

    try:
        autopilot_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, autopilot_key_path)
    except FileNotFoundError:
        message = "Autopilot diagnostics registry key not found; device is likely not MDM locked."
        log_event(message)
        return {"state": "not_locked", "details": message}
    except OSError as exc:
        message = f"Failed to open Autopilot diagnostics registry key: {exc}"
        log_event(message)
        return {"state": "error", "details": message}

    def _query_value(key, value_name):
        try:
            value, _ = winreg.QueryValueEx(key, value_name)
            return value
        except FileNotFoundError:
            return None
        except OSError as exc:
            log_event(f"Error reading Autopilot registry value '{value_name}': {exc}")
            return None

    tenant_id = _query_value(autopilot_key, "CloudAssignedTenantId")
    tenant_domain = _query_value(autopilot_key, "CloudAssignedTenantDomain")

    entdm_id = None
    ztd_id = None
    try:
        correlations_key = winreg.OpenKey(autopilot_key, "EstablishedCorrelations")
    except FileNotFoundError:
        correlations_key = None
    except OSError as exc:
        log_event(f"Unable to open EstablishedCorrelations subkey: {exc}")
        correlations_key = None

    if correlations_key is not None:
        entdm_id = _query_value(correlations_key, "EntDMID")
        ztd_id = _query_value(correlations_key, "ZTDRegistrationID")
        winreg.CloseKey(correlations_key)

    winreg.CloseKey(autopilot_key)

    details_parts = []
    if tenant_id:
        details_parts.append(f"Tenant ID: {tenant_id}")
    if tenant_domain:
        details_parts.append(f"Tenant Domain: {tenant_domain}")
    if entdm_id:
        details_parts.append(f"EntDMID: {entdm_id}")
    if ztd_id:
        details_parts.append(f"ZTDID: {ztd_id}")

    if tenant_id:
        detail_text = " | ".join(details_parts) if details_parts else "Autopilot profile detected."
        log_event(f"Microsoft MDM lock detected: {detail_text}")
        return {"state": "locked", "details": detail_text}

    detail_text = "No Autopilot tenant information was found." if not details_parts else " | ".join(details_parts)
    log_event("Microsoft MDM lock not detected.")
    return {"state": "not_locked", "details": detail_text}

def extract_details_from_sku(sku):
    # Extract hardware details from the SKU string using keywords from the config
    config = load_config()
    details = {
        "Model": "Unknown",
        "CPU": "Unknown",
        "SSD": "Unknown",
        "RAM": "Unknown",
        "Resolution": "Unknown",
        "Windows": "Unknown",
        "Battery": "Unknown"
    }

    CPU_KEYWORDS = config.get("search", "cpu_keywords").split(",")
    RAM_KEYWORDS = config.get("search", "ram_keywords").split(",")
    SSD_KEYWORDS = config.get("search", "ssd_keywords").split(",")
    MODEL_KEYWORDS = config.get("search", "model_keywords").split(",")
    RESOLUTION_KEYWORDS = config.get("search", "resolution_keywords").split(",")
    WINDOWS_KEYWORDS = config.get("search", "windows_keywords").split(",")
    GRADE_KEYWORDS = config.get("search", "grade_keywords").split(",")

    grade_map = {
        "AGRADE": "≥70%",
        "BGRADE": "≥45%",
        "CGRADE": "≥5%"
    }

    def match_with_fallback(keywords, target):
        for keyword in keywords:
            if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", target, re.IGNORECASE):
                return keyword
        for keyword in keywords:
            if keyword.lower() in target.lower():
                return keyword
        return None

    model_match = match_with_fallback(MODEL_KEYWORDS, sku)
    if model_match:
        details["Model"] = model_match

    cpu_match = match_with_fallback(CPU_KEYWORDS, sku)
    if cpu_match:
        details["CPU"] = cpu_match

    ssd_match = match_with_fallback(SSD_KEYWORDS, sku)
    if ssd_match:
        if "TB" in ssd_match.upper():
            details["SSD"] = ssd_match.replace("SSD", "").strip()
        else:
            details["SSD"] = ssd_match.replace("SSD", "").strip() + "GB"

    ram_match = match_with_fallback(RAM_KEYWORDS, sku)
    if ram_match:
        details["RAM"] = ram_match.replace("RAM", "").replace("GB", "").strip() + "GB"

    res_match = match_with_fallback(RESOLUTION_KEYWORDS, sku)
    if res_match:
        details["Resolution"] = res_match

    win_match = match_with_fallback(WINDOWS_KEYWORDS, sku)
    if win_match:
        details["Windows"] = "Windows 11" if "11" in win_match else "Windows 10"

    for keyword in GRADE_KEYWORDS:
        if keyword.upper() in sku.upper():
            details["Battery"] = grade_map.get(keyword.upper(), "Unknown")

    return details

_wmi_instance = None  # Cache WMI instance

def get_live_battery_percent(index=0):
    global _wmi_instance
    try:
        if _wmi_instance is None:
            _wmi_instance = wmi.WMI()
        batteries = _wmi_instance.Win32_Battery()
        if index < len(batteries):
            return int(batteries[index].EstimatedChargeRemaining)
    except Exception as e:
        log_event(f"get_live_battery_percent error: {e}")
    return None

def preload_previous_results():
    # Load previous test results from the database for the current serial number
    from utils.specs import get_laptop_specs
    from db.database import get_db_connection
    from utils.helpers import log_event

    specs = get_laptop_specs()
    serial_number = specs.get("Serial Number", "Unknown")
    results = {}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT test_keyboard, test_speaker, test_display, test_webcam, test_usb
            FROM order_serials
            WHERE serial_number = %s
        """, (serial_number,))
        row = cursor.fetchone()
        conn.close()

        print(f"Row from DB: {row}")  # 🧪 Debug output

        if row:
            keys = ["keyboard", "speaker", "display", "webcam", "usb"]
            for i, result in enumerate(row):
                cleaned = result.strip().lower() if result else ""
                if cleaned in ["pass", "fail"]:
                    results[keys[i]] = cleaned
                elif cleaned in ["n/a", "na"]:
                    results[keys[i]] = "Not Run"
                elif cleaned == "":
                    results[keys[i]] = "Not Run"
                else:
                    log_event(f"Unexpected result value: {result} for {keys[i]}")
    except Exception as err:
        log_event(f"MySQL error loading test results: {err}")

    return results

def ensure_batteryinfoview(download_dir="assets/BatteryInfoView"):
    """
    Ensure BatteryInfoView is downloaded and extracted in the specified directory.
    Returns the path to BatteryInfoView.exe.
    """
    url = "https://www.nirsoft.net/utils/batteryinfoview-x64.zip"
    zip_name = "batteryinfoview-x64.zip"
    exe_name = "BatteryInfoView.exe"
    os.makedirs(download_dir, exist_ok=True)
    exe_path = os.path.join(download_dir, exe_name)
    zip_path = os.path.join(download_dir, zip_name)

    # Check if already extracted
    if os.path.exists(exe_path):
        return exe_path

    # Download if not present
    if not os.path.exists(zip_path):
        try:
            print(f"Downloading {url}...")
            urllib.request.urlretrieve(url, zip_path)
        except Exception as err:
            log_event(f"Failed to download BatteryInfoView: {err}")
            raise

    expected_hash = os.getenv("BATTERYINFOVIEW_SHA256")
    if expected_hash:
        sha256 = hashlib.sha256()
        with open(zip_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        file_hash = sha256.hexdigest()
        if file_hash.lower() != expected_hash.lower():
            log_event(
                f"BatteryInfoView checksum mismatch: expected {expected_hash}, got {file_hash}"
            )
            os.remove(zip_path)
            raise ValueError("BatteryInfoView checksum mismatch")
    else:
        log_event("BATTERYINFOVIEW_SHA256 not set; skipping checksum verification")

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(download_dir)
    except Exception as err:
        log_event(f"Failed to extract BatteryInfoView: {err}")
        raise
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)

    if not os.path.exists(exe_path):
        raise FileNotFoundError(f"{exe_name} not found after extraction.")

    return exe_path
