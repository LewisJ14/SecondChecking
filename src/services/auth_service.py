"""Server authentication: password hashes and password writes stay off the desktop."""
import requests
from services import transport
from services import operator_session
from services.configuration import service_settings


def normalize_usernames(rows):
    return [str(row[0]).strip() for row in rows
            if row and row[0] is not None and str(row[0]).strip()]


def api_request(method, endpoint, payload=None, session=True):
    base, key = service_settings()
    if not base or not key:
        raise RuntimeError(
            "Configure SECOND_CHECK_BASE_URL and SECOND_CHECK_KEY, then Retry.")
    generation = operator_session.generation()
    headers = {"X-Second-Check-Key": key}
    if session:
        headers.update(operator_session.headers(base))
    try:
        response = transport.request(method, base + "/api/second-check" + endpoint,
                                    headers=headers, json=payload, timeout=15)
        body = response.json()
    except (requests.RequestException, ValueError):
        raise RuntimeError(
            "Authentication service unavailable. "
            "Check the connection and retry.") from None
    if (response.status_code != 200 or not isinstance(body, dict)
            or body.get("success") is not True):
        if (response.status_code == 401 and session
                and generation == operator_session.generation()):
            operator_session.clear()
        if response.status_code == 429:
            raise RuntimeError("Too many sign-in attempts. Wait before retrying.")
        raise RuntimeError(
            "Sign-in or permission check failed. "
            "Check credentials, reset status and service version.")
    return base, body


def fetch_usernames():
    try:
        _, body = api_request("GET", "/users", session=False)
        names = body.get("usernames")
        if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
            raise RuntimeError("Invalid user-list response.")
        return names, None
    except RuntimeError as exc:
        return [], str(exc)


def authenticate(username, password):
    operator_session.clear()
    try:
        base, body = api_request("POST", "/login", {
            "username": username, "password": password}, session=False)
        operator_session.install(base, body)
        return body, None
    except (RuntimeError, ValueError) as exc:
        return None, str(exc)


def update_password(user_id, raw_password):
    state = operator_session.snapshot()
    if state.get("user", {}).get("id") != user_id:
        raise RuntimeError("Sign in again before changing your password.")
    api_request("POST", "/password", {"password": raw_password})
    operator_session.clear()


def authorize(action):
    if not operator_session.allowed(action):
        raise RuntimeError(
            "Session expired or locked. Use Operator > Lock / change operator "
            "to sign in again.")
    api_request("POST", "/authorize", {"action": action})


def logout():
    revoke(operator_session.clear())


def revoke(previous):
    if not previous:
        return
    try:
        base, key = service_settings()
    except RuntimeError:
        return
    if base != previous["base_url"]:
        return
    try:
        transport.post(base + "/api/second-check/logout", headers={
            "X-Second-Check-Key": key,
            "X-Second-Check-Session": previous["token"]}, timeout=10)
    except requests.RequestException:
        pass
