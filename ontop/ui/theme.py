"""ttk theme and colour schemes shared by every tab.

Colours are module attributes read when widgets are drawn, so a scheme must be
chosen with set_palette() before the window is built.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..models import STATUS_PAID, STATUS_PARTIAL, STATUS_UNPAID

_MIDNIGHT = {
    "BG": "#0e121a", "SURFACE": "#161c27", "SURFACE_2": "#1f2735", "SURFACE_3": "#283245",
    "BORDER": "#2c3649", "TEXT": "#e8ebf1", "MUTED": "#97a1b3", "DISABLED": "#5d6679",
    "ACCENT": "#7c6cff", "ACCENT_HOVER": "#9184ff", "ACCENT_DIM": "#3b3577", "ON_ACCENT": "#ffffff",
    "SUCCESS": "#22c55e", "DANGER": "#ef4444", "WARNING": "#f59e0b", "INFO": "#38bdf8",
    "ROW_ALT": "#1a2130", "GRID_MINOR": "#1f2838", "NOW_LINE": "#f8fafc", "BAR_TEXT": "#0b0f17",
    "BANNER_BG": "#3a1518", "BANNER_FG": "#fecaca",
    "DANGER_BG": "#4a1d22", "DANGER_ACTIVE": "#5f2328", "DANGER_FG": "#fecaca", "DANGER_BORDER": "#7f1d1d",
}

PALETTES: dict[str, dict[str, str]] = {
    "Midnight": _MIDNIGHT,
    "Ocean": _MIDNIGHT | {
        "BG": "#0b1520", "SURFACE": "#112130", "SURFACE_2": "#182c3f", "SURFACE_3": "#21384f",
        "BORDER": "#26405a", "MUTED": "#94a9bd", "DISABLED": "#56708a",
        "ACCENT": "#0ea5e9", "ACCENT_HOVER": "#38bdf8", "ACCENT_DIM": "#0c4a6e", "INFO": "#a78bfa",
        "ROW_ALT": "#14273a", "GRID_MINOR": "#1a3044",
    },
    "Emerald": _MIDNIGHT | {
        "BG": "#0b1411", "SURFACE": "#111f1a", "SURFACE_2": "#182b24", "SURFACE_3": "#21382f",
        "BORDER": "#264237", "MUTED": "#95b3a6", "DISABLED": "#587567",
        "ACCENT": "#10b981", "ACCENT_HOVER": "#34d399", "ACCENT_DIM": "#065f46", "SUCCESS": "#84cc16",
        "ROW_ALT": "#14241e", "GRID_MINOR": "#1a2f27",
    },
    "Sunset": _MIDNIGHT | {
        "BG": "#16100e", "SURFACE": "#201815", "SURFACE_2": "#2c211d", "SURFACE_3": "#3a2c26",
        "BORDER": "#47362f", "MUTED": "#bba79e", "DISABLED": "#7a665d",
        "ACCENT": "#f97316", "ACCENT_HOVER": "#fb923c", "ACCENT_DIM": "#7c2d12", "WARNING": "#facc15",
        "ROW_ALT": "#261d19", "GRID_MINOR": "#2e231f",
    },
    "Light": {
        "BG": "#eef1f6", "SURFACE": "#ffffff", "SURFACE_2": "#f1f4f9", "SURFACE_3": "#e2e8f0",
        "BORDER": "#cbd5e1", "TEXT": "#111827", "MUTED": "#5b6474", "DISABLED": "#a0a8b6",
        "ACCENT": "#6d5dfc", "ACCENT_HOVER": "#5b4bf0", "ACCENT_DIM": "#8b7dfd", "ON_ACCENT": "#ffffff",
        "SUCCESS": "#16a34a", "DANGER": "#dc2626", "WARNING": "#d97706", "INFO": "#0284c7",
        "ROW_ALT": "#f6f8fb", "GRID_MINOR": "#e5e9f0", "NOW_LINE": "#111827", "BAR_TEXT": "#ffffff",
        "BANNER_BG": "#fee2e2", "BANNER_FG": "#7f1d1d",
        "DANGER_BG": "#fee2e2", "DANGER_ACTIVE": "#fecaca", "DANGER_FG": "#991b1b", "DANGER_BORDER": "#fca5a5",
    },
}
THEME_NAMES = tuple(PALETTES)
CURRENT_THEME = "Midnight"

BG = SURFACE = SURFACE_2 = SURFACE_3 = BORDER = TEXT = MUTED = DISABLED = ""
ACCENT = ACCENT_HOVER = ACCENT_DIM = ON_ACCENT = SUCCESS = DANGER = WARNING = INFO = ""
ROW_ALT = GRID_MINOR = NOW_LINE = BAR_TEXT = BANNER_BG = BANNER_FG = ""
DANGER_BG = DANGER_ACTIVE = DANGER_FG = DANGER_BORDER = ""
STATUS_COLORS: dict[str, str] = {}
DEVICE_COLORS = {"PS5(X)": "#7c6cff", "PS5(Y)": "#38bdf8", "PS4": "#f472b6"}


def set_palette(name: str) -> None:
    """Switch every colour constant to the named scheme (unknown names fall back to Midnight)."""
    global CURRENT_THEME
    CURRENT_THEME = name if name in PALETTES else "Midnight"
    globals().update(PALETTES[CURRENT_THEME])
    STATUS_COLORS.clear()
    STATUS_COLORS.update({STATUS_PAID: SUCCESS, STATUS_UNPAID: DANGER, STATUS_PARTIAL: WARNING})


set_palette("Midnight")

FONTS: dict[str, tkfont.Font] = {}

# Display scale relative to 96 DPI (1.25 on a "125%" Windows display); set by apply_theme.
SCALE = 1.0


def px(value: float) -> int:
    """Pixel size scaled for the display, so layouts keep pace with point-sized fonts."""
    return round(value * SCALE)


def _pick_family(root: tk.Misc) -> str:
    available = set(tkfont.families(root))
    for family in ("Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "Noto Sans", "DejaVu Sans", "Ubuntu"):
        if family in available:
            return family
    return tkfont.nametofont("TkDefaultFont").actual("family")


def apply_theme(root: tk.Tk) -> None:
    global SCALE
    SCALE = max(1.0, root.winfo_fpixels("1i") / 96)
    family = _pick_family(root)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=family, size=10)
    FONTS["base"] = tkfont.Font(root, family=family, size=10)
    FONTS["small"] = tkfont.Font(root, family=family, size=9)
    FONTS["bold"] = tkfont.Font(root, family=family, size=10, weight="bold")
    FONTS["small_bold"] = tkfont.Font(root, family=family, size=9, weight="bold")
    FONTS["section"] = tkfont.Font(root, family=family, size=12, weight="bold")
    FONTS["title"] = tkfont.Font(root, family=family, size=17, weight="bold")
    FONTS["metric"] = tkfont.Font(root, family=family, size=18, weight="bold")

    root.configure(background=BG)
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(
        ".",
        background=BG,
        foreground=TEXT,
        fieldbackground=SURFACE_2,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        troughcolor=SURFACE,
        focuscolor=ACCENT,
        selectbackground=ACCENT,
        selectforeground=ON_ACCENT,
        insertcolor=TEXT,
        font=FONTS["base"],
    )
    style.map(".", foreground=[("disabled", DISABLED)])

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE, bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("Inner.TFrame", background=SURFACE)
    style.configure("Banner.TFrame", background=BANNER_BG)

    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Title.TLabel", font=FONTS["title"])
    style.configure("Subtitle.TLabel", foreground=MUTED)
    style.configure("Card.TLabel", background=SURFACE)
    style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("CardSmall.TLabel", background=SURFACE, foreground=MUTED, font=FONTS["small"])
    style.configure("CardSection.TLabel", background=SURFACE, font=FONTS["section"])
    style.configure("CardMetric.TLabel", background=SURFACE, font=FONTS["metric"])
    style.configure("CardError.TLabel", background=SURFACE, foreground=DANGER)
    style.configure("CardWarn.TLabel", background=SURFACE, foreground=WARNING)
    style.configure("CardOk.TLabel", background=SURFACE, foreground=SUCCESS)
    style.configure("CardInfo.TLabel", background=SURFACE, foreground=INFO)
    style.configure("Error.TLabel", foreground=DANGER)
    style.configure("Banner.TLabel", background=BANNER_BG, foreground=BANNER_FG)
    style.configure("Mode.TLabel", background=ACCENT_DIM, foreground=ON_ACCENT, padding=(10, 3), font=FONTS["small_bold"])

    style.configure("TButton", background=SURFACE_2, foreground=TEXT, padding=(12, 6), borderwidth=1, focusthickness=0)
    style.map(
        "TButton",
        background=[("disabled", SURFACE), ("pressed", SURFACE_3), ("active", SURFACE_3)],
        bordercolor=[("focus", ACCENT)],
    )
    style.configure("Accent.TButton", background=ACCENT, foreground=ON_ACCENT, bordercolor=ACCENT, font=FONTS["bold"])
    style.map(
        "Accent.TButton",
        background=[("disabled", ACCENT_DIM), ("pressed", ACCENT_HOVER), ("active", ACCENT_HOVER)],
        bordercolor=[("focus", ON_ACCENT)],
    )
    style.configure("Danger.TButton", background=DANGER_BG, foreground=DANGER_FG, bordercolor=DANGER_BORDER)
    style.map("Danger.TButton", background=[("pressed", DANGER_ACTIVE), ("active", DANGER_ACTIVE)])
    style.configure("Small.TButton", padding=(8, 3), font=FONTS["small"])
    style.configure("Chip.TButton", padding=(10, 4), background=SURFACE_3)

    style.configure("TEntry", fieldbackground=SURFACE_2, foreground=TEXT, padding=6, insertcolor=TEXT)
    style.map(
        "TEntry",
        fieldbackground=[("readonly", SURFACE), ("disabled", SURFACE)],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
    )
    style.configure("Invalid.TEntry", bordercolor=DANGER, lightcolor=DANGER, darkcolor=DANGER)
    style.configure("Balance.TEntry", fieldbackground=SURFACE, foreground=TEXT)

    style.configure(
        "TCombobox",
        fieldbackground=SURFACE_2,
        background=SURFACE_2,
        foreground=TEXT,
        arrowcolor=TEXT,
        padding=5,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", SURFACE_2), ("disabled", SURFACE)],
        foreground=[("readonly", TEXT), ("disabled", DISABLED)],
        selectbackground=[("readonly", SURFACE_2)],
        selectforeground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
        background=[("active", SURFACE_3)],
    )
    root.option_add("*TCombobox*Listbox.background", SURFACE_2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", ON_ACCENT)
    root.option_add("*TCombobox*Listbox.font", FONTS["base"])

    style.configure("TSpinbox", fieldbackground=SURFACE_2, background=SURFACE_2, foreground=TEXT, arrowcolor=TEXT, padding=5)
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)], fieldbackground=[("disabled", SURFACE)])

    for name, bg in (("TCheckbutton", BG), ("Card.TCheckbutton", SURFACE)):
        style.configure(name, background=bg, foreground=TEXT, indicatorbackground=SURFACE_2, indicatorforeground=ON_ACCENT)
        style.map(
            name,
            background=[("active", bg)],
            indicatorbackground=[("selected", ACCENT), ("active", SURFACE_3)],
        )

    style.configure("Nav.TButton", background=SURFACE, foreground=MUTED, padding=(18, 7), borderwidth=0,
                    bordercolor=BG, font=FONTS["bold"])
    style.map("Nav.TButton", background=[("pressed", SURFACE_3), ("active", SURFACE_2)],
              foreground=[("active", TEXT)])
    style.configure("NavActive.TButton", background=ACCENT, foreground=ON_ACCENT, padding=(18, 7), borderwidth=0,
                    bordercolor=BG, font=FONTS["bold"])
    style.map("NavActive.TButton", background=[("pressed", ACCENT_HOVER), ("active", ACCENT_HOVER)])

    # Main pages are switched with the header buttons, so this notebook draws no tab strip.
    style.layout("Main.TNotebook.Tab", [])
    style.configure("Main.TNotebook", background=BG, borderwidth=0, tabmargins=0)

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(16, 8, 16, 0))
    style.configure("TNotebook.Tab", background=SURFACE, foreground=MUTED, padding=(22, 9), borderwidth=0, font=FONTS["bold"])
    style.map(
        "TNotebook.Tab",
        background=[("selected", ACCENT), ("active", SURFACE_2)],
        foreground=[("selected", ON_ACCENT), ("active", TEXT)],
        lightcolor=[("selected", ACCENT)],
    )

    style.configure("Sub.TNotebook", background=BG, borderwidth=0, tabmargins=(24, 4, 24, 0))
    style.configure("Sub.TNotebook.Tab", background=BG, foreground=MUTED, padding=(16, 6), borderwidth=0,
                    font=FONTS["bold"])
    style.map(
        "Sub.TNotebook.Tab",
        background=[("selected", SURFACE_2), ("active", SURFACE)],
        foreground=[("selected", TEXT), ("active", TEXT)],
        lightcolor=[("selected", ACCENT)],
    )

    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        rowheight=px(28),
        borderwidth=0,
    )
    style.map("Treeview", background=[("selected", ACCENT_DIM)], foreground=[("selected", ON_ACCENT)])
    style.configure("Treeview.Heading", background=SURFACE_2, foreground=TEXT, padding=(6, 6), font=FONTS["small_bold"], relief="flat")
    style.map("Treeview.Heading", background=[("active", SURFACE_3)])

    for orient in ("Vertical", "Horizontal"):
        style.configure(
            f"{orient}.TScrollbar",
            background=SURFACE_2,
            troughcolor=BG,
            arrowcolor=MUTED,
            bordercolor=BG,
            gripcount=0,
        )
        style.map(f"{orient}.TScrollbar", background=[("active", SURFACE_3)])

    style.configure("TSeparator", background=BORDER)
