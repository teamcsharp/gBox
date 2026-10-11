import copy
import json
from pathlib import Path
import sqlite3
import threading
import urllib.error

import pytest

from gbox import hermes_accounting as accounting
from gbox.store import Store

RID = 'b' * 16
RUN = 'a' * 32
SID = 'cron_inbox_20261011_060000'


def call(name, args, result=None, *, cid='call1', wrapped=False):
    if isinstance(result,dict) and result.get('ok') is True and isinstance(result.get('metrics'),dict):
        result = copy.deepcopy(result)
        values = args.get('metrics') or args
        result['metrics'].setdefault('tokens_in',values.get('tokens_in') or 0)
        result['metrics'].setdefault('tokens_out',values.get('tokens_out') or 0)
    fn = {'name':name,'arguments':json.dumps(args)}
    if wrapped:
        fn = {'name':'tool_call','arguments':json.dumps({'calls':[{'name':name,'arguments':args}]})}
    messages = [{'role':'assistant','tool_calls':json.dumps([{'id':cid,'function':fn}])}]
    if result is not None:
        messages.append({'role':'tool','tool_call_id':cid,'tool_name':name,
                         'content':json.dumps({'result':json.dumps(result)})})
    return messages


@pytest.fixture
def data(tmp_path):
    store = Store(tmp_path/'gbox')
    ticket = {'id':RID,'status':'in_progress','solved_by':None,'messages':[],
              'metrics':{'tokens_in':0,'tokens_out':0,'tools':{'terminal':8},'turns':4,
                         'duration_s':None,'agent_seconds':21.5,'files_changed':['existing.py'],
                         'tokens_detail':{'token_count_unavailable':3}}}
    store.put('request',RID,ticket)
    run = {'id':RUN,'state':'completed','session_id':SID,'request_ids':[]}
    session = {'id':SID,'started_at':100,'ended_at':140,'model':'opus','billing_provider':'nous',
               'input_tokens':10,'cache_read_tokens':20,'cache_write_tokens':3,
               'output_tokens':5,'reasoning_tokens':2,'api_call_count':2}
    ledger = [dict(session,task='primary',session_id=SID,estimated_cost_usd=0.5,actual_cost_usd=0),
              {'session_id':SID,'billing_provider':'openrouter','model':'vision','task':'vision',
               'input_tokens':7,'cache_read_tokens':0,'cache_write_tokens':0,'output_tokens':4,
               'reasoning_tokens':1,'api_call_count':1,'estimated_cost_usd':0.1,'actual_cost_usd':0}]
    messages = call('mcp__gbox__capture_request_screenshot',{'request_id':RID},
                    {'author':'agent','attachments':[{'sha256':'e'*64}]},wrapped=True)
    yield store,run,session,ledger,messages
    store.db.close()


def reconcile(data):
    return accounting.reconcile_run(*data)


def test_primary_auxiliary_cache_and_token_only_idempotency(data):
    store,*_ = data
    before = store.get('request',RID)
    result = reconcile(data)
    assert (result['tokens_in_added'],result['tokens_out_added']) == (40,9)
    after = store.get('request',RID)
    assert after['status'] == before['status'] and after['solved_by'] is None
    for key in ('tools','turns','duration_s','agent_seconds','files_changed'):
        assert after['metrics'][key] == before['metrics'][key]
    assert after['metrics']['tokens_detail']['token_count_unavailable'] == 3
    rows = after['metrics']['usage_by_solver']
    assert {(r['provider'],r['model'],r['tokens_in'],r['tokens_out']) for r in rows} == {
        ('nous','opus',33,5),('openrouter','vision',7,4)}
    assert reconcile(data)['status'] == 'already_recorded'
    assert store.get('request',RID) == after
    details = [v for k,v in after['metrics']['tokens_detail'].items() if k.endswith('_usage') and isinstance(v,dict) and v.get('model')]
    assert all(v['actual_cost_usd'] is None and v['billed_credits'] == 'unavailable' for v in details)
    assert sum(v['reasoning_tokens_included_in_output'] for v in details) == 3


def test_successful_snapshot_subtracted_but_duration_tools_preserved(data):
    store,run,session,ledger,messages = data
    ticket = store.get('request',RID)
    ticket['metrics'].update(tokens_in=5,tokens_out=2)
    store.put('request',RID,ticket)
    messages += call('mcp__gbox__record_request_metrics',{'request_id':RID,
                    'metrics':{'provider':'nous','model':'opus','tokens_in':5,'tokens_out':2,'duration_s':21.5}},
                    {'ok':True,'request_id':RID,'id':RID,'metrics':ticket['metrics']},cid='snapshot')
    result = reconcile(data)
    assert (result['tokens_in_added'],result['tokens_out_added']) == (35,7)
    assert store.get('request',RID)['metrics']['agent_seconds'] == 21.5
    assert store.get('request',RID)['metrics']['tokens_in'] == 40


@pytest.mark.parametrize('result',[{'isError':True,'error':'422 invalid metrics'}, {'ok':False,'status':'failed'}])
def test_rejected_nonzero_snapshot_is_not_subtracted(data,result):
    data[-1].extend(call('mcp__gbox__record_request_metrics',{'request_id':RID,'tokens_in':5,'tokens_out':2},result,cid='bad'))
    assert reconcile(data)['tokens_in_added'] == 40


@pytest.mark.parametrize('result',[None, {'result':'Unparseable success'}, {'ok':True,'metrics':{}},
                                  {'ok':True,'request_id':'c'*16,'metrics':{}}])
def test_missing_or_ambiguous_nonzero_receipt_defers(data,result):
    store = data[0]
    before = store.get('request',RID)
    data[-1].extend(call('mcp__gbox__record_request_metrics',{'request_id':RID,'tokens_in':5},result,cid='bad'))
    assert reconcile(data)['status'] == 'deferred'
    assert store.get('request',RID) == before


def test_unattributed_multimodel_snapshot_defers(data):
    data[-1].extend(call('mcp__gbox__record_request_metrics',{'request_id':RID,'tokens_in':5},
                        {'ok':True,'request_id':RID,'metrics':{}},cid='snapshot'))
    assert reconcile(data)['status'] == 'deferred'


def test_nested_snapshot_owner_disagreement_defers(data):
    data[-1].extend(call('mcp__gbox__record_request_metrics',{'request_id':RID,
                        'metrics':{'request_id':'c'*16,'tokens_in':0}},
                        {'ok':True,'request_id':RID,'metrics':{}},cid='snapshot'))
    assert reconcile(data)['status'] == 'deferred'


def test_zero_unavailable_snapshot_preserved(data):
    data[-1].extend(call('mcp__gbox__record_request_metrics',{'request_id':RID,
                    'tokens_in':0,'tokens_out':0,'tokens_detail':{'token_count_unavailable':1}},
                    {'ok':True,'request_id':RID,'metrics':{}},cid='snapshot'))
    assert reconcile(data)['tokens_in_added'] == 40
    assert data[0].get('request',RID)['metrics']['tokens_detail']['token_count_unavailable'] == 3


def manual_primary(data,marker='nous_run_'+RUN+'_final_recorded'):
    store,run,session,ledger,_ = data
    record = accounting._records(run,session,ledger)[0]
    ticket = store.get('request',RID)
    ticket['metrics']['tokens_in'] = 33
    ticket['metrics']['tokens_out'] = 5
    ticket['metrics']['tokens_detail'].update({marker:1,marker+'_usage':record})
    store.put('request',RID,ticket)
    return marker


def test_existing_manual_primary_credit_only_adds_auxiliary(data):
    manual_primary(data)
    assert reconcile(data)['tokens_in_added'] == 7
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 40
    assert reconcile(data)['status'] == 'already_recorded'


def test_manual_complete_common_marker_does_not_credit_again(data):
    store,run,session,ledger,_ = data
    ticket = store.get('request',RID)
    ticket['metrics'].update(tokens_in=40,tokens_out=9)
    for i,record in enumerate(accounting._records(run,session,ledger)):
        marker = 'hermes_run_'+RUN+'_'+str(i)+'_final_recorded'
        ticket['metrics']['tokens_detail'].update({marker:1,marker+'_usage':record})
    ticket['metrics']['tokens_detail']['hermes_session_'+SID+'_recorded'] = 1
    store.put('request',RID,ticket)
    assert reconcile(data)['tokens_in_added'] == 0
    assert reconcile(data)['status'] == 'already_recorded'
    assert store.get('request',RID)['metrics']['tokens_in'] == 40


def test_unexplained_common_marker_fails_closed(data):
    store = data[0]
    ticket = store.get('request',RID)
    ticket['metrics']['tokens_detail']['hermes_session_'+SID+'_recorded'] = 1
    store.put('request',RID,ticket)
    assert reconcile(data)['status'] == 'deferred'
    assert store.get('request',RID)['metrics']['tokens_in'] == 0


@pytest.mark.parametrize('change',[{'tokens_in_including_caches':34},{'run_id':'d'*32},{'tokens_out':6}])
def test_disagreeing_manual_marker_defers(data,change):
    marker = manual_primary(data)
    ticket = data[0].get('request',RID)
    ticket['metrics']['tokens_detail'][marker+'_usage'].update(change)
    data[0].put('request',RID,ticket)
    assert reconcile(data)['status'] == 'deferred'


def test_duplicate_final_marker_counter_rejected(data):
    marker = manual_primary(data)
    ticket = data[0].get('request',RID)
    ticket['metrics']['tokens_detail'][marker] = 2
    data[0].put('request',RID,ticket)
    assert reconcile(data)['status'] == 'deferred'


def test_same_model_multiple_task_snapshot_ambiguous(data):
    data[3][1].update(model='opus',billing_provider='nous')
    data[-1].extend(call('mcp__gbox__record_request_metrics',{'request_id':RID,
                        'provider':'nous','model':'opus','tokens_in':5},
                        {'ok':True,'request_id':RID,'metrics':{}},cid='snapshot'))
    assert reconcile(data)['status'] == 'deferred'


def test_mixed_requests_remain_unallocated_and_reads_do_not_claim(data):
    data[-1].extend(call('mcp__gbox__get_request',{'request_id':'c'*16}, {'id':'c'*16},cid='read'))
    assert reconcile(data)['tokens_in_added'] == 40


def test_multiple_work_owners_defers_entire_primary_aux_ledger(data):
    data[-1].extend(call('mcp__gbox__job_session_op',{'parent_request_id':'c'*16,'session_id':'test'},
                        {'state':'succeeded'},cid='other'))
    assert reconcile(data)['status'] == 'deferred'
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 0


def test_batch_receipts_pair_outer_id_and_unique_nested_action(data):
    args = {'calls':[{'name':'mcp__gbox__job_get_frame','arguments':{'parent_request_id':RID}},
                     {'name':'mcp__gbox__record_request_metrics','arguments':{'request_id':RID,
                      'provider':'nous','model':'opus','tokens_in':5,'tokens_out':2}}]}
    messages = call('tool_call',args,cid='batch')
    messages.extend([{'role':'tool','tool_call_id':'batch','tool_name':'mcp__gbox__job_get_frame',
                      'content':json.dumps({'result':json.dumps({'state':'succeeded'})})},
                     {'role':'tool','tool_call_id':'batch','tool_name':'mcp__gbox__record_request_metrics',
                      'content':json.dumps({'result':json.dumps({'ok':True,'request_id':RID,'metrics':{'tokens_in':5,'tokens_out':2}})})}])
    data[-1].extend(messages)
    ticket = data[0].get('request',RID)
    ticket['metrics'].update(tokens_in=5,tokens_out=2)
    data[0].put('request',RID,ticket)
    assert reconcile(data)['tokens_in_added'] == 35


def test_duplicate_nested_action_defers_instead_of_borrowing_success(data):
    data[-1].extend(call('tool_call',{'calls':[{'name':'mcp__gbox__record_request_metrics','arguments':{'request_id':RID}},
                                            {'name':'mcp__gbox__record_request_metrics','arguments':{'request_id':RID}}]},cid='batch'))
    assert reconcile(data)['status'] == 'deferred'


@pytest.mark.parametrize('change',[{'ended_at':None},{'ended_at':99},{'input_tokens':11}])
def test_unfinished_or_inconsistent_primary_counters_defer(data,change):
    data[2].update(change)
    assert reconcile(data)['status'] == 'deferred'


@pytest.mark.parametrize('bad',[-1,False,1.5,None])
def test_invalid_final_token_count_defers(data,bad):
    data[3][1]['cache_read_tokens'] = bad
    assert reconcile(data)['status'] == 'deferred'


def test_missing_ledger_keeps_zero_and_unavailable_history(data):
    data[3].clear()
    assert reconcile(data)['status'] == 'deferred'
    assert data[0].get('request',RID)['metrics']['tokens_detail'] == {'token_count_unavailable':3}


def test_sql_failure_rolls_back_credits_and_markers(data):
    store = data[0]
    before = store.get('request',RID)
    store.db.execute("CREATE TRIGGER reject_accounting BEFORE INSERT ON docs WHEN NEW.kind='hermes_accounting' "
                     "BEGIN SELECT RAISE(ABORT,'test failure'); END;")
    with pytest.raises(sqlite3.IntegrityError):
        reconcile(data)
    assert store.get('request',RID) == before
    store.db.execute('DROP TRIGGER reject_accounting')
    assert reconcile(data)['tokens_in_added'] == 40


def test_simultaneous_store_callers_credit_once(data):
    results = []
    threads = [threading.Thread(target=lambda:results.append(reconcile(data))) for _ in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sum(result['tokens_in_added'] for result in results) == 40
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 40


def fake_api(store, fault=None):
    state = {'posts':0}
    def api(path,body=None):
        if body is None: return store.get('request',RID)
        state['posts'] += 1
        if fault: fault('before',state,body)
        ticket = store.get('request',RID)
        mt = ticket['metrics']
        mt['tokens_in'] += body['tokens_in']; mt['tokens_out'] += body['tokens_out']
        for key,value in body['tokens_detail'].items():
            mt['tokens_detail'][key] = (mt['tokens_detail'].get(key,0)+value) if isinstance(value,int) else value
        store.put('request',RID,ticket)
        if fault: fault('after',state,body)
        return copy.deepcopy(ticket)
    return api,state


@pytest.fixture
def api_lock(tmp_path,monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE',str(tmp_path/'dispatch'))
    return tmp_path/'accounting'


def test_injected_api_completed_once_token_only(data,api_lock):
    store,run,session,ledger,messages = data
    api,state = fake_api(store)
    result = accounting.reconcile_run_api(api,run,session,ledger,messages,state_dir=api_lock)
    assert result['tokens_in_added'] == 40 and state['posts'] == 3
    assert accounting.reconcile_run_api(api,run,session,ledger,messages,state_dir=api_lock)['status'] == 'already_recorded'
    assert state['posts'] == 3
    assert store.get('request',RID)['metrics']['tools'] == {'terminal':8}


def test_committed_timeout_resolved_by_exact_read_without_repost(data,api_lock):
    def fault(when,state,body):
        if when == 'after' and state['posts'] == 1: raise TimeoutError('response lost')
    api,state = fake_api(data[0],fault)
    result = accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)
    assert result['tokens_in_added'] == 40 and state['posts'] == 3
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 40


def test_unresolved_timeout_persists_intent_and_never_reposts(data,api_lock):
    def fault(when,state,body):
        if when == 'before': raise TimeoutError('unknown transport')
    api,state = fake_api(data[0],fault)
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['status'] == 'deferred'
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['status'] == 'deferred'
    assert state['posts'] == 1 and data[0].get('request',RID)['metrics']['tokens_in'] == 0
    assert json.loads((api_lock/(RUN+'.json')).read_text())['pending']


def test_explicit_422_is_not_credited_and_pending_is_cleared(data,api_lock):
    def fault(when,state,body):
        if when == 'before': raise urllib.error.HTTPError('http://test',422,'invalid',{},None)
    api,state = fake_api(data[0],fault)
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['status'] == 'deferred'
    assert 'pending' not in json.loads((api_lock/(RUN+'.json')).read_text())
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 0


def test_partial_api_write_defers_next_row_without_repeating_first(data,api_lock):
    def fault(when,state,body):
        if when == 'before' and state['posts'] == 2: raise TimeoutError('second row uncertain')
    api,state = fake_api(data[0],fault)
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['status'] == 'deferred'
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 33
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['status'] == 'deferred'
    assert state['posts'] == 2


def test_partial_confirmed_model_marker_resumes_missing_model_only(data,api_lock):
    store,run,session,ledger,messages = data
    ticket = store.get('request',RID)
    plan = accounting._plan(ticket,run,session,ledger,messages)
    body = accounting._api_payload(plan)
    api,state = fake_api(store)
    api('/api/requests/'+RID+'/metrics',body)
    result = accounting.reconcile_run_api(api,run,session,ledger,messages,state_dir=api_lock)
    assert result['tokens_in_added'] == 7 and state['posts'] == 3
    assert store.get('request',RID)['metrics']['tokens_in'] == 40


def test_api_concurrent_unattributed_credit_defers_and_retains_intent(data,api_lock):
    def fault(when,state,body):
        if when == 'after' and state['posts'] == 1:
            ticket = data[0].get('request',RID)
            ticket['metrics']['tokens_in'] += 8
            data[0].put('request',RID,ticket)
            raise TimeoutError('response lost')
    api,state = fake_api(data[0],fault)
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['status'] == 'deferred'
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['status'] == 'deferred'
    assert state['posts'] == 1


def make_home(tmp_path,data):
    home = tmp_path/'home'; (home/'cron').mkdir(parents=True)
    _,run,session,ledger,messages = data
    session['source'] = 'cron'
    stamp = '1970-01-01T00:01:40+00:00'
    with sqlite3.connect(home/'cron/executions.db') as db:
        db.execute('CREATE TABLE executions(id TEXT,job_id TEXT,status TEXT,started_at TEXT,finished_at TEXT)')
        db.execute('INSERT INTO executions VALUES(?,?,?,?,?)',(RUN,'inbox','completed',stamp,'1970-01-01T00:02:20+00:00'))
    with sqlite3.connect(home/'state.db') as db:
        db.execute('CREATE TABLE sessions('+','.join(key+' '+('REAL' if key.endswith('_at') else 'INT' if isinstance(value,int) else 'TEXT') for key,value in session.items())+')')
        db.execute('INSERT INTO sessions VALUES('+','.join('?' for _ in session)+')',tuple(session.values()))
        keys = list(ledger[1])
        db.execute('CREATE TABLE session_model_usage('+','.join(key+' '+('REAL' if key.endswith('_usd') else 'INT' if isinstance(ledger[1][key],int) else 'TEXT') for key in keys)+')')
        for row in ledger: db.execute('INSERT INTO session_model_usage VALUES('+','.join('?' for _ in keys)+')',tuple(row.get(key) for key in keys))
        db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,tool_calls TEXT,tool_call_id TEXT,tool_name TEXT)')
        for i,message in enumerate(messages):
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)',(i,SID,message['role'],message.get('content'),message.get('tool_calls'),message.get('tool_call_id'),message.get('tool_name')))
    return home


def test_bounded_generic_inbox_scan_not_limited_to_zai_route(data,tmp_path):
    home = make_home(tmp_path,data)
    before = {p.name:p.read_bytes() for p in (home/'state.db',home/'cron/executions.db')}
    result = accounting.reconcile_completed(data[0],home,limit=1)
    assert result[0]['tokens_in_added'] == 40
    assert accounting.reconcile_completed(data[0],home,limit=1)[0]['status'] == 'already_recorded'
    assert before == {p.name:p.read_bytes() for p in (home/'state.db',home/'cron/executions.db')}


def test_scanner_ambiguous_session_never_selects_nearest(data,tmp_path):
    home = make_home(tmp_path,data)
    with sqlite3.connect(home/'state.db') as db:
        db.execute("INSERT INTO sessions(id,source,started_at,ended_at,model,billing_provider,input_tokens,cache_read_tokens,cache_write_tokens,output_tokens,reasoning_tokens,api_call_count) SELECT 'cron_inbox_other',source,started_at,ended_at,model,billing_provider,input_tokens,cache_read_tokens,cache_write_tokens,output_tokens,reasoning_tokens,api_call_count FROM sessions")
    assert accounting.reconcile_completed(data[0],home)[0]['status'] == 'deferred'


@pytest.mark.parametrize('limit',[0,51,True,1.5])
def test_scan_requires_explicit_bounded_limit(data,limit):
    with pytest.raises(ValueError): accounting.reconcile_completed(data[0],limit=limit)


def test_scanner_rejects_truncated_message_history(data,tmp_path):
    home = make_home(tmp_path,data)
    with sqlite3.connect(home/'state.db') as db:
        db.executemany('INSERT INTO messages(session_id,role) VALUES(?,?)',[(SID,'tool')]*4001)
    assert accounting.reconcile_completed(data[0],home)[0]['status'] == 'deferred'
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 0


def test_unattributed_existing_tokens_fail_closed(data):
    ticket = data[0].get('request',RID)
    ticket['metrics'].update(tokens_in=10,tokens_out=2)
    data[0].put('request',RID,ticket)
    assert reconcile(data)['status'] == 'deferred'
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 10


def test_proven_historical_run_credit_preserved_and_new_run_added(data):
    ticket = data[0].get('request',RID)
    record = dict(accounting._records(*data[1:4])[0],run_id='d'*32,session_id='cron_other',
                  tokens_in_including_caches=100,tokens_out=20)
    marker = 'nous_run_'+('d'*32)+'_final_recorded'
    ticket['metrics'].update(tokens_in=100,tokens_out=20)
    ticket['metrics']['tokens_detail'].update({marker:1,marker+'_usage':record})
    data[0].put('request',RID,ticket)
    assert reconcile(data)['tokens_in_added'] == 40
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 140


def test_action_aliases_cannot_share_one_nested_receipt(data):
    data[-1].extend(call('tool_call',{'calls':[{'name':'reply_request','arguments':{'request_id':RID}},
                                            {'name':'mcp__gbox__reply_request','arguments':{'request_id':RID}}]},cid='batch'))
    assert reconcile(data)['status'] == 'deferred'


def test_unconfirmed_attempt_or_run_metadata_cannot_allocate(data):
    data[-1].clear()
    data[1]['request_ids'] = [RID]
    data[-1].extend(call('mcp__gbox__capture_request_screenshot',{'request_id':RID},cid='unanswered'))
    assert reconcile(data)['status'] == 'deferred'


def test_mismatched_response_action_not_borrowed_for_snapshot(data):
    messages = call('mcp__gbox__record_request_metrics',{'request_id':RID,'provider':'nous','model':'opus','tokens_in':5},
                    {'ok':True,'request_id':RID,'metrics':{}},cid='wrong')
    messages[-1]['tool_name'] = 'mcp__gbox__reply_request'
    data[-1].extend(messages)
    assert reconcile(data)['status'] == 'deferred'


def test_two_executions_for_one_session_defer(data,tmp_path):
    home = make_home(tmp_path,data)
    with sqlite3.connect(home/'cron/executions.db') as db:
        db.execute('INSERT INTO executions VALUES(?,?,?,?,?)',('d'*32,'inbox','failed',
                    '1970-01-01T00:01:41+00:00','1970-01-01T00:02:20+00:00'))
    assert all(r['status'] == 'deferred' for r in accounting.reconcile_completed(data[0],home))


def test_previous_automatic_run_snapshot_credit_not_lost_for_next_run(data):
    store,run,session,ledger,messages = data
    ticket = store.get('request',RID)
    ticket['metrics'].update(tokens_in=5,tokens_out=2)
    store.put('request',RID,ticket)
    messages += call('mcp__gbox__record_request_metrics',{'request_id':RID,'provider':'nous','model':'opus',
                     'tokens_in':5,'tokens_out':2}, {'ok':True,'request_id':RID,'metrics':{}},cid='snapshot')
    assert reconcile(data)['tokens_in_added'] == 35
    run['id'] = 'd'*32; run['session_id'] = 'cron_inbox_next'
    session['id'] = run['session_id']
    for row in ledger: row['session_id'] = session['id']
    messages[:] = call('mcp__gbox__capture_request_screenshot',{'request_id':RID},
                      {'author':'agent','attachments':[{'sha256':'e'*64}]},cid='newclaim')
    assert reconcile(data)['tokens_in_added'] == 40
    assert store.get('request',RID)['metrics']['tokens_in'] == 80


def test_api_existing_manual_common_receipt_requires_no_posts(data,api_lock):
    store,run,session,ledger,messages = data
    ticket = store.get('request',RID)
    ticket['metrics'].update(tokens_in=40,tokens_out=9)
    for i,record in enumerate(accounting._records(run,session,ledger)):
        marker = 'hermes_run_'+RUN+'_'+str(i)+'_final_recorded'
        ticket['metrics']['tokens_detail'].update({marker:1,marker+'_usage':record})
    ticket['metrics']['tokens_detail']['hermes_session_'+SID+'_recorded'] = 1
    store.put('request',RID,ticket)
    api,state = fake_api(store)
    assert accounting.reconcile_run_api(api,run,session,ledger,messages,state_dir=api_lock)['status'] == 'already_recorded'
    assert state['posts'] == 0


@pytest.mark.parametrize('actual,status,expected',[(0.75,'actual',0.75),(0,'actual',0),
    (0,None,None),(0,'estimated',None),(float('nan'),'actual',None),(-1,'actual',None),
    (True,'actual',None)])
def test_actual_ledger_dollars_only_when_explicit_and_valid(data,actual,status,expected):
    data[3][0].update(actual_cost_usd=actual,cost_status=status)
    records = accounting._records(*data[1:4])
    primary = next(r for r in records if r['task'] == 'primary')
    assert primary['actual_cost_usd'] == expected
    assert primary['billed_credits'] == 'unavailable'


def test_automatic_snapshot_delta_must_explain_full_final_amount(data):
    assert reconcile(data)['tokens_in_added'] == 40
    ticket = data[0].get('request',RID)
    marker = next(k for k in ticket['metrics']['tokens_detail'] if '_model_' in k and k.endswith('_usage'))
    ticket['metrics']['tokens_detail'][marker]['tokens_in_added'] -= 1
    data[0].put('request',RID,ticket)
    assert reconcile(data)['status'] == 'deferred'


def test_success_receipt_with_insufficient_counters_defers(data):
    data[-1].extend(call('mcp__gbox__record_request_metrics',{'request_id':RID,'provider':'nous','model':'opus',
                        'tokens_in':5,'tokens_out':2},
                        {'ok':True,'request_id':RID,'metrics':{'tokens_in':4,'tokens_out':1}},cid='short'))
    assert reconcile(data)['status'] == 'deferred'


def test_maintenance_executions_do_not_spend_inference_run_limit(data,tmp_path):
    home = make_home(tmp_path,data)
    with sqlite3.connect(home/'cron/executions.db') as db:
        db.executemany('INSERT INTO executions VALUES(?,?,?,?,?)',[(f'{i:032x}','maintenance','completed',
            f'1970-01-01T00:{3+i//60:02}:{i%60:02}+00:00',f'1970-01-01T00:{3+i//60:02}:{i%60:02}+00:00') for i in range(80)])
        db.execute('INSERT INTO executions VALUES(?,?,?,?,?)',('f'*32,'inbox','running',
            '1970-01-01T00:05:00+00:00',None))
    result = accounting.reconcile_completed(data[0],home,limit=1)
    assert len(result) == 1 and result[0]['run_id'] == RUN and result[0]['tokens_in_added'] == 40


def test_candidate_discovery_remains_bounded(data,tmp_path):
    home = make_home(tmp_path,data)
    with sqlite3.connect(home/'cron/executions.db') as db:
        db.executemany('INSERT INTO executions VALUES(?,?,?,?,?)',[(f'{i:032x}','maintenance','completed',
            f'1970-01-01T00:{3+i//60:02}:{i%60:02}+00:00',f'1970-01-01T00:{3+i//60:02}:{i%60:02}+00:00') for i in range(101)])
    assert accounting.reconcile_completed(data[0],home,limit=1) == []
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 0


def test_injected_api_matches_real_metrics_endpoint_schema(cfg,data,api_lock):
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app = create_app(cfg)
    app.state.store.put('request',RID,data[0].get('request',RID))
    client = TestClient(app,headers={'authorization':'Bearer '+cfg.token()})
    posted = []
    def api(path,body=None):
        if body is not None:
            posted.append(copy.deepcopy(body))
        response = client.get(path) if body is None else client.post(path,json=body)
        response.raise_for_status()
        return response.json()
    try:
        result = accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)
        assert result['tokens_in_added'] == 40 and result['tokens_out_added'] == 9
        assert all(body['tools'] == {} and body['turns'] == 0 and 'duration_s' not in body for body in posted)
        after = app.state.store.get('request',RID)
        assert after['status'] == 'in_progress' and after['solved_by'] is None
        assert after['metrics']['agent_seconds'] == 21.5 and after['metrics']['turns'] == 4
        assert after['metrics']['tokens_detail']['token_count_unavailable'] == 3
        assert {(r['provider'],r['model'],r['tokens_in'],r['tokens_out']) for r in after['metrics']['usage_by_solver']} == {
            ('nous','opus',33,5),('openrouter','vision',7,4)}
        assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['status'] == 'already_recorded'
        assert len(posted) == 3
    finally:
        client.close()
        app.state.store.db.close()


def test_real_empty_primary_task_with_named_vision_is_not_missing_identity(data):
    data[3][0]['task'] = ''
    records = accounting._records(*data[1:4])
    primary = next(r for r in records if r['task'] == 'primary')
    assert primary['ledger_task'] == ''
    assert primary['tokens_in_including_caches'] == 33
    assert next(r for r in records if r['task'] == 'vision')['tokens_in_including_caches'] == 7
    assert reconcile(data)['tokens_in_added'] == 40


def test_empty_primary_task_still_checks_primary_session_totals(data):
    data[3][0]['task'] = ''
    data[2]['input_tokens'] = 11
    assert reconcile(data)['status'] == 'deferred'
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 0


@pytest.mark.parametrize('bad',[None,False,7])
def test_null_or_invalid_task_is_not_normalized(data,bad):
    data[3][0]['task'] = bad
    assert reconcile(data)['status'] == 'deferred'


def test_empty_and_named_primary_duplicate_identity_defers(data):
    duplicate = dict(data[3][0],task='')
    data[3].append(duplicate)
    assert reconcile(data)['status'] == 'deferred'


def test_write_intent_fsync_then_replace_then_directory_before_post(data,api_lock,monkeypatch):
    events = []
    real_fsync,real_replace = accounting.os.fsync,accounting.os.replace
    def fsync(fd):
        events.append('file_fsync')
        real_fsync(fd)
    def replace(source,target):
        assert events[-1] == 'file_fsync'
        events.append('replace')
        real_replace(source,target)
    def directory(path):
        events.append('directory_fsync' if events and events[-1] == 'replace' else 'directory_create_fsync')
    monkeypatch.setattr(accounting.os,'fsync',fsync)
    monkeypatch.setattr(accounting.os,'replace',replace)
    monkeypatch.setattr(accounting,'_fsync_directory',directory)
    base,state = fake_api(data[0])
    def api(path,body=None):
        if body is not None:
            assert events[-1] == 'directory_fsync'
            events.append('post')
        return base(path,body)
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['tokens_in_added'] == 40
    assert state['posts'] == 3


def test_write_intent_fsync_failure_prevents_any_post(data,api_lock,monkeypatch):
    api,state = fake_api(data[0])
    def fail(fd): raise OSError('disk write failed')
    monkeypatch.setattr(accounting.os,'fsync',fail)
    with pytest.raises(OSError): accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)
    assert state['posts'] == 0 and data[0].get('request',RID)['metrics']['tokens_in'] == 0


def test_failed_journal_clear_retains_pending_committed_write(data,api_lock,monkeypatch):
    api,state = fake_api(data[0])
    real_fsync = accounting.os.fsync
    times = []
    def fsync(fd):
        times.append(fd)
        if len(times) == 2: raise OSError('clear fsync failed')
        real_fsync(fd)
    # Mock directory support so the second fsync is the next file, on all OSes.
    monkeypatch.setattr(accounting,'_fsync_directory',lambda path:None)
    monkeypatch.setattr(accounting.os,'fsync',fsync)
    with pytest.raises(OSError): accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)
    journal = json.loads((api_lock/(RUN+'.json')).read_text())
    assert journal['pending'] and state['posts'] == 1
    assert data[0].get('request',RID)['metrics']['tokens_in'] == 33
    monkeypatch.setattr(accounting.os,'fsync',real_fsync)
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=api_lock)['tokens_in_added'] == 7
    assert state['posts'] == 3 and data[0].get('request',RID)['metrics']['tokens_in'] == 40


def test_new_journal_directory_entries_synced_before_first_post(data,tmp_path,api_lock,monkeypatch):
    directory = tmp_path/'new'/'nested'/'accounting'
    synced = []
    monkeypatch.setattr(accounting,'_fsync_directory',lambda path:synced.append(Path(path)))
    base,state = fake_api(data[0])
    def api(path,body=None):
        if body is not None and state['posts'] == 0:
            assert tmp_path in synced
            assert tmp_path/'new' in synced
            assert tmp_path/'new'/'nested' in synced
            assert directory in synced
        return base(path,body)
    assert accounting.reconcile_run_api(api,*data[1:],state_dir=directory)['tokens_in_added'] == 40
