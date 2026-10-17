import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import pytest

from gbox import inventory_recovery as R
from gbox.store import Store

JOB = "f94e6adb36964916"
WORKER = "2fc805cc13f248fb"
NAME = "FixturePC"
SERVER = "http://fixture:8765"


def snapshot(store):
    raw = store.db.execute("SELECT body FROM docs WHERE kind='job' AND id=?",(JOB,)).fetchone()[0]
    return hashlib.sha256(raw.encode()).hexdigest()


@pytest.fixture
def fixture(tmp_path):
    now=time.time(); store=Store(tmp_path/'data')
    job={'id':JOB,'tool':'tasks','input':{'op':'list','pid':None},'state':'running','worker_id':WORKER,
         'require_worker':WORKER,'created':now-700,'started':now-600,'finished':None,'output':None,'receipt_id':None}
    worker={'id':WORKER,'name':NAME,'last_seen':now,'active_jobs':0,'pending_results':0,'tools':['tasks'],
            'features':['independent_heartbeat','durable_result_delivery']}
    store.put('job',JOB,job);store.put('worker',WORKER,worker)
    store.audit('operator','job.submit',JOB,{'tool':'tasks','input':job['input']})
    store.audit('worker:'+NAME,'job.claim',JOB,{'worker':WORKER})
    config=str(tmp_path/'gbox.toml')
    proc={'pid':10,'ppid':1,'created':now-800,'exe':'python.exe','name':NAME,'server':SERVER,'config':config}
    ns=hashlib.sha256((SERVER+'\0'+NAME).encode()).hexdigest()[:24]
    evidence={'version':1,'job_id':JOB,'worker_id':WORKER,'worker_name':NAME,'host':NAME,'server':SERVER,
              'runtime':str(tmp_path/'runtime'),'config':config,'configuration_sha256':{config:'a'*64},
              'observed_at':now,'worker_process':proc,'process_chain':[proc],
              'namespaces':[ns],'current_namespace':ns,'target_filename':hashlib.sha256(JOB.encode()).hexdigest()+'.json',
              'target_paths':[],'pending_paths':[],'old_temporary_evidence':[]}
    return store,job,worker,evidence,now


def call(fixture,**kw):
    store,job,worker,evidence,now=fixture
    params=dict(expected_job_sha256=snapshot(store),expected_worker=WORKER,evidence=evidence,now=now)
    params.update(kw)
    return R.retire_inventory(store.db,JOB,**params)


def test_preview_is_readonly_and_apply_preserves_scope_and_audits_atomically(fixture):
    store,job,worker,evidence,now=fixture
    before=store.db.execute("SELECT body FROM docs WHERE kind='job' AND id=?",(JOB,)).fetchone()[0]
    preview=call(fixture)
    assert not preview['applied'] and preview['audit_seq'] is None and store.get('job',JOB)==job
    assert store.audit_log_last_seq()==2
    result=call(fixture,apply=True)
    after=store.get('job',JOB)
    assert result['applied'] and result['audit_seq']==3 and after==result['after']
    assert after['state']=='failed' and after['finished']==now and after['input']==job['input']
    assert not after.get('cancel') and after.get('output') is None and after.get('receipt_id') is None
    assert set(after)-set(job)=={'error','inventory_timeout'}
    assert store.all('receipt')==[] and store.verify_audit()==(True,3,None)
    assert store.audit_for(JOB)[-1]['data']['local_evidence']==evidence
    with pytest.raises(ValueError):call(fixture,apply=True)
    assert store.audit_log_last_seq()==3


@pytest.mark.parametrize('change',[
    {'tool':'launch_game'},{'input':{'op':'kill','pid':10}},{'input':{'op':'list','pid':10}},
    {'input':{'op':'list','pid':None,'extra':1}},{'state':'queued'},{'state':'succeeded'},
    {'worker_id':'other'},{'require_worker':'other'},{'cancel':True},{'finished':0},
    {'output':{}},{'receipt_id':'result'},{'result_sha256':'a'*64},{'result_acceptance':'pending'},
    {'result_state':'succeeded'},{'error':'pending failure'},{'started':True},{'started':float('nan')},
])
def test_only_exact_uncompleted_readonly_inventory_is_eligible(fixture,change):
    store,job,*_=fixture;store.put('job',JOB,job|change)
    before=snapshot(store)
    with pytest.raises(ValueError):call(fixture,apply=True)
    assert snapshot(store)==before and store.audit_log_last_seq()==2


def test_snapshot_change_and_young_request_are_rejected(fixture):
    store,job,worker,evidence,now=fixture
    old=snapshot(store);store.put('job',JOB,job|{'created':job['created']-1})
    with pytest.raises(ValueError,match='snapshot'):call(fixture,expected_job_sha256=old,apply=True)
    store.put('job',JOB,job|{'started':now-299})
    with pytest.raises(ValueError,match='overdue'):call(fixture,apply=True)


@pytest.mark.parametrize('kind',['receipt','late_result'])
def test_any_durable_result_blocks_retirement(fixture,kind):
    store,*_=fixture;store.put(kind,'evidence',{'job_id':JOB})
    with pytest.raises(ValueError,match='result evidence'):call(fixture,apply=True)
    assert store.get('job',JOB)['state']=='running'


@pytest.mark.parametrize('change',[
    {'active_jobs':1},{'active_jobs':False},{'pending_results':1},{'pending_results':None},
    {'last_seen':0},{'last_seen':True},{'last_seen':float('nan')},{'tools':[]},{'features':[]},
])
def test_fresh_idle_durable_worker_evidence_is_required(fixture,change):
    store,job,worker,*_=fixture;store.put('worker',WORKER,worker|change)
    with pytest.raises(ValueError):call(fixture,apply=True)
    assert store.get('job',JOB)['state']=='running'


def test_stale_or_duplicate_worker_blocks(fixture):
    store,job,worker,evidence,now=fixture
    with pytest.raises(ValueError):call(fixture,now=now+31,apply=True)
    store.put('worker','other',worker|{'id':'other'})
    with pytest.raises(ValueError,match='Another fresh'):call(fixture,apply=True)


@pytest.mark.parametrize('change',[
    {'version':True},{'job_id':'other'},{'worker_id':'other'},{'worker_name':'other'},{'host':'other'},
    {'observed_at':0},{'observed_at':float('nan')},{'target_paths':['result']},{'pending_paths':['unsettled']},
    {'target_filename':'other.json'},{'namespaces':[]},{'current_namespace':'a'*24},
    {'process_chain':[]},{'configuration_sha256':{}},
])
def test_local_evidence_cannot_be_stale_incomplete_or_for_another_job(fixture,change):
    evidence=copy.deepcopy(fixture[3]);evidence.update(change)
    with pytest.raises(ValueError):call(fixture,evidence=evidence,apply=True)
    assert fixture[0].get('job',JOB)['state']=='running'


def test_multiple_processes_or_worker_born_after_claim_are_rejected(fixture):
    evidence=copy.deepcopy(fixture[3]);evidence['process_chain'].append(evidence['worker_process']|{'pid':11})
    with pytest.raises(ValueError,match='actual worker'):call(fixture,evidence=evidence,apply=True)
    evidence=copy.deepcopy(fixture[3]);evidence['worker_process']['created']=fixture[4]-100
    with pytest.raises(ValueError,match='identity'):call(fixture,evidence=evidence,apply=True)


def test_audit_history_and_atomic_failure_are_guarded(fixture):
    store,*_=fixture
    store.db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit BEGIN SELECT RAISE(ABORT,'fixture'); END")
    store.db.commit()
    with pytest.raises(sqlite3.IntegrityError):call(fixture,apply=True)
    assert store.get('job',JOB)['state']=='running' and store.audit_log_last_seq()==2
    store.db.execute('DROP TRIGGER fail_audit');store.db.commit()
    store.audit('other','job.failed',JOB,{})
    with pytest.raises(ValueError,match='audit history'):call(fixture,apply=True)


def test_late_success_is_evidence_only_after_retirement(fixture,tmp_path):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    store,job,worker,evidence,now=fixture
    cfg=Config(data_dir=store.dir,cache_dir=tmp_path/'cache')
    app=create_app(cfg);client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token()})
    call(fixture,apply=True)
    before=store.get('job',JOB)
    result={'job_id':JOB,'ok':True,'output':{'result':{'tasks':[],'totals':{}}},'log':['late inventory'],'artifacts':[]}
    response=client.post('/api/workers/'+WORKER+'/result',json=result)
    assert response.status_code==200
    ack=response.json();assert ack['accepted'] and ack['late'] and ack['state']=='failed'
    assert store.get('job',JOB)==before and store.all('receipt')==[]
    [late]=store.all('late_result');assert late['job_id']==JOB and late['job_state']=='failed' and late['ok']
    assert client.post('/api/workers/'+WORKER+'/result',json=result).json()==ack
    assert len(store.all('late_result'))==1


def observation_fixture(tmp_path,monkeypatch):
    name='FixturePC';runtime=tmp_path/'runtime';runtime.mkdir()
    config=tmp_path/'gbox.toml';config.write_text('[runtime_dirs]\nlinux = '+json.dumps(str(runtime))+'\n')
    monkeypatch.setattr(R.platform,'node',lambda:name);monkeypatch.setattr(R.platform,'system',lambda:'Linux')
    proc={'pid':10,'ppid':1,'created':time.time()-1000,'exe':'python','name':name,'server':SERVER,'config':str(config)}
    monkeypatch.setattr(R,'_processes',lambda *a:([proc],proc))
    import psutil
    monkeypatch.setattr(psutil,'Process',lambda pid:type('P',(),{'create_time':lambda self:proc['created']})())
    ns=hashlib.sha256((SERVER+'\0'+name).encode()).hexdigest()[:24]
    directory=runtime/'worker-results'/ns;(directory/'acknowledged').mkdir(parents=True)
    def observe():return R.observe_worker(runtime,config,SERVER,name,WORKER,JOB,expected_pid=10)
    return directory,observe


def test_observation_reads_all_namespaces_and_target_states(tmp_path,monkeypatch):
    directory,observe=observation_fixture(tmp_path,monkeypatch)
    assert observe()['target_paths']==[] and observe()['pending_paths']==[]
    other=directory.parent/('a'*24);(other/'acknowledged').mkdir(parents=True)
    filename=hashlib.sha256(JOB.encode()).hexdigest()+'.json'
    target=other/'acknowledged'/filename;target.write_text('{}')
    assert observe()['target_paths']==[str(target)]
    pending=directory/(filename+'.inflight.tmp');pending.write_text('partial')
    result=observe();assert str(pending) in result['pending_paths'] and str(pending) in result['target_paths']


def test_observation_rejects_redirected_runtime_or_namespace(tmp_path,monkeypatch):
    directory,observe=observation_fixture(tmp_path,monkeypatch)
    config=tmp_path/'gbox.toml';config.write_text('[runtime_dirs]\nlinux = '+json.dumps(str(tmp_path))+'\n')
    with pytest.raises(ValueError,match='runtime differs'):observe()


@pytest.mark.parametrize('label',['acknowledged','rejected','refused-evidence'])
def test_target_result_is_found_in_every_archive_state(tmp_path,monkeypatch,label):
    directory,observe=observation_fixture(tmp_path,monkeypatch)
    archive=directory/label;archive.mkdir(exist_ok=True)
    filename=hashlib.sha256(JOB.encode()).hexdigest()+'.'+('a'*32)+'.json'
    target=archive/filename;target.write_text('{}')
    assert str(target) in observe()['target_paths']


@pytest.mark.parametrize('where',['root','namespace','acknowledged','refused-evidence'])
def test_junctions_are_rejected_without_following_them(tmp_path,monkeypatch,where):
    directory,observe=observation_fixture(tmp_path,monkeypatch)
    path={'root':directory.parent,'namespace':directory}.get(where,directory/where)
    path.mkdir(exist_ok=True)
    monkeypatch.setattr(Path,'is_junction',lambda self:self==path,raising=False)
    with pytest.raises(ValueError):observe()


def temporary_record(directory,job_id='a'*16,age=1000):
    result={'job_id':job_id,'ok':True,'output':{},'error':None,'log':[],'artifacts':[]}
    record={'version':1,'server':SERVER,'name':NAME,'worker_id':WORKER,'result':result,
            'result_sha256':R._digest(result),'created':time.time()-age,'status':'pending'}
    path=directory/(hashlib.sha256(job_id.encode()).hexdigest()+'.json.'+'b'*32+'.tmp')
    path.write_text(json.dumps(record));import os;os.utime(path,(time.time()-age,time.time()-age))
    return path,record


def test_old_unrelated_temporaries_are_preserved_with_hash_and_identity(tmp_path,monkeypatch,fixture):
    directory,observe=observation_fixture(tmp_path,monkeypatch)
    path,record=temporary_record(directory)
    raw=path.read_bytes();evidence=observe()
    assert evidence['pending_paths']==[] and evidence['target_paths']==[]
    [item]=evidence['old_temporary_evidence']
    assert item['file_sha256']==hashlib.sha256(raw).hexdigest() and item['job_id']==record['result']['job_id']
    assert path.read_bytes()==raw
    fixture[3]['old_temporary_evidence']=[item]
    assert not call(fixture)['applied']
    item['mtime']=fixture[1]['started']+1
    with pytest.raises(ValueError,match='before this claim'):call(fixture,apply=True)


@pytest.mark.parametrize('change',['fresh','wrong_id','bad_digest','partial','unknown','oversized'])
def test_unsettled_or_unidentified_temp_blocks_observation(tmp_path,monkeypatch,change):
    directory,observe=observation_fixture(tmp_path,monkeypatch)
    path,record=temporary_record(directory,age=1 if change=='fresh' else 1000)
    if change=='wrong_id':record['result']['job_id']='b'*16;path.write_text(json.dumps(record))
    if change=='bad_digest':record['result_sha256']='c'*64;path.write_text(json.dumps(record))
    if change=='partial':path.write_text('{')
    if change=='unknown':path.rename(directory/'unknown.tmp')
    if change=='oversized':monkeypatch.setattr(R,'MAX_TEMP_BYTES',8)
    with pytest.raises(ValueError):observe()


def test_windows_stat_and_fstat_creation_time_difference_is_not_a_content_change(tmp_path,monkeypatch):
    from types import SimpleNamespace
    directory,observe=observation_fixture(tmp_path,monkeypatch)
    path,record=temporary_record(directory)
    original=R.os.fstat
    def fstat(fd):
        observed=original(fd)
        fields={k:getattr(observed,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode','st_mtime')}
        fields['st_ctime_ns']+=123
        return SimpleNamespace(**fields)
    monkeypatch.setattr(R.os,'fstat',fstat)
    assert observe()['old_temporary_evidence'][0]['job_id']==record['result']['job_id']
