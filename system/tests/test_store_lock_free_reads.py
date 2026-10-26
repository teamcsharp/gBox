"""GET latency on the Spark (2026-10-26): /api/workers took 6-10 s, /api/sessions 18-49 s, /api/mercmode > 90 s while
/api/health answered in 4 ms. Every store read waited at `with store.lock:` (24% of all thread samples, ~20 threads at
once) behind two unindexed scans of the 214 MB job kind that /api/sessions ran under the lock (mercmode.control,
autoplay_resume.latest_control), and the claim poll rewrote a 120 KB registration every second with an fsync per commit.
Now: reads outside the lock run on pooled read-only connections, those scans use docs_job_session, the heartbeat is
persisted every 5 s unless a decision input changed, workers() is cached for a second, the WAL is checkpointed off the
writer's commit path (gbox/store.py, gbox/server.py)."""
import inspect
import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from gbox import autoplay_resume, mercmode
from gbox.server import create_app
from gbox.store import Store


def test_a_read_outside_the_lock_does_not_wait_for_an_open_write_transaction(tmp_path):
    store = Store(tmp_path)
    try:
        store.put("job", "a", {"id": "a", "state": "queued"})
        held, released = threading.Event(), threading.Event()

        def writer():
            with store.lock:
                store.db.execute("BEGIN IMMEDIATE")
                store.db.execute("INSERT OR REPLACE INTO docs VALUES('job','b','{\"id\":\"b\"}')")
                held.set()
                released.wait(5)
                store.db.commit()
        t = threading.Thread(target=writer)
        t.start()
        assert held.wait(5)
        t0 = time.perf_counter()
        assert store.get("job", "a") == {"id": "a", "state": "queued"}
        assert store.get("job", "b") is None                    # not committed yet: the last committed state
        assert [j["id"] for j in store.all("job")] == ["a"]
        assert time.perf_counter() - t0 < 1.0                   # it did not wait for the writer
        released.set()
        t.join(5)
        assert store.get("job", "b") == {"id": "b"}             # a committed write is seen by the next read
    finally:
        store.db.close()


def test_the_lock_holder_reads_its_own_uncommitted_rows(tmp_path):
    store = Store(tmp_path)
    try:
        with store.lock:                                        # a read-modify-write, as server.py does it
            store.db.execute("BEGIN IMMEDIATE")
            store.db.execute("INSERT INTO docs VALUES('profile','p','{\"x\":1}')")
            assert store.get("profile", "p") == {"x": 1}
            assert [d["x"] for d in store.all("profile")] == [1]
            store.db.rollback()
        assert store.get("profile", "p") is None
    finally:
        store.db.close()


def test_readers_are_read_only_pooled_and_closed_with_the_writer():
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name))
    store.put("job", "a", {"id": "a"})
    assert store.get("job", "a") == {"id": "a"} and len(store._readers) == 1
    with store.reading() as db:
        try:
            db.execute("INSERT INTO docs VALUES('x','y','{}')")
            raise AssertionError("a pooled reader wrote")
        except sqlite3.OperationalError:
            pass
    results = []
    threads = [threading.Thread(target=lambda: results.append(store.get("job", "a"))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert results == [{"id": "a"}] * 8 and 1 <= len(store._readers) <= 16
    store.db.close()                                            # what every test teardown and maintenance CLI does
    assert store.closed and store._readers == []
    tmp.cleanup()                                               # Windows: no connection may still hold the files
    assert not Path(tmp.name).exists()


def test_writer_pragmas_and_wal_checkpoints(tmp_path):
    store = Store(tmp_path)
    try:
        assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store.db.execute("PRAGMA synchronous").fetchone()[0] == 1          # NORMAL: no fsync per commit
        assert store.db.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 4000
        for i in range(200):
            store.put("job", str(i), {"id": str(i), "pad": "x" * 4000})
        assert store.wal_bytes() > 0
        busy, frames, done = store.checkpoint("PASSIVE")
        assert busy == 0 and frames == done > 0
        assert store.checkpoint("TRUNCATE")[0] == 0 and store.wal_bytes() == 0
        store.put("job", "z", {"id": "z"})
        assert store.checkpoint_due()[0] == 0
        assert store.get("job", "z") == {"id": "z"}            # readers follow the reset WAL
        assert store.version("job") == 201 and store.version("session") == 0
    finally:
        store.db.close()


def test_job_session_queries_use_the_index(tmp_path):
    store = Store(tmp_path)
    try:
        store.put("job", "j1", {"id": "j1", "tool": "autoplay", "state": "succeeded", "created": 1,
                                "input": {"session_id": "w-s", "op": "start"}})
        store.put("job", "j2", {"id": "j2", "tool": "session_op", "state": "succeeded", "created": 2, "actor": "you",
                                "input": {"session_id": "w-s", "op": "pause"}})
        statements = []
        store.db.set_trace_callback(statements.append)
        with store.lock:                                        # the lock holder reads on store.db: traceable
            assert autoplay_resume.latest_control(store, "w-s")["id"] == "j1"
        store.db.set_trace_callback(None)
        selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
        assert selects and all(any("docs_job_session" in row[3] for row in store.db.execute("EXPLAIN QUERY PLAN " + s))
                               for s in selects)
        # the two "a manual control wins" scans in mercmode take the same index
        assert inspect.getsource(mercmode).count("INDEXED BY docs_job_session") == 2
        assert store.fields("job", ("id", "tool")) == [{"id": "j1", "tool": "autoplay"}, {"id": "j2", "tool": "session_op"}]
        assert [i for i, _ in store.rows("job")] == ["j1", "j2"]
    finally:
        store.db.close()


def _client(cfg):
    app = create_app(cfg)
    return app.state.store, TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})


def test_workers_decodes_registrations_once_per_second_and_only_the_changed_ones(cfg, monkeypatch):
    store, client = _client(cfg)
    now = time.time()
    for wid in ("a", "b"):
        store.put("worker", wid, {"id": wid, "name": wid, "os": "windows", "tools": [], "unavailable": {}, "last_seen": now})
    reads, decoded = [], []
    original_rows, original_loads = store.rows, json.loads
    monkeypatch.setattr(store, "rows", lambda kind: reads.append(kind) or original_rows(kind))

    class Json:                                                  # server.py's json: count the registrations it decodes
        def __getattr__(self, name):
            return getattr(json, name)

        @staticmethod
        def loads(text, *a, **k):
            decoded.append(text)
            return original_loads(text, *a, **k)
    from gbox import server
    monkeypatch.setattr(server, "json", Json())
    assert {w["id"] for w in client.get("/api/workers").json()} == {"a", "b"}
    client.get("/api/workers")
    assert reads == ["worker"] and len(decoded) == 2             # two polls within a second: one read, two decodes
    store.put("worker", "a", store.get("worker", "a") | {"last_seen": now + 1})
    rows = {w["id"]: w for w in client.get("/api/workers").json()}
    assert rows["a"]["last_seen"] == now + 1 and rows["a"]["online"] and rows["b"]["online"]
    assert reads == ["worker", "worker"] and len(decoded) == 3   # a write in this process: re-read, only "a" decoded


def test_claim_persists_the_heartbeat_only_when_it_matters(cfg):
    store, client = _client(cfg)
    now = time.time()
    store.put("worker", "w", {"id": "w", "name": "PC", "os": "windows", "tools": [], "unavailable": {}, "last_seen": now,
                              "idle_seconds": 10, "active_jobs": 0, "address": "testclient"})

    def claim(idle, active):
        r = client.post("/api/workers/w/claim", json={"idle_seconds": idle, "active_jobs": active})
        assert r.status_code == 204, r.text
        return store.get("worker", "w")
    w = claim(11, 0)
    assert w["last_seen"] == now and w["idle_seconds"] == 10    # idle grew by a second: nothing to write
    assert claim(12, 1)["active_jobs"] == 1                     # a job started on this PC: written at once
    assert claim(13, 1)["idle_seconds"] == 12                   # unchanged again
    assert claim(2, 1)["idle_seconds"] == 2                     # operator input ended the idle spell: written
    store.put("worker", "w", store.get("worker", "w") | {"last_seen": now - 6})
    assert claim(3, 1)["last_seen"] > now                       # 5 s since the stored heartbeat: written
    assert client.get("/api/workers").json()[0]["online"] is True


def test_sessions_without_ended_rows_reads_no_archive(cfg, monkeypatch):
    store, client = _client(cfg)
    now = time.time()
    store.put("worker", "w1", {"id": "w1", "name": "PC", "os": "windows", "tools": [], "unavailable": {}, "last_seen": now})
    store.put("session", "w1-live", {"session_id": "w1-live", "game_id": "g", "title": "G", "state": "running",
                                     "started": now - 60, "worker_id": "w1"})
    for i in range(3):
        store.put("session", f"w1-old{i}", {"session_id": f"w1-old{i}", "game_id": "g", "title": "G", "state": "ended",
                                            "started": now - 900 + i, "ended": now - 800 + i})

    def guard(method):
        def wrapped(kind, *a, **k):
            assert kind != "session", "include_ended=false must not read the session archive"
            return method(kind, *a, **k)
        return wrapped
    monkeypatch.setattr(store, "all", guard(store.all))
    monkeypatch.setattr(store, "recent", guard(store.recent))
    rows = client.get("/api/sessions", params={"include_ended": "false"}).json()
    assert [r["session_id"] for r in rows] == ["w1-live"] and "worker_online" not in rows[0]
    monkeypatch.undo()
    everything = client.get("/api/sessions").json()             # the default still lists the newest ended rows
    assert [r["session_id"] for r in everything] == ["w1-old2", "w1-old1", "w1-old0", "w1-live"]
