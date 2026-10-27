"""Shared parsing and formatting helpers for dates, times, money and durations.

All timestamps handled by the application are timezone-aware. Naive values are
only ever produced from user input and are immediately interpreted in the
computer's local timezone.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M"
RUPEE = "\u20b9"

# Ten crore rupees; far above any realistic session charge, but keeps typos
# such as an extra row of zeros from being accepted.
MAX_MONEY_PAISE = 10_000_000_00

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_MONEY_RE = re.compile(r"^(\d+(\.\d{0,2})?|\.\d{1,2})$")


# --------------------------------------------------------------------------
# Date / time
# --------------------------------------------------------------------------

def now_local() -> datetime:
    """Current local time, timezone-aware, truncated to whole seconds."""
    return datetime.now().astimezone().replace(microsecond=0)


def today_local() -> date:
    return now_local().date()


def to_local(dt: datetime) -> datetime:
    """Convert an aware datetime to the computer's local timezone."""
    return dt.astimezone()


def local_datetime(d: date, t: time) -> datetime:
    """Combine a date and wall-clock time as local time (DST-aware offset)."""
    return datetime.combine(d, t).astimezone()


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Refusing to serialise a timestamp without a UTC offset.")
    return dt.isoformat(timespec="seconds")


def parse_iso(text: object) -> datetime:
    if not isinstance(text, str):
        raise ValueError("expected an ISO 8601 timestamp string")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"'{text}' is not a valid ISO 8601 timestamp") from None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"timestamp '{text}' has no UTC offset")
    return dt


def parse_date(text: str, field: str = "Date") -> date:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError(f"{field} is required (YYYY-MM-DD).")
    try:
        return datetime.strptime(cleaned, DATE_FMT).date()
    except ValueError:
        raise ValueError(f"{field} '{cleaned}' is not a valid date. Use YYYY-MM-DD, e.g. 2026-10-27.") from None


def parse_time(text: str, field: str = "Time") -> time:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError(f"{field} is required (24-hour HH:MM).")
    match = _TIME_RE.match(cleaned)
    if not match:
        raise ValueError(f"{field} '{cleaned}' is not valid. Use 24-hour HH:MM, e.g. 18:30.")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"{field} '{cleaned}' is out of range. Use 00:00 to 23:59.")
    return time(hour, minute)


def fmt_date(d: date) -> str:
    return d.strftime(DATE_FMT)


def fmt_date_long(d: date) -> str:
    return d.strftime("%a %d %b %Y")


def fmt_time(dt: datetime) -> str:
    return to_local(dt).strftime(TIME_FMT)


def fmt_datetime(dt: datetime) -> str:
    return to_local(dt).strftime(f"{DATE_FMT} {TIME_FMT}")


def fmt_offset(dt: datetime) -> str:
    offset = to_local(dt).utcoffset() or timedelta(0)
    total = int(offset.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"UTC{sign}{total // 60:02d}:{total % 60:02d}"


def fmt_datetime_long(dt: datetime) -> str:
    local = to_local(dt)
    return f"{local.strftime('%a %d %b %Y, %H:%M')} ({fmt_offset(local)})"


def fmt_range(start: datetime, end: datetime) -> str:
    """Readable range; the end date is repeated only when it differs."""
    s, e = to_local(start), to_local(end)
    if s.date() == e.date():
        return f"{fmt_datetime(s)} – {fmt_time(e)}"
    return f"{fmt_datetime(s)} – {fmt_datetime(e)}"


# --------------------------------------------------------------------------
# Durations
# --------------------------------------------------------------------------

def fmt_duration(minutes: int) -> str:
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def fmt_hours(minutes: float) -> str:
    hours = minutes / 60
    return f"{hours:,.1f} h"


# --------------------------------------------------------------------------
# Money (stored as integer paise)
# --------------------------------------------------------------------------

def parse_money(text: str, field: str = "Amount") -> int:
    """Parse an INR amount typed by a user into integer paise using Decimal."""
    cleaned = text.strip().replace(RUPEE, "").replace(",", "").replace(" ", "")
    if cleaned.lower().startswith("rs"):
        cleaned = cleaned[2:].lstrip(".")
    if cleaned == "":
        raise ValueError(f"{field} is required.")
    if cleaned.startswith("-"):
        raise ValueError(f"{field} cannot be negative.")
    if not _MONEY_RE.match(cleaned):
        raise ValueError(
            f"{field} '{text.strip()}' is not a valid amount. "
            "Use digits with up to two decimal places, e.g. 250 or 199.50."
        )
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"{field} '{text.strip()}' is not a valid amount.") from None
    paise = int(value * 100)
    if paise > MAX_MONEY_PAISE:
        raise ValueError(f"{field} is unrealistically large ({fmt_money(paise)}).")
    return paise


def _indian_grouping(n: int) -> str:
    digits = str(n)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def fmt_money(paise: int) -> str:
    """Format paise as rupees, e.g. 123456 -> '₹1,234.56' (Indian digit grouping)."""
    sign = "-" if paise < 0 else ""
    rupees, rem = divmod(abs(int(paise)), 100)
    return f"{sign}{RUPEE}{_indian_grouping(rupees)}.{rem:02d}"


def paise_to_input(paise: int) -> str:
    rupees, rem = divmod(int(paise), 100)
    return f"{rupees}.{rem:02d}"


def fmt_money_compact(rupees: float) -> str:
    """Compact axis label: ₹950, ₹12.5k, ₹1.2L, ₹3.4Cr."""
    value = abs(rupees)
    sign = "-" if rupees < 0 else ""
    if value >= 1e7:
        return f"{sign}{RUPEE}{value / 1e7:.1f}Cr"
    if value >= 1e5:
        return f"{sign}{RUPEE}{value / 1e5:.1f}L"
    if value >= 1e3:
        return f"{sign}{RUPEE}{value / 1e3:.1f}k"
    if value == int(value):
        return f"{sign}{RUPEE}{int(value)}"
    return f"{sign}{RUPEE}{value:.2f}"
