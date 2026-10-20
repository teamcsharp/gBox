"""#971 stage 2: Capture again keeps the operator's moment. save state -> capture session (test PC first, else beside
the game) -> load state -> capture -> stop -> GLB back; the operator's game is never paused, stopped or relaunched."""
import time

import pytest
from fastapi.testclient import TestClient

from gbox import scene_relay as sr

OP_SID = "opw-job1"
RELAY_ROW = {"status": "relaunch_under_capture", "driver": "vulkan", "attach": "layer", "relay": True,
             "reason": "GL session", "adapter": "retroarch", "core": "flycast"}


def worker(wid, name, **o):
    return {"id": wid, "name": name, "os": "windows", "online": True, "background_testing": True,
            "tools": ["launch_game", "scene_capture", "state_transfer", "session_op"]} | o


def session(adapter="retroarch", **o):
    return {"session_id": OP_SID, "state": "running", "adapter": adapter, "game_id": "pso", "title": "PSO Ver.2",
            "mod": "", "detail": {"scene_capture": RELAY_ROW | {"adapter": adapter}}} | o


class Jobs:
    """Fake control plane: records every job and answers like the workers would."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}

    def __call__(self, tool, inp, worker_id, wait, progress=None):
        self.calls.append((tool, dict(inp), worker_id))
        key = (tool, inp.get("op"), worker_id)
        if key in self.fail or (tool, None, worker_id) in self.fail or (tool, inp.get("op"), None) in self.fail:
            raise RuntimeError(f"{tool} failed: boom")
        if progress:
            progress(50, "working")
        if tool == "state_transfer" and inp["op"] == "snapshot":
            return {"result": {"artifact": "a" * 64}}
        if tool == "state_transfer":
            return {"result": {"load_requested": True, "load_verified": False}}
        if tool == "launch_game":
            return {"session_id": f"{worker_id}-cap"}
        if tool == "scene_capture":
            return {"glb": "b" * 64, "summary": {"draws_exported": 42}, "paused": True}
        return {}


def run(jobs, ws, sess=None, live=(), **kw):
    labels, ended = {}, []
    out = sr.relay(OP_SID, sess or session(), {"game_id": "pso", "title": "PSO Ver.2"}, run_job=jobs,
                   workers=lambda: ws, live_sessions=lambda: list(live), label=lambda s, l: labels.update({s: l}),
                   end_session=ended.append, preferred="JAYBUILTFINALE", sleep=lambda s: None, **kw)
    return out, labels, ended


def test_relay_runs_on_the_test_pc_and_keeps_the_operators_game_running():
    jobs = Jobs()
    out, labels, ended = run(jobs, [worker("opw", "i9-NUC"), worker("jay", "JAYBUILTFINALE")])
    tools = [(t, i.get("op"), w) for t, i, w in jobs.calls]
    assert tools == [("state_transfer", "snapshot", "opw"), ("launch_game", None, "jay"),
                     ("state_transfer", "import", "jay"), ("scene_capture", None, "jay"), ("session_op", "stop_game", "jay")]
    launch = jobs.calls[1][1]
    assert launch["capture_backend"] == "vulkan" and launch["examine"] is True
    assert launch["capture_for"] == OP_SID and launch["keep_session"] == ""
    assert jobs.calls[2][1]["artifact"] == "a" * 64 and jobs.calls[3][1]["session_id"] == "jay-cap"
    assert jobs.calls[4][1]["session_id"] == "jay-cap"                       # only the capture session is stopped
    assert not any(i.get("session_id") == OP_SID for t, i, w in jobs.calls if t in ("session_op", "scene_capture"))
    assert out["glb"] == "b" * 64 and out["paused"] is False and out["resume_on_leave"] is False
    info = out["capture_session"]
    assert (info["worker"], info["where"], info["driver"], info["moment"]) == ("JAYBUILTFINALE", "test PC", "vulkan",
                                                                              "save_state")
    assert out["summary"]["capture_session"] == info and out["summary"]["draws_exported"] == 42
    assert labels["jay-cap"]["owner"] == "agent" and ended == ["jay-cap"]


@pytest.mark.parametrize("test_pc,live", [
    ({"background_testing": False}, ()),                                           # unticked in the Tasks menu
    ({"online": False}, ()),
    ({}, ({"session_id": "jay-other", "state": "running"},)),                       # someone's game is on it
])
def test_relay_falls_back_to_a_hidden_capture_session_beside_the_game(test_pc, live):
    jobs = Jobs()
    out, _, _ = run(jobs, [worker("opw", "i9-NUC"), worker("jay", "JAYBUILTFINALE", **test_pc)], live=live)
    launch = next(i | {"w": w} for t, i, w in jobs.calls if t == "launch_game")
    assert launch["w"] == "opw" and launch["keep_session"] == OP_SID       # the operator's game is not closed
    assert out["capture_session"]["where"] == "this PC"


def test_operator_playing_on_the_test_pc_gets_a_capture_session_beside_the_game():
    ws = [worker("jay", "JAYBUILTFINALE")]
    sess = session(session_id="jay-job1")
    jobs = Jobs()
    out = sr.relay("jay-job1", sess, {"game_id": "pso"}, run_job=jobs, workers=lambda: ws, live_sessions=lambda: [sess],
                   preferred="JAYBUILTFINALE", sleep=lambda s: None)
    assert next(i["keep_session"] for t, i, w in jobs.calls if t == "launch_game") == "jay-job1"
    assert out["capture_session"]["where"] == "this PC"


def test_failed_test_pc_launch_retries_beside_the_game():
    jobs = Jobs(fail={("launch_game", None, "jay")})
    out, _, _ = run(jobs, [worker("opw", "i9-NUC"), worker("jay", "JAYBUILTFINALE")])
    assert [w for t, i, w in jobs.calls if t == "launch_game"] == ["jay", "opw"]
    assert out["capture_session"]["where"] == "this PC"


def test_dolphin_never_runs_beside_the_operators_dolphin():
    jobs = Jobs()
    with pytest.raises(sr.RelayError, match="can't run beside your game"):
        run(jobs, [worker("opw", "i9-NUC"), worker("jay", "JAYBUILTFINALE", background_testing=False)],
            sess=session("dolphin"))
    assert [t for t, i, w in jobs.calls] == ["state_transfer"]               # saved, but nothing was launched


def test_unsaved_moment_captures_nothing():
    jobs = Jobs(fail={("state_transfer", "snapshot", "opw")})
    with pytest.raises(sr.RelayError, match="could not be saved.*keeps running"):
        run(jobs, [worker("opw", "i9-NUC"), worker("jay", "JAYBUILTFINALE")])
    assert [t for t, i, w in jobs.calls] == ["state_transfer"]


@pytest.mark.parametrize("failing,match", [(("state_transfer", "import", None), "could not be loaded"),
                                           (("scene_capture", None, "jay"), "could not capture")])
def test_capture_session_is_always_closed(failing, match):
    jobs = Jobs(fail={failing})
    ended = []
    with pytest.raises(sr.RelayError, match=match):
        sr.relay(OP_SID, session(), {"game_id": "pso"}, run_job=jobs,
                 workers=lambda: [worker("opw", "i9-NUC"), worker("jay", "JAYBUILTFINALE")], live_sessions=lambda: [],
                 end_session=ended.append, preferred="JAYBUILTFINALE", sleep=lambda s: None)
    assert jobs.calls[-1][0] == "session_op" and jobs.calls[-1][1] == {"session_id": "jay-cap", "op": "stop_game",
                                                                       "args": {}}
    assert ended == ["jay-cap"]


def test_unsupported_and_ended_sessions_are_refused_before_any_job():
    jobs = Jobs()
    ws = [worker("opw", "i9-NUC")]
    with pytest.raises(sr.RelayError, match="2D frame only"):
        run(jobs, ws, sess=session(detail={"scene_capture": {"status": "unsupported",
                                                             "reason": "The snes9x core renders in software (2D frame only)."}}))
    with pytest.raises(sr.RelayError, match="ended"):
        run(jobs, ws, sess=session(state="ended"))
    assert jobs.calls == []


def test_wants_relay():
    assert sr.wants_relay(session(), {})
    assert sr.wants_relay({"detail": {"scene_capture": {"status": "supported"}}}, {"relay": True})
    assert not sr.wants_relay({"detail": {"scene_capture": {"status": "supported"}}}, {})
    assert not sr.wants_relay({"detail": {"scene_capture": RELAY_ROW, "capture_session": {"driver": "vulkan"}}},
                              {"relay": True})                               # never a relay of a capture session
    assert not sr.wants_relay({"detail": {"scene_capture": RELAY_ROW | {"relay": False}}}, {})


def test_server_routes_capture_again_to_a_relay_job(tmp_path, monkeypatch):
    from gbox.config import Config
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.put("session", OP_SID, session())
    seen = {}

    def fake_relay(sid, sess, game, **kw):
        seen.update(sid=sid, game=game, preferred=kw["preferred"])
        kw["say"](50, "capturing")
        return {"session_id": sid, "glb": "c" * 64, "summary": {"draws_exported": 3}, "paused": False,
                "resume_on_leave": False, "capture_session": {"worker": "JAYBUILTFINALE"}}
    monkeypatch.setattr(sr, "relay", fake_relay)
    monkeypatch.setattr(store, "catalog_get", lambda gid: {"game_id": gid, "title": "PSO Ver.2"} if gid == "pso" else None)
    with TestClient(app, headers={"Authorization": "Bearer " + cfg.token()}) as client:
        r = client.post("/api/jobs", json={"tool": "scene_capture", "input": {"session_id": OP_SID, "relay": True}})
        assert r.status_code == 200, r.text
        job = r.json()
        assert job["tool"] == "scene_relay"
        again = client.post("/api/jobs", json={"tool": "scene_capture", "input": {"session_id": OP_SID}}).json()
        for _ in range(100):
            j = client.get(f"/api/jobs/{job['id']}").json()
            if j["state"] not in ("queued", "running"):
                break
            time.sleep(0.05)
    assert j["state"] == "succeeded" and j["output"]["glb"] == "c" * 64 and j["output"]["paused"] is False
    assert seen == {"sid": OP_SID, "game": {"game_id": "pso", "title": "PSO Ver.2"}, "preferred": "JAYBUILTFINALE"}
    assert again["tool"] == "scene_relay"                                      # the matrix row alone routes it too
