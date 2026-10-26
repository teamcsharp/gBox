"""The periodic stream stutter (operator 2026-10-26: "the app itself has a stutter every 5 seconds ... a slight
stutter with the pine box").

Every game picture passes the control plane's one event loop: the worker's frame upload, each MJPEG view and the
broadcast feeds. FastAPI encoded the JSON answer of every plain `def` endpoint on that loop, so each 5-second poll of
GET /api/workers (1.9 MB: 21 stale worker rows with ~75 KB of source hashes each) held every stream ~90 ms, and each
2-second PiP read of the 660 KB session history ~120 ms. These tests pin the three fixes: answers are encoded in the
threadpool, offline worker rows lose their source hashes, and the desktop-frame upload reads the store off the loop.
Never starts a game, an emulator or ffmpeg.
"""
import asyncio
import threading
import time

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_serializer

from gbox import live_stream, server
from gbox.config import Config
from gbox.thread_json import ThreadJSONRoute, thread_encodable

JPEG = b"\xff\xd8frame\xff\xd9"


def on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


PROBE = {"seen": [], "cost": 0.0}


class Probe(BaseModel):
    """Encoding this records which thread encoded it, and can take as long as a big answer does."""
    x: int = 1

    @field_serializer("x")
    def _encode(self, value):
        PROBE["seen"].append("loop" if on_event_loop() else "thread")
        time.sleep(PROBE["cost"])
        return value


def probe_app(route_class=ThreadJSONRoute) -> FastAPI:
    app = FastAPI()
    app.router.route_class = route_class

    @app.get("/answer")
    def answer():
        return {"probe": Probe(), "n": [1, 2, 3]}

    @app.get("/async")
    async def answer_async():
        return {"probe": Probe()}

    @app.get("/created", status_code=201)
    def created():
        return {"ok": True}

    @app.get("/refused")
    def refused():
        raise HTTPException(409, "not now")

    @app.get("/raw")
    def raw():
        return Response(b"raw", media_type="text/plain")

    class Out(BaseModel):
        n: int

    @app.get("/model", response_model=Out)
    def model():
        return {"n": 3, "dropped": True}

    @app.get("/headers")
    def headers(response: Response):
        response.headers["x-kept"] = "yes"
        return {"ok": True}

    def stamp(response: Response):
        response.headers["x-stamped"] = "yes"

    @app.get("/stamped")
    def stamped(_=Depends(stamp)):
        return {"ok": True}
    return app


def route(app, path, method="GET"):
    return next(r for r in app.routes if getattr(r, "path", "") == path and method in getattr(r, "methods", ()))


# --- answers are encoded in the threadpool -------------------------------------------------------------------------

def test_def_endpoint_answer_is_encoded_in_the_threadpool_with_the_same_bytes():
    PROBE.update(seen=[], cost=0.0)
    with TestClient(probe_app(APIRoute)) as c:
        before = c.get("/answer")
    assert PROBE["seen"] == ["loop"]                    # FastAPI's own path: encoded on the event loop
    PROBE["seen"] = []
    with TestClient(probe_app()) as c:
        after = c.get("/answer")
    assert PROBE["seen"] == ["thread"]
    assert (after.status_code, after.content, after.headers["content-type"]) == \
        (before.status_code, before.content, before.headers["content-type"])
    assert after.json() == {"probe": {"x": 1}, "n": [1, 2, 3]}


def test_routes_fastapi_shapes_itself_keep_fastapi_behaviour():
    app = probe_app()
    assert thread_encodable(route(app, "/answer")) is False          # already wrapped once: never twice
    assert getattr(route(app, "/answer").dependant.call, "gbox_thread_json", False)
    assert route(app, "/answer").endpoint.__name__ == "answer"       # tests and the desktop bridge use .endpoint
    for path in ("/async", "/created", "/model", "/headers", "/stamped"):
        assert not getattr(route(app, path).dependant.call, "gbox_thread_json", False), path
    with TestClient(app) as c:
        assert c.get("/created").status_code == 201
        refused = c.get("/refused")
        assert refused.status_code == 409 and refused.json() == {"detail": "not now"}
        assert c.get("/raw").content == b"raw"
        assert c.get("/model").json() == {"n": 3}
        kept = c.get("/headers")
        assert kept.headers["x-kept"] == "yes" and kept.json() == {"ok": True}
        assert c.get("/stamped").headers["x-stamped"] == "yes"


def frames_while_requesting(app, path, *, cost=0.3):
    """Frame arrival times of the production MJPEG generator (live_stream.async_mjpeg_parts) fed at 100 fps by a
    thread, while `path` is requested through the same event loop and its answer takes `cost` seconds to encode."""
    async def run():
        lv = {"frame": JPEG, "seq": 1, "ts": time.time(), "cond": threading.Condition()}
        stop, arrived = threading.Event(), []

        def publish():
            seq = 1
            while not stop.is_set():
                seq += 1
                with lv["cond"]:
                    lv["frame"], lv["seq"] = JPEG + str(seq).encode(), seq
                    live_stream.notify_frame(lv)
                time.sleep(0.01)

        async def view():
            async for _ in live_stream.async_mjpeg_parts(lv):
                arrived.append(time.perf_counter())

        viewer = asyncio.create_task(view())
        publisher = threading.Thread(target=publish, daemon=True)
        publisher.start()
        await asyncio.sleep(0.2)
        PROBE.update(seen=[], cost=cost)
        start = time.perf_counter()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gbox") as c:
            answer = await c.get(path)
        end = time.perf_counter()
        await asyncio.sleep(0.1)
        stop.set()
        viewer.cancel()
        PROBE["cost"] = 0.0
        window = [t for t in arrived if start - 0.05 <= t <= end + 0.05]
        gaps = [b - a for a, b in zip(window, window[1:])]
        return answer, max(gaps or [end - start])
    return asyncio.run(run())


def test_live_stream_keeps_flowing_while_a_slow_answer_is_encoded():
    stalled, gap = frames_while_requesting(probe_app(APIRoute), "/answer")
    assert stalled.status_code == 200 and gap >= 0.25          # the old path: the encode held every viewer
    answer, gap = frames_while_requesting(probe_app(), "/answer")
    assert answer.json() == {"probe": {"x": 1}, "n": [1, 2, 3]}
    assert gap < 0.15, f"a viewer waited {gap * 1000:.0f} ms for a frame while an answer was encoded"


# --- the control plane --------------------------------------------------------------------------------------------

@pytest.fixture
def app(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    a = server.create_app(cfg)
    a.cfg = cfg
    return a


def client(app):
    return TestClient(app, headers={"Authorization": "Bearer " + app.cfg.token()})


def test_control_plane_routes_encode_answers_off_the_event_loop(app, monkeypatch):
    assert app.router.route_class is ThreadJSONRoute
    for path in ("/api/workers", "/api/sessions", "/api/session_labels", "/api/audit"):
        r = route(app, path)
        assert getattr(r.dependant.call, "gbox_thread_json", False), path
    # the frame ingest keeps its async handler; the MJPEG view's own StreamingResponse passes through untouched
    assert not getattr(route(app, "/api/sessions/{sid}/stream", "POST").dependant.call, "gbox_thread_json", False)

    async def frames(*a, **kw):
        yield JPEG
    monkeypatch.setattr(live_stream, "async_mjpeg_parts", frames)
    view = route(app, "/api/sessions/{sid}/mjpeg").dependant.call("w-s", actor="operator")
    assert isinstance(view, StreamingResponse) and view.media_type == "multipart/x-mixed-replace; boundary=f"

    async def consume():
        return [part async for part in view.body_iterator]
    assert asyncio.run(consume()) == [JPEG]


def test_offline_worker_rows_leave_their_source_hashes_out_of_the_polled_list(app):
    store, now = app.state.store, time.time()
    hashes = {f"gbox/module_{i}.py": f"{i:064x}" for i in range(800)}
    store.put("worker", "live", {"id": "live", "name": "lilspark", "os": "linux", "last_seen": now,
                                 "tools": ["launch_game"], "unavailable": {}, "build_sources": hashes,
                                 "local_builds": [{"name": "b"}]})
    for i in range(21):                                   # stale registrations of a restarted PC
        store.put("worker", f"old{i}", {"id": f"old{i}", "name": "i9-NUC", "os": "windows",
                                        "last_seen": now - 200000 - i, "tools": ["launch_game"], "unavailable": {},
                                        "build_sources": hashes})
    with client(app) as c:
        r = c.get("/api/workers")
    rows = {w["id"]: w for w in r.json()}
    assert rows["live"]["online"] and rows["live"]["build_sources"] == hashes   # live checks (face editor) still work
    assert "local_builds" not in rows["live"]
    for i in range(21):
        w = rows[f"old{i}"]
        assert not w["online"] and "build_sources" not in w
        assert w["tools"] == ["launch_game"] and w["name"] == "i9-NUC" and w["os"] == "windows"
    assert len(r.content) < 120_000, len(r.content)         # was ~1.9 MB with every row's hashes


def test_desktop_frame_upload_reads_the_store_off_the_event_loop(app, monkeypatch):
    store = app.state.store
    store.put("worker", "pc", {"id": "pc", "name": "JAYBUILTFINALE", "os": "windows", "last_seen": time.time(),
                               "tools": [], "unavailable": {}})
    reads, original = [], store.get

    def get(kind, id):
        reads.append((kind, on_event_loop()))
        return original(kind, id)
    monkeypatch.setattr(store, "get", get)
    with client(app) as c:
        ok = c.post("/api/workers/pc/desktop/frame", content=JPEG, headers={"content-type": "image/jpeg"})
        missing = c.post("/api/workers/nobody/desktop/frame", content=JPEG, headers={"content-type": "image/jpeg"})
        bad = c.post("/api/workers/pc/desktop/frame", content=b"not a jpeg")
    assert ok.status_code == 200 and ok.json() == {"ok": True}
    assert missing.status_code == 404 and bad.status_code == 422
    frame_reads = [loop for kind, loop in reads if kind in ("worker", "worker_alias")]
    assert frame_reads and not any(frame_reads), "a store read ran on the loop that carries the game streams"
