"""Monthly Passes tab: register passes and track the hours left on each."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import TYPE_CHECKING

from ..config import PASS_DEFAULT_PRICE_PAISE, PASS_HOURS, PASS_VALID_DAYS
from ..formatting import (
    fmt_date,
    fmt_date_long,
    fmt_datetime_long,
    fmt_duration,
    fmt_money,
    fmt_range,
    now_local,
    paise_to_input,
    parse_date,
    today_local,
)
from ..models import (
    PASS_ACTIVE,
    PASS_STATES,
    PAYMENT_METHODS,
    MonthlyPass,
    ValidationError,
    fmt_phone,
    normalise_name,
    normalise_phone,
    pass_state,
    prepare_pass,
)
from ..storage import StorageError
from . import dialogs, theme
from .widgets import Column, DateEntry, SortableTree, Tooltip, card

if TYPE_CHECKING:
    from .app import OnTopApp

ALL_STATES = "All"


@dataclass(frozen=True)
class PassRow:
    p: MonthlyPass
    used: int
    state: str

    @property
    def id(self) -> str:
        return self.p.id

    @property
    def left(self) -> int:
        return max(self.p.included_minutes - self.used, 0)


PASS_COLUMNS = [
    Column("holder", "Holder", lambda r: r.p.holder_name, lambda r: r.p.holder_name.casefold(), 160),
    Column("phone", "Phone", lambda r: fmt_phone(r.p.phone), lambda r: r.p.phone, 115, "center"),
    Column("purchased", "Purchased", lambda r: fmt_date(r.p.purchased_on), lambda r: r.p.purchased_on, 100, "center"),
    Column("valid", "Valid until", lambda r: fmt_date(r.p.valid_until), lambda r: r.p.valid_until, 100, "center"),
    Column("used", "Used", lambda r: fmt_duration(r.used), lambda r: r.used, 75, "e"),
    Column("left", "Time left", lambda r: fmt_duration(r.left), lambda r: r.left, 85, "e"),
    Column("state", "Status", lambda r: r.state, lambda r: (PASS_STATES.index(r.state), r.p.valid_until), 90, "center"),
    Column("price", "Price", lambda r: fmt_money(r.p.price_paise), lambda r: r.p.price_paise, 95, "e"),
    Column("method", "Paid by", lambda r: r.p.payment_method, lambda r: r.p.payment_method, 75, "center"),
]


class PassesTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "OnTopApp"):
        super().__init__(master, padding=(24, 18, 24, 18))
        self.app = app
        self._editing: MonthlyPass | None = None
        self.name_var = tk.StringVar()
        self.phone_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.price_var = tk.StringVar()
        self.method_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.state_var = tk.StringVar(value=ALL_STATES)
        self._build()
        self.date_var.trace_add("write", lambda *_: self._update_validity())
        self.phone_var.trace_add("write", lambda *_: self._update_validity())
        for var in (self.search_var, self.state_var):
            var.trace_add("write", lambda *_: self.refresh())
        self.clear_form()

    # -- layout ----------------------------------------------------------

    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 12))
        ttk.Label(head, text="Monthly passes", style="Title.TLabel").pack(side="left")
        ttk.Label(head, style="Subtitle.TLabel",
                  text=f"{PASS_HOURS} hours of play, valid {PASS_VALID_DAYS} days from purchase, on any console. "
                       "Passes are identified by phone number.").pack(side="left", padx=14, pady=(6, 0))

        columns = ttk.Frame(self)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(1, weight=1)
        columns.rowconfigure(0, weight=1)

        outer, f = card(columns, padding=18)
        outer.grid(row=0, column=0, sticky="nsw", padx=(0, 16))
        self.form_title = ttk.Label(f, text="Register new pass", style="CardSection.TLabel")
        self.form_title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        def field(row: int, text: str):
            ttk.Label(f, text=text, style="CardMuted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)

        field(1, "Holder name *")
        self.name_entry = ttk.Entry(f, textvariable=self.name_var, width=26)
        self.name_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=6)
        field(2, "Phone number *")
        ttk.Entry(f, textvariable=self.phone_var, width=16).grid(row=2, column=1, sticky="w", pady=6)
        field(3, "Purchase date *")
        DateEntry(f, textvariable=self.date_var, style="Inner.TFrame").grid(row=3, column=1, sticky="w", pady=6)
        field(4, "Price (₹) *")
        price = ttk.Entry(f, textvariable=self.price_var, width=12)
        price.grid(row=4, column=1, sticky="w", pady=6)
        Tooltip(price, f"Default price: {fmt_money(PASS_DEFAULT_PRICE_PAISE)}. "
                       "Change the default in ☰ Menu → Configurations.")
        field(5, "Paid by *")
        ttk.Combobox(f, textvariable=self.method_var, values=PAYMENT_METHODS, state="readonly",
                     width=10).grid(row=5, column=1, sticky="w", pady=6)

        self.validity_label = ttk.Label(f, style="CardInfo.TLabel", wraplength=330, justify="left")
        self.validity_label.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(f, style="Inner.TFrame")
        buttons.grid(row=7, column=0, columnspan=3, sticky="w", pady=(16, 0))
        self.save_btn = ttk.Button(buttons, text="Register Pass", style="Accent.TButton", command=self.save)
        self.clear_btn = ttk.Button(buttons, text="Clear", command=self.clear_form)
        self.cancel_btn = ttk.Button(buttons, text="Cancel Edit", style="Danger.TButton", command=self.clear_form)
        self.save_btn.pack(side="left")
        self.clear_btn.pack(side="left", padx=(8, 0))

        right = ttk.Frame(columns)
        right.grid(row=0, column=1, sticky="nsew")
        outer, bar = card(right, padding=12)
        outer.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="Search name or phone", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(bar, textvariable=self.search_var, width=20).pack(side="left", padx=(8, 16))
        ttk.Label(bar, text="Status", style="CardMuted.TLabel").pack(side="left")
        ttk.Combobox(bar, textvariable=self.state_var, values=(ALL_STATES, *PASS_STATES), state="readonly",
                     width=11).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Start Session", style="Accent.TButton",
                   command=self.start_session).pack(side="right")
        ttk.Button(bar, text="Edit Selected", command=self.edit_selected).pack(side="right", padx=(0, 8))

        outer, inner = card(right, padding=0)
        outer.pack(fill="both", expand=True)
        self.table = SortableTree(inner, PASS_COLUMNS, sort_column="purchased", descending=True, height=8,
                                  tag_of=lambda r: "" if r.state == PASS_ACTIVE else "inactive")
        self.table.tree.tag_configure("inactive", foreground=theme.MUTED)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<<TreeviewSelect>>", lambda e: self._show_usage())
        self.table.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.empty_label = ttk.Label(inner, style="CardMuted.TLabel")

        outer, inner = card(right, padding=12)
        outer.pack(side="bottom", fill="x", pady=(10, 0), before=self.table.master.master)
        self.usage_title = ttk.Label(inner, text="Pass usage", style="CardSection.TLabel")
        self.usage_title.pack(anchor="w")
        self.usage = ttk.Treeview(inner, columns=("when", "device", "players", "deducted", "charge"),
                                  show="headings", height=5, selectmode="browse")
        for key, text, width in (("when", "Session", 230), ("device", "Device", 80), ("players", "Players", 70),
                                 ("deducted", "Pass time used", 110), ("charge", "Extra players paid", 130)):
            self.usage.heading(key, text=text)
            self.usage.column(key, width=width, anchor="w")
        self.usage.pack(fill="x", pady=(6, 0))
        self.usage.bind("<Double-1>", self._edit_usage_session)

    # -- form --------------------------------------------------------------

    def clear_form(self):
        self._editing = None
        self.name_var.set("")
        self.phone_var.set("")
        self.date_var.set(fmt_date(today_local()))
        self.price_var.set(paise_to_input(PASS_DEFAULT_PRICE_PAISE))
        self.method_var.set("Cash")
        self.form_title.configure(text="Register new pass")
        self.save_btn.configure(text="Register Pass")
        self.cancel_btn.pack_forget()
        self.clear_btn.pack(side="left", padx=(8, 0))
        self.save_btn.configure(state="disabled" if self.app.store.read_only else "normal")
        self._update_validity()

    def prefill(self, phone: str = "", name: str = ""):
        if self._editing:
            self.clear_form()
        if phone.strip():
            self.phone_var.set(phone.strip())
        if name.strip() and not self.name_var.get().strip():
            self.name_var.set(normalise_name(name))
        (self.name_entry if not self.name_var.get() else self.name_entry).focus_set()

    def _update_validity(self):
        try:
            purchased = parse_date(self.date_var.get(), "Purchase date")
        except ValueError as exc:
            self.validity_label.configure(text=str(exc), style="CardError.TLabel")
            return
        probe = MonthlyPass("", "x", "0000000000", purchased, 0, "Cash", now_local(), now_local())
        text = (f"Includes {PASS_HOURS} hours · usable {fmt_date_long(purchased)} – "
                f"{fmt_date_long(probe.valid_until)}")
        phone = normalise_phone(self.phone_var.get())
        if len(phone) == 10:
            existing = [p for p in self.app.store.passes if p.phone == phone and
                        (not self._editing or p.id != self._editing.id)]
            if existing:
                latest = max(existing, key=lambda p: p.purchased_on)
                text += (f"\nThis number already has {len(existing)} pass(es); latest bought "
                         f"{fmt_date_long(latest.purchased_on)} by {latest.holder_name}.")
        self.validity_label.configure(text=text, style="CardInfo.TLabel")

    def save(self):
        store = self.app.store
        if store.read_only:
            dialogs.showerror("Saving disabled", store.load_error or "The data file could not be loaded.", parent=self)
            return
        try:
            p = prepare_pass(holder_name=self.name_var.get(), phone_text=self.phone_var.get(),
                             purchased_text=self.date_var.get(), price_text=self.price_var.get(),
                             payment_method=self.method_var.get(), now=now_local(), existing=self._editing)
            if self._editing:
                store.update_pass(p)
            else:
                store.add_pass(p)
        except ValidationError as exc:
            dialogs.showerror("Please fix the following", "\n".join(f"• {e}" for e in exc.errors), parent=self)
            return
        except StorageError as exc:
            dialogs.showerror("Could not save", f"{exc}\n\nYour entries are still in the form.", parent=self)
            return
        updating = self._editing is not None
        self.clear_form()
        self.app.data_changed()
        self.table.tree.selection_set(p.id) if self.table.tree.exists(p.id) else None
        verb = "Updated" if updating else "Registered"
        self.app.set_status(f"{verb} monthly pass for {p.holder_name} ({fmt_phone(p.phone)}).")
        dialogs.showinfo(
            f"Pass {verb.lower()}",
            f"{verb} monthly pass for {p.holder_name}\nPhone {fmt_phone(p.phone)}\n"
            f"{p.hours} hours · valid {fmt_date_long(p.purchased_on)} – {fmt_date_long(p.valid_until)}\n"
            f"Price {fmt_money(p.price_paise)} paid by {p.payment_method}",
            parent=self,
        )

    def edit_selected(self):
        p = self.app.store.get_pass(self.table.selected_id() or "")
        if p is None:
            dialogs.showinfo("Edit pass", "Select a pass in the list first.", parent=self)
            return
        self._editing = p
        self.name_var.set(p.holder_name)
        self.phone_var.set(fmt_phone(p.phone))
        self.date_var.set(fmt_date(p.purchased_on))
        self.price_var.set(paise_to_input(p.price_paise))
        self.method_var.set(p.payment_method)
        self.form_title.configure(text=f"Edit pass — {p.holder_name}")
        self.save_btn.configure(text="Update Pass")
        self.clear_btn.pack_forget()
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.validity_label.configure(text=self.validity_label.cget("text") +
                                      f"\nRegistered {fmt_datetime_long(p.created_at)}")

    def start_session(self):
        p = self.app.store.get_pass(self.table.selected_id() or "")
        if p is None:
            dialogs.showinfo("Start session", "Select a pass in the list first.", parent=self)
            return
        used = self.app.store.pass_used_minutes(p.id)
        state = pass_state(p, used, today_local())
        if state != PASS_ACTIVE and not dialogs.askyesno(
            "Pass not active",
            f"This pass is '{state}'. Open a session for it anyway (for example to enter a past session)?",
            parent=self,
        ):
            return
        self.app.start_pass_session(p)

    # -- list ------------------------------------------------------------

    def rows(self) -> list[PassRow]:
        store = self.app.store
        today = today_local()
        out = []
        for p in store.passes:
            used = store.pass_used_minutes(p.id)
            out.append(PassRow(p, used, pass_state(p, used, today)))
        return out

    def refresh(self):
        needle = normalise_name(self.search_var.get()).casefold()
        digits = normalise_phone(self.search_var.get())
        state = self.state_var.get()
        rows = [
            r for r in self.rows()
            if (not needle or needle in r.p.holder_name.casefold() or (digits and digits in r.p.phone))
            and (state == ALL_STATES or r.state == state)
        ]
        self.table.set_items(rows)
        if rows:
            self.empty_label.place_forget()
        else:
            text = ("No passes registered yet. Use the form on the left to register one."
                    if not self.app.store.passes else "No passes match the search.")
            self.empty_label.configure(text=text)
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        self._show_usage()
        if not self._editing:
            self.save_btn.configure(state="disabled" if self.app.store.read_only else "normal")

    def _show_usage(self):
        self.usage.delete(*self.usage.get_children())
        p = self.app.store.get_pass(self.table.selected_id() or "")
        if p is None:
            self.usage_title.configure(text="Pass usage — select a pass to see its sessions")
            return
        sessions = sorted((s for s in self.app.store.sessions if s.pass_id == p.id), key=lambda s: s.start)
        used = sum(s.pass_minutes for s in sessions)
        self.usage_title.configure(
            text=f"Pass usage — {p.holder_name}: {fmt_duration(used)} used, "
                 f"{fmt_duration(max(p.included_minutes - used, 0))} left of {p.hours}h")
        for s in sessions:
            self.usage.insert("", "end", iid=s.id, values=(
                fmt_range(s.start, s.end), s.device, s.players, fmt_duration(s.pass_minutes),
                fmt_money(s.total_paise)))
        if not sessions:
            self.usage.insert("", "end", values=("Not used yet", "", "", "", ""))

    def _edit_usage_session(self, event):
        row = self.usage.identify_row(event.y)
        if row and self.app.store.get(row):
            self.app.edit_session(row)
