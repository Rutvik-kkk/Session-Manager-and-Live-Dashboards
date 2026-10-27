"""Session Entry tab: create, edit, extend and update sessions."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ..formatting import (
    fmt_date,
    fmt_date_long,
    fmt_datetime,
    fmt_datetime_long,
    fmt_duration,
    fmt_money,
    fmt_range,
    fmt_time,
    now_local,
    paise_to_input,
    parse_date,
    parse_money,
    parse_time,
    local_datetime,
    to_local,
)
from ..models import (
    DEVICES,
    MAX_DURATION_MINUTES,
    PAYMENT_METHODS,
    PAYMENT_STATUSES,
    ConflictError,
    Extension,
    Session,
    ValidationError,
    add_minutes,
    build_times,
    conflict_message,
    duration_between,
    duration_minutes_problem,
    find_conflicts,
    payment_problems,
    prepare_session,
    suggest_status,
)
from ..storage import StorageError
from . import theme
from .widgets import DateEntry, ScrollableFrame, Tooltip, card

if TYPE_CHECKING:
    from .app import OnTopApp

DEFAULT_DURATION_MINUTES = 60


def bullet_list(errors: list[str]) -> str:
    return "\n".join(f"• {e}" for e in errors)


class SessionEntryTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "OnTopApp"):
        super().__init__(master)
        self.app = app
        self._syncing = False
        self._editing: Session | None = None
        self._pending: list[Extension] = []

        self.name_var = tk.StringVar()
        self.device_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.start_var = tk.StringVar()
        self.end_var = tk.StringVar()
        self.next_day_var = tk.BooleanVar(value=False)
        self.dur_h_var = tk.StringVar()
        self.dur_m_var = tk.StringVar()
        self.extend_var = tk.StringVar(value="30")
        self.method_var = tk.StringVar()
        self.total_var = tk.StringVar()
        self.paid_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.balance_var = tk.StringVar(value="—")

        self._build()

        for var in (self.date_var, self.start_var, self.end_var, self.next_day_var):
            var.trace_add("write", lambda *_: self._on_times_changed())
        for var in (self.dur_h_var, self.dur_m_var):
            var.trace_add("write", lambda *_: self._on_duration_changed())
        for var in (self.total_var, self.paid_var):
            var.trace_add("write", lambda *_: self._on_amounts_changed())
        self.status_var.trace_add("write", lambda *_: self._on_status_changed())

        self.clear_form()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self):
        scroller = ScrollableFrame(self)
        scroller.pack(fill="both", expand=True)
        body = ttk.Frame(scroller.inner, padding=(24, 18, 24, 24))
        body.pack(fill="both", expand=True)
        self.body = body

        head = ttk.Frame(body)
        head.pack(fill="x", pady=(0, 14))
        self.title_label = ttk.Label(head, text="New session", style="Title.TLabel")
        self.title_label.pack(side="left")
        self.mode_label = ttk.Label(head, text="EDITING", style="Mode.TLabel")
        self.subtitle = ttk.Label(body, style="Subtitle.TLabel", justify="left")
        self.subtitle.pack(fill="x", pady=(0, 12))

        self.columns = ttk.Frame(body)
        self.columns.pack(fill="both", expand=True)
        self.left = ttk.Frame(self.columns)
        self.right = ttk.Frame(self.columns)

        self._build_customer(self.left)
        self._build_timing(self.left)
        self._build_payment(self.right)
        self._build_extend(self.right)
        self._build_actions(body)

        self._stacked: bool | None = None
        self.columns.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        stacked = event.width < 980
        if stacked == self._stacked:
            return
        self._stacked = stacked
        self.left.grid_forget()
        self.right.grid_forget()
        if stacked:
            self.columns.columnconfigure(0, weight=1, uniform="")
            self.columns.columnconfigure(1, weight=0, uniform="")
            self.left.grid(row=0, column=0, sticky="nsew")
            self.right.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        else:
            self.columns.columnconfigure(0, weight=1, uniform="cols")
            self.columns.columnconfigure(1, weight=1, uniform="cols")
            self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            self.right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

    def _section(self, parent: tk.Misc, title: str, hint: str | None = None) -> ttk.Frame:
        outer, inner = card(parent, padding=18)
        outer.pack(fill="x", pady=(0, 16))
        ttk.Label(inner, text=title, style="CardSection.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        if hint:
            ttk.Label(inner, text=hint, style="CardSmall.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))
        inner.columnconfigure(1, weight=1)
        return inner

    def _field_label(self, parent, text: str, row: int, required: bool = False):
        label = text + (" *" if required else "")
        ttk.Label(parent, text=label, style="CardMuted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 14), pady=6)

    def _build_customer(self, parent):
        f = self._section(parent, "Customer & device")
        self._field_label(f, "Customer name", 2, True)
        self.name_entry = ttk.Entry(f, textvariable=self.name_var)
        self.name_entry.grid(row=2, column=1, columnspan=3, sticky="ew", pady=6)
        self._field_label(f, "Device", 3, True)
        self.device_combo = ttk.Combobox(f, textvariable=self.device_var, values=DEVICES, state="readonly", width=14)
        self.device_combo.grid(row=3, column=1, sticky="w", pady=6)

    def _build_timing(self, parent):
        f = self._section(parent, "Timing", "24-hour times (HH:MM) in this computer's local timezone.")
        self._field_label(f, "Session date", 2, True)
        row = ttk.Frame(f, style="Inner.TFrame")
        row.grid(row=2, column=1, columnspan=3, sticky="w", pady=6)
        self.date_entry = DateEntry(row, textvariable=self.date_var, style="Inner.TFrame")
        self.date_entry.pack(side="left")
        ttk.Button(row, text="Today", style="Small.TButton",
                   command=lambda: self.date_var.set(fmt_date(now_local().date()))).pack(side="left", padx=(8, 0))

        self._field_label(f, "Start time", 3, True)
        row = ttk.Frame(f, style="Inner.TFrame")
        row.grid(row=3, column=1, columnspan=3, sticky="w", pady=6)
        self.start_entry = ttk.Entry(row, textvariable=self.start_var, width=8)
        self.start_entry.pack(side="left")
        ttk.Button(row, text="Now", style="Small.TButton", command=self._start_now).pack(side="left", padx=(8, 0))

        self._field_label(f, "End time", 4, True)
        row = ttk.Frame(f, style="Inner.TFrame")
        row.grid(row=4, column=1, columnspan=3, sticky="w", pady=6)
        self.end_entry = ttk.Entry(row, textvariable=self.end_var, width=8)
        self.end_entry.pack(side="left")
        ttk.Checkbutton(row, text="Ends next day (past midnight)", variable=self.next_day_var,
                        style="Card.TCheckbutton").pack(side="left", padx=(14, 0))

        self._field_label(f, "Duration", 5, True)
        row = ttk.Frame(f, style="Inner.TFrame")
        row.grid(row=5, column=1, columnspan=3, sticky="w", pady=6)
        self.dur_h_spin = ttk.Spinbox(row, from_=0, to=24, increment=1, width=4, textvariable=self.dur_h_var)
        self.dur_h_spin.pack(side="left")
        ttk.Label(row, text="hours", style="CardMuted.TLabel").pack(side="left", padx=(6, 14))
        self.dur_m_spin = ttk.Spinbox(row, from_=0, to=59, increment=5, width=4, textvariable=self.dur_m_var)
        self.dur_m_spin.pack(side="left")
        ttk.Label(row, text="minutes", style="CardMuted.TLabel").pack(side="left", padx=(6, 0))

        self.span_label = ttk.Label(f, style="CardInfo.TLabel", wraplength=520, justify="left")
        self.span_label.grid(row=6, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.timing_error = ttk.Label(f, style="CardError.TLabel", wraplength=520, justify="left")
        self.timing_error.grid(row=7, column=0, columnspan=4, sticky="w", pady=(4, 0))

    def _build_payment(self, parent):
        f = self._section(parent, "Payment", "Pricing is entered manually. Amounts are in INR (₹).")
        self._field_label(f, "Payment method", 2, True)
        self.method_combo = ttk.Combobox(f, textvariable=self.method_var, values=PAYMENT_METHODS, state="readonly", width=14)
        self.method_combo.grid(row=2, column=1, sticky="w", pady=6)

        self._field_label(f, "Payment amount (₹)", 3, True)
        self.total_entry = ttk.Entry(f, textvariable=self.total_var, width=16)
        self.total_entry.grid(row=3, column=1, sticky="w", pady=6)
        ttk.Label(f, text="Total session charge", style="CardSmall.TLabel").grid(row=3, column=2, sticky="w", padx=8)

        self._field_label(f, "Amount paid (₹)", 4, True)
        self.paid_entry = ttk.Entry(f, textvariable=self.paid_var, width=16)
        self.paid_entry.grid(row=4, column=1, sticky="w", pady=6)
        ttk.Label(f, text="Actually received so far", style="CardSmall.TLabel").grid(row=4, column=2, sticky="w", padx=8)

        self._field_label(f, "Payment status", 5, True)
        self.status_combo = ttk.Combobox(f, textvariable=self.status_var, values=PAYMENT_STATUSES, state="readonly", width=16)
        self.status_combo.grid(row=5, column=1, sticky="w", pady=6)

        self._field_label(f, "Balance due", 6)
        self.balance_entry = ttk.Entry(f, textvariable=self.balance_var, width=16, state="readonly", style="Balance.TEntry")
        self.balance_entry.grid(row=6, column=1, sticky="w", pady=6)

        self.payment_msg = ttk.Label(f, style="CardMuted.TLabel", wraplength=480, justify="left")
        self.payment_msg.grid(row=7, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_extend(self, parent):
        f = self._section(
            parent,
            "Extend session",
            "Adds time to the end. The start time and payment amount stay the same.",
        )
        row = ttk.Frame(f, style="Inner.TFrame")
        row.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 4))
        ttk.Label(row, text="Minutes", style="CardMuted.TLabel").pack(side="left", padx=(0, 8))
        self.extend_entry = ttk.Entry(row, textvariable=self.extend_var, width=6)
        self.extend_entry.pack(side="left")
        self.extend_entry.bind("<Return>", lambda e: self.extend())
        ttk.Button(row, text="Extend", style="Accent.TButton", command=self.extend).pack(side="left", padx=(8, 18))
        for mins in (15, 30, 60):
            ttk.Button(row, text=f"+{mins} min", style="Chip.TButton",
                       command=lambda m=mins: self.extend(m)).pack(side="left", padx=(0, 6))

        self.extend_msg = ttk.Label(f, style="CardMuted.TLabel", wraplength=480, justify="left")
        self.extend_msg.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 8))

        ttk.Label(f, text="Extension history", style="CardMuted.TLabel").grid(row=4, column=0, columnspan=4, sticky="w")
        cols = ("when", "added", "prev", "new")
        self.history = ttk.Treeview(f, columns=cols, show="headings", height=4, selectmode="none")
        for key, text, width in (("when", "Extended at", 150), ("added", "Added", 70),
                                 ("prev", "Previous end", 140), ("new", "New end", 140)):
            self.history.heading(key, text=text)
            self.history.column(key, width=width, anchor="w", stretch=True)
        self.history.tag_configure("pending", foreground=theme.WARNING)
        self.history.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(4, 0))

    def _build_actions(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(4, 0))
        self.save_btn = ttk.Button(bar, text="Save Session", style="Accent.TButton", command=self.save)
        self.clear_btn = ttk.Button(bar, text="Clear Form", command=self._confirm_clear)
        self.update_btn = ttk.Button(bar, text="Update Session", style="Accent.TButton", command=self.update)
        self.cancel_btn = ttk.Button(bar, text="Cancel Edit", style="Danger.TButton", command=self.cancel_edit)
        self.action_bar = bar
        self.readonly_label = ttk.Label(bar, style="Error.TLabel")
        self.readonly_label.pack(side="right")
        Tooltip(self.save_btn, "Validate and save this session to data/sessions.json (Ctrl+S)")
        Tooltip(self.update_btn, "Validate and save the changes to this existing session (Ctrl+S)")
        Tooltip(self.cancel_btn, "Discard every unsaved change, including pending extensions")
        self.bind_all("<Control-s>", self._on_ctrl_s, add="+")

    def _on_ctrl_s(self, _event=None):
        if self.app.current_tab() is self:
            self.update() if self._editing else self.save()

    def _show_mode_buttons(self):
        for btn in (self.save_btn, self.clear_btn, self.update_btn, self.cancel_btn):
            btn.pack_forget()
        if self._editing:
            self.update_btn.pack(side="left")
            self.cancel_btn.pack(side="left", padx=(10, 0))
            self.mode_label.pack(side="left", padx=(14, 0), pady=(4, 0))
            self.title_label.configure(text=f"Edit session — {self._editing.customer_name}")
            ext_count = len(self._editing.extensions)
            self.subtitle.configure(
                text=(
                    f"Entry time: {fmt_datetime_long(self._editing.entry_time)}   ·   "
                    f"Last updated: {fmt_datetime_long(self._editing.last_updated)}   ·   "
                    f"{ext_count} saved extension(s)\n"
                    "Changes, including extensions, are only stored when you click Update Session."
                )
            )
        else:
            self.save_btn.pack(side="left")
            self.clear_btn.pack(side="left", padx=(10, 0))
            self.mode_label.pack_forget()
            self.title_label.configure(text="New session")
            self.subtitle.configure(text="Fields marked * are required. The session is stored only after Save Session succeeds.")
        read_only = self.app.store.read_only
        for btn in (self.save_btn, self.update_btn):
            btn.configure(state="disabled" if read_only else "normal")
        self.readonly_label.configure(
            text="Saving is disabled: the data file could not be loaded safely." if read_only else ""
        )

    # ------------------------------------------------------------------
    # Form state
    # ------------------------------------------------------------------

    def clear_form(self):
        self._editing = None
        self._pending = []
        now = now_local()
        end = add_minutes(now.replace(second=0), DEFAULT_DURATION_MINUTES)
        self._syncing = True
        try:
            self.name_var.set("")
            self.device_var.set("")
            self.date_var.set(fmt_date(now.date()))
            self.start_var.set(now.strftime("%H:%M"))
            self.end_var.set(fmt_time(end))
            self.next_day_var.set(end.date() > now.date())
            self.dur_h_var.set(str(DEFAULT_DURATION_MINUTES // 60))
            self.dur_m_var.set(str(DEFAULT_DURATION_MINUTES % 60))
            self.extend_var.set("30")
            self.method_var.set("Cash")
            self.total_var.set("")
            self.paid_var.set("0")
            self.status_var.set("")
        finally:
            self._syncing = False
        self.extend_msg.configure(text="", style="CardMuted.TLabel")
        self._recalc_from_times()
        self._refresh_payment(auto_status=True)
        self._render_history()
        self._show_mode_buttons()
        self.name_entry.focus_set()

    def _confirm_clear(self):
        if self.name_var.get().strip() or self.total_var.get().strip():
            if not messagebox.askyesno("Clear form", "Clear all fields in this form?", parent=self):
                return
        self.clear_form()

    def is_editing(self) -> bool:
        return self._editing is not None

    def load_session(self, session_id: str) -> bool:
        session = self.app.store.get(session_id)
        if session is None:
            messagebox.showerror("Session not found", "That session no longer exists.", parent=self)
            return False
        if self._editing and self._editing.id != session_id:
            if not messagebox.askyesno(
                "Discard current edit?",
                f"You are editing {self._editing.customer_name}'s session. Discard those unsaved changes "
                f"and edit {session.customer_name}'s session instead?",
                parent=self,
            ):
                return False
        self._editing = session
        self._pending = []
        start, end = to_local(session.start), to_local(session.end)
        self._syncing = True
        try:
            self.name_var.set(session.customer_name)
            self.device_var.set(session.device)
            self.date_var.set(fmt_date(start.date()))
            self.start_var.set(start.strftime("%H:%M"))
            self.end_var.set(end.strftime("%H:%M"))
            self.next_day_var.set(end.date() > start.date())
            self.dur_h_var.set(str(session.duration_minutes // 60))
            self.dur_m_var.set(str(session.duration_minutes % 60))
            self.method_var.set(session.payment_method)
            self.total_var.set(paise_to_input(session.total_paise))
            self.paid_var.set(paise_to_input(session.paid_paise))
            self.status_var.set(session.payment_status)
        finally:
            self._syncing = False
        self.extend_msg.configure(text="", style="CardMuted.TLabel")
        self._recalc_from_times()
        self._refresh_payment(auto_status=False)
        self._render_history()
        self._show_mode_buttons()
        self.name_entry.focus_set()
        return True

    def cancel_edit(self):
        name = self._editing.customer_name if self._editing else ""
        self.clear_form()
        self.app.set_status(f"Edit cancelled — no changes were saved to {name}'s session.")

    # ------------------------------------------------------------------
    # Linked time / duration fields
    # ------------------------------------------------------------------

    def _start_now(self):
        self.date_var.set(fmt_date(now_local().date()))
        self.start_var.set(now_local().strftime("%H:%M"))

    def _on_times_changed(self):
        if not self._syncing:
            self._recalc_from_times()

    def _on_duration_changed(self):
        if not self._syncing:
            self._recalc_from_duration()

    def _set_timing_error(self, text: str):
        self.timing_error.configure(text=text)
        if text:
            self.span_label.configure(text="")

    def _show_span(self, start, end):
        minutes = duration_between(start, end)
        s, e = to_local(start), to_local(end)
        text = f"{fmt_date_long(s.date())} {s:%H:%M}  →  "
        if e.date() > s.date():
            text += f"{fmt_date_long(e.date())} {e:%H:%M}   ·   ends on the following date"
        else:
            text += f"{e:%H:%M}"
        text += f"   ·   {fmt_duration(minutes)}"
        self.span_label.configure(text=text)
        self.timing_error.configure(text="")

    def _recalc_from_times(self):
        try:
            start, end = build_times(self.date_var.get(), self.start_var.get(), self.end_var.get(),
                                     self.next_day_var.get())
        except ValidationError as exc:
            self._set_timing_error(" ".join(exc.errors))
            return
        minutes = duration_between(start, end)
        self._syncing = True
        try:
            self.dur_h_var.set(str(minutes // 60))
            self.dur_m_var.set(str(minutes % 60))
        finally:
            self._syncing = False
        self._show_span(start, end)

    def _parse_duration(self) -> int:
        try:
            hours = int(self.dur_h_var.get().strip() or "0")
            mins = int(self.dur_m_var.get().strip() or "0")
        except ValueError:
            raise ValueError("Duration hours and minutes must be whole numbers.") from None
        if hours < 0 or mins < 0:
            raise ValueError("Duration cannot be negative.")
        if mins > 59:
            raise ValueError("Duration minutes must be between 0 and 59.")
        total = hours * 60 + mins
        problem = duration_minutes_problem(total)
        if problem:
            raise ValueError(problem)
        return total

    def _recalc_from_duration(self):
        try:
            session_date = parse_date(self.date_var.get(), "Session date")
            start = local_datetime(session_date, parse_time(self.start_var.get(), "Start time"))
            minutes = self._parse_duration()
        except ValueError as exc:
            self._set_timing_error(str(exc))
            return
        end = add_minutes(start, minutes)
        self._syncing = True
        try:
            self.end_var.set(end.strftime("%H:%M"))
            self.next_day_var.set(end.date() > session_date)
        finally:
            self._syncing = False
        self._show_span(start, end)

    def _current_times(self):
        return build_times(self.date_var.get(), self.start_var.get(), self.end_var.get(), self.next_day_var.get())

    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------

    def extend(self, minutes: int | None = None):
        def fail(title: str, text: str):
            self.extend_msg.configure(text=text, style="CardError.TLabel")
            messagebox.showerror(title, text, parent=self)

        if minutes is None:
            raw = self.extend_var.get().strip()
            if not raw.isdigit() or int(raw) <= 0:
                fail("Invalid extension", "Enter the number of minutes to add as a whole number greater than zero.")
                return
            minutes = int(raw)
        if minutes > MAX_DURATION_MINUTES:
            fail("Invalid extension", "An extension cannot add more than 24 hours.")
            return
        try:
            start, end = self._current_times()
        except ValidationError as exc:
            fail("Fix the session times first", bullet_list(exc.errors))
            return
        device = self.device_var.get()
        if device not in DEVICES:
            fail("Select a device", "Select a device first so its availability can be checked.")
            return
        new_end = add_minutes(end, minutes)
        new_minutes = duration_between(start, new_end)
        if new_minutes > MAX_DURATION_MINUTES:
            fail(
                "Extension too long",
                f"Adding {minutes} min would make the session {fmt_duration(new_minutes)} long. "
                "Sessions can be at most 24 hours.",
            )
            return
        exclude = self._editing.id if self._editing else None
        conflicts = find_conflicts(self.app.store.sessions, device, start, new_end, exclude_id=exclude)
        if conflicts:
            fail("Device unavailable", conflict_message(device, conflicts))
            return

        session_date = to_local(start).date()
        local_new_end = to_local(new_end)
        self._syncing = True
        try:
            self.end_var.set(local_new_end.strftime("%H:%M"))
            self.next_day_var.set(local_new_end.date() > session_date)
            self.dur_h_var.set(str(new_minutes // 60))
            self.dur_m_var.set(str(new_minutes % 60))
        finally:
            self._syncing = False
        self._show_span(start, new_end)

        if self._editing:
            self._pending.append(Extension(now_local(), minutes, end, new_end))
            self._render_history()
            action = "Click Update Session to save it, or Cancel Edit to discard."
        else:
            action = "This is a new session, so the time is simply added before its first save."
        self.extend_msg.configure(
            text=f"Extended by {minutes} min — new end {fmt_datetime(new_end)} "
                 f"({fmt_duration(new_minutes)} total). {action}",
            style="CardOk.TLabel",
        )

    def _render_history(self):
        self.history.delete(*self.history.get_children())
        saved = self._editing.extensions if self._editing else []
        for ext in saved:
            self.history.insert("", "end", values=(fmt_datetime(ext.extended_at), f"+{ext.minutes_added}m",
                                                   fmt_datetime(ext.previous_end), fmt_datetime(ext.new_end)))
        for ext in self._pending:
            self.history.insert("", "end", tags=("pending",),
                                values=(fmt_datetime(ext.extended_at) + "  (unsaved)", f"+{ext.minutes_added}m",
                                        fmt_datetime(ext.previous_end), fmt_datetime(ext.new_end)))
        if not saved and not self._pending:
            self.history.insert("", "end", values=("No extensions yet", "", "", ""))

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------

    def _on_amounts_changed(self):
        if not self._syncing:
            self._refresh_payment(auto_status=True)

    def _on_status_changed(self):
        if not self._syncing:
            self._refresh_payment(auto_status=False)

    def _refresh_payment(self, auto_status: bool):
        def message(text: str, style: str = "CardMuted.TLabel"):
            self.payment_msg.configure(text=text, style=style)

        total_text, paid_text = self.total_var.get(), self.paid_var.get()
        if not total_text.strip():
            self.balance_var.set("—")
            message("Enter the total session charge.")
            return
        try:
            total = parse_money(total_text, "Payment amount")
            paid = parse_money(paid_text, "Amount paid") if paid_text.strip() else None
        except ValueError as exc:
            self.balance_var.set("—")
            message(str(exc), "CardError.TLabel")
            return
        if paid is None:
            self.balance_var.set("—")
            message("Enter the amount received (0 if nothing has been paid yet).", "CardWarn.TLabel")
            return
        if paid > total:
            self.balance_var.set("—")
            message(f"Amount paid ({fmt_money(paid)}) cannot exceed the total charge ({fmt_money(total)}).",
                    "CardError.TLabel")
            return
        self.balance_var.set(fmt_money(total - paid))
        suggested = suggest_status(total, paid)
        if auto_status and self.status_var.get() != suggested:
            self._syncing = True
            try:
                self.status_var.set(suggested)
            finally:
                self._syncing = False
        problems = payment_problems(total, paid, self.status_var.get())
        if problems:
            message(problems[0], "CardError.TLabel")
        else:
            message(f"Status '{suggested}' matches the amounts.", "CardOk.TLabel")

    # ------------------------------------------------------------------
    # Save / update
    # ------------------------------------------------------------------

    def _build_session(self) -> Session:
        return prepare_session(
            customer_name=self.name_var.get(),
            device=self.device_var.get(),
            date_text=self.date_var.get(),
            start_text=self.start_var.get(),
            end_text=self.end_var.get(),
            ends_next_day=self.next_day_var.get(),
            payment_method=self.method_var.get(),
            total_text=self.total_var.get(),
            paid_text=self.paid_var.get(),
            payment_status=self.status_var.get(),
            now=now_local(),
            existing=self._editing,
            new_extensions=self._pending,
        )

    def _persist(self, updating: bool) -> Session | None:
        store = self.app.store
        if store.read_only:
            messagebox.showerror("Saving disabled", store.load_error or "The data file could not be loaded.", parent=self)
            return None
        try:
            session = self._build_session()
            if updating:
                store.update(session)
            else:
                store.add(session)
        except ConflictError as exc:
            messagebox.showerror("Device unavailable", str(exc), parent=self)
            return None
        except ValidationError as exc:
            messagebox.showerror("Please fix the following", bullet_list(exc.errors), parent=self)
            return None
        except StorageError as exc:
            messagebox.showerror(
                "Could not save",
                f"{exc}\n\nNothing was changed and your entries are still in the form, so you can try again.",
                parent=self,
            )
            return None
        return session

    def save(self):
        if self._editing:
            self.update()
            return
        session = self._persist(updating=False)
        if session is None:
            return
        self.clear_form()
        self.app.data_changed()
        self.app.set_status(f"Saved {session.customer_name} on {session.device}.")
        messagebox.showinfo(
            "Session saved",
            f"Saved session for {session.customer_name} on {session.device}\n"
            f"{fmt_range(session.start, session.end)} ({fmt_duration(session.duration_minutes)})\n"
            f"Charge {fmt_money(session.total_paise)} · Paid {fmt_money(session.paid_paise)} · "
            f"{session.payment_status}",
            parent=self,
        )

    def update(self):
        if not self._editing:
            self.save()
            return
        added = sum(e.minutes_added for e in self._pending)
        session = self._persist(updating=True)
        if session is None:
            return
        self.clear_form()
        self.app.data_changed()
        self.app.set_status(f"Updated {session.customer_name}'s session.")
        extra = f"\nIncludes {added} min of new extensions." if added else ""
        messagebox.showinfo(
            "Session updated",
            f"Updated {session.customer_name}'s session on {session.device}\n"
            f"{fmt_range(session.start, session.end)} ({fmt_duration(session.duration_minutes)})\n"
            f"Charge {fmt_money(session.total_paise)} · Paid {fmt_money(session.paid_paise)} · "
            f"{session.payment_status}{extra}",
            parent=self,
        )
