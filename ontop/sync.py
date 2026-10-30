"""Upload new and changed sessions and passes to the online dashboard (cafe-web Worker).

Threading: Tkinter is not thread-safe, so ``SyncController`` runs on the Tk thread. Every
``interval_seconds`` (and on "Sync Now") it copies the records into plain dicts and hands them
to a background ``SyncWorker`` thread, which hashes them, talks HTTPS to the Worker, retries and
saves ``sync_state.json``. Results come back through a queue the Tk thread polls with
``after``, so the window never waits on the network. The worker never touches
``sessions.json``, so it cannot interfere with the app's own saves.

Change tracking: ``sync_state.json`` (in the data folder) remembers, per record id, a content
hash, a revision and whether the server acknowledged it. Only records whose hash changed (or
that were never acknowledged) are sent. Revisions start from ``last_updated`` (seconds × 1000)
and only ever increase; the server ignores any upload whose revision is not newer than the one
it has, so a delayed or repeated request can never overwrite newer data.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import ssl
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from . import config as cafe_config
from .formatting import fmt_clock, now_local, parse_iso, to_iso, to_local
from .models import MonthlyPass, Session

CONFIG_FILE = "sync_config.json"
STATE_FILE = "sync_state.json"
DEFAULT_INTERVAL = 300
BATCH_SIZE = 40  # the Worker accepts at most 40 records per request
RETRY_DELAYS = (2, 10, 30)  # seconds between attempts of one request
REQUEST_TIMEOUT = 20
MIN_TOKEN_LENGTH = 32
USER_AGENT = "OnTopGaming-Desktop-Sync/1"
KINDS = ("sessions", "passes")


class SyncError(Exception):
    """The upload failed; the message is shown to the user."""


@dataclass(frozen=True)
class SyncConfig:
    url: str
    token: str = field(repr=False)
    interval_seconds: int = DEFAULT_INTERVAL

    @property
    def endpoint(self) -> str:
        return self.url.rstrip("/") + "/api/sync"


def config_path(app_dir: Path) -> Path:
    return Path(app_dir) / CONFIG_FILE


def load_config(path: Path) -> tuple[SyncConfig | None, str | None]:
    """(config, None) when sync is set up, (None, None) when not set up, (None, problem) when invalid."""
    path = Path(path)
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))  # Notepad may add a byte-order mark
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{path.name} could not be read: {exc}"
    if not isinstance(data, dict):
        return None, f"{path.name} must contain a JSON object."
    if data.get("enabled", True) is False:
        return None, None
    problems = []
    url = data.get("url")
    parts = urlsplit(url) if isinstance(url, str) else None
    local = parts is not None and parts.hostname in ("localhost", "127.0.0.1")
    if parts is None or not parts.hostname or parts.scheme not in ("https", "http") or (
            parts.scheme == "http" and not local):
        problems.append("'url' must be the https:// address of the dashboard (http:// only for localhost testing).")
    elif parts.username or parts.password or parts.query or parts.fragment:
        problems.append("'url' must not contain a username, password, query or fragment.")
    token = data.get("token")
    if not isinstance(token, str) or len(token.strip()) < MIN_TOKEN_LENGTH:
        problems.append(f"'token' must be the SYNC_TOKEN secret (at least {MIN_TOKEN_LENGTH} characters).")
    interval = data.get("interval_seconds", DEFAULT_INTERVAL)
    if isinstance(interval, bool) or not isinstance(interval, int) or not 60 <= interval <= 86_400:
        problems.append("'interval_seconds' must be a whole number from 60 to 86400.")
    if not problems and ("YOUR-SUBDOMAIN" in url or token.startswith("PASTE-")):
        problems.append("replace the example 'url' and 'token' with your dashboard address and SYNC_TOKEN.")
    if problems:
        return None, f"{path.name}: " + " ".join(problems)
    return SyncConfig(url=url.rstrip("/"), token=token.strip(), interval_seconds=interval), None


# --------------------------------------------------------------------------
# Payloads (built on the Tk thread: cheap copies only, no hashing or IO)
# --------------------------------------------------------------------------

def session_payload(s: Session) -> dict:
    return {
        "id": s.id,
        "customer_name": s.customer_name,
        "device": s.device,
        "players": s.players,
        "pass_id": s.pass_id,
        "start": to_iso(s.start),
        "end": to_iso(s.end),
        "duration_minutes": s.duration_minutes,
        "payment_method": s.payment_method,
        "total_paise": s.total_paise,
        "paid_paise": s.paid_paise,
        "payment_status": s.payment_status,
        "extension_minutes": sum(e.minutes_added for e in s.extensions),
        "entry_time": to_iso(s.entry_time),
        "last_updated": to_iso(s.last_updated),
    }


def pass_payload(p: MonthlyPass) -> dict:
    # Holder name and phone number stay on the café PC; the dashboard only needs the sale.
    return {
        "id": p.id,
        "purchased_on": p.purchased_on.isoformat(),
        "valid_until": p.valid_until.isoformat(),
        "hours": p.hours,
        "price_paise": p.price_paise,
        "payment_method": p.payment_method,
        "created_at": to_iso(p.created_at),
        "last_updated": to_iso(p.last_updated),
    }


@dataclass
class Snapshot:
    sessions: list[dict]
    passes: list[dict]
    cafe: dict


def take_snapshot(sessions: list[Session], passes: list[MonthlyPass]) -> Snapshot:
    return Snapshot(
        sessions=[session_payload(s) for s in sessions],
        passes=[pass_payload(p) for p in passes],
        cafe={
            "devices": list(cafe_config.DEVICES),
            "opening": cafe_config.OPENING_TIME.strftime("%H:%M"),
            "closing": cafe_config.CLOSING_TIME.strftime("%H:%M"),
        },
    )


def content_hash(record: dict) -> str:
    text = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def revision_base(record: dict) -> int:
    return int(parse_iso(record["last_updated"]).timestamp()) * 1000


# --------------------------------------------------------------------------
# Local sync state (worker thread only)
# --------------------------------------------------------------------------

class SyncState:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.endpoint: str | None = None
        self.dataset_id: str | None = None
        self.last_success_at: str | None = None
        self.records: dict[str, dict[str, dict]] = {kind: {} for kind in KINDS}

    @classmethod
    def load(cls, path: Path) -> "SyncState":
        state = cls(path)
        try:
            data = json.loads(state.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return state  # missing or damaged: start over; the server ignores repeats
        if not isinstance(data, dict):
            return state
        state.endpoint = data.get("endpoint") if isinstance(data.get("endpoint"), str) else None
        state.dataset_id = data.get("dataset_id") if isinstance(data.get("dataset_id"), str) else None
        state.last_success_at = data.get("last_success_at") if isinstance(data.get("last_success_at"), str) else None
        records = data.get("records")
        for kind in KINDS:
            entries = records.get(kind) if isinstance(records, dict) else None
            if isinstance(entries, dict):
                state.records[kind] = {
                    k: v for k, v in entries.items()
                    if isinstance(v, dict) and isinstance(v.get("rev"), int) and isinstance(v.get("hash"), str)
                }
        return state

    def forget_acknowledgements(self) -> None:
        """Send everything again (new server or database); revisions are kept so they stay increasing."""
        for entries in self.records.values():
            for entry in entries.values():
                entry["acked"] = False

    def save(self) -> None:
        payload = {
            "version": 1,
            "endpoint": self.endpoint,
            "dataset_id": self.dataset_id,
            "last_success_at": self.last_success_at,
            "records": self.records,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".sync-state-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, separators=(",", ":"))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: they could carry the sync token to another address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"Unexpected redirect to {newurl}", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))

Transport = Callable[[str, str, dict, float], dict]


def http_post(url: str, token: str, body: dict, timeout: float) -> dict:
    data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    })
    with _OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class _Retryable(Exception):
    pass


def _post_with_retry(transport: Transport, config: SyncConfig, body: dict, stop: threading.Event,
                     delays: tuple[float, ...]) -> dict:
    last = "unknown error"
    for attempt in range(len(delays) + 1):
        if attempt:
            if stop.wait(delays[attempt - 1]):
                raise SyncError("Sync stopped.")
        try:
            result = transport(config.endpoint, config.token, body, REQUEST_TIMEOUT)
            if not isinstance(result, dict):
                raise SyncError("The server sent an unexpected reply.")
            return result
        except urllib.error.HTTPError as exc:
            message = _error_message(exc)
            if exc.code in (408, 425, 429) or exc.code >= 500:
                last = f"server error {exc.code}: {message}"
                continue
            if exc.code == 401:
                raise SyncError("The server rejected the sync token. Check 'token' in sync_config.json.") from None
            raise SyncError(f"The server refused the upload ({exc.code}): {message}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            last = f"could not reach the server ({reason})"
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise SyncError(f"The server's HTTPS certificate is not trusted: {reason}") from None
        except (ValueError, UnicodeDecodeError):
            last = "the server sent a reply that is not JSON"
    raise SyncError(f"Upload failed after {len(delays) + 1} attempts: {last}.")


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        data = json.loads(exc.read().decode("utf-8"))
        if isinstance(data, dict) and isinstance(data.get("error"), str):
            return data["error"][:300]
    except Exception:  # noqa: BLE001 - best effort only
        pass
    return str(exc.reason)


# --------------------------------------------------------------------------
# One sync run (worker thread)
# --------------------------------------------------------------------------

@dataclass
class SyncResult:
    ok: bool
    finished_at: datetime
    sent: int = 0
    stored: int = 0
    skipped_older: int = 0
    invalid: list[str] = field(default_factory=list)
    error: str | None = None


def _plan(snapshot: Snapshot, state: SyncState) -> dict[str, list[dict]]:
    pending: dict[str, list[dict]] = {kind: [] for kind in KINDS}
    for kind in KINDS:
        entries = state.records[kind]
        for record in getattr(snapshot, kind):
            digest = content_hash(record)
            entry = entries.get(record["id"])
            if entry is not None and entry["hash"] == digest:
                if entry.get("acked"):
                    continue
                revision = entry["rev"]
            else:
                base = revision_base(record)
                revision = base if entry is None else max(base, entry["rev"] + 1)
                entries[record["id"]] = {"rev": revision, "hash": digest, "acked": False}
            pending[kind].append({**record, "revision": revision})
    return pending


def run_sync(snapshot: Snapshot, config: SyncConfig, state: SyncState, *, transport: Transport = http_post,
             stop: threading.Event | None = None, delays: tuple[float, ...] = RETRY_DELAYS) -> SyncResult:
    stop = stop or threading.Event()
    result = SyncResult(ok=False, finished_at=now_local())
    if state.endpoint != config.endpoint:
        state.endpoint = config.endpoint
        state.dataset_id = None
        state.forget_acknowledgements()

    restarted = False
    rounds = 0
    while True:
        rounds += 1
        pending = _plan(snapshot, state)
        state.save()  # revisions are assigned before sending, so a retry reuses them
        items = [(kind, record) for kind in KINDS for record in pending[kind]]
        batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)] or [[]]
        resend = False
        for index, batch in enumerate(batches):
            body: dict = {kind: [r for k, r in batch if k == kind] for kind in KINDS}
            body["dataset_id"] = state.dataset_id
            body["final"] = index == len(batches) - 1
            if body["final"]:
                body["cafe"] = snapshot.cafe
            reply = _post_with_retry(transport, config, body, stop, delays)
            result.sent += len(batch)
            dataset_id = reply.get("dataset_id")
            if not isinstance(dataset_id, str):
                raise SyncError("The server reply is missing its dataset id.")
            if state.dataset_id is None:
                state.dataset_id = dataset_id
            elif dataset_id != state.dataset_id:
                if restarted:
                    raise SyncError("The server database changed during the upload; will try again later.")
                # The online database was recreated: upload everything again.
                state.dataset_id = dataset_id
                state.forget_acknowledgements()
                restarted = True
                resend = True
                break
            resend |= _apply_results(reply.get("results"), batch, state, result)
            state.save()
        if not resend or rounds >= 3:
            break

    result.ok = True
    result.finished_at = now_local()
    state.last_success_at = to_iso(result.finished_at)
    state.save()
    return result


def _apply_results(results: object, batch: list[tuple[str, dict]], state: SyncState, result: SyncResult) -> bool:
    """Mark acknowledged records; return True when some records should be resent straight away."""
    resend = False
    results = results if isinstance(results, dict) else {}
    for kind, record in batch:
        outcome = (results.get(kind) or {}).get(record["id"]) if isinstance(results.get(kind), dict) else None
        entry = state.records[kind][record["id"]]
        status = outcome.get("status") if isinstance(outcome, dict) else None
        if status in ("inserted", "updated", "unchanged"):
            entry["acked"] = True
            result.stored += status != "unchanged"
        elif status == "invalid":
            entry["acked"] = True  # it will be sent again once it changes
            result.invalid.append(f"{kind[:-1]} {record['id']}: {outcome.get('error', 'rejected')}")
        elif status == "stale":
            server_rev = outcome.get("server_revision")
            if isinstance(server_rev, int) and revision_base(record) // 1000 >= server_rev // 1000:
                # Same or newer edit, but our counter is behind the server (e.g. sync_state.json was
                # reset). Move past the server's revision and send again.
                entry["rev"] = server_rev + 1
                resend = True
            elif isinstance(server_rev, int):
                entry["acked"] = True  # the server already has a newer version of this record
                result.skipped_older += 1
        # Missing or unknown status: leave unacknowledged so the next run retries it.
    return resend


# --------------------------------------------------------------------------
# Background thread and Tk-side controller
# --------------------------------------------------------------------------

class SyncWorker(threading.Thread):
    def __init__(self, config: SyncConfig, state_path: Path, transport: Transport = http_post,
                 delays: tuple[float, ...] = RETRY_DELAYS):
        super().__init__(name="online-sync", daemon=True)
        self.config = config
        self.state_path = Path(state_path)
        self.transport = transport
        self.delays = delays
        self.jobs: queue.Queue[Snapshot | None] = queue.Queue()
        self.results: queue.Queue[SyncResult] = queue.Queue()
        self.stop_event = threading.Event()

    def run(self) -> None:
        while True:
            snapshot = self.jobs.get()
            if snapshot is None or self.stop_event.is_set():
                return
            state = SyncState.load(self.state_path)
            try:
                outcome = run_sync(snapshot, self.config, state, transport=self.transport, stop=self.stop_event,
                                   delays=self.delays)
            except SyncError as exc:
                outcome = SyncResult(ok=False, finished_at=now_local(), error=str(exc))
            except Exception as exc:  # noqa: BLE001 - keep the thread alive and report it
                outcome = SyncResult(ok=False, finished_at=now_local(), error=f"Unexpected error: {exc!r}")
            self.results.put(outcome)

    def stop(self) -> None:
        self.stop_event.set()
        self.jobs.put(None)


class SyncController:
    """Schedules uploads from the Tk thread and reports status through ``on_status(text, level)``.

    ``level`` is "off", "busy", "ok" or "error".
    """

    POLL_MS = 400

    def __init__(self, root, store, config: SyncConfig | None, config_error: str | None, state_path: Path,
                 worker: SyncWorker | None = None):
        self.root = root
        self.store = store
        self.config = config
        self.config_error = config_error
        self.state_path = Path(state_path)
        self.worker = worker or (SyncWorker(config, state_path) if config else None)
        self.busy = False
        self._again = False
        self._tick_job: str | None = None
        self._poll_job: str | None = None
        self.last_result: SyncResult | None = None
        self.last_success: datetime | None = None
        self.on_status: Callable[[str, str], None] = lambda text, level: None
        if config:
            saved = SyncState.load(self.state_path)
            if saved.endpoint == config.endpoint and saved.last_success_at:
                try:
                    self.last_success = parse_iso(saved.last_success_at)
                except ValueError:
                    pass

    @property
    def enabled(self) -> bool:
        return self.worker is not None

    def start(self) -> None:
        self._report()
        if not self.enabled:
            return
        self.worker.start()
        self._tick_job = self.root.after(1500, self._tick)
        self._poll_job = self.root.after(self.POLL_MS, self._poll)

    def stop(self) -> None:
        for job in (self._tick_job, self._poll_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except Exception:  # noqa: BLE001 - root may already be gone
                    pass
        self._tick_job = self._poll_job = None
        if self.worker is not None:
            self.worker.stop()

    def sync_now(self) -> None:
        if not self.enabled:
            return
        if self.busy:
            self._again = True
            return
        try:
            snapshot = take_snapshot(self.store.sessions, self.store.passes)
        except Exception as exc:  # noqa: BLE001 - never let sync break the app
            self.last_result = SyncResult(ok=False, finished_at=now_local(), error=f"Could not read records: {exc}")
            self._report()
            return
        self.busy = True
        self.worker.jobs.put(snapshot)
        self._report()

    def _tick(self) -> None:
        self.sync_now()
        self._tick_job = self.root.after(self.config.interval_seconds * 1000, self._tick)

    def _poll(self) -> None:
        try:
            while True:
                result = self.worker.results.get_nowait()
                self.busy = False
                self.last_result = result
                if result.ok:
                    self.last_success = result.finished_at
                self._report()
        except queue.Empty:
            pass
        if self._again and not self.busy:
            self._again = False
            self.sync_now()
        self._poll_job = self.root.after(self.POLL_MS, self._poll)

    def status(self) -> tuple[str, str]:
        if self.config_error:
            return "Online sync: settings problem", "error"
        if not self.enabled:
            return "Online sync off", "off"
        when = f"last synced {_when(self.last_success)}" if self.last_success else "not synced yet"
        if self.busy:
            return f"Syncing… ({when})", "busy"
        r = self.last_result
        if r is not None and not r.ok:
            return f"Sync failed, will retry · {when}", "error"
        if r is not None and (r.invalid or r.skipped_older):
            return f"Synced with warnings · {when}", "error"
        return f"Online: {when}" if self.last_success else "Online sync: waiting for first upload", "ok"

    def details(self) -> str:
        """Longer explanation for the Sync Now dialog / tooltip."""
        if self.config_error:
            return self.config_error
        if not self.enabled:
            return ("Online sync is not set up. Copy sync_config.example.json to sync_config.json next to "
                    "main.py, fill in the dashboard address and SYNC_TOKEN, then restart the app.")
        r = self.last_result
        lines = []
        if self.last_success:
            lines.append(f"Last successful sync: {_when(self.last_success)}.")
        if r is not None and r.error:
            lines.append(f"Last attempt failed: {r.error}")
        if r is not None and r.ok:
            lines.append(f"Last run uploaded {r.stored} new or changed record(s).")
        if r is not None and r.skipped_older:
            lines.append(f"{r.skipped_older} record(s) were skipped because the server has a newer version.")
        if r is not None and r.invalid:
            lines.append("Rejected by the server:\n" + "\n".join(f"• {x}" for x in r.invalid[:5]))
        lines.append(f"Uploads run at startup and every {self.config.interval_seconds // 60} minutes.")
        return "\n".join(lines)

    def _report(self) -> None:
        text, level = self.status()
        self.on_status(text, level)


def _when(dt: datetime) -> str:
    local = to_local(dt)
    return f"{local:%d %b}, {fmt_clock(local)}"
