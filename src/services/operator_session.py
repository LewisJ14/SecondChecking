"""Memory-only operator token, scoped to one configured service."""
import threading
import time

_lock = threading.RLock()
_state = {}
_generation = 0


class SignInRequired(RuntimeError):
    """A read cannot proceed under the current operator session."""

    def __init__(self):
        super().__init__(
            "Sign in again to load saved reports. Close the report and serial "
            "list, then use Operator > Lock / change operator. "
            "Your local check drafts are preserved.")


def install(base_url, response):
    global _generation
    user = response.get("user")
    token = response.get("session_token")
    seconds = response.get("expires_in")
    if (not isinstance(user, dict) or not isinstance(user.get("id"), int)
            or not user.get("username") or user.get("role") not in {"user", "admin"}
            or not isinstance(token, str) or not token
            or not isinstance(seconds, (int, float)) or not 0 < seconds <= 3600):
        raise ValueError("Invalid operator session response.")
    with _lock:
        from services.runtime import register_private_values
        register_private_values([token, user.get('username'), user.get('email')])
        _generation += 1
        _state.clear()
        _state.update(base_url=base_url.rstrip("/"), token=token, user=dict(user),
                      expires=time.monotonic() + seconds,
                      reset_only=bool(response.get("reset_required")))


def clear():
    global _generation
    with _lock:
        _generation += 1
        previous = dict(_state)
        _state.clear()
        return previous


def clear_if_current(expected_generation):
    """An old request must never invalidate a newly installed operator."""
    with _lock:
        if _generation != expected_generation:
            return False
        clear()
        return True


def snapshot():
    with _lock:
        return dict(_state)


def generation():
    with _lock:
        return _generation


def allowed(action):
    with _lock:
        return bool(_state and not _state.get("reset_only")
                    and time.monotonic() < _state["expires"]
                    and action in _state["user"].get("permissions", []))


def headers(base_url):
    with _lock:
        if (not _state or _state["base_url"] != base_url.rstrip("/")
                or time.monotonic() >= _state["expires"]):
            return {}
        return {"X-Second-Check-Session": _state["token"]}
