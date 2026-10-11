import datetime as dt
import json
from pathlib import Path
import sqlite3

import pytest

from gbox import hermes_activation as activation
from gbox.hermes_activation import activation_snapshot, idle_reason, read_active_jobs, read_cron_snapshot, verify_activation


def quiet_tasks():
    return {'jobs': [], 'machines': [{'worker_id': 'spark', 'os': 'linux'},
                                    {'worker_id': 'windows', 'os': 'windows'}],
            'hermes': [], 'resolutions': []}


def test_activation_preserves_busy_work_and_spark_games():
    tasks = quiet_tasks()
    windows = {'session_id': 'windows-game', 'state': 'running', 'detail': {'pid': 123}}
    assert not idle_reason([], tasks, [windows])
    assert idle_reason([{'busy': True}], tasks, [windows])
    assert idle_reason([], tasks | {'jobs': [{'state': 'running'}]}, [windows])
    assert idle_reason([], tasks, [{'session_id': 'spark-game', 'state': 'running'}])


def test_activation_requires_loaded_bridge_and_original_emulator_process():
    policy = {'fallback_enabled': True, 'max_parallel_jobs': 2, 'image_input_mode': 'text'}
    before = [{'session_id': 'windows-game', 'state': 'running', 'detail': {'pid': 123}}]
    verify_activation(policy, before, before)
    with pytest.raises(RuntimeError, match='not loaded'):
        verify_activation({}, before, before)
    with pytest.raises(RuntimeError, match='original PID'):
        verify_activation(policy, before, [])
    with pytest.raises(RuntimeError, match='original PID'):
        verify_activation(policy, [{'session_id': 'windows-game', 'state': 'running'}], [])


def test_later_activation_can_require_its_own_loaded_policy_fields():
    with pytest.raises(RuntimeError, match='not loaded'):
        verify_activation({'fallback_enabled': True}, [], [], {'git_workspace_ready'})
    verify_activation({'git_workspace_ready': True}, [], [], {'git_workspace_ready'})


@pytest.mark.parametrize('state',['claimed','running'])
def test_active_hermes_blocks_refresh_even_with_no_worker_jobs(state):
    tasks = quiet_tasks() | {'hermes': [{'id':'execution','state':state}]}
    assert 'Hermes execution' in idle_reason([], tasks, [])


def test_active_resolution_blocks_refresh():
    tasks = quiet_tasks() | {'resolutions':[{'id':'request','state':'running'}]}
    assert 'inbox resolution' in idle_reason([], tasks, [])


def test_terminal_hermes_and_in_progress_idle_ticket_do_not_block():
    tasks = quiet_tasks() | {'hermes':[{'id':'done','state':'completed'}],
                            'resolutions':[{'id':'request','state':'in_progress'}]}
    assert idle_reason([],tasks,[]) == ''


@pytest.mark.parametrize('changes',[
    {'hermes':None},{'hermes':[{'state':'unknown'}]}, {'hermes':[{'state':'completed'}]},
    {'resolutions':None},{'machines':[{'worker_id':'spark'}]}, {'machines':[{'os':'linux'}]},
    {'machines':[{'worker_id':'spark','os':'linux'},{'worker_id':'spark','os':'windows'}]},
    {'jobs':{}}, {'hermes':[{'id':'run','state':[]}]}, {'resolutions':[{'state':{}}]},
])
def test_incomplete_or_ambiguous_task_snapshot_blocks(changes):
    assert 'valid activation safety snapshot' in idle_reason([],quiet_tasks() | changes,[])


@pytest.mark.parametrize('chat',[{}, {'busy':'false'}, None])
def test_unverified_chat_busy_state_blocks(chat):
    assert idle_reason([chat],quiet_tasks(),[])


@pytest.mark.parametrize('session',[
    {'state':'running','session_id':'unknown-game','detail':{'pid':123}},
    {'state':'running','session_id':'windows-game','detail':{'pid':None}},
    {'state':'running','session_id':'windows-game','detail':{'pid':True}},
    {'state':'running','session_id':'windows-game','worker_id':'spark','detail':{'pid':123}},
    {'state':'running','session_id':'windows-game','worker_id':['windows'],'detail':{'pid':123}},
    {'state':'running','session_id':'windows-game','detail':[]},
    {'state':'unknown','session_id':'windows-game'}, None,
])
def test_unknown_session_owner_or_pid_blocks(session):
    assert idle_reason([],quiet_tasks(),[session])


def test_duplicate_running_session_identity_cannot_be_assumed_safe():
    session = {'state':'running','session_id':'windows-game','detail':{'pid':123}}
    assert idle_reason([],quiet_tasks(),[session,session | {'detail':{'pid':456}}])


@pytest.fixture
def canonical(tmp_path):
    root,home = tmp_path/'system',tmp_path/'hermes'
    (root/'gbox-data').mkdir(parents=True)
    (home/'cron').mkdir(parents=True)
    with sqlite3.connect(root/'gbox-data/gbox.sqlite3') as db:
        db.execute('CREATE TABLE docs (kind TEXT, body TEXT)')
    db.close()
    with sqlite3.connect(home/'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT)')
    db.close()
    (home/'cron/jobs.json').write_text(json.dumps({'jobs':[]}),encoding='utf-8')
    return root,home


def schedule(home, *, timestamp, enabled=True, no_agent=False):
    when = dt.datetime.fromtimestamp(timestamp,dt.timezone.utc).isoformat()
    job = {'id':'scheduled','enabled':enabled,'no_agent':no_agent,'next_run_at':when,
           'schedule':{'kind':'once','run_at':when}}
    (home/'cron/jobs.json').write_text(json.dumps({'jobs':[job]}),encoding='utf-8')
    return job


def pure_api(path):
    # Calling /api/tasks would refresh process inventories; it is not permitted here.
    assert path in ('/api/chat','/api/sessions','/api/workers')
    return [{'id':'spark','os':'linux'}] if path == '/api/workers' else []


def test_snapshot_uses_pure_http_reads_and_read_only_canonical_databases(canonical):
    root,home = canonical
    before = {p:p.read_bytes() for p in (*root.rglob('*'),*home.rglob('*')) if p.is_file()}
    snapshot = activation_snapshot(root,pure_api,home=home,now=1000)
    assert snapshot['reason'] == ''
    assert snapshot['cron']['hermes'] == [] and snapshot['tasks']['jobs'] == []
    after = {p:p.read_bytes() for p in (*root.rglob('*'),*home.rglob('*')) if p.is_file()}
    assert after == before


@pytest.mark.parametrize('state',['claimed','running'])
def test_direct_cron_claim_blocks_when_http_inventory_would_miss_it(canonical,state):
    root,home = canonical
    with sqlite3.connect(home/'cron/executions.db') as db:
        db.execute('INSERT INTO executions VALUES(?,?,?)',('execution','job',state))
    assert 'Hermes execution' in activation_snapshot(root,pure_api,home=home,now=1000)['reason']


@pytest.mark.parametrize('timestamp',[900,1000,1059,1060])
@pytest.mark.parametrize('no_agent',[False,True])
def test_overdue_and_imminent_enabled_occurrence_blocks_all_modes(canonical,timestamp,no_agent):
    root,home = canonical
    schedule(home,timestamp=timestamp,no_agent=no_agent)
    snapshot = activation_snapshot(root,pure_api,home=home,now=1000)
    assert 'imminent or overdue' in snapshot['reason']
    assert snapshot['cron']['imminent_or_overdue'][0]['no_agent'] is no_agent


def test_future_or_disabled_occurrence_does_not_perpetually_block(canonical):
    root,home = canonical
    schedule(home,timestamp=1061)
    assert activation_snapshot(root,pure_api,home=home,now=1000)['reason'] == ''
    schedule(home,timestamp=900,enabled=False)
    assert activation_snapshot(root,pure_api,home=home,now=1000)['reason'] == ''


@pytest.mark.parametrize('bad',[None,'bad-time','2026-10-11T08:00:00'])
def test_enabled_schedule_without_trustworthy_next_occurrence_fails_closed(canonical,bad):
    root,home = canonical
    job = schedule(home,timestamp=2000)
    job['next_run_at'] = bad
    (home/'cron/jobs.json').write_text(json.dumps({'jobs':[job]}),encoding='utf-8')
    assert activation_snapshot(root,pure_api,home=home,now=1000)['reason']


@pytest.mark.parametrize('missing',['cron/jobs.json','cron/executions.db'])
def test_missing_cron_evidence_cannot_mean_idle(canonical,missing):
    root,home = canonical
    (home/missing).unlink()
    assert activation_snapshot(root,pure_api,home=home,now=1000)['reason']
    assert not (home/missing).exists()


def test_missing_gbox_database_is_not_created(canonical):
    root,home = canonical
    database = root/'gbox-data/gbox.sqlite3'
    database.unlink()
    assert activation_snapshot(root,pure_api,home=home,now=1000)['reason']
    assert not database.exists()


@pytest.mark.parametrize('state',['queued','running','unknown'])
def test_direct_active_or_unknown_worker_job_blocks(canonical,state):
    root,home = canonical
    with sqlite3.connect(root/'gbox-data/gbox.sqlite3') as db:
        db.execute('INSERT INTO docs VALUES(?,?)',('job',json.dumps({'id':'job','state':state})))
    assert activation_snapshot(root,pure_api,home=home,now=1000)['reason']


def test_terminal_job_records_are_not_active(canonical):
    root,_ = canonical
    with sqlite3.connect(root/'gbox-data/gbox.sqlite3') as db:
        db.executemany('INSERT INTO docs VALUES(?,?)',[('job',json.dumps({'id':s,'state':s}))
                        for s in ('succeeded','invalid','failed','rejected','cancelled')])
    assert read_active_jobs(root) == []


@pytest.mark.parametrize('now',[True,float('nan'),float('inf')])
def test_nonfinite_or_boolean_boundary_fails_closed(canonical,now):
    _,home = canonical
    with pytest.raises(ValueError): read_cron_snapshot(home,now=now)


@pytest.mark.parametrize('inventory',[
    None,[{'state':'unknown'}],[{'state':'running','session_id':'windows-game','detail':[]}],
    [{'state':'running','session_id':'windows-game','detail':{'pid':123}},
     {'state':'running','session_id':'windows-game','detail':{'pid':123}}],
])
def test_post_refresh_pid_inventory_must_be_complete_and_unambiguous(inventory):
    policy = {'fallback_enabled':True,'max_parallel_jobs':2,'image_input_mode':'text'}
    with pytest.raises(RuntimeError): verify_activation(policy,[],inventory)


def test_unhashable_original_session_identity_is_a_verification_failure():
    policy = {'fallback_enabled':True,'max_parallel_jobs':2,'image_input_mode':'text'}
    before = [{'state':'running','session_id':[],'detail':{'pid':123}}]
    with pytest.raises(RuntimeError,match='original PID'):
        verify_activation(policy,before,[])


def test_new_claim_on_last_recheck_prevents_restart_and_completion(tmp_path,monkeypatch):
    (tmp_path/'gbox-data').mkdir()
    (tmp_path/'gbox-data/api_token').write_text('temporary-test-token')
    values = iter([{'reason':'','sessions':[]},{'reason':'','sessions':[]},
                   {'reason':'Waiting for the active Hermes execution to finish.','sessions':[]}])
    monkeypatch.setattr(activation,'activation_snapshot',lambda *args,**kwargs:next(values))
    ticks = iter([0,0,10])
    monkeypatch.setattr(activation.time,'monotonic',lambda:next(ticks))
    monkeypatch.setattr(activation.time,'sleep',lambda duration:None)
    requests,commands = [],[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return b'{}'
    def urlopen(request,**kwargs):
        requests.append((request.full_url,request.data))
        return Response()
    monkeypatch.setattr(activation.urllib.request,'urlopen',urlopen)
    monkeypatch.setattr(activation.subprocess,'run',lambda *args,**kwargs:commands.append(args))
    with pytest.raises(RuntimeError,match='No safe idle window'):
        activation.activate(tmp_path,'request','run',timeout=5)
    assert commands == []
    assert all('/status' not in url for url,_ in requests)
