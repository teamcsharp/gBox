"""Rebuild & relaunch a PC from any gBox instance (operator 2026-10-26).

POST /api/workers/{name}/rebuild queues rebuild_node on that worker behind the save/stop of its agent sessions, refuses
while the operator plays a non-bot game there unless forced, and the job's console (several progress lines per report)
is served by GET /api/jobs/{jid}/console with a running line count for incremental polling.
"""
import time

from fastapi.testclient import TestClient

from gbox.config import Config
from gbox.server import CONSOLE_KEEP, create_app


def _app(tmp_path, granted=("read", "execute", "stage", "network", "install")):
    cfg = Config(data_dir=tmp_path / "data", granted_permissions=list(granted))
    app = create_app(cfg)
    return cfg, app, app.state.store


def _worker(store, wid="w1", name="JAYBUILT", os_="windows", tools=("launch_game", "session_op", "rebuild_node"),
            online=True):
    store.put("worker", wid, {"id": wid, "name": name, "os": os_, "tools": list(tools), "unavailable": {},
                              "last_seen": time.time() if online else time.time() - 3600})


def _session(store, sid, *, title="Dead or Alive 2", agent=False):
    store.put("session", sid, {"session_id": sid, "game_id": "g1", "title": title, "state": "running",
                               "started": time.time()})
    if agent:
        store.put("slabel", sid, {"owner": "agent"})


def _client(app, cfg, actor=None):
    headers = {"Authorization": f"Bearer {cfg.token()}"}
    if actor:
        headers["x-gbox-actor"] = actor
    return TestClient(app, headers=headers)


def _jobs(store, tool):
    return [j for j in store.jobs() if j["tool"] == tool]


def test_rebuild_queues_the_tool_on_that_worker(tmp_path):
    cfg, app, store = _app(tmp_path)
    _worker(store)
    with _client(app, cfg) as client:
        r = client.post("/api/workers/JAYBUILT/rebuild", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["worker"] == {"id": "w1", "name": "JAYBUILT", "os": "windows"} and body["stopped"] == []
    job = store.get("job", body["job_id"])
    assert job["tool"] == "rebuild_node" and job["state"] == "queued" and job["require_worker"] == "w1"
    assert job["input"] == {"force": False, "restart": True, "drain_s": 90.0, "delay_s": 6.0, "stop_jobs": []}
    assert not job["agent_use"]
    assert _jobs(store, "session_op") == []


def test_rebuild_refuses_while_the_operator_plays_unless_forced(tmp_path):
    cfg, app, store = _app(tmp_path)
    _worker(store)
    _session(store, "w1-launch1", title="Soul Calibur II")
    with _client(app, cfg) as client:
        r = client.post("/api/workers/JAYBUILT/rebuild", json={})
        assert r.status_code == 409, r.text
        assert "Soul Calibur II" in r.json()["detail"] and "force" in r.json()["detail"]
        assert _jobs(store, "rebuild_node") == [] and _jobs(store, "session_op") == []
        r = client.post("/api/workers/JAYBUILT/rebuild", json={"force": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["force"] is True and [s["session_id"] for s in body["stopped"]] == ["w1-launch1"]
    assert body["stopped"][0]["operator"] is True and body["stopped"][0]["title"] == "Soul Calibur II"
    stop = store.get("job", body["stopped"][0]["job_id"])
    assert stop["tool"] == "session_op" and stop["require_worker"] == "w1" and stop["state"] == "queued"
    assert stop["input"] == {"session_id": "w1-launch1", "op": "stop_game", "args": {"moment": True}}
    rebuild = store.get("job", body["job_id"])
    assert rebuild["input"]["force"] is True and rebuild["input"]["stop_jobs"] == [stop["id"]]
    # the stop was queued before the rebuild: the worker claims stops first anyway
    assert stop["created"] <= rebuild["created"]


def test_agent_sessions_are_saved_and_closed_without_force(tmp_path):
    cfg, app, store = _app(tmp_path)
    _worker(store)
    _session(store, "w1-bot1", title="Resident Evil 4", agent=True)
    _worker(store, wid="w2", name="i9-NUC")
    _session(store, "w2-other", title="Elsewhere")           # another PC's game is not touched
    with _client(app, cfg) as client:
        r = client.post("/api/workers/JAYBUILT/rebuild", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(s["session_id"], s["operator"]) for s in body["stopped"]] == [("w1-bot1", False)]
    stops = _jobs(store, "session_op")
    assert len(stops) == 1 and stops[0]["input"]["session_id"] == "w1-bot1"
    assert store.get("job", body["job_id"])["input"]["stop_jobs"] == [stops[0]["id"]]


def test_agents_unknown_and_offline_workers_are_refused(tmp_path):
    cfg, app, store = _app(tmp_path)
    _worker(store)
    _worker(store, wid="w9", name="SLEEPY", online=False)
    with _client(app, cfg, actor="hermes") as agent:
        assert agent.post("/api/workers/JAYBUILT/rebuild", json={}).status_code == 403
    with _client(app, cfg) as client:
        assert client.post("/api/workers/NOPE/rebuild", json={}).status_code == 404
        r = client.post("/api/workers/SLEEPY/rebuild", json={})
        assert r.status_code == 409 and "offline" in r.json()["detail"]
        assert client.post("/api/workers/w1/rebuild", json={}).status_code == 200    # by id as well
    assert _jobs(store, "rebuild_node")[0]["require_worker"] == "w1"


def test_a_worker_without_the_tool_or_the_permission_is_a_clear_409(tmp_path):
    cfg, app, store = _app(tmp_path)
    _worker(store, tools=("launch_game", "session_op"))
    with _client(app, cfg) as client:
        r = client.post("/api/workers/JAYBUILT/rebuild", json={})
    assert r.status_code == 409 and "restart that worker once" in r.json()["detail"], r.text
    cfg, app, store = _app(tmp_path / "noperm", granted=("read", "execute"))
    _worker(store)
    with _client(app, cfg) as client:
        r = client.post("/api/workers/JAYBUILT/rebuild", json={})
    assert r.status_code == 409 and "permission" in r.json()["detail"], r.text


def _running(store, tool="rebuild_node", wid="w1"):
    jid = f"job-{tool}"
    store.put("job", jid, {"id": jid, "tool": tool, "input": {}, "state": "running", "worker_id": wid,
                           "require_worker": wid, "created": time.time(), "started": time.time()})
    return jid


def test_console_tail_keeps_the_last_lines_and_serves_only_new_ones(tmp_path):
    cfg, app, store = _app(tmp_path)
    _worker(store)
    jid = _running(store)
    with _client(app, cfg) as client:
        r = client.post(f"/api/jobs/{jid}/progress", json={"pct": 10, "msg": "== 1/5 Code ==\n$ git pull\n[ok]"})
        assert r.json() == {"ok": True, "cancel": False}
        c = client.get(f"/api/jobs/{jid}/console").json()
        assert c["lines"] == ["== 1/5 Code ==", "$ git pull", "[ok]"] and c["seq"] == 3 and c["pct"] == 10
        assert c["state"] == "running" and c["worker"] == {"id": "w1", "name": "JAYBUILT", "os": "windows"}
        job = store.get("job", jid)
        assert job["progress"]["msg"] == "[ok]" and job["progress_log"] == ["== 1/5 Code ==", "$ git pull", "[ok]"]
        for n in range(250):
            client.post(f"/api/jobs/{jid}/progress", json={"pct": 20 + n / 10, "msg": f"line {n}"})
        c = client.get(f"/api/jobs/{jid}/console").json()
        assert len(c["lines"]) == CONSOLE_KEEP and c["seq"] == 253 and c["lines"][-1] == "line 249"
        assert c["lines"][0] == f"line {250 - CONSOLE_KEEP}"
        assert len(store.get("job", jid)["progress_log"]) == 50
        assert client.get(f"/api/jobs/{jid}/console?after=250").json()["lines"] == ["line 247", "line 248", "line 249"]
        assert client.get(f"/api/jobs/{jid}/console?after=253").json()["lines"] == []
        assert client.get(f"/api/jobs/{jid}/console?after=1").json()["lines"][0] == f"line {250 - CONSOLE_KEEP}"


def test_other_tools_keep_one_line_per_report_and_no_console(tmp_path):
    cfg, app, store = _app(tmp_path)
    _worker(store)
    jid = _running(store, tool="launch_game")
    with _client(app, cfg) as client:
        client.post(f"/api/jobs/{jid}/progress", json={"pct": 5, "msg": "two\nlines"})
        c = client.get(f"/api/jobs/{jid}/console").json()
    job = store.get("job", jid)
    assert job["progress"]["msg"] == "two\nlines" and job["progress_log"] == ["two\nlines"]
    assert "console" not in job and c["lines"] == ["two\nlines"] and c["seq"] == 1


def test_console_of_a_finished_job_carries_its_restart_outcome(tmp_path):
    cfg, app, store = _app(tmp_path)
    _worker(store)
    steps = [{"step": "code", "status": "skipped", "detail": "runs from the share"},
             {"step": "restart", "status": "ok", "detail": "desktop app relaunch"}]
    store.put("job", "done", {"id": "done", "tool": "rebuild_node", "input": {}, "state": "succeeded", "worker_id": "w1",
                              "created": 1.0, "started": 2.0, "finished": 3.0, "console": ["Done: ..."], "console_seq": 7,
                              "output": {"node": "JAYBUILT", "os": "windows", "steps": steps, "failed": [],
                                         "restart": "scheduled", "detail": "desktop app relaunch"}})
    with _client(app, cfg) as client:
        c = client.get("/api/jobs/done/console").json()
        assert client.get("/api/jobs/missing/console").status_code == 404
    assert c["state"] == "succeeded" and c["restart"] == "scheduled" and c["steps"] == steps and c["failed"] == []
    assert c["lines"] == ["Done: ..."] and c["seq"] == 7 and c["finished"] == 3.0
