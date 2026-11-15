"""Configurations dialog: hours and pass terms, devices and prices, games, and snacks & drinks."""

from __future__ import annotations

import copy
import dataclasses
import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable

from .. import config
from ..formatting import fmt_clock, fmt_money, paise_to_input, parse_money, parse_time
from ..models import normalise_name
from ..settings import AppSettings
from . import dialogs, theme
from .widgets import TimeField, card

IN_USE = "In use"
OWN_PRICES = "Own prices"  # the device gets its own column in the price list
SAME_AS = "Same prices as "  # ... or it shares another device's column


class SettingsDialog(tk.Toplevel):
    """Edits a copy of the settings; ``on_save`` receives the validated result.

    ``used_devices`` are the devices saved sessions refer to: they can change which prices they use but
    cannot be renamed or removed, because that would leave those sessions without a valid device.

    Every device normally has its own column in the price list, which the user fills in; a device can
    instead be set to use the same prices as another (as PS5(X) and PS5(Y) do).
    """

    def __init__(self, master: tk.Misc, current: AppSettings, on_save: Callable[[AppSettings], bool],
                 used_devices: Iterable[str] = ()):
        super().__init__(master)
        self.title("Configurations")
        self.configure(background=theme.BG)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.current = current
        self.on_save = on_save
        self.used_devices = frozenset(used_devices)

        self.devices: list[dict[str, str]] = []
        self.games: list[str] = []
        self.menu: list[dict] = []

        self.opening_var = tk.StringVar()
        self.closing_var = tk.StringVar()
        self.clock_var = tk.BooleanVar(value=current.clock_24h)
        self.rate_vars: dict[str, dict[int, tk.StringVar]] = {}
        self.half_vars: dict[str, tk.StringVar] = {}
        self.price_entries: dict[tuple[str, int], ttk.Entry] = {}
        self.pass_price_var = tk.StringVar()
        self.pass_hours_var = tk.StringVar()
        self.pass_days_var = tk.StringVar()
        self.device_name_var = tk.StringVar()
        self.device_group_var = tk.StringVar(value=OWN_PRICES)
        self.game_var = tk.StringVar()
        self.item_name_var = tk.StringVar()
        self.item_kind_var = tk.StringVar(value=config.ITEM_SNACK)
        self.item_price_var = tk.StringVar()

        self._build()
        self._fill(current)
        self._center_on(master.winfo_toplevel())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.focus_set()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self):
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Configurations", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, style="Subtitle.TLabel",
                  text="Saved in settings.json next to your session data. Prices, games and the snack & drink menu "
                       "apply immediately to new entries;\nadding or removing devices, opening hours and pass terms "
                       "apply after a restart. Saved sessions keep the amounts they were saved with.").pack(
            anchor="w", pady=(2, 10))

        self.tabs = ttk.Notebook(body)
        self.tabs.pack(fill="both", expand=True)
        for build, title in ((self._build_general, "General"), (self._build_devices, "Devices & Prices"),
                             (self._build_games, "Games"), (self._build_menu, "Snacks & Drinks")):
            page = ttk.Frame(self.tabs, padding=(0, 12, 0, 0))
            self.tabs.add(page, text=f"  {title}  ")
            build(page)

        self.error = ttk.Label(body, style="Error.TLabel", wraplength=theme.px(560), justify="left")
        self.error.pack(anchor="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=self._save).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Restore Defaults", command=self._restore_defaults).pack(side="right")

    def _build_general(self, page):
        outer, f = card(page, padding=(16, 12))
        outer.pack(fill="x", pady=(0, 10))
        ttk.Label(f, text="Opening Hours & Clock", style="CardSection.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(f, text="Opens At", style="CardMuted.TLabel").grid(row=1, column=0, sticky="w", pady=6)
        TimeField(f, self.opening_var).grid(row=1, column=1, sticky="w", padx=(8, 20))
        ttk.Label(f, text="Closes At", style="CardMuted.TLabel").grid(row=1, column=2, sticky="w")
        TimeField(f, self.closing_var).grid(row=1, column=3, sticky="w", padx=(8, 0))
        ttk.Label(f, text="Clock", style="CardMuted.TLabel").grid(row=2, column=0, sticky="w", pady=(4, 0))
        clock = ttk.Frame(f, style="Inner.TFrame")
        clock.grid(row=2, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=(4, 0))
        for value, text in ((True, "24-Hour (18:30)"), (False, "12-Hour (6:30 PM)")):
            ttk.Radiobutton(clock, text=text, value=value, variable=self.clock_var,
                            style="Card.TRadiobutton").pack(side="left", padx=(0, 16))

        outer, f = card(page, padding=(16, 12))
        outer.pack(fill="x", pady=(0, 10))
        ttk.Label(f, text="Monthly Pass (New Passes)", style="CardSection.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w")
        for col, (text, var, width) in enumerate((("Price (₹)", self.pass_price_var, 10),
                                                  ("Hours", self.pass_hours_var, 6),
                                                  ("Valid for (Days)", self.pass_days_var, 6))):
            cell = ttk.Frame(f, style="Inner.TFrame")
            cell.grid(row=1, column=col, sticky="w", padx=(0, 18), pady=(6, 0))
            ttk.Label(cell, text=text, style="CardMuted.TLabel").pack(anchor="w")
            ttk.Entry(cell, textvariable=var, width=width).pack(anchor="w", pady=(2, 0))
        ttk.Label(f, style="CardSmall.TLabel",
                  text="Passes already sold keep the hours and validity they were sold with.").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def _build_devices(self, page):
        outer, f = card(page, padding=(16, 12))
        outer.pack(fill="x", pady=(0, 10))
        ttk.Label(f, text="Devices", style="CardSection.TLabel").grid(row=0, column=0, columnspan=5, sticky="w")
        ttk.Label(f, style="CardSmall.TLabel", justify="left",
                  text="Each new device gets its own column in the price list below, which you fill in yourself. "
                       "A device used by saved sessions can't be renamed or removed.").grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(2, 6))
        self.device_tree = ttk.Treeview(f, columns=("name", "group", "status"), show="headings", height=4,
                                        selectmode="browse")
        for key, text, width in (("name", "Device", 170), ("group", "Prices", 170), ("status", "", 100)):
            self.device_tree.heading(key, text=text)
            self.device_tree.column(key, width=width, anchor="w")
        self.device_tree.grid(row=2, column=0, columnspan=5, sticky="ew")
        self.device_tree.bind("<<TreeviewSelect>>", self._device_selected)

        ttk.Label(f, text="Name", style="CardMuted.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(f, textvariable=self.device_name_var, width=18).grid(row=4, column=0, sticky="w", padx=(0, 10))
        ttk.Label(f, text="Prices", style="CardMuted.TLabel").grid(row=3, column=1, sticky="w", pady=(10, 0))
        self.group_combo = ttk.Combobox(f, textvariable=self.device_group_var, width=18, state="readonly")
        self.group_combo.grid(row=4, column=1, sticky="w", padx=(0, 10))
        btns = ttk.Frame(f, style="Inner.TFrame")
        btns.grid(row=4, column=2, columnspan=3, sticky="w")
        ttk.Button(btns, text="Add", style="Accent.TButton", command=self._add_device).pack(side="left")
        ttk.Button(btns, text="Update Selected", command=self._update_device).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Remove Selected", style="Danger.TButton", command=self._remove_device).pack(
            side="left", padx=(6, 0))
        ttk.Label(f, style="CardSmall.TLabel",
                  text="Choose \"Own prices\" for a separate column, or pick another device's prices to share "
                       "that column.").grid(
            row=5, column=0, columnspan=5, sticky="w", pady=(4, 0))

        outer, f = card(page, padding=(16, 12))
        outer.pack(fill="x")
        self.price_card = f

    def _build_games(self, page):
        outer, f = card(page, padding=(16, 12))
        outer.pack(fill="x")
        ttk.Label(f, text="Games", style="CardSection.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, style="CardSmall.TLabel", justify="left",
                  text="The games you can pick when entering a session (optional on each session). Removing a game "
                       "doesn't change sessions that already used it.").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 8))
        self.game_list = tk.Listbox(
            f, height=10, activestyle="none", exportselection=False, font=theme.FONTS["base"],
            background=theme.SURFACE_2, foreground=theme.TEXT, selectbackground=theme.ACCENT,
            selectforeground=theme.ON_ACCENT, relief="flat", highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT)
        self.game_list.grid(row=2, column=0, columnspan=3, sticky="ew")
        entry = ttk.Entry(f, textvariable=self.game_var, width=34)
        entry.grid(row=3, column=0, sticky="w", pady=(10, 0))
        entry.bind("<Return>", lambda e: self._add_game())
        ttk.Button(f, text="Add Game", style="Accent.TButton", command=self._add_game).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Button(f, text="Remove Selected", style="Danger.TButton", command=self._remove_game).grid(
            row=3, column=2, sticky="e", padx=(8, 0), pady=(10, 0))
        f.columnconfigure(2, weight=1)

    def _build_menu(self, page):
        outer, f = card(page, padding=(16, 12))
        outer.pack(fill="x")
        ttk.Label(f, text="Snacks & Drinks Menu", style="CardSection.TLabel").grid(
            row=0, column=0, columnspan=6, sticky="w")
        ttk.Label(f, style="CardSmall.TLabel", justify="left",
                  text="Items you can add to a session. The price is copied onto the session when you add the "
                       "item, so changing a price here never changes past sales.").grid(
            row=1, column=0, columnspan=6, sticky="w", pady=(2, 8))
        self.menu_tree = ttk.Treeview(f, columns=("name", "kind", "price"), show="headings", height=8,
                                      selectmode="browse")
        for key, text, width, anchor in (("name", "Item", 240, "w"), ("kind", "Type", 90, "w"),
                                         ("price", "Price", 100, "e")):
            self.menu_tree.heading(key, text=text)
            self.menu_tree.column(key, width=width, anchor=anchor)
        self.menu_tree.grid(row=2, column=0, columnspan=6, sticky="ew")
        self.menu_tree.bind("<<TreeviewSelect>>", self._menu_selected)

        for col, text in enumerate(("Name", "Type", "Price (₹)")):
            ttk.Label(f, text=text, style="CardMuted.TLabel").grid(row=3, column=col, sticky="w", pady=(10, 0))
        ttk.Entry(f, textvariable=self.item_name_var, width=26).grid(row=4, column=0, sticky="w", padx=(0, 10))
        ttk.Combobox(f, textvariable=self.item_kind_var, values=config.ITEM_KINDS, state="readonly",
                     width=8).grid(row=4, column=1, sticky="w", padx=(0, 10))
        price = ttk.Entry(f, textvariable=self.item_price_var, width=10)
        price.grid(row=4, column=2, sticky="w", padx=(0, 10))
        price.bind("<Return>", lambda e: self._add_item())
        btns = ttk.Frame(f, style="Inner.TFrame")
        btns.grid(row=5, column=0, columnspan=6, sticky="w", pady=(10, 0))
        ttk.Button(btns, text="Add Item", style="Accent.TButton", command=self._add_item).pack(side="left")
        ttk.Button(btns, text="Update Selected", command=self._update_item).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Remove Selected", style="Danger.TButton", command=self._remove_item).pack(
            side="left", padx=(6, 0))

    def _center_on(self, owner: tk.Misc):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = owner.winfo_rootx() + (owner.winfo_width() - w) // 2
        y = owner.winfo_rooty() + (owner.winfo_height() - h) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    # ------------------------------------------------------------------
    # Filling and defaults
    # ------------------------------------------------------------------

    def _restore_defaults(self):
        """Reset hours, prices and pass terms; the lists of devices, games and menu items are left as they are."""
        factory = AppSettings(theme=self.current.theme, clock_24h=self.current.clock_24h)
        base_group = next(iter(factory.hourly_rates_paise))
        rates, half = {}, {}
        for group in self._groups():
            if group in factory.hourly_rates_paise:
                rates[group] = dict(factory.hourly_rates_paise[group])
                half[group] = factory.half_hour_paise[group]
                continue
            # A device you added has no factory prices: keep what you typed (or the PS5 prices if it is still blank).
            try:
                rates[group] = {n: parse_money(self.rate_vars[group][n].get()) for n in config.PLAYER_COUNTS}
                half[group] = parse_money(self.half_vars[group].get())
            except ValueError:
                rates[group] = dict(factory.hourly_rates_paise[base_group])
                half[group] = factory.half_hour_paise[base_group]
        self._fill(dataclasses.replace(
            factory, hourly_rates_paise=rates, half_hour_paise=half, devices=copy.deepcopy(self.devices),
            games=list(self.games), menu_items=copy.deepcopy(self.menu)))

    def _fill(self, s: AppSettings):
        self.opening_var.set(fmt_clock(parse_time(s.opening)))
        self.closing_var.set(fmt_clock(parse_time(s.closing)))
        self.clock_var.set(s.clock_24h)
        self.pass_price_var.set(paise_to_input(s.pass_price_paise))
        self.pass_hours_var.set(str(s.pass_hours))
        self.pass_days_var.set(str(s.pass_valid_days))
        self.devices = copy.deepcopy(s.devices)
        self.games = list(s.games)
        self.menu = copy.deepcopy(s.menu_items)
        self.rate_vars, self.half_vars = {}, {}
        for group in s.price_groups:
            self._ensure_group(group)
            for players in config.PLAYER_COUNTS:
                self.rate_vars[group][players].set(paise_to_input(s.hourly_rates_paise[group][players]))
            self.half_vars[group].set(paise_to_input(s.half_hour_paise[group]))
        self._refresh_devices()
        self._refresh_games()
        self._refresh_menu()
        self.error.configure(text="")

    # ------------------------------------------------------------------
    # Devices and the price list
    # ------------------------------------------------------------------

    def _groups(self) -> list[str]:
        seen: list[str] = []
        for d in self.devices:
            if d["group"] not in seen:
                seen.append(d["group"])
        return seen

    def _users(self, group: str) -> list[str]:
        """Names of the devices that use this price column."""
        return [d["name"] for d in self.devices if d["group"] == group]

    def _prices_label(self, index: int) -> str:
        """What the 'Prices' column and box show for a device: its own column, or whose prices it shares."""
        d = self.devices[index]
        others = [n for n in self._users(d["group"]) if n != d["name"]]
        return f"{SAME_AS}{others[0]}" if others else OWN_PRICES

    def _ensure_group(self, group: str, copy_from: str | None = None):
        """Create the price fields for a column, starting from another column's prices when given (else blank)."""
        if group in self.rate_vars:
            return
        self.rate_vars[group] = {n: tk.StringVar() for n in config.PLAYER_COUNTS}
        self.half_vars[group] = tk.StringVar()
        if copy_from in self.rate_vars:
            for n, var in self.rate_vars[group].items():
                var.set(self.rate_vars[copy_from][n].get())
            self.half_vars[group].set(self.half_vars[copy_from].get())

    def _rename_group(self, old: str, new: str):
        if old == new or old not in self.rate_vars:
            return
        self.rate_vars[new] = self.rate_vars.pop(old)
        self.half_vars[new] = self.half_vars.pop(old)

    def _own_group_name(self, name: str, ignore: int | None = None) -> str:
        """A price column name for a device with its own prices: the device's name, made unique if needed."""
        taken = {d["group"].casefold() for i, d in enumerate(self.devices) if i != ignore}
        candidate, number = name, 2
        while candidate.casefold() in taken:
            suffix = f" {number}"
            candidate = name[:config.MAX_PRICE_GROUP_LENGTH - len(suffix)] + suffix
            number += 1
        return candidate

    def _refresh_devices(self):
        self.device_tree.delete(*self.device_tree.get_children())
        for index, d in enumerate(self.devices):
            self.device_tree.insert("", "end", iid=str(index), values=(
                d["name"], self._prices_label(index), IN_USE if d["name"] in self.used_devices else ""))
        self.group_combo.configure(values=[OWN_PRICES, *(f"{SAME_AS}{d['name']}" for d in self.devices)])
        # Forget the price fields of columns nobody uses any more (a removed device).
        groups = self._groups()
        self.rate_vars = {g: v for g, v in self.rate_vars.items() if g in groups}
        self.half_vars = {g: v for g, v in self.half_vars.items() if g in groups}
        self._rebuild_prices()

    def _rebuild_prices(self):
        f = self.price_card
        for child in f.winfo_children():
            child.destroy()
        self.price_entries = {}
        groups = self._groups()
        ttk.Label(f, text="Price List (₹)", style="CardSection.TLabel").grid(
            row=0, column=0, columnspan=len(groups) + 1, sticky="w")
        for col, group in enumerate(groups, start=1):
            self._ensure_group(group)
            ttk.Label(f, text=" + ".join(self._users(group)), style="Card.TLabel", font=theme.FONTS["bold"]).grid(
                row=1, column=col, sticky="w", padx=(12, 0), pady=(6, 2))
        for row, players in enumerate(config.PLAYER_COUNTS, start=2):
            label = f"{players} Player{'s' if players != 1 else ''} · per Hour"
            ttk.Label(f, text=label, style="CardMuted.TLabel").grid(row=row, column=0, sticky="w", pady=3)
            for col, group in enumerate(groups, start=1):
                entry = ttk.Entry(f, textvariable=self.rate_vars[group][players], width=10)
                entry.grid(row=row, column=col, sticky="w", padx=(12, 0))
                self.price_entries[(group, players)] = entry
        row = len(config.PLAYER_COUNTS) + 2
        ttk.Label(f, text="30 Minutes (1 Player)", style="CardMuted.TLabel").grid(row=row, column=0, sticky="w", pady=3)
        for col, group in enumerate(groups, start=1):
            ttk.Entry(f, textvariable=self.half_vars[group], width=10).grid(row=row, column=col, sticky="w", padx=(12, 0))

    def _selected_index(self, tree: ttk.Treeview) -> int | None:
        selected = tree.selection()
        return int(selected[0]) if selected else None

    def _device_selected(self, _event=None):
        index = self._selected_index(self.device_tree)
        if index is not None:
            self.device_name_var.set(self.devices[index]["name"])
            self.device_group_var.set(self._prices_label(index))

    def _device_fields(self) -> tuple[str, str] | None:
        name, choice = normalise_name(self.device_name_var.get()), self.device_group_var.get()
        if not name:
            self._fail("Enter a device name.")
            return None
        if len(name) > config.MAX_DEVICE_NAME_LENGTH:
            self._fail(f"Device names can be up to {config.MAX_DEVICE_NAME_LENGTH} characters.")
            return None
        return name, choice

    def _shared_group(self, choice: str) -> str | None:
        """The price column of the device named in a 'Same prices as …' choice, or None for 'Own prices'."""
        if not choice.startswith(SAME_AS):
            return None
        target = choice[len(SAME_AS):]
        return next((d["group"] for d in self.devices if d["name"] == target), None)

    def _device_taken(self, name: str, ignore: int | None = None) -> bool:
        return any(d["name"].casefold() == name.casefold() for i, d in enumerate(self.devices) if i != ignore)

    def _add_device(self):
        fields = self._device_fields()
        if fields is None:
            return
        name, choice = fields
        if self._device_taken(name):
            self._fail(f"There is already a device called '{name}'.")
            return
        group = self._shared_group(choice)
        own = group is None
        if own:
            group = self._own_group_name(name)
            self._ensure_group(group)  # blank: the prices are typed in by the user, never guessed
        self.devices.append({"name": name, "group": group})
        self.device_name_var.set("")
        self.device_group_var.set(OWN_PRICES)
        self._refresh_devices()
        if own:
            self.price_entries[(group, config.PLAYER_COUNTS[0])].focus_set()
            self._hint(f"'{name}' added. Type its prices in its new column of the price list, then press Save.")
        else:
            self._fail("")

    def _update_device(self):
        index = self._selected_index(self.device_tree)
        if index is None:
            self._fail("Select a device in the list first.")
            return
        fields = self._device_fields()
        if fields is None:
            return
        name, choice = fields
        old = self.devices[index]["name"]
        if name != old and old in self.used_devices:
            self._fail(f"'{old}' is used by saved sessions, so it can't be renamed. You can change its prices.")
            return
        if self._device_taken(name, ignore=index):
            self._fail(f"There is already a device called '{name}'.")
            return
        old_group = self.devices[index]["group"]
        alone = len(self._users(old_group)) == 1
        shared = self._shared_group(choice)
        if shared is None:  # own prices
            if alone:
                group = old_group
                if old_group == old and name != old:  # the column is named after the device: keep it that way
                    group = self._own_group_name(name, ignore=index)
                    self._rename_group(old_group, group)
            else:
                group = self._own_group_name(name, ignore=index)
                self._ensure_group(group, copy_from=old_group)  # starts as a copy of the shared prices
        else:
            group = shared
        self.devices[index] = {"name": name, "group": group}
        self._refresh_devices()
        self.device_tree.selection_set(str(index))
        self._fail("")

    def _remove_device(self):
        index = self._selected_index(self.device_tree)
        if index is None:
            self._fail("Select a device in the list first.")
            return
        name = self.devices[index]["name"]
        if name in self.used_devices:
            self._fail(f"'{name}' is used by saved sessions, so it can't be removed.")
            return
        if len(self.devices) == 1:
            self._fail("At least one device is needed.")
            return
        del self.devices[index]
        self._refresh_devices()
        self._fail("")

    # ------------------------------------------------------------------
    # Games
    # ------------------------------------------------------------------

    def _refresh_games(self):
        self.game_list.delete(0, "end")
        for game in self.games:
            self.game_list.insert("end", game)

    def _add_game(self):
        game = normalise_name(self.game_var.get())
        if not game:
            self._fail("Enter the game's name.")
        elif len(game) > config.MAX_GAME_LENGTH:
            self._fail(f"Game names can be up to {config.MAX_GAME_LENGTH} characters.")
        elif any(g.casefold() == game.casefold() for g in self.games):
            self._fail(f"'{game}' is already in the list.")
        elif len(self.games) >= config.MAX_CATALOG_ENTRIES:
            self._fail(f"The list can hold up to {config.MAX_CATALOG_ENTRIES} games.")
        else:
            self.games.append(game)
            self.games.sort(key=str.casefold)
            self.game_var.set("")
            self._refresh_games()
            self._fail("")

    def _remove_game(self):
        selected = self.game_list.curselection()
        if not selected:
            self._fail("Select a game in the list first.")
            return
        del self.games[selected[0]]
        self._refresh_games()
        self._fail("")

    # ------------------------------------------------------------------
    # Snacks and drinks
    # ------------------------------------------------------------------

    def _refresh_menu(self):
        self.menu_tree.delete(*self.menu_tree.get_children())
        for index, item in enumerate(self.menu):
            self.menu_tree.insert("", "end", iid=str(index), values=(
                item["name"], item["kind"], fmt_money(item["price_paise"])))

    def _menu_selected(self, _event=None):
        index = self._selected_index(self.menu_tree)
        if index is not None:
            item = self.menu[index]
            self.item_name_var.set(item["name"])
            self.item_kind_var.set(item["kind"])
            self.item_price_var.set(paise_to_input(item["price_paise"]))

    def _item_fields(self, ignore: int | None = None) -> dict | None:
        name, kind = normalise_name(self.item_name_var.get()), self.item_kind_var.get()
        if not name:
            self._fail("Enter the item's name.")
            return None
        if len(name) > config.MAX_ITEM_NAME_LENGTH:
            self._fail(f"Item names can be up to {config.MAX_ITEM_NAME_LENGTH} characters.")
            return None
        if kind not in config.ITEM_KINDS:
            self._fail("Choose whether it is a snack or a drink.")
            return None
        try:
            price = parse_money(self.item_price_var.get(), "Price")
        except ValueError as exc:
            self._fail(str(exc))
            return None
        if price > 10_000_000:
            self._fail("The price is too large.")
            return None
        if any(m["name"].casefold() == name.casefold() and m["kind"] == kind
               for i, m in enumerate(self.menu) if i != ignore):
            self._fail(f"'{name}' is already on the menu as a {kind.lower()}.")
            return None
        return {"name": name, "kind": kind, "price_paise": price}

    def _add_item(self):
        if len(self.menu) >= config.MAX_CATALOG_ENTRIES:
            self._fail(f"The menu can hold up to {config.MAX_CATALOG_ENTRIES} items.")
            return
        item = self._item_fields()
        if item is None:
            return
        self.menu.append(item)
        self.menu.sort(key=lambda m: (m["kind"], m["name"].casefold()))
        self.item_name_var.set("")
        self.item_price_var.set("")
        self._refresh_menu()
        self._fail("")

    def _update_item(self):
        index = self._selected_index(self.menu_tree)
        if index is None:
            self._fail("Select an item in the list first.")
            return
        item = self._item_fields(ignore=index)
        if item is None:
            return
        self.menu[index] = item
        self.menu.sort(key=lambda m: (m["kind"], m["name"].casefold()))
        self._refresh_menu()
        self._fail("")

    def _remove_item(self):
        index = self._selected_index(self.menu_tree)
        if index is None:
            self._fail("Select an item in the list first.")
            return
        del self.menu[index]
        self._refresh_menu()
        self._fail("")

    # ------------------------------------------------------------------
    # Reading and saving
    # ------------------------------------------------------------------

    def _fail(self, text: str):
        self.error.configure(text=text, style="Error.TLabel")

    def _hint(self, text: str):
        """A neutral message (not an error) in the same spot."""
        self.error.configure(text=text, style="Subtitle.TLabel")

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
        groups = self._groups()
        rates = {g: {n: money(self.rate_vars[g][n], f"{g} {n}-player price") for n in config.PLAYER_COUNTS}
                 for g in groups}
        half = {g: money(self.half_vars[g], f"{g} 30-minute price") for g in groups}
        missing = sorted(self.used_devices - {d["name"] for d in self.devices})
        if missing:
            errors.append(f"Saved sessions use {', '.join(missing)}, so it must stay in the device list.")
        result = dataclasses.replace(
            self.current,
            opening=times[0],
            closing=times[1],
            hourly_rates_paise=rates,
            half_hour_paise=half,
            pass_price_paise=money(self.pass_price_var, "Pass price"),
            pass_hours=whole(self.pass_hours_var, "Pass hours"),
            pass_valid_days=whole(self.pass_days_var, "Pass validity"),
            clock_24h=bool(self.clock_var.get()),
            devices=copy.deepcopy(self.devices),
            games=list(self.games),
            menu_items=copy.deepcopy(self.menu),
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
            self._fail(str(exc))
            return
        if result == self.current:
            self.destroy()
            return
        try:
            saved = self.on_save(result)
        except OSError as exc:
            dialogs.showerror("Could Not Save Configurations", str(exc), parent=self)
            return
        if saved:
            self.destroy()
