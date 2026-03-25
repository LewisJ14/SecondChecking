import os

import MySQLdb
from tkinter import messagebox

REQUIRED_ORDER_SERIALS_COLUMNS = [
    "sku",
    "test_microphone",
    "mdm_state",
    "mdm_details",
    "assigned_by",
    "battery",
    "battery2",
    "laptop_status",
]

COLUMN_DEFINITIONS = {
    "sku": "VARCHAR(128) NULL",
    "battery": "VARCHAR(128) NULL",
    "battery2": "VARCHAR(128) NULL",
    "test_microphone": "VARCHAR(16) NULL",
    "mdm_state": "VARCHAR(32) NULL",
    "mdm_details": "TEXT NULL",
    "assigned_by": "VARCHAR(150) NULL",
    "laptop_status": "VARCHAR(50) NULL",
}

DEFAULT_DB_RETRIES = 2
DEFAULT_DB_DELAY = 1
DEFAULT_DB_TIMEOUT = 5


def build_retry_sleep_seconds(base_delay: int, attempt: int) -> int:
    return base_delay * attempt


def format_db_unavailable_message(err, retries: int, unexpected: bool = False) -> str:
    prefix = "Unexpected error connecting to MySQL" if unexpected else "Error connecting to MySQL"
    return (
        "The app started, but the database is unavailable.\n\n"
        f"{prefix} after {retries} attempts:\n{err}"
    )


def load_database_settings():
    from utils.helpers import log_event, load_config

    try:
        config = load_config()
        return {
            "host": os.getenv("DB_HOST", config.get("database", "host")),
            "user": os.getenv("DB_USER", config.get("database", "user")),
            "password": os.getenv("DB_PASSWORD", config.get("database", "password")),
            "database": os.getenv("DB_NAME", config.get("database", "database")),
        }
    except Exception:
        raise


def get_db_connection(retries=DEFAULT_DB_RETRIES, delay=DEFAULT_DB_DELAY, show_errors=True):
    from utils.helpers import log_event
    import traceback
    import time

    log_event("Attempting to establish database connection...")

    try:
        settings = load_database_settings()
    except Exception as config_err:
        log_event(f"Error loading DB config: {config_err}\n{traceback.format_exc()}")
        if show_errors:
            messagebox.showerror("Config Error", f"Error loading database configuration:\n{config_err}")
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
            )
            ensure_schema(conn, settings["database"], log_event)
            log_event("Database connection established successfully.")
            return conn
        except MySQLdb.MySQLError as err:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            log_event(f"MySQL error on attempt {attempt}: {err}\n{traceback.format_exc()}")
            if attempt == retries:
                log_event("Max retries reached. Database connection failed.")
                if show_errors:
                    messagebox.showerror("Database Error", format_db_unavailable_message(err, retries))
                return None
            time.sleep(build_retry_sleep_seconds(delay, attempt))
        except Exception as err:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            log_event(f"Unexpected error on attempt {attempt}: {err}\n{traceback.format_exc()}")
            if attempt == retries:
                if show_errors:
                    messagebox.showerror("Database Error", format_db_unavailable_message(err, retries, unexpected=True))
                return None
            time.sleep(build_retry_sleep_seconds(delay, attempt))


def ensure_schema(conn, database_name, log_event):
    required_tables = {"order", "order_serials", "user"}
    required_columns = REQUIRED_ORDER_SERIALS_COLUMNS

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name IN (%s, %s, %s)
                """,
                (database_name, "order", "order_serials", "user"),
            )
            existing = {
                row[0].decode("utf-8") if isinstance(row[0], (bytes, bytearray)) else row[0]
                for row in cursor.fetchall()
            }

        missing_tables = required_tables - existing
        if missing_tables:
            log_event("Missing tables detected: " + ", ".join(sorted(missing_tables)) + ". "
                      "Please create them manually before running the app.")

        placeholders = ", ".join(["%s"] * len(required_columns))
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s AND column_name IN ({placeholders})
                """,
                (database_name, "order_serials", *required_columns),
            )
            existing_columns = {
                (row[0].decode("utf-8") if isinstance(row[0], (bytes, bytearray)) else row[0])
                for row in cursor.fetchall()
            }

        missing_columns = set(required_columns) - existing_columns
        if missing_columns:
            log_event("Missing columns in order_serials detected: " + ", ".join(sorted(missing_columns)) + ". "
                      "Attempting to apply missing columns automatically.")
            unknown_columns = sorted(c for c in missing_columns if c not in COLUMN_DEFINITIONS)
            if unknown_columns:
                log_event("No column definition available for: " + ", ".join(unknown_columns) + ". "
                          "Skipping those columns.")
            columns_to_create = sorted(c for c in missing_columns if c in COLUMN_DEFINITIONS)
            with conn.cursor() as cursor:
                for column in columns_to_create:
                    definition = COLUMN_DEFINITIONS[column]
                    sql = f"ALTER TABLE `order_serials` ADD COLUMN `{column}` {definition}"
                    try:
                        cursor.execute(sql)
                        log_event(f"Added missing column `{column}` to order_serials.")
                    except MySQLdb.OperationalError as err:
                        error_code = err.args[0] if err.args else None
                        if error_code == 1060:
                            log_event(f"Column `{column}` already exists; ignoring duplicate column error.")
                        else:
                            raise
                conn.commit()
    except Exception as err:
        log_event(f"Schema verification failed: {err}")
