"""Stream stability (docs/stream-stability.md): the operator's DOA2 view went black at random points on 2026-10-13.

Covers the worker encoder supervisor, black-frame suppression, server stall logging/health, the swap hygiene
(explicit intent, no automated swaps or launches on the operator's live game, no hanging swap) and job origins.
Never starts a game, an emulator or ffmpeg.
"""
from pathlib import Path
import queue
import shutil
import subprocess
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from gbox import adapters, live_stream, operator_guard, server, tools
from gbox.config import Config

JPEG = b"\xff\xd8frame\xff\xd9"


# --- worker: encoder supervisor -------------------------------------------------------------------------------

class FakeOut:
    def __init__(self):
        self.q = queue.Queue()

    def read1(self, n):
        return self.q.get(timeout=5)


class FakeProc:
    def __init__(self):
        self.stdout, self.code, self.killed = FakeOut(), None, False

    def poll(self):
        return self.code

    def emit(self, data=JPEG):
        self.stdout.q.put(data)

    def end(self, code=1):
        self.code = code
        self.stdout.q.put(b"")


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def make_stream(clock, procs, killed):
    def popen(argv):
        assert argv[0] == "ffmpeg" and "image2pipe" in argv
        procs.append(FakeProc())
        return procs[-1]

    def kill(proc):
        if proc is not None:
            killed.append(proc)
            proc.end(-9)
    return adapters.MjpegStream(":91", size=(960, 720), label="w-s", popen=popen, kill=kill, clock=clock,
                                supervise=False)


def wait_seq(stream, seq):
    deadline = time.monotonic() + 5
    while stream.seq < seq and time.monotonic() < deadline:
        time.sleep(0.01)
    assert stream.seq >= seq


def test_dead_encoder_restarts_with_backoff_and_keeps_the_last_frame():
    clock, procs, killed, events = Clock(), [], [], []
    s = make_stream(clock, procs, killed)
    s.on_event = events.append
    procs[0].emit(); wait_seq(s, 1)
    procs[0].end(1)                                  # ffmpeg died (OOM kill, X error): the emulator is untouched
    clock.t += 1
    assert s.check() == "scheduled" and s.latest == JPEG
    assert s.check() is None                         # backoff 0.5 s not elapsed yet
    clock.t += 0.6
    assert s.check() == "restarted" and len(procs) == 2 and s.restarts == 1
    procs[1].emit(b"\xff\xd8new\xff\xd9"); wait_seq(s, 2)
    assert s.latest == b"\xff\xd8new\xff\xd9"
    assert [e["kind"] for e in events] == ["encoder_exit", "encoder_restart"]
    assert all(e["stream"] == "w-s" and e["at"] for e in events)
    s.close()


def test_hung_encoder_is_killed_and_restarted_but_slow_frames_are_only_logged():
    clock, procs, killed, events = Clock(), [], [], []
    s = make_stream(clock, procs, killed)
    s.on_event = events.append
    procs[0].emit(); wait_seq(s, 1)
    clock.t += 3                                     # slow (overloaded host): tolerated, logged
    procs[0].emit(); wait_seq(s, 2)
    assert s.check() is None and not killed
    assert events[-1]["kind"] == "slow_frames" and events[-1]["gap_s"] == 3.0
    clock.t += s.stall_s                             # alive but silent: a hung grab
    assert s.check() == "scheduled" and killed == [procs[0]]
    assert events[-1]["kind"] == "encoder_stall"
    clock.t += 1
    assert s.check() == "restarted"
    procs[0].emit()                                  # a replaced encoder's late output is dropped
    time.sleep(0.05)
    assert s.seq == 2
    s.close()


def test_backoff_doubles_while_restarts_produce_nothing_and_close_stops_supervision():
    clock, procs, killed = Clock(), [], []
    s = make_stream(clock, procs, killed)
    delays = []
    for _ in range(4):
        procs[-1].end(1)
        assert s.check() == "scheduled"
        delays.append(round(s._next_spawn - clock.t, 2))
        clock.t = s._next_spawn
        assert s.check() == "restarted"
    assert delays == [0.5, 1.0, 2.0, 4.0]
    s.close()
    clock.t += 100
    assert s.check() is None and s.proc is None


def test_frames_from_an_exited_emulator_are_not_streamed():
    class Ad:
        def __init__(self):
            self.proc = FakeProc()
    ad, clock = Ad(), Clock()
    live = tools._EmulatorLiveness(ad, every=0.5, clock=clock)
    assert live()
    ad.proc.code = 0                                 # RetroArch exited: its Xvfb display is now black
    assert live()                                    # polled at most every 0.5 s
    clock.t += 0.6
    assert not live()


# --- server: stall log + health ----------------------------------------------------------------------------------

def test_note_frame_records_stalls_with_wall_clock_times():
    logs, lv = [], {"sid": "w-s", "ts": 1000.0}
    assert live_stream.note_frame(lv, 1001.0, logs.append) is None
    stall = live_stream.note_frame(lv, 1004.5, logs.append)
    assert stall["seconds"] == 4.5 and stall["start"] and stall["end"]
    assert "w-s no new frame for 4.5 s" in logs[0]
    h = live_stream.health(lv | {"seq": 9}, "running", now=1006.0)
    assert h["age_s"] == 6.0 and h["stalls"] == [stall] and h["state"] == "running"


@pytest.fixture
def app(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    a = server.create_app(cfg)
    a.cfg = cfg
    return a


def client(app, actor=None, **headers):
    h = {"Authorization": "Bearer " + app.cfg.token(), **headers}
    if actor:
        h["x-gbox-actor"] = actor
    return TestClient(app, headers=h)


def test_stream_upload_event_and_health_endpoints(app):
    store = app.state.store
    store.put("session", "w-s", {"session_id": "w-s", "state": "running", "game_id": "g"})
    with client(app) as c:
        body = len(JPEG).to_bytes(4, "big") + JPEG + b"\0\0\0\0"
        assert c.post("/api/sessions/w-s/stream", content=body).json() == {"frames": 1}
        r = c.post("/api/sessions/w-s/stream/event", json={"kind": "encoder_stall", "at": "2026-10-13T04:52:11-0500",
                                                            "silent_s": 8.4, "bogus": "x"})
        assert r.status_code == 200 and "bogus" not in r.json()
        h = c.get("/api/sessions/w-s/stream/health").json()
    assert h["state"] == "running" and h["seq"] == 1 and h["age_s"] is not None and h["uploads"] == 1
    assert h["events"][0]["kind"] == "encoder_stall" and h["events"][0]["silent_s"] == 8.4


# --- swap hygiene --------------------------------------------------------------------------------------------------

def enclosed(fn, name):
    return dict(zip(fn.__code__.co_freevars, fn.__closure__))[name]


def route(app, path, method="POST"):
    return next(r for r in app.routes if getattr(r, "path", "") == path and method in getattr(r, "methods", ()))


@pytest.fixture
def swap_app(app, monkeypatch):
    store = app.state.store
    store.upsert_catalog([{"game_id": "g", "title": "Dead or Alive 2", "platform": "dreamcast", "profile_id": "g",
                           "source_paths": [], "format": "gdi"}])
    store.put("worker", "spark", {"id": "spark", "name": "lilspark", "os": "linux", "last_seen": time.time(),
                                  "tools": ["launch_game", "get_frame"]})
    store.put("session", "spark-op", {"session_id": "spark-op", "game_id": "g", "title": "Dead or Alive 2",
                                      "state": "running", "mod": "amy"})
    swap_job = enclosed(route(app, "/api/sessions/{sid}/swap").endpoint, "swap_job").cell_contents
    session_swap = enclosed(swap_job, "session_swap").cell_contents
    run_cell = enclosed(session_swap, "_run_job")
    original_run = run_cell.cell_contents
    calls = []

    def run(tool, inp, *a, **k):
        calls.append((tool, inp, k))
        if tool == "launch_game":
            store.put("session", "spark-new", {"session_id": "spark-new", "game_id": "g", "state": "running"})
            return {"session_id": "spark-new"}
        if tool == "state_transfer":
            return {"result": {"artifact": "a" * 64, "load_requested": True}}
        return {"mean_luma": 30}
    run_cell.cell_contents = run
    monkeypatch.setattr(server.time, "sleep", lambda _: None)
    return app, store, calls, original_run


def finish(store, jid):
    deadline = time.monotonic() + 10
    while store.get("job", jid)["state"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.01)
    return store.get("job", jid)


def test_swap_that_drops_the_moment_needs_an_explicit_intent(swap_app):
    app, store, calls, _ = swap_app
    with client(app) as c:
        bare = c.post("/api/sessions/spark-op/swap", json={"mod": "", "to": "", "keep_state": False})
        assert bare.status_code == 422 and "intent" in bare.json()["detail"]
        assert not store.all("job") and not calls      # the exact request seen on 2026-10-13 is refused
        ok = c.post("/api/sessions/spark-op/swap", json={"mod": "", "keep_state": False, "intent": "hard_reset"},
                    headers={"x-gbox-client": "desktop-webview"})
    assert ok.status_code == 200
    job = finish(store, ok.json()["id"])
    assert job["state"] == "succeeded" and job["actor"] == "operator"
    assert job["origin"]["intent"] == "hard_reset" and job["origin"]["client"] == "desktop-webview"
    launch = next(k for t, _, k in calls if t == "launch_game")
    assert launch["origin"] == {"via": "session_swap", "parent_job": job["id"]}
    assert launch["queue_wait"] == 180.0


def test_default_swap_keeps_the_moment(swap_app):
    app, store, calls, _ = swap_app
    with client(app) as c:
        r = c.post("/api/sessions/spark-op/swap", json={"mod": "amy"})
    finish(store, r.json()["id"])
    tools_called = [t for t, _, _ in calls]
    assert tools_called.index("state_transfer") < tools_called.index("launch_game")   # saved before the restart


@pytest.mark.parametrize("actor", ["mcp", "hermes", "agent"])
def test_background_agents_never_swap_the_operators_live_game(swap_app, actor):
    app, store, calls, _ = swap_app
    with client(app, actor) as c:
        r = c.post("/api/sessions/spark-op/swap", json={"mod": "amy"})
        on_its_pc = c.post("/api/games/g/launch", params={"mod": "amy", "node": "lilspark"})
        explicit = c.post("/api/games/g/launch", params={"mod": "amy", "node": "auto", "swap": "true"})
        auto = c.post("/api/games/g/launch", params={"mod": "amy", "node": "auto"}).json()
    assert r.status_code == 409 and "operator's live session" in r.json()["detail"]
    assert on_its_pc.status_code == 409 and explicit.status_code == 409   # launch -> swap: refused too
    # node=auto is a new launch, never a swap; the only PC is the operator's, so the automated launch is refused
    assert auto["tool"] == "launch_game" and auto["state"] == "rejected"
    assert not calls and not [j for j in store.all("job") if j["tool"] == "session_swap"]


@pytest.mark.parametrize("actor", ["mcp", "hermes", "agent"])
def test_background_agents_never_reset_the_operators_live_game(swap_app, actor):
    """POST /api/sessions/{sid}/reset relaunches the game like a swap: the same rule for background agents."""
    app, store, calls, _ = swap_app
    with client(app, actor) as c:
        r = c.post("/api/sessions/spark-op/reset", json={"mode": "restart"})
    assert r.status_code == 409 and "operator's live session" in r.json()["detail"]
    assert not calls and not [j for j in store.all("job") if j["tool"] == "session_reset"]


def test_play_with_a_mod_swaps_only_on_the_requested_pc_and_keeps_the_moment(swap_app):
    """Coordinator lead: launch?mod= with node=auto silently swapped a game running on another machine."""
    app, store, calls, _ = swap_app
    store.put("worker", "pc", {"id": "pc", "name": "JAYPC", "os": "windows", "last_seen": time.time(),
                               "tools": ["launch_game"]})
    with client(app) as c:
        auto = c.post("/api/games/g/launch", params={"mod": "amy", "node": "auto"}).json()
        here = c.post("/api/games/g/launch", params={"mod": "amy", "node": "JAYPC"}).json()
    assert auto["tool"] == "launch_game" and here["tool"] == "launch_game"   # DOA2 on the Spark untouched
    assert not [j for j in store.all("job") if j["tool"] == "session_swap"] and not calls
    with client(app) as c:
        swap = c.post("/api/games/g/launch", params={"mod": "amy", "node": "lilspark"}).json()
    job = finish(store, swap["id"])
    assert job["tool"] == "session_swap" and job["input"]["keep_state"] is True
    tools_called = [t for t, _, _ in calls]
    assert tools_called.index("state_transfer") < tools_called.index("launch_game")


def test_at_launch_naming_another_pc_never_swaps_the_spark_game(swap_app):
    app, store, calls, _ = swap_app
    store.put("worker", "pc", {"id": "pc", "name": "JAYPC", "os": "windows", "last_seen": time.time(),
                               "tools": ["launch_game"]})
    with client(app) as c:
        r = c.post("/api/jobs", json={"tool": "@launch", "input": {"game_id": "g", "mod": "amy", "node": "JAYPC"}}).json()
    assert r["tool"] == "launch_game" and r["require_worker"] == "pc"
    assert not [j for j in store.all("job") if j["tool"] == "session_swap"]


def test_worker_tool_inside_an_agent_job_cannot_swap_the_operators_game(swap_app):
    """characters op=use from a Hermes job calls @launch back as the worker: it inherits the job's agent identity."""
    app, store, calls, _ = swap_app
    store.put("job", "hermesjob", {"id": "hermesjob", "tool": "characters", "agent_use": True, "actor": "mcp",
                                   "state": "running"})
    store.put("job", "chatjob", {"id": "chatjob", "tool": "characters", "agent_use": True, "actor": "gbox-agent",
                                 "state": "running"})
    body = {"tool": "@launch", "input": {"game_id": "g", "mod": "amy", "node": "auto"}}
    with client(app, "worker:lilspark", **{"x-gbox-parent-job": "hermesjob"}) as c:
        r = c.post("/api/jobs", json=body)
    assert r.status_code == 409 and "operator's live session" in r.json()["detail"]
    with client(app, "worker:lilspark", **{"x-gbox-parent-job": "chatjob"}) as c:   # the chat speaks for the operator
        r = c.post("/api/jobs", json=body)
    assert r.status_code == 200 and finish(store, r.json()["id"])["origin"]["parent_job"] == "chatjob"


def test_agents_may_swap_their_own_test_session_and_the_chat_agent_acts_for_the_operator(swap_app):
    app, store, calls, _ = swap_app
    store.put("session", "spark-test", {"session_id": "spark-test", "game_id": "g", "state": "running"})
    store.put("slabel", "spark-test", {"session_id": "spark-test", "owner": "agent"})
    with client(app, "mcp") as c:
        r = c.post("/api/sessions/spark-test/swap", json={"mod": "amy"})
    assert r.status_code == 200 and finish(store, r.json()["id"])["state"] == "succeeded"
    with client(app, "gbox-agent") as c:                     # "swap me to Amy" in the in-app chat
        r = c.post("/api/sessions/spark-op/swap", json={"mod": "amy"})
    assert r.status_code == 200 and finish(store, r.json()["id"])["actor"] == "gbox-agent"


def test_a_child_the_worker_never_picks_up_fails_fast_without_touching_the_game(swap_app):
    app, store, _, original_run = swap_app
    with pytest.raises(HTTPException) as caught:
        original_run("get_frame", {"session_id": "spark-op"}, "operator", worker="spark", wait=60, queue_wait=0.05)
    assert caught.value.status_code == 409 and "did not start get_frame within" in caught.value.detail
    child = next(j for j in store.all("job") if j["tool"] == "get_frame")
    assert child["state"] == "failed" and child["cancel"] is True


# --- launch guard + job origin ------------------------------------------------------------------------------------

GAME = {"game_id": "g", "title": "Dead or Alive 2", "platform": "dreamcast", "source_paths": [], "format": "gdi",
        "profile_id": "g"}


def test_automated_launch_never_lands_on_the_pc_the_operator_plays_on(swap_app):
    app, store, _, _ = swap_app
    body = {"tool": "launch_game", "input": {"game": GAME}, "require_os": "linux"}
    with client(app, "mcp") as c:
        r = c.post("/api/jobs", json=body).json()
    assert r["state"] == "rejected" and "operator is playing Dead or Alive 2 on lilspark" in r["error"]
    store.put("worker", "spark2", {"id": "spark2", "name": "spark2", "os": "linux", "last_seen": time.time(),
                                   "tools": ["launch_game"]})
    with client(app, "mcp") as c:
        r = c.post("/api/jobs", json=body).json()
    assert r["state"] == "queued" and r["require_worker"] == "spark2"   # pinned off the operator's PC
    with client(app, "hermes") as c:
        r = c.post("/api/jobs", json=body | {"require_worker": "spark"}).json()
    assert r["state"] == "rejected"
    with client(app) as c:                                              # the operator's own launch is theirs to make
        r = c.post("/api/jobs", json=body | {"require_worker": "spark"}).json()
    assert r["state"] == "queued" and r["error"] is None


def test_agent_test_sessions_do_not_block_automated_launches(swap_app):
    app, store, _, _ = swap_app
    store.put("session", "spark-op", {"session_id": "spark-op", "game_id": "g", "state": "ended"})
    store.put("session", "spark-t", {"session_id": "spark-t", "game_id": "g", "state": "running"})
    store.put("slabel", "spark-t", {"session_id": "spark-t", "owner": "agent"})
    with client(app, "mcp") as c:
        r = c.post("/api/jobs", json={"tool": "launch_game", "input": {"game": GAME}, "require_worker": "spark"}).json()
    assert r["state"] == "queued" and r["require_worker"] == "spark"


@pytest.mark.parametrize("actor", [None, "gbox-agent", "mcp"])
def test_watched_bot_session_blocks_launches_for_every_actor(swap_app, actor):
    app, store, _, _ = swap_app
    store.put("slabel", "spark-op", {"owner": "agent"})
    operator_guard.report_watch(store, "pip-viewer", "spark-op")
    with client(app, actor) as c:
        result = c.post("/api/jobs", json={"tool": "launch_game", "input": {"game": GAME},
                                         "require_worker": "spark"}).json()
    assert result["state"] == "rejected" and "PiP" in result["error"]


def test_watch_lease_is_per_viewer_and_expires(swap_app):
    _, store, _, _ = swap_app
    operator_guard.report_watch(store, "first", "spark-op", now=100)
    operator_guard.report_watch(store, "second", "spark-op", now=110)
    operator_guard.report_watch(store, "first", None, now=111)
    assert operator_guard.watched_sessions(store, "spark", now=112)
    assert not operator_guard.watched_sessions(store, "other", now=112)
    assert not operator_guard.watched_sessions(store, "spark", now=291)


def test_queued_launch_is_held_if_viewing_starts_before_claim(swap_app):
    app, store, _, _ = swap_app
    with client(app) as c:
        job = c.post("/api/jobs", json={"tool": "launch_game", "input": {"game": GAME},
                                      "require_worker": "spark"}).json()
        assert job["state"] == "queued"
        operator_guard.report_watch(store, "pip", "spark-op")
        response = c.post("/api/workers/spark/claim")
    assert response.status_code == 204
    assert "PiP" in store.get("job", job["id"])["admission_wait"]["reason"]


def test_connected_mjpeg_view_protects_bot_until_stream_closes(swap_app, monkeypatch):
    import asyncio
    app, store, _, _ = swap_app
    store.put("slabel", "spark-op", {"owner": "agent"})
    async def frames(*a, **kw):
        yield JPEG
    monkeypatch.setattr(live_stream, "async_mjpeg_parts", frames)
    response = route(app, "/api/sessions/{sid}/mjpeg", "GET").endpoint("spark-op", actor="operator")
    assert operator_guard.watched_sessions(store, "spark")

    async def consume():
        return [part async for part in response.body_iterator]

    assert asyncio.run(consume()) == [JPEG]
    assert not operator_guard.watched_sessions(store, "spark")


def test_jobs_record_actor_and_client_origin(swap_app):
    app, store, _, _ = swap_app
    with client(app, None, **{"x-gbox-client": "web", "user-agent": "Mozilla/5.0 Electron/31"}) as c:
        j = c.post("/api/jobs", json={"tool": "get_frame", "input": {"session_id": "spark-op"}}).json()
    rec = store.get("job", j["id"])
    assert rec["actor"] == "operator" and rec["origin"]["client"] == "web" and "Electron" in rec["origin"]["user_agent"]


def test_sessions_api_marks_agent_owned_rows(swap_app):
    app, store, _, _ = swap_app
    store.put("slabel", "spark-op", {"session_id": "spark-op", "owner": "agent"})
    with client(app) as c:
        rows = {r["session_id"]: r for r in c.get("/api/sessions?include_ended=false").json()}
    assert rows["spark-op"]["agent_owned"] is True


# --- operator guard helpers ----------------------------------------------------------------------------------------

def test_operator_sessions_skip_agent_owned_and_kept_sessions():
    sessions = [{"session_id": "a-1", "state": "running"}, {"session_id": "a-2", "state": "running"},
                {"session_id": "a-3", "state": "ended"}, {"session_id": "b-4", "state": "running"}]
    labels = {"a-2": {"owner": "agent"}}
    got = operator_guard.operator_sessions(sessions, labels.get, lambda jid: None, ["a"])
    assert [s["session_id"] for s in got] == ["a-1"]
    assert operator_guard.operator_sessions(sessions, labels.get, lambda jid: None, ["a"], keep="a-1") == []


def test_sandbox_pids_cover_bwrap_trees_only():
    table = {1: (0, "systemd"), 10: (1, "bwrap --bind /home/u/.hermes/cache/scratch/r1362 /work python agent.py"),
             11: (10, "python agent.py"), 12: (11, "dolphin-emu -b game.iso"), 13: (12, "dolphin-emu helper"),
             20: (1, "bwrap --bind /tmp/other /work sh"), 21: (20, "sh"), 30: (1, "retroarch -L flycast")}
    assert operator_guard.sandbox_pids(table) == [10, 11, 12, 13]


def test_throttle_agent_sandboxes_reads_proc_and_renices(tmp_path):
    def proc(pid, ppid, cmd):
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "stat").write_text(f"{pid} (x y) S {ppid} 0 0")
        (d / "cmdline").write_bytes(cmd.replace(" ", "\0").encode())
    proc(10, 1, "bwrap --bind /h/.hermes/cache/scratch/r1 /w x")
    proc(12, 10, "dolphin-emu")
    proc(30, 1, "retroarch")
    niced, ioniced = [], []
    out = operator_guard.throttle_agent_sandboxes(tmp_path, setprio=lambda pid, n: niced.append((pid, n)),
                                                  ionice=ioniced.append)
    assert sorted(niced) == [(10, 19), (12, 19)] and sorted(ioniced) == [10, 12]
    assert sorted(out["throttled"]) == [10, 12]


NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node is not installed")
def test_client_watchdog_cjs():
    """Client side: last good frame, badge, reconnect, ended sessions, mini player, two-step hard reset."""
    r = subprocess.run([NODE, "--test", str(Path(__file__).with_name("test_stream_watchdog.cjs"))],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]


def test_spark_operator_sessions_use_linux_workers_and_ownership():
    workers = [{"id": "spark", "os": "linux", "online": True}, {"id": "pc", "os": "windows", "online": True}]
    sessions = [{"session_id": "spark-1", "state": "running", "title": "DOA2"},
                {"session_id": "spark-2", "state": "running", "agent_owned": True},
                {"session_id": "pc-3", "state": "running"}]
    assert [s["session_id"] for s in operator_guard.spark_operator_sessions(sessions, workers)] == ["spark-1"]


def test_a_still_never_replaces_a_fresh_stream_frame(app):
    """A still lands seconds after capture; while the stream is live it must not flash an older picture."""
    store = app.state.store
    store.put("session", "w-s", {"session_id": "w-s", "state": "running", "game_id": "g"})
    with client(app) as c:
        body = len(JPEG).to_bytes(4, "big") + JPEG + b"\0\0\0\0"
        assert c.post("/api/sessions/w-s/stream", content=body).json() == {"frames": 1}
        r = c.post("/api/sessions/w-s/frame", content=b"\xff\xd8older\xff\xd9").json()
        assert r["ignored"] and r["seq"] == 1
        assert c.get("/api/sessions/w-s/frame.jpg").content == JPEG
        assert c.post("/api/sessions/w-t/frame", content=b"\xff\xd8still\xff\xd9").json() == {"seq": 1}
