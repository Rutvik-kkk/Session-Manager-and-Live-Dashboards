"""Filtering, aggregation and timeline geometry derived from session records.

Nothing here is persisted: every dashboard figure is recomputed from the
saved sessions each time it is shown.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Sequence

from .config import CLOSING_TIME, ITEM_KINDS, OPENING_TIME
from .formatting import local_datetime
from .models import (
    DEVICES,
    PAYMENT_METHODS,
    Expense,
    MonthlyPass,
    Session,
    customer_key,
    normalise_name,
)

PRESET_TODAY = "Today"
PRESET_YESTERDAY = "Yesterday"
PRESET_LAST_7 = "Last 7 Days"
PRESET_THIS_WEEK = "This Week"
PRESET_THIS_MONTH = "This Month"
PRESET_THIS_YEAR = "This Year"
PRESET_ALL = "All Time"
PRESET_CUSTOM = "Custom Range"
DATE_PRESETS = (PRESET_TODAY, PRESET_YESTERDAY, PRESET_LAST_7, PRESET_THIS_WEEK, PRESET_THIS_MONTH,
                PRESET_THIS_YEAR, PRESET_ALL, PRESET_CUSTOM)
BUSY_PERIODS = (PRESET_THIS_WEEK, PRESET_THIS_MONTH, PRESET_THIS_YEAR, PRESET_ALL)

GROUP_DAY = "Day"
GROUP_WEEK = "Week"
GROUP_MONTH = "Month"
GROUPINGS = (GROUP_DAY, GROUP_WEEK, GROUP_MONTH)

METRIC_COUNT = "Session Count"
METRIC_HOURS = "Booked Hours"
METRIC_CHARGES = "Total Charges"
DEVICE_METRICS = (METRIC_COUNT, METRIC_HOURS, METRIC_CHARGES)
SORT_DEVICE_NAME = "Device Name"
DEVICE_SORTS = (SORT_DEVICE_NAME, METRIC_COUNT, METRIC_HOURS, METRIC_CHARGES)


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------

def preset_range(preset: str, today: date) -> tuple[date | None, date | None]:
    """Inclusive start/end dates for a preset; (None, None) means unbounded."""
    if preset == PRESET_TODAY:
        return today, today
    if preset == PRESET_YESTERDAY:
        y = today - timedelta(days=1)
        return y, y
    if preset == PRESET_LAST_7:
        return today - timedelta(days=6), today
    if preset == PRESET_THIS_WEEK:
        return today - timedelta(days=today.weekday()), today
    if preset == PRESET_THIS_MONTH:
        return today.replace(day=1), today
    if preset == PRESET_THIS_YEAR:
        return today.replace(month=1, day=1), today
    if preset == PRESET_ALL:
        return None, None
    raise ValueError(f"'{preset}' has no fixed range")


@dataclass(frozen=True)
class SessionFilter:
    start_date: date | None = None
    end_date: date | None = None
    device: str | None = None
    payment_method: str | None = None
    payment_status: str | None = None
    search: str = ""

    def matches(self, s: Session) -> bool:
        d = s.start_date
        if self.start_date is not None and d < self.start_date:
            return False
        if self.end_date is not None and d > self.end_date:
            return False
        if self.device and s.device != self.device:
            return False
        if self.payment_method and s.payment_method != self.payment_method:
            return False
        if self.payment_status and s.payment_status != self.payment_status:
            return False
        needle = normalise_name(self.search).casefold()
        if needle and needle not in s.customer_name.casefold():
            return False
        return True


def filter_sessions(sessions: Iterable[Session], flt: SessionFilter) -> list[Session]:
    return [s for s in sessions if flt.matches(s)]


# --------------------------------------------------------------------------
# Summary metrics
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Summary:
    count: int
    unique_customers: int
    booked_minutes: int
    total_paise: int
    paid_paise: int
    balance_paise: int
    pass_sessions: int = 0
    pass_minutes: int = 0
    items_paise: int = 0  # snacks & drinks sold (already part of total_paise)
    items_units: int = 0

    @property
    def playing_paise(self) -> int:
        """Charges for playing time only (total charges minus snacks and drinks)."""
        return self.total_paise - self.items_paise

    @property
    def average_minutes(self) -> float:
        return self.booked_minutes / self.count if self.count else 0.0

    @property
    def average_charge_paise(self) -> int:
        # Round half up to the nearest paisa.
        return (self.total_paise * 2 + self.count) // (2 * self.count) if self.count else 0


def summarize(sessions: Sequence[Session]) -> Summary:
    return Summary(
        count=len(sessions),
        unique_customers=len({customer_key(s.customer_name) for s in sessions}),
        booked_minutes=sum(s.duration_minutes for s in sessions),
        total_paise=sum(s.total_paise for s in sessions),
        paid_paise=sum(s.paid_paise for s in sessions),
        balance_paise=sum(s.balance_paise for s in sessions),
        pass_sessions=sum(1 for s in sessions if s.pass_id),
        pass_minutes=sum(s.pass_minutes for s in sessions),
        items_paise=sum(s.items_paise for s in sessions),
        items_units=sum(i.quantity for s in sessions for i in s.items),
    )


# --------------------------------------------------------------------------
# Time series
# --------------------------------------------------------------------------

def bucket_start(d: date, group: str) -> date:
    if group == GROUP_DAY:
        return d
    if group == GROUP_WEEK:
        return d - timedelta(days=d.weekday())  # Monday
    if group == GROUP_MONTH:
        return d.replace(day=1)
    raise ValueError(f"unknown grouping '{group}'")


def next_bucket(d: date, group: str) -> date:
    if group == GROUP_DAY:
        return d + timedelta(days=1)
    if group == GROUP_WEEK:
        return d + timedelta(days=7)
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def bucket_label(d: date, group: str) -> str:
    if group == GROUP_DAY:
        return d.strftime("%d %b")
    if group == GROUP_WEEK:
        return "Wk " + d.strftime("%d %b")
    return d.strftime("%b %Y")


@dataclass(frozen=True)
class Bucket:
    start: date
    count: int
    total_paise: int
    paid_paise: int


def time_series(
    sessions: Sequence[Session],
    group: str,
    range_start: date | None = None,
    range_end: date | None = None,
) -> list[Bucket]:
    """Chronological buckets, including empty ones, covering the range.

    When the range is unbounded it spans the first to last session.
    """
    dates = [s.start_date for s in sessions]
    lo = range_start if range_start is not None else (min(dates) if dates else None)
    hi = range_end if range_end is not None else (max(dates) if dates else None)
    if lo is None or hi is None or lo > hi:
        return []
    counts: Counter = Counter()
    totals: Counter = Counter()
    paid: Counter = Counter()
    for s in sessions:
        key = bucket_start(s.start_date, group)
        counts[key] += 1
        totals[key] += s.total_paise
        paid[key] += s.paid_paise
    buckets = []
    cur = bucket_start(lo, group)
    last = bucket_start(hi, group)
    while cur <= last:
        buckets.append(Bucket(cur, counts[cur], totals[cur], paid[cur]))
        cur = next_bucket(cur, group)
    return buckets


@dataclass(frozen=True)
class EarningsBucket:
    start: date
    sessions_paise: int
    passes_paise: int

    @property
    def total_paise(self) -> int:
        return self.sessions_paise + self.passes_paise


def earnings_series(
    sessions: Sequence[Session],
    passes: Sequence[MonthlyPass],
    group: str,
    range_start: date | None = None,
    range_end: date | None = None,
) -> list[EarningsBucket]:
    """Money received per period: session payments (by session date) plus pass sales (by purchase date)."""
    dates = [s.start_date for s in sessions] + [p.purchased_on for p in passes]
    lo = range_start if range_start is not None else (min(dates) if dates else None)
    hi = range_end if range_end is not None else (max(dates) if dates else None)
    if lo is None or hi is None or lo > hi:
        return []
    from_sessions: Counter = Counter()
    from_passes: Counter = Counter()
    for s in sessions:
        from_sessions[bucket_start(s.start_date, group)] += s.paid_paise
    for p in passes:
        from_passes[bucket_start(p.purchased_on, group)] += p.price_paise
    buckets = []
    cur = bucket_start(lo, group)
    last = bucket_start(hi, group)
    while cur <= last:
        buckets.append(EarningsBucket(cur, from_sessions[cur], from_passes[cur]))
        cur = next_bucket(cur, group)
    return buckets


# --------------------------------------------------------------------------
# Breakdowns
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DeviceStats:
    device: str
    count: int
    minutes: int
    total_paise: int

    def metric(self, metric: str) -> float:
        if metric == METRIC_COUNT:
            return self.count
        if metric == METRIC_HOURS:
            return self.minutes / 60
        if metric == METRIC_CHARGES:
            return self.total_paise / 100
        raise ValueError(metric)


def device_stats(sessions: Sequence[Session], devices: Sequence[str] = DEVICES) -> list[DeviceStats]:
    out = []
    for dev in devices:
        rows = [s for s in sessions if s.device == dev]
        out.append(
            DeviceStats(dev, len(rows), sum(s.duration_minutes for s in rows), sum(s.total_paise for s in rows))
        )
    return out


def sort_device_stats(stats: Sequence[DeviceStats], sort_by: str, descending: bool) -> list[DeviceStats]:
    by_name = sorted(stats, key=lambda st: st.device.casefold(), reverse=descending and sort_by == SORT_DEVICE_NAME)
    if sort_by == SORT_DEVICE_NAME:
        return by_name
    # Stable sort keeps ties in A–Z device order regardless of direction.
    return sorted(by_name, key=lambda st: st.metric(sort_by), reverse=descending)


def received_by_method(sessions: Sequence[Session]) -> dict[str, int]:
    """Amount received, attributed to each session's single saved method."""
    out = {m: 0 for m in PAYMENT_METHODS}
    for s in sessions:
        out[s.payment_method] = out.get(s.payment_method, 0) + s.paid_paise
    return out


@dataclass(frozen=True)
class GameStats:
    game: str
    count: int
    minutes: int

    def metric(self, metric: str) -> float:
        return self.minutes / 60 if metric == METRIC_HOURS else self.count


def game_stats(sessions: Sequence[Session], metric: str = METRIC_COUNT) -> list[GameStats]:
    """Games played (sessions that name a game), most played first; ties in A–Z order."""
    counts: Counter = Counter()
    minutes: Counter = Counter()
    names: dict[str, str] = {}
    for s in sessions:
        if not s.game:
            continue
        key = s.game.casefold()
        names.setdefault(key, s.game)
        counts[key] += 1
        minutes[key] += s.duration_minutes
    rows = [GameStats(names[k], counts[k], minutes[k]) for k in counts]
    rows.sort(key=lambda g: g.game.casefold())
    return sorted(rows, key=lambda g: g.metric(metric), reverse=True)


ITEM_METRIC_SALES = "Sales (₹)"
ITEM_METRIC_UNITS = "Units Sold"
ITEM_METRICS = (ITEM_METRIC_SALES, ITEM_METRIC_UNITS)
ITEM_KIND_ALL = "Snacks & Drinks"


@dataclass(frozen=True)
class ItemSales:
    name: str
    kind: str
    units: int
    sales_paise: int

    def metric(self, metric: str) -> float:
        return self.units if metric == ITEM_METRIC_UNITS else self.sales_paise / 100


def item_sales(sessions: Sequence[Session], kind: str | None = None,
               metric: str = ITEM_METRIC_SALES) -> list[ItemSales]:
    """Snacks and drinks sold, best sellers first. Lines are grouped by name and kind whatever their price was."""
    units: Counter = Counter()
    sales: Counter = Counter()
    names: dict[tuple[str, str], str] = {}
    for s in sessions:
        for item in s.items:
            if kind and item.kind != kind:
                continue
            key = (item.name.casefold(), item.kind)
            names.setdefault(key, item.name)
            units[key] += item.quantity
            sales[key] += item.amount_paise
    rows = [ItemSales(names[k], k[1], units[k], sales[k]) for k in units]
    rows.sort(key=lambda r: (r.name.casefold(), r.kind))
    return sorted(rows, key=lambda r: r.metric(metric), reverse=True)


def sales_by_kind(sessions: Sequence[Session]) -> dict[str, int]:
    out = {k: 0 for k in ITEM_KINDS}
    for s in sessions:
        for item in s.items:
            out[item.kind] = out.get(item.kind, 0) + item.amount_paise
    return out


def expenses_in_range(expenses: Iterable[Expense], start: date | None, end: date | None,
                      search: str = "") -> list[Expense]:
    """Expenses entered in the inclusive date range (by the day they were entered)."""
    needle = " ".join(search.split()).casefold()
    return [
        e for e in expenses
        if (start is None or e.spent_on >= start) and (end is None or e.spent_on <= end)
        and (not needle or needle in e.note.casefold())
    ]


def busy_hour_counts(sessions: Sequence[Session]) -> list[int]:
    """For each hour of the day (local time), how many sessions were playing during it.

    A session from 10:30 to 12:00 counts towards 10:00 and 11:00.
    """
    counts = [0] * 24
    for s in sessions:
        cur = s.local_start.replace(minute=0, second=0, microsecond=0)
        end = s.local_end
        while cur < end:
            counts[cur.hour] += 1
            cur = (cur + timedelta(hours=1)).astimezone()
    return counts


# --------------------------------------------------------------------------
# Timeline geometry
# --------------------------------------------------------------------------

def day_bounds(d: date) -> tuple[datetime, datetime]:
    """Local midnight at the start of ``d`` and of the following day."""
    return local_datetime(d, time(0, 0)), local_datetime(d + timedelta(days=1), time(0, 0))


def sessions_on_day(sessions: Iterable[Session], d: date) -> list[Session]:
    day_start, day_end = day_bounds(d)
    rows = [s for s in sessions if s.start < day_end and s.end > day_start]
    return sorted(rows, key=lambda s: s.start)


def timeline_hours(d: date, sessions: Iterable[Session]) -> tuple[int, int]:
    """First and last hour to show: opening hours, widened for any session outside them."""
    first = OPENING_TIME.hour
    last = CLOSING_TIME.hour + (1 if CLOSING_TIME.minute else 0)
    day_start, day_end = day_bounds(d)
    for s in sessions:
        lo = max(s.start, day_start).astimezone()
        hi = min(s.end, day_end).astimezone()
        if hi <= lo:
            continue
        first = min(first, lo.hour)
        last = max(last, 24 if hi >= day_end else hi.hour + (1 if (hi.minute or hi.second) else 0))
    return first, last


def hour_moment(d: date, hour: int) -> datetime:
    return day_bounds(d)[1] if hour >= 24 else local_datetime(d, time(hour, 0))


def passes_sold(passes: Iterable[MonthlyPass], start: date | None, end: date | None, method: str | None = None,
                search: str = "") -> list[MonthlyPass]:
    """Passes purchased in the inclusive date range (by purchase date)."""
    needle = normalise_name(search).casefold()
    return [
        p for p in passes
        if (start is None or p.purchased_on >= start)
        and (end is None or p.purchased_on <= end)
        and (not method or p.payment_method == method)
        and (not needle or needle in p.holder_name.casefold() or needle in p.phone)
    ]


def bar_span(start: datetime, end: datetime, day_start: datetime, day_end: datetime) -> tuple[float, float] | None:
    """Fractions (0..1) of the day covered by a session, clipped to the day."""
    total = (day_end - day_start).total_seconds()
    lo = max(start, day_start)
    hi = min(end, day_end)
    if hi <= lo:
        return None
    return (lo - day_start).total_seconds() / total, (hi - day_start).total_seconds() / total
