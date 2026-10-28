import MySQLdb
from db.schema import SchemaCompatibilityError, validate_schema
from services.configuration import database_settings, database_tls_options, read_config
from services.runtime import log_event

DEFAULT_DB_RETRIES = 2
DEFAULT_DB_DELAY = 1
DEFAULT_DB_TIMEOUT = 5


def build_retry_sleep_seconds(base_delay: int, attempt: int) -> int:
    return base_delay * attempt


def format_db_unavailable_message(err, retries: int, unexpected: bool = False) -> str:
    prefix = "Unexpected error connecting to MySQL" if unexpected else "Error connecting to MySQL"
    return (
        "The app started, but the database is unavailable.\n\n"
        f"{prefix} after {retries} attempts.\n"
        "Check database settings, network access and server availability, then retry."
    )


def load_database_settings():
    return database_settings(read_config())


def _show_error(title, text):
    # Legacy interactive callers opt into dialogs; headless callers do not
    # import Tk. Keep this adapter outside connection/configuration logic.
    from tkinter import messagebox
    messagebox.showerror(title, text)


def check_database_connection(check_schema=False):
    """Read-only first-run probe. Does not invoke runtime schema repair."""
    settings = load_database_settings()
    conn = None
    try:
        conn = MySQLdb.connect(
            host=settings["host"], user=settings["user"],
            passwd=settings["password"], db=settings["database"],
            charset="utf8mb4", connect_timeout=DEFAULT_DB_TIMEOUT,
            read_timeout=DEFAULT_DB_TIMEOUT, write_timeout=DEFAULT_DB_TIMEOUT,
            **database_tls_options(settings["host"]))
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone()[0] != 1:
                raise RuntimeError("Unexpected probe response")
        if check_schema:
            validate_schema(conn, settings["database"])
    except SchemaCompatibilityError:
        raise
    except Exception:
        raise RuntimeError(
            "Database check failed. Check settings, network access and server permissions.") from None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def get_db_connection(retries=DEFAULT_DB_RETRIES, delay=DEFAULT_DB_DELAY, show_errors=True):
    import time

    log_event("Attempting to establish database connection...")

    try:
        settings = load_database_settings()
    except Exception:
        log_event("Database configuration invalid; check required DB fields and INI syntax.")
        if show_errors:
            _show_error("Config Error", "Check DB_HOST, DB_USER, DB_PASSWORD, DB_NAME and config.ini syntax.")
        return None

    for attempt in range(1, retries + 1):
        conn = None
        try:
            log_event(f"Database connection attempt {attempt}/{retries}.")
            conn = MySQLdb.connect(
                host=settings["host"],
                user=settings["user"],
                passwd=settings["password"],
                db=settings["database"],
                charset="utf8mb4",
                connect_timeout=DEFAULT_DB_TIMEOUT,
                read_timeout=DEFAULT_DB_TIMEOUT,
                write_timeout=DEFAULT_DB_TIMEOUT,
                **database_tls_options(settings["host"]),
            )
            validate_schema(conn, settings["database"])
            log_event("Database connection established successfully.")
            return conn
        except SchemaCompatibilityError as err:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            log_event(str(err))
            if show_errors:
                _show_error("Database upgrade required", str(err))
                return None
            raise
        except MySQLdb.MySQLError as err:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            log_event(f"MySQL connection failed on attempt {attempt}; check settings and server availability.")
            if attempt == retries:
                log_event("Max retries reached. Database connection failed.")
                if show_errors:
                    _show_error("Database Error", format_db_unavailable_message(err, retries))
                return None
            time.sleep(build_retry_sleep_seconds(delay, attempt))
        except Exception as err:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            log_event(f"Database connection failed on attempt {attempt}; check settings and server availability.")
            if attempt == retries:
                if show_errors:
                    _show_error("Database Error", format_db_unavailable_message(err, retries, unexpected=True))
                return None
            time.sleep(build_retry_sleep_seconds(delay, attempt))


def ensure_schema(conn, database_name, log_event=None):
    """Compatibility alias: validation only; schema changes are server migrations."""
    validate_schema(conn, database_name)
