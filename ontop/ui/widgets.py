"""Reusable Tk widgets: tooltips, scrollable frames, date picker, sortable tables."""

from __future__ import annotations

import calendar
import tkinter as tk
from dataclasses import dataclass
from datetime import date
from tkinter import ttk
from typing import Any, Callable, Iterable, Sequence

from ..formatting import DATE_FMT, parse_date, today_local
from . import theme


def card(master: tk.Misc, padding: int = 16) -> tuple[ttk.Frame, ttk.Frame]:
    """A bordered surface; returns (outer, inner) where widgets go into inner."""
    outer = ttk.Frame(master, style="Card.TFrame")
    inner = ttk.Frame(outer, style="Inner.TFrame", padding=padding)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    return outer, inner


class Tooltip:
    def __init__(self, widget: tk.Misc, text: str, wrap: int = 320):
        self.widget = widget
        self.text = text
        self.wrap = wrap
        self._tip: tk.Toplevel | None = None
        self._after: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after = self.widget.after(350, self._show)

    def _cancel(self):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _show(self):
        if self._tip or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.configure(background=theme.BORDER)
        label = tk.Label(
            tip,
            text=self.text,
            justify="left",
            wraplength=self.wrap,
            background=theme.SURFACE_3,
            foreground=theme.TEXT,
            font=theme.FONTS.get("small"),
            padx=10,
            pady=7,
        )
        label.pack(padx=1, pady=1)
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event=None):
        self._cancel()
        if self._tip:
            self._tip.destroy()
            self._tip = None


class ScrollableFrame(ttk.Frame):
    """Vertically scrollable container; put content in ``.inner``."""

    def __init__(self, master: tk.Misc, **kwargs):
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, background=theme.BG, highlightthickness=0, borderwidth=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        ScrollableFrame._instances.append(self)
        self.bind("<Destroy>", self._on_destroy, add="+")
        if not ScrollableFrame._wheel_installed:
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.bind_all(seq, ScrollableFrame._dispatch_wheel, add="+")
            ScrollableFrame._wheel_installed = True

    _instances: list["ScrollableFrame"] = []
    _wheel_installed = False

    @staticmethod
    def _dispatch_wheel(event):
        widget = event.widget
        if isinstance(widget, str) or isinstance(widget, (ttk.Treeview, tk.Listbox)):
            return
        path = str(widget)
        owners = [f for f in ScrollableFrame._instances if path == str(f) or path.startswith(str(f) + ".")]
        if owners:
            max(owners, key=lambda f: len(str(f)))._on_wheel(event)

    def _on_destroy(self, event):
        if event.widget is self and self in ScrollableFrame._instances:
            ScrollableFrame._instances.remove(self)

    def _on_inner(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox(self._window))

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)

    def _on_wheel(self, event):
        if not self.winfo_ismapped():
            return
        if self.inner.winfo_height() <= self.canvas.winfo_height():
            return
        if getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
            if abs(event.delta) >= 120:
                step *= max(1, abs(event.delta) // 120)
        self.canvas.yview_scroll(int(step) * 3, "units")

    def scroll_to_top(self):
        self.canvas.yview_moveto(0)


class CalendarPopup(tk.Toplevel):
    """Small month calendar used by DateEntry."""

    def __init__(self, anchor: tk.Misc, initial: date, on_pick: Callable[[date], None]):
        super().__init__(anchor)
        self.withdraw()
        self.title("Select date")
        self.configure(background=theme.SURFACE)
        self.resizable(False, False)
        self.transient(anchor.winfo_toplevel())
        self.on_pick = on_pick
        self.selected = initial
        self.month = initial.replace(day=1)

        top = tk.Frame(self, background=theme.SURFACE)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Button(top, text="‹", width=3, style="Small.TButton", command=lambda: self._shift(-1)).pack(side="left")
        self.header = tk.Label(top, background=theme.SURFACE, foreground=theme.TEXT, font=theme.FONTS["bold"], width=16)
        self.header.pack(side="left", expand=True)
        ttk.Button(top, text="›", width=3, style="Small.TButton", command=lambda: self._shift(1)).pack(side="right")
        self.grid_frame = tk.Frame(self, background=theme.SURFACE)
        self.grid_frame.pack(padx=10, pady=4)
        bottom = tk.Frame(self, background=theme.SURFACE)
        bottom.pack(fill="x", padx=10, pady=(4, 10))
        ttk.Button(bottom, text="Today", style="Small.TButton", command=lambda: self._pick(today_local())).pack(side="left")
        ttk.Button(bottom, text="Close", style="Small.TButton", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())
        self._render()

        self.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.grab_set()
        self.focus_set()

    def _shift(self, months: int):
        m = self.month.month - 1 + months
        self.month = date(self.month.year + m // 12, m % 12 + 1, 1)
        self._render()

    def _render(self):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.header.configure(text=self.month.strftime("%B %Y"))
        for col, name in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            tk.Label(self.grid_frame, text=name, background=theme.SURFACE, foreground=theme.MUTED,
                     font=theme.FONTS["small"], width=4).grid(row=0, column=col, pady=(0, 4))
        today = today_local()
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(self.month.year, self.month.month)
        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                in_month = day.month == self.month.month
                bg = theme.SURFACE_2
                fg = theme.TEXT if in_month else "#566074"
                if day == self.selected:
                    bg, fg = theme.ACCENT, "#ffffff"
                elif day == today:
                    bg = theme.SURFACE_3
                cell = tk.Label(self.grid_frame, text=str(day.day), width=4, pady=4, background=bg,
                                foreground=fg, font=theme.FONTS["small"], cursor="hand2")
                cell.grid(row=row, column=col, padx=1, pady=1)
                cell.bind("<Button-1>", lambda e, d=day: self._pick(d))

    def _pick(self, d: date):
        self.destroy()
        self.on_pick(d)


class DateEntry(ttk.Frame):
    """Text entry for YYYY-MM-DD dates with a calendar button."""

    def __init__(self, master: tk.Misc, textvariable: tk.StringVar | None = None, width: int = 12,
                 on_pick: Callable[[date], None] | None = None, style: str = "TFrame"):
        super().__init__(master, style=style)
        self.var = textvariable or tk.StringVar()
        self.on_pick = on_pick
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        self.button = ttk.Button(self, text="▾", width=3, style="Small.TButton", command=self.open_calendar)
        self.button.pack(side="left", padx=(4, 0))
        Tooltip(self.button, "Pick a date from the calendar")

    def get_date(self) -> date | None:
        try:
            return parse_date(self.var.get())
        except ValueError:
            return None

    def set_date(self, d: date | None):
        self.var.set(d.strftime(DATE_FMT) if d else "")

    def set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        self.button.configure(state=state)

    def open_calendar(self):
        CalendarPopup(self, self.get_date() or today_local(), self._picked)

    def _picked(self, d: date):
        self.set_date(d)
        if self.on_pick:
            self.on_pick(d)


@dataclass
class Column:
    key: str
    heading: str
    value: Callable[[Any], str]
    sort_key: Callable[[Any], Any]
    width: int = 120
    anchor: str = "w"
    stretch: bool = True


class SortableTree(ttk.Frame):
    """Treeview with scrollbars and click-to-sort column headings."""

    def __init__(self, master: tk.Misc, columns: Sequence[Column], sort_column: str, descending: bool = True,
                 height: int = 15, id_of: Callable[[Any], str] = lambda item: item.id,
                 tag_of: Callable[[Any], str] | None = None):
        super().__init__(master, style="Inner.TFrame")
        self.columns = {c.key: c for c in columns}
        self.order = [c.key for c in columns]
        self.sort_column = sort_column
        self.descending = descending
        self.id_of = id_of
        self.tag_of = tag_of
        self.items: list[Any] = []

        self.tree = ttk.Treeview(self, columns=self.order, show="headings", height=height, selectmode="browse")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        for c in columns:
            self.tree.heading(c.key, command=lambda k=c.key: self.sort_by(k))
            self.tree.column(c.key, width=c.width, minwidth=60, anchor=c.anchor, stretch=c.stretch)
        for status, color in theme.STATUS_COLORS.items():
            self.tree.tag_configure(status, foreground=color)
        self.tree.tag_configure("odd", background=theme.SURFACE)
        self.tree.tag_configure("even", background="#1a2130")
        self._update_headings()

    def sort_by(self, key: str):
        if self.sort_column == key:
            self.descending = not self.descending
        else:
            self.sort_column = key
            self.descending = False
        self._update_headings()
        self._render()

    def _update_headings(self):
        for key, col in self.columns.items():
            arrow = ""
            if key == self.sort_column:
                arrow = "  ▼" if self.descending else "  ▲"
            self.tree.heading(key, text=col.heading + arrow)

    def set_items(self, items: Iterable[Any]):
        self.items = list(items)
        self._render()

    def _render(self):
        selected = self.selected_id()
        col = self.columns[self.sort_column]
        ordered = sorted(self.items, key=col.sort_key, reverse=self.descending)
        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(ordered):
            tags = ["even" if i % 2 else "odd"]
            if self.tag_of:
                tags.append(self.tag_of(item))
            iid = self.id_of(item)
            self.tree.insert("", "end", iid=iid, values=[self.columns[k].value(item) for k in self.order], tags=tags)
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)

    def selected_id(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def displayed_ids(self) -> list[str]:
        return list(self.tree.get_children())
