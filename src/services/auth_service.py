from typing import Iterable, List, Optional, Tuple

from werkzeug.security import generate_password_hash

from db.database import get_db_connection
from utils.helpers import log_event


def normalize_usernames(rows: Iterable[Tuple]) -> List[str]:
    usernames: List[str] = []
    for row in rows:
        if not row or row[0] is None:
            continue
        username = str(row[0]).strip()
        if not username:
            continue
        usernames.append(username)
    return usernames


def fetch_usernames() -> Tuple[List[str], Optional[str]]:
    conn = get_db_connection(show_errors=False)
    if not conn:
        log_event("Unable to load username list; database connection failed.")
        return [], "Database unavailable. Check the connection and try again."

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM user ORDER BY username ASC")
        return normalize_usernames(cursor.fetchall()), None
    except Exception as exc:
        log_event(f"Unable to load username list: {exc}")
        return [], f"Unable to load users: {exc}"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def fetch_user_record(username: str):
    conn = get_db_connection(show_errors=False)
    if not conn:
        log_event(f"Database connection failed when looking up user '{username}'.")
        return None, "Database unavailable. Check the connection and try again."

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
                SELECT id, email, role, username, password_hash, must_reset_password
                FROM user
                WHERE username = %s
            """,
            (username,),
        )
        row = cursor.fetchone()
        if row:
            log_event(f"Fetched user row for '{username}'.")
        else:
            log_event(f"No user found for '{username}'.")
        return row, None
    except Exception as exc:
        log_event(f"Login query failed for '{username}': {exc}")
        return None, f"Unable to verify credentials: {exc}"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def update_password(user_id: int, raw_password: str) -> None:
    conn = get_db_connection()
    if not conn:
        raise RuntimeError("Unable to connect to the database to update password.")

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
                UPDATE user
                SET password_hash = %s, must_reset_password = FALSE
                WHERE id = %s
            """,
            (generate_password_hash(raw_password), user_id),
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
