"""The Spark2 task dashboard feed: GET /api/hermes/dashboard assembles the enriched Hermes runs in one
read-only call (no machine-inventory jobs, unlike /api/tasks) and tolerates an unavailable providers/
local view. Opened from the PiP right-click menu (#7526)."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from gbox.server import create_app

TZ = timezone(timedelta(hours=-6))
T0 = datetime(2026, 10, 11, 8, 0, tzinfo=TZ)


def _home(tmp_path, agent_runs, script_runs_per_agent=6):
    """An inbox job with `agent_runs` Hermes sessions and a maintenance script firing between them."""
    home = tmp_path / ".hermes"
    (home / "cron").mkdir(parents=True)
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": [
        {"id": "inbox", "name": "gBox inbox task mode"}, {"id": "maint", "name": "maintenance"}]}))
    ex = sqlite3.connect(home / "cron" / "executions.db")
    ex.execute("CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, started_at TEXT, finished_at TEXT, error TEXT)")
    st = sqlite3.connect(home / "state.db")
    st.execute("CREATE TABLE sessions (id TEXT, source TEXT, started_at REAL, model TEXT, input_tokens INTEGER, output_tokens INTEGER)")
    st.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_name TEXT, tool_calls TEXT, tool_call_id TEXT)")
    for i in range(agent_runs):
        start = T0 + timedelta(minutes=40 * i)
        sid = f"cron_inbox_{start:%Y%m%d_%H%M%S}"
        ex.execute("INSERT INTO executions VALUES (?,?,?,?,?,?)",
                   (f"run{i:03d}".ljust(32, "0"), "inbox", "completed", start.isoformat(),
                    (start + timedelta(minutes=30)).isoformat(), None))
        st.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)", (sid, "cron", start.timestamp() + 2, f"model-{i}", 10 + i, 1))
        ticket = f"{i:016x}"
        calls = [{"id": f"c{i}", "function": {"name": "mcp__gbox__reply_request",
                                              "arguments": json.dumps({"request_id": ticket, "text": "x"})}}]
        st.execute("INSERT INTO messages(session_id,role,content,tool_calls) VALUES (?,?,?,?)",
                   (sid, "assistant", "", json.dumps(calls)))
        st.execute("INSERT INTO messages(session_id,role,content,tool_name,tool_call_id) VALUES (?,?,?,?,?)",
                   (sid, "tool", json.dumps({"ok": True, "request_id": ticket, "posted_message": {"text": "x"}}),
                    "mcp__gbox__reply_request", f"c{i}"))
        for k in range(script_runs_per_agent):
            s = start + timedelta(minutes=5 * (k + 1))
            ex.execute("INSERT INTO executions VALUES (?,?,?,?,?,?)",
                       (f"m{i:03d}{k}".ljust(32, "0"), "maint", "completed", s.isoformat(), s.isoformat(), None))
    ex.commit(); st.commit(); ex.close(); st.close()
    return home


def test_dashboard_lists_enriched_runs_and_is_bounded(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_HERMES_HOME", str(_home(tmp_path, agent_runs=30)))
    app = create_app(cfg)
    client = TestClient(app, headers={"authorization": f"Bearer {cfg.token()}"})
    store = app.state.store
    store.put("request", f"{29:016x}", {"id": f"{29:016x}", "number": 7526, "status": "in_progress",
                                        "title": "open the task window from the PiP"})

    body = client.get("/api/hermes/dashboard").json()
    # Default view: the same enriched runs as the Tasks panel, under "runs" (not "hermes"), with tickets named.
    runs = body["runs"]
    assert len(runs) == 24                     # default limit
    assert "generated" in body
    assert "machines" not in body              # read-only: no worker inventory is collected here
    agent = [r for r in runs if r["job_id"] == "inbox"]
    assert agent[0]["model"] == "model-29"
    assert agent[0]["tickets"] == [{"id": f"{29:016x}", "number": 7526,
                                    "title": "open the task window from the PiP", "status": "in_progress"}]

    # The limit is honoured and bounded 1..100.
    assert len(client.get("/api/hermes/dashboard?limit=3").json()["runs"]) == 3
    assert len(client.get("/api/hermes/dashboard?limit=1000").json()["runs"]) == 31  # 30 agent + 1 maintenance
    assert len(client.get("/api/hermes/dashboard?limit=0").json()["runs"]) >= 1

    # The optional provider/local/queue views are always present as keys (possibly null) and never 500.
    for key in ("providers", "local", "grunt", "queue"):
        assert key in body


def test_dashboard_tolerates_an_unavailable_providers_view(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_HERMES_HOME", str(_home(tmp_path, agent_runs=2)))
    from gbox import hermes_providers
    monkeypatch.setattr(hermes_providers, "summary", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    app = create_app(cfg)
    client = TestClient(app, headers={"authorization": f"Bearer {cfg.token()}"})
    resp = client.get("/api/hermes/dashboard")
    assert resp.status_code == 200
    assert resp.json()["providers"] is None
    assert resp.json()["runs"]                  # the feed still lists the runs
