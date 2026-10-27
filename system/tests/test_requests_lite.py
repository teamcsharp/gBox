"""GET /api/requests?lite=1, the Hermes queue's view of the inbox. 2026-10-27: the queue pump fetched the whole history
every tick, 46 MB built in ~4 s by the server that also relays the live game streams, which stalled right after."""
from fastapi.testclient import TestClient

from gbox import inbox
from gbox.server import create_app
from gbox.store import Store


def _client(cfg):
    app = create_app(cfg)
    return app, TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})


def test_lite_rows_drop_threads_and_metrics_and_cut_long_bodies_by_status(cfg):
    _, client = _client(cfg)
    long_open = client.post("/api/requests", json={"title": "Menus lag", "body": "m" * 3000}).json()["id"]
    long_done = client.post("/api/requests", json={"title": "Old", "body": "  " + "d" * 1000}).json()["id"]
    short = client.post("/api/requests", json={"title": "Typo", "body": "fix the typo"}).json()["id"]
    child = client.post("/api/requests", json={"title": "Sub", "body": "s" * 400, "source": "automation",
                                               "parent_request_id": short}).json()["id"]
    client.post(f"/api/requests/{long_open}/messages", json={"author": "agent", "text": "found it " * 500})
    client.post(f"/api/requests/{long_open}/metrics", json={"turns": 3, "tokens_in": 100})
    client.post(f"/api/requests/{long_done}/status", json={"status": "done", "note": "Verified"})
    full = client.get("/api/requests").json()
    lite = client.get("/api/requests?lite=1").json()
    assert [r["id"] for r in lite] == [r["id"] for r in full]          # same requests, same order
    rows = {r["id"]: r for r in lite}
    assert rows[long_open]["body"] == "m" * inbox.LITE_OPEN_BODY and rows[long_open]["body_chars"] == 3000
    assert rows[long_done]["body"] == "  " + "d" * inbox.LITE_CLOSED_BODY and rows[long_done]["body_chars"] == 1002
    assert rows[short]["body"] == "fix the typo" and "body_chars" not in rows[short]
    assert rows[child]["body"] == "s" * 400 and rows[child]["parent_request_id"] == short and rows[child]["automated"]
    for whole in full:
        row = rows[whole["id"]]
        assert "messages" not in row and "metrics" not in row
        assert {k: v for k, v in row.items() if k not in ("body", "body_chars")} == \
            {k: v for k, v in whole.items() if k not in ("body", "messages", "metrics")}   # organized as the full list
        assert whole["body"].startswith(row["body"])


def test_lite_listing_has_its_own_tag_answers_304_and_is_built_once_per_change(cfg, monkeypatch):
    _, client = _client(cfg)
    rid = client.post("/api/requests", json={"title": "Slow app", "body": "menus lag"}).json()["id"]
    plain = client.get("/api/requests").headers["etag"]
    built, cut = [], inbox.lite
    monkeypatch.setattr(inbox, "lite", lambda r: built.append(r["id"]) or cut(r))
    first = client.get("/api/requests?lite=1")
    tag = first.headers["etag"]
    assert first.status_code == 200 and tag != plain and built == [rid], "a lite list is a different answer"
    assert first.headers["content-type"].startswith("application/json") and first.json()[0]["id"] == rid
    unchanged = client.get("/api/requests?lite=1", headers={"if-none-match": tag})
    assert unchanged.status_code == 304 and unchanged.content == b"" and unchanged.headers["etag"] == tag
    again = client.get("/api/requests?lite=1")                          # a caller without the tag: from memory
    assert again.content == first.content and again.headers["etag"] == tag and built == [rid]
    assert client.get("/api/requests?lite=1&status=done").json() == []  # the filters still apply
    client.post(f"/api/requests/{rid}/messages", json={"author": "agent", "text": "found it"})
    changed = client.get("/api/requests?lite=1", headers={"if-none-match": tag})
    assert changed.status_code == 200 and changed.headers["etag"] != tag and built == [rid, rid]


def test_the_store_drops_fields_in_sqlite_or_else_after_decoding(tmp_path, monkeypatch):
    store = Store(tmp_path)
    try:
        doc = {"id": "a", "body": "imported\udc9d", "created": 1.5, "messages": [{"text": "m"}], "metrics": {"turns": 1}}
        store.put("request", "a", doc)
        want = [{"id": "a", "body": "imported\udc9d", "created": 1.5}]
        assert store.all("request", without=inbox.LITE_DROPPED) == want
        take = store._take_reader

        def without_json_functions():
            db = take()
            db.create_function("json_remove", -1, lambda *args: 1 / 0)    # as if this SQLite had no JSON functions
            return db
        monkeypatch.setattr(store, "_take_reader", without_json_functions)
        assert store.all("request", without=inbox.LITE_DROPPED) == want
        assert store.all("request") == [doc]
    finally:
        store.db.close()
