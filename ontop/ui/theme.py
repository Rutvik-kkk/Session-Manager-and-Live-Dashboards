"""Dark ttk theme shared by every tab."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..models import STATUS_PAID, STATUS_PARTIAL, STATUS_UNPAID

BG = "#0e121a"
SURFACE = "#161c27"
SURFACE_2 = "#1f2735"
SURFACE_3 = "#283245"
BORDER = "#2c3649"
TEXT = "#e8ebf1"
MUTED = "#97a1b3"
ACCENT = "#7c6cff"
ACCENT_HOVER = "#9184ff"
ACCENT_DIM = "#3b3577"
SUCCESS = "#22c55e"
DANGER = "#ef4444"
WARNING = "#f59e0b"
INFO = "#38bdf8"

STATUS_COLORS = {
    STATUS_PAID: SUCCESS,
    STATUS_UNPAID: DANGER,
    STATUS_PARTIAL: WARNING,
}

DEVICE_COLORS = {"ps5A": "#7c6cff", "ps5B": "#38bdf8", "ps4": "#f472b6"}

FONTS: dict[str, tkfont.Font] = {}


def _pick_family(root: tk.Misc) -> str:
    available = set(tkfont.families(root))
    for family in ("Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue", "Noto Sans", "DejaVu Sans", "Ubuntu"):
        if family in available:
            return family
    return tkfont.nametofont("TkDefaultFont").actual("family")


def apply_theme(root: tk.Tk) -> None:
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
        selectforeground="#ffffff",
        insertcolor=TEXT,
        font=FONTS["base"],
    )
    style.map(".", foreground=[("disabled", "#5d6679")])

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE, bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("Inner.TFrame", background=SURFACE)
    style.configure("Banner.TFrame", background="#3a1518")

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
    style.configure("Banner.TLabel", background="#3a1518", foreground="#fecaca")
    style.configure("Mode.TLabel", background=ACCENT_DIM, foreground="#ffffff", padding=(10, 3), font=FONTS["small_bold"])

    style.configure("TButton", background=SURFACE_2, foreground=TEXT, padding=(12, 6), borderwidth=1, focusthickness=0)
    style.map(
        "TButton",
        background=[("disabled", SURFACE), ("pressed", SURFACE_3), ("active", SURFACE_3)],
        bordercolor=[("focus", ACCENT)],
    )
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT, font=FONTS["bold"])
    style.map(
        "Accent.TButton",
        background=[("disabled", ACCENT_DIM), ("pressed", ACCENT_HOVER), ("active", ACCENT_HOVER)],
        bordercolor=[("focus", "#ffffff")],
    )
    style.configure("Danger.TButton", background="#4a1d22", foreground="#fecaca", bordercolor="#7f1d1d")
    style.map("Danger.TButton", background=[("pressed", "#5f2328"), ("active", "#5f2328")])
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
        foreground=[("readonly", TEXT), ("disabled", "#5d6679")],
        selectbackground=[("readonly", SURFACE_2)],
        selectforeground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
        background=[("active", SURFACE_3)],
    )
    root.option_add("*TCombobox*Listbox.background", SURFACE_2)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", FONTS["base"])

    style.configure("TSpinbox", fieldbackground=SURFACE_2, background=SURFACE_2, foreground=TEXT, arrowcolor=TEXT, padding=5)
    style.map("TSpinbox", bordercolor=[("focus", ACCENT)], fieldbackground=[("disabled", SURFACE)])

    for name, bg in (("TCheckbutton", BG), ("Card.TCheckbutton", SURFACE)):
        style.configure(name, background=bg, foreground=TEXT, indicatorbackground=SURFACE_2, indicatorforeground="#ffffff")
        style.map(
            name,
            background=[("active", bg)],
            indicatorbackground=[("selected", ACCENT), ("active", SURFACE_3)],
        )

    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(16, 8, 16, 0))
    style.configure("TNotebook.Tab", background=SURFACE, foreground=MUTED, padding=(22, 9), borderwidth=0, font=FONTS["bold"])
    style.map(
        "TNotebook.Tab",
        background=[("selected", ACCENT), ("active", SURFACE_2)],
        foreground=[("selected", "#ffffff"), ("active", TEXT)],
        lightcolor=[("selected", ACCENT)],
    )

    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        rowheight=28,
        borderwidth=0,
    )
    style.map("Treeview", background=[("selected", ACCENT_DIM)], foreground=[("selected", "#ffffff")])
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
