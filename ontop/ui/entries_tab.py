"""Previous Entries tab: searchable, filterable, sortable session list."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from ..analytics import SessionFilter, filter_sessions, summarize
from ..formatting import fmt_date, fmt_datetime, fmt_duration, fmt_money, parse_date
from ..models import DEVICES, PAYMENT_STATUSES, STATUS_PAID, Session, fmt_items
from . import dialogs
from .widgets import Column, DateEntry, SortableTree, Tooltip, card

if TYPE_CHECKING:
    from .app import OnTopApp

ALL_DEVICES = "All Devices"
ALL_STATUSES = "All Statuses"


def status_tag(s: Session) -> str:
    """Only rows that still need money collected are colour-highlighted."""
    return "" if s.payment_status == STATUS_PAID else s.payment_status


def session_columns(include_session_date: bool = True, include_end: bool = True,
                    include_entry: bool = True) -> list[Column]:
    cols = [
        Column("customer", "Customer", lambda s: s.customer_name, lambda s: (s.customer_name.casefold(), s.start), 170),
        Column("device", "Device", lambda s: s.device, lambda s: (s.device.casefold(), s.start), 80, "center"),
        Column("players", "Players", lambda s: str(s.players), lambda s: (s.players, s.start), 65, "center"),
        Column("game", "Game", lambda s: s.game or "—", lambda s: ((s.game or "~").casefold(), s.start), 130),
        Column("pass", "Pass", lambda s: fmt_duration(s.pass_minutes) if s.pass_id else "—",
               lambda s: (s.pass_minutes, s.start), 70, "center"),
    ]
    if include_session_date:
        cols.append(Column("date", "Session date", lambda s: fmt_date(s.start_date), lambda s: s.start, 105, "center"))
    cols.append(Column("start", "Start date/time", lambda s: fmt_datetime(s.start), lambda s: s.start, 140, "center"))
    if include_end:
        cols.append(Column("end", "End date/time", lambda s: fmt_datetime(s.end), lambda s: s.end, 140, "center"))
    cols += [
        Column("duration", "Duration", lambda s: fmt_duration(s.duration_minutes), lambda s: s.duration_minutes, 85, "e"),
        Column("method", "Method", lambda s: s.payment_method, lambda s: s.payment_method, 80, "center"),
        Column("items", "Snacks & drinks", lambda s: fmt_items(s.items) or "—", lambda s: (s.items_paise, s.start), 170),
        Column("total", "Total charge", lambda s: fmt_money(s.total_paise), lambda s: s.total_paise, 110, "e"),
        Column("paid", "Amount paid", lambda s: fmt_money(s.paid_paise), lambda s: s.paid_paise, 110, "e"),
        Column("balance", "Balance", lambda s: fmt_money(s.balance_paise), lambda s: s.balance_paise, 100, "e"),
        Column("status", "Status", lambda s: s.payment_status, lambda s: s.payment_status, 110, "center"),
    ]
    if include_entry:
        cols.append(Column("entry", "Entry time", lambda s: fmt_datetime(s.entry_time), lambda s: s.entry_time, 140, "center"))
    cols.append(Column("notes", "Note", lambda s: " ⏎ ".join(s.notes.splitlines()),
                       lambda s: (s.notes == "", s.notes.casefold()), 220))
    return cols


class PreviousEntriesTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "OnTopApp"):
        super().__init__(master, padding=(24, 18, 24, 18))
        self.app = app
        self.search_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.device_var = tk.StringVar(value=ALL_DEVICES)
        self.status_var = tk.StringVar(value=ALL_STATUSES)
        self._build()
        for var in (self.search_var, self.date_var, self.device_var, self.status_var):
            var.trace_add("write", lambda *_: self.refresh())

    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 12))
        ttk.Label(head, text="Previous entries", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="Double-click a row to edit it.", style="Subtitle.TLabel").pack(side="left", padx=14, pady=(6, 0))

        outer, bar = card(self, padding=14)
        outer.pack(fill="x", pady=(0, 12))
        ttk.Label(bar, text="Customer", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        search = ttk.Entry(bar, textvariable=self.search_var, width=22)
        search.grid(row=1, column=0, sticky="w", padx=(0, 14))
        Tooltip(search, "Matches any part of the customer name, ignoring case.")

        ttk.Label(bar, text="Session date (start)", style="CardMuted.TLabel").grid(row=0, column=1, sticky="w")
        self.date_entry = DateEntry(bar, textvariable=self.date_var, style="Inner.TFrame")
        self.date_entry.grid(row=1, column=1, sticky="w", padx=(0, 14))

        ttk.Label(bar, text="Device", style="CardMuted.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Combobox(bar, textvariable=self.device_var, values=(ALL_DEVICES, *DEVICES), state="readonly",
                     width=13).grid(row=1, column=2, sticky="w", padx=(0, 14))

        ttk.Label(bar, text="Payment status", style="CardMuted.TLabel").grid(row=0, column=3, sticky="w")
        ttk.Combobox(bar, textvariable=self.status_var, values=(ALL_STATUSES, *PAYMENT_STATUSES), state="readonly",
                     width=15).grid(row=1, column=3, sticky="w", padx=(0, 14))

        buttons = ttk.Frame(bar, style="Inner.TFrame")
        buttons.grid(row=1, column=4, sticky="e")
        bar.columnconfigure(4, weight=1)
        ttk.Button(buttons, text="Clear Filters", command=self.clear_filters).pack(side="left")
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Edit Selected", style="Accent.TButton", command=self.edit_selected).pack(side="left", padx=(8, 0))
        self.filter_error = ttk.Label(bar, style="CardError.TLabel")
        self.filter_error.grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))

        outer, inner = card(self, padding=0)
        outer.pack(fill="both", expand=True)
        self.table = SortableTree(inner, session_columns(), sort_column="entry", descending=True, height=18,
                                  tag_of=status_tag)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", self._on_double_click)
        self.table.tree.bind("<Return>", lambda e: self.edit_selected())
        self.empty_label = ttk.Label(inner, style="CardMuted.TLabel")

        self.summary = ttk.Frame(self)
        self.summary.pack(fill="x", pady=(12, 0))
        self.summary_labels = {}
        for key, title in (("count", "Sessions"), ("total", "Total charges"), ("paid", "Total received"),
                           ("balance", "Outstanding balance")):
            o, i = card(self.summary, padding=12)
            o.pack(side="left", fill="x", expand=True, padx=(0, 10) if key != "balance" else 0)
            ttk.Label(i, text=title, style="CardMuted.TLabel").pack(anchor="w")
            value = ttk.Label(i, text="0", style="CardSection.TLabel")
            value.pack(anchor="w")
            self.summary_labels[key] = value

    def current_filter(self) -> SessionFilter | None:
        date_text = self.date_var.get().strip()
        day = None
        if date_text:
            try:
                day = parse_date(date_text, "Date filter")
            except ValueError as exc:
                self.filter_error.configure(text=str(exc))
                return None
        self.filter_error.configure(text="")
        device = self.device_var.get()
        status = self.status_var.get()
        return SessionFilter(
            start_date=day,
            end_date=day,
            device=device if device in DEVICES else None,
            payment_status=status if status in PAYMENT_STATUSES else None,
            search=self.search_var.get(),
        )

    def refresh(self):
        flt = self.current_filter()
        if flt is None:
            return
        rows = filter_sessions(self.app.store.sessions, flt)
        self.table.set_items(rows)
        if rows:
            self.empty_label.place_forget()
        else:
            total = len(self.app.store.sessions)
            text = ("No sessions saved yet. Add one in the Session Entry tab." if total == 0
                    else "No sessions match these filters.")
            self.empty_label.configure(text=text)
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        summary = summarize(rows)
        self.summary_labels["count"].configure(text=str(summary.count))
        self.summary_labels["total"].configure(text=fmt_money(summary.total_paise))
        self.summary_labels["paid"].configure(text=fmt_money(summary.paid_paise))
        self.summary_labels["balance"].configure(text=fmt_money(summary.balance_paise))

    def clear_filters(self):
        self.search_var.set("")
        self.date_var.set("")
        self.device_var.set(ALL_DEVICES)
        self.status_var.set(ALL_STATUSES)

    def _on_double_click(self, event):
        row = self.table.tree.identify_row(event.y)
        if row and self.table.tree.identify_region(event.x, event.y) == "cell":
            self.app.edit_session(row)

    def edit_selected(self):
        sid = self.table.selected_id()
        if not sid:
            dialogs.showinfo("Edit session", "Select a session in the list first.", parent=self)
            return
        self.app.edit_session(sid)
