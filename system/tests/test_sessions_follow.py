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
    """#2870: connecting to a 'running' session whose PC is gone showed nothing; the row says so, the view skips it.
    Within the reap grace (a blip / Spark restart) the session stays running and is merely flagged offline."""
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    store.put("session", "ghostpc-s1", {"session_id": "ghostpc-s1", "game_id": "g", "title": "G", "state": "running",
                                        "started": now - 50, "worker_id": "ghostpc"})
    store.put("worker", "ghostpc", {"id": "ghostpc", "name": "Ghost", "os": "windows", "last_seen": now - 60})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    rows = {r["session_id"]: r for r in client.get("/api/sessions").json()}
    assert rows["ghostpc-s1"].get("state") == "running"           # offline only briefly: not reaped yet
    assert rows["ghostpc-s1"].get("worker_online") is False
    # the desktop shell's live list (PiP, docking, saved-view restore) and the view's banner carry it too (2026-10-26)
    live = {r["session_id"]: r for r in client.get("/api/sessions", params={"include_ended": "false"}).json()}
    assert live["ghostpc-s1"].get("worker_online") is False
    assert client.get("/api/sessions/ghostpc-s1/stream/health").json().get("worker_online") is False


def test_dead_session_on_a_long_offline_pc_is_reaped(cfg):
    """A running session whose worker has been gone past the grace is a dead instance: GET /api/sessions ends it so it
    never reaches the Sessions view or the desktop Streams menu. A session on an online worker is never touched."""
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    store.put("session", "deadpc-s1", {"session_id": "deadpc-s1", "game_id": "g", "title": "G", "state": "running",
                                       "started": now - 100000, "worker_id": "deadpc"})
    store.put("worker", "deadpc", {"id": "deadpc", "name": "Dead", "os": "windows", "last_seen": now - 100000})
    store.put("session", "livepc-s1", {"session_id": "livepc-s1", "game_id": "g", "title": "G", "state": "running",
                                       "started": now - 100, "worker_id": "livepc"})
    store.put("worker", "livepc", {"id": "livepc", "name": "Live", "os": "windows", "last_seen": now})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    rows = {r["session_id"]: r for r in client.get("/api/sessions").json()}
    assert rows["deadpc-s1"]["state"] == "ended"
    assert rows["deadpc-s1"]["exit"]["via"] == "reap"
    assert rows["livepc-s1"]["state"] == "running"                # the live game keeps running
    assert store.get("session", "deadpc-s1")["state"] == "ended"  # persisted, so it stops piling up


def test_dead_worker_epochs_are_pruned_and_the_newest_registration_of_a_name_stays(cfg):
    """One reaper pass (app.state.reap_dead_instances, the startup loop's body): a long-offline registration that was
    replaced - federation superseded_by, or a newer registration with the same PC name - is deleted once its sessions
    are reaped, with a worker_alias to the live id. The newest registration of a name is never pruned, and a live
    worker is never touched. 2026-11-04: 100 piled-up epochs each listed a dead 'PC offline' broadcast."""
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    store.put("worker", "i9epoch1", {"id": "i9epoch1", "name": "i9-NUC", "os": "windows", "last_seen": now - 90000})
    store.put("worker", "i9epoch2", {"id": "i9epoch2", "name": "i9-NUC", "os": "windows", "last_seen": now - 80000,
                                     "federation": {"authority": "a" * 64, "superseded_by": "i9live00"}})
    store.put("worker", "i9live00", {"id": "i9live00", "name": "i9-NUC", "os": "windows", "last_seen": now})
    # a dead epoch that still owns a "running" row: the row is reaped first, then the epoch is pruned
    store.put("worker", "i9epoch3", {"id": "i9epoch3", "name": "i9-NUC", "os": "windows", "last_seen": now - 70000})
    store.put("session", "i9epoch3-s1", {"session_id": "i9epoch3-s1", "game_id": "pso", "title": "PSO",
                                         "state": "running", "started": now - 70000, "worker_id": "i9epoch3"})
    store.put("session", "i9live00-s1", {"session_id": "i9live00-s1", "game_id": "pso", "title": "PSO",
                                         "state": "running", "started": now - 100, "worker_id": "i9live00"})
    out = app.state.reap_dead_instances()
    assert out["sessions"] == ["i9epoch3-s1"]                     # the dead epoch's stale row, nothing else
    assert set(out["workers"]) == {"i9epoch1", "i9epoch2", "i9epoch3"}
    assert store.get("worker", "i9live00") and not store.get("worker", "i9epoch1")
    assert store.get("worker_alias", "i9epoch1")["to"] == "i9live00"   # flat alias: cached ids resolve in one hop
    assert store.get("worker_alias", "i9epoch2")["to"] == "i9live00"
    assert store.get("session", "i9live00-s1")["state"] == "running"   # the live i9 game keeps running
    assert app.state.reap_dead_instances() == {"sessions": [], "workers": []}  # a second pass finds nothing
