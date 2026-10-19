"""#2388 / #2392: extracting a game that has no native reader queues the reader work instead of just failing."""
from types import SimpleNamespace

from gbox import characters as C, hermes_work_queue as Q


def _ctx(tmp_path):
    return SimpleNamespace(config=SimpleNamespace(cache=str(tmp_path / "cache")), progress=lambda *a: None)


def test_unsupported_collect_queues_reader_work_and_says_so(monkeypatch, tmp_path):
    game = {"game_id": "cd" * 8, "title": "No Reader Yet", "platform": "xbox360"}
    monkeypatch.setattr(C, "_game", lambda ctx, inp: game)
    queued = []
    monkeypatch.setattr(Q, "ensure_item", lambda g, **kw: queued.append((g, kw)) or {"game_id": g["game_id"], "new": True})
    res = C.collect(_ctx(tmp_path), C.CharIn(op="collect", game_id=game["game_id"]))
    assert res["status"] == "unsupported" and res["reader_work"] == {"game_id": "cd" * 8, "new": True}
    assert queued[0][0]["in_catalog"] is True and queued[0][1] == {"source": "collect"}
    assert "queued to build one" in res["message"]


def test_unsupported_collect_survives_a_busy_queue(monkeypatch, tmp_path):
    game = {"game_id": "ef" * 8, "title": "No Reader Yet", "platform": "xbox360"}
    monkeypatch.setattr(C, "_game", lambda ctx, inp: game)

    def busy(g, **kw):
        raise BlockingIOError("the queue tick holds the lock")
    monkeypatch.setattr(Q, "ensure_item", busy)
    res = C.collect(_ctx(tmp_path), C.CharIn(op="collect", game_id=game["game_id"]))
    assert res["status"] == "unsupported" and res["reader_work"] is None
    assert "no unrigged capture was substituted" in res["message"]
