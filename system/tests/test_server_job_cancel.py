"""In-server jobs (session_swap) must be cancellable, even after the server restarted under them (#1297)."""
import time

from fastapi.testclient import TestClient

from gbox import job_maintenance
from gbox.config import Config
from gbox.models import Job
from gbox.server import create_app

# The exact job the operator could not cancel: running for 6 h, no worker, cancel flag already set.
STUCK = {"tool": "session_swap", "state": "running", "worker_id": None,
         "input": {"session_id": "89206492e649435c-a5c55d89afc64ce3", "game_id": "4187aeab4d67638c",
                   "mod": "jgr_sa2_amy_rose_04_r6", "to": "", "keep_state": False},
         "progress": {"pct": 60, "msg": "That didn't start: putting your game back", "ts": time.time() - 6 * 3600}}


def _app(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    return cfg, app, app.state.store


def _put(store, **body):
    job = Job(**body)
    store.put("job", job.id, job.model_dump() | {k: v for k, v in body.items() if k not in Job.model_fields})
    return job.id


def test_cancel_finishes_swap_left_running_by_an_earlier_server(tmp_path):
    cfg, app, store = _app(tmp_path)
    jid = _put(store, **STUCK, created=time.time() - 6 * 3600, started=time.time() - 6 * 3600)
    with TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"}) as client:
        r = client.post(f"/api/jobs/{jid}/cancel")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "failed"
        j = client.get(f"/api/jobs/{jid}").json()
    assert j["state"] == "failed" and j["finished"]
    assert j["error"].startswith("cancelled by the operator")
    assert "restarted" in j["error"]


def test_cancel_still_only_flags_worker_jobs(tmp_path):
    cfg, app, store = _app(tmp_path)
    jid = _put(store, tool="launch_game", state="running", worker_id="w1", input={}, started=time.time())
    with TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"}) as client:
        r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.json() == {"id": jid, "state": "running", "cancel_requested": True}
    assert store.get("job", jid)["state"] == "running"


def test_sweep_retires_orphans_but_never_a_live_thread_or_worker_job(tmp_path):
    _, _, store = _app(tmp_path)
    orphan = _put(store, **(STUCK | {"progress": None}))
    live = _put(store, **(STUCK | {"progress": None}))
    worker = _put(store, tool="launch_game", state="running", worker_id="w1", input={})
    frame = _put(store, tool="get_frame", state="running", worker_id=None, input={}, started=time.time())
    flagged = _put(store, **STUCK, cancel=True)
    assert sorted(job_maintenance.retire_orphaned_server_jobs(store, {live})) == sorted([orphan, flagged])
    assert store.get("job", orphan)["error"] == job_maintenance.ORPHAN_REASON
    assert store.get("job", flagged)["error"] == job_maintenance.CANCELLED_REASON
    for jid in (live, worker, frame):
        assert store.get("job", jid)["state"] == "running"
    assert job_maintenance.retire_orphaned_server_jobs(store, {live}) == []


def test_live_swap_stops_while_its_prepare_step_waits(tmp_path):
    cfg, app, store = _app(tmp_path)
    store.upsert_catalog([{"game_id": "g1", "title": "Test game", "platform": "dreamcast", "source_paths": ["t.gdi"],
                           "format": "gdi", "profile_id": "g1", "core": "flycast",
                           "launch": {"kind": "retroarch", "path": "t.gdi"}}])
    store.put("worker", "w1", {"id": "w1", "name": "TESTPC", "os": "windows", "tools": ["prepare_mod", "launch_game"],
                               "unavailable": {}, "last_seen": time.time() + 3600})
    sid = "w1-s1"
    store.put("session", sid, {"id": sid, "game_id": "g1", "state": "running", "mod": ""})
    with TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"}) as client:
        r = client.post(f"/api/sessions/{sid}/swap", json={"mod": "m1", "keep_state": False})
        assert r.status_code == 200, r.text
        swap = r.json()["id"]
        deadline = time.time() + 5
        while time.time() < deadline and not [j for j in store.all("job") if j["tool"] == "prepare_mod"]:
            time.sleep(0.1)
        child = next(j for j in store.all("job") if j["tool"] == "prepare_mod")
        assert child["state"] == "queued"            # nothing will ever claim it in this test
        assert client.post(f"/api/jobs/{swap}/cancel").json()["cancel_requested"] is True
        deadline = time.time() + 5
        while time.time() < deadline and store.get("job", swap)["state"] == "running":
            time.sleep(0.1)
    j = store.get("job", swap)
    assert j["state"] == "failed", j
    assert j["error"].startswith("cancelled by the operator before the replacement started")
    assert store.get("job", child["id"])["state"] == "failed"
    assert store.get("session", sid)["state"] == "running"       # the operator's game was left alone
    assert not [x for x in store.all("job") if x["tool"] == "launch_game"]
    # an operator cancel is not a failed model mod: no auto report is filed
    assert not [rq for rq in store.all("request") if (rq.get("source") or "") == "automation"]
