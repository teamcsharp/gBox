import copy
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from gbox import live_controls as L, live_controls_api as API
from gbox.registry import Unsupported
from tests.test_build_quarantine import Memory


def spec():
    return {'executable_sha256':'a'*64, 'revision_label':'USA fixture',
        'guards':[{'address':100,'hex':'abcd'*8}], 'ghidra_artifacts':['b'*64], 'runtime_artifacts':['b'*64],
        'actions':[{'id':'boss_hp','category':'bosses','label':'Set boss HP to zero',
            'scope':'Offline boss room', 'notes':'Fixed live object, test fixture only',
            'guards':[{'address':200,'hex':'01'}], 'parameters':[],
            'binding':{'kind':'memory','address':300,'width':2,'byteorder':'big','value':0}}]}


def validate(body):
    store=Memory(); store.read_artifact=lambda sha: b'evidence' if sha=='b'*64 else None
    return L.validate(body,store)


class RAM:
    def __init__(self):
        self.data=bytearray(1024); self.data[100:116]=bytes.fromhex('abcd'*8);self.data[200]=1
        self.data[300:302]=b'\x01\x00';self.writes=[];self.retain=True
    def read_memory(self,a,n): return bytes(self.data[a:a+n])
    def write_memory(self,a,b):
        self.writes.append((a,b))
        if self.retain:self.data[a:a+len(b)]=b


def fixture():
    p=validate(spec());p.update(game_id='g',revision='rev')
    return RAM(),p,{'game_id':'g'},L.LiveIn(session_id='worker-session',game_id='g',revision='rev',op='apply',action='boss_hp')


def test_readback_and_inspection_do_not_guess_success():
    ad,p,g,i=fixture()
    assert L.operate(ad,p,g,i.model_copy(update={'op':'inspect'}),None)['actions']==[{'id':'boss_hp','available':True}]
    assert not ad.writes
    assert L.operate(ad,p,g,i,None)=={'action':'boss_hp','verified':True,'before':256,'value':0}
    ad,p,g,i=fixture();ad.retain=False
    with pytest.raises(Unsupported,match='retain'): L.operate(ad,p,g,i,None)
    assert len(ad.writes)==1, 'a non-idempotent action is never retried blindly'


@pytest.mark.parametrize('change', ['game','profile_game','revision','fingerprint','mode','action','parameters'])
def test_mismatches_never_write(change):
    ad,p,g,i=fixture()
    if change=='game':g['game_id']='other'
    if change=='profile_game':p['game_id']='other'
    if change=='revision':p['revision']='new'
    if change=='fingerprint':ad.data[100]=0
    if change=='mode':ad.data[200]=2
    if change=='action':i.action='unknown'
    if change=='parameters':i.values={'unexpected':1}
    with pytest.raises((Unsupported,ValueError)): L.operate(ad,p,g,i,None)
    assert not ad.writes


def test_bounded_parameters_and_choices():
    a=spec()['actions'][0]
    a['parameters']=[{'id':'amount','label':'HP','kind':'integer','min':0,'max':100,'default':50},
                     {'id':'item','label':'Item','kind':'choice','options':[{'value':'sword','label':'Sword'}],'default':'sword'}]
    assert L.values_for(a,{'amount':0,'item':'sword'})['amount']==0
    for value in [-1,101,True,1.5,'50']:
        with pytest.raises(ValueError): L.values_for(a,{'amount':value,'item':'sword'})
    with pytest.raises(ValueError): L.values_for(a,{'amount':50,'item':'unknown'})


@pytest.mark.parametrize('change',['short','missingproof','unknownproof','missingmode','overlap','wide','native','sid','unknownparam'])
def test_publication_requires_evidence_and_bounded_bindings(change):
    p=spec();a=p['actions'][0]
    if change=='short':p['guards'][0]['hex']='ab'
    if change=='missingproof':p['runtime_artifacts']=[]
    if change=='unknownproof':p['ghidra_artifacts']=['c'*64]
    if change=='missingmode':a['guards']=[]
    if change=='overlap':a['binding']['address']=200
    if change=='wide':a['binding']['width']=8
    if change=='native':a['binding']={'kind':'native','tool':'launch_game','input':{'op':'spawn'}}
    if change=='sid':a['binding']={'kind':'native','tool':'gta_mods','input':{'op':'ped_rain','session_id':'victim'}}
    if change=='unknownparam':a['binding']={'kind':'native','tool':'gta_mods','input':{'op':'ped_rain','count':'$guess'}}
    with pytest.raises(ValueError):validate(p)


def test_native_injects_session_and_validates_native_schema(monkeypatch):
    from pydantic import BaseModel
    from gbox.registry import REGISTRY
    class In(BaseModel):
        session_id:str
        op:str
        count:int
    class Out(BaseModel):result:dict
    calls=[]
    monkeypatch.setitem(REGISTRY,'gta_mods',SimpleNamespace(In=In,Out=Out,unavailable_reason=lambda _:None,
        fn=lambda inp,ctx:calls.append(inp.model_dump()) or {'result':{'spawned':inp.count}}))
    ad,p,g,i=fixture();a=p['actions'][0]
    a.update(parameters=[{'id':'count','label':'Count','kind':'integer','min':1,'max':10,'default':2}],
             binding={'kind':'native','tool':'gta_mods','input':{'op':'ped_rain','count':'$count'}})
    i.values={'count':3}
    assert L.operate(ad,p,g,i,SimpleNamespace(config=None))['result']['result']['spawned']==3
    assert calls==[{'session_id':'worker-session','op':'ped_rain','count':3}]
    assert not ad.writes


def rig():
    store=Memory();store.catalog_get=lambda gid:{'game_id':gid,'title':'Fixture'} if gid=='g' else None
    store.read_artifact=lambda sha:b'evidence' if sha=='b'*64 else None
    store.put('session','worker-session',{'game_id':'g','state':'running'})
    created=[];dispatched=[];jobs=[]
    def create(body):
        r=body|{'id':'r1','number':1,'status':'open'};created.append(r);store.put('request','r1',r);return r
    def submit(req,actor):jobs.append(req);return {'id':'job','state':'queued'}
    app=FastAPI()
    API.routes(app,store,lambda:'operator',submit,SimpleNamespace,create,lambda *a,**k:dispatched.append(a) or {'mode':'queue'})
    return TestClient(app),store,created,dispatched,jobs


def test_read_only_get_and_idempotent_discovery():
    c,s,created,dispatched,jobs=rig()
    assert c.get('/api/games/g/live-controls').json()['profile'] is None
    assert not created and not jobs
    assert c.get('/api/games/unknown/live-controls').status_code==404
    for _ in range(2):assert c.post('/api/games/g/live-controls/discover').status_code==200
    assert len(created)==len(dispatched)==1
    assert 'Ghidra' in created[0]['body'] and 'EVERY custom build' in created[0]['body']
    r=s.get('request','r1');r['status']='done';s.put('request','r1',r)
    c.post('/api/games/g/live-controls/discover')
    assert len(created)==1 and len(dispatched)==2 and s.get('request','r1')['status']=='open'


def test_api_rejects_stale_or_wrong_session_and_pins_worker():
    c,s,created,dispatched,jobs=rig()
    profile=c.post('/api/games/g/live-controls/profile',json=spec()).json()
    body={'session_id':'worker-session','revision':profile['revision'],'op':'apply','action':'boss_hp','values':{}}
    assert c.post('/api/games/g/live-controls/run',json=body|{'revision':'stale'}).status_code==409
    assert c.post('/api/games/g/live-controls/run',json=body|{'session_id':'other'}).status_code==409
    assert c.post('/api/games/g/live-controls/run',json=body|{'values':{'arbitrary':99}}).status_code==422
    assert not jobs
    assert c.post('/api/games/g/live-controls/run',json=body).status_code==200
    assert jobs[0].require_worker=='worker' and jobs[0].input['game_id']=='g'
    s.put('session','worker-session',{'game_id':'other','state':'running'})
    assert c.post('/api/games/g/live-controls/run',json=body).status_code==409


def test_failed_discovery_dispatch_reuses_saved_ticket():
    c,s,created,dispatched,jobs=rig()
    c.post('/api/games/g/live-controls/discover')
    t=s.get(L.TASK,'g');t.update(dispatched=False,error='temporary');s.put(L.TASK,'g',t)
    c.post('/api/games/g/live-controls/discover')
    assert len(created)==1 and len(dispatched)==2 and 'error' not in s.get(L.TASK,'g')


def test_agent_research_tool_uses_authenticated_publication_route(monkeypatch):
    import httpx
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        return httpx.Response(200,json={'revision':'published'},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    ctx=SimpleNamespace(server='http://control',headers={'Authorization':'Bearer fixture'})
    assert L.research(L.ResearchIn(game_id='g',op='publish',profile=spec()),ctx)['result']['revision']=='published'
    assert calls[0][0]=='http://control/api/games/g/live-controls/profile'
    assert calls[0][1]['headers']==ctx.headers and calls[0][1]['json']==spec()
    with pytest.raises(Unsupported):L.research(L.ResearchIn(game_id='g',op='shell'),ctx)


def test_worker_fetches_authoritative_profile_before_memory_access(monkeypatch):
    import httpx
    from gbox.tools import SESSIONS
    ad,p,g,i=fixture()
    monkeypatch.setitem(SESSIONS,'worker-session',(ad,g))
    ctx=SimpleNamespace(server='http://control',headers={})
    def get(url,**kwargs):return httpx.Response(200,json={'profile':p},request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx,'get',get)
    assert L.live_controls(i,ctx)['result']['value']==0
    ad.writes.clear();p['revision']='new finding'
    with pytest.raises(Unsupported,match='changed'):L.live_controls(i,ctx)
    assert not ad.writes
