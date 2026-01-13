# main_logic.py
import threading
import tkinter as tk
import wmi
from tkinter import messagebox
from typing import Dict, List, Optional, Tuple

from db.database import get_db_connection
from utils.helpers import (
    log_event,
    extract_details_from_sku,
    get_live_battery_percent,
    parse_percent,
    check_mdm_lock_status,
    check_activation_status,
    is_battery_charging,
)
from utils.specs import get_laptop_specs
from logic.view_serials_logic import open_serial_viewer
import traceback
import ttkbootstrap as tb
from ttkbootstrap import ttk


ORDER_NUMBER_SQL = "LPAD(COALESCE(local_id, id), 5, '0')"


def resolve_order_identity(cursor, order_reference: str) -> Optional[Tuple[int, str]]:
    """Return the database id and display order number for a given reference."""

    if order_reference is None:
        return None

    trimmed_reference = order_reference.strip()
    if not trimmed_reference:
        return None

    conditions = ["external_id = %s", f"{ORDER_NUMBER_SQL} = %s"]
    params = [trimmed_reference, trimmed_reference]

    if trimmed_reference.isdigit():
        conditions.append("CAST(local_id AS CHAR) = %s")
        params.append(trimmed_reference)
        conditions.append("CAST(id AS CHAR) = %s")
        params.append(trimmed_reference)

    where_clause = " OR ".join(f"({clause})" for clause in conditions)
    cursor.execute(
        f"""
            SELECT id, {ORDER_NUMBER_SQL} AS order_number
            FROM `order`
            WHERE {where_clause}
            LIMIT 1
        """,
        params,
    )
    row = cursor.fetchone()
    if not row:
        return None

    order_id, order_number = row
    if isinstance(order_number, (bytes, bytearray)):
        order_number_str = order_number.decode("utf-8")
    else:
        order_number_str = str(order_number)
    return int(order_id), order_number_str


def normalise_test_result(value: Optional[str]) -> str:
    """Convert UI test labels to the canonical database value."""

    if not value:
        return "n/a"

    lowered = value.strip().lower()
    if lowered in {"pass", "fail"}:
        return lowered
    if lowered in {"n/a", "na", "not run", "not_run", "pending"}:
        return "n/a"
    return "n/a"


def prompt_for_sku_selection(root: tk.Tk, sku_options: List[str]) -> Optional[str]:
    """Display a modal prompt so the user can choose which SKU to process."""

    unique_options: List[str] = []
    seen = set()
    for option in sku_options:
        if not option:
            continue
        candidate = option.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        unique_options.append(candidate)

    if not unique_options:
        return None
    if len(unique_options) == 1:
        return unique_options[0]

    selection_event = threading.Event()
    selection: Dict[str, Optional[str]] = {"value": None}
    dialog_holder: Dict[str, tk.Toplevel] = {}

    def close_dialog(value: Optional[str]) -> None:
        selection["value"] = value
        selection_event.set()
        dialog = dialog_holder.get("dialog")
        if dialog is not None:
            dialog.destroy()

    def show_dialog() -> None:
        dialog = tk.Toplevel(root)
        dialog_holder["dialog"] = dialog
        dialog.title("Select SKU")
        dialog.transient(root)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text="Multiple SKUs were found for this order.\nSelect the one you want to process:",
            anchor="center",
            justify="center",
        ).pack(padx=20, pady=(20, 10))

        for option in unique_options:
            ttk.Button(
                dialog,
                text=option,
                command=lambda value=option: close_dialog(value),
                style="secondary.TButton",
            ).pack(fill="x", padx=20, pady=4)

        ttk.Button(dialog, text="Cancel", command=lambda: close_dialog(None)).pack(padx=20, pady=(10, 20))
        dialog.protocol("WM_DELETE_WINDOW", lambda: close_dialog(None))

        dialog.update_idletasks()
        try:
            root_x = root.winfo_rootx()
            root_y = root.winfo_rooty()
            root_width = root.winfo_width() or dialog.winfo_width()
            root_height = root.winfo_height() or dialog.winfo_height()
            dialog_width = dialog.winfo_width()
            dialog_height = dialog.winfo_height()
            pos_x = root_x + max(0, (root_width - dialog_width) // 2)
            pos_y = root_y + max(0, (root_height - dialog_height) // 2)
            dialog.geometry(f"+{pos_x}+{pos_y}")
        except Exception:
            dialog.geometry("+200+200")

    root.after(0, show_dialog)
    selection_event.wait()
    return selection["value"]

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

def battery_charging_status(index: int = 0) -> bool:
    """Return True when the specified battery reports an active charging state."""

    try:
        return is_battery_charging(index)
    except Exception as exc:  # noqa: BLE001 - defensive logging path
        log_event(f"Error checking battery charging status: {exc}")
        return False


def get_sku_from_db(cursor, order_reference):
    """Fetch SKUs for an order along with its canonical display number."""

    identity = resolve_order_identity(cursor, order_reference)
    if not identity:
        return None, []

    order_db_id, order_number = identity
    cursor.execute("SELECT sku FROM `order` WHERE id = %s", (order_db_id,))

    sku_options: List[str] = []
    seen = set()
    for (raw_value,) in cursor.fetchall():
        if raw_value is None:
            continue
        if isinstance(raw_value, (bytes, bytearray)):
            decoded = raw_value.decode("utf-8", errors="ignore")
        else:
            decoded = str(raw_value)
        for part in decoded.split(","):
            candidate = part.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            sku_options.append(candidate)

    return (order_db_id, order_number), sku_options


def load_laptop_specs():
    try:
        return get_laptop_specs()
    except Exception as spec_err:
        log_event(f"Error during get_laptop_specs: {spec_err}")
        return {
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


def load_test_results(cursor, order_id, serial_number):
    cursor.execute(
        """
            SELECT test_keyboard, test_speaker, test_microphone, test_display, test_webcam, test_usb
            FROM order_serials
            WHERE order_number = %s AND serial_number = %s
        """,
        (order_id, serial_number),
    )
    row = cursor.fetchone()
    if row:
        def to_ui_value(value: Optional[str]) -> str:
            if not value:
                return "Not Run"
            lowered = value.strip().lower()
            if lowered == "pass":
                return "pass"
            if lowered == "fail":
                return "fail"
            if lowered in {"n/a", "na"}:
                return "Not Run"
            return value

        return {
            "keyboard": to_ui_value(row[0]),
            "speaker": to_ui_value(row[1]),
            "microphone": to_ui_value(row[2]),
            "display": to_ui_value(row[3]),
            "webcam": to_ui_value(row[4]),
            "usb": to_ui_value(row[5]),
        }
    return {
        "keyboard": "Not Run",
        "speaker": "Not Run",
        "microphone": "Not Run",
        "display": "Not Run",
        "webcam": "Not Run",
        "usb": "Not Run",
    }


def render_results(
    canvas,
    order_id,
    sku,
    serial_number,
    laptop_specs,
    details,
    test_results,
    mdm_status,
    assigned_by,
    show_serial_controls: bool,
    root,
):
    canvas.delete("all")
    canvas_width = canvas.winfo_width() or 800
    center_x = canvas_width // 2

    style = tb.Style()
    success = style.colors.success
    warning = style.colors.warning
    danger = style.colors.danger
    light = style.colors.light
    secondary = style.colors.secondary

    canvas.create_text(center_x, 20, text=f"🔍 SKU: {sku}", font=("Arial", 14, "bold"), anchor="center")
    canvas.create_text(center_x, 40, text=f"Serial: {serial_number}", font=("Arial", 10, "bold"), anchor="center")

    if show_serial_controls:
        assign_button = ttk.Button(
            canvas,
            text="Assign Serial",
            style="success.TButton",
            command=lambda: assign_serial_logic(
                order_id,
                serial_number,
                laptop_specs,
                test_results,
                sku,
                mdm_status,
                assigned_by,
                root,
            ),
        )
        canvas.create_window(center_x + 90, 40, window=assign_button, anchor="w")

        view_serials_button = ttk.Button(
            canvas,
            text="View Serials",
            style="info.TButton",
            command=lambda: open_serial_viewer(order_id),
        )
        canvas.create_window(center_x + 200, 40, window=view_serials_button, anchor="w")

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

        if field.startswith("Battery") and isinstance(laptop_value, str):
            import re
            laptop_value = re.sub(r"\s*\(.*?\)", "", laptop_value).strip()

        if i % 2 == 0:
            canvas.create_rectangle(
                canvas_width * 0.05, y - 10, canvas_width * 0.95, y + 15, fill="#f9f9f9", outline=""
            )

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
    mismatch_origin_y = bottom_y + 30
    canvas.create_text(
        canvas_width * 0.35,
        mismatch_origin_y,
        text=mismatch_text,
        fill=mismatch_color,
        font=("Arial", 10, "bold"),
        anchor="nw",
    )

    if mismatches:
        log_event(f"Spec mismatches detected for order {order_id}:\n" + mismatch_text)

    estimated_line_height = 18
    mismatch_lines = mismatch_text.count("\n") + 1
    mdm_origin_y = mismatch_origin_y + mismatch_lines * estimated_line_height

    status = mdm_status or {}
    mdm_state = status.get("state", "error")
    mdm_details = status.get("details", "")

    if mdm_state == "locked":
        mdm_text = "❌ Microsoft MDM lock detected."
        if mdm_details:
            mdm_text = f"{mdm_text}\n{mdm_details}"
        mdm_color = danger
    elif mdm_state == "not_locked":
        mdm_text = "✅ No Microsoft MDM lock detected."
        if mdm_details:
            mdm_text = f"{mdm_text}\n{mdm_details}"
        mdm_color = success
    elif mdm_state == "unsupported":
        mdm_text = mdm_details or "ℹ️ Microsoft MDM lock checks are not supported on this platform."
        mdm_color = secondary
    else:
        fallback_details = mdm_details or "Unable to retrieve Microsoft MDM lock status."
        mdm_text = f"⚠️ {fallback_details}"
        mdm_color = warning

    if mdm_state == "locked":
        log_event(f"Microsoft MDM lock warning for order {order_id}: {mdm_details}")
    elif mdm_state not in {"not_locked", "unsupported"}:
        log_event(f"Microsoft MDM lock status indeterminate ({mdm_state}): {mdm_details}")

    canvas.create_text(
        canvas_width * 0.35,
        mdm_origin_y + 10,
        text=mdm_text,
        fill=mdm_color,
        font=("Arial", 10, "bold"),
        anchor="nw",
    )

    mdm_lines = mdm_text.count("\n") + 1
    mdm_height = mdm_lines * estimated_line_height
    battery_base_y = max(bottom_y + 70, mdm_origin_y + mdm_height + 30)

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
        canvas.create_text(
            bar_x + bar_width // 2, bar_y + bar_height // 2, text=display_text, fill="black", font=("Arial", 10, "bold"), tags=tag
        )

    existing_animation = getattr(canvas, "_battery_animation_id", None)
    if existing_animation:
        try:
            canvas.after_cancel(existing_animation)
        except Exception:  # pragma: no cover - defensive
            pass

    def animate():
        if len(battery_labels) == 1:
            percent = get_live_battery_percent()
            charging = battery_charging_status()
            bar_y = max(battery_base_y, canvas.winfo_height() - 30)
            draw_battery_bar(10, bar_y, battery_labels[0], percent or "NONE", charging, "battery_bar")
        else:
            percent1 = get_live_battery_percent(index=0)
            charging1 = battery_charging_status(index=0)
            draw_battery_bar(10, battery_base_y, battery_labels[0], percent1 or "NONE", charging1, "battery_bar")

            percent2 = get_live_battery_percent(index=1)
            charging2 = battery_charging_status(index=1)
            draw_battery_bar(10, battery_base_y + 30, battery_labels[1], percent2 or "NONE", charging2, "battery_bar2")

        pulse_index[0] = (pulse_index[0] + 1) % (pulse_ticks + 1)
        canvas._battery_animation_id = canvas.after(150, animate)

    animate()

def search_order_logic(
    order_id: str,
    canvas: tk.Canvas,
    search_button: tk.Button,
    test_results: dict,
    test_labels: dict,
    root: tk.Tk,
    assigned_by: Optional[str] = None,
) -> None:
    """Search for an order, compare laptop specs, and update the UI."""
    log_event(f"Starting search for order ID: {order_id}")

    def run_search():
        try:
            with get_db_connection() as conn:
                if not conn:
                    log_event("Database connection failed.")
                    return

                cursor = conn.cursor()
                identity, sku_options = get_sku_from_db(cursor, order_id)
                if not identity:
                    log_event(f"Order {order_id} not found in consolidated database.")
                    root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Order Not Found",
                            f"No order matching '{order_id}' was found in the consolidated order table.",
                        ),
                    )
                    return

                db_order_id, order_number = identity
                log_event(
                    f"Fetched {len(sku_options)} SKU candidates for order {order_number} (id={db_order_id})."
                )

                if not sku_options:
                    root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Order Missing Items",
                            f"Order '{order_number}' does not have any SKUs recorded in the database.",
                        ),
                    )
                    return

                selected_sku = prompt_for_sku_selection(root, sku_options)
                if not selected_sku:
                    log_event(
                        f"User cancelled SKU selection for order {order_number} (candidates={sku_options})."
                    )
                    root.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Selection Cancelled",
                            "No SKU was selected. Please search again when you are ready to continue.",
                        ),
                    )
                    return

                laptop_specs = load_laptop_specs()
                serial_number = laptop_specs.get("Serial Number", "Unknown")

                test_results.update(load_test_results(cursor, order_number, serial_number))
                test_results["activation"] = "pass" if check_activation_status() else "fail"
                log_event(
                    f"[DEBUG] test_results['activation'] set to: {test_results['activation']} for order {order_number}"
                )

                log_event(f"Processing SKU: {selected_sku}")
                details = extract_details_from_sku(selected_sku)
                mdm_status = check_mdm_lock_status()

                root.after(
                    0,
                lambda: render_results(
                    canvas,
                    order_number,
                    selected_sku,
                    serial_number,
                    laptop_specs,
                    details,
                    test_results,
                    mdm_status,
                    assigned_by,
                    True,
                    root,
                ),
                )

        except Exception as err:
            log_event(f"Unhandled exception in search logic for order {order_id}:\n{traceback.format_exc()}")
            msg = f"{err}"
            root.after(0, lambda: messagebox.showerror("Unexpected Error", msg))
        finally:
            root.after(0, lambda: search_button.config(state="normal"))

    threading.Thread(target=run_search, daemon=True).start()
def assign_serial_logic(
    order_number: str,
    serial_number: str,
    specs: dict,
    test_results: dict,
    sku: str,
    mdm_status: Optional[Dict[str, str]],
    assigned_by: Optional[str],
    root: tk.Tk,
) -> None:
    """
    Assign a serial number to an order and update test results.
    """
    conn = None
    try:
        if not order_number or not serial_number or serial_number == "Unknown":
            messagebox.showerror("Input Error", "Order number and serial number must be provided.")
            return

        test_keys = ["keyboard", "speaker", "microphone", "display", "webcam", "usb"]
        incomplete = [
            key.replace("_", " ").title()
            for key in test_keys
            if normalise_test_result(test_results.get(key)) == "n/a"
        ]
        mdm_locked = mdm_status and mdm_status.get("state") == "locked"

        warning_lines = []
        if incomplete:
            warning_lines.append(f"The following tests are incomplete: {', '.join(incomplete)}.")
        if mdm_locked:
            mdm_details = mdm_status.get("details") if mdm_status else ""
            detail_text = f" {mdm_details}" if mdm_details else ""
            warning_lines.append(f"Microsoft MDM lock detected.{detail_text}")

        if warning_lines:
            warn_message = (
                "There are outstanding issues before assigning this serial:\n"
                + "\n".join(warning_lines)
                + "\n\nPress OK to continue or Cancel to abort."
            )
            if not messagebox.askokcancel("Confirm Assignment", warn_message):
                return

        conn = get_db_connection()
        if not conn:
            messagebox.showerror("Database Error", "Could not connect to the database.")
            return

        cursor = conn.cursor()

        identity = resolve_order_identity(cursor, order_number)
        if not identity:
            messagebox.showerror(
                "Order Not Found",
                f"Order '{order_number}' could not be found in the consolidated order table.",
            )
            return

        order_db_id, canonical_order_number = identity
        order_number = canonical_order_number

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

        sku_value = sku or ""
        mdm_state = mdm_status.get("state") if mdm_status else None
        mdm_details = mdm_status.get("details") if mdm_status else None

        cursor.execute(
            """
                INSERT INTO order_serials (
                    order_id, order_number, serial_number, sku, cpu, ram, ssd, model, resolution, windows, battery, battery2,
                    test_keyboard, test_speaker, test_microphone, test_display, test_webcam, test_usb, activation,
                    mdm_state, mdm_details, assigned_by
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """,
            (
                order_db_id,
                order_number,
                serial_number,
                sku_value,
                specs.get("CPU", ""),
                specs.get("RAM", ""),
                specs.get("SSD", ""),
                specs.get("Model", ""),
                specs.get("Resolution", ""),
                specs.get("Windows", ""),
                specs.get("Battery", ""),
                specs.get("Battery 2", ""),
                normalise_test_result(test_results.get("keyboard")),
                normalise_test_result(test_results.get("speaker")),
                normalise_test_result(test_results.get("microphone")),
                normalise_test_result(test_results.get("display")),
                normalise_test_result(test_results.get("webcam")),
                normalise_test_result(test_results.get("usb")),
                normalise_test_result(test_results.get("activation")),
                mdm_state,
                mdm_details,
                assigned_by,
            ),
        )
        conn.commit()
        user_text = f" by '{assigned_by}'" if assigned_by else ""
        messagebox.showinfo(
            "Success",
            f"Serial '{serial_number}' (SKU '{sku_value or 'Unknown'}') assigned to order '{order_number}'{user_text}.",
        )
    except Exception as e:
        if conn:
            conn.rollback()
        messagebox.showerror("Error", f"Failed to assign serial: {e}")
    finally:
        if conn:
            conn.close()
