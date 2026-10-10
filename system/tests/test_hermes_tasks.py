import json
import sqlite3

from gbox import hermes_tasks


def test_running_hermes_run_exposes_expandable_live_tool_output(monkeypatch, tmp_path):
    home = tmp_path / ".hermes"
    cron = home / "cron"
    cron.mkdir(parents=True)
    run_id = "a" * 32
    job_id = "job123"
    (cron / "jobs.json").write_text(json.dumps({"jobs": [{"id": job_id, "name": "MGS swap"}]}))
    with sqlite3.connect(cron / "executions.db") as db:
        db.execute("CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, started_at TEXT, finished_at TEXT, error TEXT)")
        db.execute("INSERT INTO executions VALUES (?,?,?,?,?,?)", (run_id, job_id, "running", "2026-10-09T17:48:48-06:00", None, None))
        db.execute("INSERT INTO executions VALUES (?,?,?,?,?,?)", ("b" * 32, job_id, "failed", None, None, "Fire claim lost"))
    session_id = "cron_job123_20261009_174849"
    with sqlite3.connect(home / "state.db") as db:
        db.execute("CREATE TABLE sessions (id TEXT, source TEXT, started_at REAL, model TEXT, input_tokens INTEGER, output_tokens INTEGER)")
        db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_name TEXT, tool_calls TEXT)")
        db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)", (session_id, "cron", 1791589729, "gemma4:e4b", 100, 12))
        db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)", (1, session_id, "assistant", "", None,
                   json.dumps([{"function": {"name": "tool_call", "arguments": json.dumps({"calls": [{"name": "mcp__gbox__game_roster", "arguments": {"game_id": "fixture", "request_id": "ticket42"}}]})}}])))
        db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)", (2, session_id, "tool", "Native reader missing", "mcp__gbox__game_roster", None))
    monkeypatch.setenv("GBOX_HERMES_HOME", str(home))

    runs = hermes_tasks.list_runs()
    assert len(runs) == 1
    assert runs[0]["id"] == run_id
    assert runs[0]["name"] == "MGS swap"
    assert runs[0]["progress"] == "Finished mcp__gbox__game_roster"
    assert runs[0]["tokens_in"] == 100
    assert runs[0]['request_ids'] == []
    detail = hermes_tasks.get_run(run_id)
    assert "→ mcp__gbox__game_roster" in detail["output"]
    assert "← mcp__gbox__game_roster: Native reader missing" in detail["output"]
    assert hermes_tasks.get_run("../state.db") is None
    assert detail["steps"] == [{"action": "mcp__gbox__game_roster", "attempt": 1,
                                "input": {"game_id": "fixture", "request_id": "ticket42"}, "result": "Native reader missing", "status": "finished"}]
    assert detail["request_id"] == "ticket42"
    (cron / "jobs.json").write_text(json.dumps({"jobs": [{"id": job_id, "name": "gBox inbox task mode"}]}))
    assert hermes_tasks.get_run(run_id)["request_id"] is None
    with sqlite3.connect(home / 'state.db') as db:
        for message_id, action, request_id in [(3, 'get_request', 'read-only-ticket'),
                                                (4, 'reply_request', 'selected-ticket')]:
            calls = [{'function': {'name': 'mcp__gbox__' + action,
                                   'arguments': json.dumps({'request_id': request_id})}}]
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',
                       (message_id, session_id, 'assistant', '', None, json.dumps(calls)))
    # The general inbox run remains unbound in the viewer, but another agent can
    # see which ticket it claimed without mistaking every read for ownership.
    assert hermes_tasks.list_runs()[0]['request_ids'] == ['selected-ticket']
    with sqlite3.connect(cron / 'executions.db') as db:
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)',
                   ('c' * 32, 'recent-job', 'completed', '2026-10-09T18:48:48-06:00',
                    '2026-10-09T18:49:48-06:00', None))
    # A stream of short terminal runs must not hide an older live investigation.
    assert hermes_tasks.list_runs(limit=1)[0]['id'] == run_id


def test_missing_hermes_installation_has_no_tasks(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_HERMES_HOME", str(tmp_path))
    assert hermes_tasks.list_runs() == []
    assert hermes_tasks.get_run("a" * 32) is None


def test_script_only_hermes_run_links_its_explicit_progress_report(monkeypatch, tmp_path):
    home = tmp_path / '.hermes'
    cron = home / 'cron'
    cron.mkdir(parents=True)
    (cron / 'jobs.json').write_text(json.dumps({'jobs': [{'id': 'script', 'name': 'Backend refresh',
        'prompt': 'Activate safely, request_id=0123456789abcdef.'}]}))
    with sqlite3.connect(cron / 'executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, started_at TEXT, finished_at TEXT, error TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)',
                   ('a' * 32, 'script', 'running', '2026-10-10T13:00:00-06:00', None, None))
    monkeypatch.setenv('GBOX_HERMES_HOME', str(home))
    run = hermes_tasks.get_run('a' * 32)
    assert run['session_id'] is None and run['request_id'] == '0123456789abcdef'
