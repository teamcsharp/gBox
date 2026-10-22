"""The Sessions view follows the live game (clients/web/viz/session-follow.js): the server tells an ended agent / demo
session from the operator's own (agent_owned on every row, ended ones too), and the screensaver says why each PC has
no game yet (GET /api/autoplay-screensaver pcs; tests/test_screensaver.py)."""
import time

from fastapi.testclient import TestClient

from gbox.server import create_app


def test_ended_sessions_say_whether_an_agent_launched_them(cfg):
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    store.put("job", "agentjob", {"id": "agentjob", "tool": "launch_game", "agent_use": True, "state": "succeeded"})
    store.put("job", "mine", {"id": "mine", "tool": "launch_game", "agent_use": False, "state": "succeeded"})
    store.put("session", "w1-agentjob", {"session_id": "w1-agentjob", "game_id": "re4", "title": "RE4", "state": "ended",
                                         "started": now - 600, "ended": now - 20})
    store.put("session", "w1-mine", {"session_id": "w1-mine", "game_id": "pso", "title": "PSO", "state": "ended",
                                     "started": now - 900, "ended": now - 5})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    rows = {r["session_id"]: r for r in client.get("/api/sessions").json()}
    assert rows["w1-agentjob"]["agent_owned"] is True             # an agent's test session: the view moves on at once
    assert rows["w1-mine"]["agent_owned"] is False                # the operator's own game: a minute to Reopen it first
    store.put("slabel", "w1-agentjob", {"owner": "you"})          # claimed by the operator: theirs from now on
    rows = {r["session_id"]: r for r in client.get("/api/sessions").json()}
    assert rows["w1-agentjob"]["agent_owned"] is False


def test_sessions_list_is_running_plus_the_newest_ended_rows(cfg):
    """The archive holds every session ever played; listing all of them cost 45-120 s on the loaded Spark."""
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    for i in range(80):
        store.put("session", f"w1-old{i:03d}", {"session_id": f"w1-old{i:03d}", "game_id": "g", "title": "G",
                                                "state": "ended", "started": now - 9000 + i, "ended": now - 8000 + i})
    store.put("session", "w1-live", {"session_id": "w1-live", "game_id": "g", "title": "G", "state": "running",
                                     "started": now - 8900, "worker_id": "w1"})           # older than every ended row
    for i in range(5):
        store.put("session", f"w1-new{i}", {"session_id": f"w1-new{i}", "game_id": "g", "title": "G",
                                            "state": "ended", "started": now - 100 + i, "ended": now - 50 + i})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    rows = client.get("/api/sessions").json()
    ids = [r["session_id"] for r in rows]
    assert ids[0] == "w1-new4" and "w1-live" in ids                  # newest first; the running session always listed
    assert sum(r["state"] == "ended" for r in rows) == 60
    assert [r["session_id"] for r in client.get("/api/sessions?limit=3").json()] == ["w1-new4", "w1-new3", "w1-new2", "w1-live"]
    assert len(client.get("/api/sessions?limit=0").json()) == 86    # the whole archive on request
    assert [r["session_id"] for r in client.get("/api/sessions?include_ended=false").json()] == ["w1-live"]


def test_running_session_on_an_offline_pc_is_flagged(cfg):
    """#2870: connecting to a 'running' session whose PC is gone showed nothing; the row says so, the view skips it."""
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    store.put("session", "ghostpc-s1", {"session_id": "ghostpc-s1", "game_id": "g", "title": "G", "state": "running",
                                        "started": now - 50, "worker_id": "ghostpc"})
    store.put("worker", "ghostpc", {"id": "ghostpc", "name": "Ghost", "os": "windows", "last_seen": now - 100000})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    rows = {r["session_id"]: r for r in client.get("/api/sessions").json()}
    assert rows["ghostpc-s1"].get("worker_online") is False
