"""Corrected #2969 queue contracts: durable evidence identity and normal Hermes admission."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import bots, coaching, hermes_work_queue as queue, tools
from gbox.models import new_id
from gbox.store import Store

GAME, SID = "a" * 16, "worker-session"


class BotQueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="gbox-coaching-test-")
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name))
        self.addCleanup(self.store.db.close)
        self.store.upsert_catalog([{"game_id": GAME, "title": "Test game", "platform": "ps3"}])
        self.store.put("session", SID, {"session_id": SID, "game_id": GAME, "state": "ended"})
        self.parent = self.create({"title": "Coaching", "source": "coach", "context": {"coaching": True,
                                  "game_id": GAME, "title": "Test game"}}, "operator")

    def create(self, body, actor):
        row = body | {"id": new_id(), "number": len(self.store.all("request")) + 1,
                      "status": "open", "messages": [], "created": 1, "automated": False}
        self.store.put("request", row["id"], row)
        return row

    def add(self, message="message", text="aim at the exposed enemy"):
        return bots.add_change(self.store, GAME, note=1, text=text, request_id=self.parent["id"],
                               message_id=message, session_id=SID)

    def test_real_tuple_module_contract_and_no_setup_or_play(self):
        seen = []
        def load(name, package):
            return SimpleNamespace(matches=lambda adapter, game: seen.append((name, adapter, game)) or name == ".second")
        with patch.object(tools, "PLAYBOOKS", ("first", "second")), patch.object(bots.importlib, "import_module", side_effect=load):
            self.assertEqual(bots.playbook_for({"game_id": GAME}), "second")
        self.assertEqual([x[0] for x in seen], [".first", ".second"])
        self.assertTrue(all(x[1] is None for x in seen))

    def test_same_note_and_concurrent_additions_do_not_lose_work(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            items = list(pool.map(self.add, ["same"] * 8 + [f"m{i}" for i in range(10)]))
        self.assertEqual(len({x["id"] for x in items[:8]}), 1)
        self.assertEqual(len(bots.changes_for(self.store, GAME)["items"]), 11)
        with self.assertRaises(ValueError):
            self.add("same", "different critique")

    def test_store_errors_propagate_and_corruption_is_not_overwritten(self):
        with patch.object(self.store, "put", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.add()
        with patch.object(self.store, "get", side_effect=OSError("unreadable")), self.assertRaises(OSError):
            self.add()
        self.store.put(bots.CHANGES_KIND, GAME, {"items": "damaged"})
        with self.assertRaises(ValueError):
            self.add()
        self.assertEqual(self.store.get(bots.CHANGES_KIND, GAME)["items"], "damaged")

    def test_bounded_queue_never_discards_unfinished_work(self):
        with patch.object(bots, "MAX_ITEMS", 2):
            first, second = self.add("one"), self.add("two")
            with self.assertRaises(ValueError):
                self.add("three")
            bots.set_change_state(self.store, GAME, first["id"], "applied", by="agent", pr="#800")
            bots.set_change_state(self.store, GAME, first["id"], "verified", by="agent", verification="Regression test passed")
            third = self.add("three")
        self.assertEqual({x["id"] for x in bots.changes_for(self.store, GAME)["items"]}, {second["id"], third["id"]})

    def test_transition_routes_need_pr_and_verification_and_auth_actor(self):
        item = self.add()
        app = FastAPI(); bots.routes(app, self.store, lambda: "agent")
        with TestClient(app) as client:
            url = f"/api/autoplay/bots/{GAME}/changes/{item['id']}"
            self.assertEqual(client.post(url, json={"state": "verified"}).status_code, 409)
            self.assertEqual(client.post(url, json={"state": "acknowledged"}).json()["by"], "agent")
            self.assertEqual(client.post(url, json={"state": "applied"}).status_code, 409)
            self.assertEqual(client.post(url, json={"state": "applied", "pr": "#800"}).status_code, 200)
            self.assertEqual(client.post(url, json={"state": "applied", "pr": "  "}).status_code, 409)
            self.assertEqual(client.post(url, json={"state": "verified", "verification": "  "}).status_code, 409)
            self.assertEqual(client.post(url, json={"state": "verified", "verification": "Test passed"}).status_code, 200)
            self.assertEqual(client.post(url, json={"state": "verified", "verification": "  "}).status_code, 409)
            saved = client.get(f"/api/autoplay/bots/{GAME}/changes").json()["items"][0]
            self.assertEqual((saved["state"], saved["pr"], saved["verification"]), ("verified", "#800", "Test passed"))

    def test_deduplicated_child_is_admitted_while_parent_stays_excluded_and_busy_game_holds(self):
        item = self.add()
        child_info = bots.ensure_request(self.store, self.create, GAME, item["id"], "operator")
        again = bots.ensure_request(self.store, self.create, GAME, item["id"], "operator")
        self.assertEqual(child_info["implementation_request_id"], again["implementation_request_id"])
        requests = self.store.all("request")
        self.assertEqual(len(requests), 2)
        child = self.store.get("request", child_info["implementation_request_id"])
        self.assertEqual(child["author"], "operator")
        self.assertEqual(child["parent_request_id"], self.parent["id"])
        self.assertNotIn("coaching", child["context"])
        data = {"version": 1, "items": {}, "last_lane": "inbox"}
        queue.sync(data, {"count": 0, "items": []}, requests, now=100)
        self.assertEqual(set(data["items"]), {"inbox:" + child["id"]})
        self.assertEqual(len(queue.candidates(data, requests, [], set(), set(), now=100)), 1)
        self.assertEqual(queue.candidates(data, requests, [{"input": {"game_id": GAME}}], set(), set(), now=100), [])
        self.assertEqual(queue.candidates(data, requests, [], {child["id"]}, set(), now=100), [])

    def test_lost_create_response_is_reconciled_without_duplicate_and_unknown_creation_is_held(self):
        item = self.add()
        def lost(body, actor):
            self.create(body, actor)
            raise OSError("response lost")
        with patch.object(self, "create", wraps=self.create) as create:
            result = bots.ensure_request(self.store, lost, GAME, item["id"], "operator")
            self.assertEqual(result["dispatch_state"], "queued")
            self.assertEqual(create.call_count, 1)
        other = self.add("other")
        with patch.object(self, "create", side_effect=OSError("unknown")) as create:
            for _ in range(2):
                result = bots.ensure_request(self.store, create, GAME, other["id"], "operator")
            self.assertEqual(result["dispatch_state"], "uncertain")
            self.assertEqual(create.call_count, 1)

    def test_actual_coach_route_links_one_change_child_and_original_evidence_note_on_retry(self):
        app = FastAPI(); coaching.routes(app, self.store, lambda: "operator", self.create, lambda *_: self.fail("ended session captures"))
        with TestClient(app) as client:
            body = {"text": "Aim at the exposed enemy", "client_id": "same-critique"}
            one = client.post(f"/api/sessions/{SID}/coach", json=body)
            self.assertEqual(one.status_code, 200, one.text)
            two = client.post(f"/api/sessions/{SID}/coach", json=body)
            self.assertEqual(two.status_code, 200, two.text)
        self.assertEqual(one.json()["change_id"], two.json()["change_id"])
        self.assertEqual(one.json()["implementation_request_id"], two.json()["implementation_request_id"])
        self.assertEqual(len(bots.changes_for(self.store, GAME)["items"]), 1)
        parent = self.store.get("request", one.json()["request_id"])
        self.assertEqual(len(parent["messages"]), 1)
        self.assertEqual(parent["messages"][0]["coach"]["change_id"], one.json()["change_id"])
        self.assertEqual(parent["messages"][0]["coach"]["session_id"], SID)


if __name__ == "__main__":
    unittest.main()
