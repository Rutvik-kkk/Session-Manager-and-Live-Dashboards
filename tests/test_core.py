"""Unit tests for models, storage and analytics (no GUI needed).

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

from ontop import analytics as an
from ontop.formatting import fmt_money, local_datetime, parse_money
from ontop.models import (
    ConflictError,
    Extension,
    Session,
    ValidationError,
    build_times,
    find_conflicts,
    payment_problems,
    prepare_session,
    suggest_status,
)
from ontop.storage import InstanceLock, InstanceLockError, SessionStore, StorageError

NOW = local_datetime(date(2026, 10, 27), time(12, 0))


def make(name="Asha", device="ps5A", day=date(2026, 10, 27), start="18:00", end="19:00", next_day=False,
         total="200", paid="200", status=None, method="Cash", now=NOW, existing=None, extensions=()):
    total_p, paid_p = parse_money(total), parse_money(paid)
    return prepare_session(
        customer_name=name, device=device, date_text=day.isoformat(), start_text=start, end_text=end,
        ends_next_day=next_day, payment_method=method, total_text=total, paid_text=paid,
        payment_status=status or suggest_status(total_p, paid_p), now=now, existing=existing,
        new_extensions=extensions,
    )


class TempStoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "data"
        self.path = self.dir / "sessions.json"

    def tearDown(self):
        self.tmp.cleanup()

    def store(self) -> SessionStore:
        s = SessionStore(self.path)
        s.load()
        return s


class MoneyTests(unittest.TestCase):
    def test_parse_decimal_without_float_error(self):
        self.assertEqual(parse_money("0.10") + parse_money("0.20"), 30)
        self.assertEqual(parse_money("₹1,234.5"), 123450)
        self.assertEqual(parse_money(" 199.99 "), 19999)
        self.assertEqual(parse_money(".5"), 50)

    def test_rejects_invalid(self):
        for bad in ("-5", "abc", "1.234", "1e3", "", "12..3", "nan"):
            with self.assertRaises(ValueError, msg=bad):
                parse_money(bad)

    def test_format(self):
        self.assertEqual(fmt_money(0), "₹0.00")
        self.assertEqual(fmt_money(12345678), "₹1,23,456.78")
        self.assertEqual(fmt_money(-250), "-₹2.50")


class PaymentTests(unittest.TestCase):
    def test_status_rules(self):
        self.assertEqual(suggest_status(50000, 50000), "Paid")
        self.assertEqual(suggest_status(50000, 0), "Unpaid")
        self.assertEqual(suggest_status(50000, 100), "Partially Paid")
        self.assertEqual(suggest_status(0, 0), "Paid")

    def test_conflicting_status_rejected(self):
        self.assertTrue(payment_problems(50000, 0, "Paid"))
        self.assertTrue(payment_problems(0, 0, "Unpaid"))
        self.assertTrue(payment_problems(50000, 20000, "Unpaid"))
        self.assertEqual(payment_problems(50000, 20000, "Partially Paid"), [])

    def test_overpayment_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            make(total="100", paid="150", status="Paid")
        self.assertIn("cannot exceed", str(ctx.exception))

    def test_balance(self):
        s = make(total="350.50", paid="100.25", status="Partially Paid")
        self.assertEqual(s.balance_paise, 25025)


class TimeTests(unittest.TestCase):
    def test_overnight_session(self):
        start, end = build_times("2026-10-27", "23:00", "02:30", True)
        self.assertEqual(end - start, timedelta(hours=3, minutes=30))
        self.assertEqual(end.date(), date(2026, 10, 28))
        self.assertIsNotNone(start.utcoffset())

    def test_end_before_start_without_next_day_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            build_times("2026-10-27", "23:00", "02:30", False)
        self.assertIn("Ends next day", str(ctx.exception))

    def test_zero_and_over_24h_rejected(self):
        with self.assertRaises(ValidationError):
            build_times("2026-10-27", "10:00", "10:00", False)
        with self.assertRaises(ValidationError):
            build_times("2026-10-27", "10:00", "10:01", True)
        start, end = build_times("2026-10-27", "10:00", "10:00", True)
        self.assertEqual(end - start, timedelta(hours=24))

    def test_blank_name_rejected_and_trimmed(self):
        with self.assertRaises(ValidationError):
            make(name="   ")
        self.assertEqual(make(name="  Ravi   Kumar ").customer_name, "Ravi Kumar")


class ConflictTests(unittest.TestCase):
    def setUp(self):
        self.a = make(name="Asha", start="18:00", end="19:00")

    def test_overlap_same_device(self):
        b = make(name="Bala", start="18:30", end="19:30")
        self.assertEqual(find_conflicts([self.a], "ps5A", b.start, b.end), [self.a])

    def test_back_to_back_allowed(self):
        b = make(name="Bala", start="19:00", end="20:00")
        self.assertEqual(find_conflicts([self.a], "ps5A", b.start, b.end), [])
        c = make(name="Chitra", start="17:00", end="18:00")
        self.assertEqual(find_conflicts([self.a], "ps5A", c.start, c.end), [])

    def test_other_device_allowed(self):
        b = make(name="Bala", device="ps4", start="18:30", end="19:30")
        self.assertEqual(find_conflicts([self.a], "ps4", b.start, b.end), [])

    def test_exclude_own_id(self):
        self.assertEqual(find_conflicts([self.a], "ps5A", self.a.start, self.a.end, exclude_id=self.a.id), [])

    def test_overnight_conflict_across_dates(self):
        late = make(name="Night", start="23:00", end="03:00", next_day=True)
        early = make(name="Early", day=date(2026, 10, 28), start="02:00", end="04:00")
        self.assertEqual(find_conflicts([late], "ps5A", early.start, early.end), [late])


class StorageTests(TempStoreCase):
    def test_creates_file_and_reloads(self):
        store = self.store()
        self.assertTrue(self.path.exists())
        data = json.loads(self.path.read_text())
        self.assertEqual(data, {"schema_version": 1, "sessions": []})
        s = make(total="300", paid="100", status="Partially Paid")
        store.add(s)
        again = self.store()
        self.assertIsNone(again.load_error)
        loaded = again.get(s.id)
        self.assertEqual(loaded, s)
        raw = json.loads(self.path.read_text())["sessions"][0]
        self.assertEqual(raw["total_charge_paise"], 30000)
        self.assertEqual(raw["amount_paid_paise"], 10000)
        self.assertEqual(raw["duration_minutes"], 60)
        self.assertRegex(raw["start"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertEqual(raw["extension_history"], [])

    def test_update_preserves_entry_time_and_id_without_duplicates(self):
        store = self.store()
        s = make(total="300", paid="0", status="Unpaid")
        store.add(s)
        later = NOW + timedelta(hours=3)
        edited = make(name="Asha R", total="300", paid="300", status="Paid", now=later, existing=s)
        store.update(edited)
        again = self.store()
        self.assertEqual(len(again.sessions), 1)
        got = again.get(s.id)
        self.assertEqual(got.entry_time, s.entry_time)
        self.assertEqual(got.last_updated, later)
        self.assertEqual(got.customer_name, "Asha R")
        self.assertEqual(got.payment_status, "Paid")

    def test_entry_time_cannot_change(self):
        store = self.store()
        s = make()
        store.add(s)
        bad = s.copy()
        bad.entry_time = s.entry_time + timedelta(minutes=1)
        bad.last_updated = bad.entry_time
        with self.assertRaises(StorageError):
            store.update(bad)

    def test_store_rejects_conflicts(self):
        store = self.store()
        store.add(make(name="Asha", start="18:00", end="19:00"))
        with self.assertRaises(ConflictError) as ctx:
            store.add(make(name="Bala", start="18:59", end="20:00"))
        msg = str(ctx.exception)
        self.assertIn("ps5A", msg)
        self.assertIn("Asha", msg)
        self.assertIn("2026-10-27 18:00", msg)
        store.add(make(name="Bala", start="19:00", end="20:00"))
        self.assertEqual(len(self.store().sessions), 2)

    def test_extension_history_round_trip(self):
        store = self.store()
        s = make(start="18:00", end="19:00")
        store.add(s)
        new_end = s.end + timedelta(minutes=30)
        ext = Extension(NOW + timedelta(hours=7), 30, s.end, new_end)
        extended = make(start="18:00", end="19:30", existing=s, extensions=[ext], now=NOW + timedelta(hours=7))
        store.update(extended)
        got = self.store().get(s.id)
        self.assertEqual(got.start, s.start)
        self.assertEqual(got.duration_minutes, 90)
        self.assertEqual(got.total_paise, s.total_paise)
        self.assertEqual(got.extensions, [ext])
        raw = json.loads(self.path.read_text())["sessions"][0]["extension_history"][0]
        self.assertEqual(set(raw), {"extended_at", "minutes_added", "previous_end", "new_end"})

    def test_corrupted_json_preserved_and_read_only(self):
        self.dir.mkdir(parents=True)
        self.path.write_text('{"schema_version": 1, "sessions": [ {oops')
        before = self.path.read_bytes()
        store = self.store()
        self.assertTrue(store.read_only)
        self.assertIn("not valid JSON", store.load_error)
        with self.assertRaises(StorageError):
            store.add(make())
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_record_not_silently_discarded(self):
        good = make(name="Good").to_dict()
        bad = make(name="Bad", start="20:00", end="21:00").to_dict()
        bad["device"] = "xbox"
        self.dir.mkdir(parents=True)
        self.path.write_text(json.dumps({"schema_version": 1, "sessions": [good, bad]}))
        before = self.path.read_bytes()
        store = self.store()
        self.assertTrue(store.read_only)
        self.assertIn("Record #2", store.load_error)
        self.assertIn("xbox", store.load_error)
        self.assertEqual(len(store.sessions), 1)
        with self.assertRaises(StorageError):
            store.add(make(name="New", start="22:00", end="23:00"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_inconsistent_status_in_file_is_flagged(self):
        rec = make(total="100", paid="0", status="Unpaid").to_dict()
        rec["payment_status"] = "Paid"
        self.dir.mkdir(parents=True)
        self.path.write_text(json.dumps({"schema_version": 1, "sessions": [rec]}))
        store = self.store()
        self.assertTrue(store.read_only)
        self.assertIn("should be 'Unpaid'", store.load_error)

    def test_failed_write_keeps_file_and_memory(self):
        store = self.store()
        first = make(name="First")
        store.add(first)
        before = self.path.read_bytes()
        with mock.patch("ontop.storage.os.replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(StorageError) as ctx:
                store.add(make(name="Second", start="20:00", end="21:00"))
        self.assertIn("No space left", str(ctx.exception))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([s.customer_name for s in store.sessions], ["First"])
        self.assertEqual([p.name for p in self.dir.iterdir() if p.suffix == ".tmp"], [])
        store.add(make(name="Second", start="20:00", end="21:00"))
        self.assertEqual(len(self.store().sessions), 2)

    def test_external_modification_detected(self):
        store = self.store()
        store.add(make(name="First"))
        other = json.loads(self.path.read_text())
        other["sessions"] = []
        os.utime(self.path, ns=(0, 0))
        self.path.write_text(json.dumps(other))
        with self.assertRaises(StorageError):
            store.add(make(name="Second", start="20:00", end="21:00"))

    def test_single_instance_lock(self):
        first = InstanceLock(self.dir / "sessions.lock")
        first.acquire()
        try:
            with self.assertRaises(InstanceLockError):
                InstanceLock(self.dir / "sessions.lock").acquire()
        finally:
            first.release()
        again = InstanceLock(self.dir / "sessions.lock")
        again.acquire()
        again.release()


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            make(name="Asha", device="ps5A", day=date(2026, 10, 20), start="10:00", end="11:30", total="150",
                 paid="150", method="UPI"),
            make(name="asha ", device="ps5B", day=date(2026, 10, 26), start="18:00", end="20:00", total="200",
                 paid="50", method="Cash"),
            make(name="Bala", device="ps4", day=date(2026, 10, 27), start="23:00", end="01:00", next_day=True,
                 total="120", paid="0", method="Card"),
            make(name="Chitra", device="ps5A", day=date(2026, 9, 30), start="18:00", end="19:00", total="0",
                 paid="0", method="Other"),
        ]

    def test_presets(self):
        today = date(2026, 10, 27)
        self.assertEqual(an.preset_range(an.PRESET_LAST_7, today), (date(2026, 10, 21), today))
        self.assertEqual(an.preset_range(an.PRESET_THIS_MONTH, today), (date(2026, 10, 1), today))
        self.assertEqual(an.preset_range(an.PRESET_YESTERDAY, today), (date(2026, 10, 26),) * 2)
        self.assertEqual(an.preset_range(an.PRESET_ALL, today), (None, None))

    def test_filter_inclusive_by_start_date(self):
        flt = an.SessionFilter(start_date=date(2026, 10, 26), end_date=date(2026, 10, 27))
        self.assertEqual([s.customer_name for s in an.filter_sessions(self.rows, flt)], ["asha", "Bala"])
        flt = an.SessionFilter(search="ASH")
        self.assertEqual(len(an.filter_sessions(self.rows, flt)), 2)
        flt = an.SessionFilter(device="ps5A", payment_status="Paid")
        self.assertEqual(len(an.filter_sessions(self.rows, flt)), 2)

    def test_summary(self):
        s = an.summarize(self.rows)
        self.assertEqual(s.count, 4)
        self.assertEqual(s.unique_customers, 3)
        self.assertEqual(s.booked_minutes, 90 + 120 + 120 + 60)
        self.assertEqual(s.total_paise, 47000)
        self.assertEqual(s.paid_paise, 20000)
        self.assertEqual(s.balance_paise, 27000)
        self.assertEqual(s.average_charge_paise, 11750)
        empty = an.summarize([])
        self.assertEqual((empty.average_minutes, empty.average_charge_paise), (0.0, 0))

    def test_time_series_grouping(self):
        days = an.time_series(self.rows, an.GROUP_DAY, date(2026, 10, 25), date(2026, 10, 27))
        self.assertEqual([(b.start.day, b.count) for b in days], [(25, 0), (26, 1), (27, 1)])
        weeks = an.time_series(self.rows, an.GROUP_WEEK)
        self.assertTrue(all(b.start.weekday() == 0 for b in weeks))
        self.assertEqual(weeks[0].start, date(2026, 9, 28))
        self.assertEqual(sum(b.count for b in weeks), 4)
        months = an.time_series(self.rows, an.GROUP_MONTH)
        self.assertEqual([(b.start, b.paid_paise) for b in months],
                         [(date(2026, 9, 1), 0), (date(2026, 10, 1), 20000)])
        self.assertEqual(an.time_series([], an.GROUP_DAY), [])

    def test_breakdowns(self):
        self.assertEqual(an.status_counts(self.rows), {"Paid": 2, "Unpaid": 1, "Partially Paid": 1})
        self.assertEqual(an.received_by_method(self.rows), {"Cash": 5000, "UPI": 15000, "Card": 0, "Other": 0})
        hours = an.start_hour_counts(self.rows)
        self.assertEqual((hours[10], hours[18], hours[23]), (1, 2, 1))
        stats = an.sort_device_stats(an.device_stats(self.rows), an.METRIC_HOURS, True)
        self.assertEqual([s.device for s in stats], ["ps5A", "ps4", "ps5B"])
        self.assertEqual([s.device for s in an.sort_device_stats(stats, an.SORT_DEVICE_NAME, False)],
                         ["ps4", "ps5A", "ps5B"])

    def test_timeline_clipping(self):
        overnight = self.rows[2]
        d27, d28 = date(2026, 10, 27), date(2026, 10, 28)
        self.assertIn(overnight, an.sessions_on_day(self.rows, d27))
        self.assertIn(overnight, an.sessions_on_day(self.rows, d28))
        lo, hi = an.day_bounds(d27)
        f0, f1 = an.bar_span(overnight.start, overnight.end, lo, hi)
        self.assertAlmostEqual(f0, 23 / 24)
        self.assertAlmostEqual(f1, 1.0)
        lo, hi = an.day_bounds(d28)
        f0, f1 = an.bar_span(overnight.start, overnight.end, lo, hi)
        self.assertAlmostEqual((f0, f1), (0.0, 1 / 24))
        self.assertEqual(overnight.end.hour, 1)
        noon = self.rows[0]
        lo, hi = an.day_bounds(date(2026, 10, 20))
        f0, f1 = an.bar_span(noon.start, noon.end, lo, hi)
        self.assertAlmostEqual(f0, 10 / 24)
        self.assertAlmostEqual(f1, 11.5 / 24)
        self.assertIsNone(an.bar_span(noon.start, noon.end, *an.day_bounds(date(2026, 10, 21))))


class SessionRecordTests(unittest.TestCase):
    def test_from_dict_reports_problems(self):
        rec = make().to_dict()
        rec["duration_minutes"] = 61
        with self.assertRaises(ValueError):
            Session.from_dict(rec)
        rec = make().to_dict()
        rec["start"] = "2026-10-27T18:00:00"
        with self.assertRaisesRegex(ValueError, "no UTC offset"):
            Session.from_dict(rec)
        rec = make().to_dict()
        rec["total_charge_paise"] = 12.5
        with self.assertRaisesRegex(ValueError, "integer"):
            Session.from_dict(rec)

    def test_timestamps_have_offsets(self):
        d = make().to_dict()
        for key in ("start", "end", "entry_time", "last_updated"):
            self.assertIsNotNone(datetime.fromisoformat(d[key]).utcoffset(), key)


if __name__ == "__main__":
    unittest.main()
