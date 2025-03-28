# main_logic.py
import threading
import tkinter as tk
import wmi
from tkinter import messagebox
from db.database import get_db_connection
from utils.helpers import log_event, parse_percent, extract_details_from_sku, get_live_battery_percent
from utils.specs import get_laptop_specs
from logic.view_serials_logic import open_serial_viewer
from ui.tests import TestsWindow

# Store the initial battery level
initial_battery_level = get_live_battery_percent()

# Utility function

def search_order_logic(order_id, canvas, search_button, test_results, test_labels, root):

    def battery_charging_status():
        try:
            c = wmi.WMI()
            battery = c.Win32_Battery()[0]
            return battery.BatteryStatus == 2  # 2 = Charging
        except:
            return None

    def parse_percent(text):
        import re
        try:
            return int(re.search(r"\d+", text).group())
        except:
            return None

    def run_search():
        try:
            from db.database import get_db_connection
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

            def update_ui():
                canvas.delete("all")
                canvas_width = canvas.winfo_width() or 800
                center_x = canvas_width // 2

                canvas.create_text(center_x, 20, text=f"🔍 SKU: {sku}", font=("Arial", 14, "bold"), anchor="center")
                canvas.create_text(center_x, 40, text=f"Serial: {serial_number}", font=("Arial", 10, "bold"), anchor="center")

                # Assign Button
                assign_button = tk.Button(
                    canvas, text="Assign Serial", bg="lightgreen", font=("Arial", 9, "bold"),
                    command=lambda: assign_serial_logic(order_id, serial_number, laptop_specs, test_results, root)
                )
                canvas.create_window(center_x + 90, 40, window=assign_button, anchor="w")

                # View Serials Button
                view_serials_button = tk.Button(
                    canvas, text="View Serials", bg="lightblue", font=("Arial", 9, "bold"),
                    command=lambda: open_serial_viewer(order_id)
                )
                canvas.create_window(center_x + 200, 40, window=view_serials_button, anchor="w")

                # Spec comparison
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

                if mismatches:
                    log_event("Spec mismatches detected:\n" + mismatch_text)

                # Animated battery bar with pulse and reset logic
                pulse_index = [0]
                pulse_ticks = 4

                def draw_battery_bar():
                    bar_x, bar_y = 10, canvas.winfo_height() - 30
                    bar_width, bar_height = 200, 20

                    live_percent = get_live_battery_percent()
                    charging = battery_charging_status()

                    percent = live_percent if live_percent is not None else 0

                    if pulse_index[0] >= pulse_ticks:
                        pulse_index[0] = 0

                    offset = pulse_index[0] if charging else -pulse_index[0]
                    animated_percent = max(0, min(100, percent + offset))
                    fill_width = int(bar_width * animated_percent / 100)

                    if live_percent is None:
                        bar_color = "gray"
                    elif percent >= 70:
                        bar_color = "green"
                    elif percent >= 45:
                        bar_color = "orange"
                    else:
                        bar_color = "red"

                    canvas.delete("battery_bar")
                    canvas.create_rectangle(bar_x, bar_y, bar_x + bar_width, bar_y + bar_height,
                                            fill="lightgray", outline="black", tags="battery_bar")
                    canvas.create_rectangle(bar_x, bar_y, bar_x + fill_width, bar_y + bar_height,
                                            fill=bar_color, outline="", tags="battery_bar")

                    change_str = ""
                    if initial_battery_level is not None and live_percent is not None:
                        delta = live_percent - initial_battery_level
                        if delta != 0:
                            sign = "+" if delta > 0 else ""
                            change_str = f" ({sign}{delta}%)"

                    label = f"Battery: {percent}%" + (" ⚡" if charging else "")
                    canvas.create_text(bar_x + bar_width // 2, bar_y + bar_height // 2,
                                    text=label, fill="black", font=("Arial", 10, "bold"), tags="battery_bar")

                    if change_str:
                        color = "green" if delta > 0 else "red"
                        canvas.create_text(bar_x + bar_width + 40, bar_y + bar_height // 2,
                                        text=change_str, fill=color, font=("Arial", 10, "bold"), tags="battery_bar")

                    pulse_index[0] += 1
                    canvas.after(150, draw_battery_bar)

                draw_battery_bar()

            root.after(0, update_ui)

        except Exception as e:
            log_event(f"Unhandled exception in search logic for order {order_id}: {e}")
            root.after(0, lambda: messagebox.showerror("Unexpected Error", str(e)))
            search_button.config(state="normal")

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