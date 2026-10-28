"""Result states and the provenance of manual bench decisions."""

from copy import deepcopy
from datetime import datetime, timezone

TEST_KEYS = ("keyboard", "speaker", "microphone", "display", "webcam", "usb",
             "wifi", "activation")
STATES = {"pass", "fail", "n/a", "cancelled", "unavailable", "error"}


def normalise(value):
    text = str(value or "").strip().lower()
    return text if text in STATES else "n/a"


def current_override(results, key):
    events = results.get("_overrides", {}).get(key, [])
    if events and events[-1].get("active"):
        return events[-1]
    return None


def clear_override(results, key):
    """Retesting supersedes a decision without deleting its audit history."""
    for event in results.get("_overrides", {}).get(key, []):
        event["active"] = False


def start_measurement(results, key):
    clear_override(results, key)
    results.get('_coverage', {}).pop(key, None)
    unknown = results.get("_history_unknown", [])
    results["_history_unknown"] = [name for name in unknown if name != key]
    results["_provenance_unknown"] = bool(results["_history_unknown"])


def record_override(results, key, value, operator, reason):
    reason = str(reason or "").strip()
    operator = str(operator or "").strip()
    if key not in TEST_KEYS or value not in STATES:
        raise ValueError("Invalid test or replacement result.")
    if not operator or not reason or len(reason) > 2000:
        raise ValueError("An operator and reason (1–2000 characters) are required.")
    previous = normalise(results.get(key))
    existing = current_override(results, key)
    measured = existing["measured_result"] if existing else previous
    clear_override(results, key)
    event = {
        "measured_result": measured, "previous_result": previous,
        "result": value, "operator": operator, "reason": reason,
        "at": datetime.now(timezone.utc).isoformat(), "active": True,
    }
    results.setdefault("_overrides", {}).setdefault(key, []).append(event)
    results[key] = value


def badge_text(results, key):
    state = normalise(results.get(key))
    label = "NOT RUN" if state == "n/a" else state.upper()
    if current_override(results, key):
        return "OVERRIDDEN " + label
    if key in results.get("_history_unknown", []):
        return label + " (HISTORY UNKNOWN)"
    return label


def snapshot(results):
    return ({key: normalise(results.get(key)) for key in TEST_KEYS},
            deepcopy(results.get("_overrides", {})))


def review_lines(results):
    from services.test_coverage import coverage_lines
    lines = []
    groups = (("Passed", "pass"), ("Failed", "fail"), ("Incomplete", "n/a"),
              ("Cancelled", "cancelled"), ("Unavailable", "unavailable"),
              ("Test errors", "error"))
    for title, state in groups:
        names = [key.title() for key in TEST_KEYS
                 if normalise(results.get(key)) == state]
        if names:
            lines.append(title + ": " + ", ".join(names))
    for key in TEST_KEYS:
        event = current_override(results, key)
        if event:
            lines.append("Overridden {}: {} → {} by {}. Reason: {}".format(
                key.title(), event["measured_result"], event["result"],
                event["operator"], event["reason"]))
    return lines + coverage_lines(results)


def needs_reason(results):
    return any(normalise(results.get(key)) != "pass"
               or current_override(results, key) for key in TEST_KEYS)
