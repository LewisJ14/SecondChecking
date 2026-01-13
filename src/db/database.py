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
]

COLUMN_DEFINITIONS = {
    "sku": "VARCHAR(128) NULL",
    "battery": "VARCHAR(128) NULL",
    "battery2": "VARCHAR(128) NULL",
    "test_microphone": "VARCHAR(16) NULL",
    "mdm_state": "VARCHAR(32) NULL",
    "mdm_details": "TEXT NULL",
    "assigned_by": "VARCHAR(150) NULL",
}

def get_db_connection(retries=3, delay=5):
    from utils.helpers import log_event, load_config
    import traceback
    import time

    log_event("Attempting to establish database connection...")

    try:
        config = load_config()
        DB_HOST = os.getenv("DB_HOST", config.get("database", "host"))
        DB_USER = os.getenv("DB_USER", config.get("database", "user"))
        DB_PASSWORD = os.getenv("DB_PASSWORD", config.get("database", "password"))
        DB_NAME = os.getenv("DB_NAME", config.get("database", "database"))
    except Exception as config_err:
        log_event(f"Error loading DB config: {config_err}\n{traceback.format_exc()}")
        messagebox.showerror("Config Error", f"Error loading database configuration:\n{config_err}")
        return None

    for attempt in range(1, retries + 1):
        conn = None
        try:
            log_event(f"Database connection attempt {attempt}/{retries}.")
            conn = MySQLdb.connect(
                host=DB_HOST,
                user=DB_USER,
                passwd=DB_PASSWORD,
                db=DB_NAME,
                charset="utf8mb4",
            )
            ensure_schema(conn, DB_NAME, log_event)
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
                messagebox.showerror("Database Error", f"Error connecting to MySQL after {retries} attempts:\n{err}")
                return None
            time.sleep(delay * attempt)  # Exponential backoff
        except Exception as err:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            log_event(f"Unexpected error on attempt {attempt}: {err}\n{traceback.format_exc()}")
            if attempt == retries:
                messagebox.showerror("Database Error", f"Unexpected error connecting to MySQL after {retries} attempts:\n{err}")
                return None
            time.sleep(delay)


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
