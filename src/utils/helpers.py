import configparser
import subprocess
import winreg
import os
import datetime
import re
import wmi
import sys
import zipfile
import urllib.request

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
        print(f"Downloading {url}...")
        urllib.request.urlretrieve(url, zip_path)

    # Extract
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(download_dir)

    # Optionally, remove the zip after extraction
    os.remove(zip_path)

    if not os.path.exists(exe_path):
        raise FileNotFoundError(f"{exe_name} not found after extraction.")

    return exe_path
