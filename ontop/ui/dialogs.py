"""Themed replacements for tkinter.messagebox (same call style: title, message, parent=...)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import theme

_ICONS = {
    "info": ("i", "INFO"),
    "warning": ("!", "WARNING"),
    "error": ("✕", "DANGER"),
    "question": ("?", "ACCENT"),
}


class MessageDialog(tk.Toplevel):
    """A modal message in the app's colours; ``result`` is True for OK / Yes."""

    def __init__(self, parent: tk.Misc, title: str, message: str, icon: str, buttons: tuple[str, ...],
                 default: str):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(background=theme.SURFACE)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.result = False

        body = ttk.Frame(self, style="Inner.TFrame", padding=(22, 20, 22, 18))
        body.pack(fill="both", expand=True)
        glyph, color = _ICONS.get(icon, _ICONS["info"])
        size = theme.px(34)
        badge = tk.Canvas(body, width=size, height=size, background=theme.SURFACE, highlightthickness=0)
        badge.create_oval(1, 1, size - 1, size - 1, fill=getattr(theme, color), outline="")
        badge.create_text(size / 2, size / 2, text=glyph, fill=theme.BAR_TEXT, font=theme.FONTS["section"])
        badge.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 16))
        ttk.Label(body, text=title, style="CardSection.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(body, text=message, style="Card.TLabel", wraplength=theme.px(420), justify="left").grid(
            row=1, column=1, sticky="w", pady=(6, 0))

        row = ttk.Frame(body, style="Inner.TFrame")
        row.grid(row=2, column=0, columnspan=2, sticky="e", pady=(20, 0))
        for label in reversed(buttons):
            primary = label == default
            btn = ttk.Button(row, text=label, style="Accent.TButton" if primary else "TButton", width=8,
                             command=lambda ok=label in ("OK", "Yes"): self._close(ok))
            btn.pack(side="right", padx=(8, 0))
            if primary:
                btn.focus_set()
        self.bind("<Return>", lambda e: self._close(default in ("OK", "Yes")))
        self.bind("<Escape>", lambda e: self._close(len(buttons) == 1))
        self.protocol("WM_DELETE_WINDOW", lambda: self._close(len(buttons) == 1))

        self.update_idletasks()
        top = parent.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - self.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.grab_set()

    def _close(self, result: bool):
        self.result = result
        self.grab_release()
        self.destroy()


def _show(title: str, message: str, parent: tk.Misc | None, icon: str, buttons: tuple[str, ...],
          default: str, fallback) -> bool:
    if parent is None or not theme.FONTS or not parent.winfo_exists():
        return fallback(title, message, parent=parent)
    dialog = MessageDialog(parent, title, message, icon, buttons, default)
    parent.wait_window(dialog)
    return dialog.result


def showinfo(title: str, message: str, parent: tk.Misc | None = None, **_kw) -> bool:
    return _show(title, message, parent, "info", ("OK",), "OK", messagebox.showinfo)


def showwarning(title: str, message: str, parent: tk.Misc | None = None, **_kw) -> bool:
    return _show(title, message, parent, "warning", ("OK",), "OK", messagebox.showwarning)


def showerror(title: str, message: str, parent: tk.Misc | None = None, **_kw) -> bool:
    return _show(title, message, parent, "error", ("OK",), "OK", messagebox.showerror)


def askyesno(title: str, message: str, parent: tk.Misc | None = None, icon: str = "question",
             default: str = "yes", **_kw) -> bool:
    return _show(title, message, parent, icon, ("Yes", "No"), "No" if default == "no" else "Yes",
                 messagebox.askyesno)
