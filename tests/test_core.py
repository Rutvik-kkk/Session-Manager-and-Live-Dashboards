"""Unit tests for pricing, models, storage and analytics (no GUI needed).

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
    MonthlyPass,
    Session,
    ValidationError,
    active_pass_for_phone,
    build_times,
    find_conflicts,
    normalise_phone,
    pass_state,
    payment_problems,
    prepare_pass,
    prepare_session,
    suggest_status,
)
from ontop.pricing import billable_minutes, suggested_charge
from ontop.storage import InstanceLock, InstanceLockError, SessionStore, StorageError

DAY = date(2026, 10, 27)
NOW = local_datetime(DAY, time(12, 0))


def make(name="Asha", device="PS5(X)", day=DAY, start="18:00", end="19:00", players=1, total="200",
         paid="200", status=None, method="Cash", now=NOW, existing=None, extensions=(), monthly_pass=None,
         used=0, notes=""):
    total_p, paid_p = parse_money(total), parse_money(paid)
    return prepare_session(
        customer_name=name, device=device, players=players, date_text=day.isoformat(), start_text=start,
        end_text=end, payment_method=method, total_text=total, paid_text=paid,
        payment_status=status or suggest_status(total_p, paid_p), now=now, existing=existing,
        new_extensions=extensions, monthly_pass=monthly_pass, pass_used_by_others=used, notes_text=notes,
    )


def raw_session(name, device, start: datetime, end: datetime, sid=None, pass_id=None, players=1) -> Session:
    """A session built directly, e.g. an older record from before the opening-hours rule."""
    return Session(sid or f"raw-{name}", name, device, start, end, "Cash", 0, 0, "Paid", NOW, NOW,
                   players=players, pass_id=pass_id)


def make_pass(name="Rahul", phone="98765 43210", bought=DAY, price="1920", now=NOW, existing=None):
    return prepare_pass(holder_name=name, phone_text=phone, purchased_text=bought.isoformat(),
                        price_text=price, payment_method="UPI", now=now, existing=existing)


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


class PricingTests(unittest.TestCase):
    def test_rounds_up_to_30_minutes(self):
        self.assertEqual([billable_minutes(m) for m in (1, 30, 31, 60, 61, 90, 95)], [30, 30, 60, 60, 90, 90, 120])

    def test_price_list(self):
        self.assertEqual(suggested_charge("PS5(X)", 1, 60), 8000)
        self.assertEqual(suggested_charge("PS5(Y)", 2, 60), 18000)
        self.assertEqual(suggested_charge("PS5(X)", 3, 60), 28000)
        self.assertEqual(suggested_charge("PS5(Y)", 4, 60), 38000)
        self.assertEqual(suggested_charge("PS4", 1, 60), 6000)
        self.assertEqual(suggested_charge("PS4", 2, 60), 12000)
        self.assertEqual(suggested_charge("PS4", 3, 60), 18000)
        self.assertEqual(suggested_charge("PS4", 4, 60), 24000)

    def test_half_hour_prices(self):
        self.assertEqual(suggested_charge("PS5(X)", 1, 30), 5500)
        self.assertEqual(suggested_charge("PS4", 1, 20), 4000)

    def test_longer_sessions(self):
        self.assertEqual(suggested_charge("PS5(X)", 1, 90), 12000)
        self.assertEqual(suggested_charge("PS5(X)", 2, 75), 27000)
        self.assertEqual(suggested_charge("PS4", 3, 120), 36000)

    def test_pass_holder_pays_only_for_extra_players(self):
        self.assertEqual(suggested_charge("PS5(X)", 1, 120, on_pass=True), 0)
        self.assertEqual(suggested_charge("PS5(X)", 1, 30, on_pass=True), 0)
        self.assertEqual(suggested_charge("PS5(X)", 2, 60, on_pass=True), 10000)
        self.assertEqual(suggested_charge("PS4", 4, 90, on_pass=True), 27000)

    def test_multiplayer_needs_an_hour(self):
        with self.assertRaises(ValidationError) as ctx:
            make(players=2, start="18:00", end="18:30")
        self.assertIn("at least 1h", str(ctx.exception))
        self.assertEqual(make(players=2, start="18:00", end="19:00").players, 2)
        with self.assertRaises(ValidationError):
            make(players=5)


class MoneyTests(unittest.TestCase):
    def test_parse_decimal_without_float_error(self):
        self.assertEqual(parse_money("0.10") + parse_money("0.20"), 30)
        self.assertEqual(parse_money("₹1,234.5"), 123450)
        self.assertEqual(parse_money(" 199.99 "), 19999)

    def test_rejects_invalid(self):
        for bad in ("-5", "abc", "1.234", "1e3", "", "12..3", "nan"):
            with self.assertRaises(ValueError, msg=bad):
                parse_money(bad)

    def test_format(self):
        self.assertEqual(fmt_money(0), "₹0.00")
        self.assertEqual(fmt_money(12345678), "₹1,23,456.78")


class PaymentTests(unittest.TestCase):
    def test_status_rules(self):
        self.assertEqual(suggest_status(50000, 50000), "Paid")
        self.assertEqual(suggest_status(50000, 0), "Unpaid")
        self.assertEqual(suggest_status(50000, 100), "Partially Paid")
        self.assertEqual(suggest_status(0, 0), "Paid")

    def test_conflicting_status_rejected(self):
        self.assertTrue(payment_problems(50000, 0, "Paid"))
        self.assertTrue(payment_problems(0, 0, "Unpaid"))
        self.assertEqual(payment_problems(50000, 20000, "Partially Paid"), [])

    def test_overpayment_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            make(total="100", paid="150", status="Paid")
        self.assertIn("cannot exceed", str(ctx.exception))

    def test_balance(self):
        self.assertEqual(make(total="350.50", paid="100.25", status="Partially Paid").balance_paise, 25025)


class OpeningHoursTests(unittest.TestCase):
    def test_within_hours(self):
        start, end = build_times("2026-10-27", "09:00", "22:00")
        self.assertEqual(end - start, timedelta(hours=13))
        self.assertIsNotNone(start.utcoffset())

    def test_outside_hours_rejected(self):
        with self.assertRaisesRegex(ValidationError, "opens at 09:00"):
            build_times("2026-10-27", "08:30", "10:00")
        with self.assertRaisesRegex(ValidationError, "closes at 22:00"):
            build_times("2026-10-27", "21:30", "22:15")
        with self.assertRaises(ValidationError):
            build_times("2026-10-27", "21:00", "01:00")

    def test_zero_or_negative_rejected(self):
        with self.assertRaises(ValidationError):
            build_times("2026-10-27", "10:00", "10:00")
        with self.assertRaises(ValidationError):
            build_times("2026-10-27", "11:00", "10:00")

    def test_blank_name_rejected_and_trimmed(self):
        with self.assertRaises(ValidationError):
            make(name="   ")
        self.assertEqual(make(name="  Ravi   Kumar ").customer_name, "Ravi Kumar")


class ConflictTests(unittest.TestCase):
    def setUp(self):
        self.a = make(name="Asha", start="18:00", end="19:00")

    def test_overlap_same_device(self):
        b = make(name="Bala", start="18:30", end="19:30")
        self.assertEqual(find_conflicts([self.a], "PS5(X)", b.start, b.end), [self.a])

    def test_back_to_back_allowed(self):
        for start, end in (("19:00", "20:00"), ("17:00", "18:00")):
            b = make(name="Bala", start=start, end=end)
            self.assertEqual(find_conflicts([self.a], "PS5(X)", b.start, b.end), [])

    def test_other_device_allowed(self):
        b = make(name="Bala", device="PS4", start="18:30", end="19:30")
        self.assertEqual(find_conflicts([self.a], "PS4", b.start, b.end), [])

    def test_exclude_own_id(self):
        self.assertEqual(find_conflicts([self.a], "PS5(X)", self.a.start, self.a.end, exclude_id=self.a.id), [])

    def test_conflict_across_dates(self):
        late = raw_session("Night", "PS5(X)", local_datetime(DAY, time(23)), local_datetime(DAY + timedelta(1), time(3)))
        early = raw_session("Early", "PS5(X)", local_datetime(DAY + timedelta(1), time(2)),
                            local_datetime(DAY + timedelta(1), time(4)))
        self.assertEqual(find_conflicts([late], "PS5(X)", early.start, early.end), [late])


class PassRuleTests(unittest.TestCase):
    def test_phone_normalised(self):
        self.assertEqual(normalise_phone("+91 98765-43210"), "9876543210")
        self.assertEqual(normalise_phone("09876543210"), "9876543210")
        with self.assertRaises(ValidationError):
            make_pass(phone="12345")

    def test_validity_and_state(self):
        p = make_pass(bought=date(2026, 10, 1))
        self.assertEqual(p.valid_until, date(2026, 10, 30))
        self.assertEqual(p.included_minutes, 30 * 60)
        self.assertEqual(pass_state(p, 0, date(2026, 10, 30)), "Active")
        self.assertEqual(pass_state(p, 0, date(2026, 10, 31)), "Expired")
        self.assertEqual(pass_state(p, 1800, date(2026, 10, 5)), "Used up")
        self.assertEqual(pass_state(p, 0, date(2026, 9, 30)), "Not started")

    def test_pass_session_deducts_billed_time(self):
        p = make_pass()
        s = make(start="18:00", end="19:10", total="0", paid="0", monthly_pass=p)
        self.assertEqual(s.pass_id, p.id)
        self.assertEqual(s.pass_minutes, 90)

    def test_pass_limits(self):
        p = make_pass(bought=DAY)
        with self.assertRaisesRegex(ValidationError, "has 1h left"):
            make(start="10:00", end="12:00", total="0", paid="0", monthly_pass=p, used=29 * 60)
        with self.assertRaisesRegex(ValidationError, "expired"):
            make(day=DAY + timedelta(days=30), total="0", paid="0", monthly_pass=p)
        with self.assertRaisesRegex(ValidationError, "starts on"):
            make(day=DAY - timedelta(days=1), total="0", paid="0", monthly_pass=p)

    def test_active_pass_lookup_by_phone(self):
        old = make_pass(bought=DAY - timedelta(days=40))
        new = make_pass(bought=DAY - timedelta(days=2))
        self.assertEqual(active_pass_for_phone([old, new], [], "9876543210", DAY).id, new.id)
        self.assertIsNone(active_pass_for_phone([old, new], [], "9000000000", DAY))


class StorageTests(TempStoreCase):
    def test_creates_file_and_reloads(self):
        store = self.store()
        self.assertEqual(json.loads(self.path.read_text()), {"schema_version": 2, "sessions": [], "passes": []})
        s = make(players=3, total="280", paid="100", status="Partially Paid")
        store.add(s)
        loaded = self.store().get(s.id)
        self.assertEqual(loaded, s)
        raw = json.loads(self.path.read_text())["sessions"][0]
        self.assertEqual((raw["players"], raw["pass_id"], raw["device"]), (3, None, "PS5(X)"))
        self.assertEqual(raw["total_charge_paise"], 28000)
        self.assertRegex(raw["start"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

    def test_update_preserves_entry_time_and_id_without_duplicates(self):
        store = self.store()
        s = make(total="300", paid="0", status="Unpaid")
        store.add(s)
        later = NOW + timedelta(hours=3)
        store.update(make(name="Asha R", total="300", paid="300", status="Paid", now=later, existing=s))
        again = self.store()
        self.assertEqual(len(again.sessions), 1)
        got = again.get(s.id)
        self.assertEqual((got.entry_time, got.last_updated, got.customer_name), (s.entry_time, later, "Asha R"))

    def test_store_rejects_conflicts_and_allows_back_to_back(self):
        store = self.store()
        store.add(make(name="Asha", start="18:00", end="19:00"))
        with self.assertRaises(ConflictError) as ctx:
            store.add(make(name="Bala", start="18:59", end="20:00"))
        self.assertIn("Asha", str(ctx.exception))
        store.add(make(name="Bala", start="19:00", end="20:00"))
        self.assertEqual(len(self.store().sessions), 2)

    def test_store_enforces_opening_hours_for_new_times(self):
        store = self.store()
        late = raw_session("Late", "PS4", local_datetime(DAY, time(21, 30)), local_datetime(DAY, time(22, 30)))
        late.total_paise = late.paid_paise = 0
        with self.assertRaisesRegex(ValidationError, "closes"):
            store.add(late)

    def test_extension_history_round_trip(self):
        store = self.store()
        s = make(start="18:00", end="19:00")
        store.add(s)
        ext = Extension(NOW + timedelta(hours=7), 30, s.end, s.end + timedelta(minutes=30))
        store.update(make(start="18:00", end="19:30", existing=s, extensions=[ext], now=NOW + timedelta(hours=7)))
        got = self.store().get(s.id)
        self.assertEqual((got.start, got.duration_minutes, got.extensions), (s.start, 90, [ext]))

    def test_pass_registration_usage_and_limits(self):
        store = self.store()
        p = make_pass()
        store.add_pass(p)
        with self.assertRaisesRegex(ValidationError, "already has a pass"):
            store.add_pass(make_pass(name="Someone", bought=DAY + timedelta(days=3)))
        store.add(make(start="09:00", end="22:00", total="0", paid="0", monthly_pass=p))
        store.add(make(device="PS4", day=DAY + timedelta(1), start="09:00", end="22:00", total="0", paid="0",
                       monthly_pass=p, used=780))
        self.assertEqual(store.pass_used_minutes(p.id), 26 * 60)
        too_long = make(day=DAY + timedelta(2), start="10:00", end="15:00", total="0", paid="0",
                        monthly_pass=p, used=0)
        with self.assertRaisesRegex(ValidationError, "has 4h left"):
            store.add(too_long)
        again = self.store()
        self.assertEqual(again.get_pass(p.id), p)
        self.assertEqual(again.pass_used_minutes(p.id), 26 * 60)
        raw = json.loads(self.path.read_text())["passes"][0]
        self.assertEqual((raw["phone"], raw["hours"], raw["price_paise"]), ("9876543210", 30, 192000))

    def test_new_pass_allowed_after_old_used_up(self):
        store = self.store()
        p = make_pass(bought=DAY - timedelta(days=2))
        store.add_pass(p)
        for i in range(3):
            day = DAY - timedelta(days=2) + timedelta(days=i)
            store.add(make(day=day, start="09:00", end="19:00", total="0", paid="0", monthly_pass=p,
                           used=store.pass_used_minutes(p.id)))
        store.add_pass(make_pass(bought=DAY + timedelta(days=1)))
        self.assertEqual(len(store.passes), 2)

    def test_upgrades_v1_file_with_backup(self):
        self.dir.mkdir(parents=True)
        rec = make().to_dict()
        rec["device"] = "ps5B"
        del rec["players"], rec["pass_id"]
        original = json.dumps({"schema_version": 1, "sessions": [rec]})
        self.path.write_text(original)
        store = self.store()
        self.assertIsNone(store.load_error)
        self.assertEqual(store.upgraded_from, 1)
        self.assertEqual(store.sessions[0].device, "PS5(Y)")
        self.assertEqual(store.sessions[0].players, 1)
        self.assertEqual(self.path.read_text(), original)
        store.add(make(name="New", start="10:00", end="11:00"))
        self.assertEqual(store.backup_path.read_text(), original)
        self.assertEqual(json.loads(self.path.read_text())["schema_version"], 2)

    def test_corrupted_json_preserved_and_read_only(self):
        self.dir.mkdir(parents=True)
        self.path.write_text('{"schema_version": 2, "sessions": [ {oops')
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
        orphan = make(name="Orphan", start="10:00", end="11:00").to_dict()
        orphan["pass_id"] = "missing-pass"
        self.dir.mkdir(parents=True)
        self.path.write_text(json.dumps({"schema_version": 2, "sessions": [good, bad, orphan], "passes": []}))
        before = self.path.read_bytes()
        store = self.store()
        self.assertTrue(store.read_only)
        self.assertIn("xbox", store.load_error)
        self.assertIn("missing-pass", store.load_error)
        self.assertEqual(len(store.sessions), 1)
        with self.assertRaises(StorageError):
            store.add(make(name="New", start="12:00", end="13:00"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_write_keeps_file_and_memory(self):
        store = self.store()
        store.add(make(name="First"))
        before = self.path.read_bytes()
        with mock.patch("ontop.storage.os.replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaisesRegex(StorageError, "No space left"):
                store.add(make(name="Second", start="20:00", end="21:00"))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([s.customer_name for s in store.sessions], ["First"])
        self.assertEqual([p.name for p in self.dir.iterdir() if p.suffix == ".tmp"], [])

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


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            make(name="Asha", device="PS5(X)", day=date(2026, 10, 20), start="10:00", end="11:30", total="150",
                 paid="150", method="UPI"),
            make(name="asha ", device="PS5(Y)", day=date(2026, 10, 26), start="18:00", end="20:00", total="200",
                 paid="50", method="Cash"),
            make(name="Bala", device="PS4", day=date(2026, 10, 27), start="20:00", end="22:00", players=2,
                 total="120", paid="0", method="Card"),
            make(name="Chitra", device="PS5(X)", day=date(2026, 9, 30), start="18:00", end="19:00", total="0",
                 paid="0", method="Other"),
        ]

    def test_presets(self):
        today = date(2026, 10, 27)
        self.assertEqual(an.preset_range(an.PRESET_LAST_7, today), (date(2026, 10, 21), today))
        self.assertEqual(an.preset_range(an.PRESET_THIS_WEEK, today), (date(2026, 10, 26), today))
        self.assertEqual(an.preset_range(an.PRESET_THIS_MONTH, today), (date(2026, 10, 1), today))
        self.assertEqual(an.preset_range(an.PRESET_THIS_YEAR, today), (date(2026, 1, 1), today))
        self.assertEqual(an.preset_range(an.PRESET_ALL, today), (None, None))

    def test_filter_inclusive_by_start_date(self):
        flt = an.SessionFilter(start_date=date(2026, 10, 26), end_date=date(2026, 10, 27))
        self.assertEqual([s.customer_name for s in an.filter_sessions(self.rows, flt)], ["asha", "Bala"])
        self.assertEqual(len(an.filter_sessions(self.rows, an.SessionFilter(search="ASH"))), 2)
        self.assertEqual(len(an.filter_sessions(self.rows, an.SessionFilter(device="PS5(X)",
                                                                              payment_status="Paid"))), 2)

    def test_summary(self):
        s = an.summarize(self.rows)
        self.assertEqual((s.count, s.unique_customers, s.booked_minutes), (4, 3, 90 + 120 + 120 + 60))
        self.assertEqual((s.total_paise, s.paid_paise, s.balance_paise), (47000, 20000, 27000))
        self.assertEqual(s.average_charge_paise, 11750)
        self.assertEqual(an.summarize([]).average_charge_paise, 0)

    def test_time_series_grouping(self):
        days = an.time_series(self.rows, an.GROUP_DAY, date(2026, 10, 25), date(2026, 10, 27))
        self.assertEqual([(b.start.day, b.count) for b in days], [(25, 0), (26, 1), (27, 1)])
        weeks = an.time_series(self.rows, an.GROUP_WEEK)
        self.assertTrue(all(b.start.weekday() == 0 for b in weeks))
        self.assertEqual(sum(b.count for b in weeks), 4)
        months = an.time_series(self.rows, an.GROUP_MONTH)
        self.assertEqual([(b.start, b.paid_paise) for b in months],
                         [(date(2026, 9, 1), 0), (date(2026, 10, 1), 20000)])

    def test_earnings_include_pass_sales(self):
        p = make_pass(bought=date(2026, 10, 26))
        days = an.earnings_series(self.rows, [p], an.GROUP_DAY, date(2026, 10, 25), date(2026, 10, 27))
        self.assertEqual([(b.start.day, b.sessions_paise, b.passes_paise, b.total_paise) for b in days],
                         [(25, 0, 0, 0), (26, 5000, 192000, 197000), (27, 0, 0, 0)])
        months = an.earnings_series(self.rows, [p], an.GROUP_MONTH)
        self.assertEqual([b.total_paise for b in months], [0, 20000 + 192000])

    def test_busy_hours_count_every_hour_played(self):
        counts = an.busy_hour_counts(self.rows)
        self.assertEqual({h: c for h, c in enumerate(counts) if c},
                         {10: 1, 11: 1, 18: 2, 19: 1, 20: 1, 21: 1})

    def test_breakdowns(self):
        self.assertEqual(an.received_by_method(self.rows), {"Cash": 5000, "UPI": 15000, "Card": 0, "Other": 0})
        stats = an.sort_device_stats(an.device_stats(self.rows), an.METRIC_HOURS, True)
        self.assertEqual([s.device for s in stats], ["PS5(X)", "PS4", "PS5(Y)"])

    def test_passes_sold(self):
        a = make_pass(bought=date(2026, 10, 5))
        b = make_pass(name="Priya", phone="9123456780", bought=date(2026, 10, 20))
        self.assertEqual(an.passes_sold([a, b], date(2026, 10, 10), date(2026, 10, 31)), [b])
        self.assertEqual(an.passes_sold([a, b], None, None, search="9876"), [a])

    def test_timeline_hours_and_placement(self):
        self.assertEqual(an.timeline_hours(DAY, []), (9, 22))
        s = self.rows[0]
        d = date(2026, 10, 20)
        lo, hi = an.hour_moment(d, 9), an.hour_moment(d, 22)
        f0, f1 = an.bar_span(s.start, s.end, lo, hi)
        self.assertAlmostEqual(f0, 1 / 13)
        self.assertAlmostEqual(f1, 2.5 / 13)
        night = raw_session("Night", "PS4", local_datetime(DAY, time(23)), local_datetime(DAY + timedelta(1), time(1)))
        self.assertEqual(an.timeline_hours(DAY, [night]), (9, 24))
        self.assertEqual(an.timeline_hours(DAY + timedelta(1), [night]), (0, 22))
        f0, f1 = an.bar_span(night.start, night.end, *an.day_bounds(DAY + timedelta(1)))
        self.assertAlmostEqual((f0, f1), (0.0, 1 / 24))


class RecordTests(unittest.TestCase):
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
        rec["players"] = 7
        with self.assertRaisesRegex(ValueError, "players"):
            Session.from_dict(rec)

    def test_notes(self):
        s = make(notes="  Wants PS5(X) next time  \r\n\r\nPaid by friend  ")
        self.assertEqual(s.notes, "Wants PS5(X) next time\n\nPaid by friend")
        self.assertEqual(Session.from_dict(s.to_dict()).notes, s.notes)
        self.assertEqual(make(notes="   ").notes, "")
        rec = make().to_dict()
        del rec["notes"]
        self.assertEqual(Session.from_dict(rec).notes, "")
        rec["notes"] = 5
        with self.assertRaisesRegex(ValueError, "notes"):
            Session.from_dict(rec)
        with self.assertRaisesRegex(ValidationError, "at most 500"):
            make(notes="x" * 501)
        edited = make(notes="new note", existing=s, now=NOW + timedelta(minutes=5))
        self.assertEqual((edited.id, edited.notes), (s.id, "new note"))

    def test_pass_round_trip(self):
        p = make_pass()
        self.assertEqual(MonthlyPass.from_dict(p.to_dict()), p)
        bad = p.to_dict()
        bad["valid_until"] = "2030-01-01"
        with self.assertRaises(ValueError):
            MonthlyPass.from_dict(bad)


class SettingsTests(TempStoreCase):
    def test_round_trip_and_apply(self):
        from ontop import config
        from ontop import settings as st

        saved = {k: getattr(config, k) for k in ("OPENING_TIME", "CLOSING_TIME", "HOURLY_RATES_PAISE",
                                                 "HALF_HOUR_PRICES_PAISE", "PASS_DEFAULT_PRICE_PAISE",
                                                 "PASS_HOURS", "PASS_VALID_DAYS")}
        self.addCleanup(lambda: [setattr(config, k, v) for k, v in saved.items()])
        path = st.settings_path(self.dir)
        self.assertEqual(st.load(path), (st.AppSettings(), None))
        s = st.AppSettings(theme="Forest Lodge", opening="10:00", closing="23:00", pass_price_paise=250000, pass_hours=20)
        s.hourly_rates_paise["PS4"][2] = 13000
        st.save(path, s)
        loaded, warning = st.load(path)
        self.assertIsNone(warning)
        self.assertEqual(loaded, s)
        st.apply(loaded)
        self.assertEqual((config.OPENING_TIME, config.CLOSING_TIME), (time(10), time(23)))
        self.assertEqual((config.HOURLY_RATES_PAISE["PS4"][2], config.PASS_HOURS), (13000, 20))

    def test_invalid_settings_fall_back_to_defaults(self):
        from ontop import settings as st

        path = st.settings_path(self.dir)
        with self.assertRaises(ValueError):
            st.save(path, st.AppSettings(opening="22:00", closing="09:00"))
        self.assertFalse(path.exists())
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        settings, warning = st.load(path)
        self.assertEqual(settings, st.AppSettings())
        self.assertIn("default settings", warning)
        path.write_text(json.dumps({"pass_hours": 0}), encoding="utf-8")
        self.assertIn("between 1 and 744", st.load(path)[1])

    def test_every_theme_defines_every_colour(self):
        from ontop.ui import theme

        keys = set(theme.PALETTES["Midnight"])
        self.assertEqual(len(theme.PALETTES), 7)
        for name, palette in theme.PALETTES.items():
            self.assertEqual(set(palette), keys, name)
            self.assertTrue(all(len(c) == 7 and c.startswith("#") for c in palette.values()), name)
        self.assertEqual(theme.PALETTES["Forest Lodge"]["SUCCESS"], "#4ade80")
        self.assertEqual(theme.PALETTES["Alpine Dusk"]["ACCENT"], "#f9b17a")
        self.addCleanup(theme.set_palette, "Midnight")
        theme.set_palette("Dusk Blue")
        self.assertEqual(theme.DEVICE_COLORS["PS5(Y)"], "#f2a7b8")
        theme.set_palette("Retired theme")
        self.assertEqual(theme.CURRENT_THEME, "Midnight")


if __name__ == "__main__":
    unittest.main()
