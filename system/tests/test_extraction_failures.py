import copy
from concurrent.futures import ThreadPoolExecutor

import pytest

from gbox import extraction_failures as E, hermes_work_queue as Q
from gbox.store import Store, canon, sha256

GID = 'a' * 16


def setup(tmp_path):
    store = Store(tmp_path)
    store.upsert_catalog([{'game_id': GID, 'title': 'Exact owned game', 'platform': 'xbox',
                          'source_paths': ['owned.iso'], 'format': 'iso'}])
    return store


def add(store, jid='b' * 16, *, result=None, state='succeeded', op='collect', **changes):
    result = {'status': 'unsupported', 'game_id': GID, 'message': 'no model reader'} if result is None else result
    job = {'id': jid, 'tool': 'characters', 'input': {'op': op, 'game_id': GID},
           'state': state, 'worker_id': 'actual-worker', 'receipt_id': jid + '-receipt',
           'output': {'result': result}, 'finished': 20, 'started': 10, 'result_acceptance': 'complete'}
    job.update(changes)
    store.put('job', jid, job)
    store.put('receipt', job['receipt_id'], {'id': job['receipt_id'], 'job_id': jid, 'tool': 'characters',
        'worker_id': job['worker_id'], 'started': 10, 'finished': 20,
        'input_sha256': sha256(canon(job['input'])), 'output_sha256': sha256(canon(job['output']))})
    return job


def test_unsupported_creates_actionable_offline_request_and_bound_receipt(tmp_path):
    s = setup(tmp_path)
    s.put('request', 'parent', {'id': 'parent', 'number': 1, 'status': 'open', 'completed': None})
    j = add(s, parent_request_id='parent')
    before = copy.deepcopy(j)
    event = E.observe(s, j['id'])
    r = s.get('request', event['request_id'])
    assert r['parent_request_id'] == 'parent' and r['status'] == 'open' and r['completed'] is None
    assert r['source'] == 'characters' and r['context']['extraction_engineering'] is True
    assert r['context']['resolution_dispatch'] == 'hermes_queue'
    assert all(t in r['body'] for t in ('REA/Ghidra', 'isolated workspace', 'independently validate', 'do not launch'))
    assert event['evidence']['receipt_id'] == j['receipt_id']
    assert event['evidence']['source']['reported_source_sha256'] is None
    assert event['evidence']['worker_id'] == 'actual-worker'
    assert s.get('job', j['id']) == before
    assert s.get('request', 'parent')['completed'] is None
    assert s.verify_audit()[0]


def test_concurrent_duplicate_delivery_and_repeated_failure_share_one_task(tmp_path):
    s = setup(tmp_path); j = add(s)
    with ThreadPoolExecutor(max_workers=6) as pool:
        events = list(pool.map(lambda _: E.observe(s, j['id']), range(20)))
    assert len({e['request_id'] for e in events}) == 1
    r = s.get('request', events[0]['request_id'])
    assert len(r['messages']) == 1
    assert len(s.all(E.EVENT)) == 1
    j2 = add(s, 'c' * 16)
    e2 = E.observe(s, j2['id'])
    assert e2['request_id'] == r['id']
    assert len(s.get('request', r['id'])['messages']) == 2
    assert len(s.all(E.EVENT)) == 2
    assert s.verify_audit()[0]


@pytest.mark.parametrize('result', [
    {'status': 'complete', 'entries': [{'verified': True, 'retargetable': True}]},
    {'status': 'partial', 'roster_complete': True, 'scope': {'coverage': 'subset'},
     'entries': [{'verified': True, 'retargetable': True}]},
    {'status': 'in_collection'}, {'status': 'extracted'}, {'status': 'not_found'},
])
def test_success_subset_and_wrong_picture_point_are_not_format_failures(tmp_path, result):
    s = setup(tmp_path); j = add(s, result=result)
    assert E.observe(s, j['id']) is None
    assert not s.all('request') and not s.all(E.EVENT)


@pytest.mark.parametrize('change', [{'state': 'queued'}, {'state': 'running'}, {'cancel': True},
    {'cancel_requested': True}, {'error': 'cancelled by the operator'}, {'tool': 'launch_game'}])
def test_active_cancelled_and_other_tools_do_not_escalate(tmp_path, change):
    s = setup(tmp_path); j = add(s, **change)
    assert E.observe(s, j['id']) is None
    assert not s.all('request')


@pytest.mark.parametrize('status,row', [('partial', {'slug': 'claire', 'verified': False, 'error': '19 parts, 15 bones'}),
    ('partial', {'slug': 'rig', 'verified': True, 'retargetable': False}),
    ('complete', {'slug': 'contradiction', 'status': 'failed'})])
def test_failed_or_unmapped_entries_escalate_even_if_outer_job_succeeded(tmp_path, status, row):
    s = setup(tmp_path); j = add(s, result={'status': status, 'entries': [row]})
    e = E.observe(s, j['id'])
    assert e['evidence']['issue']['failed_entry_count'] == 1
    assert e['evidence']['issue']['failed_entries'][0]['slug'] == row['slug']


@pytest.mark.parametrize('field,value', [('input_sha256','f' * 64), ('output_sha256','f' * 64),
    ('worker_id','other'), ('job_id','other'), ('tool','other')])
def test_mismatching_receipt_never_creates_work(tmp_path, field, value):
    s = setup(tmp_path); j = add(s)
    r = s.get('receipt', j['receipt_id']);r[field] = value;s.put('receipt', r['id'], r)
    with pytest.raises(ValueError, match='receipt'):
        E.observe(s, j['id'])
    assert not s.all('request') and not s.all(E.EVENT) and not s.db.in_transaction


def test_ambiguous_game_identity_is_rejected(tmp_path):
    s = setup(tmp_path);j = add(s, result={'status': 'unsupported', 'game_id': 'd' * 16})
    with pytest.raises(ValueError, match='unambiguous'):
        E.observe(s, j['id'])
    assert not s.all('request')


def test_source_selection_changes_and_operator_closed_requests_are_preserved(tmp_path):
    s=setup(tmp_path);first=E.observe(s, add(s)['id']);r=s.get('request',first['request_id'])
    r.update(status='done',completed=42);s.put('request',r['id'],r)
    second=E.observe(s,add(s,'c'*16)['id'])
    assert second['request_id'] != r['id'] and s.get('request',r['id']) == r
    third=E.observe(s,add(s,'d'*16,result={'status':'unsupported','source_sha256':'e'*64})['id'])
    assert third['request_id'] != second['request_id']
    assert third['evidence']['source']['reported_source_sha256'] == 'e'*64


def test_atomic_audit_failure_leaves_no_partial_request_or_marker(tmp_path,monkeypatch):
    s=setup(tmp_path);j=add(s)
    def fail(*a,**kw):raise RuntimeError('disk failure')
    monkeypatch.setattr(E,'append_audit',fail)
    with pytest.raises(RuntimeError,match='disk failure'):E.observe(s,j['id'])
    assert not s.all('request') and not s.all(E.EVENT) and not s.all(E.KIND)


def test_engineering_is_in_local_queue_and_does_not_require_emulator(tmp_path):
    s=setup(tmp_path);e=E.observe(s,add(s)['id']);r=s.get('request',e['request_id'])
    data={'items':{}}
    Q.sync(data,{'items':[],'count':0},[r],now=30)
    item=data['items']['inbox:'+r['id']]
    assert item['repair'] and item['extraction_engineering']
    assert not Q.launches_emulator(item)
    prompt=Q._prompt(item)
    assert 'offline native extraction engineering' in prompt
    assert 'Do not launch, capture, pause or stop games' in prompt
    assert 'replacement, animations and controls' not in prompt


def test_actual_worker_result_route_creates_request_once(cfg,monkeypatch):
    from test_worker_results import control
    monkeypatch.setenv('GBOX_HERMES_HOME',str(cfg.data_dir/'hermes'))
    app,plane=control(cfg,jid='collect',tool='characters')
    s=app.state.store
    s.upsert_catalog([{'game_id':GID,'title':'Exact game','platform':'xbox','source_paths':['owned.iso'],'format':'iso'}])
    j=s.get('job','collect');j['input']={'op':'collect','game_id':GID};s.put('job',j['id'],j)
    body={'job_id':'collect','ok':True,'output':{'result':{'status':'unsupported','game_id':GID}}}
    response=plane.post('/api/workers/old-worker/result',json=body)
    assert response.status_code == 200,response.text
    assert response.json()['accepted'] is True
    event=s.get(E.EVENT,'collect');assert event
    assert plane.post('/api/workers/old-worker/result',json=body).json() == response.json()
    assert len(s.all('request')) == 1 and len(s.all('job')) == 1 and not s.all('session')
    assert s.get('receipt',event['receipt_id'])['job_id'] == 'collect'
    assert s.verify_audit()[0]


def test_existing_single_extract_gap_request_is_enriched_not_duplicated(tmp_path):
    s=setup(tmp_path);jid='b'*16
    existing={'id':'gap','number':1,'status':'in_progress','completed':None,'source':'characters',
        'body':'Extract Beat','context':{'game_id':GID,'job_id':jid,'what':'Beat'},'messages':[]}
    s.put('request','gap',existing)
    j=add(s,jid,op='extract',result={'status':'missing','game_id':GID,'request':{'id':'gap'}})
    e=E.observe(s,j['id'])
    assert e['request_id']=='gap' and len(s.all('request'))==1
    r=s.get('request','gap')
    assert r['status']=='in_progress' and r['completed'] is None
    assert r['context']['extraction_engineering'] and len(r['messages'])==1


def test_unrelated_request_id_in_worker_result_cannot_redirect_handoff(tmp_path):
    s=setup(tmp_path)
    unrelated={'id':'other','number':1,'status':'open','source':'app','context':{'game_id':GID},'messages':[]}
    s.put('request','other',unrelated)
    j=add(s,result={'status':'missing','game_id':GID,'request':{'id':'other'}})
    e=E.observe(s,j['id'])
    assert e['request_id']!='other' and s.get('request','other')==unrelated


def test_same_game_different_model_selection_is_separate(tmp_path):
    s=setup(tmp_path)
    a=E.observe(s,add(s,op='extract',input={'op':'extract','game_id':GID,'character':'Beat'})['id'])
    b=E.observe(s,add(s,'c'*16,op='extract',input={'op':'extract','game_id':GID,'character':'Gum'})['id'])
    assert a['request_id']!=b['request_id']


def test_accepted_result_retry_recovers_failed_handoff_without_worker_retry(cfg,monkeypatch):
    from test_worker_results import control
    monkeypatch.setenv('GBOX_HERMES_HOME',str(cfg.data_dir/'hermes'))
    app,plane=control(cfg,jid='collect',tool='characters');s=app.state.store
    s.upsert_catalog([{'game_id':GID,'title':'Exact game','platform':'xbox','source_paths':['owned.iso'],'format':'iso'}])
    j=s.get('job','collect');j['input']={'op':'collect','game_id':GID};s.put('job',j['id'],j)
    body={'job_id':'collect','ok':False,'error':'bad native table'}
    original=E.observe
    def fail(*args,**kwargs):raise RuntimeError('temporary disk unavailable')
    monkeypatch.setattr(E,'observe',fail)
    first=plane.post('/api/workers/old-worker/result',json=body)
    assert first.status_code==200 and first.json()['accepted'] is True
    assert s.get('job','collect')['state']=='failed' and not s.all('request')
    monkeypatch.setattr(E,'observe',original)
    again=plane.post('/api/workers/old-worker/result',json=body)
    assert again.json()==first.json() and len(s.all('request'))==1
    assert len([a for a in s.audit_log() if a['action']=='job.failed'])==1
    assert not s.all('session')
