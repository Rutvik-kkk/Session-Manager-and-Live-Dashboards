"""Write a demo sessions.json for trying the app without touching real café data.

    python tools/make_demo_data.py --data-dir demo-data
    python main.py --data-dir demo-data

Refuses to write into the application's own ./data folder.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ontop.config import CLOSING_TIME, DEVICES, OPENING_TIME, PASS_DEFAULT_PRICE_PAISE  # noqa: E402
from ontop.formatting import local_datetime, now_local  # noqa: E402
from ontop.models import (  # noqa: E402
    PAYMENT_METHODS,
    Extension,
    MonthlyPass,
    Session,
    find_conflicts,
    pass_used_minutes,
    suggest_status,
)
from ontop.pricing import billable_minutes, players_problem, suggested_charge  # noqa: E402
from ontop.storage import SessionStore  # noqa: E402

NAMES = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Sana", "Vikram", "Ishaan", "Tara", "Zoya", "Arjun", "Nikhil"]
PASS_HOLDERS = [("Rahul Mehta", "9876543210"), ("Priya Shah", "9123456780"), ("Dev Patel", "9988776655")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--days", type=int, default=35)
    args = parser.parse_args()
    target = Path(args.data_dir).expanduser().resolve()
    if target == (ROOT / "data").resolve():
        print("Refusing to write demo data into the real data folder.", file=sys.stderr)
        return 2
    path = target / "sessions.json"
    if path.exists():
        print(f"{path} already exists; choose an empty folder.", file=sys.stderr)
        return 2

    rng = random.Random(7)
    store = SessionStore(path)
    store.load()
    now = now_local()
    today = now.date()

    passes = []
    for i, (name, phone) in enumerate(PASS_HOLDERS):
        bought = today - timedelta(days=4 + i * 9)
        created = local_datetime(bought, time(10, 0))
        p = MonthlyPass(f"demo-pass-{i}", name, phone, bought, PASS_DEFAULT_PRICE_PAISE,
                        rng.choice(PAYMENT_METHODS), created, created)
        store.add_pass(p)
        passes.append(p)

    sessions: list[Session] = []
    for back in range(args.days, -1, -1):
        day = today - timedelta(days=back)
        for _ in range(rng.randint(2, 8)):
            device = rng.choice(DEVICES)
            players = rng.choice((1, 1, 1, 2, 2, 3, 4))
            minutes = rng.choice((30, 60, 60, 90, 120, 180) if players == 1 else (60, 90, 120, 180))
            start = local_datetime(day, time(rng.randint(OPENING_TIME.hour, CLOSING_TIME.hour - 1),
                                             rng.choice((0, 15, 30, 45))))
            end = start + timedelta(minutes=minutes)
            if end > local_datetime(day, CLOSING_TIME) or players_problem(players, minutes):
                continue
            if find_conflicts(sessions, device, start, end):
                continue
            holder = rng.choice(passes) if rng.random() < 0.2 else None
            if holder is not None:
                fits = holder.covers(day) and (
                    pass_used_minutes(holder.id, sessions) + billable_minutes(minutes) <= holder.included_minutes)
                if not fits:
                    holder = None
            total = suggested_charge(device, players, minutes, on_pass=holder is not None)
            paid = rng.choice((total, total, total, 0, total // 2)) if total else 0
            entered = min(start, now)
            ext = []
            if rng.random() < 0.1 and end + timedelta(minutes=30) <= local_datetime(day, CLOSING_TIME):
                if not find_conflicts(sessions, device, start, end + timedelta(minutes=30)) and holder is None:
                    ext.append(Extension(entered, 30, end, end + timedelta(minutes=30)))
                    end += timedelta(minutes=30)
            sessions.append(Session(
                id=f"demo-{len(sessions):04d}", customer_name=holder.holder_name if holder else rng.choice(NAMES),
                device=device, start=start, end=end.astimezone(), payment_method=rng.choice(PAYMENT_METHODS),
                total_paise=total, paid_paise=paid, payment_status=suggest_status(total, paid), entry_time=entered,
                last_updated=entered, extensions=ext, players=players, pass_id=holder.id if holder else None,
            ))
    for s in sessions:
        store.add(s)
    print(f"Wrote {len(sessions)} demo sessions and {len(passes)} passes to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
