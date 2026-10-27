"""JSON persistence with atomic writes and a single-instance lock."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout

from .models import ConflictError, Session, ValidationError, find_conflicts

SCHEMA_VERSION = 1
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


class SessionStore:
    """Owns the in-memory session list and keeps ``sessions.json`` in sync.

    Every change is written to disk first; memory is only updated after the
    atomic replace succeeds, so a failed write leaves both unchanged.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._sessions: dict[str, Session] = {}
        self.load_error: str | None = None
        self._fingerprint: tuple[int, int] | None = None

    # -- state -----------------------------------------------------------

    @property
    def read_only(self) -> bool:
        return self.load_error is not None

    @property
    def sessions(self) -> list[Session]:
        return [s.copy() for s in self._sessions.values()]

    def get(self, session_id: str) -> Session | None:
        s = self._sessions.get(session_id)
        return s.copy() if s else None

    # -- loading ---------------------------------------------------------

    def load(self) -> None:
        """Load and validate the data file, creating it on first use.

        If the file is unreadable or contains invalid records, the valid
        records are kept for viewing, ``load_error`` explains the problem and
        all writes are refused so the original file is preserved untouched.
        """
        self._sessions = {}
        self.load_error = None
        self._fingerprint = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.load_error = f"Could not create the data folder {self.path.parent}: {exc}"
            return

        if not self.path.exists():
            try:
                self._write({})
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

        problems: list[str] = []
        if not isinstance(data, dict):
            self.load_error = f"{self.path} must contain a JSON object with 'schema_version' and 'sessions'."
            return
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            self.load_error = (
                f"{self.path} has schema_version {version!r}; this version of the app reads "
                f"schema_version {SCHEMA_VERSION}."
            )
            return
        records = data.get("sessions")
        if not isinstance(records, list):
            self.load_error = f"{self.path} is missing its 'sessions' list."
            return

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
            self._sessions[session.id] = session

        if problems:
            shown = problems[:MAX_REPORTED_PROBLEMS]
            more = len(problems) - len(shown)
            text = "\n".join(f"• {p}" for p in shown)
            if more:
                text += f"\n• …and {more} more"
            self.load_error = (
                f"{len(problems)} of {len(records)} saved record(s) in {self.path} are invalid:\n{text}"
            )

    # -- changes ---------------------------------------------------------

    def add(self, session: Session) -> None:
        self._ensure_valid(session)
        if session.id in self._sessions:
            raise StorageError("A session with this id already exists; use update instead.")
        self._ensure_available(session)
        updated = dict(self._sessions)
        updated[session.id] = session.copy()
        self._commit(updated)

    def update(self, session: Session) -> None:
        existing = self._sessions.get(session.id)
        if existing is None:
            raise StorageError("This session no longer exists in the data file.")
        if session.entry_time != existing.entry_time:
            raise StorageError("The original entry time of a session cannot be changed.")
        self._ensure_valid(session)
        self._ensure_available(session)
        updated = dict(self._sessions)
        updated[session.id] = session.copy()
        self._commit(updated)

    def _ensure_valid(self, session: Session) -> None:
        problems = session.problems()
        if problems:
            raise ValidationError(problems)

    def _ensure_available(self, session: Session) -> None:
        conflicts = find_conflicts(
            self._sessions.values(), session.device, session.start, session.end, exclude_id=session.id
        )
        if conflicts:
            raise ConflictError(session.device, conflicts)

    def _commit(self, updated: dict[str, Session]) -> None:
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
        self._write(updated)
        self._sessions = updated

    # -- file IO ---------------------------------------------------------

    def _stat(self) -> tuple[int, int] | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_mtime_ns, st.st_size

    def _write(self, sessions: dict[str, Session]) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "sessions": [s.to_dict() for s in sorted(sessions.values(), key=lambda s: s.entry_time)],
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
