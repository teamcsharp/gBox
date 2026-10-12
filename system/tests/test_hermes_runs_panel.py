"""The Tasks panel lists more than 8 Hermes runs and names each run's tickets (#1300)."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from gbox import hermes_tasks
from gbox.server import create_app

TZ = timezone(timedelta(hours=-6))
T0 = datetime(2026, 10, 11, 8, 0, tzinfo=TZ)


def _home(tmp_path, agent_runs, script_runs_per_agent=6):
    """An inbox job with `agent_runs` sessions and a maintenance script that
    fires several times between every agent run, as on the Spark."""
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


def test_list_runs_returns_more_than_eight_and_matches_old_sessions_by_time(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOX_HERMES_HOME", str(_home(tmp_path, agent_runs=40)))
    runs = hermes_tasks.list_runs(30)
    agent = [r for r in runs if r["job_id"] == "inbox"]
    # One row for the maintenance script; the rest are the 29 newest agent runs.
    assert len(runs) == 30 and len(agent) == 29
    assert [r["job_id"] for r in runs].count("maint") == 1
    # Runs far older than the job's 10 newest sessions still have their own session.
    assert [r["model"] for r in agent] == [f"model-{i}" for i in range(39, 10, -1)]
    assert agent[-1]["request_ids"] == [f"{11:016x}"]
    assert agent[-1]["tokens_in"] == 21
    assert len(hermes_tasks.list_runs()) == hermes_tasks.DEFAULT_RUNS
    assert len(hermes_tasks.list_runs(500)) == 41  # capped at MAX_RUNS; only 41 rows exist
    assert len(hermes_tasks.list_runs(0)) == hermes_tasks.DEFAULT_RUNS


def test_tasks_endpoint_honours_hermes_limit_and_names_tickets(cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_HERMES_HOME", str(_home(tmp_path, agent_runs=30)))
    app = create_app(cfg)
    client = TestClient(app, headers={"authorization": f"Bearer {cfg.token()}"})
    store = app.state.store
    store.put("request", f"{29:016x}", {"id": f"{29:016x}", "number": 1300, "status": "in_progress",
                                        "title": "check the tasks deployed via hermes"})
    default = client.get("/api/tasks").json()["hermes"]
    assert len(default) == 20
    agent = [r for r in default if r["job_id"] == "inbox"]
    newest = agent[0]
    assert newest["model"] == "model-29"
    assert newest["tickets"] == [{"id": f"{29:016x}", "number": 1300,
                                  "title": "check the tasks deployed via hermes", "status": "in_progress"}]
    assert agent[1]["tickets"] == []  # a ticket id the inbox no longer has is left out
    more = client.get("/api/tasks?hermes_limit=40").json()["hermes"]
    assert len(more) == 31  # 30 agent runs + one maintenance row
    assert len(client.get("/api/tasks?hermes_limit=1000").json()["hermes"]) == 31
    assert len(client.get("/api/tasks?hermes_limit=3").json()["hermes"]) == 3
