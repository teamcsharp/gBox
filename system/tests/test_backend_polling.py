"""Polling must keep API results while skipping irrelevant, expensive history."""
import json
import time

from fastapi.testclient import TestClient
import pytest

from gbox import hermes_tasks
from gbox.server import create_app
from gbox.store import Store


@pytest.mark.parametrize("limit", [1, 2, 100, 0, -1, -2, -100])
@pytest.mark.parametrize("states", [None, ("queued", "running"), ("failed",), ()])
def test_store_job_filter_and_limit_keep_historical_slice_order(tmp_path, limit, states):
    store = Store(tmp_path)
    try:
        for index, state in enumerate(["failed", "running", "succeeded", "queued", "failed", "running"]):
            store.put("job", str(index), {"id": str(index), "state": state, "created": 100 - index})
        # INSERT OR REPLACE moves this document to the end of rowid order, just
        # as before: polling order must not silently become created-time order.
        store.put("job", "0", {"id": "0", "state": "failed", "created": -1})
        old = [j for j in store.all("job") if states is None or j.get("state") in states]
        assert store.jobs(states=states, limit=limit, reverse=True) == old[-limit:][::-1]
        assert store.jobs(states=states, limit=limit) == old[-limit:]
    finally:
        store.db.close()


def _client(cfg, monkeypatch):
    monkeypatch.setattr(hermes_tasks, "list_runs", lambda limit=20: [])
    app = create_app(cfg)
    return app, TestClient(app, headers={"authorization": f"Bearer {cfg.token()}"})


def _refuse_old_documents(monkeypatch):
    original = json.loads
    def loads(body, *args, **kwargs):
        if isinstance(body, str) and '"must_not_decode"' in body:
            raise AssertionError("poll decoded unrelated historic document")
        return original(body, *args, **kwargs)
    monkeypatch.setattr(json, "loads", loads)


def test_job_endpoint_skips_completed_history_before_state_and_limit(cfg, monkeypatch):
    app, client = _client(cfg, monkeypatch)
    store = app.state.store
    store.put("job", "obsolete", {"id": "obsolete", "state": "succeeded", "must_not_decode": True})
    for jid, state in [("active-1", "running"), ("active-2", "queued"), ("latest", "succeeded")]:
        store.put("job", jid, {"id": jid, "state": state, "created": time.time()})
    # Unrelated malformed documents are legal to coexist and must not be read.
    store.db.execute("INSERT INTO docs VALUES('orphan','bad','not JSON')")
    store.db.commit()
    _refuse_old_documents(monkeypatch)
    assert [j["id"] for j in client.get("/api/jobs?state=running,queued&limit=1").json()] == ["active-2"]
    assert [j["id"] for j in client.get("/api/jobs?state=queued,running&limit=0").json()] == ["active-2", "active-1"]
    assert [j["id"] for j in client.get("/api/jobs?state=queued,running&limit=-1").json()] == ["active-2"]
    assert [j["id"] for j in client.get("/api/jobs?limit=1").json()] == ["latest"]
    assert client.get("/api/jobs?state=unknown").status_code == 422


def test_tasks_poll_skips_history_inventory_and_unrelated_inbox_before_limits(cfg, monkeypatch):
    app, client = _client(cfg, monkeypatch)
    store = app.state.store
    now = time.time()
    store.put("worker", "worker", {"id": "worker", "name": "fixture", "last_seen": now, "tools": []})
    store.put("job", "obsolete", {"id": "obsolete", "tool": "scan_library", "state": "failed",
                                  "must_not_decode": True})
    for index in range(12):
        store.put("job", f"recent-{index}", {"id": f"recent-{index}", "tool": "scan_library",
                                             "state": "succeeded", "created": 100 - index})
    store.put("job", "inventory", {"id": "inventory", "tool": "tasks", "state": "succeeded",
                                   "must_not_decode": True})
    for jid, created in [("active-newer", now), ("active-older", now - 1)]:
        store.put("job", jid, {"id": jid, "tool": "scan_library", "state": "running", "created": created,
                               "worker_id": "worker", "progress": {"pct": 31, "msg": jid}})
    store.put("request", "manual", {"id": "manual", "created": now + 999,
                                     "messages": [{"must_not_decode": True}]})
    for index, cid in enumerate([[], {}, False, None, "", 0]):
        store.put("request", f"empty-{index}", {"id": f"empty-{index}", "created": now + 999,
                                               "context": {"resolution_chat_id": cid}, "must_not_decode": True})
    for index in range(23):
        body = {"id": f"auto-{index}", "number": index, "title": str(index), "status": "in_progress",
                "created": index // 2, "context": {"resolution_chat_id": f"chat-{index}"}}
        if index < 2:
            body["must_not_decode"] = True
        store.put("request", body["id"], body)
    all_workers_calls = []
    original = store.all
    def all_docs(kind, **kwargs):
        if kind in ("job", "request"):
            raise AssertionError("task poll requested unbounded history")
        if kind == "worker":
            all_workers_calls.append(kind)
        return original(kind, **kwargs)
    monkeypatch.setattr(store, "all", all_docs)
    _refuse_old_documents(monkeypatch)
    snapshot = client.get("/api/tasks").json()
    assert [j["id"] for j in snapshot["jobs"]] == ["active-newer", "active-older"]
    assert snapshot["jobs"][0]["worker"] == "fixture"
    assert snapshot["jobs"][0]["progress"] == "active-newer"
    assert snapshot["jobs"][0]["pct"] == 31
    assert [j["id"] for j in snapshot["recent"]] == [f"recent-{i}" for i in range(11, 1, -1)]
    # Equal creation times retain the former stable ascending-rowid tie order.
    assert [r["id"] for r in snapshot["resolutions"]] == ["auto-22"] + [f"auto-{i}" for i in
            [20, 21, 18, 19, 16, 17, 14, 15, 12, 13, 10, 11, 8, 9, 6, 7, 4, 5, 2]]
    assert all_workers_calls == ["worker"]


def test_resolution_query_excludes_empty_context_and_keeps_missing_created_order(tmp_path):
    store = Store(tmp_path)
    try:
        cids = [None, "", 0, False, [], {}, "0", "[]", "{}", "chat", [1], {"a": 1}, 42, 0.0, True]
        for index, cid in enumerate(cids):
            store.put("request", str(index), {"id": str(index), "context": {"resolution_chat_id": cid}})
        assert [r["id"] for r in store.resolution_requests()] == [str(i) for i, cid in enumerate(cids) if cid]
    finally:
        store.db.close()


def test_sessions_keep_ended_and_running_history_newest_first_and_live_frame_age(cfg, monkeypatch):
    app, client = _client(cfg, monkeypatch)
    store = app.state.store
    for sid, state in [("ended", "ended"), ("live", "running"), ("old", "ended")]:
        store.put("session", sid, {"session_id": sid, "state": state, "detail": {"pid": 1}, "custom": sid})
    # The endpoint's closure holds the actual live-frame table.
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/sessions")
    closure = dict(zip(endpoint.__code__.co_freevars, (cell.cell_contents for cell in endpoint.__closure__)))
    closure["live"]["live"] = {"ts": 90}
    monkeypatch.setattr("gbox.server.time.time", lambda: 100)
    result = client.get("/api/sessions").json()
    assert [s["session_id"] for s in result] == ["old", "live", "ended"]
    assert [s["last_frame_age"] for s in result] == [None, 10.0, None]
    assert result[0]["detail"] == {"pid": 1} and result[0]["custom"] == "old"


def test_retirement_reuses_same_locked_session_and_worker_alias_snapshot(cfg, monkeypatch):
    app, client = _client(cfg, monkeypatch)
    store = app.state.store
    now = time.time()
    store.put("session", "game", {"session_id": "game", "state": "running"})
    store.put("worker_alias", "old-worker", {"to": "real-worker"})
    store.put("worker", "real-worker", {"id": "real-worker", "name": "fixture", "last_seen": now, "tools": []})
    for index in range(3):
        store.put("job", str(index), {"id": str(index), "state": "queued", "created": now - 7200,
                                     "input": {"session_id": "game"}, "require_worker": "old-worker"})
    gets = []
    original = store.get
    def get(kind, identifier):
        gets.append((kind, identifier))
        return original(kind, identifier)
    monkeypatch.setattr(store, "get", get)
    result = client.get("/api/jobs?state=queued").json()
    assert [j["id"] for j in result] == ["2", "1", "0"]
    assert gets.count(("session", "game")) == 1
    assert gets.count(("worker_alias", "old-worker")) == 1
    assert gets.count(("worker_alias", "real-worker")) == 1


def test_poll_queries_use_kind_and_job_state_indexes(tmp_path):
    store = Store(tmp_path)
    try:
        statements = []
        store.db.set_trace_callback(statements.append)
        store.all("session", reverse=True)
        store.jobs(states=("queued", "running"), limit=1000, reverse=True)
        store.resolution_requests()
        store.db.set_trace_callback(None)
        by_kind, active, resolutions = [store.db.execute("EXPLAIN QUERY PLAN " + sql).fetchall() for sql in statements]
        assert any("docs_kind" in row[3] for row in by_kind)
        assert any("docs_queued_jobs" in row[3] for row in active)
        assert any("docs_resolution_requests_created" in row[3] for row in resolutions)
    finally:
        store.db.close()
