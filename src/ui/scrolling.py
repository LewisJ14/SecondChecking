"""Scrolling scoped to one surface, with keyboard focus kept in view."""

import tkinter as tk
from tkinter import ttk


def bind_scrolling(canvas, content=None, horizontal=False):
    content = content or canvas
    top = canvas.winfo_toplevel()
    bindings = []

    def inside(widget):
        while widget is not None:
            if widget in (canvas, content):
                return True
            widget = getattr(widget, 'master', None)
        return False

    def wheel(event, sideways=False):
        if not inside(event.widget):
            return
        if event.widget.winfo_class() in ('Text', 'Listbox', 'Treeview',
                                         'TCombobox', 'Spinbox', 'TSpinbox'):
            return
        number, delta = getattr(event, 'num', None), getattr(event, 'delta', 0)
        steps = -1 if number == 4 else 1 if number == 5 else (
            -max(1, abs(int(delta / 120))) if delta > 0 else
            max(1, abs(int(delta / 120))) if delta < 0 else 0)
        if sideways and horizontal:
            canvas.xview_scroll(steps, 'units')
        else:
            canvas.yview_scroll(steps, 'units')
        return 'break'

    def focus(event):
        if not inside(event.widget) or event.widget == canvas:
            return
        bounds = canvas.bbox('all')
        if not bounds:
            return
        position, widget = 0, event.widget
        while widget.master != canvas:
            position += widget.winfo_y()
            widget = widget.master
        for item in canvas.find_all():
            if canvas.type(item) == 'window' and canvas.itemcget(item, 'window') == str(widget):
                position += canvas.coords(item)[1]
                break
        visible_top = canvas.canvasy(0)
        bottom = position + event.widget.winfo_height()
        if position < visible_top or bottom > visible_top + canvas.winfo_height():
            target = (position - 20 if position < visible_top else
                      bottom - canvas.winfo_height() + 20)
            canvas.yview_moveto(max(0, target) / max(1, bounds[3]))

    for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
        bindings.append((sequence, top.bind(sequence, wheel, add='+')))
    if horizontal:
        bindings.append(('<Shift-MouseWheel>', top.bind(
            '<Shift-MouseWheel>', lambda event: wheel(event, True), add='+')))
    bindings.append(('<FocusIn>', top.bind('<FocusIn>', focus, add='+')))
    canvas.configure(takefocus=True, yscrollincrement=20, xscrollincrement=20)
    canvas.bind('<Next>', lambda event: canvas.yview_scroll(1, 'pages'))
    canvas.bind('<Prior>', lambda event: canvas.yview_scroll(-1, 'pages'))
    canvas.bind('<Home>', lambda event: canvas.yview_moveto(0))
    canvas.bind('<End>', lambda event: canvas.yview_moveto(1))

    def destroy(event):
        if event.widget == canvas:
            for sequence, identifier in bindings:
                if top.winfo_exists():
                    top.unbind(sequence, identifier)
            bindings.clear()
    canvas.bind('<Destroy>', destroy, add='+')


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, height=150, horizontal=False, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, height=height)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=vertical.set)
        if horizontal:
            bar = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
            bar.grid(row=1, column=0, sticky='ew')
            self.canvas.configure(xscrollcommand=bar.set)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.content = tk.Frame(self.canvas)
        self.item = self.canvas.create_window(0, 0, window=self.content, anchor='nw')

        def fit(event=None):
            width = max(self.canvas.winfo_width(),
                        self.content.winfo_reqwidth() if horizontal else 1)
            self.canvas.itemconfigure(self.item, width=width)
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.canvas.bind('<Configure>', fit)
        self.content.bind('<Configure>', fit)
        bind_scrolling(self.canvas, self.content, horizontal)
