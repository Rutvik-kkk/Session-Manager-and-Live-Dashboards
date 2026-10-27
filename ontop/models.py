"""Session records, calculations and validation rules.

Everything in this module is UI-independent so it can be unit tested.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

from .formatting import (
    fmt_duration,
    fmt_money,
    fmt_range,
    local_datetime,
    parse_date,
    parse_iso,
    parse_money,
    parse_time,
    to_iso,
    to_local,
)

DEVICES: tuple[str, ...] = ("ps5A", "ps5B", "ps4")
PAYMENT_METHODS: tuple[str, ...] = ("Cash", "UPI", "Card", "Other")

STATUS_PAID = "Paid"
STATUS_UNPAID = "Unpaid"
STATUS_PARTIAL = "Partially Paid"
PAYMENT_STATUSES: tuple[str, ...] = (STATUS_PAID, STATUS_UNPAID, STATUS_PARTIAL)

MAX_DURATION_MINUTES = 24 * 60
MAX_NAME_LENGTH = 80


class ValidationError(Exception):
    """One or more user-correctable problems with a session."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


class ConflictError(ValidationError):
    """The device is already booked for part of the requested time."""

    def __init__(self, device: str, conflicts: Sequence["Session"]):
        self.device = device
        self.conflicts = list(conflicts)
        super().__init__([conflict_message(device, self.conflicts)])


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Extension:
    extended_at: datetime
    minutes_added: int
    previous_end: datetime
    new_end: datetime

    def to_dict(self) -> dict:
        return {
            "extended_at": to_iso(self.extended_at),
            "minutes_added": self.minutes_added,
            "previous_end": to_iso(self.previous_end),
            "new_end": to_iso(self.new_end),
        }

    @classmethod
    def from_dict(cls, data: object) -> "Extension":
        if not isinstance(data, dict):
            raise ValueError("extension entry is not an object")
        minutes = data.get("minutes_added")
        if not _is_int(minutes) or minutes <= 0:
            raise ValueError("extension 'minutes_added' must be a positive integer")
        ext = cls(
            extended_at=parse_iso(data.get("extended_at")),
            minutes_added=minutes,
            previous_end=parse_iso(data.get("previous_end")),
            new_end=parse_iso(data.get("new_end")),
        )
        if ext.new_end - ext.previous_end != timedelta(minutes=minutes):
            raise ValueError("extension 'new_end' does not equal 'previous_end' plus 'minutes_added'")
        return ext


@dataclass
class Session:
    id: str
    customer_name: str
    device: str
    start: datetime
    end: datetime
    payment_method: str
    total_paise: int
    paid_paise: int
    payment_status: str
    entry_time: datetime
    last_updated: datetime
    extensions: list[Extension] = field(default_factory=list)

    @property
    def duration_minutes(self) -> int:
        return duration_between(self.start, self.end)

    @property
    def balance_paise(self) -> int:
        return self.total_paise - self.paid_paise

    @property
    def local_start(self) -> datetime:
        return to_local(self.start)

    @property
    def local_end(self) -> datetime:
        return to_local(self.end)

    @property
    def start_date(self) -> date:
        """Local calendar date the session starts on (used by date filters)."""
        return self.local_start.date()

    def copy(self) -> "Session":
        return replace(self, extensions=list(self.extensions))

    def problems(self) -> list[str]:
        """Return every rule this record violates (empty when valid)."""
        errors: list[str] = []
        if not isinstance(self.id, str) or not self.id.strip():
            errors.append("missing session id")
        name_error = name_problem(self.customer_name)
        if name_error:
            errors.append(name_error)
        elif self.customer_name != normalise_name(self.customer_name):
            errors.append("customer name has leading/trailing or repeated spaces")
        if self.device not in DEVICES:
            errors.append(f"unknown device '{self.device}'")
        if self.payment_method not in PAYMENT_METHODS:
            errors.append(f"unknown payment method '{self.payment_method}'")
        duration_error = duration_problem(self.start, self.end)
        if duration_error:
            errors.append(duration_error)
        errors.extend(payment_problems(self.total_paise, self.paid_paise, self.payment_status))
        if self.last_updated < self.entry_time:
            errors.append("last updated time is earlier than entry time")
        return errors

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "customer_name": self.customer_name,
            "device": self.device,
            "start": to_iso(self.start),
            "end": to_iso(self.end),
            "duration_minutes": self.duration_minutes,
            "payment_method": self.payment_method,
            "total_charge_paise": self.total_paise,
            "amount_paid_paise": self.paid_paise,
            "payment_status": self.payment_status,
            "entry_time": to_iso(self.entry_time),
            "last_updated": to_iso(self.last_updated),
            "extension_history": [ext.to_dict() for ext in self.extensions],
        }

    @classmethod
    def from_dict(cls, data: object) -> "Session":
        """Build a session from JSON data, raising ValueError describing every problem."""
        if not isinstance(data, dict):
            raise ValueError("record is not a JSON object")
        errors: list[str] = []

        def take(key: str, kind: type | tuple, label: str):
            value = data.get(key)
            if key not in data:
                errors.append(f"missing '{key}'")
                return None
            if kind is int and not _is_int(value):
                errors.append(f"'{key}' must be an integer ({label})")
                return None
            if kind is not int and not isinstance(value, kind):
                errors.append(f"'{key}' has the wrong type ({label})")
                return None
            return value

        def take_time(key: str):
            value = data.get(key)
            if key not in data:
                errors.append(f"missing '{key}'")
                return None
            try:
                return parse_iso(value)
            except ValueError as exc:
                errors.append(f"'{key}': {exc}")
                return None

        sid = take("id", str, "text")
        name = take("customer_name", str, "text")
        device = take("device", str, "text")
        method = take("payment_method", str, "text")
        status = take("payment_status", str, "text")
        total = take("total_charge_paise", int, "paise")
        paid = take("amount_paid_paise", int, "paise")
        stored_duration = take("duration_minutes", int, "minutes")
        start = take_time("start")
        end = take_time("end")
        entry_time = take_time("entry_time")
        last_updated = take_time("last_updated")

        extensions: list[Extension] = []
        history = data.get("extension_history", None)
        if not isinstance(history, list):
            errors.append("'extension_history' must be a list")
        else:
            for i, item in enumerate(history, start=1):
                try:
                    extensions.append(Extension.from_dict(item))
                except ValueError as exc:
                    errors.append(f"extension #{i}: {exc}")

        if errors:
            raise ValueError("; ".join(errors))

        session = cls(
            id=sid,
            customer_name=name,
            device=device,
            start=start,
            end=end,
            payment_method=method,
            total_paise=total,
            paid_paise=paid,
            payment_status=status,
            entry_time=entry_time,
            last_updated=last_updated,
            extensions=extensions,
        )
        problems = session.problems()
        if not problems and stored_duration != session.duration_minutes:
            problems.append(
                f"'duration_minutes' is {stored_duration} but start/end span {session.duration_minutes} minutes"
            )
        if problems:
            raise ValueError("; ".join(problems))
        return session


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def normalise_name(name: str) -> str:
    return " ".join(name.split())


def customer_key(name: str) -> str:
    """Key used to estimate unique customers: trimmed and case-insensitive."""
    return normalise_name(name).casefold()


def name_problem(name: object) -> str | None:
    if not isinstance(name, str) or not normalise_name(name):
        return "Customer name is required."
    if len(normalise_name(name)) > MAX_NAME_LENGTH:
        return f"Customer name must be at most {MAX_NAME_LENGTH} characters."
    return None


# --------------------------------------------------------------------------
# Time calculations
# --------------------------------------------------------------------------

def duration_between(start: datetime, end: datetime) -> int:
    """Elapsed whole minutes between two aware datetimes."""
    return int((end - start).total_seconds() // 60)


def duration_problem(start: datetime, end: datetime) -> str | None:
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return "The session must end after it starts (duration must be more than zero)."
    if seconds % 60:
        return "Session start and end must be whole minutes."
    if seconds > MAX_DURATION_MINUTES * 60:
        return (
            f"Sessions can be at most 24 hours long; this one is "
            f"{fmt_duration(int(seconds // 60))}."
        )
    return None


def duration_minutes_problem(minutes: int) -> str | None:
    if minutes <= 0:
        return "Duration must be more than zero."
    if minutes > MAX_DURATION_MINUTES:
        return f"Duration cannot exceed 24 hours (entered {fmt_duration(minutes)})."
    return None


def add_minutes(dt: datetime, minutes: int) -> datetime:
    """Add elapsed minutes and re-express the result in local time."""
    return to_local(dt + timedelta(minutes=minutes))


def build_times(date_text: str, start_text: str, end_text: str, ends_next_day: bool) -> tuple[datetime, datetime]:
    """Turn form text into aware local start/end datetimes (validation included)."""
    errors: list[str] = []
    try:
        session_date = parse_date(date_text, "Session date")
    except ValueError as exc:
        errors.append(str(exc))
        session_date = None
    try:
        start_t = parse_time(start_text, "Start time")
    except ValueError as exc:
        errors.append(str(exc))
        start_t = None
    try:
        end_t = parse_time(end_text, "End time")
    except ValueError as exc:
        errors.append(str(exc))
        end_t = None
    if errors:
        raise ValidationError(errors)
    start = local_datetime(session_date, start_t)
    end_date = session_date + timedelta(days=1) if ends_next_day else session_date
    end = local_datetime(end_date, end_t)
    problem = duration_problem(start, end)
    if problem:
        if not ends_next_day and end_t <= start_t:
            problem += " If the session runs past midnight, tick 'Ends next day'."
        raise ValidationError([problem])
    return start, end


# --------------------------------------------------------------------------
# Payments
# --------------------------------------------------------------------------

def suggest_status(total_paise: int, paid_paise: int) -> str:
    if paid_paise >= total_paise:
        return STATUS_PAID
    if paid_paise == 0:
        return STATUS_UNPAID
    return STATUS_PARTIAL


def payment_problems(total_paise: int, paid_paise: int, status: str) -> list[str]:
    errors: list[str] = []
    if total_paise < 0:
        errors.append("Payment amount cannot be negative.")
    if paid_paise < 0:
        errors.append("Amount paid cannot be negative.")
    if errors:
        return errors
    if paid_paise > total_paise:
        errors.append(
            f"Amount paid ({fmt_money(paid_paise)}) cannot exceed the total charge ({fmt_money(total_paise)})."
        )
        return errors
    if status not in PAYMENT_STATUSES:
        errors.append("Select a payment status (Paid, Unpaid or Partially Paid).")
        return errors
    expected = suggest_status(total_paise, paid_paise)
    if status != expected:
        errors.append(
            f"Payment status '{status}' does not match the amounts: {fmt_money(paid_paise)} received "
            f"of {fmt_money(total_paise)} means the status should be '{expected}'."
        )
    return errors


# --------------------------------------------------------------------------
# Device availability
# --------------------------------------------------------------------------

def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def find_conflicts(
    sessions: Iterable[Session],
    device: str,
    start: datetime,
    end: datetime,
    exclude_id: str | None = None,
) -> list[Session]:
    found = [
        s
        for s in sessions
        if s.device == device and s.id != exclude_id and overlaps(start, end, s.start, s.end)
    ]
    return sorted(found, key=lambda s: s.start)


def conflict_message(device: str, conflicts: Sequence[Session]) -> str:
    lines = [f"{device} is not available for that time. It is already booked by:"]
    for s in conflicts:
        lines.append(f"  • {s.customer_name}: {fmt_range(s.start, s.end)}")
    lines.append("Choose a different device or time. A session may start exactly when another ends.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Building a session from form input
# --------------------------------------------------------------------------

def prepare_session(
    *,
    customer_name: str,
    device: str,
    date_text: str,
    start_text: str,
    end_text: str,
    ends_next_day: bool,
    payment_method: str,
    total_text: str,
    paid_text: str,
    payment_status: str,
    now: datetime,
    existing: Session | None = None,
    new_extensions: Sequence[Extension] = (),
) -> Session:
    """Validate raw form values and return a ready-to-store Session.

    For an existing session the id and entry time are preserved and any
    pending extensions are appended to its history.
    """
    errors: list[str] = []

    problem = name_problem(customer_name)
    if problem:
        errors.append(problem)
    name = normalise_name(customer_name or "")

    if device not in DEVICES:
        errors.append("Select a device (ps5A, ps5B or ps4).")
    if payment_method not in PAYMENT_METHODS:
        errors.append("Select a payment method (Cash, UPI, Card or Other).")

    start = end = None
    try:
        start, end = build_times(date_text, start_text, end_text, ends_next_day)
    except ValidationError as exc:
        errors.extend(exc.errors)

    total = paid = None
    try:
        total = parse_money(total_text, "Payment amount")
    except ValueError as exc:
        errors.append(str(exc))
    try:
        paid = parse_money(paid_text, "Amount paid")
    except ValueError as exc:
        errors.append(str(exc))
    if total is not None and paid is not None:
        errors.extend(payment_problems(total, paid, payment_status))
    elif payment_status not in PAYMENT_STATUSES:
        errors.append("Select a payment status (Paid, Unpaid or Partially Paid).")

    if errors:
        raise ValidationError(errors)

    if existing is not None:
        return Session(
            id=existing.id,
            customer_name=name,
            device=device,
            start=start,
            end=end,
            payment_method=payment_method,
            total_paise=total,
            paid_paise=paid,
            payment_status=payment_status,
            entry_time=existing.entry_time,
            last_updated=max(now, existing.entry_time),
            extensions=list(existing.extensions) + list(new_extensions),
        )
    return Session(
        id=str(uuid.uuid4()),
        customer_name=name,
        device=device,
        start=start,
        end=end,
        payment_method=payment_method,
        total_paise=total,
        paid_paise=paid,
        payment_status=payment_status,
        entry_time=now,
        last_updated=now,
        extensions=list(new_extensions),
    )
