"""Session and monthly-pass records, calculations and validation rules.

Everything in this module is UI-independent so it can be unit tested.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

from .config import (
    CLOSING_TIME,
    DEVICES,
    OPENING_TIME,
    PASS_HOURS,
    PASS_VALID_DAYS,
)
from .formatting import (
    fmt_date_long,
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
from .pricing import billable_minutes, players_problem

PAYMENT_METHODS: tuple[str, ...] = ("Cash", "UPI", "Card", "Other")

STATUS_PAID = "Paid"
STATUS_UNPAID = "Unpaid"
STATUS_PARTIAL = "Partially Paid"
PAYMENT_STATUSES: tuple[str, ...] = (STATUS_PAID, STATUS_UNPAID, STATUS_PARTIAL)

PASS_ACTIVE = "Active"
PASS_USED_UP = "Used up"
PASS_EXPIRED = "Expired"
PASS_NOT_STARTED = "Not started"
PASS_STATES: tuple[str, ...] = (PASS_ACTIVE, PASS_USED_UP, PASS_EXPIRED, PASS_NOT_STARTED)

# Structural limit applied to every stored record; opening hours further limit new sessions.
MAX_DURATION_MINUTES = 24 * 60
MAX_NAME_LENGTH = 80
MAX_NOTES_LENGTH = 500


class ValidationError(Exception):
    """One or more user-correctable problems with a session or pass."""

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
    players: int = 1
    pass_id: str | None = None
    notes: str = ""

    @property
    def duration_minutes(self) -> int:
        return duration_between(self.start, self.end)

    @property
    def pass_minutes(self) -> int:
        """Time deducted from the monthly pass (billed duration), or 0."""
        return billable_minutes(self.duration_minutes) if self.pass_id else 0

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
        """Structural rules every stored record must satisfy (empty when valid)."""
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
        player_error = players_problem(self.players)
        if player_error:
            errors.append(player_error)
        if self.pass_id is not None and (not isinstance(self.pass_id, str) or not self.pass_id.strip()):
            errors.append("invalid pass id")
        notes_error = notes_problem(self.notes)
        if notes_error:
            errors.append(notes_error)
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
            "players": self.players,
            "pass_id": self.pass_id,
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
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: object) -> "Session":
        """Build a session from JSON data, raising ValueError describing every problem."""
        if not isinstance(data, dict):
            raise ValueError("record is not a JSON object")
        reader = _Reader(data)
        sid = reader.text("id")
        name = reader.text("customer_name")
        device = reader.text("device")
        players = reader.integer("players")
        pass_id = reader.optional_text("pass_id")
        method = reader.text("payment_method")
        status = reader.text("payment_status")
        total = reader.integer("total_charge_paise")
        paid = reader.integer("amount_paid_paise")
        stored_duration = reader.integer("duration_minutes")
        start = reader.timestamp("start")
        end = reader.timestamp("end")
        entry_time = reader.timestamp("entry_time")
        last_updated = reader.timestamp("last_updated")
        notes = data.get("notes", "")
        if not isinstance(notes, str):
            reader.errors.append("'notes' must be text")

        extensions: list[Extension] = []
        history = data.get("extension_history", None)
        if not isinstance(history, list):
            reader.errors.append("'extension_history' must be a list")
        else:
            for i, item in enumerate(history, start=1):
                try:
                    extensions.append(Extension.from_dict(item))
                except ValueError as exc:
                    reader.errors.append(f"extension #{i}: {exc}")

        if reader.errors:
            raise ValueError("; ".join(reader.errors))

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
            players=players,
            pass_id=pass_id,
            notes=notes,
        )
        problems = session.problems()
        if not problems and stored_duration != session.duration_minutes:
            problems.append(
                f"'duration_minutes' is {stored_duration} but start/end span {session.duration_minutes} minutes"
            )
        if problems:
            raise ValueError("; ".join(problems))
        return session


@dataclass
class MonthlyPass:
    id: str
    holder_name: str
    phone: str
    purchased_on: date
    price_paise: int
    payment_method: str
    created_at: datetime
    last_updated: datetime
    hours: int = PASS_HOURS
    valid_days: int = PASS_VALID_DAYS

    @property
    def included_minutes(self) -> int:
        return self.hours * 60

    @property
    def valid_until(self) -> date:
        """Last calendar date on which the pass can be used."""
        return self.purchased_on + timedelta(days=self.valid_days - 1)

    def covers(self, d: date) -> bool:
        return self.purchased_on <= d <= self.valid_until

    def copy(self) -> "MonthlyPass":
        return replace(self)

    def problems(self) -> list[str]:
        errors: list[str] = []
        if not isinstance(self.id, str) or not self.id.strip():
            errors.append("missing pass id")
        name_error = name_problem(self.holder_name)
        if name_error:
            errors.append(name_error.replace("Customer", "Pass holder"))
        phone_error = phone_problem(self.phone)
        if phone_error:
            errors.append(phone_error)
        elif self.phone != normalise_phone(self.phone):
            errors.append("phone number is not stored as 10 digits")
        if self.payment_method not in PAYMENT_METHODS:
            errors.append(f"unknown payment method '{self.payment_method}'")
        if self.price_paise < 0:
            errors.append("pass price cannot be negative")
        if self.hours <= 0:
            errors.append("pass hours must be positive")
        if self.valid_days <= 0:
            errors.append("pass validity must be at least one day")
        if self.last_updated < self.created_at:
            errors.append("last updated time is earlier than creation time")
        return errors

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "holder_name": self.holder_name,
            "phone": self.phone,
            "purchased_on": self.purchased_on.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "hours": self.hours,
            "valid_days": self.valid_days,
            "price_paise": self.price_paise,
            "payment_method": self.payment_method,
            "created_at": to_iso(self.created_at),
            "last_updated": to_iso(self.last_updated),
        }

    @classmethod
    def from_dict(cls, data: object) -> "MonthlyPass":
        if not isinstance(data, dict):
            raise ValueError("pass is not a JSON object")
        reader = _Reader(data)
        pid = reader.text("id")
        name = reader.text("holder_name")
        phone = reader.text("phone")
        purchased_text = reader.text("purchased_on")
        hours = reader.integer("hours")
        valid_days = reader.integer("valid_days")
        price = reader.integer("price_paise")
        method = reader.text("payment_method")
        created_at = reader.timestamp("created_at")
        last_updated = reader.timestamp("last_updated")
        purchased = None
        if purchased_text is not None:
            try:
                purchased = date.fromisoformat(purchased_text)
            except ValueError:
                reader.errors.append(f"'purchased_on' {purchased_text!r} is not a YYYY-MM-DD date")
        if reader.errors:
            raise ValueError("; ".join(reader.errors))
        p = cls(pid, name, phone, purchased, price, method, created_at, last_updated, hours, valid_days)
        problems = p.problems()
        if not problems and data.get("valid_until") not in (None, p.valid_until.isoformat()):
            problems.append("'valid_until' does not match 'purchased_on' plus 'valid_days'")
        if problems:
            raise ValueError("; ".join(problems))
        return p


class _Reader:
    """Collects type errors while reading fields from a JSON object."""

    def __init__(self, data: dict):
        self.data = data
        self.errors: list[str] = []

    def _get(self, key: str):
        if key not in self.data:
            self.errors.append(f"missing '{key}'")
            return None, False
        return self.data[key], True

    def text(self, key: str):
        value, ok = self._get(key)
        if ok and not isinstance(value, str):
            self.errors.append(f"'{key}' must be text")
            return None
        return value

    def optional_text(self, key: str):
        value, ok = self._get(key)
        if ok and value is not None and not isinstance(value, str):
            self.errors.append(f"'{key}' must be text or null")
            return None
        return value

    def integer(self, key: str):
        value, ok = self._get(key)
        if ok and not _is_int(value):
            self.errors.append(f"'{key}' must be an integer")
            return None
        return value

    def timestamp(self, key: str):
        value, ok = self._get(key)
        if not ok:
            return None
        try:
            return parse_iso(value)
        except ValueError as exc:
            self.errors.append(f"'{key}': {exc}")
            return None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------
# Names and phone numbers
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


def normalise_notes(text: str) -> str:
    """Trim the note and its lines; line breaks are kept."""
    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def notes_problem(notes: object) -> str | None:
    if not isinstance(notes, str):
        return "Note must be text."
    if len(notes) > MAX_NOTES_LENGTH:
        return f"Note must be at most {MAX_NOTES_LENGTH} characters (currently {len(notes)})."
    return None


def normalise_phone(text: str) -> str:
    """Digits only, without a +91 or leading 0 prefix."""
    digits = re.sub(r"\D", "", text or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def phone_problem(text: object) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return "Phone number is required."
    if len(normalise_phone(text)) != 10:
        return f"'{text.strip()}' is not a valid phone number. Enter 10 digits, e.g. 98765 43210."
    return None


def fmt_phone(phone: str) -> str:
    return f"{phone[:5]} {phone[5:]}" if len(phone) == 10 else phone


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
        return f"Sessions can be at most 24 hours long; this one is {fmt_duration(int(seconds // 60))}."
    return None


def opening_hours_text() -> str:
    return f"{OPENING_TIME:%H:%M}–{CLOSING_TIME:%H:%M}"


def opening_hours_problem(start: datetime, end: datetime) -> str | None:
    s, e = to_local(start), to_local(end)
    closing = local_datetime(s.date(), CLOSING_TIME)
    if s.time() < OPENING_TIME:
        return f"The café opens at {OPENING_TIME:%H:%M}; sessions cannot start before then."
    if e > closing:
        return (
            f"The café closes at {CLOSING_TIME:%H:%M}; this session would end at "
            f"{e:%H:%M}{'' if e.date() == s.date() else ' the next day'}."
        )
    return None


def max_minutes_until_close(start: datetime) -> int:
    s = to_local(start)
    return duration_between(s, local_datetime(s.date(), CLOSING_TIME))


def duration_minutes_problem(minutes: int, start: datetime | None = None) -> str | None:
    if minutes <= 0:
        return "Duration must be more than zero."
    if start is not None:
        limit = max_minutes_until_close(start)
        if minutes > limit:
            return (
                f"A {fmt_duration(minutes)} session starting at {to_local(start):%H:%M} would run past closing "
                f"time ({CLOSING_TIME:%H:%M}). The longest possible is {fmt_duration(max(limit, 0))}."
            )
    return None


def add_minutes(dt: datetime, minutes: int) -> datetime:
    """Add elapsed minutes and re-express the result in local time."""
    return to_local(dt + timedelta(minutes=minutes))


def build_times(date_text: str, start_text: str, end_text: str) -> tuple[datetime, datetime]:
    """Turn form text into aware local start/end datetimes within opening hours."""
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
    end = local_datetime(session_date, end_t)
    problem = duration_problem(start, end)
    if problem:
        raise ValidationError([problem])
    problem = opening_hours_problem(start, end)
    if problem:
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
# Monthly passes
# --------------------------------------------------------------------------

def pass_used_minutes(pass_id: str, sessions: Iterable[Session], exclude_session_id: str | None = None) -> int:
    return sum(s.pass_minutes for s in sessions if s.pass_id == pass_id and s.id != exclude_session_id)


def pass_state(p: MonthlyPass, used_minutes: int, on: date) -> str:
    if on < p.purchased_on:
        return PASS_NOT_STARTED
    if used_minutes >= p.included_minutes:
        return PASS_USED_UP
    if on > p.valid_until:
        return PASS_EXPIRED
    return PASS_ACTIVE


def pass_session_problems(p: MonthlyPass, session_date: date, needed_minutes: int, used_by_others: int) -> list[str]:
    """Can this pass cover a session on ``session_date`` that needs ``needed_minutes``?"""
    errors: list[str] = []
    if session_date < p.purchased_on:
        errors.append(
            f"{p.holder_name}'s pass starts on {fmt_date_long(p.purchased_on)}, after this session's date."
        )
    elif session_date > p.valid_until:
        errors.append(f"{p.holder_name}'s pass expired after {fmt_date_long(p.valid_until)}.")
    remaining = p.included_minutes - used_by_others
    if needed_minutes > remaining:
        errors.append(
            f"{p.holder_name}'s pass has {fmt_duration(max(remaining, 0))} left, but this session needs "
            f"{fmt_duration(needed_minutes)} (time is deducted in 30-minute blocks). Shorten the session or "
            "untick 'Monthly pass holder' to bill it normally."
        )
    return errors


def active_pass_for_phone(passes: Iterable[MonthlyPass], sessions: Sequence[Session], phone: str,
                          on: date, exclude_session_id: str | None = None) -> MonthlyPass | None:
    """The pass for this phone that covers ``on`` and still has time left (oldest first)."""
    candidates = sorted((p for p in passes if p.phone == phone and p.covers(on)), key=lambda p: p.purchased_on)
    for p in candidates:
        if pass_used_minutes(p.id, sessions, exclude_session_id) < p.included_minutes:
            return p
    return candidates[-1] if candidates else None


def prepare_pass(
    *,
    holder_name: str,
    phone_text: str,
    purchased_text: str,
    price_text: str,
    payment_method: str,
    now: datetime,
    existing: MonthlyPass | None = None,
) -> MonthlyPass:
    errors: list[str] = []
    problem = name_problem(holder_name)
    if problem:
        errors.append(problem.replace("Customer", "Pass holder"))
    problem = phone_problem(phone_text)
    if problem:
        errors.append(problem)
    purchased = None
    try:
        purchased = parse_date(purchased_text, "Purchase date")
    except ValueError as exc:
        errors.append(str(exc))
    price = None
    try:
        price = parse_money(price_text, "Pass price")
    except ValueError as exc:
        errors.append(str(exc))
    if payment_method not in PAYMENT_METHODS:
        errors.append("Select how the pass was paid for (Cash, UPI, Card or Other).")
    if errors:
        raise ValidationError(errors)
    if existing is not None:
        return replace(
            existing,
            holder_name=normalise_name(holder_name),
            phone=normalise_phone(phone_text),
            purchased_on=purchased,
            price_paise=price,
            payment_method=payment_method,
            last_updated=max(now, existing.created_at),
        )
    return MonthlyPass(
        id=str(uuid.uuid4()),
        holder_name=normalise_name(holder_name),
        phone=normalise_phone(phone_text),
        purchased_on=purchased,
        price_paise=price,
        payment_method=payment_method,
        created_at=now,
        last_updated=now,
    )


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
    players: int | None,
    date_text: str,
    start_text: str,
    end_text: str,
    payment_method: str,
    total_text: str,
    paid_text: str,
    payment_status: str,
    now: datetime,
    existing: Session | None = None,
    new_extensions: Sequence[Extension] = (),
    monthly_pass: MonthlyPass | None = None,
    pass_used_by_others: int = 0,
    notes_text: str = "",
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
        errors.append(f"Select a device ({', '.join(DEVICES)}).")
    if payment_method not in PAYMENT_METHODS:
        errors.append("Select a payment method (Cash, UPI, Card or Other).")

    start = end = None
    try:
        start, end = build_times(date_text, start_text, end_text)
    except ValidationError as exc:
        errors.extend(exc.errors)

    duration = duration_between(start, end) if start and end else None
    problem = players_problem(players, duration)
    if problem:
        errors.append(problem)

    if monthly_pass is not None and start is not None:
        errors.extend(
            pass_session_problems(monthly_pass, to_local(start).date(), billable_minutes(duration),
                                  pass_used_by_others)
        )

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

    notes = normalise_notes(notes_text)
    problem = notes_problem(notes)
    if problem:
        errors.append(problem)

    if errors:
        raise ValidationError(errors)

    pass_id = monthly_pass.id if monthly_pass else None
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
            players=players,
            pass_id=pass_id,
            notes=notes,
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
        players=players,
        pass_id=pass_id,
        notes=notes,
    )
