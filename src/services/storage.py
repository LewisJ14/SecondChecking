"""Compare physical drive configurations, never an accidental capacity total."""

from datetime import datetime, timezone
import re
import math

CAPACITY_TOLERANCE = 0.01
COMPONENT = re.compile(
    r"\s*(?:(\d+)\s*[x×]\s*)?"
    r"(?:(NVME(?:\s*SSD)?|SSD|HDD|SCM)\s*)?"
    r"(\d+(?:\.\d+)?)\s*(TIB|GIB|TB|GB)?\s*"
    r"(?:(NVME)(?:\s*SSD)?|(SSD|HDD|SCM))?\s*", re.I)


def parse_configuration(value):
    if not isinstance(value, str) or not value.strip():
        return None
    drives = []
    for part in value.split("+"):
        match = COMPONENT.fullmatch(part)
        if not match:
            return None
        count, prefix, number, unit, nvme, suffix = match.groups()
        prefix = "NVME" if prefix and prefix.upper().startswith("NVME") else (prefix or "").upper()
        kind = (nvme or suffix or prefix or "").upper()
        if prefix and (nvme or suffix) and prefix != kind:
            if {prefix, kind} == {"SSD", "NVME"}:
                kind = "NVME"
            else:
                return None
        if not unit and not kind:
            return None
        unit = (unit or "GB").upper()
        try:
            amount = float(number)
            count = int(count or 1)
        except (ValueError, OverflowError):
            return None
        if not math.isfinite(amount) or amount <= 0 or count < 1 or count > 32:
            return None
        # Compatibility with pre-SC07 nominal binary-looking GB labels.
        if unit == "GB" and amount in {1024, 2048, 4096, 8192}:
            amount *= 1000 / 1024
        multiplier = {"GB": 10**9, "TB": 10**12,
                      "GIB": 2**30, "TIB": 2**40}[unit]
        if not math.isfinite(amount * multiplier):
            return None
        drives.extend([{"size_bytes": amount * multiplier,
                        "kind": "SSD" if kind == "NVME" else kind,
                        "bus": "NVMe" if kind == "NVME" else None}]
                      * count)
    return drives if len(drives) <= 32 else None


def sku_storage(value, keywords):
    """Keep complete typed/recognised storage expressions in legacy SKUs."""
    token = r"(?:\d+\s*[x×]\s*)?(?:(?:NVMe\s*SSD|NVMe|SSD|HDD|SCM)\s*)?\d+(?:\.\d+)?\s*(?:TiB|GiB|TB|GB)?\s*(?:NVMe\s*SSD|NVMe|SSD|HDD|SCM)?"
    pattern = re.compile(r"(?<![A-Za-z0-9.])(" + token + r"(?:\s*\+\s*" + token + r")*)(?![A-Za-z0-9.])", re.I)
    found = []
    for match in pattern.finditer(str(value or "")):
        text = match.group(1).strip()
        compact = re.sub(r"\s+", "", text).casefold()
        recognised = any(re.sub(r"\s+", "", word).casefold() in compact
                         for word in keywords if word.strip())
        if (recognised or re.search(r"SSD|HDD|NVME|SCM", text, re.I)) and parse_configuration(text):
            found.append(text)
    return " + ".join(found) if found else None


def inventory(disks, physical_disks=(), type_errors=()):
    """Win32 device IDs identify entries; serials join optional type evidence."""
    types = {}
    for disk in physical_disks:
        serial = str(getattr(disk, "SerialNumber", "") or "").strip()
        if serial:
            types.setdefault(serial, []).append(disk)
    entries, errors, seen = [], [], set()
    for disk in disks:
        device = str(getattr(disk, "DeviceID", "") or "").strip()
        if not device:
            errors.append("A physical disk has no device ID.")
        elif device in seen:
            errors.append("Duplicate physical disk ID: " + device)
            continue
        seen.add(device)
        serial = str(getattr(disk, "SerialNumber", "") or "").strip()
        matches = types.get(serial, [])
        typed = matches[0] if len(matches) == 1 else None
        bus = str(getattr(typed, "BusType", "") or "")
        media = str(getattr(typed, "MediaType", "") or "")
        interface = str(getattr(disk, "InterfaceType", "") or "").upper()
        pnp = str(getattr(disk, "PNPDeviceID", "") or "").upper()
        removable = "removable" in str(getattr(disk, "MediaType", "") or "").lower()
        excluded = interface == "USB" or pnp.startswith(("USBSTOR\\", "USB\\")) or bus in {"7", "12"} or removable
        try:
            size = int(disk.Size)
            if size <= 0:
                raise ValueError()
        except (AttributeError, TypeError, ValueError):
            size = None
            if not excluded:
                errors.append("Physical capacity unavailable: " + (device or "unknown ID"))
        kind = {"3": "HDD", "4": "SSD", "5": "SCM"}.get(media, "Unknown")
        entries.append({
            "device_id": device, "serial_number": serial, "size_bytes": size,
            "kind": kind, "bus": "NVMe" if bus == "17" else interface,
            "model": str(getattr(disk, "Model", "") or ""),
            "type_source": "MSFT_PhysicalDisk serial match" if typed else "Unknown",
            "excluded": excluded,
            "exclusion_reason": "USB/removable/SD media" if excluded else None,
        })
    return {"version": 1, "source": "Win32_DiskDrive",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "disks": entries, "errors": errors,
            "type_errors": list(type_errors)}


def inventory_label(captured):
    entries = [disk for disk in captured["disks"] if not disk["excluded"]]
    if not entries or captured["errors"]:
        return "Unknown"
    parts = []
    for disk in entries:
        size = disk["size_bytes"] / 10**9
        kind = " NVMe SSD" if disk["kind"] == "SSD" and disk["bus"] == "NVMe" else (
            " " + disk["kind"] if disk["kind"] != "Unknown" else "")
        parts.append(f"{size:.3f}".rstrip("0").rstrip(".") + "GB" + kind)
    return " + ".join(parts)


def compare_storage(expected, measured, captured=None):
    required = parse_configuration(expected)
    if not required:
        return False, "Storage requirement is missing, ambiguous or unsupported."
    if captured is not None:
        if not isinstance(captured, dict) or captured.get("version") != 1 or captured.get("errors"):
            return False, "Physical storage measurement is incomplete."
        rows = captured.get("disks")
        if not isinstance(rows, list) or any(not isinstance(disk, dict) for disk in rows):
            return False, "Physical storage measurement is incomplete."
        actual = [disk for disk in rows if not disk.get("excluded")]
    else:
        actual = parse_configuration(measured)
    if not actual:
        return False, "Physical storage capacity is unavailable."
    if len(required) != len(actual):
        return False, f"Expected {len(required)} physical drive(s), found {len(actual)}."

    def compatible(wanted, found):
        size = found.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(size) or size <= 0:
            return False
        if abs(wanted["size_bytes"] - size) > max(10**9, wanted["size_bytes"] * CAPACITY_TOLERANCE):
            return False
        kind = wanted["kind"]
        if wanted.get("bus") and wanted["bus"] != found.get("bus"):
            return False
        if kind and kind != found.get("kind"):
            return False
        return True

    # Match constrained types first; a generic requirement must not consume the
    # only drive that can satisfy a later explicit SSD/HDD/NVMe requirement.
    required = sorted(required, key=lambda disk: not bool(disk["kind"]))
    assigned = {}
    def match(index, visited):
        for item in range(len(actual)):
            if item in visited or not compatible(required[index], actual[item]):
                continue
            visited.add(item)
            if item not in assigned or match(assigned[item], visited):
                assigned[item] = index
                return True
        return False
    if not all(match(index, set()) for index in range(len(required))):
        return False, "Per-drive capacities or required media/bus types do not match (1% / 1GB tolerance)."
    return True, "Physical drive configuration matches."


def resolve_requirement(configured, sku_value):
    """Do not silently reduce an explicit SKU layout to one matching tag."""
    left, right = parse_configuration(configured), parse_configuration(sku_value)
    if not left or not right:
        return configured
    if not compare_storage(configured, sku_value)[0] and not compare_storage(sku_value, configured)[0]:
        return f"Ambiguous storage: configured {configured}; SKU {sku_value}"
    if len(left) != len(right):
        return f"Ambiguous storage: configured {configured}; SKU {sku_value}"
    if all(not disk["kind"] for disk in left) and any(disk["kind"] for disk in right):
        return sku_value
    if all(not disk.get("bus") for disk in left) and any(disk.get("bus") for disk in right):
        return sku_value
    return configured
