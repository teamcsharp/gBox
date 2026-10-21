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
