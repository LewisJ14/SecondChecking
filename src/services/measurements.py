"""Capture age and battery export parsing, independent of hardware access."""

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import io
import math
import re
import time


def utc_now():
    # Use the same wall clock and microsecond conversion as capture_age. Mixing
    # datetime.now with float epoch subtraction can make an immediate check
    # appear a fraction of a microsecond in the future on Windows.
    return datetime.fromtimestamp(time.time(), timezone.utc).isoformat()


def capture_age(specs):
    try:
        stamp = specs["Measurements"]["checked_at"]
        captured = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if captured.utcoffset() is None:
            return None
        now = datetime.fromtimestamp(time.time(), timezone.utc)
        age = (now - captured).total_seconds()
        return age if age >= 0 else None
    except (KeyError, TypeError, AttributeError, ValueError):
        return None


def fresh(specs, ttl=300):
    age = capture_age(specs)
    return age is not None and age <= ttl


def measurement_summary(specs):
    age = capture_age(specs)
    metadata = specs.get("Measurements", {})
    return ("Device capture: " + str(metadata.get("checked_at") or "Unknown")
            + " | Age: " + (str(int(age)) + "s" if age is not None else "Unknown"))


def _capacity(value):
    match = re.fullmatch(r"\s*([\d][\d\s.,\u00a0]*)\s*(mWh|mAh)?\s*", value, re.I)
    if not match:
        return None
    number = re.sub(r"[\s\u00a0]", "", match.group(1))
    if "." in number and "," in number:
        decimal = "." if number.rfind(".") > number.rfind(",") else ","
        number = number.replace("," if decimal == "." else ".", "").replace(decimal, ".")
    elif "," in number or "." in number:
        delimiter = "," if "," in number else "."
        groups = number.split(delimiter)
        if len(groups) > 1 and all(len(group) == 3 for group in groups[1:]):
            number = "".join(groups)
        elif len(groups) == 2:
            number = number.replace(delimiter, ".")
        else:
            return None
    try:
        amount = Decimal(number)
        if amount.is_finite() and amount >= 0:
            return amount, (match.group(2) or "unspecified").lower()
    except InvalidOperation:
        pass
    return None


def parse_battery_csv(content):
    """Pair full/design capacity by CSV column or row, never by loose numbers."""
    try:
        dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(content), dialect))
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    design, full = "designed capacity", "full charged capacity"
    cycle_labels = {"number of charge/discharge cycles", "cycle count"}
    pairs = []
    if rows:
        header = [cell.strip().casefold() for cell in rows[0]]
        if design in header and full in header:
            cycle_column = next((i for i, name in enumerate(header)
                                 if name in cycle_labels), None)
            for row in rows[1:]:
                pairs.append((row[header.index(design)] if len(row) > header.index(design) else "",
                              row[header.index(full)] if len(row) > header.index(full) else "",
                              row[cycle_column] if cycle_column is not None
                              and len(row) > cycle_column else ""))
        else:
            columns = {}
            for row in rows:
                label = row[0].strip().casefold()
                if label in cycle_labels:
                    label = "cycles"
                if label in {design, full, "cycles"}:
                    if label in columns:
                        return [{"state": "unreadable", "reason": "Duplicate capacity rows"}]
                    columns[label] = row[1:]
            if columns:
                width = max(len(values) for values in columns.values())
                for index in range(width):
                    pairs.append(tuple(columns.get(label, [])[index]
                                       if index < len(columns.get(label, [])) else ""
                                       for label in (design, full, "cycles")))
    results = []
    for index, (designed, charged, cycles) in enumerate(pairs, 1):
        left, right = _capacity(designed), _capacity(charged)
        entry = {"index": index, "state": "unreadable"}
        count = cycles.strip()
        if re.fullmatch(r"[0-9]+", count):
            count = int(count)
            if 0 < count < 0xffffffff:
                entry["cycle_count"] = count
        if left and right and left[0] > 0 and left[1] == right[1]:
            percent = float(right[0] / left[0] * 100)
            if math.isfinite(percent):
                entry.update(state="measured", health_percent=percent,
                             designed_capacity=str(left[0]), full_capacity=str(right[0]),
                             unit=left[1])
        results.append(entry)
    return results or [{"state": "unreadable", "reason": "Capacity columns/rows unavailable"}]


def pair_windows_batteries(static_rows, full_rows, expected_count=None,
                          cycle_rows=None):
    """Join capacities by WMI instance, never by enumeration order or name."""
    groups = []
    for rows in (static_rows, full_rows):
        grouped = {}
        for row in rows:
            identity = row.get("InstanceName")
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError("Battery instance identity unavailable")
            grouped.setdefault(identity.casefold(), []).append(row)
        groups.append(grouped)
    identities = sorted(set(groups[0]) | set(groups[1]))
    if not identities:
        raise ValueError("Windows battery capacity data unavailable")
    entries = []
    cycles = {}
    for row in cycle_rows or []:
        identity = row.get("InstanceName")
        if isinstance(identity, str) and identity.strip():
            cycles.setdefault(identity.casefold(), []).append(row.get("CycleCount"))
    for index, identity in enumerate(identities, 1):
        entry = {"index": index, "instance_name": identity,
                 "state": "unreadable"}
        counts = cycles.get(identity, [])
        if (len(counts) == 1 and type(counts[0]) is int
                and 0 < counts[0] < 0xffffffff):
            entry["cycle_count"] = counts[0]
        left, right = (group.get(identity, []) for group in groups)
        if len(left) != 1 or len(right) != 1:
            entry["reason"] = "Missing or duplicate battery capacity record"
        else:
            design = left[0].get("DesignedCapacity")
            full = right[0].get("FullChargedCapacity")
            capabilities = left[0].get("Capabilities")
            if (type(design) is int and type(full) is int
                    and 0 < design < 0xffffffff and 0 <= full < 0xffffffff
                    and type(capabilities) is int):
                entry.update(state="measured", health_percent=full / design * 100,
                             designed_capacity=str(design), full_capacity=str(full),
                             unit="relative" if capabilities & 0x40000000 else "mwh")
            else:
                entry["reason"] = "Invalid or unknown battery capacity"
        entries.append(entry)
    if expected_count is not None and len(entries) != expected_count:
        return [{"index": index + 1, "state": "unreadable",
                 "reason": "Battery count differs between inventory and capacity data"}
                for index in range(max(expected_count, len(entries)))]
    return entries


def battery_labels(entries, source="BatteryInfoView"):
    labels = []
    for entry in entries:
        if entry.get("state") != "measured":
            labels.append("Unreadable (battery health)")
            continue
        count = entry.get("cycle_count")
        cycles = (f"{count} {'cycle' if count == 1 else 'cycles'}"
                  if type(count) is int and 0 < count < 0xffffffff
                  else "cycles unavailable")
        labels.append(f"{entry['health_percent']:.1f}% ({cycles}) ({source} health)")
    return labels


def native_battery_live_state(static_rows, full_rows, status_rows, index=0,
                              expected_count=None):
    """Join live power and capacity by pack identity, never enumeration order."""
    groups = []
    for rows in (static_rows, full_rows, status_rows):
        group = {}
        for row in rows:
            identity = row.get('InstanceName')
            if not isinstance(identity, str) or not identity.strip():
                return None
            key = identity.casefold()
            if key in group:
                return None
            group[key] = row
        groups.append(group)
    identities = sorted(groups[0])
    if (not identities or set(identities) != set(groups[2])
            or (groups[1] and set(identities) != set(groups[1]))
            or (expected_count is not None and len(identities) != expected_count)
            or not 0 <= index < len(identities)):
        return None
    identity = identities[index]
    static, full, status = (group.get(identity, {}) for group in groups)
    charging, discharging = status.get('Charging'), status.get('Discharging')
    if type(charging) is not bool or type(discharging) is not bool or (charging and discharging):
        return None
    state = ('Charging' if charging else 'Discharging' if discharging else
             'Not charging' if status.get('PowerOnline') is True else 'Idle')
    result = dict(percent=None, charging=charging, power_state=state,
                  rate_watts=None, rate_state='unavailable',
                  source='Windows battery status')
    capacity, remaining = full.get('FullChargedCapacity'), status.get('RemainingCapacity')
    if (type(capacity) is int and 0 < capacity < 0xffffffff
            and type(remaining) is int and 0 <= remaining <= capacity):
        result['percent'] = round(remaining / capacity * 100)
    capabilities = static.get('Capabilities')
    if type(capabilities) is int and capabilities & 0x40000000:
        result['rate_state'] = 'relative'
        return result
    rate = status.get('ChargeRate') if charging else status.get('DischargeRate')
    if not charging and not discharging:
        # Zero is measured only if both counters explicitly report zero.
        rate = (0 if all(type(status.get(key)) is int and status[key] == 0
                         for key in ('ChargeRate', 'DischargeRate')) else None)
    if (type(capabilities) is int and capabilities >= 0 and type(rate) is int
            and 0 <= rate < 0x80000000):
        result.update(rate_watts=rate / 1000.0, rate_state='measured')
    return result


def battery_power_label(live):
    state = live.get('power_state', 'Unknown')
    if state == 'AC power (charging unconfirmed)':
        state = 'AC power'
    rate = live.get('rate_watts')
    if (type(rate) in (int, float) and math.isfinite(rate) and rate >= 0
            and live.get('rate_state') == 'measured'):
        return '{} — {:.1f} W'.format(state, rate)
    return '{} — rate unavailable'.format(state)
