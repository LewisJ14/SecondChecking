# main_logic.py
import threading
import tkinter as tk
import wmi
from tkinter import messagebox
from db.database import get_db_connection
from utils.helpers import log_event, extract_details_from_sku, get_live_battery_percent, parse_percent
from utils.specs import get_laptop_specs
from logic.view_serials_logic import open_serial_viewer
from utils.helpers import check_activation_status
import traceback
import ttkbootstrap as tb
from ttkbootstrap import ttk
import configparser
import requests

# Store the initial battery level
initial_battery_level = get_live_battery_percent()

# Detect number of batteries and set labels
try:
    c = wmi.WMI()
    batteries = c.Win32_Battery()
    battery_labels = ["Battery"] if len(batteries) == 1 else ["Battery 1", "Battery 2"]
except Exception as e:
    log_event(f"Error detecting batteries: {e}")
    battery_labels = ["Battery"]  # fallback to just one label

_wmi_instance = None  # Cache WMI instance

def battery_charging_status(index: int = 0) -> bool:
    global _wmi_instance
    try:
        if _wmi_instance is None:
            _wmi_instance = wmi.WMI()
        batteries = _wmi_instance.Win32_Battery()
        if index < len(batteries):
            return batteries[index].BatteryStatus in [2, 6]  # 2 = Charging, 6 = Charging and High
    except Exception as e:
        log_event(f"Error checking battery charging status: {e}")
    return False

def search_order_logic(
    order_id: str,
    canvas: tk.Canvas,
    search_button: tk.Button,
    test_results: dict,
    test_labels: dict,
    root: tk.Tk
) -> None:
    """
    Search for an order, compare laptop specs, and update the UI.
    """
    log_event(f"Starting search for order ID: {order_id}")
    cached_results = {}

    def run_search():
        nonlocal cached_results
        try:
            log_event("Getting database connection...")
            with get_db_connection() as conn:
                if not conn:
                    log_event("Database connection failed.")
                    return

                log_event("Fetching SKU from database.")
                cursor = conn.cursor()
                cursor.execute("SELECT sku FROM orders WHERE order_number = %s", (order_id,))
                rows = cursor.fetchall()
                log_event(f"Fetched {len(rows)} rows for order ID: {order_id}")

                # If not found in local DB, try WooCommerce
                if not rows:
                    log_event(f"No SKUs found for order ID: {order_id}, checking WooCommerce...")

                    try:
                        from utils.helpers import load_config, get_config_path
                        config = load_config()
                        config_path = get_config_path()
                        log_event(f"Loaded config.ini from: {config_path}")
                    except Exception as config_err:
                        log_event(f"Error loading config.ini: {config_err}")
                        root.after(0, lambda: messagebox.showerror("Config Error", f"Error loading config.ini:\n{config_err}"))
                        return

                    wc_url = config.get('woocommerce', 'url', fallback=None)
                    wc_consumer_key = config.get('woocommerce', 'consumer_key', fallback=None)
                    wc_consumer_secret = config.get('woocommerce', 'consumer_secret', fallback=None)
                    log_event(f"WooCommerce config loaded: url={wc_url}, consumer_key={'set' if wc_consumer_key else 'missing'}, consumer_secret={'set' if wc_consumer_secret else 'missing'}")

                    if wc_url and wc_consumer_key and wc_consumer_secret:
                        params = {"search": order_id}
                        headers = {"User-Agent": "Mozilla/5.0"}
                        log_event(f"Request headers: {headers}")
                        log_event(f"Request URL: {wc_url} | Params: {params}")
                        try:
                            response = requests.get(
                                wc_url,
                                params=params,
                                auth=(wc_consumer_key, wc_consumer_secret),
                                headers=headers,
                                timeout=10
                            )
                            log_event(f"WooCommerce API response status: {response.status_code}")
                            log_event(f"WooCommerce API final URL: {response.url}")
                            response.raise_for_status()
                            wc_orders = response.json()
                            log_event(f"WooCommerce API returned {len(wc_orders) if isinstance(wc_orders, list) else 'unknown'} orders")
                            log_event(f"WooCommerce API raw response: {wc_orders}")
                            if wc_orders:
                                # Try to extract SKU from WooCommerce order line items
                                line_items = wc_orders[0].get("line_items", [])
                                sku = None
                                for item in line_items:
                                    if item.get("sku"):
                                        sku = item["sku"]
                                        break
                                if sku:
                                    log_event(f"Order found in WooCommerce. SKU: {sku}")
                                    rows = [(sku,)]
                                else:
                                    log_event("Order found in WooCommerce but SKU not present in line items.")
                                    root.after(0, lambda: messagebox.showwarning("No SKU", f"Order found in WooCommerce but SKU not present for Order Number: {order_id}"))
                                    return
                            else:
                                log_event("Order not found in WooCommerce.")
                                root.after(0, lambda: messagebox.showwarning("No Results", f"No order found in eBay or WooCommerce for Order Number: {order_id}"))
                                return
                        except Exception as wc_e:
                            log_event(f"Error searching WooCommerce: {wc_e}\n{traceback.format_exc()}")
                            if hasattr(wc_e, 'response') and wc_e.response is not None:
                                try:
                                    log_event(f"WooCommerce error response content: {wc_e.response.content.decode('utf-8', errors='replace')}")
                                except Exception as decode_err:
                                    log_event(f"Could not decode error response content: {decode_err}")
                            root.after(0, lambda: messagebox.showerror("WooCommerce Error", f"Error searching WooCommerce:\n{wc_e}"))
                            return
                    else:
                        log_event("WooCommerce API credentials missing in config.ini.")
                        root.after(0, lambda: messagebox.showerror("Config Error", "WooCommerce API credentials missing in config.ini."))
                        return

                # Only call get_laptop_specs() ONCE and reuse the result
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

                test_results["activation"] = "pass" if check_activation_status() else "fail"
                log_event(f"[DEBUG] test_results['activation'] set to: {test_results['activation']} for order {order_id}")

                cursor.execute("""
                    SELECT test_keyboard, test_speaker, test_display, test_webcam, test_usb
                    FROM order_serials
                    WHERE order_number = %s AND serial_number = %s
                """, (order_id, serial_number))
                test_row = cursor.fetchone()

                if test_row:
                    cached_results.update({
                        "keyboard": test_row[0],
                        "speaker": test_row[1],
                        "display": test_row[2],
                        "webcam": test_row[3],
                        "usb": test_row[4],
                    })
                else:
                    cached_results.update({
                        "keyboard": "N/A",
                        "speaker": "N/A",
                        "display": "N/A",
                        "webcam": "N/A",
                        "usb": "N/A",
                    })

                for key, value in cached_results.items():
                    test_results[key] = value

                if not rows:
                    log_event(f"No SKUs found for order ID: {order_id}")
                    root.after(0, lambda: messagebox.showwarning("No Results", f"No SKUs found for Order Number: {order_id}"))
                    return

                sku = rows[0][0]
                log_event(f"Processing SKU: {sku}")
                details = extract_details_from_sku(sku)

                # Use the already obtained laptop_specs here, do not call get_laptop_specs() again

                def update_ui():
                    canvas.delete("all")
                    canvas_width = canvas.winfo_width() or 800
                    center_x = canvas_width // 2

                    style = tb.Style()
                    primary = style.colors.primary
                    success = style.colors.success
                    info = style.colors.info
                    warning = style.colors.warning
                    danger = style.colors.danger
                    light = style.colors.light
                    secondary = style.colors.secondary

                    canvas.create_text(center_x, 20, text=f"🔍 SKU: {sku}", font=("Arial", 14, "bold"), anchor="center")
                    canvas.create_text(center_x, 40, text=f"Serial: {serial_number}", font=("Arial", 10, "bold"), anchor="center")

                    assign_button = ttk.Button(
                        canvas,
                        text="Assign Serial",
                        style="success.TButton",
                        command=lambda: assign_serial_logic(order_id, serial_number, laptop_specs, test_results, root)
                    )
                    canvas.create_window(center_x + 90, 40, window=assign_button, anchor="w")

                    view_serials_button = ttk.Button(
                        canvas,
                        text="View Serials",
                        style="info.TButton",
                        command=lambda: open_serial_viewer(order_id)
                    )
                    canvas.create_window(center_x + 200, 40, window=view_serials_button, anchor="w")

                    # Responsive columns
                    col_spec = 0.165
                    col_sku = 0.45
                    col_laptop = 0.75
                    col_symbol = 0.91

                    canvas.create_text(canvas_width * col_spec, 70, text="Spec", font=("Arial", 12, "bold"), anchor="center")
                    canvas.create_text(canvas_width * col_sku, 70, text="SKU Spec", font=("Arial", 12, "bold"), anchor="center")
                    canvas.create_text(canvas_width * col_laptop, 70, text="Laptop Spec", font=("Arial", 12, "bold"), anchor="center")
                    canvas.create_line(canvas_width * 0.05, 85, canvas_width * 0.95, 85, fill="gray", width=2)

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

                        # Remove bracketed source from battery health for display
                        if field.startswith("Battery") and isinstance(laptop_value, str):
                            import re
                            laptop_value = re.sub(r"\s*\(.*?\)", "", laptop_value).strip()

                        if i % 2 == 0:
                            canvas.create_rectangle(canvas_width * 0.05, y - 10, canvas_width * 0.95, y + 15, fill="#f9f9f9", outline="")

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
                        canvas.create_text(canvas_width * col_spec, y, text=field, font=("Arial", 10), anchor="center")
                        canvas.create_text(canvas_width * col_sku, y, text=sku_value, font=("Arial", 10), anchor="center")
                        canvas.create_text(canvas_width * col_laptop, y, text=laptop_value, font=("Arial", 10), anchor="center")
                        canvas.create_text(canvas_width * col_symbol, y, text=symbol, font=("Arial", 10), anchor="w")

                    bottom_y = start_y + (len(fields) - 1) * line_spacing + 15
                    canvas.create_line(canvas_width * 0.05, 60, canvas_width * 0.05, bottom_y, fill="lightgray")
                    canvas.create_line(canvas_width * 0.31, 60, canvas_width * 0.31, bottom_y, fill="lightgray")
                    canvas.create_line(canvas_width * 0.61, 60, canvas_width * 0.61, bottom_y, fill="lightgray")
                    canvas.create_line(canvas_width * 0.89, 60, canvas_width * 0.89, bottom_y, fill="lightgray")
                    canvas.create_line(canvas_width * 0.95, 60, canvas_width * 0.95, bottom_y, fill="lightgray")

                    mismatch_text = "\n".join(mismatches) if mismatches else "✅ All specs match"
                    mismatch_color = danger if mismatches else success
                    canvas.create_text(
                        canvas_width * 0.35,
                        bottom_y + 30,
                        text=mismatch_text,
                        fill=mismatch_color,
                        font=("Arial", 10, "bold"),
                        anchor="nw"
                    )

                    if mismatches:
                        log_event(f"Spec mismatches detected for order {order_id}:\n" + mismatch_text)

                    pulse_index = [0]
                    pulse_ticks = 4

                    def draw_battery_bar(bar_x, bar_y, label_prefix, percent, charging, tag):
                        bar_width, bar_height = 200, 20
                        if isinstance(percent, str) and percent == "NONE":
                            fill_width = 0
                            bar_color = secondary
                            display_text = f"{label_prefix}: NONE"
                        else:
                            offset = pulse_index[0] if charging else -pulse_index[0]
                            animated_percent = max(0, min(100, percent + offset))
                            fill_width = int(bar_width * animated_percent / 100)
                            if percent >= 70:
                                bar_color = success
                            elif percent >= 45:
                                bar_color = warning
                            else:
                                bar_color = danger
                            display_text = f"{label_prefix}: {percent}%" + (" ⚡" if charging else "")

                        canvas.delete(tag)
                        canvas.create_rectangle(bar_x, bar_y, bar_x + bar_width, bar_y + bar_height, fill=light, outline="black", tags=tag)
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
        finally:
            root.after(0, lambda: search_button.config(state="normal"))

    threading.Thread(target=run_search, daemon=True).start()

def assign_serial_logic(
    order_number: str,
    serial_number: str,
    specs: dict,
    test_results: dict,
    root: tk.Tk
) -> None:
    """
    Assign a serial number to an order and update test results.
    """
    conn = None
    try:
        if not order_number or not serial_number or serial_number == "Unknown":
            messagebox.showerror("Input Error", "Order number and serial number must be provided.")
            return

        conn = get_db_connection()
        if not conn:
            messagebox.showerror("Database Error", "Could not connect to the database.")
            return

        cursor = conn.cursor()

        # Check if order exists in ebay_orders
        cursor.execute("SELECT 1 FROM orders WHERE order_number = %s", (order_number,))
        in_ebay_orders = cursor.fetchone() is not None

        # If not in ebay_orders, add to website_orders if not already present
        if not in_ebay_orders:
            cursor.execute("SELECT 1 FROM website_orders WHERE order_number = %s", (order_number,))
            in_website_orders = cursor.fetchone() is not None
            if not in_website_orders:
                # Insert minimal info; you can expand columns as needed
                cursor.execute(
                    "INSERT INTO website_orders (order_number, sku) VALUES (%s, %s)",
                    (order_number, specs.get("SKU", ""))
                )

        cursor.execute("SELECT order_number FROM order_serials WHERE serial_number = %s", (serial_number,))
        existing = cursor.fetchall()

        if existing:
            old_orders = ", ".join(order[0] for order in existing)
            confirm = messagebox.askyesno(
                "Reassign Serial",
                f"Serial '{serial_number}' is already assigned to {old_orders}\nDo you want to reassign it to order '{order_number}'?"
            )
            if not confirm:
                return
            cursor.execute("DELETE FROM order_serials WHERE serial_number = %s", (serial_number,))

        cursor.execute("""
            INSERT INTO order_serials (
                order_number, serial_number, cpu, ram, ssd, model, resolution, windows, battery,
                test_keyboard, test_speaker, test_display, test_webcam, test_usb, activation
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
        """, (
            order_number, serial_number,
            specs.get("CPU", ""), specs.get("RAM", ""), specs.get("SSD", ""), specs.get("Model", ""),
            specs.get("Resolution", ""), specs.get("Windows", ""), specs.get("Battery", ""),
            test_results.get("keyboard", ""), test_results.get("speaker", ""), test_results.get("display", ""),
            test_results.get("webcam", ""), test_results.get("usb", ""), test_results.get("activation", "")
        ))
        conn.commit()
        messagebox.showinfo("Success", f"Serial '{serial_number}' assigned to order '{order_number}'.")
    except Exception as e:
        if conn:
            conn.rollback()
        messagebox.showerror("Error", f"Failed to assign serial: {e}")
    finally:
        if conn:
            conn.close()
