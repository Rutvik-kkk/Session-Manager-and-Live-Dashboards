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
    "DEVICE_1": "#7c6cff", "DEVICE_2": "#38bdf8", "DEVICE_3": "#f472b6",
}

# Paid / Unpaid / Partially paid colours shared by every palette below.
_STATUS = {"SUCCESS": "#4ade80", "DANGER": "#fb7185", "WARNING": "#fbbf24"}


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _mix(a: str, b: str, t: float) -> str:
    """``t`` of the way from colour ``a`` to colour ``b``."""
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(_rgb(a), _rgb(b)))


def _palette(
    bg: str, surface: str, surface_2: str, surface_3: str, text: str, muted: str,
    accent: str, on_accent: str, info: str, devices: tuple[str, str, str],
) -> dict[str, str]:
    """A full scheme from hand-picked main colours; the minor shades are blended from them."""
    danger = _STATUS["DANGER"]
    return {
        "BG": bg, "SURFACE": surface, "SURFACE_2": surface_2, "SURFACE_3": surface_3,
        "TEXT": text, "MUTED": muted, "ACCENT": accent, "ON_ACCENT": on_accent, "INFO": info, **_STATUS,
        "BORDER": _mix(surface, text, 0.14), "DISABLED": _mix(muted, surface, 0.45),
        "ACCENT_HOVER": _mix(accent, "#ffffff", 0.16), "ACCENT_DIM": _mix(accent, surface, 0.58),
        "ROW_ALT": _mix(surface, text, 0.035), "GRID_MINOR": _mix(surface, text, 0.07),
        "NOW_LINE": text, "BAR_TEXT": _mix(bg, "#000000", 0.45),
        "BANNER_BG": _mix(surface, danger, 0.22), "BANNER_FG": _mix(text, danger, 0.25),
        "DANGER_BG": _mix(surface, danger, 0.2), "DANGER_ACTIVE": _mix(surface, danger, 0.3),
        "DANGER_FG": _mix(text, danger, 0.3), "DANGER_BORDER": _mix(surface, danger, 0.5),
        "DEVICE_1": devices[0], "DEVICE_2": devices[1], "DEVICE_3": devices[2],
    }


PALETTES: dict[str, dict[str, str]] = {
    "Midnight": _MIDNIGHT,
    "Dusk Blue": _palette("#24293e", "#2f3552", "#3a4163", "#454d73", "#f4f5fc", "#9ba1bd",
                          "#8ebbff", "#1b2033", "#f2a7b8", ("#8ebbff", "#f2a7b8", "#c3a6f5")),
    "Lavender Haze": _palette("#2a2438", "#352f44", "#433b55", "#5c5470", "#f1effa", "#aaa3bd",
                              "#dbd8e3", "#2a2438", "#a99be0", ("#b8a6f0", "#8fc1e3", "#f0b8c8")),
    "Alpine Dusk": _palette("#181e31", "#2d3250", "#3a4064", "#424769", "#f7f7fb", "#a3a8c8",
                            "#f9b17a", "#2d3250", "#8f98d6", ("#f9b17a", "#8f98d6", "#e9d8c4")),
    "Twinkle Sand": _palette("#1c1f2e", "#2a2f42", "#363d52", "#434c60", "#ece6dc", "#97a7ad",
                             "#c9a37e", "#1e2133", "#9fb6bd", ("#c9a37e", "#9fb6bd", "#e8dcc8")),
    "Violet Glass": _palette("#1d1550", "#2b2070", "#382c88", "#45389c", "#f4f2ff", "#b2aade",
                             "#8a78ff", "#ffffff", "#7fb8ff", ("#a596ff", "#7fb8ff", "#f08ad8")),
    "Forest Lodge": _palette("#072a20", "#0c3b2e", "#14493a", "#1c5847", "#f3f1e7", "#a8c0b0",
                             "#6d9773", "#ffffff", "#d9a86c", ("#8fbf96", "#d9a86c", "#ece4cc")),
}
THEME_NAMES = tuple(PALETTES)
CURRENT_THEME = "Midnight"
# Themes drawn with the original square, bordered widgets; the rest use rounded, borderless ones.
CLASSIC_THEMES = frozenset({"Midnight"})

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
# Gap between a card's edge and its content, wide enough to keep rounded corners visible.
CARD_INSET = 1


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

    if CURRENT_THEME not in CLASSIC_THEMES:
        _apply_rounded_shapes(root, style)


def _rounded_image(root: tk.Misc, fill: str, radius: int, outline: str | None = None):
    """An anti-aliased rounded rectangle with transparent corners, for 9-slice image elements."""
    from PIL import Image, ImageDraw, ImageTk

    size, scale = radius * 2 + 12, 4
    img = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(
        (0, 0, size * scale - 1, size * scale - 1), radius=radius * scale, fill=fill,
        outline=outline, width=max(1, round(SCALE * 1.5)) * scale if outline else 0,
    )
    return ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS), master=root)


def _arrow_image(root: tk.Misc, color: str, up: bool = False):
    """A small anti-aliased triangle on a transparent background."""
    from PIL import Image, ImageDraw, ImageTk

    w, h, scale = px(9), px(5), 4
    img = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    points = [(0, 0), (w * scale, 0), (w * scale / 2, h * scale)]
    if up:
        points = [(x, h * scale - y) for x, y in points]
    ImageDraw.Draw(img).polygon(points, fill=color)
    return ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS), master=root)


def _parent_background(style: ttk.Style, widget: tk.Misc) -> str:
    parent = widget.master
    if isinstance(parent, ttk.Widget):
        return style.lookup(str(parent.cget("style")) or parent.winfo_class(), "background")
    try:
        return str(parent.cget("background"))
    except tk.TclError:
        return ""


def _replace_element(layout: list, old: str, new: str) -> list:
    out = []
    for name, opts in layout:
        opts = dict(opts)
        opts.pop("border", None)
        if "children" in opts:
            opts["children"] = _replace_element(opts["children"], old, new)
        out.append((new if name == old else name, opts))
    return out


def _apply_rounded_shapes(root: tk.Misc, style: ttk.Style) -> None:
    """Rounded, borderless cards, buttons and fields in the style of modern app mock-ups."""
    try:
        import PIL.ImageTk  # noqa: F401
    except ImportError:
        return
    images: list = []
    root._rounded_images = images  # PhotoImages vanish once unreferenced

    def element(name: str, radius: int, normal: tuple, states=(), padding=0) -> None:
        def image(colors: tuple):
            img = _rounded_image(root, colors[0], radius, colors[1] if len(colors) > 1 else None)
            images.append(img)
            return img

        base = image(normal)
        specs = [(state, image(colors)) for state, colors in states]
        try:
            style.element_create(name, "image", base, *specs, border=radius + 2, padding=padding, sticky="nsew")
        except tk.TclError:
            pass  # already created for this interpreter

    card_r, button_r, field_r = px(14), px(8), px(7)
    global CARD_INSET
    CARD_INSET = round(card_r * 0.32) + 1
    element("Rounded.card", card_r, (SURFACE,))
    style.layout("Card.TFrame", [("Rounded.card", {"sticky": "nsew"})])
    style.configure("Card.TFrame", background=BG)

    button_layout = _replace_element(style.layout("TButton"), "Button.border", "{}")
    buttons = {
        "TButton": ((SURFACE_2,), [("disabled", (SURFACE,)), ("pressed", (SURFACE_3,)), ("active", (SURFACE_3,))]),
        "Accent.TButton": ((ACCENT,), [("disabled", (ACCENT_DIM,)), ("pressed", (ACCENT_HOVER,)),
                                       ("active", (ACCENT_HOVER,))]),
        "Danger.TButton": ((DANGER_BG, DANGER_BORDER), [("pressed", (DANGER_ACTIVE, DANGER_BORDER)),
                                                        ("active", (DANGER_ACTIVE, DANGER_BORDER))]),
        "Chip.TButton": ((SURFACE_3,), [("pressed", (_mix(SURFACE_3, TEXT, 0.14),)),
                                        ("active", (_mix(SURFACE_3, TEXT, 0.08),))]),
        "Nav.TButton": ((SURFACE,), [("pressed", (SURFACE_3,)), ("active", (SURFACE_2,))]),
        "NavActive.TButton": ((ACCENT,), [("pressed", (ACCENT_HOVER,)), ("active", (ACCENT_HOVER,))]),
    }
    for name, (normal, states) in buttons.items():
        el = f"Rounded.{name}.border"
        element(el, button_r, normal, states)
        style.layout(name, _replace_element(button_layout, "{}", el))
        style.configure(name, background=BG if name.startswith("Nav") else SURFACE)
        style.map(name, background=[])
    style.layout("Small.TButton", style.layout("TButton"))
    style.configure("Nav.TButton", padding=(20, 7))
    style.configure("NavActive.TButton", padding=(20, 7))

    field_states = [
        ("disabled", (SURFACE, BORDER)), ("readonly !focus", (SURFACE, BORDER)), ("focus", (SURFACE_2, ACCENT)),
    ]
    element("Rounded.field", field_r, (SURFACE_2,), field_states, padding=px(3))
    element("Rounded.select", field_r, (SURFACE_2,), [("disabled", (SURFACE, BORDER)), ("focus", (SURFACE_2, ACCENT))],
            padding=px(3))
    element("Rounded.invalid", field_r, (SURFACE_2, DANGER), padding=px(3))
    entry = _replace_element(style.layout("TEntry"), "Entry.field", "Rounded.field")
    style.layout("TEntry", entry)
    style.layout("Balance.TEntry", entry)
    style.layout("Invalid.TEntry", _replace_element(entry, "Rounded.field", "Rounded.invalid"))
    style.configure("TEntry", padding=(6, 3), background=SURFACE)
    style.map("TEntry", background=[])

    element("Rounded.tab", button_r, (BG,), [("selected", (SURFACE_2,)), ("active", (SURFACE,))])
    style.layout("Sub.TNotebook.Tab", _replace_element(style.layout("TNotebook.Tab"), "Notebook.tab", "Rounded.tab"))
    style.map("Sub.TNotebook.Tab", background=[], expand=[])
    style.configure("Sub.TNotebook.Tab", padding=(16, 6))
    for name in ("Main.TNotebook", "Sub.TNotebook", "TNotebook"):
        style.configure(name, bordercolor=BG, lightcolor=BG, darkcolor=BG)
    style.configure("Treeview", bordercolor=SURFACE_2, lightcolor=SURFACE_2, darkcolor=SURFACE_2)

    for name, up in (("Rounded.downarrow", False), ("Rounded.uparrow", True)):
        normal, faded = _arrow_image(root, MUTED, up), _arrow_image(root, DISABLED, up)
        hover = _arrow_image(root, TEXT, up)
        images.extend((normal, faded, hover))
        try:
            style.element_create(name, "image", normal, ("disabled", faded), ("active", hover),
                                 sticky="", padding=(px(6), px(1)))
        except tk.TclError:
            pass

    style.layout("TCombobox", [("Rounded.select", {"sticky": "nsew", "children": [
        ("Rounded.downarrow", {"side": "right", "sticky": "ns"}),
        ("Combobox.padding", {"sticky": "nsew", "children": [("Combobox.textarea", {"sticky": "nsew"})]}),
    ]})])
    spinbox = _replace_element(style.layout("TSpinbox"), "Spinbox.field", "Rounded.select")
    spinbox = _replace_element(spinbox, "Spinbox.uparrow", "Rounded.uparrow")
    style.layout("TSpinbox", _replace_element(spinbox, "Spinbox.downarrow", "Rounded.downarrow"))
    for name in ("TCombobox", "TSpinbox"):
        style.configure(name, padding=(5, 2), background=SURFACE)
        style.map(name, background=[])

    # ttk paints a widget's own background into the transparent corners, so each rounded
    # widget takes the background of whatever it sits on.
    def match_parent(event: tk.Event) -> None:
        widget = event.widget
        if not isinstance(widget, ttk.Widget):
            return
        current = str(widget.cget("style")) or widget.winfo_class()
        bg = _parent_background(style, widget)
        if not bg or style.lookup(current, "background") == bg:
            return
        fitted = f"On{bg.lstrip('#')}.{current.split('.', 1)[1] if current.startswith('On') else current}"
        style.configure(fitted, background=bg)
        widget.configure(style=fitted)

    for cls in ("TButton", "TEntry", "TCombobox", "TSpinbox"):
        root.bind_class(cls, "<Map>", match_parent, add="+")
