# view_serials_logic.py
import tkinter as tk
from tkinter import messagebox
from ttkbootstrap import ttk
from tkinter import font as tkfont
from db.database import get_db_connection
from utils.helpers import log_event, unassign_order_serial
from ui.saved_report import open_saved_report
from utils.ui_scaling import center_window, get_work_area
import traceback
import threading
from queue import Empty, Queue

SERIALS_PER_PAGE = 20


def _serial_text(value):
    """Decode an identifier once, without losing bytes or numeric formatting."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("The database returned an invalid serial identifier")
    return value


def open_serial_viewer(order_number, assigned_by=None):
    # Open a window to view and manage serial numbers assigned to an order
    try:
        view_window = tk.Toplevel()
        view_window.title(f"Assigned Serial Numbers — {order_number}")
        view_window.columnconfigure(0, weight=1)
        view_window.rowconfigure(0, weight=1)
        table_frame = ttk.Frame(view_window)
        table_frame.grid(row=0, column=0, sticky='nsew', padx=12, pady=(10, 0))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        footer = ttk.Frame(view_window, padding=12)
        footer.grid(row=1, column=0, sticky='ew')

        treeview = ttk.Treeview(table_frame, height=8,
                               columns=("Serial Number", "SKU", "Assigned At"), show="headings")
        treeview.heading("Serial Number", text="Serial Number")
        treeview.heading("SKU", text="SKU")
        treeview.heading("Assigned At", text="Assigned At")
        font_name = ttk.Style(view_window).lookup('Treeview', 'font') or 'TkDefaultFont'
        font = tkfont.Font(root=view_window, font=font_name)
        for column in ("Serial Number", "SKU", "Assigned At"):
            treeview.column(column, anchor='w', width=font.measure('M' * 18) + 24,
                            minwidth=80, stretch=False)
        treeview.grid(row=0, column=0, sticky='nsew')
        vertical_bar = ttk.Scrollbar(table_frame, orient='vertical', command=treeview.yview)
        vertical_bar.grid(row=0, column=1, sticky='ns')
        horizontal_bar = ttk.Scrollbar(table_frame, orient='horizontal', command=treeview.xview)
        horizontal_bar.grid(row=1, column=0, sticky='ew')
        treeview.configure(yscrollcommand=vertical_bar.set, xscrollcommand=horizontal_bar.set)

        # Pagination state
        page = [0]
        all_rows = []
        serials_by_item = {}
        removing = [False]
        loading = [True]
        results = Queue()
        poll_id = [None]
        closed = [False]

        status_label = tk.Label(footer, text="Loading assigned serials...", anchor='w')
        status_label.pack(fill='x')
        detail_frame = ttk.Frame(footer)
        detail_frame.pack(fill='x', pady=5)
        selected_details = tk.Text(detail_frame, height=3, width=1, wrap='word',
                                   state='disabled', autostyle=False,
                                   bg='#ffffff', fg='#334155', relief='flat',
                                   padx=12, pady=8, highlightthickness=1,
                                   highlightbackground='#dce6f2')
        selected_details.pack(side='left', fill='x', expand=True)
        detail_bar = ttk.Scrollbar(detail_frame, orient='vertical', command=selected_details.yview)
        detail_bar.pack(side='right', fill='y')
        selected_details.configure(yscrollcommand=detail_bar.set)

        def show_selected_details():
            selected = treeview.selection()
            values = treeview.item(selected[0], 'values') if selected else ()
            text = ('Serial Number: {}\nSKU: {}'.format(*values[:2]) if len(values) >= 2
                    else 'Select a row to inspect and copy its complete serial and SKU.')
            selected_details.configure(state='normal')
            selected_details.delete('1.0', tk.END)
            selected_details.insert('1.0', text)
            selected_details.configure(state='disabled')

        def update_controls(event=None):
            busy = loading[0] or removing[0]
            selected = treeview.selection()
            has_selection = bool(
                selected and selected[0] in serials_by_item
            )
            action_state = (
                "normal" if has_selection and not busy else "disabled"
            )
            remove_button.configure(state=action_state)
            view_button.configure(state=action_state)
            previous_button.configure(
                state="normal" if page[0] > 0 and not busy else "disabled"
            )
            next_button.configure(
                state="normal" if not busy and
                (page[0] + 1) * SERIALS_PER_PAGE < len(all_rows)
                else "disabled"
            )
            reload_button.configure(state="disabled" if busy else "normal")
            show_selected_details()

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
        nav_frame = tk.Frame(footer)
        nav_frame.pack(fill='x', pady=5)
        nav_frame.columnconfigure((0, 2), weight=1, uniform='pages')
        nav_frame.columnconfigure(1, weight=1)
        previous_button = tk.Button(
            nav_frame, text="Previous", command=prev_page, width=8
        )
        previous_button.grid(row=0, column=0, sticky='ew', padx=2)
        page_label = tk.Label(nav_frame, text="")
        page_label.grid(row=0, column=1, padx=2)
        next_button = tk.Button(
            nav_frame, text="Next", command=next_page, width=8
        )
        next_button.grid(row=0, column=2, sticky='ew', padx=2)

        def load_rows():
            nonlocal all_rows
            loading[0] = True
            all_rows = []
            status_label.configure(text="Loading assigned serials...")
            show_page()

            def fetch_data():
                conn = None
                try:
                    conn = get_db_connection(show_errors=False)
                    if not conn:
                        raise RuntimeError("Database unavailable.")
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT serial_number, sku, assigned_at "
                        "FROM order_serials WHERE order_number = %s "
                        "ORDER BY assigned_at, serial_number",
                        (order_number,),
                    )
                    rows = cursor.fetchall()
                    results.put(("rows", list(rows)))
                except Exception as err:
                    from services.runtime import log_diagnostic
                    log_diagnostic('serials.load_failed', error=err, stage='read')
                    msg = f"Failed to load serials:\n{err}"
                    results.put(("load_error", msg))
                finally:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass

            threading.Thread(target=fetch_data, daemon=True).start()

        def update_rows(rows):
            nonlocal all_rows
            loading[0] = False
            try:
                all_rows = [
                    (_serial_text(serial), sku, assigned_at)
                    for serial, sku, assigned_at in rows
                ]
            except (ValueError, TypeError):
                all_rows = []
                page[0] = 0
                show_page()
                status_label.configure(text="Serial data needs correction.")
                log_event("Serial viewer rejected an invalid database identifier")
                messagebox.showerror(
                    "Invalid Serial Data",
                    "A serial number could not be read exactly. "
                    "Check the database record before viewing or removing it.",
                )
                return
            page[0] = min(page[0], max(0, (len(all_rows) - 1) // SERIALS_PER_PAGE))
            show_page()
            status_label.configure(
                text="Select a serial to view or remove."
                if all_rows else "No serials are assigned to this order."
            )

        def show_page():
            # Display the current page of serial numbers in the treeview
            treeview.delete(*treeview.get_children())
            serials_by_item.clear()
            start = page[0] * SERIALS_PER_PAGE
            end = start + SERIALS_PER_PAGE
            for serial, sku_value, assigned_at in all_rows[start:end]:
                try:
                    if hasattr(assigned_at, "strftime"):
                        display_time = assigned_at.strftime("%d/%m/%Y %H:%M")
                    else:
                        display_time = str(assigned_at) if assigned_at else "Unknown"
                except Exception as e:
                    log_event(f"Error formatting assigned_at: {assigned_at} ({e})")
                    display_time = "Unknown"
                if isinstance(sku_value, (bytes, bytearray)):
                    sku_display = sku_value.decode("utf-8", errors="ignore")
                else:
                    sku_display = sku_value or ""

                item = treeview.insert("", "end", values=(serial, sku_display, display_time))
                serials_by_item[item] = serial
            values = [treeview.item(item, 'values') for item in treeview.get_children()]
            for index, column in enumerate(("Serial Number", "SKU", "Assigned At")):
                width = max([font.measure(column)] + [font.measure(row[index]) for row in values]) + 24
                treeview.column(column, width=min(width, font.measure('M' * 65) + 24))
            pages = max(1, (len(all_rows) - 1) // SERIALS_PER_PAGE + 1)
            page_label.config(
                text="Loading..." if loading[0]
                else f"Page {page[0] + 1} of {pages}"
            )
            update_controls()

        def remove_selected():
            if removing[0] or loading[0]:
                return
            selected = treeview.selection()
            serial = serials_by_item.get(selected[0]) if selected else None
            if serial is None:
                messagebox.showwarning("No Selection", "Please select a serial to remove.")
                return
            if not messagebox.askyesno(
                "Confirm", f"Remove serial '{serial}' from order '{order_number}'?"
            ):
                return
            removing[0] = True
            status_label.configure(
                text="Waiting for Web-Tools to confirm removal..."
            )
            update_controls()

            def completed(ok, response):
                if not view_window.winfo_exists():
                    return
                removing[0] = False
                update_controls()
                if ok:
                    load_rows()
                    from services.runtime import log_diagnostic
                    log_diagnostic('serials.removal_confirmed', count=1, state='confirmed')
                    if response.get("recovered_pending"):
                        messagebox.showinfo(
                            "Previous Removal Confirmed",
                            "Web-Tools confirmed the earlier removal request. "
                            "The list is being refreshed; this historical receipt "
                            "does not establish the device's current assignment.",
                            parent=view_window,
                        )
                else:
                    status_label.configure(
                        text="Removal not confirmed. Review the error before retrying."
                    )
                    detail = str(response.get(
                        "error", "Web-Tools did not confirm removal"
                    ))
                    if response.get("operation_id"):
                        detail += "\nOperation ID: " + str(response["operation_id"])
                    messagebox.showerror(
                        "Removal Not Confirmed",
                        detail,
                    )

            def worker():
                try:
                    ok, response = unassign_order_serial(order_number, serial, assigned_by)
                except Exception as exc:
                    ok, response = False, {"error": str(exc)}
                results.put(("removed", (ok, response, completed)))

            threading.Thread(target=worker, daemon=True).start()

        def view_spec():
            # View detailed specifications for the selected serial number
            if removing[0] or loading[0]:
                return
            selected = treeview.selection()
            serial = serials_by_item.get(selected[0]) if selected else None
            if serial is None:
                messagebox.showwarning("No Selection", "Please select a serial to view.")
                view_window.attributes("-topmost", 1)
                view_window.after(100, lambda: view_window.attributes("-topmost", 0))
                return

            open_saved_report(view_window, order_number, serial)

        btn_frame = tk.Frame(footer)
        btn_frame.pack(fill='x', pady=(5, 0))
        btn_frame.columnconfigure((0, 1, 2), weight=1, uniform='actions')
        remove_button = tk.Button(btn_frame, text="Remove", command=remove_selected,
                                  width=10, autostyle=False, bg='#fef2f2', fg='#b91c1c',
                                  activebackground='#fee2e2', relief='flat', pady=8)
        remove_button.grid(row=0, column=0, sticky='ew', padx=5)
        view_button = tk.Button(
            btn_frame, text="View Report", command=view_spec,
            width=10, autostyle=False, bg='#1f7f52', fg='#ffffff',
            activebackground='#17643f', activeforeground='#ffffff', relief='flat', pady=8,
        )
        view_button.grid(row=0, column=1, sticky='ew', padx=5)
        reload_button = tk.Button(btn_frame, text="Reload list",
                                  command=lambda: load_rows(), width=10,
                                  autostyle=False, bg='#e2e8f0', fg='#334155',
                                  relief='flat', pady=8)
        reload_button.grid(row=0, column=2, sticky='ew', padx=5)
        treeview.bind("<<TreeviewSelect>>", update_controls)
        footer.bind('<Configure>', lambda event: status_label.configure(
            wraplength=max(100, event.width - 32)))
        view_window.update_idletasks()
        center_window(view_window, max(740, font.measure('M' * 70) + 48),
                      max(500, footer.winfo_reqheight() + 240),
                      min_width=480, min_height=320)
        _, _, work_width, work_height = get_work_area(view_window)
        view_window.minsize(min(480, work_width - 40),
                            min(footer.winfo_reqheight() + 120, work_height - 40))

        def poll_results():
            try:
                while True:
                    kind, value = results.get_nowait()
                    if kind == "rows":
                        update_rows(value)
                    elif kind == "load_error":
                        loading[0] = False
                        page_label.configure(text="Unavailable")
                        status_label.configure(
                            text="Could not load assigned serials. Reload list to retry."
                        )
                        update_controls()
                        messagebox.showerror("Error", value, parent=view_window)
                    else:
                        ok, response, callback = value
                        callback(ok, response)
            except Empty:
                pass
            if not closed[0]:
                poll_id[0] = view_window.after(50, poll_results)

        def stop_polling(event):
            nonlocal font
            if event.widget == view_window:
                closed[0] = True
                if poll_id[0] is not None:
                    view_window.after_cancel(poll_id[0])
                    poll_id[0] = None
                # Release the measured font on the Tk thread. Callback cycles
                # may otherwise be collected by a database worker while the
                # main thread is waiting for that worker's result.
                font = None

        view_window.bind("<Destroy>", stop_polling, add="+")
        load_rows()
        poll_id[0] = view_window.after(50, poll_results)

        return view_window

    except Exception as e:
        from services.runtime import log_diagnostic
        log_diagnostic('serials.open_failed', error=e, stage='open')
        messagebox.showerror("Error", "Failed to open serial viewer")
