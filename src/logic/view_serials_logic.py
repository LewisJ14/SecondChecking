# view_serials_logic.py
import tkinter as tk
from tkinter import messagebox, ttk
from db.database import get_db_connection
from utils.helpers import log_event

def open_serial_viewer(order_number):
    try:
        view_window = tk.Toplevel()
        view_window.title("Assigned Serial Numbers")
        view_window.geometry("300x400")

        treeview = ttk.Treeview(view_window, columns=("Serial Number", "Assigned At"), show="headings")
        treeview.heading("Serial Number", text="Serial Number")
        treeview.heading("Assigned At", text="Assigned At")
        treeview.pack(pady=10, expand=True, fill=tk.BOTH)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT serial_number, assigned_at FROM order_serials WHERE order_number = %s", (order_number,))
        rows = cursor.fetchall()
        conn.close()

        for serial, assigned_at in rows:
            display_time = assigned_at.strftime("%d/%m/%Y %H:%M") if assigned_at else "Unknown"
            treeview.insert("", "end", values=(serial, display_time))

        def remove_selected():
            selected = treeview.selection()
            if not selected:
                messagebox.showwarning("No Selection", "Please select a serial to remove.")
                return

            serial = treeview.item(selected[0])["values"][0]
            confirm = messagebox.askyesno("Confirm", f"Remove serial '{serial}' from order?")
            if not confirm:
                return

            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM order_serials WHERE order_number = %s AND serial_number = %s", (order_number, serial))
                conn.commit()
                conn.close()
                treeview.delete(selected[0])
                log_event(f"Removed serial '{serial}' from order '{order_number}'")
            except Exception as err:
                log_event(f"Error removing serial: {err}")
                messagebox.showerror("Error", "Failed to remove serial")

        def view_spec():
            selected = treeview.selection()
            if not selected:
                messagebox.showwarning("No Selection", "Please select a serial to view.")
                return

            serial = treeview.item(selected[0])["values"][0]
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT cpu, ram, ssd, model, resolution, windows, battery
                    FROM order_serials WHERE order_number = %s AND serial_number = %s
                """, (order_number, serial))
                row = cursor.fetchone()
                conn.close()

                if row:
                    info = (
                        f"CPU: {row[0]}\nRAM: {row[1]}\nSSD: {row[2]}\nModel: {row[3]}\n"
                        f"Resolution: {row[4]}\nWindows: {row[5]}\nBattery: {row[6]}"
                    )
                    messagebox.showinfo(f"Specs for {serial}", info)
                else:
                    messagebox.showinfo("No Data", f"No specs found for serial {serial}.")

            except Exception as err:
                log_event(f"Error viewing serial spec: {err}")
                messagebox.showerror("Error", "Failed to retrieve specs")

        btn_frame = tk.Frame(view_window)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Remove", command=remove_selected).pack(side="left", padx=5)
        tk.Button(btn_frame, text="View Spec", command=view_spec).pack(side="left", padx=5)

        return view_window

    except Exception as e:
        log_event(f"Error opening serial viewer: {e}")
        messagebox.showerror("Error", "Failed to open serial viewer")