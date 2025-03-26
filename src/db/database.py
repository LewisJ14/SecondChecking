# db/database.py
import mysql.connector
from tkinter import messagebox
from utils.helpers import log_event, load_config

config = load_config()

DB_HOST = config.get("database", "host")
DB_USER = config.get("database", "user")
DB_PASSWORD = config.get("database", "password")
DB_NAME = config.get("database", "database")

def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        return conn
    except mysql.connector.Error as err:
        log_event(f"MySQL error: {err}")
        messagebox.showerror("Database Error", f"Error connecting to MySQL:\n{err}")
        return None