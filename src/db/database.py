import os
from pathlib import Path
import MySQLdb
from tkinter import messagebox

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
    import traceback

    required_tables = {"order", "order_serials"}
    script_path = Path(__file__).resolve().parents[2] / "sql" / "001_create_order.sql"

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name IN (%s, %s)
                """,
                (database_name, "order", "order_serials"),
            )
            existing = {
                row[0].decode("utf-8") if isinstance(row[0], (bytes, bytearray)) else row[0]
                for row in cursor.fetchall()
            }

        missing = required_tables - existing
        if missing:
            script = script_path.read_text(encoding="utf-8")
            statements = [stmt.strip() for stmt in script.split(";") if stmt.strip()]

            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)

            conn.commit()
            log_event(
                "Provisioned missing tables: " + ", ".join(sorted(missing))
            )

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s AND column_name IN (%s, %s)
                """,
                (database_name, "order_serials", "sku", "test_microphone"),
            )
            existing_columns = {
                (row[0].decode("utf-8") if isinstance(row[0], (bytes, bytearray)) else row[0])
                for row in cursor.fetchall()
            }

        if "sku" not in existing_columns:
            with conn.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE order_serials ADD COLUMN sku VARCHAR(128) NULL AFTER serial_number"
                )
            conn.commit()
            log_event("Added missing 'sku' column to order_serials table.")

        if "test_microphone" not in existing_columns:
            with conn.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE order_serials ADD COLUMN test_microphone VARCHAR(16) NULL AFTER test_speaker"
                )
            conn.commit()
            log_event("Added missing 'test_microphone' column to order_serials table.")
    except FileNotFoundError as file_err:
        log_event(f"Schema file missing at {script_path}: {file_err}")
        raise
    except Exception as err:
        log_event(
            f"Schema provisioning failed: {err}\n{traceback.format_exc()}"
        )
        raise
