"""Session Entry tab: create, edit, extend and update sessions."""

from __future__ import annotations

import tkinter as tk
from datetime import timedelta
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from ..config import CLOSING_TIME, DEVICES, OPENING_TIME, PLAYER_COUNTS
from ..formatting import (
    fmt_date,
    fmt_date_long,
    fmt_datetime,
    fmt_datetime_long,
    fmt_duration,
    fmt_money,
    fmt_range,
    local_datetime,
    now_local,
    paise_to_input,
    parse_date,
    parse_money,
    parse_time,
    to_local,
)
from ..models import (
    MAX_NOTES_LENGTH,
    PAYMENT_METHODS,
    PAYMENT_STATUSES,
    ConflictError,
    Extension,
    MonthlyPass,
    Session,
    ValidationError,
    active_pass_for_phone,
    add_minutes,
    build_times,
    conflict_message,
    duration_between,
    duration_minutes_problem,
    find_conflicts,
    fmt_phone,
    max_minutes_until_close,
    normalise_notes,
    normalise_phone,
    opening_hours_text,
    pass_session_problems,
    payment_problems,
    prepare_session,
    suggest_status,
)
from ..pricing import billable_minutes, charge_explanation, players_problem, suggested_charge
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
        self._pass: MonthlyPass | None = None
        self._amount_auto = True

        self.pass_var = tk.BooleanVar(value=False)
        self.phone_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.device_var = tk.StringVar()
        self.players_var = tk.StringVar(value="1")
        self.date_var = tk.StringVar()
        self.start_var = tk.StringVar()
        self.end_var = tk.StringVar()
        self.dur_h_var = tk.StringVar()
        self.dur_m_var = tk.StringVar()
        self.extend_var = tk.StringVar(value="30")
        self.method_var = tk.StringVar()
        self.total_var = tk.StringVar()
        self.paid_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.balance_var = tk.StringVar(value="—")

        self._build()

        for var in (self.date_var, self.start_var, self.end_var):
            var.trace_add("write", lambda *_: self._on_times_changed())
        for var in (self.dur_h_var, self.dur_m_var):
            var.trace_add("write", lambda *_: self._on_duration_changed())
        for var in (self.device_var, self.players_var):
            var.trace_add("write", lambda *_: self._on_pricing_input_changed())
        for var in (self.pass_var, self.phone_var):
            var.trace_add("write", lambda *_: self._on_pass_input_changed())
        self.total_var.trace_add("write", lambda *_: self._on_total_typed())
        self.paid_var.trace_add("write", lambda *_: self._on_amounts_changed())
        self.status_var.trace_add("write", lambda *_: self._on_status_changed())

        self.clear_form()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self):
        scroller = ScrollableFrame(self)
        scroller.pack(fill="both", expand=True)
        body = ttk.Frame(scroller.inner, padding=(24, 10, 24, 12))
        body.pack(fill="both", expand=True)
        self.body = body

        head = ttk.Frame(body)
        head.pack(fill="x", pady=(0, 4))
        self.title_label = ttk.Label(head, text="New session", style="Title.TLabel")
        self.title_label.pack(side="left")
        self.mode_label = ttk.Label(head, text="EDITING", style="Mode.TLabel")
        self._build_actions(head)
        self.subtitle = ttk.Label(body, style="Subtitle.TLabel", justify="left")
        self.subtitle.pack(fill="x", pady=(0, 10))

        self.columns = ttk.Frame(body)
        self.columns.pack(fill="both", expand=True)
        self.left = ttk.Frame(self.columns)
        self.right = ttk.Frame(self.columns)

        self._build_customer(self.left)
        self._build_timing(self.left)
        self._build_payment(self.right)
        self._build_extend(self.right)

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
        outer, inner = card(parent, padding=(18, 12))
        outer.pack(fill="x", pady=(0, 12))
        ttk.Label(inner, text=title, style="CardSection.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        if hint:
            ttk.Label(inner, text=hint, style="CardSmall.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 0))
        inner.columnconfigure(3, weight=1)
        return inner

    def _field_label(self, parent, text: str, row: int, required: bool = False):
        label = text + (" *" if required else "")
        ttk.Label(parent, text=label, style="CardMuted.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 14), pady=4)

    def _build_customer(self, parent):
        f = self._section(parent, "Customer & device")
        ttk.Checkbutton(f, text="Monthly pass holder (time comes off their pass)", variable=self.pass_var,
                        style="Card.TCheckbutton").grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 2))
        self.phone_label = ttk.Label(f, text="Pass phone no. *", style="CardMuted.TLabel")
        self.phone_label.grid(row=3, column=0, sticky="w", padx=(0, 14), pady=4)
        row = ttk.Frame(f, style="Inner.TFrame")
        row.grid(row=3, column=1, columnspan=3, sticky="w", pady=4)
        self.phone_entry = ttk.Entry(row, textvariable=self.phone_var, width=16)
        self.phone_entry.pack(side="left")
        self.register_pass_btn = ttk.Button(row, text="Register new pass", style="Small.TButton",
                                            command=self._register_pass)
        self.register_pass_btn.pack(side="left", padx=(8, 0))
        self.pass_info = ttk.Label(f, style="CardMuted.TLabel", wraplength=520, justify="left")
        self.pass_info.grid(row=4, column=0, columnspan=4, sticky="w", pady=(0, 4))

        self._field_label(f, "Customer name", 5, True)
        self.name_entry = ttk.Entry(f, textvariable=self.name_var)
        self.name_entry.grid(row=5, column=1, columnspan=3, sticky="ew", pady=4)
        self._field_label(f, "Device", 6, True)
        self.device_combo = ttk.Combobox(f, textvariable=self.device_var, values=DEVICES, state="readonly", width=14)
        self.device_combo.grid(row=6, column=1, sticky="w", pady=4)
        self._field_label(f, "No. of players", 7, True)
        self.players_combo = ttk.Combobox(f, textvariable=self.players_var, values=[str(n) for n in PLAYER_COUNTS],
                                          state="readonly", width=6)
        self.players_combo.grid(row=7, column=1, sticky="w", pady=4)
        ttk.Label(f, text="2–4 players: minimum 1 hour", style="CardSmall.TLabel").grid(
            row=7, column=2, columnspan=2, sticky="w", padx=8)
        self._build_notes(f, 8)

    def _build_timing(self, parent):
        f = self._section(parent, "Timing",
                          f"Open {opening_hours_text()} · 24-hour times (HH:MM) in this computer's local timezone.")
        self._field_label(f, "Session date", 2, True)
        row = ttk.Frame(f, style="Inner.TFrame")
        row.grid(row=2, column=1, columnspan=3, sticky="w", pady=4)
        self.date_entry = DateEntry(row, textvariable=self.date_var, style="Inner.TFrame")
        self.date_entry.pack(side="left")
        ttk.Button(row, text="Today", style="Small.TButton",
                   command=lambda: self.date_var.set(fmt_date(now_local().date()))).pack(side="left", padx=(8, 0))

        self._field_label(f, "Start time", 3, True)
        row = ttk.Frame(f, style="Inner.TFrame")
        row.grid(row=3, column=1, columnspan=3, sticky="w", pady=4)
        self.start_entry = ttk.Entry(row, textvariable=self.start_var, width=8)
        self.start_entry.pack(side="left")
        ttk.Button(row, text="Now", style="Small.TButton", command=self._start_now).pack(side="left", padx=(8, 0))

        self._field_label(f, "End time", 4, True)
        self.end_entry = ttk.Entry(f, textvariable=self.end_var, width=8)
        self.end_entry.grid(row=4, column=1, sticky="w", pady=4)

        self._field_label(f, "Duration", 5, True)
        row = ttk.Frame(f, style="Inner.TFrame")
        row.grid(row=5, column=1, columnspan=3, sticky="w", pady=4)
        for var, unit, step in ((self.dur_h_var, "hours", 60), (self.dur_m_var, "minutes", 30)):
            ttk.Button(row, text="−", width=3, takefocus=False,
                       command=lambda s=-step: self._step_duration(s)).pack(side="left")
            ttk.Entry(row, textvariable=var, width=4, justify="center").pack(side="left", padx=4)
            ttk.Button(row, text="+", width=3, takefocus=False,
                       command=lambda s=step: self._step_duration(s)).pack(side="left")
            ttk.Label(row, text=unit, style="CardMuted.TLabel").pack(side="left", padx=(6, 18))
        Tooltip(row, "− / + change the duration by 1 hour (hours) or 30 minutes (minutes). You can also type.")

        self.span_label = ttk.Label(f, style="CardInfo.TLabel", wraplength=520, justify="left")
        self.span_label.grid(row=6, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.timing_error = ttk.Label(f, style="CardError.TLabel", wraplength=520, justify="left")
        self.timing_error.grid(row=7, column=0, columnspan=4, sticky="w", pady=(4, 0))

    def _build_notes(self, f: ttk.Frame, row: int):
        self._field_label(f, "Note", row)
        self.notes_text = tk.Text(
            f, height=2, width=10, wrap="word", undo=True, font=theme.FONTS["base"],
            background=theme.SURFACE_2, foreground=theme.TEXT, insertbackground=theme.TEXT,
            selectbackground=theme.ACCENT_DIM, selectforeground=theme.TEXT, relief="flat",
            highlightthickness=1, highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT,
            padx=8, pady=4,
        )
        self.notes_text.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        Tooltip(self.notes_text, "Optional — anything worth remembering about this session.")
        self.notes_count = ttk.Label(f, style="CardSmall.TLabel")
        self.notes_count.grid(row=row + 1, column=0, columnspan=4, sticky="e")
        self.notes_text.bind("<<Modified>>", self._on_notes_modified)
        self.notes_text.bind("<Tab>", self._focus_next)
        self.notes_text.bind("<Shift-Tab>", self._focus_prev)

    @staticmethod
    def _focus_next(event):
        event.widget.tk_focusNext().focus_set()
        return "break"

    @staticmethod
    def _focus_prev(event):
        event.widget.tk_focusPrev().focus_set()
        return "break"

    def _on_notes_modified(self, _event=None):
        self.notes_text.edit_modified(False)
        length = len(normalise_notes(self.notes_text.get("1.0", "end-1c")))
        over = length > MAX_NOTES_LENGTH
        self.notes_count.configure(text=f"{length}/{MAX_NOTES_LENGTH}",
                                   style="CardError.TLabel" if over else "CardSmall.TLabel")

    def _notes(self) -> str:
        return self.notes_text.get("1.0", "end-1c")

    def _set_notes(self, text: str):
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", text)
        self.notes_text.edit_reset()
        self._on_notes_modified()

    def _build_payment(self, parent):
        f = self._section(parent, "Payment",
                          "The amount is filled in from the price list. You can change it; amounts are in INR (₹).")
        self._field_label(f, "Payment method", 2, True)
        self.method_combo = ttk.Combobox(f, textvariable=self.method_var, values=PAYMENT_METHODS, state="readonly", width=14)
        self.method_combo.grid(row=2, column=1, sticky="w", pady=4)

        self._field_label(f, "Payment amount (₹)", 3, True)
        self.total_entry = ttk.Entry(f, textvariable=self.total_var, width=16)
        self.total_entry.grid(row=3, column=1, sticky="w", pady=4)
        self.use_price_btn = ttk.Button(f, text="Use price list", style="Small.TButton", command=self.use_price_list)
        self.use_price_btn.grid(row=3, column=2, sticky="w", padx=8)
        Tooltip(self.use_price_btn, "Replace the amount with the price-list charge and keep it updated automatically.")
        self.price_label = ttk.Label(f, style="CardSmall.TLabel", wraplength=480, justify="left")
        self.price_label.grid(row=4, column=1, columnspan=3, sticky="w", pady=(0, 4))

        self._field_label(f, "Amount paid (₹)", 5, True)
        self.paid_entry = ttk.Entry(f, textvariable=self.paid_var, width=16)
        self.paid_entry.grid(row=5, column=1, sticky="w", pady=4)
        ttk.Button(f, text="Paid in full", style="Small.TButton",
                   command=lambda: self.paid_var.set(self.total_var.get())).grid(row=5, column=2, sticky="w", padx=8)

        self._field_label(f, "Payment status", 6, True)
        self.status_combo = ttk.Combobox(f, textvariable=self.status_var, values=PAYMENT_STATUSES, state="readonly", width=16)
        self.status_combo.grid(row=6, column=1, sticky="w", pady=4)

        self._field_label(f, "Balance due", 7)
        self.balance_entry = ttk.Entry(f, textvariable=self.balance_var, width=16, state="readonly", style="Balance.TEntry")
        self.balance_entry.grid(row=7, column=1, sticky="w", pady=4)

        self.payment_msg = ttk.Label(f, style="CardMuted.TLabel", wraplength=480, justify="left")
        self.payment_msg.grid(row=8, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_extend(self, parent):
        f = self._section(
            parent,
            "Extend session",
            "Adds time to the end, up to closing time. The start time stays the same; the amount follows the "
            "price list unless you changed it by hand.",
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
        self.history = ttk.Treeview(f, columns=cols, show="headings", height=3, selectmode="none")
        for key, text, width in (("when", "Extended at", 150), ("added", "Added", 70),
                                 ("prev", "Previous end", 140), ("new", "New end", 140)):
            self.history.heading(key, text=text)
            self.history.column(key, width=width, anchor="w", stretch=True)
        self.history.tag_configure("pending", foreground=theme.WARNING)
        self.history.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(4, 0))

    def _build_actions(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(side="right")
        self.save_btn = ttk.Button(bar, text="Save Session", style="Accent.TButton", command=self.save)
        self.clear_btn = ttk.Button(bar, text="Clear Form", command=self._confirm_clear)
        self.update_btn = ttk.Button(bar, text="Update Session", style="Accent.TButton", command=self.update)
        self.cancel_btn = ttk.Button(bar, text="Cancel Edit", style="Danger.TButton", command=self.cancel_edit)
        self.action_bar = bar
        self.readonly_label = ttk.Label(bar, style="Error.TLabel")
        self.readonly_label.pack(side="left", padx=(0, 12))
        Tooltip(self.save_btn, "Validate and save this session (Ctrl+S)")
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

    @staticmethod
    def _default_start():
        now = now_local().replace(second=0)
        today = now.date()
        opening = local_datetime(today, OPENING_TIME)
        closing = local_datetime(today, CLOSING_TIME)
        if now < opening:
            return opening
        if now > closing - timedelta(minutes=30):
            return local_datetime(today + timedelta(days=1), OPENING_TIME)
        return now

    def clear_form(self):
        self._editing = None
        self._pending = []
        self._pass = None
        self._amount_auto = True
        start = self._default_start()
        minutes = min(DEFAULT_DURATION_MINUTES, max_minutes_until_close(start))
        end = add_minutes(start, minutes)
        self._syncing = True
        try:
            self.pass_var.set(False)
            self.phone_var.set("")
            self.name_var.set("")
            self.device_var.set("")
            self.players_var.set("1")
            self.date_var.set(fmt_date(start.date()))
            self.start_var.set(start.strftime("%H:%M"))
            self.end_var.set(end.strftime("%H:%M"))
            self.dur_h_var.set(str(minutes // 60))
            self.dur_m_var.set(str(minutes % 60))
            self.extend_var.set("30")
            self.method_var.set("Cash")
            self.total_var.set("")
            self.paid_var.set("0")
            self.status_var.set("")
        finally:
            self._syncing = False
        self._set_notes("")
        self.extend_msg.configure(text="", style="CardMuted.TLabel")
        self._recalc_from_times()
        self._render_history()
        self._show_mode_buttons()
        self.name_entry.focus_set()

    def _confirm_clear(self):
        if self.name_var.get().strip() or self.phone_var.get().strip() or self._notes().strip():
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
        self._pass = self.app.store.get_pass(session.pass_id)
        on_pass = self._pass is not None
        self._amount_auto = session.total_paise == suggested_charge(
            session.device, session.players, session.duration_minutes, on_pass)
        start, end = to_local(session.start), to_local(session.end)
        self._syncing = True
        try:
            self.pass_var.set(on_pass)
            self.phone_var.set(fmt_phone(self._pass.phone) if self._pass else "")
            self.name_var.set(session.customer_name)
            self.device_var.set(session.device)
            self.players_var.set(str(session.players))
            self.date_var.set(fmt_date(start.date()))
            self.start_var.set(start.strftime("%H:%M"))
            self.end_var.set(end.strftime("%H:%M"))
            self.dur_h_var.set(str(session.duration_minutes // 60))
            self.dur_m_var.set(str(session.duration_minutes % 60))
            self.method_var.set(session.payment_method)
            self.total_var.set(paise_to_input(session.total_paise))
            self.paid_var.set(paise_to_input(session.paid_paise))
            self.status_var.set(session.payment_status)
        finally:
            self._syncing = False
        self._set_notes(session.notes)
        self.extend_msg.configure(text="", style="CardMuted.TLabel")
        try:
            span = self._current_times()
        except ValidationError:
            span = None
        if span:
            self._show_span(*span)
        else:
            self.span_label.configure(text=f"{fmt_range(session.start, session.end)} · "
                                           f"{fmt_duration(session.duration_minutes)} (saved before current rules)")
            self.timing_error.configure(text="")
        self._resolve_pass(auto_amount=False)
        self._refresh_payment(auto_status=False)
        self._render_history()
        self._show_mode_buttons()
        self.name_entry.focus_set()
        return True

    def cancel_edit(self):
        name = self._editing.customer_name if self._editing else ""
        self.clear_form()
        self.app.set_status(f"Edit cancelled — no changes were saved to {name}'s session.")

    def start_with_pass(self, p: MonthlyPass):
        """Prepare a new session for a pass holder (used from the Monthly Passes tab)."""
        if self._editing and not messagebox.askyesno(
            "Discard current edit?", "Discard the session you are editing and start a new pass session?",
            parent=self,
        ):
            return False
        if self._editing:
            self.clear_form()
        self.pass_var.set(True)
        self.phone_var.set(fmt_phone(p.phone))
        return True

    def refresh_pass(self):
        """Re-check the pass after passes or sessions change elsewhere."""
        if self.pass_var.get():
            self._resolve_pass(auto_amount=True)

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

    def _step_duration(self, delta: int):
        try:
            minutes = self._parse_duration()
        except ValueError:
            minutes = 0
        longest = (CLOSING_TIME.hour - OPENING_TIME.hour) * 60
        minutes = max(0, min(minutes + delta, longest))
        self._syncing = True
        try:
            self.dur_h_var.set(str(minutes // 60))
            self.dur_m_var.set(str(minutes % 60))
        finally:
            self._syncing = False
        self._recalc_from_duration()

    def _set_timing_error(self, text: str):
        self.timing_error.configure(text=text)
        if text:
            self.span_label.configure(text="")

    def _show_span(self, start, end):
        minutes = duration_between(start, end)
        s, e = to_local(start), to_local(end)
        billed = billable_minutes(minutes)
        text = f"{fmt_date_long(s.date())}   {s:%H:%M} → {e:%H:%M}   ·   {fmt_duration(minutes)}"
        if billed != minutes:
            text += f" (billed as {fmt_duration(billed)})"
        self.span_label.configure(text=text)
        self.timing_error.configure(text="")

    def _after_timing_change(self):
        self._resolve_pass(auto_amount=True)

    def _recalc_from_times(self):
        try:
            start, end = self._current_times()
        except ValidationError as exc:
            self._set_timing_error(" ".join(exc.errors))
            self._after_timing_change()
            return
        minutes = duration_between(start, end)
        self._syncing = True
        try:
            self.dur_h_var.set(str(minutes // 60))
            self.dur_m_var.set(str(minutes % 60))
        finally:
            self._syncing = False
        self._show_span(start, end)
        self._after_timing_change()

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
        return hours * 60 + mins

    def _recalc_from_duration(self):
        try:
            session_date = parse_date(self.date_var.get(), "Session date")
            start = local_datetime(session_date, parse_time(self.start_var.get(), "Start time"))
            minutes = self._parse_duration()
            problem = duration_minutes_problem(minutes, start)
            if problem:
                raise ValueError(problem)
        except ValueError as exc:
            self._set_timing_error(str(exc))
            self._after_timing_change()
            return
        end = add_minutes(start, minutes)
        self._syncing = True
        try:
            self.end_var.set(end.strftime("%H:%M"))
        finally:
            self._syncing = False
        self._recalc_from_times()

    def _current_times(self):
        return build_times(self.date_var.get(), self.start_var.get(), self.end_var.get())

    def _current_minutes(self) -> int | None:
        try:
            start, end = self._current_times()
        except ValidationError:
            return None
        return duration_between(start, end)

    def _players(self) -> int | None:
        try:
            return int(self.players_var.get())
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Monthly pass
    # ------------------------------------------------------------------

    def _on_pass_input_changed(self):
        if not self._syncing:
            self._resolve_pass(auto_amount=True)

    def _register_pass(self):
        self.app.open_pass_registration(phone=self.phone_var.get(), name=self.name_var.get())

    def _pass_used_by_others(self, p: MonthlyPass) -> int:
        return self.app.store.pass_used_minutes(p.id, self._editing.id if self._editing else None)

    def _resolve_pass(self, auto_amount: bool):
        on = self.pass_var.get()
        state = "normal" if on else "disabled"
        self.phone_entry.configure(state=state)
        self.register_pass_btn.configure(state=state)
        if not on:
            self._pass = None
            self.pass_info.configure(text="")
            self.name_entry.configure(state="normal")
            self._update_price(auto_amount)
            return

        def info(text: str, style: str = "CardMuted.TLabel"):
            self.pass_info.configure(text=text, style=style)

        phone = normalise_phone(self.phone_var.get())
        if len(phone) != 10:
            self._pass = None
            self.name_entry.configure(state="normal")
            info("Enter the pass holder's 10-digit phone number.", "CardWarn.TLabel")
            self._update_price(auto_amount)
            return
        try:
            session_date = parse_date(self.date_var.get())
        except ValueError:
            session_date = now_local().date()
        store = self.app.store
        exclude = self._editing.id if self._editing else None
        found = None
        if self._editing and self._editing.pass_id:
            original = store.get_pass(self._editing.pass_id)
            if original and original.phone == phone:
                found = original
        found = found or active_pass_for_phone(store.passes, store.sessions, phone, session_date, exclude)
        self._pass = found
        if found is None:
            self.name_entry.configure(state="normal")
            info(f"No monthly pass for {fmt_phone(phone)} is valid on {fmt_date_long(session_date)}. "
                 "Check the number or use 'Register new pass'.", "CardError.TLabel")
            self._update_price(auto_amount)
            return

        self._syncing = True
        try:
            self.name_var.set(found.holder_name)
        finally:
            self._syncing = False
        self.name_entry.configure(state="readonly")
        left = found.included_minutes - self._pass_used_by_others(found)
        text = (f"✓ {found.holder_name}'s pass · {fmt_duration(max(left, 0))} left of {found.hours}h · "
                f"valid {fmt_date_long(found.purchased_on)} – {fmt_date_long(found.valid_until)}")
        minutes = self._current_minutes()
        style = "CardOk.TLabel"
        if minutes is not None:
            need = billable_minutes(minutes)
            problems = pass_session_problems(found, session_date, need, found.included_minutes - left)
            if problems:
                text += "\n" + " ".join(problems)
                style = "CardError.TLabel"
            else:
                text += f"\nThis session uses {fmt_duration(need)}; {fmt_duration(left - need)} will remain."
        info(text, style)
        self._update_price(auto_amount)

    # ------------------------------------------------------------------
    # Price list
    # ------------------------------------------------------------------

    def _on_pricing_input_changed(self):
        if not self._syncing:
            self._update_price(auto_amount=True)

    def _on_total_typed(self):
        if self._syncing:
            return
        self._amount_auto = False
        self._update_price(auto_amount=False)
        self._refresh_payment(auto_status=True)

    def use_price_list(self):
        self._amount_auto = True
        self._update_price(auto_amount=True)

    def _suggestion(self) -> tuple[int | None, str]:
        device, players, minutes = self.device_var.get(), self._players(), self._current_minutes()
        if device not in DEVICES:
            return None, "Select a device to see the price-list amount."
        if minutes is None:
            return None, "Enter valid times to see the price-list amount."
        problem = players_problem(players, minutes)
        if problem:
            return None, problem
        on_pass = self._pass is not None and self.pass_var.get()
        amount = suggested_charge(device, players, minutes, on_pass)
        return amount, charge_explanation(device, players, minutes, on_pass)

    def _update_price(self, auto_amount: bool):
        amount, explanation = self._suggestion()
        if amount is None:
            self.price_label.configure(text=explanation, style="CardWarn.TLabel")
            self._refresh_payment(auto_status=True)
            return
        if self._amount_auto and auto_amount and self.total_var.get() != paise_to_input(amount):
            self._syncing = True
            try:
                self.total_var.set(paise_to_input(amount))
            finally:
                self._syncing = False
        try:
            matches = parse_money(self.total_var.get()) == amount
        except ValueError:
            matches = False
        if matches:
            text, style = f"Price list: {fmt_money(amount)} — {explanation}", "CardSmall.TLabel"
        else:
            text = (f"Edited by hand. Price list would be {fmt_money(amount)} — {explanation}. "
                    "Click 'Use price list' to switch back.")
            style = "CardWarn.TLabel"
        self.price_label.configure(text=text, style=style)
        self._refresh_payment(auto_status=True)

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
        if new_minutes > max_minutes_until_close(start):
            fail(
                "Past closing time",
                f"Adding {minutes} min would end the session at {to_local(new_end):%H:%M}, after closing time "
                f"({CLOSING_TIME:%H:%M}). The latest it can be extended to is {CLOSING_TIME:%H:%M}.",
            )
            return
        if self.pass_var.get() and self._pass is not None:
            problems = pass_session_problems(self._pass, to_local(start).date(), billable_minutes(new_minutes),
                                             self._pass_used_by_others(self._pass))
            if problems:
                fail("Not enough time on the pass", bullet_list(problems))
                return
        exclude = self._editing.id if self._editing else None
        conflicts = find_conflicts(self.app.store.sessions, device, start, new_end, exclude_id=exclude)
        if conflicts:
            fail("Device unavailable", conflict_message(device, conflicts))
            return

        self._syncing = True
        try:
            self.end_var.set(to_local(new_end).strftime("%H:%M"))
        finally:
            self._syncing = False
        self._recalc_from_times()

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
        monthly_pass = None
        used = 0
        if self.pass_var.get():
            if self._pass is None:
                raise ValidationError([
                    "'Monthly pass holder' is ticked but no valid pass was found for that phone number. "
                    "Register the pass first, or untick the box to bill the session normally."
                ])
            monthly_pass = self._pass
            used = self._pass_used_by_others(monthly_pass)
        return prepare_session(
            customer_name=self.name_var.get(),
            device=self.device_var.get(),
            players=self._players(),
            date_text=self.date_var.get(),
            start_text=self.start_var.get(),
            end_text=self.end_var.get(),
            payment_method=self.method_var.get(),
            total_text=self.total_var.get(),
            paid_text=self.paid_var.get(),
            payment_status=self.status_var.get(),
            now=now_local(),
            existing=self._editing,
            new_extensions=self._pending,
            monthly_pass=monthly_pass,
            pass_used_by_others=used,
            notes_text=self._notes(),
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

    def _summary(self, session: Session) -> str:
        players = f"{session.players} player{'s' if session.players != 1 else ''}"
        text = (f"{session.customer_name} · {session.device} · {players}\n"
                f"{fmt_range(session.start, session.end)} ({fmt_duration(session.duration_minutes)})\n"
                f"Charge {fmt_money(session.total_paise)} · Paid {fmt_money(session.paid_paise)} · "
                f"{session.payment_status}")
        if session.pass_id:
            p = self.app.store.get_pass(session.pass_id)
            left = p.included_minutes - self.app.store.pass_used_minutes(p.id)
            text += (f"\nMonthly pass: {fmt_duration(session.pass_minutes)} used, "
                     f"{fmt_duration(max(left, 0))} left")
        if session.notes:
            text += f"\nNote: {session.notes}"
        return text

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
        messagebox.showinfo("Session saved", "Saved session:\n" + self._summary(session), parent=self)

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
        messagebox.showinfo("Session updated", "Updated session:\n" + self._summary(session) + extra, parent=self)
