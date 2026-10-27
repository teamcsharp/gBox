"""Stream stalls on the Spark (2026-10-27): json.dumps of a whole answer is one C call that keeps the GIL until it ends.
GET /api/requests (the 47 MB full inbox list) held it 0.3-0.6 s per encode, and every poller rebuilt it after each
inbox change (~5 a minute); the event loop and every MJPEG view stood still meanwhile. Answers are now encoded in
pieces with identical bytes, and the full listing is built once per change like the lite one."""
import math
import threading

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from gbox import thread_json
from gbox.server import create_app
from gbox.thread_json import json_bytes


SAMPLES = [
    [],
    {},
    [1, 2.5, -0.0, 1e300, 10**30, True, None, "x"],
    {"a": [1, {"b": [2, 3]}], "é": "ünïcödé ✓ 🎮", "empty": [], "nested": {"k": [[], {}]}},
    [{"id": i, "messages": [{"text": "line\n\"quoted\" \\  ", "n": i}] * 3} for i in range(50)],
    {1: "int key", "s": "str key"},                 # json.dumps converts non-string keys: one call
    {True: 1, None: 2, 1.5: 3},
    ("a", "tuple"),
    "plain string",
    42,
    None,
    [[1, [2, [3]]], {"x": None}],
]


@pytest.mark.parametrize("content", SAMPLES)
def test_piecewise_bytes_equal_jsonresponse(content):
    assert json_bytes(content) == JSONResponse(content).body


def test_errors_stay_the_same():
    for bad in ([math.nan], {"x": [math.inf]}, [object()], {"x": "\udc9d"}):
        with pytest.raises(Exception) as whole:
            JSONResponse(bad)
        with pytest.raises(type(whole.value)):
            json_bytes(bad)


def test_large_list_is_encoded_in_one_call_per_item(monkeypatch):
    calls = []
    real = thread_json.json.dumps
    rows = [{"id": i, "body": "x" * 100} for i in range(500)]
    expected = JSONResponse(rows).body
    monkeypatch.setattr(thread_json.json, "dumps", lambda v, **kw: calls.append(1) or real(v, **kw))
    assert json_bytes(rows) == expected
    assert len(calls) == 500
    calls.clear()
    json_bytes({"items": rows, "count": 500})
    assert len(calls) == 2 + 500 + 1, "two keys, the list's items, the count"


def test_full_inbox_listing_is_built_once_per_change_with_the_same_bytes(cfg, monkeypatch):
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    for i in range(3):
        client.post("/api/requests", json={"title": f"Report {i}", "body": "é ✓ " * 20})
    store = app.state.store
    real_all = type(store).all
    reads = []

    def counting(self, kind, **kw):
        if kind == "request" and not kw.get("without"):
            reads.append(1)
        return real_all(self, kind, **kw)
    monkeypatch.setattr(type(store), "all", counting)
    first = client.get("/api/requests")
    second = client.get("/api/requests")
    assert first.status_code == second.status_code == 200 and len(reads) == 1, "an unchanged inbox is built once"
    assert first.content == second.content and first.headers["etag"] == second.headers["etag"]
    assert first.headers["content-type"] == "application/json"
    # the bytes FastAPI's JSONResponse would have sent
    from gbox import inbox
    rows = sorted(inbox.organize(real_all(store, "request")), key=lambda r: r["created"], reverse=True)
    assert first.content == JSONResponse(rows).body
    grouped = client.get("/api/requests?group=1")
    assert grouped.status_code == 200 and len(reads) == 2 and grouped.headers["etag"] != first.headers["etag"]
    rid = first.json()[0]["id"]
    client.post(f"/api/requests/{rid}/messages", json={"author": "agent", "text": "found it"})
    changed = client.get("/api/requests")
    assert len(reads) == 3 and changed.headers["etag"] != first.headers["etag"]
    assert changed.json()[0]["messages"][-1]["text"] == "found it"


def test_concurrent_pollers_share_one_build(cfg, monkeypatch):
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    client.post("/api/requests", json={"title": "One", "body": "b"})
    store = app.state.store
    real_all = type(store).all
    reads = []
    monkeypatch.setattr(type(store), "all",
                        lambda self, kind, **kw: (reads.append(kind) if kind == "request" else None) or real_all(self, kind, **kw))
    answers = []
    threads = [threading.Thread(target=lambda: answers.append(client.get("/api/requests").content)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(answers) == 6 and len(set(answers)) == 1 and reads.count("request") == 1
