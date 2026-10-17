import copy
import threading
import time
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gbox import inspection_builds as I
from gbox import background_testing as B
from tests.test_build_quarantine import Memory

GIB=1024**3

class Store(Memory):
    def __init__(self):super().__init__();self.lock=threading.RLock()
    def jobs(self,states=None,**kwargs):return [j for j in self.all('job') if states is None or j['state'] in states]
    def running_sessions(self):return self.all('session')
    def catalog_get(self,gid):return {'game_id':gid,'title':'Fixture'}

def worker(now):
    return {'id':'worker','name':'JAYBUILTFINALE','os':'windows','online':True,'idle_seconds':0,'tools':['characters'],
        'build_sources':{'gbox/cast_swap.py':'a'},'resources':{'sampled_at':now,'cpu_percent':30,'memory_percent':50,
        'memory_total_bytes':64*GIB,'memory_available_bytes':32*GIB,'cache_free_bytes':100*GIB,
        'gpus':[{'name':'Busy GPU','utilization_percent':99}]}}

def plan():
    return {'game_id':'g','enabled':True,'revision':'v1','changed_at':0,'dependencies':['gbox/cast_swap.py'],
            'requires_gpu':False,'recipe':{'tool':'characters','input':{'op':'cast_swap','target_game':'g','source':'sonic','launch':False}},
            'requests_ack':{},'feedback_ack':{}}

def rig():
    s=Store();clock=[1000];w=worker(clock[0]);calls=[]
    s.put(I.POLICY,'default',I.settings({'enabled':True,'debounce_s':10}))
    s.put(I.PLAN,'g',plan())
    def submit(body,key):
        j=body | {'id':f'job{len(calls)}','state':'queued','origin':{'inspection_run':key},'created':clock[0]}
        calls.append(j);s.put('job',j['id'],j);return j
    c=I.Controller(s,lambda:[w],submit,clock=lambda:clock[0],sources=lambda _:copy.deepcopy(w['build_sources']))
    def advance(seconds):clock[0]+=seconds;w['resources']['sampled_at']=clock[0]
    return s,w,c,calls,advance

def test_debounce_local_typing_no_autolaunch_and_unchanged_failure_never_loops():
    s,w,c,calls,advance=rig();c.tick();advance(9);c.tick();assert not calls
    advance(2);c.tick();assert len(calls)==1
    j=calls[0];assert j['require_worker']=='worker' and j['input']['launch'] is False and j['agent_use'] and j['low_priority']
    assert j['input']['mod_name'].startswith('inspect_')
    s.put('job',j['id'],j|{'state':'failed','error':'Writer budget exceeded'})
    for _ in range(3):advance(100);c.tick()
    assert len(calls)==1 and s.get(I.PLAN,'g')['state']=='failed'

def test_source_changes_coalesce_and_supersede_only_queued_work():
    s,w,c,calls,advance=rig();c.tick();advance(11);c.tick();old=calls[0]
    w['build_sources']['gbox/cast_swap.py']='b';c.tick()
    assert s.get('job',old['id'])['state']=='failed'
    w['build_sources']['gbox/cast_swap.py']='c';advance(5);c.tick();advance(11);c.tick()
    assert len(calls)==2 and calls[0]['input']['mod_name']!=calls[1]['input']['mod_name']

def test_feedback_blocks_until_exact_review_and_preserves_running_build():
    s,w,c,calls,advance=rig();c.tick();advance(11);c.tick();j=calls[0]
    s.put('job',j['id'],j|{'state':'running','worker_id':'worker'})
    s.put('request','r',{'id':'r','context':{'game_id':'g'},'body':'Fix shoes','messages':[]})
    c.tick();assert s.get(I.PLAN,'g')['state']=='needs_review' and len(calls)==1
    assert s.get('job',j['id'])['state']=='running'
    p=s.get(I.PLAN,'g');p.update(requests_ack=I.request_revisions(s,'g'),revision='review2');s.put(I.PLAN,'g',p)
    c.tick();advance(11);c.tick();assert len(calls)==1,'do not overlap a running native build'

@pytest.mark.parametrize('case',['ram','disk','unknown','gpu','operator','gaming','cpu'])
def test_headroom_and_gameplay_gate(case):
    s,w,c,calls,advance=rig();p=I.settings({'enabled':True})
    assert I.resource_reason(s,w,p,[],now=1000) is None,'typing and an unrelated busy GPU must not block CPU-only assembly'
    if case=='ram':w['resources']['memory_available_bytes']=10*GIB
    if case=='disk':w['resources']['cache_free_bytes']=10*GIB
    if case=='unknown':del w['resources']['memory_total_bytes']
    if case=='gpu':p=copy.deepcopy(p)
    if case=='operator':s.put('session','worker-play',{'session_id':'worker-play','state':'running','game_id':'g'})
    if case=='gaming':B.set_available(s,w['name'],False)
    if case=='cpu':w['resources']['cpu_percent']=99
    assert I.resource_reason(s,w,p,[],require_gpu=case=='gpu',now=1000)

def test_offline_work_resumes_and_nonbuild_success_is_not_ready():
    s,w,c,calls,advance=rig();w['online']=False;c.tick();advance(11);c.tick();assert not calls
    w['online']=True;c.tick();assert len(calls)==1
    j=calls[0];s.put('job',j['id'],j|{'state':'succeeded','output':{'result':{'status':'needs_source'}}})
    c.tick();assert s.get(I.PLAN,'g')['state']=='blocked'
    s.put('job',j['id'],j|{'state':'succeeded','output':{'result':{'status':'built','mod':'inspect_test'}}})
    c.tick();p=s.get(I.PLAN,'g');assert p['state']=='ready_for_inspection' and p['verification']=='pending gameplay inspection'

def test_ambiguous_submit_is_reconciled_without_duplicate():
    s,w,c,calls,advance=rig();c.tick();advance(11);c.tick()
    r=s.all(I.RUN)[0];r.pop('job_id');s.put(I.RUN,r['id'],r)
    c.tick();assert len(calls)==1 and s.get(I.RUN,r['id'])['job_id']==calls[0]['id']

def test_publish_rejects_unread_requests_and_session_recipes():
    s=Store();app=FastAPI();I.routes(app,s,lambda:'operator',lambda *_:None,lambda:[]);client=TestClient(app)
    s.put('request','r',{'id':'r','context':{'game_id':'g'},'body':'Fix shoes','messages':[]})
    body={'recipe':{'tool':'characters','input':{'op':'cast_swap','target_game':'g','source':'sonic'}},
        'change_id':'geometry correction','dependencies':['gbox/cast_swap.py']}
    assert client.post('/api/inspection-builds/g',json=body).status_code==422
    body['requests_ack']=I.request_revisions(s,'g')
    result=client.post('/api/inspection-builds/g',json=body);assert result.status_code==200,result.text
    assert result.json()['recipe']['input']['launch'] is False
    body['recipe']['input']['session_id']='operator-game'
    assert client.post('/api/inspection-builds/g',json=body).status_code==422
    assert client.post('/api/inspection-builds',json={'memory_gib':0}).status_code==422
    assert client.get('/api/inspection-builds').json()['hard_memory_cap'] is False

def test_dependency_paths_cannot_escape_code_tree(tmp_path):
    (tmp_path/'gbox').mkdir();(tmp_path/'gbox/writer.py').write_text('x=1\r\n')
    assert 'gbox/writer.py' in I.dependencies(['gbox/writer.py'],tmp_path)
    for paths in [[],['gbox/../secret.py'],['gbox/settings.json'],['../secret.py']]:
        with pytest.raises(ValueError):I.dependencies(paths,tmp_path)


def test_claim_rechecks_reservation_loaded_sources_and_recipe(monkeypatch):
    s,w,c,calls,advance=rig();c.tick();advance(11);c.tick();j=calls[0]
    w['resources']['sampled_at']=time.time()
    monkeypatch.setattr(I,'dependencies',lambda _: {'gbox/cast_swap.py':'a'})
    assert I.claim_reason(s,w,j) is None
    assert I.claim_reason(s,w,j | {'input':j['input'] | {'launch':True}})
    w['build_sources']['gbox/cast_swap.py']='old process'
    assert 'refresh' in I.claim_reason(s,w,j)
    w['build_sources']['gbox/cast_swap.py']='a'
    s.put(I.POLICY,'default',I.settings({'enabled':False}))
    assert 'paused' in I.claim_reason(s,w,j)


def test_unknown_telemetry_never_counts_as_headroom():
    s,w,c,calls,advance=rig();p=I.settings()
    for bad in [float('nan'),float('inf'),True,-1]:
        w['resources']['memory_total_bytes']=bad
        assert I.resource_reason(s,w,p,[],now=1000)


def test_draft_enrollment_never_acknowledges_feedback_or_builds():
    s,w,c,calls,advance=rig()
    app=FastAPI();I.routes(app,s,lambda:'operator',lambda *_:None,lambda:[]);client=TestClient(app)
    body={'draft':True,'recipe':{'tool':'characters','input':{'op':'cast_swap','target_game':'g','source':'sonic'}},
          'change_id':'await rig corrections','dependencies':['gbox/cast_swap.py']}
    r=client.post('/api/inspection-builds/g',json=body)
    assert r.status_code==200 and r.json()['state']=='needs_review'
    assert r.json()['requests_ack']=={} and r.json()['reviewed'] is False
    c.tick();advance(100);c.tick();assert not calls


def test_real_submission_defaults_preserve_reservation(monkeypatch):
    from gbox.characters import CharIn
    s,w,c,calls,advance=rig()
    original=c.submit
    def submit(body,key):
        return original(body | {'input':CharIn.model_validate(body['input']).model_dump(mode='json')},key)
    c.submit=submit;c.tick();advance(11);c.tick();job=calls[0]
    run=s.all(I.RUN)[0]
    assert run['input_digest']==I.digest(job['input'])
    w['resources']['sampled_at']=time.time()
    monkeypatch.setattr(I,'dependencies',lambda _: {'gbox/cast_swap.py':'a'})
    assert I.claim_reason(s,w,job) is None


def test_legacy_sparse_reservation_is_bound_to_exact_reviewed_plan(monkeypatch):
    s,w,c,calls,advance=rig();c.tick();advance(11);c.tick();job=calls[0]
    run=s.all(I.RUN)[0];p=s.get(I.PLAN,'g')
    run['input_digest']=I.digest(I.build_input(p,run['id'],normalized=False));s.put(I.RUN,run['id'],run)
    w['resources']['sampled_at']=time.time()
    monkeypatch.setattr(I,'dependencies',lambda _: {'gbox/cast_swap.py':'a'})
    assert I.claim_reason(s,w,job) is None
    for changed in [{'launch':True},{'source':'different'},{'scale':{'x':2}},{'unknown':True},{'mod_name':'other'}]:
        assert 'recipe' in I.claim_reason(s,w,job | {'input':job['input'] | changed})
    p['recipe']['input']['source']='different';s.put(I.PLAN,'g',p)
    assert 'recipe' in I.claim_reason(s,w,job)


def test_arbitrary_reservation_digest_cannot_authorize_job():
    s,w,c,calls,advance=rig();c.tick();advance(11);c.tick();job=calls[0]
    run=s.all(I.RUN)[0];p=s.get(I.PLAN,'g')
    changed=job | {'input':job['input'] | {'source':'unreviewed'}}
    run['input_digest']=I.digest(changed['input'])
    assert not I.reservation_matches(p,run,changed)
