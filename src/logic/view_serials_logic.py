# view_serials_logic.py
import tkinter as tk
from tkinter import messagebox, ttk
from db.database import get_db_connection
from utils.helpers import log_event
import traceback
import threading

SERIALS_PER_PAGE = 20

def open_serial_viewer(order_number):
    # Open a window to view and manage serial numbers assigned to an order
    try:
        view_window = tk.Toplevel()
        view_window.title("Assigned Serial Numbers")
        view_window.geometry("350x450")

        treeview = ttk.Treeview(view_window, columns=("Serial Number", "Assigned At"), show="headings")
        treeview.heading("Serial Number", text="Serial Number")
        treeview.heading("Assigned At", text="Assigned At")
        treeview.column("Serial Number", anchor="center", width=150, stretch=True)
        treeview.column("Assigned At", anchor="center", width=150, stretch=True)
        treeview.pack(pady=10, expand=True, fill=tk.BOTH)

        # Pagination state
        page = [0]
        all_rows = []

        def next_page():
            # Navigate to the next page of serial numbers
            if (page[0]+1)*SERIALS_PER_PAGE < len(all_rows):
                page[0] += 1
                show_page()

        def prev_page():
            # Navigate to the previous page of serial numbers
            if page[0] > 0:
                page[0] -= 1
                show_page()

        # Pagination controls (define after prev_page/next_page)
        nav_frame = tk.Frame(view_window)
        nav_frame.pack(pady=5)
        tk.Button(nav_frame, text="Previous", command=prev_page, width=8).pack(side="left", padx=2)
        page_label = tk.Label(nav_frame, text="")
        page_label.pack(side="left", padx=2)
        tk.Button(nav_frame, text="Next", command=next_page, width=8).pack(side="left", padx=2)

        def load_rows():
            def fetch_data():
                conn = None
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT serial_number, assigned_at FROM order_serials WHERE order_number = %s", (order_number,))
                    rows = cursor.fetchall()
                    view_window.after(0, lambda: update_rows(list(rows)))
                except Exception as err:
                    log_event(f"Error loading serials: {err}\n{traceback.format_exc()}")
                    msg = f"Failed to load serials:\n{err}"
                    view_window.after(0, lambda: messagebox.showerror("Error", msg))
                finally:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass

            threading.Thread(target=fetch_data, daemon=True).start()

        def update_rows(rows):
            nonlocal all_rows
            all_rows = rows
            show_page()

        def show_page():
            # Display the current page of serial numbers in the treeview
            treeview.delete(*treeview.get_children())
            start = page[0] * SERIALS_PER_PAGE
            end = start + SERIALS_PER_PAGE
            for serial, assigned_at in all_rows[start:end]:
                try:
                    if hasattr(assigned_at, "strftime"):
                        display_time = assigned_at.strftime("%d/%m/%Y %H:%M")
                    else:
                        display_time = str(assigned_at) if assigned_at else "Unknown"
                except Exception as e:
                    log_event(f"Error formatting assigned_at: {assigned_at} ({e})")
                    display_time = "Unknown"
                treeview.insert("", "end", values=(serial, display_time))
            page_label.config(text=f"Page {page[0]+1} of {max(1, (len(all_rows)-1)//SERIALS_PER_PAGE+1)}")

        load_rows()

        def remove_selected():
            # Remove the selected serial number from the database and refresh the view
            selected = treeview.selection()
            if not selected:
                messagebox.showwarning("No Selection", "Please select a serial to remove.")
                view_window.attributes("-topmost", 1)
                view_window.after(100, lambda: view_window.attributes("-topmost", 0))
                return

            try:
                serial = treeview.item(selected[0])["values"][0]
                if not serial:
                    raise ValueError("Invalid serial selected.")
                confirm = messagebox.askyesno("Confirm", f"Remove serial '{serial}' from order?")
                view_window.attributes("-topmost", 1)
                view_window.after(100, lambda: view_window.attributes("-topmost", 0))
                if not confirm:
                    return

                conn = None
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM order_serials WHERE order_number = %s AND serial_number = %s", (order_number, serial))
                    conn.commit()
                    # Remove from all_rows and refresh page
                    all_rows[:] = [row for row in all_rows if row[0] != serial]
                    show_page()
                    log_event(f"Removed serial '{serial}' from order '{order_number}'")
                except Exception as err:
                    log_event(f"Error removing serial: {err}\n{traceback.format_exc()}")
                    messagebox.showerror("Error", "Failed to remove serial")
                    view_window.attributes("-topmost", 1)
                    view_window.after(100, lambda: view_window.attributes("-topmost", 0))
                finally:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass
            except Exception as err:
                log_event(f"Error removing serial: {err}\n{traceback.format_exc()}")
                messagebox.showerror("Error", "Failed to remove serial")

        def view_spec():
            # View detailed specifications for the selected serial number
            selected = treeview.selection()
            if not selected:
                messagebox.showwarning("No Selection", "Please select a serial to view.")
                view_window.attributes("-topmost", 1)
                view_window.after(100, lambda: view_window.attributes("-topmost", 0))
                return

            serial = treeview.item(selected[0])["values"][0]
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT cpu, ram, ssd, model, resolution, windows, battery
                    FROM order_serials WHERE order_number = %s AND serial_number = %s
                """, (order_number, serial))
                row = cursor.fetchone()

                if row:
                    info = (
                        f"CPU: {row[0]}\nRAM: {row[1]}\nSSD: {row[2]}\nModel: {row[3]}\n"
                        f"Resolution: {row[4]}\nWindows: {row[5]}\nBattery: {row[6]}"
                    )
                    messagebox.showinfo(f"Specs for {serial}", info)
                else:
                    messagebox.showinfo("No Data", f"No specs found for serial {serial}.")
                view_window.attributes("-topmost", 1)
                view_window.after(100, lambda: view_window.attributes("-topmost", 0))
            except Exception as err:
                log_event(f"Error viewing serial spec: {err}\n{traceback.format_exc()}")
                messagebox.showerror("Error", "Failed to retrieve specs")
                view_window.attributes("-topmost", 1)
                view_window.after(100, lambda: view_window.attributes("-topmost", 0))
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        btn_frame = tk.Frame(view_window)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Remove", command=remove_selected, width=10, bg="tomato").pack(side="left", padx=5)
        tk.Button(btn_frame, text="View Spec", command=view_spec, width=10, bg="lightblue").pack(side="left", padx=5)

        return view_window

    except Exception as e:
        log_event(f"Error opening serial viewer: {e}\n{traceback.format_exc()}")
        messagebox.showerror("Error", "Failed to open serial viewer")
