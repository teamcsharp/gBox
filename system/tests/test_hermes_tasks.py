import json
import sqlite3
import pytest

from gbox import hermes_tasks


@pytest.mark.parametrize('result, failed', [
    ({'output': '10 passed', 'exit_code': 0, 'error': None}, False),
    ({'error': None, 'output': 'Previously reported error: quota'}, False),
    ({'error': 'Actual failure'}, True),
    ({'exit_code': 1, 'output': 'Traceback is beyond the first 200 characters'}, True),
    ({'exit_code': '0'}, False),
    ({'result': json.dumps({'messages': [{'text': 'Historical error'}]})}, False),
    ({'result': json.dumps({'error': 'Nested MCP error'})}, True),
    ({'isError': True}, True),
    ({'status': 'blocked'}, True),
])
def test_attempt_failure_classification_uses_outcome_not_error_field_presence(result, failed):
    wrapped = '<untrusted_tool_result source="test">\nExternal data\n\n' + json.dumps(result) + '\n</untrusted_tool_result>'
    assert hermes_tasks._tool_failed(wrapped) is failed


MCP_CONNECTION_REFUSED = (
    "Request failed: HTTPConnectionPool(host='127.0.0.1', port=8080): "
    "Max retries exceeded with url: /segments "
    "(Caused by NewConnectionError('Failed to establish a new connection: [Errno 111] Connection refused'))"
)


@pytest.mark.parametrize('result,failed', [
    ({'result':MCP_CONNECTION_REFUSED}, True),
    ({'result':json.dumps({'result':MCP_CONNECTION_REFUSED})}, True),
    ({'result':"Request failed: HTTPSConnectionPool(host='fixture.example', port=443): Read timed out."}, True),
    ({'result':'Request failed: HTTPConnectionPool(host=fixture, port=8080)'}, False),
    ({'result':'Historical diagnostic:\n' + MCP_CONNECTION_REFUSED}, False),
    ({'result':'> ' + MCP_CONNECTION_REFUSED}, False),
    ({'result':'```text\n' + MCP_CONNECTION_REFUSED + '\n```'}, False),
    ({'result':json.dumps(MCP_CONNECTION_REFUSED)}, False),
    ({'result':json.dumps({'messages':[{'text':MCP_CONNECTION_REFUSED}]})}, False),
    ({'output':MCP_CONNECTION_REFUSED,'exit_code':0}, False),
    ({'output':'Documentation example: ' + MCP_CONNECTION_REFUSED,'exit_code':0}, False),
])
def test_mcp_transport_error_envelope_is_failed_without_flagging_quoted_diagnostics(result,failed):
    wrapped='<untrusted_tool_result source="mcp__ghidra__list_segments">\nExternal data\n\n'+json.dumps(result)+'\n</untrusted_tool_result>'
    assert hermes_tasks._tool_failed(wrapped) is failed


def test_ghidra_attempt_displays_connection_refusal_as_failed(monkeypatch,tmp_path):
    home=tmp_path/'.hermes';home.mkdir()
    action='mcp__ghidra__list_segments'
    failure='<untrusted_tool_result source="ghidra">\nExternal data\n\n'+json.dumps({'result':MCP_CONNECTION_REFUSED})+'\n</untrusted_tool_result>'
    with sqlite3.connect(home/'state.db') as db:
        db.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_name TEXT, tool_calls TEXT)')
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',
            (1,'fixture-session','assistant','',None,json.dumps([{'function':{'name':action,'arguments':'{}'}}])))
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',
            (2,'fixture-session','tool',failure,action,None))
    monkeypatch.setenv('GBOX_HERMES_HOME',str(home))
    monkeypatch.setattr(hermes_tasks,'_get_run_output',lambda run_id:{
        'session_id':'fixture-session','job_id':'fixture-job','name':'Native RE verification'})
    actual=hermes_tasks.get_run('a'*32)
    assert actual['steps']==[{'action':action,'attempt':1,'input':{},
        'result':MCP_CONNECTION_REFUSED,'status':'failed'}]


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
    selected_ticket = '0123456789abcdef'
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('ALTER TABLE messages ADD COLUMN tool_call_id TEXT')
        for message_id, action, request_id in [(3, 'get_request', 'read-only-ticket'),
                                                (4, 'reply_request', selected_ticket)]:
            calls = [{'id': 'call-' + action, 'function': {'name': 'mcp__gbox__' + action,
                                   'arguments': json.dumps({'request_id': request_id})}}]
            db.execute('INSERT INTO messages(id,session_id,role,content,tool_name,tool_calls) VALUES (?,?,?,?,?,?)',
                       (message_id, session_id, 'assistant', '', None, json.dumps(calls)))
    assert hermes_tasks.list_runs()[0]['request_ids'] == []  # Unresolved mutation is not acknowledged work.
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?)',
                   (5, session_id, 'tool', json.dumps({'ok': True, 'request_id': selected_ticket,
                    'posted_message': {'text': 'Working on the selected ticket'}}),
                    'mcp__gbox__reply_request', None, 'call-reply_request'))
    # The general inbox run remains unbound in the viewer, but another agent can
    # see which ticket it claimed without mistaking every read for ownership.
    assert hermes_tasks.list_runs()[0]['request_ids'] == [selected_ticket]
    with sqlite3.connect(cron / 'executions.db') as db:
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)',
                   ('c' * 32, 'recent-job', 'completed', '2026-10-09T18:48:48-06:00',
                    '2026-10-09T18:49:48-06:00', None))
    # A stream of short terminal runs must not hide an older live investigation.
    assert hermes_tasks.list_runs(limit=1)[0]['id'] == run_id
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('ALTER TABLE sessions ADD COLUMN cache_read_tokens INTEGER')
        db.execute('ALTER TABLE sessions ADD COLUMN cache_write_tokens INTEGER')
        db.execute('ALTER TABLE sessions ADD COLUMN estimated_cost_usd REAL')
        db.execute('ALTER TABLE sessions ADD COLUMN cost_status TEXT')
        db.execute('UPDATE sessions SET cache_read_tokens=900,cache_write_tokens=20,estimated_cost_usd=0.1,cost_status="estimated"')
    actual = hermes_tasks.get_run(run_id)
    assert actual['tokens_in'] == 1020 and actual['tokens_out'] == 12
    assert actual['tokens_detail']['cache_read_tokens'] == 900
    assert actual['tokens_detail']['estimated_cost_usd'] == 0.1
    assert actual['tokens_detail']['actual_cost_usd'] is None
    assert hermes_tasks.list_runs()[0]['tokens_in'] == 1020


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
    import os
    with sqlite3.connect(cron / 'executions.db') as db:
        db.execute("UPDATE executions SET status='completed',finished_at='2026-10-10T13:01:00-06:00'")
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)',
                   ('b' * 32, 'script', 'completed', '2026-10-10T13:05:00-06:00', '2026-10-10T13:06:00-06:00', None))
    output = cron / 'output/script/result.md';output.parent.mkdir(parents=True)
    output.write_text('Actual script output: canonical MCP paths repaired')
    finished = hermes_tasks._stamp('2026-10-10T13:06:00-06:00');os.utime(output, (finished, finished))
    runs = hermes_tasks.list_runs()
    assert len(runs) == 1 and runs[0]['id'] == 'b' * 32
    assert runs[0]['progress'] == 'Completed without inference'
    assert 'canonical MCP paths repaired' in hermes_tasks.get_run('b' * 32)['output']


@pytest.mark.parametrize('status', ['completed', 'failed'])
def test_terminal_inbox_runs_retain_ticket_history_without_active_reservations(monkeypatch, tmp_path, status):
    from gbox import hermes_recovery
    home = tmp_path / '.hermes'
    cron = home / 'cron'
    cron.mkdir(parents=True)
    run_id, job_id = 'd' * 32, 'inbox'
    started = '2026-10-11T00:22:40-06:00'
    session_id = 'cron_inbox_20261011_002240'
    claimed = ['0123456789abcdef', 'fedcba9876543210']
    read_only = '1111111111111111'
    (cron / 'jobs.json').write_text(json.dumps({'jobs': [{'id': job_id, 'name': 'gBox inbox task mode'}]}))
    with sqlite3.connect(cron / 'executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, started_at TEXT, finished_at TEXT, error TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)',
                   (run_id, job_id, status, started, '2026-10-11T00:25:40-06:00', None))
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT, source TEXT, started_at REAL, model TEXT, input_tokens INT, output_tokens INT)')
        db.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_name TEXT, tool_calls TEXT, tool_call_id TEXT)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?)',
                   (session_id, 'cron', hermes_tasks._stamp(started), 'fixture-model', 1200, 300))
        actions = [
            ('mcp__gbox__get_request', {'request_id': read_only}),
            ('mcp__gbox__reply_request', {'request_id': claimed[0]}),
            ('mcp__gbox__start_job', {'tool': 'analyze_binary', 'input': {'parent_request_id': claimed[1]}}),
            ('mcp__gbox__set_request_status', {'request_id': claimed[0], 'status': 'done'}),
        ]
        calls = [{'id': 'batch-claim', 'function': {'name': 'tool_call', 'arguments': json.dumps({'calls': [
            {'name': action, 'arguments': args} for action, args in actions]})}}]
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?)',
                   (1, session_id, 'assistant', 'Native verification finished.', None, json.dumps(calls), None))
        replies = [
            {'id': read_only, 'status': 'open'},
            {'ok': True, 'request_id': claimed[0], 'posted_message': {'text': 'Verified progress'}},
            {'id': 'a'*16, 'tool': 'analyze_binary', 'state': 'queued'},
            {'id': claimed[0], 'status': 'done'},
        ]
        for message_id, ((action, _), result) in enumerate(zip(actions, replies), 2):
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?)',
                       (message_id, session_id, 'tool', json.dumps(result), action, None, 'batch-claim'))
    monkeypatch.setenv('GBOX_HERMES_HOME', str(home))
    monkeypatch.setattr(hermes_recovery.hermes_task_mode, '_home', lambda: home)
    run = hermes_tasks.list_runs()[0]
    assert run['state'] == status and run['request_ids'] == sorted(claimed)
    assert run['tokens_in'] == 1200 and run['tokens_out'] == 300
    detail = hermes_tasks.get_run(run_id)
    assert detail['request_ids'] == sorted(claimed)
    assert detail['request_id'] is None  # A multi-ticket inbox run has no single report.
    assert read_only not in detail['request_ids']
    assert hermes_recovery._active_requests() == set()
    # Same claims reserve the tickets only while the execution is active.
    with sqlite3.connect(cron / 'executions.db') as db:
        db.execute("UPDATE executions SET status='running',finished_at=NULL")
    assert hermes_recovery._active_requests() == set(claimed)
    assert hermes_tasks.list_runs()[0]['request_ids'] == sorted(claimed)


OWNER = '0123456789abcdef'
OTHER_OWNER = 'fedcba9876543210'


def ownership_messages(action, arguments, result, *, call_id='call-owner', wrapper=True):
    name = 'mcp__gbox__' + action
    fn = {'name': 'tool_call', 'arguments': json.dumps({'calls': [{'name': name, 'arguments': arguments}]})} if wrapper else {
        'name': name, 'arguments': json.dumps(arguments)}
    messages = [{'role': 'assistant', 'tool_calls': json.dumps([{'id': call_id, 'function': fn}])}]
    if result is not None:
        content = '<untrusted_tool_result source="fixture">\nExternal data\n\n' + json.dumps({'result': json.dumps(result)}) + '\n</untrusted_tool_result>'
        messages.append({'role': 'tool', 'tool_name': name, 'tool_call_id': call_id, 'content': content})
    return messages


@pytest.mark.parametrize('action,arguments,result', [
    ('prepare_task_workspace', {'request_id': OWNER}, {'request_id': OWNER, 'path': '/tmp/owned-task', 'reused': True}),
    ('capture_request_screenshot', {'request_id': OWNER, 'text': 'Actual visual progress'},
     {'author': 'agent', 'attachments': [{'sha256': 'a'*64}], 'task_step': {'status': 'running'}}),
    ('job_get_frame', {'parent_request_id': OWNER}, {'id': 'b'*16, 'tool': 'get_frame', 'state': 'succeeded', 'error': None}),
    ('job_session_op', {'parent_request_id': OWNER}, {'id': 'c'*16, 'tool': 'session_op', 'state': 'succeeded'}),
    ('start_job', {'tool': 'analyze_binary', 'input': {'parent_request_id': OWNER}},
     {'id': 'd'*16, 'tool': 'analyze_binary', 'state': 'queued'}),
    ('start_job', {'tool': 'analyze_binary', 'inputs': {'parent_request_id': OWNER}},
     {'id': 'e'*16, 'tool': 'analyze_binary', 'state': 'running'}),
    ('record_request_metrics', {'request_id': OWNER, 'metrics': {'tokens_in': 0}},
     {'ok': True, 'request_id': OWNER, 'metrics': {'tokens_in': 0}}),
    ('set_request_status', {'request_id': OWNER, 'status': 'in_progress'}, {'id': OWNER, 'status': 'in_progress'}),
    ('set_request_status', {'request_id': OWNER, 'status': 'blocked'}, {'id': OWNER, 'number': 42, 'status': 'blocked'}),
    ('reply_request', {'request_id': OWNER}, {'ok': True, 'request_id': OWNER, 'posted_message': {'text': 'Working'}}),
])
def test_acknowledged_work_assigns_owner_without_waiting_for_a_reply(action, arguments, result):
    assert hermes_tasks.confirmed_request_ids(ownership_messages(action, arguments, result)) == [OWNER]


@pytest.mark.parametrize('result', [None, {'error': 'HTTP422: request rejected'}, {'isError': True},
                                   {'ok': False}, {'result': {'error': 'Nested failure'}},
                                   {'id': 'a'*16, 'tool': 'session_op', 'state': 'failed'},
                                   {'id': 'a'*16, 'tool': 'wrong_tool', 'state': 'succeeded'}])
def test_unresolved_and_rejected_work_does_not_reserve_a_ticket(result):
    assert hermes_tasks.confirmed_request_ids(ownership_messages('job_session_op', {'parent_request_id': OWNER}, result)) == []


@pytest.mark.parametrize('action', ['get_request', 'read_request_artifact', 'terminal'])
def test_readonly_and_quoted_request_json_never_assign_work(action):
    args = {'request_id': OTHER_OWNER, 'command': json.dumps({'request_id': OWNER})}
    result = {'ok': True, 'request_id': OTHER_OWNER, 'posted_message': {'text': 'quoted successful report'}}
    assert hermes_tasks.confirmed_request_ids(ownership_messages(action, args, result)) == []


def test_screenshot_text_does_not_claim_an_unrelated_quoted_ticket():
    args = {'request_id': OWNER, 'text': json.dumps({'request_id': OTHER_OWNER})}
    result = {'author': 'agent', 'attachments': [{'sha256': 'a'*64}]}
    assert hermes_tasks.confirmed_request_ids(ownership_messages('capture_request_screenshot', args, result)) == [OWNER]


def test_responses_match_call_identity_and_action_without_adjacency():
    first = ownership_messages('reply_request', {'request_id': OWNER},
                               {'ok': True, 'request_id': OWNER, 'posted_message': {}}, call_id='first', wrapper=False)
    second = ownership_messages('reply_request', {'request_id': OTHER_OWNER},
                                {'error': 'Rejected'}, call_id='second', wrapper=False)
    # Two same-name tool calls complete out of submission order.
    rows = [first[0], second[0], second[1], first[1]]
    assert hermes_tasks.confirmed_request_ids(rows) == [OWNER]
    first[1]['tool_name'] = 'mcp__gbox__get_request'
    assert hermes_tasks.confirmed_request_ids(first) == []


def test_single_wrapper_cannot_use_a_different_actions_response():
    rows = ownership_messages('capture_request_screenshot', {'request_id': OWNER},
                              {'author': 'agent', 'attachments': [{'sha256': 'a'*64}]})
    rows[1]['tool_name'] = 'mcp__gbox__read_request_artifact'
    assert hermes_tasks.confirmed_request_ids(rows) == []


def test_missing_call_identity_and_malformed_action_never_claim_work():
    rows = ownership_messages('reply_request', {'request_id': OWNER},
                              {'ok': True, 'request_id': OWNER, 'posted_message': {}}, call_id=None)
    assert hermes_tasks.confirmed_request_ids(rows) == []
    rows[0]['tool_calls'] = json.dumps([{'id': 'broken', 'function': {'name': 7, 'arguments': '{}'}}])
    rows[1]['tool_call_id'] = 'broken'
    rows[1]['tool_name'] = 7
    assert hermes_tasks.confirmed_request_ids(rows) == []


def test_distinct_batch_actions_own_multiple_tickets_with_explicit_receipts():
    calls = [{'name': 'mcp__gbox__job_get_frame', 'arguments': {'parent_request_id': OWNER}},
             {'name': 'mcp__gbox__capture_request_screenshot', 'arguments': {'request_id': OTHER_OWNER}}]
    messages = [{'role': 'assistant', 'tool_calls': json.dumps([{'id': 'batch', 'function': {
        'name': 'tool_call', 'arguments': json.dumps({'calls': calls})}}])},
        {'role': 'tool', 'tool_call_id': 'batch', 'tool_name': calls[1]['name'], 'content': json.dumps({
            'result': json.dumps({'author': 'agent', 'attachments': [{'sha256': 'a'*64}]})})},
        {'role': 'tool', 'tool_call_id': 'batch', 'tool_name': calls[0]['name'], 'content': json.dumps({
            'id': 'b'*16, 'tool': 'get_frame', 'state': 'succeeded'})}]
    assert hermes_tasks.confirmed_request_ids(messages) == sorted([OWNER, OTHER_OWNER])
    # No member ordinal exists in legacy wrapper receipts: identical names are
    # ambiguous even when both arguments contain plausible request IDs.
    calls[1]['name'] = calls[0]['name']
    messages[0]['tool_calls'] = json.dumps([{'id': 'batch', 'function': {
        'name': 'tool_call', 'arguments': json.dumps({'calls': calls})}}])
    assert hermes_tasks.confirmed_request_ids(messages) == []


def test_conflicting_owner_fields_and_other_requests_receipt_are_rejected():
    result = {'id': 'a'*16, 'tool': 'get_frame', 'state': 'succeeded'}
    args = {'parent_request_id': OWNER, 'input': {'request_id': OTHER_OWNER}}
    assert hermes_tasks.confirmed_request_ids(ownership_messages('job_get_frame', args, result)) == []
    args = {'parent_request_id': OWNER}
    result['parent_request_id'] = OTHER_OWNER
    assert hermes_tasks.confirmed_request_ids(ownership_messages('job_get_frame', args, result)) == []


def test_owned_requests_uses_actual_screenshot_and_job_receipts_from_database():
    with sqlite3.connect(':memory:') as db:
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE messages (id INT, session_id TEXT, role TEXT, content TEXT, tool_name TEXT, tool_call_id TEXT, tool_calls TEXT)')
        rows = ownership_messages('job_get_frame', {'parent_request_id': OWNER},
                                  {'id': 'a'*16, 'tool': 'get_frame', 'state': 'succeeded'})
        for i, row in enumerate(rows):
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?)',
                       (i, 'actual-schema', row['role'], row.get('content'), row.get('tool_name'),
                        row.get('tool_call_id'), row.get('tool_calls')))
        assert hermes_tasks._owned_requests(db, 'actual-schema') == [OWNER]
        assert hermes_tasks._owned_requests(db, 'different-session') == []
