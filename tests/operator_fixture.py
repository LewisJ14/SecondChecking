"""Explicit signed-in stand-in for pre-existing UI/layout boundary tests."""
from services import operator_session


def sign_in():
    operator_session.install("https://isolated", {
        "session_token": "mock-operator-token", "expires_in": 3600,
        "reset_required": False,
        "user": {"id": 1, "username": "tester", "role": "user",
                 "permissions": ["test", "assign", "override", "remove",
                                 "maintenance", "read", "notes"]}})


def sign_out():
    operator_session.clear()
