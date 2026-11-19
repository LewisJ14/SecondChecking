"""Build and submit an order-independent capture from installed Windows."""
from urllib.parse import urlsplit
from uuid import uuid4

from services import operator_session, transport
from services.configuration import service_settings
from services.measurements import fresh

SPEC_NAMES = {
    "manufacturer": "Manufacturer", "model": "Model", "cpu": "CPU",
    "ram": "RAM", "storage": "SSD", "installed_windows": "Windows",
}


def _spec(value):
    if not isinstance(value, str) or value.strip().casefold() in {"", "unknown"}:
        return ""
    return value.strip()[:255]


def build_capture(measurements, mdm_state, features=None):
    serial = _spec(measurements.get("Serial Number"))
    if (not serial or len(serial) > 100 or any(ord(char) < 32 for char in serial)
            or serial.upper() in {"NONE", "N/A", "DEFAULT STRING", "TO BE FILLED BY O.E.M."}):
        raise ValueError("Windows did not report a usable device serial.")
    if not fresh(measurements):
        raise ValueError("Fresh Windows measurements are unavailable. Scan the laptop again.")
    specs = {field: _spec(measurements.get(name)) for field, name in SPEC_NAMES.items()}
    if not specs["manufacturer"] or not specs["model"]:
        raise ValueError("Windows did not report the laptop's manufacturer and model.")
    graphics = measurements.get("Graphics", [])
    specs["gpu"] = _spec(" / ".join(graphics))
    screen_mode = _spec(measurements.get("Resolution"))
    battery = measurements.get("Battery Evidence") or {}
    batteries = [
        {"health_percent": round(entry["health_percent"], 1) if "health_percent" in entry else None,
         "full_charge_capacity": entry.get("full_capacity"),
         "design_capacity": entry.get("designed_capacity"),
         "cycle_count": entry.get("cycle_count"),
         "source": battery.get("source")}
        for entry in battery.get("batteries", [])
    ]
    battery_labels = [measurements.get("Battery")]
    battery_labels.extend(measurements[key] for key in measurements if key.startswith("Battery ")
                          and key[8:].isdigit())
    return {
        "capture_id": str(uuid4()),
        "captured_at": measurements["Measurements"]["checked_at"],
        "serial_number": serial,
        "specs": specs,
        "features": features or {},
        "evidence": {
            "battery_health": " / ".join(filter(None, map(_spec, battery_labels))) or "Unknown",
            "batteries": batteries,
            "current_resolution": screen_mode,
            "local_mdm_state": mdm_state,
        },
    }


def submit_capture(payload):
    base, key = service_settings()
    generation = operator_session.generation()
    headers = operator_session.headers(base)
    if not headers or not operator_session.allowed("test"):
        raise RuntimeError("Sign in with device-check access before saving a listing draft.")
    headers["X-Second-Check-Key"] = key
    response = transport.post(base + "/api/second-check/listing-captures",
                              headers=headers, json=payload, timeout=20)
    if response.status_code == 401:
        operator_session.clear_if_current(generation)
        raise RuntimeError("Your session expired. Sign in again to save a listing draft.")
    if response.status_code == 404:
        raise RuntimeError("Listing capture is unavailable on this Astro server. Check its version.")
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError("Astro returned an unexpected response. Try saving again.") from None
    if not isinstance(result, dict):
        raise RuntimeError("Astro returned an invalid capture receipt.")
    if response.status_code != 200 or result.get("success") is not True:
        error = result.get("error")
        raise RuntimeError(error if isinstance(error, str) else "Could not save the draft. Try again.")
    draft_url = result.get("draft_url")
    draft_id = result.get("draft_id")
    path = f"/orders/listing-drafts/{draft_id}"
    prefixed_path = urlsplit(base).path + path
    if (result.get("capture_id") != payload["capture_id"]
            or type(draft_id) is not int or draft_id < 1
            or result.get("state") not in (
                "draft", "validating", "publishing", "published", "publish_uncertain")
            or draft_url not in (path, prefixed_path)):
        raise RuntimeError("Astro returned an invalid capture receipt.")
    return result, base + path
