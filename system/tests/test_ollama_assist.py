import copy
import json
import time
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gbox import ollama_assist as O
from gbox.registry import ToolUnavailable
from tests.test_inspection_builds import Store

GIB = 2**30


def rig():
    s = Store()
    w = dict(id='w', name='PC', os='windows', idle_seconds=600, active_jobs=0,
             resources=dict(sampled_at=time.time(), cpu_percent=20, memory_percent=40,
                            memory_available_bytes=32*GIB, gpus=[dict(name='GPU', utilization_percent=10,
                            memory_total_mb=8192, memory_used_mb=1000)]),
             ollama=dict(available=True, sampled_at=time.time(), models=[dict(name='coder:3b', size=2*GIB, digest='sha')]))
    s.put('worker', 'w', w)
    p = O.policy(dict(enabled=True, model='coder:3b'))
    s.put('setting', O.SETTING, {'nodes': {'PC': p}})
    return s, w, p


@pytest.mark.parametrize('value', [dict(enabled=1), dict(enabled=True), dict(model='x-cloud'),
    dict(model='https://remote'), dict(context_tokens=1), dict(reserve_gib=0), dict(model_budget_gib=100),
    dict(max_output_tokens=4096,context_tokens=2048)])
def test_policy_rejects_invalid(value):
    with pytest.raises(ValueError): O.policy(value)


def test_defaults_off_and_name_survives_reconnect():
    assert O.policy()['enabled'] is False
    s,w,p=rig(); w['id']='new-worker'
    assert O.selected(s,w)==p
    assert O.reason(s,w) is None


@pytest.mark.parametrize('change,match', [
    ({'idle_seconds':0},'input'), ({'active_jobs':1},'current job'),
    ({'ollama':{}},'inventory'),
    ({'resources':{'sampled_at':0}},'telemetry')])
def test_admission_waits(change,match):
    s,w,p=rig(); w.update(change)
    assert match in O.reason(s,w)


def test_memory_model_vram_and_shared_budget():
    s,w,p=rig(); w['resources']['memory_available_bytes']=10*GIB
    assert 'RAM' in O.reason(s,w)
    w['resources']['memory_available_bytes']=32*GIB
    w['ollama']['models'][0]['size']=7*GIB
    assert 'weight budget' in O.reason(s,w)
    w['ollama']['models'][0]['size']=2*GIB
    w['resources']['gpus'][0]['memory_used_mb']=7000
    assert 'GPU memory' in O.reason(s,w)
    w['resources']['gpus'][0]['utilization_percent']=90
    assert '90%' in O.reason(s,w)


def test_gaming_mode_disabled_policy_and_human_game():
    s,w,p=rig(); s.put('setting','background_testing',{'excluded':['PC']})
    assert 'Gaming mode' in O.reason(s,w)
    s.put('setting','background_testing',{})
    s.put('session','w-game',{'session_id':'w-game','state':'running'})
    assert 'Human gameplay' in O.reason(s,w)
    s.put('session','w-game',{'session_id':'w-game','state':'ended'})
    s.put('setting',O.SETTING,{})
    assert 'disabled' in O.reason(s,w)


def test_inventory_probe_is_read_only_and_fails_closed(monkeypatch):
    calls=[]
    def get(url,**kw):
        calls.append(url)
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'models':[{'name':'coder','size':123}]})
    monkeypatch.setattr(O.httpx,'get',get)
    assert O.inventory()['models'][0]['size']==123
    assert calls==[O.URL+'/api/tags']
    def fail(*a,**kw):raise O.httpx.ConnectError('offline')
    monkeypatch.setattr(O.httpx,'get',fail)
    assert O.inventory()['available'] is False


def test_authenticated_api_policy_and_running_job_permit():
    s,w,p=rig(); app=FastAPI(); O.install(app,s,lambda:'test'); c=TestClient(app)
    assert c.get('/api/ollama-assist').json()['workers'][0]['policy']==p
    assert c.post('/api/ollama-assist/w',json={'enabled':True,'model':'coder:3b','reserve_gib':12}).status_code==200
    assert c.get('/api/ollama-assist/permit/w?job_id=j').status_code==409
    s.put('job','j',dict(id='j',tool='ollama_assist',input={'op':'analyze'},state='running',worker_id='w'))
    # Own inference can occupy GPU; the admission budget must not cancel it just for doing useful GPU work.
    w['resources']['gpus'][0]['utilization_percent']=99;s.put('worker','w',w)
    assert c.get('/api/ollama-assist/permit/w?job_id=j').json()['reason'] is None
    assert c.post('/api/ollama-assist/w',json={'enabled':False}).status_code==200
    assert c.get('/api/ollama-assist/permit/w?job_id=j').json()['reason']


def stream_rig(monkeypatch,remote=False):
    _,_,p=rig(); artifacts=[]; payloads=[]
    monkeypatch.setattr(O,'authorization',lambda ctx:p)
    monkeypatch.setattr(O,'inventory',lambda:{'models':[{'name':'coder:3b','digest':'sha'}]})
    monkeypatch.setattr(O.httpx,'post',lambda *a,**k:SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'remote_host':'host'} if remote else {}))
    class Stream:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def raise_for_status(self):pass
        def iter_lines(self):
            yield json.dumps({'message':{'content':'Possible function purpose.'}})
            yield json.dumps({'done':True,'prompt_eval_count':42,'eval_count':8})
    class Client(Stream):
        def __init__(self,**kw):pass
        def stream(self,*a,**kw):payloads.append(kw['json']);return Stream()
    monkeypatch.setattr(O.httpx,'Client',Client)
    from gbox import worker
    monkeypatch.setattr(worker,'user_idle_seconds',lambda:600)
    ctx=SimpleNamespace(worker='w',artifact=lambda *a:artifacts.append(a),progress=lambda *a:None)
    return ctx,artifacts,payloads


def test_stream_receipt_token_counts_and_no_tools(monkeypatch):
    ctx,a,p=stream_rig(monkeypatch)
    res=O.analyze(O.AssistIn(prompt='int f(){return 1;}'),ctx)
    assert res['status']=='hypothesis' and res['usage']['prompt_eval_count']==42
    assert res['digest']=='sha' and a[0][0]=='ollama-analysis.json'
    assert p[0]['keep_alive']==0 and p[0]['options']['num_predict']==1024
    assert 'tools' not in p[0]


def test_remote_alias_and_oversized_evidence_never_infer(monkeypatch):
    ctx,a,p=stream_rig(monkeypatch,remote=True)
    with pytest.raises(ToolUnavailable,match='Remote'):O.analyze(O.AssistIn(prompt='code'),ctx)
    assert not p
    with pytest.raises(ValueError,match='too large'):O.analyze(O.AssistIn(prompt='x'*10000),ctx)
    assert not p and not O.LOCK.locked()


def test_operator_return_cancels_before_inference(monkeypatch):
    import os
    if os.name!='nt':pytest.skip('Windows input telemetry')
    ctx,a,p=stream_rig(monkeypatch)
    from gbox import worker
    monkeypatch.setattr(worker,'user_idle_seconds',lambda:0)
    with pytest.raises(ToolUnavailable,match='Operator returned'):O.analyze(O.AssistIn(prompt='code'),ctx)
    assert not p and not a and not O.LOCK.locked()


def test_server_claim_mandatory_even_for_nonagent_jobs(cfg):
    from gbox.server import create_app
    app=create_app(cfg); s=app.state.store
    _,w,p=rig(); w.update(tools=['ollama_assist'],unavailable={},last_seen=time.time())
    s.put('worker','w',w)
    c=TestClient(app,headers={'Authorization':f'Bearer {cfg.token()}'})
    j=c.post('/api/jobs',json={'tool':'ollama_assist','input':{'prompt':'int f(){return 1;}'},'require_worker':'w'})
    assert j.status_code==200,j.text
    blocked=c.post('/api/workers/w/claim',json={'idle_seconds':600,'active_jobs':0})
    assert blocked.status_code==204
    assert 'disabled' in s.get('job',j.json()['id'])['admission_wait']['reason']
    c.post('/api/ollama-assist/w',json=p).raise_for_status()
    claimed=c.post('/api/workers/w/claim',json={'idle_seconds':600,'active_jobs':0})
    assert claimed.status_code==200,claimed.text
    assert claimed.json()['id']==j.json()['id']


def test_status_discovery_is_not_blocked_by_compute_admission():
    from gbox.background_testing import requires_admission
    assert not requires_admission({'tool':'ollama_assist','input':{'op':'status'},'agent_use':True})
    assert requires_admission({'tool':'ollama_assist','input':{'op':'analyze'},'agent_use':True})


def test_policy_revocation_between_chunks_closes_stream(monkeypatch):
    ctx,a,p=stream_rig(monkeypatch)
    count=[0]
    def auth(ctx):
        count[0]+=1
        if count[0]>=3:raise ToolUnavailable('Gaming mode changed')
        return O.policy(dict(enabled=True,model='coder:3b'))
    monkeypatch.setattr(O,'authorization',auth)
    with pytest.raises(ToolUnavailable,match='Gaming mode'):O.analyze(O.AssistIn(prompt='code'),ctx)
    assert p and not a and not O.LOCK.locked()
