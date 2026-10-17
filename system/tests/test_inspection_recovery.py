import copy
import json
import sqlite3
import time
import pytest
from gbox.store import Store
from gbox import inspection_builds as I
from gbox.inspection_recovery import normalize_reservation, main


@pytest.fixture
def fixture(tmp_path):
    store = Store(tmp_path/'data')
    source = tmp_path/'system'
    (source/'gbox').mkdir(parents=True)
    (source/'gbox/writer.py').write_text('owned reviewed writer')
    sources = I.dependencies(['gbox/writer.py'], root=source)
    policy = I.settings({'enabled': True, 'node': 'BuildPC'})
    plan = {'game_id': 'game', 'enabled': True, 'reviewed': True, 'revision': 'revision',
            'dependencies': ['gbox/writer.py'], 'feedback_ack': {}, 'requests_ack': {},
            'recipe': {'tool': 'characters', 'input': {'op':'cast_swap','target_game':'game','source':'mario,sonic'}}}
    rid = I.digest({'plan':plan['revision'], 'sources':sources})
    run = {'id':rid, 'game_id':'game', 'plan_revision':'revision', 'sources':sources,
           'input_digest': I.digest(I.build_input(plan,rid,normalized=False)), 'node':'BuildPC', 'job_id':'job'}
    job = {'id':'job','tool':'characters','state':'queued','require_worker':'worker',
           'worker_id':None,'started':None,'finished':None,'output':None,'receipt_id':None,
           'input':I.build_input(plan,rid), 'origin':{'inspection_run':rid},'parent_request_id':'parent'}
    worker = {'id':'worker','name':'BuildPC','last_seen':time.time(),'tools':['characters'],'build_sources':sources}
    for kind, key, val in [(I.POLICY,'default',policy),(I.PLAN,'game',plan),(I.RUN,rid,run),('job','job',job),('worker','worker',worker)]:
        store.put(kind,key,val)
    return store,source,plan,run,job,worker


def call(f, **kwargs):
    s,root,p,r,j,w=f
    return normalize_reservation(s.db,j['id'],expected_run=r['id'],expected_digest=r['input_digest'],source_root=root,**kwargs)


def test_preview_never_writes_and_apply_only_normalizes_equivalent_digest(fixture):
    s,root,p,r,j,w=fixture
    assert I.reservation_matches(p,r,j)
    assert I.digest(j['input']) != r['input_digest']  # reason old loaded server refuses it
    result=call(fixture)
    assert result['applied'] is False and result['audit_seq'] is None
    assert s.get(I.RUN,r['id'])==r and s.get('job','job')==j and s.audit_log_last_seq()==0
    result=call(fixture,apply=True)
    assert result['applied'] and result['audit_seq']==1
    after=s.get(I.RUN,r['id'])
    assert after==r|{'input_digest':I.digest(I.build_input(p,r['id']))}
    assert after['input_digest']==I.digest(j['input'])  # strict old guard now accepts same payload
    assert s.get('job','job')==j
    assert s.verify_audit()==(True,1,None)
    evidence=s.audit_for(r['id'])[0]['data']
    assert evidence['before']==r and evidence['after']==after and evidence['job']==j
    with pytest.raises(ValueError):call(fixture,apply=True)
    assert s.audit_log_last_seq()==1


@pytest.mark.parametrize('changes',[{'state':'running'},{'worker_id':'worker'},{'started':0},{'finished':0},
    {'output':{}},{'receipt_id':'done'},{'cancel':True},{'tool':'launch_game'},
    {'origin':{'inspection_run':'different'}},{'require_worker':'different'}])
def test_refuses_claimed_changed_other_or_unpinned_jobs(fixture,changes):
    s,root,p,r,j,w=fixture;s.put('job','job',j|changes)
    with pytest.raises(ValueError):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r and s.audit_log_last_seq()==0


@pytest.mark.parametrize('changes',[{'launch':True},{'source':'different'},{'op':'use'},{'feedback_ack':{'new':1}},{'seed':'changed'}])
def test_never_approves_a_different_job_using_its_own_digest(fixture,changes):
    s,root,p,r,j,w=fixture;s.put('job','job',j|{'input':j['input']|changes})
    with pytest.raises(ValueError):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r and s.audit_log_last_seq()==0


@pytest.mark.parametrize('changes',[{'reviewed':False},{'enabled':False},{'revision':'new'},
    {'recipe':{'tool':'characters','input':{'op':'cast_swap','target_game':'other'}}}])
def test_refuses_stale_or_unreviewed_recipe(fixture,changes):
    s,root,p,r,j,w=fixture;s.put(I.PLAN,'game',p|changes)
    with pytest.raises((ValueError,KeyError)):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r


def test_new_operator_feedback_requires_review(fixture):
    s,root,p,r,j,w=fixture
    s.put('request','new',{'id':'new','body':'New requested change','context':{'game_id':'game'},'messages':[]})
    with pytest.raises(ValueError,match='reviewed'):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r


@pytest.mark.parametrize('changes',[{'last_seen':0},{'last_seen':True},{'last_seen':float('nan')},
    {'last_seen':time.time()+10000},{'name':'other'},{'tools':[]},{'build_sources':{}},{'id':'other'}])
def test_fresh_matching_pinned_worker_required(fixture,changes):
    s,root,p,r,j,w=fixture;s.put('worker','worker',w|changes)
    with pytest.raises(ValueError):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r


def test_current_writer_changes_block_recovery(fixture):
    s,root,p,r,j,w=fixture;(root/'gbox/writer.py').write_text('new writer awaiting review')
    with pytest.raises(ValueError,match='sources changed'):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r


def test_audit_failure_rolls_back_digest(fixture):
    s,root,p,r,j,w=fixture
    s.db.execute("CREATE TRIGGER fixture_fail BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'test'); END")
    s.db.commit()
    with pytest.raises(sqlite3.IntegrityError):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r and s.get('job','job')==j and s.audit_log_last_seq()==0


def test_cli_readonly_default_and_missing_database(fixture,tmp_path,capsys):
    s,root,p,r,j,w=fixture
    args=['--database',str(s.dir/'gbox.sqlite3'),'--job-id','job','--expected-run',r['id'],
          '--expected-digest',r['input_digest'],'--source-root',str(root)]
    main(args)
    assert json.loads(capsys.readouterr().out)['applied'] is False
    assert s.get(I.RUN,r['id'])==r and s.audit_log_last_seq()==0
    missing=tmp_path/'missing.sqlite3';args[1]=str(missing)
    with pytest.raises(sqlite3.OperationalError):main(args)
    assert not missing.exists()


def test_unacknowledged_durable_build_feedback_is_rejected(fixture):
    from gbox import build_feedback as B
    s,root,p,r,j,w=fixture
    s.put(B.KIND,'report',{'id':'report','game_id':'game','revision':1})
    with pytest.raises(ValueError,match='build feedback'):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r and s.audit_log_last_seq()==0


def test_acknowledged_build_feedback_revised_since_plan_is_rejected(fixture):
    from gbox import build_feedback as B
    s,root,p,r,j,w=fixture
    p['feedback_ack']={'report':1}
    j['input']=I.build_input(p,r['id'])
    r['input_digest']=I.digest(I.build_input(p,r['id'],normalized=False))
    s.put(I.PLAN,'game',p);s.put('job','job',j);s.put(I.RUN,r['id'],r)
    s.put(B.KIND,'report',{'id':'report','game_id':'game','revision':1})
    assert call(fixture)['applied'] is False
    s.put(B.KIND,'report',{'id':'report','game_id':'game','revision':2})
    with pytest.raises(ValueError,match='build feedback'):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r and s.audit_log_last_seq()==0


def test_equivalent_payload_cannot_borrow_noncanonical_reservation_id(fixture):
    s,root,p,r,j,w=fixture
    r['id']='f'*64
    r['input_digest']=I.digest(I.build_input(p,r['id'],normalized=False))
    j['origin']['inspection_run']=r['id'];j['input']=I.build_input(p,r['id'])
    s.put(I.RUN,r['id'],r);s.put('job','job',j)
    with pytest.raises(ValueError,match='canonical'):call(fixture,apply=True)
    assert s.get(I.RUN,r['id'])==r and s.audit_log_last_seq()==0
