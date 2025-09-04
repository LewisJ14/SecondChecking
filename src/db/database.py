import MySQLdb
from tkinter import messagebox

def get_db_connection(retries=3, delay=5):
    from utils.helpers import log_event, load_config
    import traceback
    import time

    log_event("Attempting to establish database connection...")

    try:
        config = load_config()
        DB_HOST = config.get("database", "host")
        DB_USER = config.get("database", "user")
        DB_PASSWORD = config.get("database", "password")
        DB_NAME = config.get("database", "database")
    except Exception as config_err:
        log_event(f"Error loading DB config: {config_err}\n{traceback.format_exc()}")
        messagebox.showerror("Config Error", f"Error loading database configuration:\n{config_err}")
        return None

    for attempt in range(1, retries + 1):
        try:
            log_event(f"Database connection attempt {attempt}/{retries}.")
            conn = MySQLdb.connect(
                host=DB_HOST,
                user=DB_USER,
                passwd=DB_PASSWORD,
                db=DB_NAME,
                charset='utf8mb4'
            )
            log_event("Database connection established successfully.")
            return conn
        except MySQLdb.MySQLError as err:
            log_event(f"MySQL error on attempt {attempt}: {err}\n{traceback.format_exc()}")
            if attempt == retries:
                log_event("Max retries reached. Database connection failed.")
                messagebox.showerror("Database Error", f"Error connecting to MySQL after {retries} attempts:\n{err}")
                return None
            time.sleep(delay * attempt)  # Exponential backoff
        except Exception as err:
            log_event(f"Unexpected error on attempt {attempt}: {err}\n{traceback.format_exc()}")
            if attempt == retries:
                messagebox.showerror("Database Error", f"Unexpected error connecting to MySQL after {retries} attempts:\n{err}")
                return None
            time.sleep(delay)
