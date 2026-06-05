# main_logic.py
import threading
import tkinter as tk
import wmi
import re
import datetime
import os
import subprocess
from tkinter import messagebox
from typing import Any, Dict, List, Optional, Tuple

from db.database import get_db_connection
from utils.helpers import (
    log_event,
    extract_details_from_sku,
    get_live_battery_percent,
    parse_percent,
    check_mdm_lock_status,
    check_activation_status,
    is_battery_charging,
    cpu_specs_are_compatible,
    storage_specs_are_compatible,
    capture_autopilot_hash_csv,
    upload_hash_csv,
    upload_stock_unit_check_report,
)
from utils.specs import get_laptop_specs
from logic.view_serials_logic import open_serial_viewer
import traceback
import ttkbootstrap as tb
from ttkbootstrap import ttk


def _close_existing_sysprep_processes() -> bool:
    if os.name != "nt":
        return True

    creationflags = subprocess.CREATE_NO_WINDOW
    try:
        tasklist = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Sysprep.exe", "/NH"],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            timeout=10,
        )
        if "sysprep.exe" not in tasklist.stdout.lower():
            log_event("No existing Sysprep process found before launch.")
            return True

        taskkill = subprocess.run(
            ["taskkill", "/IM", "Sysprep.exe", "/F", "/T"],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            timeout=15,
        )
        if taskkill.returncode != 0:
            details = (taskkill.stderr or taskkill.stdout or "").strip()
            messagebox.showerror("Sysprep Error", f"Failed to close existing Sysprep window:\n{details}")
            log_event(f"Sysprep preflight failed: could not close existing process. {details}")
            return False

        log_event("Closed existing Sysprep process before launching /oobe /shutdown.")
        return True
    except Exception as exc:
        messagebox.showerror("Sysprep Error", f"Failed to check for existing Sysprep process:\n{exc}")
        log_event(f"Sysprep preflight failed while checking existing process: {exc}")
        return False


def _run_sysprep_shutdown() -> bool:
    sysprep_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "Sysprep")
    sysprep_exe = os.path.join(sysprep_dir, "Sysprep.exe")
    if not os.path.exists(sysprep_exe):
        messagebox.showerror("Sysprep Error", f"Sysprep.exe was not found:\n{sysprep_exe}")
        log_event(f"Sysprep launch failed: executable not found at {sysprep_exe}")
        return False

    if not _close_existing_sysprep_processes():
        return False

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.Popen(
            [sysprep_exe, "/oobe", "/shutdown"],
            cwd=sysprep_dir,
            creationflags=creationflags,
        )
        log_event("Sysprep launched with /oobe /shutdown after serial assignment.")
        return True
    except Exception as exc:
        messagebox.showerror("Sysprep Error", f"Failed to launch Sysprep:\n{exc}")
        log_event(f"Sysprep launch failed: {exc}")
        return False


def show_assign_success_dialog(root: tk.Tk, message: str) -> None:
    dialog = tk.Toplevel(root)
    dialog.title("Success")
    dialog.transient(root)
    dialog.grab_set()
    dialog.resizable(False, False)
    dialog.configure(bg="#f4f6fa")

    body = tk.Frame(dialog, bg="#ffffff", padx=18, pady=16)
    body.pack(fill="both", expand=True, padx=12, pady=12)

    tk.Label(
        body,
        text=message,
        font=("Segoe UI", 10),
        fg="#101828",
        bg="#ffffff",
        justify="left",
        anchor="w",
    ).pack(fill="x", pady=(0, 14))

    button_row = tk.Frame(body, bg="#ffffff")
    button_row.pack(anchor="e")

    def close_dialog() -> None:
        dialog.destroy()

    def sysprep_and_close() -> None:
        if _run_sysprep_shutdown():
            dialog.destroy()

    ok_button = ttk.Button(button_row, text="OK", command=close_dialog, style="secondary.TButton")
    ok_button.pack(side="left", padx=(0, 8))
    ttk.Button(button_row, text="OK & Sysprep", command=sysprep_and_close, style="success.TButton").pack(side="left")

    dialog.protocol("WM_DELETE_WINDOW", close_dialog)
    dialog.bind("<Return>", lambda event: close_dialog())
    dialog.update_idletasks()

    width = max(420, dialog.winfo_reqwidth())
    height = dialog.winfo_reqheight()
    x = root.winfo_rootx() + max(0, (root.winfo_width() - width) // 2)
    y = root.winfo_rooty() + max(0, (root.winfo_height() - height) // 2)
    dialog.geometry(f"{width}x{height}+{x}+{y}")
    ok_button.focus_set()
    dialog.wait_window()


def _row_to_identity(row) -> Optional[Tuple[int, str]]:
    if not row:
        return None
    order_id, order_number = row
    if isinstance(order_number, (bytes, bytearray)):
        order_number_str = order_number.decode("utf-8")
    else:
        order_number_str = str(order_number)
    return int(order_id), order_number_str


def resolve_order_by_order_number(cursor, order_reference: str) -> Optional[Tuple[int, str]]:
    """Resolve by ASTRO custom order number first."""

    if order_reference is None:
        return None

    trimmed_reference = order_reference.strip()
    if not trimmed_reference:
        return None

    cursor.execute(
        """
            SELECT id, order_number
            FROM `order`
            WHERE order_number = %s
            ORDER BY id DESC
            LIMIT 1
        """,
        (trimmed_reference,),
    )
    row = cursor.fetchone()
    if row:
        return _row_to_identity(row)

    # Convenience fallback: numeric search can map to custom "PC-####" orders.
    if trimmed_reference.isdigit():
        cursor.execute(
            """
                SELECT id, order_number
                FROM `order`
                WHERE order_number = %s
                ORDER BY id DESC
                LIMIT 1
            """,
            (f"PC-{trimmed_reference}",),
        )
        row = cursor.fetchone()
        if row:
            return _row_to_identity(row)
    return None


def resolve_order_by_external_id(cursor, order_reference: str) -> Optional[Tuple[int, str]]:
    """Resolve by marketplace order number (external_id)."""

    if order_reference is None:
        return None

    trimmed_reference = order_reference.strip()
    if not trimmed_reference:
        return None

    cursor.execute(
        """
            SELECT id, order_number
            FROM `order`
            WHERE external_id = %s
            ORDER BY id DESC
            LIMIT 1
        """,
        (trimmed_reference,),
    )
    return _row_to_identity(cursor.fetchone())


def resolve_order_identity(cursor, order_reference: str) -> Optional[Tuple[int, str]]:
    """Resolve by custom order number, then marketplace order number."""

    identity = resolve_order_by_order_number(cursor, order_reference)
    if identity:
        return identity
    return resolve_order_by_external_id(cursor, order_reference)


def prompt_for_marketplace_search(root: tk.Tk) -> bool:
    """Ask whether to continue searching by marketplace order number."""

    prompt_event = threading.Event()
    response = {"value": False}

    def ask_user() -> None:
        response["value"] = messagebox.askyesno(
            "Order Not Found",
            "ASTRO Order Number not found. Would you like to search marketplace order numbers?",
        )
        prompt_event.set()

    root.after(0, ask_user)
    prompt_event.wait()
    return bool(response["value"])


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


def has_secondary_battery(value) -> bool:
    """Return True when the second battery should be displayed."""

    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized not in {"", "unknown", "none", "n/a", "na"}


def get_sku_from_db(cursor, order_reference):
    """Fetch SKUs for an order along with its canonical display number."""

    identity = resolve_order_identity(cursor, order_reference)
    if not identity:
        return None, []

    order_db_id, order_number = identity
    sku_options = load_sku_options_for_order_id(cursor, order_db_id)
    return (order_db_id, order_number), sku_options


def load_sku_options_for_order_id(cursor, order_db_id: int) -> List[str]:
    """Return unique SKU options for the given order row id."""

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
    return sku_options


def _decode_db_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="ignore").strip()
    return str(value).strip()


def _build_custom_item_details(item_row: Dict[str, Any]) -> Dict[str, str]:
    battery_value = _decode_db_value(item_row.get("battery")) or "Unknown"
    return {
        "Model": _decode_db_value(item_row.get("model_label")) or "Unknown",
        "CPU": _decode_db_value(item_row.get("cpu")) or "Unknown",
        "SSD": _decode_db_value(item_row.get("ssd")) or "Unknown",
        "RAM": _decode_db_value(item_row.get("ram")) or "Unknown",
        "Resolution": "Unknown",
        "Windows": _decode_db_value(item_row.get("os")) or "Unknown",
        "Battery": battery_value,
        "Battery 2": battery_value,
    }


def load_order_candidates_for_order_id(cursor, order_db_id: int) -> List[Dict[str, Any]]:
    """
    Return user-selectable order item candidates.

    For custom orders, prefer rows from custom_order_item so saved spec fields
    (model/cpu/ram/ssd/os/battery) are used for comparison in SecondChecking.
    """
    try:
        cursor.execute(
            """
                SELECT id, spec_set, line_number, sku, title, model_label, cpu, os, ram, ssd, battery
                FROM custom_order_item
                WHERE order_id = %s
                ORDER BY COALESCE(spec_set, line_number, id), line_number, id
            """,
            (order_db_id,),
        )
        custom_rows = cursor.fetchall()
    except Exception as exc:
        custom_rows = []
        log_event(f"Custom order item lookup skipped for order id {order_db_id}: {exc}")

    if custom_rows:
        candidates: List[Dict[str, Any]] = []
        seen_labels = set()
        for row in custom_rows:
            (
                row_id,
                spec_set,
                line_number,
                sku,
                title,
                model_label,
                cpu,
                os_value,
                ram,
                ssd,
                battery,
            ) = row
            item_payload = {
                "model_label": model_label,
                "cpu": cpu,
                "os": os_value,
                "ram": ram,
                "ssd": ssd,
                "battery": battery,
            }
            sku_value = _decode_db_value(sku)
            title_value = _decode_db_value(title)
            model_value = _decode_db_value(model_label)
            sku_for_assignment = sku_value or model_value or title_value or f"CUSTOM-LINE-{row_id}"
            label_base = sku_for_assignment
            line_hint = spec_set or line_number or row_id
            label = label_base
            if label in seen_labels:
                label = f"{label_base} (line {line_hint})"
            seen_labels.add(label)
            candidates.append(
                {
                    "label": label,
                    "sku": sku_for_assignment,
                    "details": _build_custom_item_details(item_payload),
                }
            )
        return candidates

    return [{"label": sku, "sku": sku, "details": None} for sku in load_sku_options_for_order_id(cursor, order_db_id)]


def merge_spec_details(primary: Dict[str, str], fallback: Dict[str, str]) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for field in ["Model", "CPU", "SSD", "RAM", "Resolution", "Windows", "Battery", "Battery 2"]:
        primary_value = (primary.get(field) or "").strip() if primary else ""
        fallback_value = (fallback.get(field) or "").strip() if fallback else ""
        if primary_value and primary_value.lower() != "unknown":
            merged[field] = primary_value
        elif fallback_value:
            merged[field] = fallback_value
        else:
            merged[field] = "Unknown"
    return merged


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
            SELECT test_keyboard, test_speaker, test_microphone, test_display, test_webcam, test_usb, test_wifi
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
            "wifi": to_ui_value(row[6]),
        }
    return {
        "keyboard": "Not Run",
        "speaker": "Not Run",
        "microphone": "Not Run",
        "display": "Not Run",
        "webcam": "Not Run",
        "usb": "Not Run",
        "wifi": "Not Run",
    }


def load_order_note_for_order_id(cursor, order_db_id: int) -> str:
    """Return the latest notes text for the order row id."""

    try:
        cursor.execute(
            """
                SELECT notes
                FROM order_note
                WHERE order_id = %s
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
            """,
            (order_db_id,),
        )
        row = cursor.fetchone()
    except Exception as exc:
        log_event(f"Order note lookup failed for order id {order_db_id}: {exc}")
        return ""

    if not row:
        return ""

    value = row[0]
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="ignore").strip()
    return str(value).strip()


def save_order_note_for_order_id(order_db_id: int, notes: str) -> None:
    """Create or update the single notes row attached to an order."""

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
                INSERT INTO order_note (order_id, notes, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    notes = VALUES(notes),
                    updated_at = NOW()
            """,
            (order_db_id, notes or ""),
        )
        conn.commit()
        log_event(f"Saved order notes for order id {order_db_id}.")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def build_results_footer(laptop_specs, details, mdm_status):
    success_color = "#1f7a4d"
    warning_color = "#b54708"
    danger_color = "#b42318"
    secondary_color = "#475467"

    mismatches = []
    fields = ["Model", "CPU", "SSD", "RAM", "Resolution", "Windows", "Battery"]
    if has_secondary_battery(laptop_specs.get("Battery 2")):
        fields.append("Battery 2")

    for field in fields:
        sku_value = details.get(field, "Unknown")
        laptop_value = laptop_specs.get(field, "Unknown")

        if field.startswith("Battery") and isinstance(laptop_value, str):
            laptop_value = re.sub(r"\s*\(.*?\)", "", laptop_value).strip()

        sku_is_unknown = str(sku_value).strip().lower() == "unknown"
        laptop_is_unknown = str(laptop_value).strip().lower() == "unknown"
        if sku_is_unknown:
            mismatches.append(f"{field}: SKU spec is Unknown (review required)")
        elif laptop_is_unknown:
            mismatches.append(f"{field}: Laptop spec is Unknown (review required)")
        elif field.startswith("Battery"):
            sku_pct = parse_percent(sku_value)
            laptop_pct = parse_percent(laptop_value)
            if sku_pct is not None and laptop_pct is not None and laptop_pct < sku_pct:
                mismatches.append(f"{field}: Expected at least {sku_pct}%, found {laptop_pct}%")
        elif not sku_is_unknown and not laptop_is_unknown:
            if field == "CPU":
                if not cpu_specs_are_compatible(sku_value, laptop_value):
                    mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")
            elif field == "SSD":
                if not storage_specs_are_compatible(sku_value, laptop_value):
                    mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")
            elif str(sku_value).lower().strip() != str(laptop_value).lower().strip():
                mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")

    mismatch_text = "\n".join(mismatches) if mismatches else "All listed specs match."
    mismatch_color = danger_color if mismatches else success_color

    status = mdm_status or {}
    mdm_state = status.get("state", "error")
    mdm_details = status.get("details", "")

    if mdm_state == "locked":
        mdm_text = "Microsoft MDM lock detected."
        if mdm_details:
            mdm_text = f"{mdm_text}\n{mdm_details}"
        mdm_color = danger_color
    elif mdm_state == "not_locked":
        mdm_text = "No Microsoft MDM lock detected."
        if mdm_details:
            mdm_text = f"{mdm_text}\n{mdm_details}"
        mdm_color = success_color
    elif mdm_state == "unsupported":
        mdm_text = mdm_details or "Microsoft MDM lock checks are not supported on this platform."
        mdm_color = secondary_color
    else:
        mdm_text = mdm_details or "Unable to retrieve Microsoft MDM lock status."
        mdm_color = warning_color

    battery_lines = []
    for index, label in enumerate(battery_labels):
        percent = get_live_battery_percent(index=index)
        charging = battery_charging_status(index=index)
        if percent is None:
            line = f"{label}: NONE"
        else:
            line = f"{label}: {percent}%"
        if charging and percent is not None:
            line = f"{line} Charging"
        battery_lines.append(line)

    return mismatch_text, mismatch_color, mdm_text, mdm_color, battery_lines


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
    order_note_text: str,
    root,
):
    canvas.delete("all")
    canvas.configure(bg="#f4f6fa")
    canvas.update_idletasks()
    canvas_width = max(canvas.winfo_width(), 800)
    canvas_height = max(canvas.winfo_height(), 650)
    log_event(
        "render_results(active) start: "
        f"order_id={order_id}, sku={sku}, serial={serial_number}, "
        f"canvas_width={canvas_width}, canvas_height={canvas_height}"
    )
    style = tb.Style()
    success = style.colors.success
    warning = style.colors.warning
    danger = style.colors.danger
    secondary = style.colors.secondary

    panel_bg = "#ffffff"
    border = "#d7dde8"
    divider = "#e6eaf2"
    heading = "#101828"
    muted = "#475467"
    header_fill = "#eef4fb"
    light_fill = "#f8fafc"

    outer_left = 24
    outer_right = canvas_width - 24
    inner_left = outer_left + 18
    inner_right = outer_right - 18
    content_width = inner_right - inner_left

    header_top = 20
    header_bottom = 96
    canvas.create_rectangle(outer_left, header_top, outer_right, header_bottom, fill=panel_bg, outline=border, width=1)
    canvas.create_text(inner_left, header_top + 24, text=f"SKU: {sku}", font=("Segoe UI", 18, "bold"), fill=heading, anchor="w")
    canvas.create_text(
        inner_left,
        header_top + 54,
        text=f"Serial Number: {serial_number}",
        font=("Segoe UI", 10, "bold"),
        fill=muted,
        anchor="w",
    )

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
        view_serials_button = ttk.Button(
            canvas,
            text="View Serials",
            style="info.TButton",
            command=lambda: open_serial_viewer(order_id),
        )
        canvas.create_window(outer_right - 236, header_top + 38, window=assign_button, anchor="w")
        canvas.create_window(outer_right - 122, header_top + 38, window=view_serials_button, anchor="w")

    table_top = header_bottom + 18
    row_height = 38
    fields = ["Model", "CPU", "SSD", "RAM", "Resolution", "Windows", "Battery"]
    if has_secondary_battery(laptop_specs.get("Battery 2")):
        fields.append("Battery 2")
    log_event(f"render_results(active) fields={fields}")

    table_header_top = table_top + 12
    table_header_bottom = table_header_top + 38
    table_bottom = table_header_bottom + (len(fields) * row_height) + 12
    canvas.create_rectangle(outer_left, table_top, outer_right, table_bottom, fill=panel_bg, outline=border, width=1)
    canvas.create_rectangle(inner_left, table_header_top, inner_right, table_header_bottom, fill=header_fill, outline=divider, width=1)

    col_field = inner_left + 14
    col_sku = inner_left + int(content_width * 0.31)
    col_laptop = inner_left + int(content_width * 0.62)
    col_status = inner_right - 92

    canvas.create_text(col_field, table_header_top + 19, text="Spec", font=("Segoe UI", 11, "bold"), fill=heading, anchor="w")
    canvas.create_text(col_sku, table_header_top + 19, text="SKU Spec", font=("Segoe UI", 11, "bold"), fill=heading, anchor="w")
    canvas.create_text(col_laptop, table_header_top + 19, text="Laptop Spec", font=("Segoe UI", 11, "bold"), fill=heading, anchor="w")
    canvas.create_text(col_status, table_header_top + 19, text="Status", font=("Segoe UI", 11, "bold"), fill=heading, anchor="w")

    canvas.create_line(col_sku - 16, table_header_top, col_sku - 16, table_bottom - 12, fill=divider)
    canvas.create_line(col_laptop - 16, table_header_top, col_laptop - 16, table_bottom - 12, fill=divider)
    canvas.create_line(col_status - 16, table_header_top, col_status - 16, table_bottom - 12, fill=divider)

    mismatches = []

    for index, field in enumerate(fields):
        row_top = table_header_bottom + (index * row_height)
        row_bottom = row_top + row_height
        row_center = row_top + (row_height // 2)
        sku_value = details.get(field, "Unknown")
        laptop_value = laptop_specs.get(field, "Unknown")
        match = True

        if field.startswith("Battery") and isinstance(laptop_value, str):
            laptop_value = re.sub(r"\s*\(.*?\)", "", laptop_value).strip()

        if index % 2 == 0:
            canvas.create_rectangle(inner_left, row_top, inner_right, row_bottom, fill=light_fill, outline="")

        sku_is_unknown = str(sku_value).strip().lower() == "unknown"
        laptop_is_unknown = str(laptop_value).strip().lower() == "unknown"
        if sku_is_unknown:
            mismatches.append(f"{field}: SKU spec is Unknown (review required)")
            match = False
        elif laptop_is_unknown:
            mismatches.append(f"{field}: Laptop spec is Unknown (review required)")
            match = False
        elif field.startswith("Battery"):
            sku_pct = parse_percent(sku_value)
            laptop_pct = parse_percent(laptop_value)
            if sku_pct is not None and laptop_pct is not None and laptop_pct < sku_pct:
                mismatches.append(f"{field}: Expected at least {sku_pct}%, found {laptop_pct}%")
                match = False
        elif not sku_is_unknown and not laptop_is_unknown:
            if field == "CPU":
                if not cpu_specs_are_compatible(sku_value, laptop_value):
                    mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")
                    match = False
            elif field == "SSD":
                if not storage_specs_are_compatible(sku_value, laptop_value):
                    mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")
                    match = False
            elif sku_value.lower().strip() != laptop_value.lower().strip():
                mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")
                match = False

        canvas.create_text(col_field, row_center, text=field, font=("Segoe UI", 10), fill=heading, anchor="w")
        canvas.create_text(col_sku, row_center, text=str(sku_value), font=("Segoe UI", 10), fill=heading, anchor="w")
        canvas.create_text(col_laptop, row_center, text=str(laptop_value), font=("Segoe UI", 10), fill=heading, anchor="w")

        badge_fill = "#e7f6ec" if match else "#fdeaea"
        badge_text = "MATCH" if match else "REVIEW"
        badge_text_color = "#1f7a4d" if match else "#b42318"
        canvas.create_rectangle(col_status, row_center - 11, col_status + 72, row_center + 11, fill=badge_fill, outline="")
        canvas.create_text(col_status + 36, row_center, text=badge_text, font=("Segoe UI", 9, "bold"), fill=badge_text_color, anchor="center")

    mismatch_text = "\n".join(mismatches) if mismatches else "All listed specs match."
    mismatch_color = danger if mismatches else success
    if mismatches:
        log_event(f"Spec mismatches detected for order {order_id}:\n{mismatch_text}")

    status = mdm_status or {}
    mdm_state = status.get("state", "error")
    mdm_details = status.get("details", "")

    if mdm_state == "locked":
        mdm_text = "Microsoft MDM lock detected."
        if mdm_details:
            mdm_text = f"{mdm_text}\n{mdm_details}"
        mdm_color = danger
    elif mdm_state == "not_locked":
        mdm_text = "No Microsoft MDM lock detected."
        if mdm_details:
            mdm_text = f"{mdm_text}\n{mdm_details}"
        mdm_color = success
    elif mdm_state == "unsupported":
        mdm_text = mdm_details or "Microsoft MDM lock checks are not supported on this platform."
        mdm_color = secondary
    else:
        mdm_text = mdm_details or "Unable to retrieve Microsoft MDM lock status."
        mdm_color = warning

    if mdm_state == "locked":
        log_event(f"Microsoft MDM lock warning for order {order_id}: {mdm_details}")
    elif mdm_state not in {"not_locked", "unsupported"}:
        log_event(f"Microsoft MDM lock status indeterminate ({mdm_state}): {mdm_details}")

    existing_animation = getattr(canvas, "_battery_animation_id", None)
    if existing_animation:
        try:
            canvas.after_cancel(existing_animation)
        except Exception:
            pass
    canvas._battery_animation_id = None
    canvas.configure(scrollregion=canvas.bbox("all"))
    canvas.yview_moveto(0)

    # The dedicated footer is updated before render_results() is called.
    # Do not sample battery state again here; intermittent reads can replace
    # a valid footer with a temporary "Battery: NONE" state.



def search_order_logic(
    order_id: str,
    canvas: tk.Canvas,
    search_button: tk.Button,
    test_results: dict,
    test_labels: dict,
    root: tk.Tk,
    assigned_by: Optional[str] = None,
    on_complete=None,
) -> None:
    """Search for an order, compare laptop specs, and update the UI."""
    log_event(f"Starting search for order ID: {order_id}")

    def run_search():
        conn = None
        try:
            conn = get_db_connection(show_errors=False)
            if not conn:
                log_event("Database connection failed.")
                root.after(
                    0,
                    lambda: messagebox.showerror(
                        "Database Error",
                        "The app started, but the database is unavailable. Please try again when the connection is back.",
                    ),
                )
                return

            cursor = conn.cursor()
            identity = resolve_order_by_order_number(cursor, order_id)
            if not identity:
                log_event(f"ASTRO order number {order_id} not found.")
                if not prompt_for_marketplace_search(root):
                    log_event(f"User declined marketplace fallback search for {order_id}.")
                    return
                identity = resolve_order_by_external_id(cursor, order_id)
                if not identity:
                    log_event(f"Marketplace order number {order_id} not found in consolidated database.")
                    root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Order Not Found",
                            f"No marketplace order matching '{order_id}' was found in the consolidated order table.",
                        ),
                    )
                    return

            db_order_id, order_number = identity
            order_candidates = load_order_candidates_for_order_id(cursor, db_order_id)
            sku_options = [candidate["label"] for candidate in order_candidates]
            order_note_text = load_order_note_for_order_id(cursor, db_order_id)
            order_notes_callback = getattr(root, "_update_order_notes_footer", None)
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

            selected_candidate = next(
                (candidate for candidate in order_candidates if candidate["label"] == selected_sku),
                None,
            )
            selected_sku_value = (
                selected_candidate.get("sku")
                if isinstance(selected_candidate, dict)
                else selected_sku
            ) or selected_sku

            laptop_specs = load_laptop_specs()
            serial_number = laptop_specs.get("Serial Number", "Unknown")

            test_results.update(load_test_results(cursor, order_number, serial_number))
            test_results["activation"] = "pass" if check_activation_status() else "fail"
            log_event(
                f"[DEBUG] test_results['activation'] set to: {test_results['activation']} for order {order_number}"
            )

            log_event(f"Processing SKU: {selected_sku_value}")
            details = extract_details_from_sku(cursor, selected_sku_value)
            if isinstance(selected_candidate, dict) and selected_candidate.get("details"):
                details = merge_spec_details(selected_candidate["details"], details)
            mdm_status = check_mdm_lock_status()

            footer_payload = None
            footer_callback = getattr(root, "_update_results_footer", None)
            if callable(footer_callback):
                try:
                    footer_payload = build_results_footer(laptop_specs, details, mdm_status)
                except Exception as exc:
                    log_event(f"Search footer preparation failed: {exc}")

            hash_status_text = "Autopilot Hash Failed"
            hash_status_color = "#b42318"
            hash_status_callback = getattr(root, "_update_hash_capture_status", None)
            try:
                hash_csv_path = capture_autopilot_hash_csv(preferred_serial=serial_number)
                if hash_csv_path:
                    hash_status_text = "Autopilot Hash Collected"
                    hash_status_color = "#1f7a4d"
                    log_event(f"Autopilot hash ready after search: {hash_csv_path}")
                else:
                    log_event("Autopilot hash capture returned no file during search.")
            except Exception as exc:
                log_event(f"Autopilot hash capture raised during search: {exc}")

            root.after(
                0,
                lambda: render_results(
                    canvas,
                    order_number,
                    selected_sku_value,
                    serial_number,
                    laptop_specs,
                    details,
                    test_results,
                    mdm_status,
                    assigned_by,
                    True,
                    order_note_text,
                    root,
                ),
            )

            if footer_payload and callable(footer_callback):
                root.after(0, lambda payload=footer_payload: footer_callback(*payload))
            if callable(order_notes_callback):
                root.after(
                    0,
                    lambda t=order_note_text, oid=db_order_id, on=order_number: order_notes_callback(t, oid, on),
                )
            if callable(hash_status_callback):
                root.after(
                    0,
                    lambda t=hash_status_text, c=hash_status_color: hash_status_callback(t, c),
                )

        except Exception as err:
            log_event(f"Unhandled exception in search logic for order {order_id}:\n{traceback.format_exc()}")
            msg = f"{err}"
            root.after(0, lambda: messagebox.showerror("Unexpected Error", msg))
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            root.after(0, lambda: search_button.config(state="normal"))
            if on_complete is not None:
                root.after(0, on_complete)

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

        test_keys = ["keyboard", "speaker", "microphone", "display", "webcam", "usb", "wifi"]
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

        conn = get_db_connection()
        if not conn:
            messagebox.showerror("Database Error", "Could not connect to the database.")
            return

        cursor = conn.cursor()

        try:
            details = extract_details_from_sku(cursor, (sku or "").strip())
            mismatch_text, _, _, _, _ = build_results_footer(specs, details, mdm_status)
            if mismatch_text != "All listed specs match.":
                warning_lines.append("Spec mismatches were detected (items marked REVIEW in the results table).")
        except Exception as exc:  # noqa: BLE001 - warning enrichment should not block assignment
            log_event(f"Unable to prepare spec mismatch warning during assignment: {exc}")

        if warning_lines:
            warn_message = (
                "There are outstanding issues before assigning this serial:\n"
                + "\n".join(warning_lines)
                + "\n\nPress OK to continue or Cancel to abort."
            )
            if not messagebox.askokcancel("Confirm Assignment", warn_message):
                return

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

        sku_value = (sku or "").strip()
        if not sku_value:
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
            if sku_options:
                if len(sku_options) == 1:
                    sku_value = sku_options[0]
                else:
                    selected = prompt_for_sku_selection(root, sku_options)
                    if not selected:
                        messagebox.showinfo(
                            "Selection Cancelled",
                            "No SKU was selected. Assignment cancelled.",
                        )
                        return
                    sku_value = selected
        mdm_state = mdm_status.get("state") if mdm_status else None
        mdm_details = mdm_status.get("details") if mdm_status else None
        checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        normalized_tests = {
            "keyboard": normalise_test_result(test_results.get("keyboard")),
            "speaker": normalise_test_result(test_results.get("speaker")),
            "microphone": normalise_test_result(test_results.get("microphone")),
            "display": normalise_test_result(test_results.get("display")),
            "webcam": normalise_test_result(test_results.get("webcam")),
            "usb": normalise_test_result(test_results.get("usb")),
            "wifi": normalise_test_result(test_results.get("wifi")),
            "activation": normalise_test_result(test_results.get("activation")),
        }

        hash_csv_path = capture_autopilot_hash_csv(preferred_serial=serial_number)
        stock_report_ok, stock_report_response = upload_stock_unit_check_report(
            order_id=order_db_id,
            order_number=order_number,
            serial_number=serial_number,
            sku=sku_value,
            specs=specs,
            test_results=normalized_tests,
            mdm_status=mdm_status,
            assigned_by=assigned_by,
            hash_csv_path=hash_csv_path,
            checked_at=checked_at,
        )
        if (
            not stock_report_ok
            and isinstance(stock_report_response, dict)
            and stock_report_response.get("error") == "Stock unit not found"
        ):
            create_stock = messagebox.askyesno(
                "Stock Entry Not Found",
                (
                    f"Serial '{serial_number}' was not found in the Stock List.\n\n"
                    "Would you like to create a new Web-Tools stock entry for this laptop "
                    "and continue assigning it to the order?"
                ),
            )
            if create_stock:
                stock_report_ok, stock_report_response = upload_stock_unit_check_report(
                    order_id=order_db_id,
                    order_number=order_number,
                    serial_number=serial_number,
                    sku=sku_value,
                    specs=specs,
                    test_results=normalized_tests,
                    mdm_status=mdm_status,
                    assigned_by=assigned_by,
                    hash_csv_path=hash_csv_path,
                    checked_at=checked_at,
                    create_stock_unit=True,
                )
        if stock_report_ok:
            user_text = f" by '{assigned_by}'" if assigned_by else ""
            hash_status_text = "OK" if hash_csv_path else "Not collected"
            show_assign_success_dialog(
                root,
                f"Serial '{serial_number}' (SKU '{sku_value or 'Unknown'}') assigned to order '{order_number}'{user_text}."
                f"\nStock Report Upload: OK"
                f"\nHash Upload: {hash_status_text}",
            )
            return

        log_event(
            f"Falling back to legacy order_serials insert for serial={serial_number}; "
            f"stock report response={stock_report_response}"
        )
        if existing:
            cursor.execute("DELETE FROM order_serials WHERE serial_number = %s", (serial_number,))

        cursor.execute(
            """
                INSERT INTO order_serials (
                    order_id, order_number, serial_number, sku, cpu, ram, ssd, model, resolution, windows, battery, battery2,
                    laptop_status, test_keyboard, test_speaker, test_microphone, test_display, test_webcam, test_usb, test_wifi, activation,
                    mdm_state, mdm_details, assigned_by
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                "Reserved",
                normalized_tests["keyboard"],
                normalized_tests["speaker"],
                normalized_tests["microphone"],
                normalized_tests["display"],
                normalized_tests["webcam"],
                normalized_tests["usb"],
                normalized_tests["wifi"],
                normalized_tests["activation"],
                mdm_state,
                mdm_details,
                assigned_by,
            ),
        )
        serial_row_id = cursor.lastrowid
        conn.commit()

        hash_upload_ok = False
        if hash_csv_path:
            hash_upload_ok = upload_hash_csv(
                hash_csv_path,
                serial_id=serial_row_id,
                sku=sku_value,
                uploaded_at=checked_at,
            )
        else:
            log_event(
                f"Hash upload skipped for serial assignment: serial_id={serial_row_id}, serial_number={serial_number} (csv capture failed)."
            )

        user_text = f" by '{assigned_by}'" if assigned_by else ""
        hash_status_text = "OK" if hash_upload_ok else "Failed"
        show_assign_success_dialog(
            root,
            f"Serial '{serial_number}' (SKU '{sku_value or 'Unknown'}') assigned to order '{order_number}'{user_text}."
            f"\nHash Upload: {hash_status_text}",
        )
    except Exception as e:
        if conn:
            conn.rollback()
        messagebox.showerror("Error", f"Failed to assign serial: {e}")
    finally:
        if conn:
            conn.close()
