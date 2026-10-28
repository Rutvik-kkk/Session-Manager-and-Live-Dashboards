"""ttk theme and colour schemes shared by every tab.

Colours are module attributes read when widgets are drawn, so a scheme must be
chosen with set_palette() before the window is built.
"""

from __future__ import annotations

import colorsys
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
    "DEVICE_1": "#7c6cff", "DEVICE_2": "#38bdf8", "DEVICE_3": "#f472b6",
}

# Paid / Unpaid / Partially paid colours shared by every palette below.
_STATUS = {"SUCCESS": "#4ade80", "DANGER": "#fb7185", "WARNING": "#fbbf24"}


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _mix(a: str, b: str, t: float) -> str:
    """``t`` of the way from colour ``a`` to colour ``b``."""
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(_rgb(a), _rgb(b)))


def _luminance(color: str) -> float:
    r, g, b = (c / 255 for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hue(color: str) -> float:
    return colorsys.rgb_to_hls(*(c / 255 for c in _rgb(color)))[0]


def _distinct_from(base: str, *others: str) -> str:
    """``base`` re-hued as far as possible from every hue in ``others``."""
    _, lightness, s = colorsys.rgb_to_hls(*(c / 255 for c in _rgb(base)))
    taken = [_hue(c) for c in others]

    def gap(h: float) -> float:
        return min(min(abs(h - t), 1 - abs(h - t)) for t in taken)

    hue = max((i / 36 for i in range(36)), key=gap)
    r, g, b = colorsys.hls_to_rgb(hue, max(lightness, 0.55), max(s, 0.6))
    return "#" + "".join(f"{round(c * 255):02x}" for c in (r, g, b))


def _palette(bg: str, surface: str, text: str, accent: str, info: str) -> dict[str, str]:
    """A full scheme built from five base colours plus the shared status colours."""
    danger = _STATUS["DANGER"]
    return {
        "BG": bg, "SURFACE": surface, "TEXT": text, "ACCENT": accent, "INFO": info, **_STATUS,
        "SURFACE_2": _mix(surface, text, 0.06), "SURFACE_3": _mix(surface, text, 0.12),
        "BORDER": _mix(surface, text, 0.16), "MUTED": _mix(text, surface, 0.38),
        "DISABLED": _mix(text, surface, 0.62),
        "ACCENT_HOVER": _mix(accent, "#ffffff", 0.18), "ACCENT_DIM": _mix(accent, surface, 0.6),
        "ON_ACCENT": _mix(bg, "#000000", 0.4) if _luminance(accent) > 0.55 else "#ffffff",
        "ROW_ALT": _mix(surface, text, 0.03), "GRID_MINOR": _mix(surface, text, 0.06),
        "NOW_LINE": text, "BAR_TEXT": _mix(bg, "#000000", 0.4),
        "BANNER_BG": _mix(surface, danger, 0.22), "BANNER_FG": _mix(text, danger, 0.25),
        "DANGER_BG": _mix(surface, danger, 0.2), "DANGER_ACTIVE": _mix(surface, danger, 0.3),
        "DANGER_FG": _mix(text, danger, 0.3), "DANGER_BORDER": _mix(surface, danger, 0.5),
        "DEVICE_1": accent, "DEVICE_2": info, "DEVICE_3": _distinct_from(accent, accent, info, *_STATUS.values()),
    }


PALETTES: dict[str, dict[str, str]] = {
    "Midnight": _MIDNIGHT,
    "Koi Ember": _palette("#0a0f12", "#20292d", "#f0e6df", "#f07844", "#79c4d4"),
    "Crimson Forest": _palette("#081919", "#223330", "#eeede7", "#f05252", "#7ec8d5"),
    "Indigo Silk": _palette("#0a1123", "#242744", "#eef0fa", "#8387c3", "#9ebef5"),
    "Saffron Grove": _palette("#181d19", "#2c263f", "#f5eedd", "#f8c662", "#a9b9f0"),
    "Electric Plum": _palette("#1d0c13", "#35152d", "#edede8", "#a78bfa", "#c5f9fc"),
    "Whiskey Lounge": _palette("#150c0c", "#34150f", "#eaceaa", "#d39858", "#8fc4d4"),
    "Lilac Mist": _palette("#2a193d", "#2f2c5e", "#f0eaf5", "#b494d4", "#97c2c5"),
    "Neon Alley": _palette("#021826", "#07343b", "#e6fff4", "#06f284", "#64ddf0"),
    "Cyber Aqua": _palette("#101f30", "#1a334a", "#e8f8fc", "#27e6ec", "#a7aced"),
}
THEME_NAMES = tuple(PALETTES)
CURRENT_THEME = "Midnight"

BG = SURFACE = SURFACE_2 = SURFACE_3 = BORDER = TEXT = MUTED = DISABLED = ""
ACCENT = ACCENT_HOVER = ACCENT_DIM = ON_ACCENT = SUCCESS = DANGER = WARNING = INFO = ""
ROW_ALT = GRID_MINOR = NOW_LINE = BAR_TEXT = BANNER_BG = BANNER_FG = ""
DANGER_BG = DANGER_ACTIVE = DANGER_FG = DANGER_BORDER = DEVICE_1 = DEVICE_2 = DEVICE_3 = ""
STATUS_COLORS: dict[str, str] = {}
DEVICE_COLORS: dict[str, str] = {}


def set_palette(name: str) -> None:
    """Switch every colour constant to the named scheme (unknown names fall back to Midnight)."""
    global CURRENT_THEME
    CURRENT_THEME = name if name in PALETTES else "Midnight"
    globals().update(PALETTES[CURRENT_THEME])
    STATUS_COLORS.clear()
    STATUS_COLORS.update({STATUS_PAID: SUCCESS, STATUS_UNPAID: DANGER, STATUS_PARTIAL: WARNING})
    DEVICE_COLORS.clear()
    DEVICE_COLORS.update({"PS5(X)": DEVICE_1, "PS5(Y)": DEVICE_2, "PS4": DEVICE_3})


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
    style.configure("Mode.TLabel", background=ACCENT_DIM, foreground=TEXT, padding=(10, 3), font=FONTS["small_bold"])

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
    style.map("Treeview", background=[("selected", ACCENT_DIM)], foreground=[("selected", TEXT)])
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
