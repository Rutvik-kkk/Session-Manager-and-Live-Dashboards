"""Write a demo sessions.json for trying the app without touching real café data.

    python tools/make_demo_data.py --data-dir /tmp/ontop-demo
    python main.py --data-dir /tmp/ontop-demo

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

from ontop.formatting import local_datetime, now_local  # noqa: E402
from ontop.models import DEVICES, PAYMENT_METHODS, Extension, Session, find_conflicts, suggest_status  # noqa: E402
from ontop.storage import SessionStore  # noqa: E402

NAMES = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Sana", "Vikram", "Ishaan", "Tara", "Zoya", "Arjun", "Nikhil"]


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
    today = now_local().date()
    sessions: list[Session] = []
    for back in range(args.days, -1, -1):
        day = today - timedelta(days=back)
        for _ in range(rng.randint(2, 7)):
            device = rng.choice(DEVICES)
            start = local_datetime(day, time(rng.choice(range(10, 24)), rng.choice((0, 15, 30, 45))))
            minutes = rng.choice((30, 60, 60, 90, 120, 180))
            end = start + timedelta(minutes=minutes)
            if find_conflicts(sessions, device, start, end):
                continue
            rate = 150 if device.startswith("ps5") else 100
            total = rate * minutes // 60 * 100
            paid = rng.choice((total, total, total, 0, total // 2))
            entered = min(start, now_local())
            ext = []
            if rng.random() < 0.15:
                ext.append(Extension(entered, 30, end, end + timedelta(minutes=30)))
                end += timedelta(minutes=30)
                if find_conflicts(sessions, device, start, end):
                    continue
            sessions.append(Session(
                id=f"demo-{len(sessions):04d}", customer_name=rng.choice(NAMES), device=device,
                start=start, end=end.astimezone(), payment_method=rng.choice(PAYMENT_METHODS), total_paise=total,
                paid_paise=paid, payment_status=suggest_status(total, paid), entry_time=entered,
                last_updated=entered, extensions=ext,
            ))
    for s in sessions:
        store.add(s)
    print(f"Wrote {len(sessions)} demo sessions to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
