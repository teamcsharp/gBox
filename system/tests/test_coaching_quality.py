"""Coaching notes must be actionable guidance (request #2961: no nonsense reaches the tickets)."""
import pytest

from gbox import coaching_quality as Q


@pytest.mark.parametrize("text", [
    "Stop walking into walls", "that's not an enemy", "aim at the enemy", "dies at the door in room 3, go around",
    "too slow", "Stuck at the ladder", "go after the enemy", "壁に向かって歩かないで",
])
def test_actionable_notes_pass(text):
    assert Q.check(text) is None


@pytest.mark.parametrize("text", ["", "   ", "!!!", "123", "ok", "lol", "test", "asdfgh", "aaaaaaa", "hi hello", "zxcvbnm", "👍"])
def test_nonsense_is_rejected_with_a_reason(text):
    assert Q.check(text)


def test_route_rejects_nonsense_before_filing(monkeypatch):
    from fastapi import HTTPException
    from gbox import coaching
    from fastapi import FastAPI
    app = FastAPI()
    filed = []
    monkeypatch.setattr(coaching, "add_note", lambda *a, **k: filed.append(a))

    class Store:
        def get(self, kind, key): return {"game_id": "g"}
    coaching.routes(app, Store(), lambda: "operator", lambda *a: {}, lambda *a: {})
    from fastapi.testclient import TestClient
    c = TestClient(app)
    r = c.post("/api/sessions/s1/coach", json={"text": "asdfgh"})
    assert r.status_code == 422 and filed == []
