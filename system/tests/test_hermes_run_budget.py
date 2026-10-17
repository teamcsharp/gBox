import asyncio
from datetime import datetime, timezone
import json
import sqlite3

import pytest

from gbox import hermes_run_budget as B, llm_proxy as P
from gbox.config import HermesLocalConfig

RID = '1234567890abcdef'
TASK = f'Assigned queue task: request #7 ({RID}). Work ONLY this request.'
URL = 'http://127.0.0.1:8765/api/llm/local/nodes/sparkDeux/v1'
START = 1792270000.0
JOB = 'abcdef123456'
SID = f'cron_{JOB}_20261017_150000'


def call(identity, name='terminal', args=None):
    return {'id': identity, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args or {'command': 'true'})}}


def conversation(*items, task=TASK):
    return [{'role': 'user', 'content': task},
            *[{'role': 'assistant', 'content': '', 'tool_calls': [item]} for item in items]]


@pytest.fixture
def history(tmp_path):
    (tmp_path / 'cron').mkdir()
    with sqlite3.connect(tmp_path / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions(id TEXT,job_id TEXT,started_at TEXT,status TEXT)')
    with sqlite3.connect(tmp_path / 'state.db') as db:
        db.executescript('CREATE TABLE sessions(id TEXT PRIMARY KEY,source TEXT,started_at REAL,ended_at REAL,billing_base_url TEXT);'
                         'CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,tool_calls TEXT);'
                         'CREATE INDEX message_session ON messages(session_id,id);')
    def add(items, *, sid=SID, execution='run1', job=JOB, started=START, status='running', endpoint=URL, task=TASK, ended=None):
        with sqlite3.connect(tmp_path / 'cron/executions.db') as db:
            db.execute('INSERT INTO executions VALUES(?,?,?,?)', (execution,job,datetime.fromtimestamp(started,timezone.utc).isoformat(),status))
        with sqlite3.connect(tmp_path / 'state.db') as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(sid,'cron',started+1,ended,endpoint))
            db.execute('INSERT INTO messages(session_id,role,content) VALUES(?,?,?)',(sid,'user',task))
            for item in items:
                db.execute('INSERT INTO messages(session_id,role,tool_calls) VALUES(?,?,?)',(sid,'assistant',json.dumps([item])))
    return tmp_path, add


def test_compaction_uses_durable_calls_and_deduplicates_copied_history(history):
    home, add = history
    items = [call(f'c{i}') for i in range(59)]
    add(items + items[20:])  # Hermes rewrites historical rows during compaction.
    result = B.measure(conversation(*items[-41:]), URL, home=home)
    assert result == {'attempts': 59, 'source': 'durable_transcript', 'execution_id': 'run1',
                      'session_id': SID, 'request_id': RID,
                      'reason': 'active_execution_assignment_endpoint_and_calls_match'}


def test_batched_attempts_are_individual_and_duplicate_outer_id_counts_once(history):
    home, add = history
    batch = call('batch1', 'tool_call', {'calls': [{'name': 'a', 'arguments': {}}, {'name': 'b', 'arguments': {}}]})
    add([batch, batch, call('c2')])
    assert B.measure(conversation(batch, batch, call('c2')), URL, home=home)['attempts'] == 3


def test_same_ticket_new_execution_never_inherits_previous_run_budget(history):
    home, add = history
    add([call(f'old{i}') for i in range(100)], status='completed', ended=START+10)
    new_sid = f'cron_{JOB}_20261017_160000'
    add([call('fresh')], sid=new_sid, execution='run2', started=START+3600)
    result = B.measure(conversation(call('fresh')), URL, home=home)
    assert result['attempts'] == 1 and result['execution_id'] == 'run2'


@pytest.mark.parametrize('change', ['other_endpoint','other_assignment','other_calls','ended_session','ended_execution','ambiguous_sessions','ambiguous_runs'])
def test_missing_or_ambiguous_identity_never_borrows_durable_calls(history, change):
    home, add = history
    kwargs = {}
    if change == 'other_endpoint': kwargs['endpoint'] = URL.replace('sparkDeux','lilspark')
    if change == 'other_assignment': kwargs['task'] = TASK.replace(RID,'aaaaaaaaaaaaaaaa')
    if change == 'ended_session': kwargs['ended'] = START+100
    if change == 'ended_execution': kwargs['status'] = 'completed'
    add([call('one'),call('two')], **kwargs)
    if change == 'ambiguous_sessions':
        with sqlite3.connect(home/'state.db') as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(SID+'copy','cron',START+2,None,URL))
    if change == 'ambiguous_runs':
        add([call('one'),call('two')], sid='cron_111111111111_20261017_150000',job='111111111111',execution='run2')
    result = B.measure(conversation(call('different' if change == 'other_calls' else 'two')),URL,home=home)
    assert result['source'] == 'visible_messages' and result['attempts'] == 1
    assert 'execution_id' not in result


def test_multiple_assignment_markers_do_not_guess_owner(history):
    home, add = history; add([call('one'),call('two')])
    result = B.measure(conversation(call('two'),task=TASK+' '+TASK.replace(RID,'aaaaaaaaaaaaaaaa')),URL,home=home)
    assert result['source'] == 'visible_messages' and result['attempts'] == 1


def test_tool_result_cannot_claim_a_different_assignment(history):
    home, add = history; add([call('one'),call('two')])
    messages = conversation(call('two')) + [{'role':'tool','content':TASK.replace(RID,'aaaaaaaaaaaaaaaa')}]
    assert B.measure(messages,URL,home=home)['attempts'] == 2


def test_same_call_id_with_different_arguments_is_not_trusted(history):
    home, add = history; add([call('one'),call('two')])
    result = B.measure(conversation(call('two',args={'command':'different'})),URL,home=home)
    assert result['source'] == 'visible_messages'


def test_corrupt_replayed_id_is_not_counted_as_durable(history):
    home, add = history; add([call('one'),call('one',args={'command':'different'}),call('two')])
    assert B.measure(conversation(call('two')),URL,home=home)['source'] == 'visible_messages'


@pytest.mark.parametrize('limit', ['MAX_ROWS','MAX_TOTAL_BYTES','MAX_CALL_BYTES','MAX_EXECUTIONS','MAX_ASSIGNMENT_BYTES'])
def test_reads_are_bounded_and_fallback_does_not_borrow_history(history,monkeypatch,limit):
    home, add = history; add([call('one'),call('two')])
    monkeypatch.setattr(B,limit,0 if limit=='MAX_EXECUTIONS' else 1)
    assert B.measure(conversation(call('two')),URL,home=home)['source']=='visible_messages'


def test_missing_databases_are_not_created(tmp_path):
    assert B.measure(conversation(call('one')),URL,home=tmp_path)['source']=='visible_messages'
    assert list(tmp_path.iterdir()) == []


def test_read_only_probe_leaves_database_bytes_unchanged(history):
    home, add=history;add([call('one'),call('two')])
    paths=[home/'cron/executions.db',home/'state.db'];before=[p.read_bytes()for p in paths]
    assert B.measure(conversation(call('two')),URL,home=home)['attempts']==2
    assert before==[p.read_bytes()for p in paths]


def test_missing_ids_and_invalid_batches_keep_visible_attempts():
    assert B.measure(conversation({'function':{'name':'tool_call','arguments':'{"calls":[{},{}]}'}}),URL)['attempts']==2
    assert B.measure(conversation(call('empty','tool_call',{'calls':[]})),URL)['attempts']==1


def test_proxy_budget_after_compaction_and_checkpoint_reserve(history,monkeypatch):
    home,add=history;items=[call(f'c{i}')for i in range(59)];add(items)
    monkeypatch.setenv('HERMES_HOME',str(home))
    settings=HermesLocalConfig(enabled=True,proxy_url=URL,api_format='openai',tool_budget=45)
    proxy=P.LocalLLM(lambda:settings)
    _,payload,meta=asyncio.run(proxy.prepare({'messages':conversation(*items[-41:]),'tools':[]}))
    assert meta['queue_tool_calls']==59 and meta['budget_final']
    assert meta['queue_budget']['execution_id']=='run1'
    assert payload['tool_choice']=='none'
    assert 'artifact/job IDs, tests, blockers' in payload['messages'][-1]['content']
    assert 'Do not claim incomplete acceptance criteria are resolved' in payload['messages'][-1]['content']


def test_budget_warning_preserves_tools_for_tests_publication_and_handoff(history,monkeypatch):
    home,add=history;items=[call(f'c{i}')for i in range(39)];add(items)
    monkeypatch.setenv('HERMES_HOME',str(home))
    settings=HermesLocalConfig(enabled=True,proxy_url=URL,api_format='openai',tool_budget=45)
    tools=[{'type':'function','function':{'name':'publish_task_changes','parameters':{'type':'object'}}}]
    _,payload,meta=asyncio.run(P.LocalLLM(lambda:settings).prepare({'messages':conversation(*items[-10:]),'tools':tools}))
    assert not meta['budget_final'] and payload['tools']==tools and 'tool_choice'not in payload
    assert 'Only 6 tool calls remain' in payload['messages'][-1]['content']


def test_final_reminder_does_not_discard_latest_tool_evidence(monkeypatch,tmp_path):
    monkeypatch.setenv('HERMES_HOME',str(tmp_path))
    settings=HermesLocalConfig(enabled=True,proxy_url=URL,api_format='openai',tool_budget=6,
                              context_tokens=4096,max_output_tokens=512)
    messages=conversation(*[call(f'c{i}')for i in range(6)])
    messages.append({'role':'tool','tool_call_id':'c5','content':'VERIFIED RECEIPT: '+('x'*30000)+' tests=failed; request remains open'})
    _,payload,meta=asyncio.run(P.LocalLLM(lambda:settings).prepare({'messages':messages,'tools':[]}))
    assert meta['budget_final'] and meta['cut']
    retained=[m for m in payload['messages']if m.get('tool_call_id')=='c5']
    assert len(retained)==1 and 'VERIFIED RECEIPT' in retained[0]['content'] and 'tests=failed' in retained[0]['content']


def test_non_queue_calls_do_not_read_transcripts(monkeypatch):
    def fail(*args): raise AssertionError('not a queued run')
    monkeypatch.setattr(B,'measure',fail)
    settings=HermesLocalConfig(enabled=True,proxy_url=URL)
    _,_,meta=asyncio.run(P.LocalLLM(lambda:settings).prepare({'messages':[{'role':'user','content':'hello'}]}))
    assert meta['queue_budget'] is None and meta['queue_tool_calls'] is None
