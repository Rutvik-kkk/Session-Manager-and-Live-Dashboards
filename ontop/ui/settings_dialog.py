"""General settings dialog: opening hours, price list and monthly pass terms."""

from __future__ import annotations

import dataclasses
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .. import config
from ..formatting import paise_to_input, parse_money, parse_time
from ..settings import AppSettings
from . import theme
from .widgets import card

GROUPS = tuple(config.HOURLY_RATES_PAISE)


class SettingsDialog(tk.Toplevel):
    """Edits a copy of the settings; ``on_save`` receives the validated result."""

    def __init__(self, master: tk.Misc, current: AppSettings, on_save: Callable[[AppSettings], bool]):
        super().__init__(master)
        self.title("General settings")
        self.configure(background=theme.BG)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.current = current
        self.on_save = on_save

        self.opening_var = tk.StringVar()
        self.closing_var = tk.StringVar()
        self.rate_vars = {g: {n: tk.StringVar() for n in config.PLAYER_COUNTS} for g in GROUPS}
        self.half_vars = {g: tk.StringVar() for g in GROUPS}
        self.pass_price_var = tk.StringVar()
        self.pass_hours_var = tk.StringVar()
        self.pass_days_var = tk.StringVar()

        self._build()
        self._fill(current)
        self._center_on(master.winfo_toplevel())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.focus_set()

    def _build(self):
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="General settings", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, style="Subtitle.TLabel",
                  text="Saved in settings.json next to your session data. Changes apply after a restart.\n"
                       "Saved sessions keep the amounts they were saved with.").pack(anchor="w", pady=(2, 12))

        outer, f = card(body, padding=(16, 12))
        outer.pack(fill="x", pady=(0, 10))
        ttk.Label(f, text="Opening hours", style="CardSection.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(f, text="Opens at", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.opening_var, width=8).grid(row=1, column=1, sticky="w", padx=(8, 20))
        ttk.Label(f, text="Closes at", style="CardMuted.TLabel").grid(row=1, column=2, sticky="w")
        ttk.Entry(f, textvariable=self.closing_var, width=8).grid(row=1, column=3, sticky="w", padx=(8, 0))

        outer, f = card(body, padding=(16, 12))
        outer.pack(fill="x", pady=(0, 10))
        ttk.Label(f, text="Price list (₹)", style="CardSection.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        for col, group in enumerate(GROUPS, start=1):
            ttk.Label(f, text=group, style="Card.TLabel", font=theme.FONTS["bold"]).grid(
                row=1, column=col, sticky="w", padx=(12, 0), pady=(6, 2))
        for row, players in enumerate(config.PLAYER_COUNTS, start=2):
            label = f"{players} player{'s' if players != 1 else ''} · per hour"
            ttk.Label(f, text=label, style="CardMuted.TLabel").grid(row=row, column=0, sticky="w", pady=3)
            for col, group in enumerate(GROUPS, start=1):
                ttk.Entry(f, textvariable=self.rate_vars[group][players], width=10).grid(
                    row=row, column=col, sticky="w", padx=(12, 0))
        row = len(config.PLAYER_COUNTS) + 2
        ttk.Label(f, text="30 minutes (1 player)", style="CardMuted.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        for col, group in enumerate(GROUPS, start=1):
            ttk.Entry(f, textvariable=self.half_vars[group], width=10).grid(row=row, column=col, sticky="w", padx=(12, 0))

        outer, f = card(body, padding=(16, 12))
        outer.pack(fill="x", pady=(0, 10))
        ttk.Label(f, text="Monthly pass (new passes)", style="CardSection.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w")
        for col, (text, var, width) in enumerate((("Price (₹)", self.pass_price_var, 10),
                                                  ("Hours", self.pass_hours_var, 6),
                                                  ("Valid for (days)", self.pass_days_var, 6))):
            cell = ttk.Frame(f, style="Inner.TFrame")
            cell.grid(row=1, column=col, sticky="w", padx=(0, 18), pady=(6, 0))
            ttk.Label(cell, text=text, style="CardMuted.TLabel").pack(anchor="w")
            ttk.Entry(cell, textvariable=var, width=width).pack(anchor="w", pady=(2, 0))
        ttk.Label(f, style="CardSmall.TLabel",
                  text="Passes already sold keep the hours and validity they were sold with.").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self.error = ttk.Label(body, style="Error.TLabel", wraplength=theme.px(460), justify="left")
        self.error.pack(anchor="w")
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=self._save).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Restore defaults", command=lambda: self._fill(self._defaults())).pack(side="right")

    def _center_on(self, owner: tk.Misc):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = owner.winfo_rootx() + (owner.winfo_width() - w) // 2
        y = owner.winfo_rooty() + (owner.winfo_height() - h) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _defaults(self) -> AppSettings:
        return AppSettings(theme=self.current.theme)

    def _fill(self, s: AppSettings):
        self.opening_var.set(s.opening)
        self.closing_var.set(s.closing)
        for group in GROUPS:
            for players in config.PLAYER_COUNTS:
                self.rate_vars[group][players].set(paise_to_input(s.hourly_rates_paise[group][players]))
            self.half_vars[group].set(paise_to_input(s.half_hour_paise[group]))
        self.pass_price_var.set(paise_to_input(s.pass_price_paise))
        self.pass_hours_var.set(str(s.pass_hours))
        self.pass_days_var.set(str(s.pass_valid_days))
        self.error.configure(text="")

    def _read(self) -> AppSettings:
        errors: list[str] = []

        def money(var: tk.StringVar, name: str) -> int:
            try:
                return parse_money(var.get(), name)
            except ValueError as exc:
                errors.append(str(exc))
                return 0

        def whole(var: tk.StringVar, name: str) -> int:
            text = var.get().strip()
            if not text.isdigit():
                errors.append(f"{name} must be a whole number.")
                return 0
            return int(text)

        times = []
        for var, name in ((self.opening_var, "Opening time"), (self.closing_var, "Closing time")):
            try:
                times.append(parse_time(var.get(), name).strftime("%H:%M"))
            except ValueError as exc:
                errors.append(str(exc))
                times.append(var.get().strip())
        rates = {g: {n: money(self.rate_vars[g][n], f"{g} {n}-player price") for n in config.PLAYER_COUNTS}
                 for g in GROUPS}
        half = {g: money(self.half_vars[g], f"{g} 30-minute price") for g in GROUPS}
        result = dataclasses.replace(
            self.current,
            opening=times[0],
            closing=times[1],
            hourly_rates_paise=rates,
            half_hour_paise=half,
            pass_price_paise=money(self.pass_price_var, "Pass price"),
            pass_hours=whole(self.pass_hours_var, "Pass hours"),
            pass_valid_days=whole(self.pass_days_var, "Pass validity"),
        )
        if not errors:
            errors = result.problems()
        if errors:
            raise ValueError("\n".join(f"• {e}" for e in errors))
        return result

    def _save(self):
        try:
            result = self._read()
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return
        if result == self.current:
            self.destroy()
            return
        try:
            saved = self.on_save(result)
        except OSError as exc:
            messagebox.showerror("Could not save settings", str(exc), parent=self)
            return
        if saved:
            self.destroy()
