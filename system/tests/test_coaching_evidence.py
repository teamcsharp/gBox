"""Report receipt is distinct from later worker captures, and missing sources are explicit."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import coaching as C, coaching_evidence as E, tactical_map
from gbox.models import new_id
from gbox.store import Store

JPEG = b"\xff\xd8report moment\xff\xd9"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Captured map</text></svg>'
SID, GAME = "worker-session", "a" * 16


def sources():
    return {"stream": {"data": JPEG, "at": 99.25, "seq": 7},
            "tactical": {"frame": {"v": 1, "stage": "room", "t": 98.9,
                "player": {"hp": 1, "pos": [0, 0, 0]},
                "enemies": [{"hp": 20, "distance_cm": 100, "visibility": "blocked"}]},
                "stage": None, "at": 99.5, "seq": 8},
            "telemetry": {"data": {"at": 99, "stats": {"combat": "tracking", "qte": "mash:circle"}}, "at": 99},
            "ram_fields": {"data": {"rows": [{"address": "0x1000", "display": "0x0001", "value": 1}],
                                    "raw": {"hp": 1}}, "at": 98}}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="gbox-evidence-")
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name))
        self.addCleanup(self.store.db.close)
        self.store.upsert_catalog([{"game_id": GAME, "title": "RE5", "platform": "ps3"}])
        self.store.put("session", SID, {"session_id": SID, "game_id": GAME, "state": "running", "adapter": "rpcs3"})
        self.store.put("worker", "worker", {"name": "test", "last_seen": time.time()})

    def create(self, body, actor):
        request = body | {"id": new_id(), "number": len(self.store.all("request")) + 1,
                          "status": "open", "messages": [], "created": time.time()}
        self.store.put("request", request["id"], request)
        return request

    def test_frozen_sources_and_independent_age_survive_later_mutation(self):
        original = sources()
        packet = E.capture(lambda sid: original, SID, 100)
        original["tactical"]["frame"]["player"]["hp"] = 30000
        original["telemetry"]["data"]["stats"]["qte"] = None
        evidence, attachments = E.attach(self.store, packet, 1, "request", renderer=lambda *a: SVG)
        manifest = json.loads(self.store.read_artifact(evidence["moment"]["sha256"]))
        self.assertEqual(manifest["sources"]["tactical"]["frame"]["player"]["hp"], 1)
        self.assertEqual(manifest["sources"]["telemetry"]["data"]["stats"]["qte"], "mash:circle")
        self.assertEqual(evidence["stream"]["age_s"], .75)
        self.assertEqual(evidence["map"]["age_s"], .5)
        self.assertEqual(self.store.read_artifact(evidence["stream"]["sha256"]), JPEG)
        self.assertEqual(len(attachments), 3)
        self.assertNotIn("data", manifest["sources"]["stream"])

    def test_missing_stale_and_invalid_sources_are_not_called_fresh(self):
        original = sources()
        original["stream"]["at"] = 10
        original["ram_fields"]["at"] = float("nan")
        original.pop("telemetry")
        packet = E.capture(lambda sid: original, SID, 100)
        evidence, _ = E.attach(self.store, packet, 1, "request", renderer=lambda *a: SVG)
        self.assertEqual(evidence["stream"]["age_s"], 90)
        self.assertIn("90.000s", evidence["stream"]["detail"])
        self.assertEqual(evidence["ram_fields"]["state"], "skipped")
        self.assertEqual(evidence["telemetry"]["state"], "skipped")

    def test_render_failure_preserves_actual_tactical_json_and_other_artifacts(self):
        packet = E.capture(lambda sid: sources(), SID, 100)
        def fail(*args): raise OSError("node unavailable")
        evidence, _ = E.attach(self.store, packet, 1, "request", renderer=fail)
        self.assertEqual(evidence["map"]["state"], "failed")
        self.assertIn("node unavailable", evidence["map"]["detail"])
        self.assertEqual(evidence["moment"]["state"], "done")
        manifest = json.loads(self.store.read_artifact(evidence["moment"]["sha256"]))
        self.assertEqual(manifest["sources"]["tactical"]["frame"]["enemies"][0]["visibility"], "blocked")

    def test_bounds_provider_failure_and_failed_manifest_storage_are_visible(self):
        original = sources(); original["stream"]["data"] = b"not jpeg"
        original["telemetry"]["data"] = {"big": "x" * E.JSON_MAX}
        packet = E.capture(lambda sid: original, SID, 100)
        self.assertIn("JPEG", packet["sources"]["stream"]["error"])
        self.assertIn("5 MiB", packet["sources"]["telemetry"]["error"])
        with patch.object(self.store, "put_artifact", side_effect=OSError("disk full")):
            evidence, _ = E.attach(self.store, packet, 1, "request", renderer=lambda *a: SVG)
        self.assertEqual(evidence["moment"]["state"], "failed")
        self.assertEqual(evidence["tactical"]["state"], "failed")
        def fail(sid): raise OSError("cache unavailable")
        self.assertIn("cache unavailable", E.capture(fail, SID, 100)["capture_error"])

    def test_cached_collector_uses_exact_session_and_never_refreshes_ram(self):
        maps = tactical_map.Store(clock=lambda: 99)
        maps.put_frame(SID, {"v": 1, "stage": "room", "player": {"hp": 1}})
        live = {SID: {"frame": JPEG, "seq": 7, "ts": 99, "cond": threading.Condition()},
                "other": {"frame": b"wrong session"}}
        values = SimpleNamespace(rows=lambda: [{"name": str(i)} for i in range(E.ROWS_MAX + 3)], raw={"hp": 1}, errors={})
        inspector = SimpleNamespace(eval_lock=threading.Lock(), last=values, last_at=98)
        inspectors = SimpleNamespace(_LOCK=threading.Lock(), _INSPECTORS={SID: inspector})
        result = E.cached(SID, live, maps, {SID: {"at": 99, "stats": {"hp": 1}}}, inspectors)
        self.assertEqual(result["stream"]["data"], JPEG)
        self.assertEqual(len(result["ram_fields"]["data"]["rows"]), E.ROWS_MAX)
        self.assertEqual(result["ram_fields"]["data"]["rows_omitted"], 3)
        self.assertEqual(result["ram_fields"]["data"]["raw_hex"], {"hp": "0x1"})
        with inspector.eval_lock:
            self.assertIn("busy", E.cached(SID, live, maps, {}, inspectors)["ram_fields"]["error"])
        self.assertEqual(E.cached("missing", live, maps, {}, inspectors), {})
        def failed_rows(): raise ValueError("bad cached map")
        values.rows = failed_rows
        result = E.cached(SID, live, maps, {}, inspectors)
        self.assertEqual(result["stream"]["data"], JPEG)
        self.assertIn("bad cached map", result["ram_fields"]["error"])

    def test_note_copies_before_worker_jobs_and_retry_keeps_same_evidence(self):
        original = sources(); copied = []
        def provider(sid):
            copied.append(sid)
            return original
        def submit(*args):
            original["stream"] = {"data": b"\xff\xd8later\xff\xd9", "at": 101, "seq": 9}
            original["tactical"]["frame"]["player"]["hp"] = 30000
            return {"id": "capture-job", "state": "queued"}
        with patch.object(E, "render_map", return_value=SVG), patch.object(C, "_lesson"):
            first = C.add_note(self.store, self.create, submit, SID, "recover now", now=100,
                               client_id="report-123", moment_provider=provider)
            second = C.add_note(self.store, self.create, submit, SID, "recover now", now=102,
                                client_id="report-123", moment_provider=provider)
        self.assertEqual(copied, [SID])
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertEqual(self.store.read_artifact(first["evidence"]["stream"]["sha256"]), JPEG)
        manifest = json.loads(self.store.read_artifact(first["evidence"]["moment"]["sha256"]))
        self.assertEqual(manifest["report_received_at"], 100)
        self.assertEqual(manifest["sources"]["tactical"]["frame"]["player"]["hp"], 1)
        self.assertEqual(first["captures"]["state"]["state"], "skipped")
        self.assertIn("rpcs3", first["captures"]["state"]["detail"])
        status = C.status(self.store, first["request_id"], first["message_id"])
        self.assertEqual(status["evidence"], first["evidence"])

    def test_http_concurrent_reports_freeze_each_ingress_before_waiting_for_submission_lock(self):
        first_started, second_copied, release_first = threading.Event(), threading.Event(), threading.Event()
        current, packets = sources(), {}
        calls = [0]
        def provider(sid):
            calls[0] += 1
            value = copy.deepcopy(current)
            if calls[0] == 2:
                second_copied.set()
            return value
        def file_note(store, create, submit, sid, text, actor, now, moment_provider, frozen_moment):
            packets[text] = frozen_moment
            if text == "first":
                first_started.set()
                self.assertTrue(release_first.wait(5))
            return {"request_id": "ticket", "message_id": text, "captures": {}, "evidence": {}}
        app = FastAPI()
        C.routes(app, self.store, lambda: "operator", self.create, None, moment_provider=provider)
        def post(text):
            with TestClient(app) as client:
                return client.post(f"/api/sessions/{SID}/coach", json={"text": text, "client_id": "note-" + text})
        with patch.object(C, "_add_note", side_effect=file_note), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(post, "first")
            try:
                self.assertTrue(first_started.wait(5))
                current["tactical"]["frame"]["player"]["hp"] = 2
                second = pool.submit(post, "second")
                self.assertTrue(second_copied.wait(5))  # proves it copied while the first note still held the lock
                current["tactical"]["frame"]["player"]["hp"] = 30000
            finally:
                released_at = time.time()
                release_first.set()
            self.assertEqual(first.result().status_code, 200)
            self.assertEqual(second.result().status_code, 200)
        self.assertEqual(packets["first"]["sources"]["tactical"]["frame"]["player"]["hp"], 1)
        self.assertEqual(packets["second"]["sources"]["tactical"]["frame"]["player"]["hp"], 2)
        self.assertLessEqual(packets["second"]["report_received_at"], released_at)


if __name__ == "__main__":
    unittest.main()
