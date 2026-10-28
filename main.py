"""Entry point for On Top Gaming — Session Manager.

Usage:
    python main.py                  # data stored in ./data/sessions.json
    python main.py --data-dir PATH  # use a different data folder (e.g. for training)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

APP_DIR = Path(__file__).resolve().parent


def enable_sharp_rendering() -> None:
    """Tell Windows the app handles display scaling, so text isn't drawn small and then stretched (blurry)."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware; must run before the window exists
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="On Top Gaming — Session Manager")
    parser.add_argument("--data-dir", help="folder containing sessions.json (default: ./data next to main.py)")
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir or os.environ.get("ONTOP_DATA_DIR") or APP_DIR / "data").expanduser().resolve()

    from ontop import settings as app_settings

    settings_file = app_settings.settings_path(data_dir)
    settings, settings_warning = app_settings.load(settings_file)
    app_settings.apply(settings)

    from ontop.storage import InstanceLock, InstanceLockError, SessionStore
    from ontop.ui.app import APP_TITLE, OnTopApp, maximize

    enable_sharp_rendering()
    root = tk.Tk()
    root.withdraw()
    root.title(APP_TITLE)

    lock = InstanceLock(data_dir / "sessions.lock")
    try:
        lock.acquire()
    except InstanceLockError as exc:
        messagebox.showerror("Already running", str(exc), parent=root)
        root.destroy()
        return 1
    except OSError as exc:
        messagebox.showerror("Cannot open data folder", f"Could not use {data_dir}:\n{exc}", parent=root)
        root.destroy()
        return 1

    app = None
    try:
        store = SessionStore(data_dir / "sessions.json")
        store.load()
        app = OnTopApp(root, store, settings, settings_file)
        root.deiconify()
        maximize(root)
        if settings_warning:
            root.after(500, lambda: messagebox.showwarning("Settings not loaded", settings_warning, parent=root))
        root.mainloop()
    finally:
        lock.release()
    if app is not None and app.restart_requested:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], cwd=APP_DIR,
                         creationflags=flags)
    return 0


if __name__ == "__main__":
    sys.exit(main())
