# main_logic.py
import threading
import tkinter as tk
from tkinter import messagebox
from db.database import get_db_connection
from utils.helpers import log_event, parse_percent, extract_details_from_sku, get_live_battery_percent
from utils.specs import get_laptop_specs
from ui.tests import TestsWindow

# Utility function

def search_order_logic(order_id, canvas, search_button, test_results, test_labels, root):
    def run_search():
        try:
            conn = get_db_connection()
            if not conn:
                return

            cursor = conn.cursor()
            cursor.execute("SELECT sku FROM orders WHERE order_number = %s", (order_id,))
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                root.after(0, lambda: messagebox.showwarning("No Results", f"No SKUs found for Order Number: {order_id}"))
                return

            sku = rows[0][0]
            details = extract_details_from_sku(sku)
            laptop_specs = get_laptop_specs()
            serial_number = laptop_specs.get("Serial Number", "Unknown")

            canvas.delete("all")
            canvas_width = canvas.winfo_width() or 800
            center_x = canvas_width // 2

            def update_ui():
                canvas.create_text(center_x, 20, text=f"🔍 SKU: {sku}", font=("Arial", 14, "bold"), anchor="center")
                canvas.create_text(center_x, 40, text=f"Serial: {serial_number}", font=("Arial", 10, "bold"), anchor="center")

                canvas.create_text(canvas.winfo_width() * 0.3, 70, text="SKU Spec", font=("Arial", 12, "bold"), anchor="center")
                canvas.create_text(canvas.winfo_width() * 0.7, 70, text="Laptop Spec", font=("Arial", 12, "bold"), anchor="center")

                start_y = 100
                line_spacing = 25
                mismatches = []
                fields = ["Model", "CPU", "SSD", "RAM", "Resolution", "Windows", "Battery"]

                for i, field in enumerate(fields):
                    y = start_y + i * line_spacing
                    sku_value = details.get(field, "Unknown")
                    laptop_value = laptop_specs.get(field, "Unknown")
                    match = True

                    if field == "Battery":
                        sku_pct = parse_percent(sku_value)
                        laptop_pct = parse_percent(laptop_value)
                        if sku_pct is not None and laptop_pct is not None and laptop_pct < sku_pct:
                            mismatches.append(f"⚠ {field}: Expected ≥{sku_pct}%, Found {laptop_pct}%")
                            match = False
                    elif sku_value != "Unknown" and laptop_value != "Unknown" and sku_value != laptop_value:
                        mismatches.append(f"⚠ {field}: Expected {sku_value}, Found {laptop_value}")
                        match = False

                    symbol = "✅" if match else "❌"
                    canvas.create_text(canvas.winfo_width() * 0.3, y, text=sku_value, font=("Arial", 10), anchor="center")
                    canvas.create_text(canvas.winfo_width() * 0.7, y, text=laptop_value, font=("Arial", 10), anchor="center")
                    canvas.create_text(canvas.winfo_width() - 20, y, text=symbol, font=("Arial", 10), anchor="e")
                    canvas.create_line(50, y + 10, canvas.winfo_width() - 50, y + 10, fill="lightgray")

                mismatch_text = "\n".join(mismatches) if mismatches else "✅ All specs match"
                mismatch_color = "red" if mismatches else "green"
                canvas.create_text(center_x, start_y + len(fields) * line_spacing + 35, text=mismatch_text, fill=mismatch_color, font=("Arial", 10, "bold"), anchor="center")

                # Battery bar
                def draw_battery_bar():
                    canvas.delete("battery_bar")
                    bar_x, bar_y = 10, canvas.winfo_height() - 30
                    bar_width, bar_height = 200, 20
                    percent = get_live_battery_percent() or 0
                    fill_width = int(bar_width * percent / 100)

                    if percent >= 70:
                        bar_color = "green"
                    elif percent >= 45:
                        bar_color = "orange"
                    else:
                        bar_color = "red"

                    canvas.create_rectangle(bar_x, bar_y, bar_x + bar_width, bar_y + bar_height, fill="lightgray", outline="black", tags="battery_bar")
                    canvas.create_rectangle(bar_x, bar_y, bar_x + fill_width, bar_y + bar_height, fill=bar_color, outline="", tags="battery_bar")
                    label = f"Battery: {percent}%"
                    canvas.create_text(bar_x + bar_width // 2, bar_y + bar_height // 2, text=label, fill="black", font=("Arial", 10, "bold"), tags="battery_bar")

                draw_battery_bar()

            root.after(0, update_ui)

        except Exception as e:
            log_event(f"Unhandled exception in search logic for order {order_id}: {e}")
            def show_error():
                messagebox.showerror("Unexpected Error", str(e))
                search_button.config(state="normal")
            root.after(0, show_error)

    threading.Thread(target=run_search, daemon=True).start()


def assign_serial_logic(order_number, serial_number, specs, test_results, root):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT order_number FROM order_serials WHERE serial_number = %s", (serial_number,))
        existing = cursor.fetchall()

        if existing:
            old_orders = ", ".join(order[0] for order in existing)
            confirm = messagebox.askyesno("Reassign Serial", f"Serial '{serial_number}' is already assigned to {old_orders}\nDo you want to reassign it to order '{order_number}'?")
            if not confirm:
                conn.close()
                return
            cursor.execute("DELETE FROM order_serials WHERE serial_number = %s", (serial_number,))

        cursor.execute("""
            INSERT INTO order_serials (
                order_number, serial_number, cpu, ram, ssd, model, resolution, windows, battery,
                test_keyboard, test_speaker, test_display, test_webcam, test_usb
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                cpu = VALUES(cpu),
                ram = VALUES(ram),
                ssd = VALUES(ssd),
                model = VALUES(model),
                resolution = VALUES(resolution),
                windows = VALUES(windows),
                battery = VALUES(battery),
                test_keyboard = VALUES(test_keyboard),
                test_speaker = VALUES(test_speaker),
                test_display = VALUES(test_display),
                test_webcam = VALUES(test_webcam),
                test_usb = VALUES(test_usb),
                assigned_at = CURRENT_TIMESTAMP
        """, (
            order_number,
            serial_number,
            specs["CPU"],
            specs["RAM"],
            specs["SSD"],
            specs["Model"],
            specs["Resolution"],
            specs["Windows"],
            specs["Battery"],
            test_results.get("keyboard"),
            test_results.get("speaker"),
            test_results.get("display"),
            test_results.get("webcam"),
            test_results.get("usb"),
        ))

        conn.commit()
        conn.close()
        log_event(f"Serial '{serial_number}' assigned to Order '{order_number}' with specs.")
        root.after(0, lambda: messagebox.showinfo("Serial Assigned", f"Serial '{serial_number}' has been added to order '{order_number}'."))

    except Exception as err:
        log_event(f"MySQL error on assigning serial: {err}")
        root.after(0, lambda: messagebox.showerror("Database Error", f"Error assigning serial number:\n{err}"))
