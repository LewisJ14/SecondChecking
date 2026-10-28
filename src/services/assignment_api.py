"""Retry a server-owned assignment using one durable operation identity."""

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import threading
import time
from uuid import uuid4

import requests
from services import transport
from services.operator_session import headers as session_headers

_operation_lock = threading.Lock()
ORDER_ENDPOINTS = frozenset({
    "/api/stock_units/check-report",
    "/api/stock_units/unassign",
})


@contextmanager
def _journal_lock(path):
    """Release the per-device process lock automatically if the app crashes."""
    with path.with_suffix(".lock").open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _pending_directory():
    base = os.environ.get("LOCALAPPDATA") or str(
        Path.home() / ".local" / "share"
    )
    path = Path(base) / "SecondChecking" / "pending-operations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _intent_hash(endpoint, payload):
    intent = {
        k: v
        for k, v in payload.items()
        if k
        not in {
            "checked_at",
            "hash_uploaded_at",
            "operation_id",
            "create_stock_unit",
            "reassignment_token",
        }
    }
    # Reopening the same review changes its timestamp, not the bench decision.
    if isinstance(intent.get("assignment_review"), dict):
        intent["assignment_review"] = {
            key: value for key, value in intent["assignment_review"].items()
            if key != "at"
        }
    if isinstance(intent.get("mdm"), dict):
        intent["mdm"] = {key: value for key, value in intent["mdm"].items()
                         if key != "checked_at"}
    if isinstance(intent.get("specs"), dict):
        intent["specs"] = dict(intent["specs"])
        captured = intent["specs"].get("Storage")
        if isinstance(captured, dict):
            intent["specs"]["Storage"] = {
                key: value for key, value in captured.items() if key != "checked_at"
            }
        for field in ("Measurements", "Battery Evidence"):
            metadata = intent["specs"].get(field)
            if isinstance(metadata, dict):
                intent["specs"][field] = {key: value for key, value in metadata.items()
                                         if key != "checked_at"}
    if isinstance(intent.get("battery_report"), dict):
        intent["battery_report"] = {key: value for key, value in intent["battery_report"].items()
                                    if key != "checked_at"}
    if isinstance(intent.get("storage_review"), dict):
        intent["storage_review"] = {
            key: value for key, value in intent["storage_review"].items()
            if key != "captured_at"
        }
    return hashlib.sha256(
        json.dumps(
            [endpoint, intent],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _body(response):
    try:
        value = response.json()
    except ValueError:
        value = None
    return (
        value if isinstance(value, dict) else {"error": "Invalid API response"}
    )


def post_assignment(
    base_url, api_key, endpoint, payload, reassignment_prompt=None
):
    """Keep an uncertain request until its exact receipt can be reconciled.

    The journal contains the pending report, never the API key. A changed intent
    cannot silently replace a request whose outcome is still unknown.
    """
    if endpoint not in ORDER_ENDPOINTS:
        return False, {"error": "This desktop supports order operations only"}
    with _operation_lock:
        try:
            return _post_assignment(
                base_url, api_key, endpoint, payload, reassignment_prompt
            )
        except (OSError, ValueError) as exc:
            return False, {
                "error": "Could not preserve the pending operation: "
                + str(exc)
            }


def _post_assignment(base_url, api_key, endpoint, payload, prompt):
    headers = {"X-Second-Check-Key": api_key, "Accept": "application/json"}
    headers.update(session_headers(base_url))
    base_url = base_url.rstrip("/")
    try:
        capabilities = transport.get(
            base_url + "/api/stock_units/second-check-capabilities",
            headers=headers,
            timeout=10,
        )
        if capabilities.status_code in {401, 403}:
            return False, {"error": "Operator session expired or denied. Sign in again before retrying."}
        if (
            capabilities.status_code != 200
            or _body(capabilities).get("transactional_assignments") != 1
            or _body(capabilities).get("operator_sessions") != 1
        ):
            return False, {
                "error": "Web-Tools must be upgraded for transactional assignments first"
            }
    except requests.RequestException as exc:
        return False, {"error": str(exc)}

    serial = str(payload.get("serial_number") or "").strip().upper()
    mdm = payload.get("mdm")
    if (isinstance(mdm, dict) and mdm.get("evidence_version") == 1
            and _body(capabilities).get("mdm_evidence_version") != 1):
        return False, {"error": "Upgrade Web-Tools for qualified local MDM evidence first"}
    if (endpoint == "/api/stock_units/check-report"
            and payload.get("result_policy_version") == 1
            and _body(capabilities).get("result_policy_version") != 1):
        return False, {"error": "Upgrade Web-Tools for recorded result reviews first"}
    key = hashlib.sha256((base_url + "|" + serial).encode("utf-8")).hexdigest()
    path = _pending_directory() / (key + ".json")
    with _journal_lock(path):
        return _send_pending(
            base_url, headers, endpoint, payload, prompt, path
        )


def _send_pending(base_url, headers, endpoint, payload, prompt, path):
    intent = _intent_hash(endpoint, payload)
    recovered = False
    changed_intent = False
    if path.exists():
        pending = json.loads(path.read_text(encoding="utf-8"))
        try:
            receipt = transport.get(
                base_url
                + "/api/stock_units/second-check-operations/"
                + pending["payload"]["operation_id"],
                headers=headers,
                timeout=10,
            )
        except requests.RequestException as exc:
            return False, {
                "error": "Previous operation is unconfirmed: " + str(exc),
                "operation_id": pending["payload"]["operation_id"],
            }
        result = _body(receipt)
        if (
            receipt.status_code == 200
            and result.get("success")
            and result.get("operation_id")
            == pending["payload"]["operation_id"]
        ):
            path.unlink()
            if pending["intent"] == intent and pending.get("endpoint") == endpoint:
                result["recovered_pending"] = True
                return True, result
            return False, {
                "error": "Previous operation was confirmed. Review the current assignment, then retry the new change."
            }
        if receipt.status_code != 404:
            return False, {
                "error": "Unable to reconcile the previous operation. Check Web-Tools before continuing."
            }
        if pending.get("endpoint") not in ORDER_ENDPOINTS:
            return False, {
                "error": "An earlier operation from a retired workflow is "
                "unconfirmed. Resolve it in Web-Tools before assigning this device.",
                "operation_id": pending["payload"]["operation_id"],
            }
        changed_intent = pending["intent"] != intent
        recovered = True
    else:
        pending = {
            "intent": intent,
            "endpoint": endpoint,
            "payload": dict(payload, operation_id=str(uuid4())),
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(pending), encoding="utf-8")
        os.replace(str(temporary), str(path))

    for attempt in range(4):
        try:
            response = transport.post(
                base_url + pending["endpoint"],
                headers=headers,
                json=pending["payload"],
                timeout=30,
            )
        except requests.RequestException:
            response = None
            recovered = True
        if response is not None:
            body = _body(response)
            if response.status_code == 200 and body.get("success"):
                if (
                    body.get("operation_id")
                    != pending["payload"]["operation_id"]
                ):
                    return False, {
                        "error": "Server returned an unrecognised operation receipt"
                    }
                path.unlink()
                if changed_intent:
                    return False, {
                        "error": "Previous operation was confirmed. Review the current assignment, then retry the new change."
                    }
                if recovered:
                    body["recovered_pending"] = True
                return True, body
            if (
                response.status_code == 409
                and body.get("code") == "assignment_conflict"
            ):
                # A 409 confirms no transaction was committed. Revalidate the
                # operator's decision with a token of the current server state.
                path.unlink()
                if (
                    changed_intent
                    or prompt is None
                    or not prompt(body.get("conflicts", []))
                ):
                    return False, {"error": "Reassignment cancelled"}
                payload = dict(
                    payload, reassignment_token=body["reassignment_token"]
                )
                # Bound repeated conflicts when another operator keeps changing it.
                pending = {
                    "intent": intent,
                    "endpoint": endpoint,
                    "payload": dict(payload, operation_id=str(uuid4())),
                }
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(pending), encoding="utf-8")
                os.replace(str(temporary), str(path))
                continue
            if 400 <= response.status_code < 500:
                if (
                    response.status_code not in {401, 403}
                    and body.get("success") is False
                ):
                    path.unlink()
                return False, body
        if attempt < 3:
            time.sleep(2**attempt)

    operation_id = pending["payload"]["operation_id"]
    try:
        response = transport.get(
            base_url
            + "/api/stock_units/second-check-operations/"
            + operation_id,
            headers=headers,
            timeout=10,
        )
        body = _body(response)
        if (
            response.status_code == 200
            and body.get("success")
            and body.get("operation_id") == operation_id
        ):
            path.unlink()
            if changed_intent:
                return False, {
                    "error": "Previous operation was confirmed. Review the current assignment, then retry the new change."
                }
            body["recovered_pending"] = True
            return True, body
    except requests.RequestException:
        pass
    return False, {
        "error": "Assignment outcome is unconfirmed. Retry the same change to reconcile it safely.",
        "operation_id": operation_id,
    }
