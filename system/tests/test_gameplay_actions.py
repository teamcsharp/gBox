import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import gameplay_actions as A,gameplay_demo as D
from gbox.gameplay_memory import Archive,install
from tests.test_inspection_builds import Store

SESSION={'session_id':'pc-human','game_id':'pso','title':'Phantasy Star Online','mod':'','started':100}


def test_drop_receipt_freezes_resolved_random_items_and_never_re_rolls():
    result={'codes':['001000','000105','001000'],'spawned':3,'verified':True,'max_grinds':{'001000':15}}
    payload=A.action({'op':'floor_rares','count':3,'highest':True,'max_grind':True,'radius':25},result)
    assert payload['replayable']
    assert payload['replay_input']['op']=='floor_spawn'
    assert payload['replay_input']['codes']==result['codes']
    assert payload['replay_input']['count']==3 and payload['replay_input']['radius']==25
    assert payload['result']['max_grinds']=={'001000':15}
    assert A.action({'op':'status'},{}) is None
    assert not A.action({'op':'floor_rares'},{'verified':True})['replayable']
    assert not A.action({'op':'randomized','on':True},{'verified':True})['replayable']
    assert not A.action({'op':'stat','name':'atp','value':900},{'verified':False})['replayable']


def test_failed_recorder_does_not_raise_or_retry_successful_game_action(monkeypatch):
    from gbox import tools
    monkeypatch.setitem(tools.SESSIONS,'human',(SimpleNamespace(),{}))
    def fail(*args):raise OSError('disk full')
    monkeypatch.setattr(A,'start',fail)
    assert A.record('human',{'op':'give','code':'001000'},{'created':1},None,'cmd') is None


def recorder(tmp_path,monkeypatch):
    monkeypatch.setattr(A.threading.Thread,'start',lambda self:None)
    cfg=SimpleNamespace(runtime=tmp_path)
    return A.Recorder('pc-human',SimpleNamespace(name='dolphin'),{'platform':'gamecube'},SimpleNamespace(config=cfg,server='http://spark',headers={}))


def test_outbox_atomic_order_times_and_restart_preservation(tmp_path,monkeypatch):
    r=recorder(tmp_path,monkeypatch)
    r.save('mod_action',{'op':'give'},token='first',at=123)
    r.save('mod_action',{'op':'stat'},token='second',at=124)
    paths=sorted(r.root.glob('*-event.json'))
    assert [json.loads(p.read_text())['token'] for p in paths]==['first','second']
    assert json.loads(paths[0].read_text())['at']==123
    assert not list(r.root.glob('*.tmp'))
    second=A.Recorder(r.sid,None,r.game,r.ctx)
    second.save('mod_action',{'op':'revive'},token='third',at=125)
    assert len(list(second.root.glob('*-event.json')))==3


def test_snapshot_keeps_every_restore_but_bounds_periodic_states(tmp_path,monkeypatch):
    r=recorder(tmp_path,monkeypatch)
    state=tmp_path/'source.s08';state.write_bytes(b'private state')
    clock=[1000.]
    monkeypatch.setattr(A.time,'time',lambda:clock[0])
    monkeypatch.setattr(A.shutil,'disk_usage',lambda _:SimpleNamespace(free=10*2**30))
    r.checkpoint(state)
    clock[0]+=10;r.checkpoint(state)
    assert len(list(r.root.glob('*-event.json')))==1
    clock[0]+=1;r.checkpoint(state,'restore')
    clock[0]+=1;r.checkpoint(state,'restore')
    rows=[json.loads(p.read_text()) for p in sorted(r.root.glob('*-event.json'))]
    assert [p['payload']['branch'] for p in rows]==[0,1,2]
    assert rows[-1]['payload']['operation']=='restore'
    state.unlink()
    blob=r.root/(rows[0]['payload']['sha256']+'.blob')
    assert blob.read_bytes()==b'private state' # ring deletion never destroys replay history


def test_failed_upload_retains_exact_local_files_and_accepted_outbox_is_idempotent(tmp_path,monkeypatch):
    r=recorder(tmp_path,monkeypatch)
    r.identity={'adapter':'dolphin'};r.cards=[]
    r.save('mod_action',{'op':'give'},token='fixed')
    class Response:
        def raise_for_status(self):raise OSError('offline')
    monkeypatch.setattr(A.httpx,'post',lambda *a,**k:Response())
    with pytest.raises(OSError):r.upload_once()
    assert len(list(r.root.glob('*-event.json')))==1
    class Okay:
        def raise_for_status(self):pass
        def json(self):return {'saved':True}
    seen=[]
    monkeypatch.setattr(A.httpx,'post',lambda *a,**k:seen.append(k['json']) or Okay())
    r.upload_once();r.upload_once()
    assert len(seen)==1 and seen[0]['token']=='fixed'
    assert not list(r.root.glob('*-event.json'))


def test_streamed_snapshots_are_hash_checked_retained_and_required_before_readiness(tmp_path):
    app=FastAPI();store=Store();store.put('session','pc-human',SESSION)
    install(app,store,SimpleNamespace(data_dir=tmp_path,gameplay_memory_enabled=True),lambda:'operator')
    c=TestClient(app)
    state=b'native state fixture';card=b'card fixture'
    sha=hashlib.sha256(state).hexdigest();card_sha=hashlib.sha256(card).hexdigest()
    payload={'schema':1,'sha256':sha,'cards':[{'sha256':card_sha,'slot':'A'}],
             'identity':{'rom_sha256':'a'*64,'emulator_sha256':'b'*64}}
    body={'kind':'checkpoint','payload':payload,'token':'checkpoint1','at':123}
    assert c.post('/api/gameplay-memory/runs/pc-human/observe',json=body).status_code==422
    assert c.post('/api/gameplay-memory/blobs/'+sha,content=b'bad').status_code==422
    assert c.post('/api/gameplay-memory/blobs/'+sha,content=state).status_code==200
    assert c.post('/api/gameplay-memory/blobs/'+card_sha,content=card).status_code==200
    assert c.post('/api/gameplay-memory/runs/pc-human/observe',json=body).json()['saved']
    assert c.post('/api/gameplay-memory/runs/pc-human/observe',json=body).json()['saved']
    plan=c.get('/api/gameplay-memory/runs/pc-human/demo').json()
    assert plan['ready'] and plan['start']==123 and plan['game_id']=='pso'
    assert c.get('/api/gameplay-memory/blobs/'+sha).content==state
    assert app.state.gameplay_memory.status()['events']==1
    assert not list((tmp_path/'gameplay-memory/snapshots').glob('upload-*'))


def test_timeline_orders_capture_time_before_upload_receipt_and_freezes_prefix(tmp_path):
    archive=Archive(tmp_path)
    archive.record(SESSION,'pad',{'events':[]},at=112)
    archive.record(SESSION,'mod_action',{'op':'give'},at=110)
    archive.record(SESSION,'checkpoint',{'marker':'old'},at=109)
    frozen_end=archive.events('pc-human')[-1]['id']
    archive.record(SESSION,'note',{'text':'later tail'},at=113)
    rows=archive.timeline('pc-human',after_at=109,end_id=frozen_end)
    assert [r['at'] for r in rows]==[109,110,112]
    assert all(r['kind']!='note' for r in rows)
    cursor=rows[1]
    assert archive.timeline('pc-human',cursor['at'],cursor['id'],frozen_end)==rows[2:]


def test_observed_scheduler_replays_cheats_and_branches_once_in_chronological_order():
    clock=[0.];calls=[]
    events=[{'id':1,'at':100,'kind':'pad','payload':{'events':[{'key':'a','down':True}]}},
            {'id':2,'at':101,'kind':'mod_action','payload':{'replayable':True}},
            {'id':3,'at':102,'kind':'checkpoint','payload':{'schema':1,'operation':'restore','branch':1}},
            {'id':3,'at':102,'kind':'checkpoint','payload':{'schema':1}},
            {'id':4,'at':103,'kind':'pad','payload':{'events':[{'key':'a','down':False}]}}]
    result=D.run_timeline(events,start=100,clock=lambda:clock[0],sleep=lambda s:clock.__setitem__(0,clock[0]+s),
        active=lambda:True,send=lambda e:calls.append(('pad',e[0]['down'])),
        restore=lambda p:calls.append(('restore',p['branch'])),
        apply=lambda e:calls.append(('mod',e['id'])) or {'verified':True},remaining=300)
    assert calls==[('pad',True),('mod',2),('restore',1),('pad',False)]
    assert result=={'pads':2,'actions':1,'restores':1,'skipped':0,'completed':True}
    assert clock[0]==3


def test_observed_scheduler_yields_before_further_inputs_or_mutations():
    called=[]
    with pytest.raises(InterruptedError):
        D.run_timeline([{'id':1,'at':1}],start=0,clock=lambda:0,sleep=lambda _:None,active=lambda:False,
                       send=called.append,restore=called.append,apply=called.append,remaining=100)
    assert not called


def test_analog_input_is_explicitly_quantized_and_select_chords_are_not_reissued():
    rows=D.pad_events({'events':[{'key':'select','down':True},{'key':'a','down':True}],
                       'stick':{'x':.9,'y':-.8},'rstick':{'x':0,'y':0}})
    assert not any(r['key']=='select' for r in rows)
    assert {'key':'a','down':True} in rows
    assert {'key':'right','down':True} in rows and {'key':'up','down':True} in rows
    assert {'key':'left','down':False} in rows and {'key':'down','down':False} in rows


def test_no_demo_in_operator_job_or_without_initial_native_state(tmp_path):
    ctx=SimpleNamespace(server='http://spark',agent_use=False)
    with pytest.raises(ValueError,match='agent-owned'):
        D.play(SimpleNamespace(),ctx)


def test_randomizer_records_resolved_codes_only_after_native_equipment_acknowledgment():
    from gbox import pso_modes as M
    class Gear:
        def __init__(self):self.rows=[]
        def check(self):return 1
        def u16(self,a):return 1
        def inventory(self):return self.rows[:]
        def give(self,code):self.rows.append({'id':0xf00001,'code':code});return {'ids':[0xf00001],'verified':True}
        def equip_id(self,item_id):return True
    seen=[]
    state={'on':True,'due':0,'interval':15,'categories':['weapon'],'character_class':'HUmar',
           'catalog':[{'code':'001000','rare':True,'classes':['HUmar']}],'generated':{},'cycles':0,
           '_record':lambda gear,cycle:seen.append((gear,cycle))}
    M.tick(Gear(),state,1)
    assert seen==[([{'kind':'weapon','code':'001000'}],1)]


def test_demo_api_accepts_json_and_never_dispatches_to_an_active_operator(tmp_path):
    import time
    app=FastAPI();store=Store();source=SESSION|{'state':'ended','worker_id':'source'}
    store.put('session','pc-human',source)
    install(app,store,SimpleNamespace(data_dir=tmp_path,gameplay_memory_enabled=True),lambda:'operator')
    archive=app.state.gameplay_memory
    archive.record(source,'checkpoint',{'schema':1,'sha256':'a'*64,'cards':[{'sha256':'b'*64,'slot':'A'}],
                                      'identity':{'rom_sha256':'c'*64,'emulator_sha256':'d'*64}},at=123)
    now=time.time()
    worker={'id':'idle','name':'i9-NUC','online':True,'os':'windows','tools':['gameplay_demo'],'idle_seconds':999,
            'resources':{'sampled_at':now,'cpu_percent':10,'memory_percent':40,'memory_available_bytes':8*2**30}}
    calls=[]
    def submit(body,**kwargs):calls.append((body,kwargs));return {'id':'demo-job'}
    D.install(app,store,SimpleNamespace(),lambda:'operator',submit,lambda:[worker],archive)
    c=TestClient(app)
    response=c.post('/api/gameplay-memory/runs/pc-human/demo/play',json={'loop':True})
    assert response.status_code==200,response.text
    assert calls[0][0].agent_use and calls[0][0].require_worker=='idle'
    assert calls[0][0].input['loop']
    response=c.post('/api/gameplay-memory/runs/pc-human/demo/idle',json={'enabled':True})
    assert response.status_code==200,response.text
    assert store.get('gameplay_demo_idle','pc-human')['run_id']=='pc-human'
    store.put('session','idle-current',{'session_id':'idle-current','worker_id':'idle','state':'running'})
    response=c.post('/api/gameplay-memory/runs/pc-human/demo/play',json={})
    assert response.status_code==409 and len(calls)==1


def test_face_paint_is_kept_as_artifact_evidence_and_not_sent_to_pso_mods():
    p=A.action({'op':'pso_face_apply','candidate':'a'*64,'address':0x81000000,'key':'face'}, {'verified':True})
    assert p['tool']=='pso_faces' and not p['replayable']
    assert p['input']['candidate']=='a'*64 and 'native checkpoints' in p['reason']


def test_idle_success_rejects_black_frames():
    import io
    from PIL import Image,ImageDraw
    def png(image):
        stream=io.BytesIO();image.save(stream,format='PNG');return stream.getvalue()
    assert not D.visible_frame(b'')
    assert not D.visible_frame(png(Image.new('RGB',(64,64),'black')))
    image=Image.new('RGB',(64,64),'black');ImageDraw.Draw(image).rectangle((10,10,50,50),fill='white')
    assert D.visible_frame(png(image))


def test_automatic_completed_human_pso_verification_then_loop_and_failed_prefix_backoff(tmp_path,monkeypatch):
    clock=[1000.];monkeypatch.setattr(D.time,'time',lambda:clock[0])
    app=FastAPI();store=Store()
    store.catalog_get=lambda gid:{'game_id':gid,'title':'Phantasy Star Online Episode I & II Plus','platform':'gamecube'}
    for sid,state in [('source-ended','ended'),('source-running','running'),('source-agent','ended'),('source-disabled','ended')]:
        store.put('session',sid,{'session_id':sid,'game_id':'pso','state':state,'worker_id':'source'})
    store.put('slabel','source-agent',{'owner':'agent'})
    store.put('gameplay_demo_idle','source-disabled',{'run_id':'source-disabled','enabled':False})
    plan={'ready':True,'checkpoint':{'sha256':'a'*64},'end_id':100}
    archive=SimpleNamespace(runs=lambda limit=50:[{'id':sid,'observed_demo':{'ready':True}} for sid in
                         ('source-running','source-agent','source-disabled','source-ended')],
                            demo=lambda sid:dict(plan))
    worker={'id':'idle','name':'i9-NUC','online':True,'os':'windows','tools':['gameplay_demo'],'idle_seconds':999,
            'resources':{'sampled_at':clock[0],'cpu_percent':10,'memory_percent':40,'memory_available_bytes':8*2**30}}
    calls=[]
    def submit(body,**kwargs):
        job={'id':'demo'+str(len(calls)),'tool':body.tool,'input':body.input,'state':'queued'}
        calls.append(job);store.put('job',job['id'],job);return job
    D.install(app,store,SimpleNamespace(gameplay_memory_enabled=True),lambda:'operator',submit,lambda:[worker],archive)
    tick=app.state.gameplay_demo_idle_tick
    tick()
    assert len(calls)==1 and calls[0]['input']['run_id']=='source-ended' and not calls[0]['input']['loop']
    assert store.get('gameplay_demo_idle','source-running') is None
    assert store.get('gameplay_demo_idle','source-agent') is None
    assert not store.get('gameplay_demo_idle','source-disabled')['enabled']
    # A failed unchanged prefix never enters a blind restart loop.
    store.put('job','demo0',calls[0]|{'state':'failed'})
    clock[0]+=301;worker['resources']['sampled_at']=clock[0];tick()
    assert len(calls)==1
    # Additional archived events create a new immutable prefix; respect the
    # cooldown, then permit exactly one fresh verification attempt.
    plan['end_id']=101;tick()
    assert len(calls)==2 and not calls[1]['input']['loop']
    store.put('job','demo1',calls[1]|{'state':'succeeded'})
    store.put('gameplay_demo_result','demo1',{'job_id':'demo1','status':{'verified':True,'state':'finished'}})
    tick();assert len(calls)==2
    clock[0]+=301;worker['resources']['sampled_at']=clock[0];tick()
    assert len(calls)==3 and calls[2]['input']['loop'] and calls[2]['input']['idle_demo']
    # The launch job can finish while its emulator keeps playing. That session
    # still blocks all further automatic PSO demonstrations globally.
    store.put('job','demo2',calls[2]|{'state':'succeeded'})
    store.put('session','idle-demo',{'session_id':'idle-demo','state':'running','detail':{'gameplay_demo':{'run_id':'source-ended'}}})
    clock[0]+=301;worker['resources']['sampled_at']=clock[0];tick()
    assert len(calls)==3


def test_manual_state_session_operations_feed_actual_file_and_capture_cannot_fail_load(tmp_path,monkeypatch,cfg):
    from gbox import tools
    from gbox.registry import Ctx
    path=tmp_path/'GPOE8P.s01';calls=[];saved=[];loaded=[]
    def save():
        saved.append(1);path.write_bytes(b'native operator state fixture')
        return {'path':str(path),'slot':1,'verified':True}
    def load():loaded.append(1);return {'slot':1}
    ad=SimpleNamespace(name='dolphin',serial='GPOE8P',state_dir=lambda:tmp_path,
                       save_state=save,load_state=load,gameplay_checkpoint=lambda p,kind:calls.append((p,kind)))
    monkeypatch.setitem(tools.SESSIONS,'manual-state',(ad,{'platform':'gamecube'}))
    ctx=Ctx(cfg)
    assert tools.session_op(tools.SessionIn(session_id='manual-state',op='save_state'),ctx)['result']['verified']
    assert tools.session_op(tools.SessionIn(session_id='manual-state',op='load_state'),ctx)['result']['slot']==1
    assert calls==[(path,'checkpoint'),(path,'restore')] and len(saved)==len(loaded)==1
    def failed_capture(*args):raise OSError('capture disk is full')
    ad.gameplay_checkpoint=failed_capture
    assert tools.session_op(tools.SessionIn(session_id='manual-state',op='load_state'),ctx)['result']['slot']==1
    assert len(loaded)==2 # completed load is neither failed nor retried by capture


def test_queued_pso_receipt_archives_resolved_action_once_even_after_result_retry(cfg):
    from tests.test_worker_results import control
    import time
    app,plane=control(cfg,jid='pso-action',tool='pso_mods')
    store=app.state.store
    store.put('session','pc-human',SESSION|{'state':'running'})
    job=store.get('job','pso-action')
    store.put('job','pso-action',job|{'input':{'session_id':'pc-human','op':'floor_rares','count':2,'highest':True,'max_grind':True}})
    result={'job_id':'pso-action','ok':True,'output':{'result':{'verified':True,'spawned':2,'codes':['001000','000105']}},
            'artifacts':[],'log':[]}
    first=plane.post('/api/workers/old-worker/result',json=result)
    assert first.status_code==200,first.text
    assert plane.post('/api/workers/old-worker/result',json=result).status_code==200
    rows=app.state.gameplay_memory.events('pc-human')
    assert len(rows)==1 and rows[0]['kind']=='mod_action'
    assert rows[0]['payload']['replay_input']['op']=='floor_spawn'
    assert rows[0]['payload']['replay_input']['codes']==['001000','000105']


def test_native_dolphin_physical_input_convention_differs_from_streamed_adapter_buttons():
    labels=['a','b','x','y','r','l2','r2','up']
    physical={'events':[{'key':key,'down':True} for key in labels],'stick':{'x':0,'y':0},'rstick':{'x':0,'y':0}}
    events=D.pad_events(physical,'gamecube')
    # XInput A was recorded as RetroPad b; replay must press GameCube A.
    expected=['b','a','y','x','z','l','r','t']
    assert [e['key'] for e in events[:len(labels)]]==expected
    streamed={'events':[{'key':key,'down':True} for key in labels]}
    assert [e['key'] for e in D.pad_events(streamed,'gamecube')]==labels


def test_flycast_uses_native_analog_channel_and_preserves_retropad_faces():
    rows=D.pad_events({'events':[{'key':'b','down':True}], 'stick':{'x':.9,'y':-.9}},'dreamcast')
    assert rows[0]=={'key':'b','down':True}
    assert {'key':'lright','down':True} in rows and {'key':'lup','down':True} in rows
    assert not any(row['key'] in ('up','down','left','right') for row in rows)
    # UI input already expressed using the analog channel stays unchanged.
    assert D.pad_events({'events':[{'key':'lleft','down':False}]},'dreamcast')==[{'key':'lleft','down':False}]


def test_cleanup_only_removes_its_stopped_uuid_demo_directory(tmp_path):
    root=tmp_path/'gameplay-demos';root.mkdir()
    folder=root/('a'*32);folder.mkdir();(folder/'state').write_bytes(b'private')
    live=SimpleNamespace(poll=lambda:None)
    dead=SimpleNamespace(poll=lambda:0)
    assert not D.cleanup_demo(folder,root,live) and folder.is_dir()
    outside=tmp_path/('b'*32);outside.mkdir();(outside/'save').write_bytes(b'human')
    assert not D.cleanup_demo(outside,root,dead) and (outside/'save').read_bytes()==b'human'
    assert D.demo_bytes(root)==7
    assert D.cleanup_demo(folder,root,dead) and not folder.exists()
    assert D.demo_bytes(root)==0


def test_unsupported_queued_cheat_actions_remain_visible_but_do_not_abort_live_replay():
    payload=A.action({'op':'move_speed','factor':3,'on':True},{'verified':True})
    assert not payload['replayable'] and payload['input']['factor']==3
    assert 'no verified live replay handler' in payload['reason']
    assert D.replay_action('no-session',payload,None,'no-execution',{})['skipped']
