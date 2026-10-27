"""Entry point for On Top Gaming — Session Manager.

Usage:
    python main.py                  # data stored in ./data/sessions.json
    python main.py --data-dir PATH  # use a different data folder (e.g. for training)
"""

from __future__ import annotations

import argparse
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

APP_DIR = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="On Top Gaming — Session Manager")
    parser.add_argument("--data-dir", help="folder containing sessions.json (default: ./data next to main.py)")
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir or os.environ.get("ONTOP_DATA_DIR") or APP_DIR / "data").expanduser().resolve()

    from ontop.storage import InstanceLock, InstanceLockError, SessionStore
    from ontop.ui.app import APP_TITLE, OnTopApp, maximize

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

    try:
        store = SessionStore(data_dir / "sessions.json")
        store.load()
        OnTopApp(root, store)
        root.deiconify()
        maximize(root)
        root.mainloop()
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
