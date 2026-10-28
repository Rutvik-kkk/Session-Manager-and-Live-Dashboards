"""Main window: theme, header, tab navigation and cross-tab refreshes."""

from __future__ import annotations

import dataclasses
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ..formatting import fmt_datetime_long, fmt_offset, now_local
from ..settings import AppSettings, settings_path
from ..settings import save as save_settings
from ..storage import SessionStore
from . import dialogs, theme
from .dashboard_tab import DashboardTab
from .entries_tab import PreviousEntriesTab
from .entry_tab import SessionEntryTab
from .mapping_tab import SessionMappingTab
from .passes_tab import PassesTab
from .settings_dialog import SettingsDialog

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
    def __init__(self, root: tk.Tk, store: SessionStore, settings: AppSettings | None = None,
                 settings_file: Path | None = None):
        self.root = root
        self.store = store
        self.settings = settings or AppSettings()
        self.settings_file = settings_file or settings_path(store.path.parent)
        self.restart_requested = False
        root.title(APP_TITLE)
        root.minsize(1000, 660)
        theme.set_palette(self.settings.theme)
        theme.apply_theme(root)
        root.protocol("WM_DELETE_WINDOW", self.request_exit)

        self._build_header()
        self.notebook = ttk.Notebook(root, style="Main.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self.dashboard = DashboardTab(self.notebook, self)
        self.entry_area = ttk.Frame(self.notebook)
        self.entry_tabs = ttk.Notebook(self.entry_area, style="Sub.TNotebook")
        self.entry_tabs.pack(fill="both", expand=True)
        self.entry = SessionEntryTab(self.entry_tabs, self)
        self.passes = PassesTab(self.entry_tabs, self)
        self.entry_tabs.add(self.entry, text="New Session")
        self.entry_tabs.add(self.passes, text="Monthly Passes")
        self.entries = PreviousEntriesTab(self.notebook, self)
        self.mapping = SessionMappingTab(self.notebook, self)
        self.notebook.add(self.entry_area, text="Session Entry")
        self.notebook.add(self.mapping, text="Session Mapping")
        self.notebook.add(self.entries, text="Previous Entries")
        self.notebook.add(self.dashboard, text="Dashboard")
        self._build_nav()

        self.status = ttk.Label(root, style="Muted.TLabel", padding=(24, 6))
        self.status.pack(fill="x", side="bottom")
        self.set_status(f"{len(store.sessions)} session(s) loaded from {store.path}")

        self.entry._show_mode_buttons()
        self.data_changed()
        self._tick_clock()
        root.bind("<Destroy>", self._on_destroy, add="+")
        if store.load_error:
            root.after(300, self.show_load_error)

    def _build_header(self):
        header = ttk.Frame(self.root, padding=(16, 10, 24, 8))
        header.pack(fill="x")
        self.menu_button = ttk.Button(header, text="☰", style="Nav.TButton", width=3, takefocus=False,
                                      command=self.show_menu)
        self.menu_button.pack(side="left", padx=(0, 12))
        self._build_menu()
        brand = ttk.Frame(header)
        brand.pack(side="left")
        tk.Label(brand, text="▲", background=theme.BG, foreground=theme.ACCENT,
                 font=theme.FONTS["title"]).pack(side="left", padx=(0, 10))
        ttk.Label(brand, text="On Top Gaming", style="Title.TLabel").pack(side="left")
        self.clock = ttk.Label(header, style="Subtitle.TLabel")
        self.clock.pack(side="right")
        self.nav_bar = ttk.Frame(header)
        self.nav_bar.pack(side="left", padx=(28, 0))

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

    def _build_menu(self):
        colors = dict(background=theme.SURFACE_2, foreground=theme.TEXT, activebackground=theme.ACCENT,
                      activeforeground=theme.ON_ACCENT, selectcolor=theme.ACCENT, font=theme.FONTS["base"],
                      relief="flat", borderwidth=1)
        self.menu = tk.Menu(self.root, tearoff=False, **colors)
        self.menu.add_command(label="General settings…", command=self.open_settings)
        self.theme_var = tk.StringVar(value=theme.CURRENT_THEME)
        themes = tk.Menu(self.menu, tearoff=False, **colors)
        for name in theme.THEME_NAMES:
            themes.add_radiobutton(label=name, value=name, variable=self.theme_var,
                                   command=lambda n=name: self.choose_theme(n))
        self.menu.add_cascade(label="Theme", menu=themes)
        self.clock_var = tk.BooleanVar(value=self.settings.clock_24h)
        clock = tk.Menu(self.menu, tearoff=False, **colors)
        for value, label in ((True, "24-hour (18:30)"), (False, "12-hour (6:30 PM)")):
            clock.add_radiobutton(label=label, value=value, variable=self.clock_var,
                                  command=lambda v=value: self.choose_clock(v))
        self.menu.add_cascade(label="Clock format", menu=clock)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self.request_exit)

    def show_menu(self):
        b = self.menu_button
        self.menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        self.menu.grab_release()

    def open_settings(self):
        SettingsDialog(self.root, self.settings, self._save_settings)

    def choose_theme(self, name: str):
        if name == self.settings.theme:
            return
        if not self._save_settings(dataclasses.replace(self.settings, theme=name), what="Theme"):
            self.theme_var.set(self.settings.theme)

    def choose_clock(self, clock_24h: bool):
        if clock_24h == self.settings.clock_24h:
            return
        if not self._save_settings(dataclasses.replace(self.settings, clock_24h=clock_24h), what="Clock format"):
            self.clock_var.set(self.settings.clock_24h)

    def _save_settings(self, new: AppSettings, what: str = "Settings") -> bool:
        try:
            save_settings(self.settings_file, new)
        except (OSError, ValueError) as exc:
            dialogs.showerror("Could not save settings", str(exc), parent=self.root)
            return False
        self.settings = new
        if dialogs.askyesno(
            "Restart to apply",
            f"{what} saved. Restart the app now to apply the change?\n\n"
            "If you choose No, it will apply the next time the app starts.",
            parent=self.root,
        ):
            self.request_exit(restart=True, confirmed=True)
        else:
            self.set_status(f"{what} saved — restart the app to apply.")
        return True

    def request_exit(self, restart: bool = False, confirmed: bool = False):
        """Close (or restart) the app. ``confirmed`` skips the question unless unsaved form data would be lost."""
        entry = self.entry
        unsaved = entry.is_editing() or entry.name_var.get().strip() or entry._notes().strip()
        action = "Restart" if restart else "Exit"
        question = f"{action} On Top Gaming?"
        if unsaved:
            question += "\n\nThe session form has information that hasn't been saved; it will be lost."
        if (unsaved or not confirmed) and not dialogs.askyesno(
            action, question, icon="warning" if unsaved else "question", parent=self.root
        ):
            return
        self.restart_requested = restart
        self.root.destroy()

    def _build_nav(self):
        self.nav_buttons: dict[str, ttk.Button] = {}
        for page_id in self.notebook.tabs():
            btn = ttk.Button(self.nav_bar, text=self.notebook.tab(page_id, "text"), style="Nav.TButton",
                             takefocus=False, command=lambda p=page_id: self.notebook.select(p))
            btn.pack(side="left", padx=(0, 4))
            self.nav_buttons[page_id] = btn
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._sync_nav(), add="+")
        self._sync_nav()

    def _sync_nav(self):
        selected = self.notebook.select()
        for page_id, btn in self.nav_buttons.items():
            btn.configure(style="NavActive.TButton" if page_id == selected else "Nav.TButton")

    def _tick_clock(self):
        now = now_local()
        self.clock.configure(text=f"{fmt_datetime_long(now).rsplit(' (', 1)[0]}  ·  {fmt_offset(now)}")
        self._clock_job = self.root.after(15_000, self._tick_clock)

    def _on_destroy(self, event):
        if event.widget is self.root:
            self.root.after_cancel(self._clock_job)
            self.mapping.stop_timer()

    def show_load_error(self):
        dialogs.showerror(
            "Data file problem",
            f"{self.store.load_error}\n\nThe file has been preserved exactly as it is and the app will not "
            "save over it. Fix or move the file (for example restore a backup), then restart the app. "
            "Records that could be read are shown for reference.",
            parent=self.root,
        )

    def set_status(self, text: str):
        self.status.configure(text=text)

    def current_tab(self):
        """The visible page, looking inside the Session Entry sub-tabs."""
        page = self.root.nametowidget(self.notebook.select())
        if page is self.entry_area:
            return self.root.nametowidget(self.entry_tabs.select())
        return page

    def show_entry_page(self, page: ttk.Frame):
        self.notebook.select(self.entry_area)
        self.entry_tabs.select(page)

    def data_changed(self):
        """Refresh every view after a successful write, keeping their filters."""
        self.entries.refresh()
        self.passes.refresh()
        self.entry.refresh_pass()
        self.mapping.refresh()
        self.dashboard.refresh()

    def edit_session(self, session_id: str):
        if self.entry.load_session(session_id):
            self.show_entry_page(self.entry)

    def open_pass_registration(self, phone: str = "", name: str = ""):
        self.show_entry_page(self.passes)
        self.passes.prefill(phone=phone, name=name)

    def start_pass_session(self, p):
        if self.entry.start_with_pass(p):
            self.show_entry_page(self.entry)
