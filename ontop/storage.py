"""JSON persistence with atomic writes and a single-instance lock."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout

from .config import LEGACY_DEVICE_NAMES
from .formatting import fmt_date_long, fmt_duration
from .models import (
    ConflictError,
    MonthlyPass,
    Session,
    ValidationError,
    find_conflicts,
    fmt_phone,
    opening_hours_problem,
    pass_session_problems,
    pass_used_minutes,
)
from .pricing import players_problem

SCHEMA_VERSION = 2
READABLE_VERSIONS = (1, 2)
MAX_REPORTED_PROBLEMS = 12


class StorageError(Exception):
    """Reading or writing the data file failed."""


class InstanceLockError(Exception):
    """Another copy of the application is already using the data folder."""


class InstanceLock:
    """Cross-platform exclusive lock (fcntl on Unix, msvcrt on Windows via filelock).

    The OS releases the lock automatically if the process exits or crashes,
    so a stale lock file never blocks the next launch.
    """

    def __init__(self, lock_path: Path):
        self.path = Path(lock_path)
        self._lock = FileLock(str(self.path), timeout=0)

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._lock.acquire()
        except Timeout:
            raise InstanceLockError(
                "On Top Gaming — Session Manager is already running with this data folder:\n"
                f"{self.path.parent}\n\nSwitch to the open window instead of starting a second copy, "
                "so the two windows cannot overwrite each other's changes."
            ) from None

    def release(self) -> None:
        if self._lock.is_locked:
            self._lock.release()


def _upgrade_v1_session(record: object) -> object:
    """Version 1 used device names ps5A/ps5B/ps4 and had no players or passes."""
    if not isinstance(record, dict):
        return record
    upgraded = dict(record)
    device = upgraded.get("device")
    if isinstance(device, str) and device in LEGACY_DEVICE_NAMES:
        upgraded["device"] = LEGACY_DEVICE_NAMES[device]
    upgraded.setdefault("players", 1)
    upgraded.setdefault("pass_id", None)
    return upgraded


class SessionStore:
    """Owns the in-memory sessions and passes and keeps ``sessions.json`` in sync.

    Every change is written to disk first; memory is only updated after the
    atomic replace succeeds, so a failed write leaves both unchanged.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._sessions: dict[str, Session] = {}
        self._passes: dict[str, MonthlyPass] = {}
        self.load_error: str | None = None
        self.upgraded_from: int | None = None
        self._fingerprint: tuple[int, int] | None = None

    # -- state -----------------------------------------------------------

    @property
    def read_only(self) -> bool:
        return self.load_error is not None

    @property
    def sessions(self) -> list[Session]:
        return [s.copy() for s in self._sessions.values()]

    @property
    def passes(self) -> list[MonthlyPass]:
        return [p.copy() for p in self._passes.values()]

    def get(self, session_id: str) -> Session | None:
        s = self._sessions.get(session_id)
        return s.copy() if s else None

    def get_pass(self, pass_id: str | None) -> MonthlyPass | None:
        p = self._passes.get(pass_id) if pass_id else None
        return p.copy() if p else None

    def pass_used_minutes(self, pass_id: str, exclude_session_id: str | None = None) -> int:
        return pass_used_minutes(pass_id, self._sessions.values(), exclude_session_id)

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.stem + ".v1-backup.json")

    # -- loading ---------------------------------------------------------

    def load(self) -> None:
        """Load and validate the data file, creating it on first use.

        If the file is unreadable or contains invalid records, the valid
        records are kept for viewing, ``load_error`` explains the problem and
        all writes are refused so the original file is preserved untouched.
        """
        self._sessions = {}
        self._passes = {}
        self.load_error = None
        self.upgraded_from = None
        self._fingerprint = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.load_error = f"Could not create the data folder {self.path.parent}: {exc}"
            return

        if not self.path.exists():
            try:
                self._write({}, {})
            except StorageError as exc:
                self.load_error = str(exc)
            return

        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.load_error = f"Could not read {self.path}: {exc}"
            return
        self._fingerprint = self._stat()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.load_error = (
                f"{self.path} is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg})."
            )
            return

        if not isinstance(data, dict):
            self.load_error = f"{self.path} must contain a JSON object with 'schema_version' and 'sessions'."
            return
        version = data.get("schema_version")
        if version not in READABLE_VERSIONS:
            self.load_error = (
                f"{self.path} has schema_version {version!r}; this version of the app reads "
                f"schema_version {', '.join(map(str, READABLE_VERSIONS))}."
            )
            return
        records = data.get("sessions")
        if not isinstance(records, list):
            self.load_error = f"{self.path} is missing its 'sessions' list."
            return
        pass_records = data.get("passes", []) if version >= 2 else []
        if not isinstance(pass_records, list):
            self.load_error = f"{self.path} has a 'passes' value that is not a list."
            return
        if version == 1:
            records = [_upgrade_v1_session(r) for r in records]
            self.upgraded_from = 1

        problems: list[str] = []
        for index, record in enumerate(pass_records, start=1):
            label = f"Pass #{index}"
            if isinstance(record, dict) and isinstance(record.get("phone"), str):
                label += f" (phone {record['phone']})"
            try:
                p = MonthlyPass.from_dict(record)
            except ValueError as exc:
                problems.append(f"{label}: {exc}")
                continue
            if p.id in self._passes:
                problems.append(f"{label}: duplicate pass id")
                continue
            self._passes[p.id] = p

        for index, record in enumerate(records, start=1):
            label = f"Record #{index}"
            if isinstance(record, dict) and isinstance(record.get("id"), str):
                label += f" (id {record['id']})"
            try:
                session = Session.from_dict(record)
            except ValueError as exc:
                problems.append(f"{label}: {exc}")
                continue
            if session.id in self._sessions:
                problems.append(f"{label}: duplicate session id")
                continue
            if session.pass_id is not None and session.pass_id not in self._passes:
                problems.append(f"{label}: refers to monthly pass {session.pass_id} which is not in the file")
                continue
            self._sessions[session.id] = session

        if problems:
            shown = problems[:MAX_REPORTED_PROBLEMS]
            more = len(problems) - len(shown)
            text = "\n".join(f"• {p}" for p in shown)
            if more:
                text += f"\n• …and {more} more"
            total = len(records) + len(pass_records)
            self.load_error = f"{len(problems)} of {total} saved record(s) in {self.path} are invalid:\n{text}"

    # -- session changes -------------------------------------------------

    def add(self, session: Session) -> None:
        if session.id in self._sessions:
            raise StorageError("A session with this id already exists; use update instead.")
        self._check_session(session, None)
        updated = dict(self._sessions)
        updated[session.id] = session.copy()
        self._commit(updated, self._passes)

    def update(self, session: Session) -> None:
        existing = self._sessions.get(session.id)
        if existing is None:
            raise StorageError("This session no longer exists in the data file.")
        if session.entry_time != existing.entry_time:
            raise StorageError("The original entry time of a session cannot be changed.")
        self._check_session(session, existing)
        updated = dict(self._sessions)
        updated[session.id] = session.copy()
        self._commit(updated, self._passes)

    def _check_session(self, session: Session, existing: Session | None) -> None:
        problems = session.problems()
        if problems:
            raise ValidationError(problems)
        # Rules for new bookings; older records saved before a rule existed can
        # still have their payment details edited without being rejected.
        times_changed = existing is None or (session.start, session.end) != (existing.start, existing.end)
        if times_changed:
            problem = opening_hours_problem(session.start, session.end)
            if problem:
                raise ValidationError([problem])
        if times_changed or existing is None or session.players != existing.players:
            problem = players_problem(session.players, session.duration_minutes)
            if problem:
                raise ValidationError([problem])
        if session.pass_id is not None:
            p = self._passes.get(session.pass_id)
            if p is None:
                raise ValidationError(["The monthly pass for this session no longer exists."])
            problems = pass_session_problems(
                p, session.start_date, session.pass_minutes, self.pass_used_minutes(p.id, session.id)
            )
            if problems:
                raise ValidationError(problems)
        conflicts = find_conflicts(
            self._sessions.values(), session.device, session.start, session.end, exclude_id=session.id
        )
        if conflicts:
            raise ConflictError(session.device, conflicts)

    # -- pass changes ----------------------------------------------------

    def add_pass(self, p: MonthlyPass) -> None:
        if p.id in self._passes:
            raise StorageError("A pass with this id already exists; use update instead.")
        self._check_pass(p)
        updated = dict(self._passes)
        updated[p.id] = p.copy()
        self._commit(self._sessions, updated)

    def update_pass(self, p: MonthlyPass) -> None:
        existing = self._passes.get(p.id)
        if existing is None:
            raise StorageError("This pass no longer exists in the data file.")
        if p.created_at != existing.created_at:
            raise StorageError("The creation time of a pass cannot be changed.")
        self._check_pass(p)
        outside = [s for s in self._sessions.values() if s.pass_id == p.id and not p.covers(s.start_date)]
        if outside:
            raise ValidationError([
                f"{len(outside)} session(s) already used this pass on dates outside "
                f"{fmt_date_long(p.purchased_on)} – {fmt_date_long(p.valid_until)}, so the purchase date "
                "cannot be changed that way."
            ])
        updated = dict(self._passes)
        updated[p.id] = p.copy()
        self._commit(self._sessions, updated)

    def _check_pass(self, p: MonthlyPass) -> None:
        problems = p.problems()
        if problems:
            raise ValidationError(problems)
        for other in self._passes.values():
            if other.id == p.id or other.phone != p.phone:
                continue
            overlap = other.purchased_on <= p.valid_until and p.purchased_on <= other.valid_until
            remaining = other.included_minutes - self.pass_used_minutes(other.id)
            if overlap and remaining > 0:
                raise ValidationError([
                    f"{fmt_phone(p.phone)} already has a pass ({other.holder_name}) valid "
                    f"{fmt_date_long(other.purchased_on)} – {fmt_date_long(other.valid_until)} with "
                    f"{fmt_duration(remaining)} left. A new pass can start once that one is used up "
                    f"or after {fmt_date_long(other.valid_until)}."
                ])

    # -- file IO ---------------------------------------------------------

    def _commit(self, sessions: dict[str, Session], passes: dict[str, MonthlyPass]) -> None:
        if self.read_only:
            raise StorageError(
                "Saving is disabled because the data file could not be loaded safely. "
                "The original file has been left untouched.\n\n" + (self.load_error or "")
            )
        current = self._stat()
        if self._fingerprint is not None and current is not None and current != self._fingerprint:
            raise StorageError(
                f"{self.path} was changed by another program since it was loaded. "
                "To avoid overwriting those changes, nothing was saved. Restart the app to reload the file."
            )
        if self.upgraded_from is not None and self.path.exists() and not self.backup_path.exists():
            try:
                shutil.copy2(self.path, self.backup_path)
            except OSError as exc:
                raise StorageError(
                    f"Could not back up the old-format data file to {self.backup_path} before upgrading it: "
                    f"{exc.strerror or exc}"
                ) from exc
        self._write(sessions, passes)
        self._sessions = dict(sessions)
        self._passes = dict(passes)
        self.upgraded_from = None

    def _stat(self) -> tuple[int, int] | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def _write(self, sessions: dict[str, Session], passes: dict[str, MonthlyPass]) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "sessions": [s.to_dict() for s in sorted(sessions.values(), key=lambda s: s.entry_time)],
            "passes": [p.to_dict() for p in sorted(passes.values(), key=lambda p: p.created_at)],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        tmp_path: str | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".sessions-", suffix=".tmp", dir=str(self.path.parent))
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self.path)
            tmp_path = None
            _fsync_directory(self.path.parent)
        except OSError as exc:
            raise StorageError(f"Could not save sessions to {self.path}: {exc.strerror or exc}") from exc
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        self._fingerprint = self._stat()


def _fsync_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
