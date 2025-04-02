import configparser
import os
import datetime
import re
import wmi
import sys

def log_event(message):
    with open("logs.txt", "a", encoding="utf-8") as log_file:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file.write(f"[{timestamp}] {message}\n")

def load_config(config_file="config.ini"):
    import sys

    config = configparser.ConfigParser()

    required_config = {
        "database": ["host", "user", "password", "database"],
        "search": [
            "cpu_keywords", "ram_keywords", "ssd_keywords", "model_keywords",
            "resolution_keywords", "windows_keywords", "grade_keywords"
        ]
    }

    # Always get the folder containing the EXE or script
    base_path = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__)
    config_path = os.path.join(base_path, config_file)

    if not os.path.exists(config_path):
        log_event(f"Missing config.ini at: {config_path}")
        raise FileNotFoundError("Missing config.ini")

    config.read(config_path)

    for section, keys in required_config.items():
        if not config.has_section(section):
            raise ValueError(f"Missing section: [{section}]")
        for key in keys:
            if not config.has_option(section, key):
                raise ValueError(f"Missing option: [{section}] {key}")

    return config

def parse_percent(text):
    try:
        return int(re.search(r"\d+", text).group())
    except:
        return None

def extract_details_from_sku(sku):
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

def get_live_battery_percent(index=0):
    try:
        c = wmi.WMI()
        batteries = c.Win32_Battery()
        if index < len(batteries):
            return int(batteries[index].EstimatedChargeRemaining)
    except:
        pass
    return None