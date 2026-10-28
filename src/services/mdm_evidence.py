"""Local deployment observations are not tenant registration verification."""

from copy import deepcopy
from datetime import datetime, timezone

SOURCE = "windows_autopilot_registry"
LOCAL_STATES = {"local_indicators", "no_local_indicators", "error",
                "unsupported", "unknown"}


def evidence(state, details, **fields):
    result = {
        "evidence_version": 1, "state": state, "source": SOURCE,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "tenant_verification": "not_checked", "details": details,
        "observations": {}, "read_errors": [],
    }
    result.update(fields)
    return result


def qualified(status):
    if (isinstance(status, dict) and status.get("evidence_version") == 1
            and isinstance(status.get("state"), str)
            and status.get("state") in LOCAL_STATES
            and status.get("source") == SOURCE
            and status.get("tenant_verification") == "not_checked"):
        return deepcopy(status)
    return evidence("unknown", "Local evidence unavailable or from an unqualified legacy check.",
                    checked_at=None)


def summary(status):
    status = qualified(status)
    labels = {
        "local_indicators": "Local Autopilot indicators found; this does not establish a current MDM lock.",
        "no_local_indicators": "No local Autopilot indicators found; this does not establish that the device is clear.",
        "error": "Local Autopilot evidence could not be read completely.",
        "unsupported": "Local Autopilot evidence is unavailable on this platform.",
        "unknown": "Local Autopilot evidence is unknown.",
    }
    lines = [labels[status["state"]],
             "Tenant registration / enrolment: NOT VERIFIED."]
    color = "#b42318" if status["state"] == "local_indicators" else "#b54708"
    return "\n".join(lines), color


def needs_review(status):
    status = qualified(status)
    return status["state"] != "no_local_indicators" or bool(status.get("read_errors"))
