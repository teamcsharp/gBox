"""Retrying a compact-window report must not capture a later moment or file a duplicate note."""
import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gbox import coaching as C


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.data = {("session", "s1"): {"game_id": "game"}, ("session", "s2"): {"game_id": "game"}}

    def get(self, kind, key):
        return copy.deepcopy(self.data.get((kind, key)))

    def put(self, kind, key, value):
        self.data[kind, key] = copy.deepcopy(value)


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.result = {"request_id": "ticket", "message_id": "note", "jobs": {"frame": "one"}, "captures": {}}

    def add(self, sid="s1", text="aim at him", actor="operator", client_id="unique-id"):
        return C.add_note(self.store, None, None, sid, text, actor, client_id=client_id)

    def test_retry_returns_the_original_message_and_jobs_without_resubmission(self):
        with patch.object(C, "_add_note", return_value=self.result) as submit:
            first = self.add()
            second = self.add()
        self.assertEqual(submit.call_count, 1)
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertEqual(first["jobs"], second["jobs"])
        self.assertTrue(second["deduplicated"])

    def test_concurrent_retries_submit_once(self):
        started, finish = threading.Event(), threading.Event()
        def submit(*args):
            started.set()
            self.assertTrue(finish.wait(2))
            return self.result
        with patch.object(C, "_add_note", side_effect=submit) as call, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.add)
            self.assertTrue(started.wait(2))
            second = pool.submit(self.add)
            finish.set()
            self.assertEqual(first.result()["message_id"], second.result()["message_id"])
        self.assertEqual(call.call_count, 1)

    def test_changed_text_is_rejected_but_actor_and_session_ids_are_separate(self):
        with patch.object(C, "_add_note", return_value=self.result) as submit:
            self.add()
            with self.assertRaises(HTTPException) as error:
                self.add(text="different")
            self.assertEqual(error.exception.status_code, 409)
            self.add(actor="agent")
            self.add(sid="s2")
        self.assertEqual(submit.call_count, 3)

    def test_interrupted_capture_submission_cannot_be_silently_replayed(self):
        with patch.object(C, "_add_note", side_effect=RuntimeError("interrupted after job submission")) as submit:
            with self.assertRaises(RuntimeError):
                self.add()
            with self.assertRaises(HTTPException) as error:
                self.add()
        self.assertEqual(submit.call_count, 1)
        self.assertIn("check the coaching ticket", error.exception.detail)

    def test_history_is_bounded_and_invalid_sessions_do_not_reserve(self):
        with patch.object(C, "_add_note", return_value=self.result) as submit:
            for i in range(C.NOTES_KEPT + 3):
                self.add(client_id=f"attempt-{i}")
            with self.assertRaises(HTTPException):
                self.add(sid="missing")
        entries = self.store.get("coaching_submissions", "s1")["entries"]
        self.assertEqual(len(entries), C.NOTES_KEPT)
        self.assertEqual(entries[0]["client_id"], "attempt-3")
        self.assertIsNone(self.store.get("coaching_submissions", "missing"))

    def test_legacy_calls_and_request_validation(self):
        with patch.object(C, "_add_note", return_value=self.result) as submit:
            self.add(client_id=None)
            self.add(client_id=None)
        self.assertEqual(submit.call_count, 2)
        self.assertEqual(C.NoteIn(text="hello", client_id="abc-1234").client_id, "abc-1234")
        for value in ("short", "bad/path", "x" * 97):
            with self.assertRaises(ValidationError):
                C.NoteIn(text="hello", client_id=value)

    def test_http_retry_forwards_exact_session_actor_and_does_not_spawn_another_capture_watcher(self):
        app = FastAPI()
        C.routes(app, self.store, lambda: "operator", None, None)
        result = self.result | {"captures": {"frame": {"state": "pending"}}}
        with patch.object(C, "_add_note", return_value=result) as submit, patch.object(C, "_spawn") as spawn, TestClient(app) as client:
            body = {"text": "  aim at him  ", "client_id": "stable-id"}
            first = client.post("/api/sessions/s1/coach", json=body)
            second = client.post("/api/sessions/s1/coach", json=body)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.json()["message_id"], first.json()["message_id"])
            self.assertTrue(second.json()["deduplicated"])
            self.assertEqual(submit.call_count, 1)
            self.assertEqual(submit.call_args.args[3:6], ("s1", "aim at him", "operator"))
            self.assertEqual(spawn.call_count, 1)

    def test_receipt_lookup_is_read_only_and_exact_session_actor_bound(self):
        app = FastAPI()
        C.routes(app, self.store, lambda: "operator", None, None)
        with patch.object(C, "_add_note", return_value=self.result) as submit, TestClient(app) as client:
            self.add()
            saved = client.get("/api/sessions/s1/coach/submissions/unique-id").json()
            self.assertEqual(saved["state"], "saved")
            self.assertEqual(saved["result"]["message_id"], "note")
            self.assertTrue(saved["result"]["deduplicated"])
            self.assertEqual(client.get("/api/sessions/s2/coach/submissions/unique-id").json()["state"], "missing")
            self.assertEqual(C.submission_status(self.store, "s1", "unique-id", "agent")["state"], "missing")
            self.assertEqual(client.get("/api/sessions/missing/coach/submissions/unique-id").status_code, 404)
            self.assertEqual(submit.call_count, 1)

    def test_receipt_can_observe_pending_without_waiting_for_submission_lock(self):
        started, finish = threading.Event(), threading.Event()
        def submit(*args):
            started.set()
            self.assertTrue(finish.wait(2))
            return self.result
        with patch.object(C, "_add_note", side_effect=submit), ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(self.add)
            self.assertTrue(started.wait(2))
            lookup = pool.submit(C.submission_status, self.store, "s1", "unique-id", "operator")
            self.assertEqual(lookup.result(timeout=.5)["state"], "pending")
            finish.set()
            future.result()


if __name__ == "__main__":
    unittest.main()
