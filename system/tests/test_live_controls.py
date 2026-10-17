import copy
import json
import time
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


def test_profile_can_record_native_inapplicability_without_publishing_a_fake_action():
    body=spec()
    body['assessments']={'checkpoints':{'status':'unsupported','scope':'Owned on-foot campaign maps',
        'reason':'No ordered native checkpoint route is present in the reviewed maps'}}
    profile=validate(body)
    assert profile['assessments']==body['assessments']
    assert all(a['category']!='checkpoints' for a in profile['actions'])
    body['assessments']['bosses']=body['assessments']['checkpoints']
    with pytest.raises(ValueError,match='published action'):validate(body)
    body['assessments']={'checkpoints':{'status':'verified'}}
    with pytest.raises(ValueError,match='status'):validate(body)


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
    return RAM(),p,{'game_id':'g'},L.LiveIn(session_id='worker-session',game_id='g',revision='rev',op='apply',action='boss_hp',
                                         command_id='fixture-command-0001',expires=time.time()+15)


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


def toggle_spec():
    p=spec();a=p['actions'][0]
    a.update(id='noclip',category='movement',label='Walk through walls',
             control='toggle',toggle_parameter='on',
             parameters=[{'id':'on','label':'Enabled','kind':'boolean','default':False}],
             binding={'kind':'native','tool':'auf_live','input':{'op':'noclip','on':'$on'},'state_key':'noclip'})
    return p


def test_boolean_toggle_parameters_are_explicit_and_not_integer_coercions():
    p=validate(toggle_spec());a=p['actions'][0]
    assert a['control']=='toggle' and a['toggle_parameter']=='on'
    for value in (True,False):assert L.values_for(a,{'on':value})=={'on':value}
    for value in (1,0,'true',None):
        with pytest.raises(ValueError,match='true or false'):L.values_for(a,{'on':value})
    for change in ('default','integer','memory','missingbinding','otherparameter','button'):
        p=toggle_spec();a=p['actions'][0]
        if change=='default':a['parameters'][0]['default']=0
        if change=='integer':a['parameters'][0].update(kind='integer',min=0,max=1,default=0)
        if change=='memory':a['binding']=spec()['actions'][0]['binding']
        if change=='missingbinding':a['binding']['input'].pop('on')
        if change=='otherparameter':a['toggle_parameter']='unknown'
        if change=='button':a['control']='button'
        with pytest.raises(ValueError):validate(p)


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


def native_probe(monkeypatch, result):
    from pydantic import BaseModel
    from gbox.registry import REGISTRY
    class In(BaseModel):
        session_id:str
        op:str
        on:bool=False
        command_id:str=''
        expires:float=0
    class Out(BaseModel):result:dict
    calls=[]
    def native(inp,ctx):calls.append(inp.model_dump());return {'result':result}
    monkeypatch.setitem(REGISTRY,'auf_live',SimpleNamespace(In=In,Out=Out,
        unavailable_reason=lambda _:None,fn=native))
    ad,old,g,i=fixture();p=validate(toggle_spec());p.update(game_id='g',revision='rev')
    return ad,p,g,i.model_copy(update={'action':'noclip'}),calls


def test_native_probe_is_read_only_once_per_tool_and_uses_actual_state(monkeypatch):
    result={'switches':{'noclip':True,'infinite_ammo':False},
            'available':{'noclip':True,'infinite_ammo':True,'give_item':False},
            'unavailable_reasons':{'give_item':'A real loaded-item reason'}}
    ad,p,g,i,calls=native_probe(monkeypatch,result)
    p['actions'].append(p['actions'][0]|{'id':'ammo','binding':{'kind':'native','tool':'auf_live',
        'input':{'op':'infinite_ammo','on':'$on'},'state_key':'infinite_ammo'}})
    p['actions'].append(p['actions'][0]|{'id':'give','control':'button','parameters':[],
        'binding':{'kind':'native','tool':'auf_live','input':{'op':'give_item','item':'fixture'}}})
    r=L.operate(ad,p,g,i.model_copy(update={'op':'inspect'}),SimpleNamespace(config=None))
    assert r['actions']==[{'id':'noclip','available':True,'value':True},
                          {'id':'ammo','available':True,'value':False},
                          {'id':'give','available':False,'reason':'A real loaded-item reason'}]
    assert len(calls)==1 and calls[0]['op']=='inspect' and not ad.writes
    assert not calls[0]['command_id'] and not calls[0]['expires']


def test_native_loaded_item_choices_cannot_add_unreviewed_items_and_missing_reason_is_shown(monkeypatch):
    result={'available':{'give_item':True,'next_checkpoint':False},
            'items':[{'id':'pistol','name':'Dynamic untrusted name'},{'id':'unknown','name':'Unreviewed'}],
            'unavailable_reasons':{'next_checkpoint':'No authored ordered mission checkpoint route found'}}
    ad,p,g,i,calls=native_probe(monkeypatch,result)
    base=p['actions'][0]
    p['actions']=[base|{'id':'give','control':'button',
        'parameters':[{'id':'item','kind':'choice','label':'Item','default':'pistol',
                       'options':[{'value':'pistol','label':'Reviewed pistol'},{'value':'rocket','label':'Reviewed rocket'}]}],
        'binding':{'kind':'native','tool':'auf_live','input':{'op':'give_item','item':'$item'}}},
        base|{'id':'checkpoint','control':'button','parameters':[],
        'binding':{'kind':'native','tool':'auf_live','input':{'op':'next_checkpoint'}}}]
    r=L.operate(ad,p,g,i.model_copy(update={'op':'inspect'}),SimpleNamespace(config=None))['actions']
    assert r[0]=={'id':'give','available':True,'item_choices':{'parameter':'item','values':['pistol']}}
    assert r[1]=={'id':'checkpoint','available':False,'reason':result['unavailable_reasons']['next_checkpoint']}
    result['items']=[]
    r=L.operate(ad,p,g,i.model_copy(update={'op':'inspect'}),SimpleNamespace(config=None))['actions']
    assert r[0]['available'] is False and r[0]['item_choices']['values']==[]


def test_native_inventory_status_is_typed_and_limited_to_reviewed_loaded_choices(monkeypatch):
    result={'available':{'give_item':True}, 'items':[
        {'id':'claw','owned':True,'equipped':False,'name':'Untrusted runtime label'},
        {'id':'laser','owned':False,'equipped':True},
        {'id':'unknown','owned':True,'equipped':True},
        {'id':'pistol','owned':1,'equipped':False},
    ]}
    ad,p,g,i,calls=native_probe(monkeypatch,result)
    p['actions']=[p['actions'][0]|{'id':'give','control':'button',
        'parameters':[{'id':'item','kind':'choice','label':'Item','default':'claw',
                       'options':[{'value':v,'label':v} for v in ('claw','laser','pistol')]}],
        'binding':{'kind':'native','tool':'auf_live','input':{'op':'give_item','item':'$item'}}}]
    row=L.operate(ad,p,g,i.model_copy(update={'op':'inspect'}),SimpleNamespace(config=None))['actions'][0]
    assert row['item_choices']=={'parameter':'item','values':['claw','laser','pistol'],
        'states':{'claw':{'owned':True,'equipped':False},'laser':{'owned':False}}}
    assert not ad.writes and len(calls)==1


@pytest.mark.parametrize('result',[
    {'switches':{'noclip':True}},
    {'switches':{'noclip':1},'available':{'noclip':True}},
    {'switches':{},'available':{'noclip':True}},
    {'switches':{'noclip':False},'available':{'noclip':'yes'}},
    {'error':'Unsupported revision','verified':False},
])
def test_unknown_native_availability_or_state_never_enables_switch(monkeypatch,result):
    ad,p,g,i,calls=native_probe(monkeypatch,result)
    r=L.operate(ad,p,g,i.model_copy(update={'op':'inspect'}),SimpleNamespace(config=None))
    assert r['actions'][0]['available'] is False and not ad.writes


def test_native_mutation_inherits_command_identity_and_expiry(monkeypatch):
    ad,p,g,i,calls=native_probe(monkeypatch,{'verified':True,'switches':{'noclip':True}})
    i.values={'on':True}
    L.operate(ad,p,g,i,SimpleNamespace(config=None))
    assert calls==[{'session_id':i.session_id,'op':'noclip','on':True,
                    'command_id':i.command_id,'expires':i.expires}]
    calls.clear();i.expires=time.time()-1
    with pytest.raises(Unsupported,match='expired'):L.operate(ad,p,g,i,SimpleNamespace(config=None))
    assert not calls and not ad.writes


@pytest.mark.parametrize('change',['missing','mismatch','unknown','other_tool','not_toggle'])
def test_toggle_state_binding_cannot_select_arbitrary_inspector(change):
    p=toggle_spec();a=p['actions'][0]
    if change=='missing':a['binding'].pop('state_key')
    if change=='mismatch':a['binding']['state_key']='infinite_ammo'
    if change=='unknown':a['binding']['state_key']='guess'
    if change=='other_tool':a['binding'].update(tool='gta_mods',input={'op':'ped_rain','on':'$on'})
    if change=='not_toggle':a.pop('control');a.pop('toggle_parameter')
    with pytest.raises(ValueError):validate(p)


def rig(*,real_job=False):
    store=Memory();store.catalog_get=lambda gid:{'game_id':gid,'title':'Fixture'} if gid=='g' else None
    store.read_artifact=lambda sha:b'evidence' if sha=='b'*64 else None
    store.put('session','worker-session',{'game_id':'g','state':'running'})
    created=[];dispatched=[];jobs=[]
    def create(body):
        r=body|{'id':'r1','number':1,'status':'open'};created.append(r);store.put('request','r1',r);return r
    def submit(req,actor):
        jobs.append(req)
        if real_job:
            from gbox.models import Job
            return Job(tool=req.tool,input=req.input,require_worker=req.require_worker)
        return {'id':'job','state':'queued'}
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
    assert created[0]['context']['requested_controls']==list(L.REQUESTED_CONTROLS)
    assert all(word in created[0]['body'] for word in ('noclip','checkpoint','ammunition','rockets','dropdown'))
    r=s.get('request','r1');r['status']='done';s.put('request','r1',r)
    c.post('/api/games/g/live-controls/discover')
    assert len(created)==1 and len(dispatched)==2 and s.get('request','r1')['status']=='open'


def test_old_discovery_ticket_is_upgraded_once_without_losing_history():
    c,s,created,dispatched,jobs=rig()
    s.put('request','old',{'id':'old','number':9,'status':'open','body':'Original research',
                         'context':{'other':'preserved'},'messages':[{'text':'Earlier finding'}]})
    s.put(L.TASK,'g',{'request_id':'old','number':9,'dispatched':True})
    for _ in range(2):assert c.post('/api/games/g/live-controls/discover').status_code==200
    assert not created and len(dispatched)==1
    r=s.get('request','old')
    assert r['body']=='Original research' and r['context']['other']=='preserved'
    assert len(r['messages'])==2 and 'noclip' in r['messages'][1]['text']
    assert s.get(L.TASK,'g')['requested_controls']==list(L.REQUESTED_CONTROLS)


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
    assert time.time()<jobs[0].input['expires']<=time.time()+15
    assert len(jobs[0].input['command_id'])==32
    s.put('session','worker-session',{'game_id':'other','state':'running'})
    assert c.post('/api/games/g/live-controls/run',json=body).status_code==409


def test_queued_commands_expire_before_write_and_after_slow_guard_reads():
    ad,p,g,i=fixture()
    i.expires=time.time()-1
    with pytest.raises(Unsupported,match='expired'):L.operate(ad,p,g,i,None)
    assert not ad.writes
    ad,p,g,i=fixture();original=ad.read_memory
    def slow_guard(address,size):
        if address==200:i.expires=time.time()-1
        return original(address,size)
    ad.read_memory=slow_guard
    with pytest.raises(Unsupported,match='expired'):L.operate(ad,p,g,i,None)
    assert not ad.writes


def test_api_command_deadlines_and_replay_receipts_never_submit_twice():
    c,s,created,dispatched,jobs=rig()
    profile=c.post('/api/games/g/live-controls/profile',json=spec()).json()
    body={'session_id':'worker-session','revision':profile['revision'],'op':'apply','action':'boss_hp',
          'values':{},'command_id':'one-click-command-0001','expires':time.time()+4}
    first=c.post('/api/games/g/live-controls/run',json=body)
    assert first.status_code==200
    assert jobs[0].input['expires']==body['expires'],'earlier caller deadline is never extended'
    assert c.post('/api/games/g/live-controls/run',json=body).json()==first.json()
    assert len(jobs)==1
    assert c.post('/api/games/g/live-controls/run',json=body|{'expires':time.time()-1}).status_code==422
    assert c.post('/api/games/g/live-controls/run',json=body|{'command_id':'invalid'}).status_code==422
    collision=body|{'values':{},'action':'other'}
    p=s.get(L.PROFILE,'g');p['actions'].append(p['actions'][0]|{'id':'other'});s.put(L.PROFILE,'g',p)
    assert c.post('/api/games/g/live-controls/run',json=collision).status_code==409
    assert len(jobs)==1


def test_uncertain_submission_is_reserved_instead_of_retried():
    c,s,created,dispatched,jobs=rig()
    profile=c.post('/api/games/g/live-controls/profile',json=spec()).json()
    body={'session_id':'worker-session','revision':profile['revision'],'op':'apply','action':'boss_hp',
          'values':{},'command_id':'uncertain-command-0001','expires':time.time()+4}
    fingerprint=L.digest({k:body[k] for k in ('session_id','revision','action','values')}|{'game_id':'g'})
    s.put(L.COMMAND,body['command_id'],{'fingerprint':fingerprint,'expires':body['expires']})
    assert c.post('/api/games/g/live-controls/run',json=body).status_code==409
    assert not jobs


def test_real_job_model_replay_receipt_survives_the_persistent_store_json_boundary():
    c,s,created,dispatched,jobs=rig(real_job=True)
    put=s.put
    s.put=lambda kind,key,value:put(kind,key,json.loads(json.dumps(value,default=str)))
    profile=c.post('/api/games/g/live-controls/profile',json=spec()).json()
    body={'session_id':'worker-session','revision':profile['revision'],'op':'apply','action':'boss_hp',
          'values':{},'command_id':'real-job-command-0001','expires':time.time()+10}
    first=c.post('/api/games/g/live-controls/run',json=body)
    assert first.status_code==200
    receipt=s.get(L.COMMAND,body['command_id'])
    assert isinstance(receipt['job'],dict) and receipt['job']['id']==first.json()['id']
    replay=c.post('/api/games/g/live-controls/run',json=body)
    assert replay.status_code==200 and replay.json()==first.json()
    assert len(jobs)==1


def test_native_profiles_require_current_worker_code_before_any_probe_or_mutation(monkeypatch):
    c,s,created,dispatched,jobs=rig()
    expected={'gbox/live_controls.py':'c'*64,'gbox/auf_live.py':'d'*64}
    monkeypatch.setattr(API,'worker_sources',lambda:expected)
    profile=c.post('/api/games/g/live-controls/profile',json=toggle_spec()).json()
    body={'session_id':'worker-session','revision':profile['revision'],'op':'inspect'}
    assert c.post('/api/games/g/live-controls/run',json=body).status_code==409
    w={'tools':['game_live_controls','auf_live'],'last_seen':time.time(),'build_sources':expected}
    s.put('worker','worker',w|{'tools':['game_live_controls']})
    assert c.post('/api/games/g/live-controls/run',json=body).status_code==409
    s.put('worker','worker',w|{'build_sources':expected|{'gbox/live_controls.py':'old'}})
    assert c.post('/api/games/g/live-controls/run',json=body).status_code==409
    assert not jobs
    s.put('worker','worker',w)
    assert c.post('/api/games/g/live-controls/run',json=body).status_code==200
    assert len(jobs)==1 and jobs[0].input['op']=='inspect'


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


def test_profile_metadata_job_works_with_staging_grants_without_broad_file_or_ram_permissions(tmp_path):
    from gbox.models import Permission
    from gbox.registry import REGISTRY
    from tests.test_builds import fixture
    cfg,app,store,headers=fixture(tmp_path)
    cfg.granted_permissions=[Permission.READ,Permission.EXECUTE,Permission.STAGE,Permission.NETWORK,Permission.INSTALL]
    with TestClient(app) as c:
        response=c.post('/api/jobs',headers=headers,json={'tool':'game_controls_research',
            'input':{'game_id':'g1','op':'get'}})
        assert response.status_code==200
        assert response.json()['state']=='queued',response.text
        mutation=c.post('/api/jobs',headers=headers,json={'tool':'game_live_controls',
            'input':{'session_id':'w-test','game_id':'g1','revision':'rev','op':'inspect'}})
        assert mutation.status_code==200
        assert mutation.json()['state']=='rejected' and 'memory_write' in mutation.json()['error']
    research=REGISTRY['game_controls_research']
    assert research.side_effects and set(research.permissions)=={Permission.READ,Permission.STAGE}


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
