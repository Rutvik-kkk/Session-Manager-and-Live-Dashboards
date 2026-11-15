"""Entry point for On Top Gaming — Session Manager.

Usage:
    python main.py                  # data stored in ./data/sessions.json
    python main.py --data-dir PATH  # use a different data folder (e.g. for training)
    OnTopGaming.exe                 # packaged build: data\ and sync_config.json sit next to the .exe

Online dashboard sync is enabled by sync_config.json next to this file (or next to the .exe)
(see sync_config.example.json and cafe-web/README.md).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

# Beside main.py when run from source; beside the .exe when packaged (data/ and sync_config.json live there).
FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent


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
    from ontop.ui import dialogs
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

    from ontop.sync import STATE_FILE, SyncController, config_path, load_config

    app = None
    sync = None
    try:
        store = SessionStore(data_dir / "sessions.json")
        store.load()
        app = OnTopApp(root, store, settings, settings_file)
        sync_config, sync_problem = load_config(config_path(APP_DIR))
        sync = SyncController(root, store, sync_config, sync_problem, data_dir / STATE_FILE)
        app.attach_sync(sync)
        sync.start()
        root.deiconify()
        maximize(root)
        if settings_warning:
            root.after(500, lambda: dialogs.showwarning("Configurations Not Loaded", settings_warning, parent=root))
        root.mainloop()
    finally:
        if sync is not None:
            sync.stop()
        lock.release()
    if app is not None and app.restart_requested:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        env = None
        if FROZEN:  # a one-file .exe must unpack itself afresh rather than reuse this run's temporary folder
            command = [sys.executable, *sys.argv[1:]]
            env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
        else:
            command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
        subprocess.Popen(command, cwd=APP_DIR, creationflags=flags, env=env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
