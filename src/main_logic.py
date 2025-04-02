# main_logic.py
import threading
import tkinter as tk
import wmi
from tkinter import messagebox
from db.database import get_db_connection
from utils.helpers import log_event, extract_details_from_sku, get_live_battery_percent
from utils.specs import get_laptop_specs
from logic.view_serials_logic import open_serial_viewer
from ui.tests import TestsWindow
import traceback

# Store the initial battery level
initial_battery_level = get_live_battery_percent()

# Detect number of batteries and set labels
try:
    c = wmi.WMI()
    batteries = c.Win32_Battery()
    battery_labels = ["Battery"] if len(batteries) == 1 else ["Battery 1", "Battery 2"]
except:
    battery_labels = ["Battery", "Battery 2"]  # fallback

def search_order_logic(order_id, canvas, search_button, test_results, test_labels, root):
    def battery_charging_status(index=0):
        try:
            c = wmi.WMI()
            batteries = c.Win32_Battery()
            if index < len(batteries):
                return batteries[index].BatteryStatus == 2  # 2 = Charging
        except:
            pass
        return None

    def parse_percent(text):
        import re
        try:
            return int(re.search(r"\d+", text).group())
        except:
            return None

    def run_search():
        try:
            search_button.config(state="disabled")
            conn = get_db_connection()
            if not conn:
                search_button.config(state="normal")
                return

            cursor = conn.cursor()
            cursor.execute("SELECT sku FROM orders WHERE order_number = %s", (order_id,))
            rows = cursor.fetchall()

            try:
                laptop_specs = get_laptop_specs()
            except Exception as spec_err:
                log_event(f"Error during get_laptop_specs: {spec_err}")
                laptop_specs = {
                    "Serial Number": "Unknown",
                    "CPU": "Unknown",
                    "RAM": "Unknown",
                    "SSD": "Unknown",
                    "Drive Type": "Unknown",
                    "Model": "Unknown",
                    "Resolution": "Unknown",
                    "Windows": "Unknown",
                    "Battery": "Unknown",
                    "Battery 2": "Unknown",
                }

            serial_number = laptop_specs.get("Serial Number", "Unknown")

            cursor.execute("""
                SELECT test_keyboard, test_speaker, test_display, test_webcam, test_usb
                FROM order_serials
                WHERE order_number = %s AND serial_number = %s
            """, (order_id, serial_number))
            test_row = cursor.fetchone()

            if test_row:
                test_results.update({
                    "keyboard": test_row[0],
                    "speaker": test_row[1],
                    "display": test_row[2],
                    "webcam": test_row[3],
                    "usb": test_row[4],
                })

            conn.close()

            if not rows:
                root.after(0, lambda: messagebox.showwarning("No Results", f"No SKUs found for Order Number: {order_id}"))
                search_button.config(state="normal")
                return

            sku = rows[0][0]
            details = extract_details_from_sku(sku)

            try:
                laptop_specs = get_laptop_specs()
            except Exception as spec_err:
                log_event(f"Error during get_laptop_specs: {spec_err}")
                laptop_specs = {
                    "Serial Number": "Unknown",
                    "CPU": "Unknown",
                    "RAM": "Unknown",
                    "SSD": "Unknown",
                    "Drive Type": "Unknown",
                    "Model": "Unknown",
                    "Resolution": "Unknown",
                    "Windows": "Unknown",
                    "Battery": "Unknown",
                    "Battery 2": "Unknown",
                }

            serial_number = laptop_specs.get("Serial Number", "Unknown")

            def update_ui():
                canvas.delete("all")
                canvas_width = canvas.winfo_width() or 800
                center_x = canvas_width // 2

                canvas.create_text(center_x, 20, text=f"🔍 SKU: {sku}", font=("Arial", 14, "bold"), anchor="center")
                canvas.create_text(center_x, 40, text=f"Serial: {serial_number}", font=("Arial", 10, "bold"), anchor="center")

                assign_button = tk.Button(canvas, text="Assign Serial", bg="lightgreen", font=("Arial", 9, "bold"),
                                          command=lambda: assign_serial_logic(order_id, serial_number, laptop_specs, test_results, root))
                canvas.create_window(center_x + 90, 40, window=assign_button, anchor="w")

                view_serials_button = tk.Button(canvas, text="View Serials", bg="lightblue", font=("Arial", 9, "bold"),
                                               command=lambda: open_serial_viewer(order_id))
                canvas.create_window(center_x + 200, 40, window=view_serials_button, anchor="w")

                canvas.create_text(canvas.winfo_width() * 0.165, 70, text="Spec", font=("Arial", 12, "bold"), anchor="center")
                canvas.create_text(canvas.winfo_width() * 0.45, 70, text="SKU Spec", font=("Arial", 12, "bold"), anchor="center")
                canvas.create_text(canvas.winfo_width() * 0.75, 70, text="Laptop Spec", font=("Arial", 12, "bold"), anchor="center")
                canvas.create_line(canvas.winfo_width() * 0.05, 85, canvas.winfo_width() * 0.95, 85, fill="gray", width=2)

                start_y = 100
                line_spacing = 25
                mismatches = []
                fields = ["Model", "CPU", "SSD", "RAM", "Resolution", "Windows", "Battery"]
                if laptop_specs.get("Battery 2") != "Unknown":
                    fields.append("Battery 2")

                for i, field in enumerate(fields):
                    y = start_y + i * line_spacing
                    sku_value = details.get(field, "Unknown")
                    laptop_value = laptop_specs.get(field, "Unknown")
                    match = True

                    if i % 2 == 0:
                        canvas.create_rectangle(canvas.winfo_width() * 0.05, y - 10, canvas.winfo_width() * 0.95, y + 15, fill="#f9f9f9", outline="")

                    if field.startswith("Battery"):
                        sku_pct = parse_percent(sku_value)
                        laptop_pct = parse_percent(laptop_value)
                        if sku_pct is not None and laptop_pct is not None and laptop_pct < sku_pct:
                            mismatches.append(f"⚠ {field}: Expected ≥{sku_pct}%, Found {laptop_pct}%")
                            match = False
                    elif sku_value.lower().strip() != laptop_value.lower().strip():
                        if sku_value != "Unknown" and laptop_value != "Unknown":
                            mismatches.append(f"⚠ {field}: Expected {sku_value}, Found {laptop_value}")
                            match = False

                    symbol = "✅" if match else "❌"
                    canvas.create_text(canvas.winfo_width() * 0.165, y, text=field, font=("Arial", 10), anchor="center")
                    canvas.create_text(canvas.winfo_width() * 0.45, y, text=sku_value, font=("Arial", 10), anchor="center")
                    canvas.create_text(canvas.winfo_width() * 0.75, y, text=laptop_value, font=("Arial", 10), anchor="center")
                    canvas.create_text(canvas.winfo_width() * 0.91, y, text=symbol, font=("Arial", 10), anchor="w")

                bottom_y = start_y + (len(fields) - 1) * line_spacing + 15
                canvas.create_line(canvas.winfo_width() * 0.05, 60, canvas.winfo_width() * 0.05, bottom_y, fill="lightgray")
                canvas.create_line(canvas.winfo_width() * 0.31, 60, canvas.winfo_width() * 0.31, bottom_y, fill="lightgray")
                canvas.create_line(canvas.winfo_width() * 0.61, 60, canvas.winfo_width() * 0.61, bottom_y, fill="lightgray")
                canvas.create_line(canvas.winfo_width() * 0.89, 60, canvas.winfo_width() * 0.89, bottom_y, fill="lightgray")
                canvas.create_line(canvas.winfo_width() * 0.95, 60, canvas.winfo_width() * 0.95, bottom_y, fill="lightgray")

                mismatch_text = "\n".join(mismatches) if mismatches else "✅ All specs match"
                mismatch_color = "red" if mismatches else "green"
                canvas.create_text(canvas.winfo_width() * 0.35, bottom_y + 30, text=mismatch_text, fill=mismatch_color, font=("Arial", 10, "bold"), anchor="nw")

                if mismatches:
                    log_event("Spec mismatches detected:\n" + mismatch_text)

                pulse_index = [0]
                pulse_ticks = 4

                def draw_battery_bar(bar_x, bar_y, label_prefix, percent, charging, tag):
                    bar_width, bar_height = 200, 20
                    if isinstance(percent, str) and percent == "NONE":
                        fill_width = 0
                        bar_color = "gray"
                        display_text = f"{label_prefix}: NONE"
                    else:
                        offset = pulse_index[0] if charging else -pulse_index[0]
                        animated_percent = max(0, min(100, percent + offset))
                        fill_width = int(bar_width * animated_percent / 100)
                        if percent >= 70:
                            bar_color = "green"
                        elif percent >= 45:
                            bar_color = "orange"
                        else:
                            bar_color = "red"
                        display_text = f"{label_prefix}: {percent}%" + (" ⚡" if charging else "")

                    canvas.delete(tag)
                    canvas.create_rectangle(bar_x, bar_y, bar_x + bar_width, bar_y + bar_height, fill="lightgray", outline="black", tags=tag)
                    canvas.create_rectangle(bar_x, bar_y, bar_x + fill_width, bar_y + bar_height, fill=bar_color, outline="", tags=tag)
                    canvas.create_text(bar_x + bar_width // 2, bar_y + bar_height // 2, text=display_text, fill="black", font=("Arial", 10, "bold"), tags=tag)

                def animate():
                    if len(battery_labels) == 1:
                        percent = get_live_battery_percent()
                        charging = battery_charging_status()
                        draw_battery_bar(10, canvas.winfo_height() - 30, battery_labels[0], percent or "NONE", charging, "battery_bar")
                    else:
                        percent1 = get_live_battery_percent(index=0)
                        charging1 = battery_charging_status(index=0)
                        draw_battery_bar(10, bottom_y + 70, battery_labels[0], percent1 or "NONE", charging1, "battery_bar")

                        percent2 = get_live_battery_percent(index=1)
                        charging2 = battery_charging_status(index=1)
                        draw_battery_bar(10, bottom_y + 100, battery_labels[1], percent2 or "NONE", charging2, "battery_bar2")

                    pulse_index[0] = (pulse_index[0] + 1) % (pulse_ticks + 1)
                    canvas.after(150, animate)

                animate()
                search_button.config(state="normal")

            root.after(0, update_ui)

        except Exception as e:
            log_event(f"Unhandled exception in search logic for order {order_id}:\n{traceback.format_exc()}")
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
