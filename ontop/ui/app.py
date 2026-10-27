"""Main window: theme, header, tab navigation and cross-tab refreshes."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..formatting import fmt_datetime_long, fmt_offset, now_local
from ..storage import SessionStore
from . import theme
from .dashboard_tab import DashboardTab
from .entries_tab import PreviousEntriesTab
from .entry_tab import SessionEntryTab
from .mapping_tab import SessionMappingTab

APP_TITLE = "On Top Gaming — Session Manager"


def maximize(root: tk.Tk) -> None:
    try:
        root.state("zoomed")  # Windows and macOS
        return
    except tk.TclError:
        pass
    try:
        root.attributes("-zoomed", True)  # X11
    except tk.TclError:
        root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")


class OnTopApp:
    def __init__(self, root: tk.Tk, store: SessionStore):
        self.root = root
        self.store = store
        root.title(APP_TITLE)
        root.minsize(1000, 660)
        theme.apply_theme(root)

        self._build_header()
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)
        self.dashboard = DashboardTab(self.notebook, self)
        self.entry = SessionEntryTab(self.notebook, self)
        self.entries = PreviousEntriesTab(self.notebook, self)
        self.mapping = SessionMappingTab(self.notebook, self)
        self.notebook.add(self.dashboard, text="Dashboard")
        self.notebook.add(self.entry, text="Session Entry")
        self.notebook.add(self.entries, text="Previous Entries")
        self.notebook.add(self.mapping, text="Session Mapping")

        self.status = ttk.Label(root, style="Muted.TLabel", padding=(24, 6))
        self.status.pack(fill="x", side="bottom")
        self.set_status(f"{len(store.sessions)} session(s) loaded from {store.path}")

        self.entry._show_mode_buttons()
        self.data_changed()
        self._tick_clock()
        if store.load_error:
            root.after(300, self.show_load_error)

    def _build_header(self):
        header = ttk.Frame(self.root, padding=(24, 14, 24, 4))
        header.pack(fill="x")
        brand = ttk.Frame(header)
        brand.pack(side="left")
        tk.Label(brand, text="▲", background=theme.BG, foreground=theme.ACCENT,
                 font=theme.FONTS["title"]).pack(side="left", padx=(0, 10))
        ttk.Label(brand, text="On Top Gaming", style="Title.TLabel").pack(side="left")
        ttk.Label(brand, text="Session Manager", style="Subtitle.TLabel").pack(side="left", padx=(10, 0), pady=(7, 0))
        self.clock = ttk.Label(header, style="Subtitle.TLabel")
        self.clock.pack(side="right", pady=(6, 0))

        if self.store.load_error:
            banner = ttk.Frame(self.root, style="Banner.TFrame", padding=(24, 8))
            banner.pack(fill="x")
            ttk.Label(
                banner,
                style="Banner.TLabel",
                text="Read-only mode: the saved data file has a problem, so saving is disabled to protect it. "
                     "The file has not been modified.",
            ).pack(side="left")
            ttk.Button(banner, text="Details", style="Small.TButton", command=self.show_load_error).pack(side="right")

    def _tick_clock(self):
        now = now_local()
        self.clock.configure(text=f"{fmt_datetime_long(now).rsplit(' (', 1)[0]}  ·  {fmt_offset(now)}")
        self.root.after(15_000, self._tick_clock)

    def show_load_error(self):
        messagebox.showerror(
            "Data file problem",
            f"{self.store.load_error}\n\nThe file has been preserved exactly as it is and the app will not "
            "save over it. Fix or move the file (for example restore a backup), then restart the app. "
            "Records that could be read are shown for reference.",
            parent=self.root,
        )

    def set_status(self, text: str):
        self.status.configure(text=text)

    def current_tab(self):
        return self.root.nametowidget(self.notebook.select())

    def data_changed(self):
        """Refresh every view after a successful write, keeping their filters."""
        self.entries.refresh()
        self.mapping.refresh()
        self.dashboard.refresh()

    def edit_session(self, session_id: str):
        if self.entry.load_session(session_id):
            self.notebook.select(self.entry)
