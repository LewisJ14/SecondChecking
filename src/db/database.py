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
    script_path = (
        Path(__file__).resolve().parent.parent / "sql" / "001_create_order.sql"
    )

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
        if not missing:
            return

        script = script_path.read_text(encoding="utf-8")
        statements = [stmt.strip() for stmt in script.split(";") if stmt.strip()]

        with conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

        conn.commit()
        log_event(
            "Provisioned missing tables: " + ", ".join(sorted(missing))
        )
    except FileNotFoundError as file_err:
        log_event(f"Schema file missing at {script_path}: {file_err}")
        raise
    except Exception as err:
        log_event(
            f"Schema provisioning failed: {err}\n{traceback.format_exc()}"
        )
        raise
