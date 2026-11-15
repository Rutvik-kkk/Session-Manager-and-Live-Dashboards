"""Expenses tab: employees record money they spent for the café (an amount and a note)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

from ..analytics import (
    PRESET_ALL,
    PRESET_LAST_7,
    PRESET_THIS_MONTH,
    PRESET_THIS_YEAR,
    PRESET_TODAY,
    PRESET_YESTERDAY,
    expenses_in_range,
    preset_range,
)
from ..config import MAX_EXPENSE_NOTE_LENGTH
from ..formatting import fmt_datetime, fmt_datetime_long, fmt_money, now_local, paise_to_input, today_local
from ..models import Expense, ValidationError, normalise_notes, prepare_expense
from ..storage import StorageError
from . import dialogs, theme
from .widgets import Column, SortableTree, Tooltip, card

if TYPE_CHECKING:
    from .app import OnTopApp

EXPENSE_PRESETS = (PRESET_TODAY, PRESET_YESTERDAY, PRESET_LAST_7, PRESET_THIS_MONTH, PRESET_THIS_YEAR, PRESET_ALL)

EXPENSE_COLUMNS = [
    Column("when", "Entered", lambda e: fmt_datetime(e.created_at), lambda e: e.created_at, 150, "center", False),
    Column("amount", "Amount", lambda e: fmt_money(e.amount_paise), lambda e: e.amount_paise, 100, "e", False),
    Column("note", "Note", lambda e: " ⏎ ".join(e.note.splitlines()), lambda e: e.note.casefold(), 360),
]


class ExpensesTab(ttk.Frame):
    def __init__(self, master: tk.Misc, app: "OnTopApp"):
        super().__init__(master, padding=(24, 18, 24, 18))
        self.app = app
        self._editing: Expense | None = None
        self.amount_var = tk.StringVar()
        self.preset_var = tk.StringVar(value=PRESET_TODAY)
        self.search_var = tk.StringVar()
        self._build()
        for var in (self.preset_var, self.search_var):
            var.trace_add("write", lambda *_: self.refresh())
        self.clear_form()

    # -- layout ----------------------------------------------------------

    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 12))
        ttk.Label(head, text="Employee expenses", style="Title.TLabel").pack(side="left")
        ttk.Label(head, style="Subtitle.TLabel",
                  text="Money an employee spent for the café. Enter the amount and a note; the time is saved "
                       "automatically.").pack(side="left", padx=14, pady=(6, 0))

        columns = ttk.Frame(self)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(1, weight=1)
        columns.rowconfigure(0, weight=1)

        outer, f = card(columns, padding=18)
        outer.grid(row=0, column=0, sticky="nsw", padx=(0, 16))
        self.form_title = ttk.Label(f, text="New expense", style="CardSection.TLabel")
        self.form_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(f, text="Amount (₹) *", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self.amount_entry = ttk.Entry(f, textvariable=self.amount_var, width=14)
        self.amount_entry.grid(row=1, column=1, sticky="w", pady=6)
        self.amount_entry.bind("<Return>", lambda e: self.note_text.focus_set())

        ttk.Label(f, text="Note *", style="CardMuted.TLabel").grid(row=2, column=0, sticky="nw", padx=(0, 12), pady=6)
        self.note_text = tk.Text(
            f, height=4, width=28, wrap="word", undo=True, font=theme.FONTS["base"],
            background=theme.SURFACE_2, foreground=theme.TEXT, insertbackground=theme.TEXT,
            selectbackground=theme.ACCENT_DIM, selectforeground=theme.TEXT, relief="flat",
            highlightthickness=1, highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT, padx=8, pady=4)
        self.note_text.grid(row=2, column=1, sticky="ew", pady=6)
        self.note_text.bind("<<Modified>>", self._on_note_modified)
        self.note_text.bind("<Tab>", lambda e: (e.widget.tk_focusNext().focus_set(), "break")[1])
        self.note_text.bind("<Shift-Tab>", lambda e: (e.widget.tk_focusPrev().focus_set(), "break")[1])
        Tooltip(self.note_text, "What was bought or paid for, e.g. 'Cold drinks restock' or 'Controller repair'.")
        self.note_count = ttk.Label(f, style="CardSmall.TLabel")
        self.note_count.grid(row=3, column=1, sticky="e")

        self.form_msg = ttk.Label(f, style="CardMuted.TLabel", wraplength=300, justify="left")
        self.form_msg.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(f, style="Inner.TFrame")
        buttons.grid(row=5, column=0, columnspan=2, sticky="w", pady=(14, 0))
        self.save_btn = ttk.Button(buttons, text="Save Expense", style="Accent.TButton", command=self.save)
        self.clear_btn = ttk.Button(buttons, text="Clear", command=self.clear_form)
        self.cancel_btn = ttk.Button(buttons, text="Cancel Edit", style="Danger.TButton", command=self.clear_form)
        self.save_btn.pack(side="left")
        self.clear_btn.pack(side="left", padx=(8, 0))

        right = ttk.Frame(columns)
        right.grid(row=0, column=1, sticky="nsew")
        outer, bar = card(right, padding=12)
        outer.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="Show", style="CardMuted.TLabel").pack(side="left")
        ttk.Combobox(bar, textvariable=self.preset_var, values=EXPENSE_PRESETS, state="readonly",
                     width=12).pack(side="left", padx=(8, 16))
        ttk.Label(bar, text="Search note", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(bar, textvariable=self.search_var, width=22).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Edit Selected", command=self.edit_selected).pack(side="right")

        outer, inner = card(right, padding=0)
        outer.pack(fill="both", expand=True)
        self.table = SortableTree(inner, EXPENSE_COLUMNS, sort_column="when", descending=True, height=12)
        self.table.pack(fill="both", expand=True)
        self.table.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.empty_label = ttk.Label(inner, style="CardMuted.TLabel")

        outer, inner = card(right, padding=12)
        outer.pack(fill="x", pady=(10, 0))
        ttk.Label(inner, text="Total spent (shown)", style="CardMuted.TLabel").pack(side="left")
        self.total_label = ttk.Label(inner, text="₹0.00", style="CardSection.TLabel")
        self.total_label.pack(side="left", padx=(10, 0))
        self.count_label = ttk.Label(inner, style="CardMuted.TLabel")
        self.count_label.pack(side="right")

    # -- form --------------------------------------------------------------

    def _note(self) -> str:
        return self.note_text.get("1.0", "end-1c")

    def _set_note(self, text: str):
        self.note_text.delete("1.0", "end")
        self.note_text.insert("1.0", text)
        self.note_text.edit_reset()
        self._on_note_modified()

    def _on_note_modified(self, _event=None):
        self.note_text.edit_modified(False)
        length = len(normalise_notes(self._note()))
        over = length > MAX_EXPENSE_NOTE_LENGTH
        self.note_count.configure(text=f"{length}/{MAX_EXPENSE_NOTE_LENGTH}",
                                  style="CardError.TLabel" if over else "CardSmall.TLabel")

    def clear_form(self):
        self._editing = None
        self.amount_var.set("")
        self._set_note("")
        self.form_title.configure(text="New expense")
        self.form_msg.configure(text="", style="CardMuted.TLabel")
        self.save_btn.configure(text="Save Expense")
        self.cancel_btn.pack_forget()
        self.clear_btn.pack(side="left", padx=(8, 0))
        self.save_btn.configure(state="disabled" if self.app.store.read_only else "normal")

    def save(self):
        store = self.app.store
        if store.read_only:
            dialogs.showerror("Saving disabled", store.load_error or "The data file could not be loaded.", parent=self)
            return
        try:
            expense = prepare_expense(amount_text=self.amount_var.get(), note_text=self._note(),
                                      now=now_local(), existing=self._editing)
            if self._editing:
                store.update_expense(expense)
            else:
                store.add_expense(expense)
        except ValidationError as exc:
            dialogs.showerror("Please fix the following", "\n".join(f"• {e}" for e in exc.errors), parent=self)
            return
        except StorageError as exc:
            dialogs.showerror("Could not save", f"{exc}\n\nYour entries are still in the form.", parent=self)
            return
        updating = self._editing is not None
        self.clear_form()
        self.app.data_changed()
        if self.table.tree.exists(expense.id):
            self.table.tree.selection_set(expense.id)
        verb = "Updated" if updating else "Saved"
        self.form_msg.configure(text=f"{verb} {fmt_money(expense.amount_paise)} — {expense.note.splitlines()[0]}",
                                style="CardOk.TLabel")
        self.app.set_status(f"{verb} expense of {fmt_money(expense.amount_paise)}.")

    def edit_selected(self):
        expense = self.app.store.get_expense(self.table.selected_id())
        if expense is None:
            dialogs.showinfo("Edit expense", "Select an expense in the list first.", parent=self)
            return
        self._editing = expense
        self.amount_var.set(paise_to_input(expense.amount_paise))
        self._set_note(expense.note)
        self.form_title.configure(text="Edit expense")
        self.form_msg.configure(text=f"Entered {fmt_datetime_long(expense.created_at)}", style="CardMuted.TLabel")
        self.save_btn.configure(text="Update Expense", state="disabled" if self.app.store.read_only else "normal")
        self.clear_btn.pack_forget()
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.amount_entry.focus_set()

    # -- list ------------------------------------------------------------

    def refresh(self):
        start, end = preset_range(self.preset_var.get(), today_local())
        rows = expenses_in_range(self.app.store.expenses, start, end, self.search_var.get())
        self.table.set_items(rows)
        total = sum(e.amount_paise for e in rows)
        self.total_label.configure(text=fmt_money(total))
        self.count_label.configure(text=f"{len(rows)} expense{'s' if len(rows) != 1 else ''}")
        if rows:
            self.empty_label.place_forget()
        else:
            text = ("No expenses recorded yet. Use the form on the left." if not self.app.store.expenses
                    else "No expenses match these filters.")
            self.empty_label.configure(text=text)
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")
        if not self._editing:
            self.save_btn.configure(state="disabled" if self.app.store.read_only else "normal")
