"""Online sync: config loading, change tracking, retries and the non-blocking Tk controller."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
import urllib.error
from datetime import timedelta
from pathlib import Path

from ontop import sync
from test_core import NOW, make, make_pass

URL = "https://dash.example.com"
TOKEN = "t" * 40


class FakeServer:
    """Mimics the Worker's /api/sync rules (content hash + revision guard) in memory."""

    def __init__(self):
        self.dataset_id = "dataset-1"
        self.rows = {"sessions": {}, "passes": {}}
        self.requests: list[dict] = []
        self.fail_next: list[Exception] = []

    def __call__(self, url, token, body, timeout):
        if self.fail_next:
            raise self.fail_next.pop(0)
        assert url == URL + "/api/sync" and token == TOKEN
        self.requests.append(json.loads(json.dumps(body)))
        assert len(body["sessions"]) + len(body["passes"]) <= 40
        results = {"sessions": {}, "passes": {}}
        for kind in ("sessions", "passes"):
            for record in body[kind]:
                content = {k: v for k, v in record.items() if k != "revision"}
                old = self.rows[kind].get(record["id"])
                if old is None:
                    status = "inserted"
                elif old["content"] == content:
                    status = "unchanged"
                elif record["revision"] > old["revision"]:
                    status = "updated"
                else:
                    results[kind][record["id"]] = {"status": "stale", "server_revision": old["revision"]}
                    continue
                if old is None or record["revision"] > old["revision"]:
                    self.rows[kind][record["id"]] = {"revision": record["revision"], "content": content}
                results[kind][record["id"]] = {"status": status}
        return {"dataset_id": self.dataset_id, "results": results, "final": body["final"]}

    def sent_ids(self, index=-1):
        r = self.requests[index]
        return {x["id"] for x in r["sessions"] + r["passes"]}


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / sync.CONFIG_FILE

    def write(self, **data):
        self.path.write_text(json.dumps(data), encoding="utf-8")
        return sync.load_config(self.path)

    def test_missing_or_disabled_means_off(self):
        self.assertEqual(sync.load_config(self.path), (None, None))
        self.assertEqual(self.write(enabled=False, url="nonsense"), (None, None))

    def test_valid_and_invalid(self):
        config, problem = self.write(url=URL + "/", token=TOKEN)
        self.assertIsNone(problem)
        self.assertEqual((config.endpoint, config.interval_seconds), (URL + "/api/sync", 300))
        self.assertNotIn(TOKEN, repr(config))
        self.assertIsNotNone(self.write(url="http://dash.example.com", token=TOKEN)[1])  # plain http
        self.assertIsNone(self.write(url="http://localhost:8787", token=TOKEN)[1])  # allowed for testing
        self.assertIsNotNone(self.write(url=URL, token="short")[1])
        self.assertIsNotNone(self.write(url=URL, token=TOKEN, interval_seconds=5)[1])
        self.path.write_text("\ufeff" + json.dumps({"url": URL, "token": TOKEN}), encoding="utf-8")
        self.assertIsNone(sync.load_config(self.path)[1], "a byte-order mark from Notepad is accepted")
        example = json.loads((Path(__file__).parents[1] / "sync_config.example.json").read_text(encoding="utf-8"))
        self.assertIn("replace the example", self.write(**example)[1])


class RunSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_path = Path(self.tmp.name) / sync.STATE_FILE
        self.config = sync.SyncConfig(URL, TOKEN)
        self.server = FakeServer()
        self.pass_ = make_pass()
        self.sessions = [make(name=f"Customer {i}", start=f"{10 + i // 2}:{'30' if i % 2 else '00'}",
                              end=f"{10 + (i + 1) // 2}:{'30' if (i + 1) % 2 else '00'}", device="PS4")
                         for i in range(20)]

    def run_sync(self, sessions=None, passes=None, **kw):
        snap = sync.take_snapshot(self.sessions if sessions is None else sessions,
                                  [self.pass_] if passes is None else passes)
        state = sync.SyncState.load(self.state_path)
        return sync.run_sync(snap, self.config, state, transport=self.server, delays=(0, 0, 0), **kw)

    def test_initial_upload_then_only_changes(self):
        result = self.run_sync()
        self.assertTrue(result.ok)
        self.assertEqual(result.stored, 21)
        self.assertEqual(len(self.server.rows["sessions"]), 20)
        self.assertTrue(self.server.requests[-1]["final"])
        self.assertNotIn("phone", self.server.requests[0]["passes"][0])
        self.assertNotIn("holder_name", self.server.requests[0]["passes"][0])

        self.run_sync()  # nothing changed: one empty heartbeat request marks the sync as done
        self.assertEqual(self.server.requests[-1]["sessions"], [])
        self.assertTrue(self.server.requests[-1]["final"])

        changed = dataclasses.replace(self.sessions[3], paid_paise=0, payment_status="Unpaid",
                                      last_updated=self.sessions[3].last_updated + timedelta(minutes=5))
        sessions = self.sessions[:3] + [changed] + self.sessions[4:]
        self.run_sync(sessions)
        self.assertEqual(self.server.sent_ids(), {changed.id})
        row = self.server.rows["sessions"][changed.id]
        self.assertEqual(row["content"]["payment_status"], "Unpaid")
        self.assertGreater(row["revision"], sync.revision_base(sync.session_payload(self.sessions[3])))

    def test_session_ids_are_preserved(self):
        self.run_sync()
        self.assertEqual(set(self.server.rows["sessions"]), {s.id for s in self.sessions})

    def test_same_second_edits_get_increasing_revisions(self):
        self.run_sync()
        first = self.sessions[0]
        for paid in (100_00, 50_00):  # identical last_updated, different content
            edit = dataclasses.replace(first, paid_paise=paid, total_paise=200_00, payment_status="Partially Paid")
            self.run_sync([edit] + self.sessions[1:])
        self.assertEqual(self.server.rows["sessions"][first.id]["content"]["paid_paise"], 50_00)

    def test_batches_respect_request_limit(self):
        many = [make(name=f"N{i}", day=NOW.date() + timedelta(days=i), start="12:00", end="13:00") for i in range(95)]
        self.run_sync(many, [])
        self.assertEqual([len(r["sessions"]) for r in self.server.requests], [40, 40, 15])
        self.assertEqual([r["final"] for r in self.server.requests], [False, False, True])

    def test_new_database_triggers_full_upload(self):
        self.run_sync()
        self.server.rows = {"sessions": {}, "passes": {}}
        self.server.dataset_id = "dataset-2"
        self.run_sync()
        self.assertEqual(len(self.server.rows["sessions"]), 20)
        self.assertEqual(len(self.server.rows["passes"]), 1)

    def test_lost_state_file_recovers_without_overwriting_newer_data(self):
        self.run_sync()
        first = dataclasses.replace(self.sessions[0], customer_name="Edit One")  # same last_updated second
        self.run_sync([first] + self.sessions[1:])
        self.state_path.unlink()
        # The server's revision is now ahead of a fresh counter; a newer edit must still get through.
        second = dataclasses.replace(self.sessions[0], customer_name="Edit Two")
        result = self.run_sync([second] + self.sessions[1:])
        self.assertTrue(result.ok)
        self.assertEqual(result.skipped_older, 0)
        self.assertEqual(self.server.rows["sessions"][second.id]["content"]["customer_name"], "Edit Two")

    def test_older_copy_is_not_uploaded_over_newer(self):
        newer = dataclasses.replace(self.sessions[0], customer_name="Newer Name",
                                    last_updated=self.sessions[0].last_updated + timedelta(hours=1))
        self.run_sync([newer] + self.sessions[1:])
        self.state_path.unlink()
        result = self.run_sync()  # e.g. an old backup of sessions.json restored on the PC
        self.assertEqual(result.skipped_older, 1)
        self.assertEqual(self.server.rows["sessions"][newer.id]["content"]["customer_name"], "Newer Name")

    def test_retries_network_errors_then_succeeds(self):
        self.server.fail_next = [urllib.error.URLError("offline"), TimeoutError("slow")]
        self.assertTrue(self.run_sync().ok)

    def test_gives_up_after_retries_and_keeps_changes_pending(self):
        self.server.fail_next = [urllib.error.URLError("offline")] * 4
        with self.assertRaises(sync.SyncError):
            self.run_sync()
        self.assertEqual(self.server.rows["sessions"], {})
        self.run_sync()
        self.assertEqual(len(self.server.rows["sessions"]), 20)

    def test_bad_token_is_not_retried(self):
        self.server.fail_next = [urllib.error.HTTPError(URL, 401, "Unauthorized", {}, None),
                                 urllib.error.URLError("should not be reached")]
        with self.assertRaisesRegex(sync.SyncError, "token"):
            self.run_sync()
        self.assertEqual(len(self.server.fail_next), 1)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_sync_runs_in_background_without_blocking_tk(self):
        release = threading.Event()
        server = FakeServer()

        def slow(*args):
            release.wait(5)
            return server(*args)

        class Store:
            sessions = [make()]
            passes = []

        state = Path(self.tmp.name) / sync.STATE_FILE
        config = sync.SyncConfig(URL, TOKEN)
        controller = sync.SyncController(self.root, Store(), config, None, state,
                                         worker=sync.SyncWorker(config, state, transport=slow, delays=(0,)))
        statuses = []
        controller.on_status = lambda text, level: statuses.append(level)
        controller.start()
        self.addCleanup(controller.stop)
        began = time.perf_counter()
        controller.sync_now()
        self.assertLess(time.perf_counter() - began, 0.2)
        self.assertEqual(statuses[-1], "busy")
        controller.sync_now()  # while busy: queued, not run twice at once
        release.set()
        deadline = time.time() + 5
        while statuses[-1] == "busy" and time.time() < deadline:
            self.root.update()
            time.sleep(0.02)
        self.assertEqual(statuses[-1], "ok")
        self.assertTrue(state.exists())
        self.assertIn("Online: last synced", controller.status()[0])

    def test_not_configured(self):
        controller = sync.SyncController(self.root, None, None, None, Path(self.tmp.name) / sync.STATE_FILE)
        controller.start()
        self.assertFalse(controller.enabled)
        self.assertEqual(controller.status(), ("Online sync off", "off"))
        self.assertIn("sync_config.example.json", controller.details())


if __name__ == "__main__":
    unittest.main()
