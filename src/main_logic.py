# main_logic.py
import threading
import tkinter as tk
import wmi
import re
import datetime
import os
import subprocess
from copy import deepcopy
from tkinter import messagebox
from ui.assignment_review import prompt_assignment_review
from services.storage import compare_storage, resolve_requirement
from services.measurements import measurement_summary, fresh
from services.mdm_evidence import qualified, summary as mdm_summary, needs_review as mdm_needs_review
from services.check_results import (normalise, snapshot, review_lines,
                                    needs_reason, start_measurement)
from typing import Any, Dict, List, Optional, Tuple

from db.database import get_db_connection
from utils.helpers import (
    log_event,
    extract_details_from_sku,
    get_live_battery_percent,
    get_live_battery_state,
    parse_percent,
    check_mdm_lock_status,
    check_activation_status,
    is_battery_charging,
    cpu_specs_are_compatible,
    specification_matches,
    storage_specs_are_compatible,
    capture_autopilot_hash_csv,
    upload_hash_csv,
    upload_stock_unit_check_report,
    load_saved_check_results,
)
from utils.specs import (
    capture_batteryinfoview_report,
    get_laptop_specs,
    get_latest_batteryinfoview_report,
)
from logic.view_serials_logic import open_serial_viewer
import traceback
import ttkbootstrap as tb
from ttkbootstrap import ttk


def _read_optional_hash_file(path: Optional[str]) -> Tuple[str, str]:
    if not path:
        return "", ""
    try:
        if not os.path.exists(path):
            return os.path.basename(path), ""
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                return os.path.basename(path), handle.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                return os.path.basename(path), handle.read()
    except Exception as exc:
        log_event(f"Failed to read Autopilot hash for job serial upsert: {exc}")
    return os.path.basename(path), ""


def _run_sysprep_shutdown():
    from services.maintenance import run_sysprep_shutdown
    run_sysprep_shutdown()
    return True


def show_assign_success_dialog(root: tk.Tk, message: str) -> None:
    state = {"running": False}
    dialog = tk.Toplevel(root)
    dialog.title("Success")
    dialog.transient(root)
    dialog.grab_set()
    dialog.resizable(False, False)
    dialog.configure(bg="#f1f4f8")

    body = tk.Frame(dialog, autostyle=False, bg="#ffffff", padx=18, pady=16)
    body.pack(fill="both", expand=True, padx=12, pady=12)

    tk.Label(
        body,
        autostyle=False, text=message,
        font=("Arial", 10),
        fg="#101828",
        bg="#ffffff",
        justify="left",
        anchor="w",
    ).pack(fill="x", pady=(0, 14))

    button_row = tk.Frame(body, autostyle=False, bg="#ffffff")
    button_row.pack(anchor="e")

    def close_dialog() -> None:
        if state["running"]:
            return
        dialog.destroy()

    def sysprep_and_close() -> None:
        if state["running"]:
            return
        if not messagebox.askyesno("Prepare and shut down this computer",
                "Sysprep will prepare Windows for first use and shut down this computer. "
                "Save all other work. Continue and request administrator approval?", parent=dialog):
            return
        import queue
        state["running"] = True
        replies = queue.Queue()
        sysprep_button.configure(state="disabled")
        ok_button.configure(state="disabled")
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)

        def worker():
            try:
                _run_sysprep_shutdown()
            except Exception as exc:
                replies.put(str(exc))
            else:
                replies.put(None)

        def poll():
            try:
                error = replies.get_nowait()
            except queue.Empty:
                dialog.after(60, poll)
                return
            if error:
                state["running"] = False
                messagebox.showerror("Sysprep did not confirm success", error, parent=dialog)
                sysprep_button.configure(state="normal")
                ok_button.configure(state="normal")
                dialog.protocol("WM_DELETE_WINDOW", close_dialog)
            else:
                dialog.destroy()

        threading.Thread(target=worker, daemon=True).start()
        dialog.after(60, poll)

    ok_button = ttk.Button(button_row, text="OK", command=close_dialog, style="secondary.TButton")
    ok_button.pack(side="left", padx=(0, 8))
    sysprep_button = ttk.Button(button_row, text="OK & Sysprep", command=sysprep_and_close, style="success.TButton")
    sysprep_button.pack(side="left")

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


def _call_on_ui(root, callback, *args):
    """Run a dialog on the Tk thread and return its answer to the worker."""
    if threading.current_thread() is threading.main_thread():
        return callback(*args)
    completed = threading.Event()
    outcome = {}

    def invoke():
        try:
            outcome["value"] = callback(*args)
        except Exception as exc:
            outcome["error"] = exc
        finally:
            completed.set()

    root.after(0, invoke)
    completed.wait()
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def start_serial_assignment(root, button, assignment):
    """Keep Tk responsive while preventing concurrent edits or assignments."""
    if getattr(root, "_update_preparing", False) is True:
        return
    if getattr(root, "_assignment_running", False):
        return
    root._assignment_running = True
    button.configure(state="disabled")
    progress = tk.Toplevel(root)
    progress.title("Assigning Serial")
    progress.transient(root)
    progress.grab_set()
    progress.protocol("WM_DELETE_WINDOW", lambda: None)
    ttk.Label(
        progress, text="Saving checks to Web-Tools. Please wait...", padding=24,
    ).pack()

    def finish():
        root._assignment_running = False
        if progress.winfo_exists():
            progress.destroy()
        if button.winfo_exists():
            button.configure(state="normal")

    def worker():
        import pythoncom

        initialized = False
        try:
            pythoncom.CoInitialize()
            initialized = True
            assignment()
        except Exception as exc:
            _call_on_ui(root, messagebox.showerror, "Assignment Error", str(exc))
        finally:
            if initialized:
                pythoncom.CoUninitialize()
            root.after(0, finish)

    try:
        threading.Thread(target=worker, daemon=True).start()
    except Exception:
        finish()
        raise


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

    return normalise(value)


def prompt_for_sku_selection(
    root: tk.Tk,
    sku_options: List[str],
    *,
    title: str = "Select SKU",
    message: str = "Multiple SKUs were found for this order.\nSelect the one you want to process:",
) -> Optional[str]:
    """Display a modal prompt so the user can choose an option to process."""

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
        dialog.title(title)
        dialog.transient(root)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text=message,
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

battery_labels = ["Battery"]  # Actual per-capture count is used by the footer.

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
    merged["SSD"] = resolve_requirement(merged["SSD"], (fallback or {}).get("SSD"))
    return merged


def load_laptop_specs(force_refresh=False):
    try:
        return get_laptop_specs(force_refresh=force_refresh)
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
    """Load complete saved results, including Wi-Fi and override provenance."""
    from services.check_results import TEST_KEYS

    saved = load_saved_check_results(order_id, serial_number)
    results = dict.fromkeys(TEST_KEYS, "Not Run")
    results["_overrides"] = {}
    results["_coverage"] = {}
    results["_provenance_unknown"] = False
    results["_history_unknown"] = []
    if saved.get("found"):
        tests = saved.get("test_results")
        overrides = saved.get("test_overrides")
        if not isinstance(tests, dict) or not isinstance(overrides, dict):
            raise ValueError("Web-Tools returned invalid saved results.")
        results.update({key: normalise(tests.get(key)) for key in TEST_KEYS})
        results["_overrides"] = deepcopy(overrides)
        coverage = saved.get("test_coverage", {})
        if not isinstance(coverage, dict):
            raise ValueError("Web-Tools returned invalid test coverage.")
        results["_coverage"] = deepcopy(coverage)
        results["_provenance_unknown"] = not saved.get("provenance_known", False)
        results["_history_unknown"] = saved.get("history_unknown", list(TEST_KEYS)
                                                if results["_provenance_unknown"] else [])
    return results


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
        from services.runtime import log_diagnostic
        log_diagnostic('order.note_read_failed', error=exc, stage='read')
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
    """The server derives note attribution from the operator session."""
    from services.auth_service import api_request
    api_request("POST", "/notes/{}".format(order_db_id), {"notes": notes or ""})


def build_results_footer(laptop_specs, details, mdm_status):
    from services.measurements import battery_power_label
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
        elif field == "Resolution":
            mismatches.append("Resolution: current Windows mode only; native panel capability is unverified.")
        elif field.startswith("Battery"):
            sku_pct = parse_percent(sku_value)
            laptop_pct = parse_percent(laptop_value)
            if sku_pct is None or laptop_pct is None:
                mismatches.append(f"{field}: health is unavailable or unreadable (review required)")
            elif laptop_pct < sku_pct:
                mismatches.append(f"{field}: Expected at least {sku_pct}%, found {laptop_pct}%")
        elif not sku_is_unknown and not laptop_is_unknown:
            if field == "CPU":
                if not cpu_specs_are_compatible(sku_value, laptop_value):
                    mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")
            elif field == "SSD":
                if not storage_specs_are_compatible(sku_value, laptop_value, laptop_specs.get("Storage", {})):
                    mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}. "
                                      + compare_storage(sku_value, laptop_value, laptop_specs.get("Storage", {}))[1])
            elif not specification_matches(field, sku_value, laptop_value):
                mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")

    mismatch_text = "\n".join(mismatches) if mismatches else "All listed specs match."
    mismatch_color = danger_color if mismatches else success_color

    mdm_text, mdm_color = mdm_summary(mdm_status)

    battery_lines = []
    count = max(1, len((laptop_specs.get("Battery Evidence") or {}).get("batteries", [])))
    for index in range(count):
        live = get_live_battery_state(index)
        percent = live["percent"]
        label = "Battery" if count == 1 else f"Battery {index + 1}"
        value = f"{percent}%" if percent is not None else live["state"].title()
        battery_lines.append(f"{label} current charge: {value} — {battery_power_label(live)}")

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
    context_guard=None,
):
    for widget in canvas.winfo_children():
        widget.destroy()
    canvas.delete("all")
    canvas.configure(bg="#f1f4f8")
    canvas.update_idletasks()
    from ui.scrolling import bind_scrolling
    panel_bg = '#ffffff'
    heading = '#101828'
    content = tk.Frame(canvas, autostyle=False, bg=panel_bg, padx=20, pady=18)
    item = canvas.create_window(0, 0, window=content, anchor='nw')
    canvas._comparison_content = content
    if not getattr(canvas, "_sc12_wheel", False):
        bind_scrolling(canvas)
        canvas._sc12_wheel = True
    title = tk.Label(content, autostyle=False, text='SKU: ' + str(sku), anchor='w',
                     justify='left', bg=panel_bg, fg=heading,
                     font=('Segoe UI', 16, 'bold'))
    title.pack(fill='x', pady=(0, 8))
    identity = tk.Label(content, autostyle=False, text=(
        'Order: {}  |  Serial Number: {}'.format(order_id, serial_number)
        if show_serial_controls else 'Serial Number: ' + str(serial_number)),
        anchor='w', justify='left', bg=panel_bg, font=('Arial', 10, 'bold'))
    identity.pack(fill='x', pady=(0, 8))
    actions = tk.Frame(content, autostyle=False, bg=panel_bg)
    actions.pack(fill='x', pady=(0, 12))
    if show_serial_controls:
        def guarded(action):
            if context_guard is not None and not context_guard():
                messagebox.showwarning("Search required", "Search again to resolve the current order before using this action.")
                return
            action()

        assign_command = lambda: assign_serial_logic(
            order_id,
            serial_number,
            laptop_specs,
            test_results,
            sku,
            mdm_status,
            assigned_by,
            root,
            expected_details=deepcopy(details),
        )
        assign_button = ttk.Button(
            actions,
            text="Assign Serial",
            style="success.TButton",
            command=lambda: guarded(lambda: start_serial_assignment(root, assign_button, assign_command)),
        )
        assign_button.pack(side="left", padx=(0, 8))
        view_serials_button = ttk.Button(
            actions,
            text="View Serials",
            style="info.TButton",
            command=lambda: guarded(lambda: open_serial_viewer(order_id, assigned_by=assigned_by)),
        )
        view_serials_button.pack(side="left")


    title.pack_forget()
    title.pack(fill='x', pady=(0, 12))
    table = tk.Frame(content, autostyle=False, bg=panel_bg)
    table.pack(fill='x')
    for column, weight in enumerate((20, 30, 30, 20)):
        table.columnconfigure(column, weight=weight, uniform='spec_column')
    headings = []
    for column, text in enumerate(('Check', 'Order requirement', 'This device', 'Result')):
        label = tk.Label(table, autostyle=False, text=text, bg='#eef5f1', anchor='w',
                         font=('Arial', 10, 'bold'), padx=6, pady=8)
        label.grid(row=0, column=column, sticky='nsew')
        headings.append(label)
    cells = []
    canvas._comparison_status = {}
    fields = ['Model', 'CPU', 'SSD', 'RAM', 'Resolution', 'Windows', 'Battery']
    if has_secondary_battery(laptop_specs.get('Battery 2')):
        fields.append('Battery 2')
    mismatches = []

    for index, field in enumerate(fields):
        sku_value = details.get(field, 'Unknown')
        laptop_value = laptop_specs.get(field, 'Unknown')
        match = True
        if field.startswith('Battery') and isinstance(laptop_value, str):
            laptop_value = re.sub(r'\s*\([^)]* health\)', '', laptop_value).strip()
        sku_is_unknown = str(sku_value).strip().lower() == "unknown"
        laptop_is_unknown = str(laptop_value).strip().lower() == "unknown"
        if sku_is_unknown:
            mismatches.append(f"{field}: SKU spec is Unknown (review required)")
            match = False
        elif laptop_is_unknown:
            mismatches.append(f"{field}: Laptop spec is Unknown (review required)")
            match = False
        elif field == "Resolution":
            mismatches.append("Resolution: native panel capability is unverified.")
            match = False
        elif field.startswith("Battery"):
            sku_pct = parse_percent(sku_value)
            laptop_pct = parse_percent(laptop_value)
            if sku_pct is None or laptop_pct is None:
                mismatches.append(f"{field}: health is unavailable or unreadable (review required)")
                match = False
            elif laptop_pct < sku_pct:
                mismatches.append(f"{field}: Expected at least {sku_pct}%, found {laptop_pct}%")
                match = False
        elif not sku_is_unknown and not laptop_is_unknown:
            if field == "CPU":
                if not cpu_specs_are_compatible(sku_value, laptop_value):
                    mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")
                    match = False
            elif field == "SSD":
                if not storage_specs_are_compatible(sku_value, laptop_value, laptop_specs.get("Storage", {})):
                    mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}. "
                                      + compare_storage(sku_value, laptop_value, laptop_specs.get("Storage", {}))[1])
                    match = False
            elif not specification_matches(field, sku_value, laptop_value):
                mismatches.append(f"{field}: Expected {sku_value}, found {laptop_value}")
                match = False

        sku_display = str(sku_value)
        laptop_display = str(laptop_value)
        if field == "SSD":
            sku_display = ("Ambiguous storage\n(review mapping)" if sku_display.startswith("Ambiguous")
                           else "\n+ ".join(part.strip() for part in sku_display.split("+")))
            laptop_display = "\n+ ".join(part.strip() for part in laptop_display.split("+"))
        name = ('Storage' if field == 'SSD' else
                'Current display mode\n(panel capability unverified)' if field == 'Resolution'
                else 'Windows edition\n(activation separate)' if field == 'Windows' else field)
        row_cells = []
        for column, text in enumerate((name, sku_display, laptop_display,
                                       'MATCH' if match else 'REVIEW')):
            label = tk.Label(table, autostyle=False, text=text, anchor='w', justify='left',
                             bg=('#f8fafc' if index % 2 == 0 else panel_bg),
                             fg=heading, font=('Arial', 10), padx=6, pady=8)
            if column == 3:
                label.config(bg='#ecfdf3' if match else '#fffbeb',
                             fg='#166534' if match else '#92400e',
                             font=('Arial', 9, 'bold'))
                canvas._comparison_status[field] = label
            label.grid(row=index + 1, column=column, sticky='nsew')
            row_cells.append(label)
        cells.append(row_cells)

    def resize(event=None):
        if not content.winfo_exists():
            return
        width = max(200, canvas.winfo_width() - 4)
        canvas.itemconfigure(item, width=width)
        title.config(wraplength=max(100, width - 28))
        identity.config(wraplength=max(100, width - 28))
        for row in [headings] + cells:
            for column, label in enumerate(row):
                fraction = (.20, .30, .30, .20)[column]
                label.config(wraplength=max(30, int((width - 28) * fraction) - 16))
        canvas.configure(scrollregion=canvas.bbox('all'))
    previous = getattr(canvas, '_comparison_resize_binding', None)
    if previous:
        canvas.unbind('<Configure>', previous)
    canvas._comparison_resize_binding = canvas.bind('<Configure>', resize, add='+')
    content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
    resize()
    mismatch_text = "\n".join(mismatches) if mismatches else "All listed specs match."
    if mismatches:
        log_event(f"Spec mismatches detected for order {order_id}:\n{mismatch_text}")

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
    on_resolved=None,
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

            laptop_specs = load_laptop_specs(force_refresh=True)
            serial_number = laptop_specs.get("Serial Number", "Unknown")

            loaded_results = load_test_results(cursor, order_number, serial_number)
            start_measurement(loaded_results, "activation")
            loaded_results["activation"] = "pass" if check_activation_status() else "fail"
            log_event(
                f"Activation refreshed for order {order_number}"
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

            def deliver():
                if on_resolved is not None:
                    on_resolved({
                        "order_id": db_order_id, "order_number": order_number,
                        "serial_number": serial_number, "sku": selected_sku_value,
                        "specs": laptop_specs, "details": details,
                        "test_results": loaded_results, "mdm": mdm_status,
                        "notes": order_note_text, "footer": footer_payload,
                    })
                    return
                test_results.clear()
                test_results.update(loaded_results)
                render_results(canvas, order_number, selected_sku_value,
                               serial_number, laptop_specs, details, test_results,
                               mdm_status, assigned_by, True, order_note_text, root)
                if footer_payload and callable(footer_callback):
                    footer_callback(*footer_payload)
                if callable(order_notes_callback):
                    order_notes_callback(order_note_text, db_order_id, order_number)
                start_hash_capture_status_update(root, serial_number, "order search")

            root.after(0, deliver)

        except Exception as err:
            from services.runtime import log_diagnostic
            log_diagnostic('order.search_failed', error=err, stage='lookup')
            msg = f"{err}"
            root.after(0, lambda: messagebox.showerror("Unexpected Error", msg))
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if on_complete is None:
                root.after(0, lambda: search_button.config(state="normal"))
            if on_complete is not None:
                root.after(0, on_complete)

    threading.Thread(target=run_search, daemon=True).start()


def start_hash_capture_status_update(root: tk.Tk, serial_number: str,
                                     context_label: str, context_guard=None) -> None:
    hash_status_callback = getattr(root, "_update_hash_capture_status", None)
    if not callable(hash_status_callback):
        return

    root.after(
        0,
        lambda: hash_status_callback("Autopilot Hash Pending", "#b54708")
        if context_guard is None or context_guard() else None,
    )

    def worker() -> None:
        hash_status_text = "Autopilot Hash Failed"
        hash_status_color = "#b42318"
        try:
            hash_csv_path = capture_autopilot_hash_csv(preferred_serial=serial_number)
            if hash_csv_path:
                hash_status_text = "Autopilot Hash Collected"
                hash_status_color = "#1f7a4d"
                log_event(f"Autopilot hash ready after {context_label}: {hash_csv_path}")
            else:
                log_event(f"Autopilot hash capture returned no file after {context_label}.")
        except Exception as exc:
            log_event(f"Autopilot hash capture raised after {context_label}: {exc}")
        root.after(
            0,
            lambda t=hash_status_text, c=hash_status_color: hash_status_callback(t, c)
            if context_guard is None or context_guard() else None,
        )

    threading.Thread(target=worker, daemon=True).start()


def confirm_server_reassignment(root, conflicts):
    return _call_on_ui(
        root, messagebox.askyesno, "Reassign Serial",
        "Current server assignment: " + ", ".join(conflicts)
        + "\nMove this serial to the selected reference?",
    )


def assignment_receipt_note(response):
    operation_id = response.get("operation_id")
    note = f"\nOperation: {operation_id}" if operation_id else ""
    if response.get("recovered_pending"):
        note += (
            "\nRecovered an earlier server confirmation. Refresh Web-Tools "
            "to check the current assignment."
        )
    return note


def refresh_assignment_specs(previous, serial_number):
    current = load_laptop_specs(force_refresh=True)
    if current.get("Serial Number") != serial_number or not fresh(current):
        raise ValueError("Fresh device measurements could not be confirmed for this serial. Refresh Device and search again.")
    return current


def assign_serial_logic(
    order_number: str,
    serial_number: str,
    specs: dict,
    test_results: dict,
    sku: str,
    mdm_status: Optional[Dict[str, str]],
    assigned_by: Optional[str],
    root: tk.Tk,
    expected_details=None,
) -> None:
    """
    Assign a serial number to an order and update test results.
    """
    conn = None
    try:
        if not order_number or not serial_number or serial_number == "Unknown":
            _call_on_ui(root, messagebox.showerror, "Input Error", "Order number and serial number must be provided.")
            return

        test_results = deepcopy(test_results)
        specs = refresh_assignment_specs(specs, serial_number)
        mdm_status = qualified(check_mdm_lock_status())

        warning_lines = []
        if test_results.get("_provenance_unknown"):
            warning_lines.append("Saved result override history is unavailable for this legacy report.")
        if mdm_needs_review(mdm_status):
            warning_lines.append("Local MDM evidence needs review; tenant status is not verified.")

        conn = get_db_connection(show_errors=False)
        if not conn:
            _call_on_ui(root, messagebox.showerror, "Database Error", "Could not connect to the database.")
            return

        cursor = conn.cursor()

        details = {}
        try:
            details = (deepcopy(expected_details) if isinstance(expected_details, dict)
                       else extract_details_from_sku(cursor, (sku or "").strip()))
            mismatch_text, _, _, _, _ = build_results_footer(specs, details, mdm_status)
            if mismatch_text != "All listed specs match.":
                warning_lines.append("Spec mismatches were detected (items marked REVIEW in the results table).")
        except Exception as exc:  # noqa: BLE001 - warning enrichment should not block assignment
            log_event(f"Unable to prepare spec mismatch warning during assignment: {exc}")

        storage_ok, storage_message = compare_storage(
            details.get("SSD"), specs.get("SSD"), specs.get("Storage", {}))
        storage_review = {
            "policy": "physical_configuration", "required": details.get("SSD", "Unknown"),
            "matched": storage_ok, "detail": storage_message,
            "measured": specs.get("SSD", "Unknown"),
            "captured_at": (specs.get("Storage") or {}).get("checked_at"),
        }
        if not storage_ok:
            warning_lines.append("Storage review: " + storage_message)

        identity = resolve_order_identity(cursor, order_number)
        if not identity:
            _call_on_ui(root, messagebox.showerror,
                "Order Not Found",
                f"Order '{order_number}' could not be found in the consolidated order table.",
            )
            return

        order_db_id, canonical_order_number = identity
        order_number = canonical_order_number

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
                        _call_on_ui(root, messagebox.showinfo,
                            "Selection Cancelled",
                            "No SKU was selected. Assignment cancelled.",
                        )
                        return
                    sku_value = selected
        hash_csv_path = capture_autopilot_hash_csv(preferred_serial=serial_number)
        if not hash_csv_path:
            warning_lines.append("Autopilot hardware hash was not captured; elevated capture may be required. No tenant enrolment is inferred.")

        summary = (f"Order: {order_number}\nSerial: {serial_number}\nSKU: {sku_value}\nOperator: {assigned_by or 'not signed in'}\n\n"
                   + "\n".join(review_lines(test_results) + warning_lines)
                   + "\n\nStorage required: " + str(storage_review["required"])
                   + "\nStorage measured: " + str(storage_review["measured"])
                   + "\nStorage policy: exact physical configuration; " + storage_message
                   + "\n\n" + measurement_summary(specs)
                   + "\nDisplay: current mode only; panel capability unverified. Windows edition is separate from activation."
                   + "\n\n" + mdm_summary(mdm_status)[0])
        reason = _call_on_ui(
            root, prompt_assignment_review, root, summary,
            bool(needs_reason(test_results) or warning_lines),
        )
        if reason is None:
            return
        checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        normalized_tests, test_overrides = snapshot(test_results)
        test_coverage = deepcopy(test_results.get("_coverage", {}))
        assignment_review = {
            "operator": assigned_by, "at": checked_at,
            "reason": reason, "warnings": warning_lines,
            "history_unknown": test_results.get("_history_unknown", []),
        }

        battery_report = deepcopy(specs.get("_battery_report")) or {}
        stock_report_ok, stock_report_response = upload_stock_unit_check_report(
            order_id=order_db_id,
            order_number=order_number,
            serial_number=serial_number,
            sku=sku_value,
            specs=specs,
            test_results=normalized_tests,
            test_overrides=test_overrides,
            test_coverage=test_coverage,
            assignment_review=assignment_review,
            storage_review=storage_review,
            mdm_status=mdm_status,
            assigned_by=assigned_by,
            hash_csv_path=hash_csv_path,
            battery_report=battery_report,
            checked_at=checked_at,
            reassignment_prompt=lambda conflicts: confirm_server_reassignment(root, conflicts),
        )
        if (
            not stock_report_ok
            and isinstance(stock_report_response, dict)
            and stock_report_response.get("error") == "Stock unit not found"
        ):
            create_stock = _call_on_ui(root, messagebox.askyesno,
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
                    test_overrides=test_overrides,
                    test_coverage=test_coverage,
                    assignment_review=assignment_review,
                    storage_review=storage_review,
                    mdm_status=mdm_status,
                    assigned_by=assigned_by,
                    hash_csv_path=hash_csv_path,
                    battery_report=battery_report,
                    checked_at=checked_at,
                    reassignment_prompt=lambda conflicts: confirm_server_reassignment(root, conflicts),
                    create_stock_unit=True,
                )
            else:
                _call_on_ui(root, messagebox.showinfo,
                    "Assignment Cancelled",
                    f"Serial '{serial_number}' was not assigned because no stock entry was created.",
                )
                return
        if stock_report_ok:
            saved_callback = getattr(root, "_check_report_saved", None)
            if callable(saved_callback):
                _call_on_ui(root, saved_callback, order_db_id, serial_number,
                            test_results)
            user_text = f" by '{assigned_by}'" if assigned_by else ""
            hash_status_text = "OK" if hash_csv_path else "Not collected"
            _call_on_ui(root, show_assign_success_dialog,
                root,
                f"Serial '{serial_number}' (SKU '{sku_value or 'Unknown'}') assigned to order '{order_number}'{user_text}."
                f"\nStock Report Upload: OK"
                f"\nHash Upload: {hash_status_text}"
                + assignment_receipt_note(stock_report_response),
            )
            return

        error = (stock_report_response.get("error", "Unknown error")
                 if isinstance(stock_report_response, dict) else "Unknown error")
        if isinstance(stock_report_response, dict):
            error += assignment_receipt_note(stock_report_response)
        _call_on_ui(
            root, messagebox.showerror, "Assignment Not Confirmed",
            f"Web-Tools did not confirm the assignment: {error}\n\n"
            "Check the connection and configuration, then retry. "
            "If the request timed out, check Web-Tools before retrying.",
        )
    except Exception as e:
        if conn:
            conn.rollback()
        _call_on_ui(root, messagebox.showerror, "Error", f"Failed to assign serial: {e}")
    finally:
        if conn:
            conn.close()
