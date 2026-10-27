"""Real central HTTP/store admission with synthetic local-authority evidence.

No worker is run and no emulator is launched. Lost responses repeat transport,
not native execution, and imported sessions keep the actual local SID.
"""
import time

import pytest

from fastapi.testclient import TestClient

from gbox.models import Job, WorkerInfo
from gbox.server import create_app
from gbox.store import canon, sha256

AUTH='a'*64
KEY='b'*64
WID='c'*16
LOCAL='d'*32
SID=WID+'-'+LOCAL


def plane(cfg):
    app=create_app(cfg)
    client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token(),
                                  'x-gbox-federation-key':KEY},raise_server_exceptions=False)
    return app,client


def snapshot(*,sessions=True,wid=WID,name='Owned local fixture'):
    return {'epoch':'e'*32,'worker':WorkerInfo(id=wid,name=name,os='windows',tools=['launch_game','session_op']).model_dump(),
            'sessions':[{'session_id':wid+'-'+LOCAL,'game_id':'fixture','title':'Owned fixture','adapter':'retroarch',
                         'state':'running','started':time.time(),'detail':{'pid':4321,'local_window':True}}] if sessions else []}


def enroll(client,**kw):
    response=client.post('/api/federation/'+AUTH+'/snapshot',json=snapshot(**kw))
    assert response.status_code==200,response.text
    return response.json()


def queued(app,*,jid='f'*32,tool='launch_game',inp=None):
    job=Job(id=jid,tool=tool,input=inp or {},require_worker=WID)
    app.state.store.put('job',jid,job.model_dump())
    return jid


def result(jid,local_id=LOCAL):
    return {'local_job_id':local_id,'state':'succeeded','result':{'job_id':jid,'ok':True,
        'output':{'session_id':WID+'-'+local_id,'adapter':'retroarch','capabilities':{},
                  'detail':{'pid':4321,'_game':{'game_id':None,'title':'Synthetic native fixture'}}},
        'artifacts':[],'log':['one local execution']}}


def test_snapshot_preserves_native_identity_and_omission_or_outage_is_not_exit(cfg):
    app,c=plane(cfg);enroll(c)
    store=app.state.store
    row=store.get('session',SID)
    assert row['session_id']==SID and row['federation']['media']=='session_stream'
    assert store.get('worker',WID)['id']==WID
    enroll(c,sessions=False)
    assert store.get('session',SID)['state']=='running'
    app.state.federation.clock=lambda:time.time()+120
    response=c.post('/api/federation/'+AUTH+'/commands',json={})
    assert response.status_code==409 and store.get('session',SID)['state']=='running'
    assert store.get('worker',WID)['last_seen']<app.state.federation.clock()-30


def test_cross_authority_key_sid_and_native_identity_are_fenced(cfg):
    app,c=plane(cfg);enroll(c)
    wrong=c.post('/api/federation/'+AUTH+'/snapshot',json=snapshot(),headers={'x-gbox-federation-key':'1'*64})
    assert wrong.status_code==403
    body=snapshot();body['sessions'][0]['session_id']='1'*16+'-'+LOCAL
    assert c.post('/api/federation/'+AUTH+'/snapshot',json=body).status_code==422
    body=snapshot();body['sessions'][0]['game_id']='another-game'
    assert c.post('/api/federation/'+AUTH+'/snapshot',json=body).status_code==409
    other='2'*64
    assert c.post('/api/federation/'+other+'/snapshot',json=snapshot()).status_code==409
    assert app.state.store.get('session',SID)['game_id']=='fixture'


def test_catalog_import_preserves_existing_sources_and_requires_local_file_evidence(cfg):
    app,c=plane(cfg)
    entry={'game_id':'owned','title':'Owned fixture','platform':'gamecube','source_paths':['C:/owned.iso'],
           'format':'iso','profile_id':'fixture','local_availability':{'verified':True}}
    central=entry|{'source_paths':['/central/original.iso'],'launch':{'path':'/central/original.iso'}}
    app.state.store.upsert_catalog([central])
    body=snapshot(sessions=False);body['catalog']=[entry,entry|{'game_id':'new-owned'}]
    response=c.post('/api/federation/'+AUTH+'/snapshot',json=body)
    assert response.status_code==200,response.text
    existing=app.state.store.catalog_get('owned')
    assert existing['source_paths']==central['source_paths'] and existing['launch']==central['launch']
    assert existing['cached_on']==['Owned local fixture']
    assert app.state.store.catalog_get('new-owned')['federation_source']==AUTH
    del body['catalog'][0]['local_availability']
    assert c.post('/api/federation/'+AUTH+'/snapshot',json=body).status_code==422


def test_existing_remote_native_owner_is_preserved_without_worker_retirement(cfg):
    app,c=plane(cfg);store=app.state.store
    old='1'*16
    store.put('worker',old,WorkerInfo(id=old,name='Owned local fixture',os='windows',tools=[]).model_dump())
    store.put('session',old+'-'+LOCAL,{'session_id':old+'-'+LOCAL,'state':'running','game_id':'owned'})
    assert c.post('/api/federation/'+AUTH+'/snapshot',json=snapshot()).status_code==409
    assert store.get('session',old+'-'+LOCAL)['state']=='running'
    assert store.get('worker',old) and not store.get('worker_alias',old)
    assert not store.get('worker',WID)


@pytest.mark.parametrize('seen_s,authority,admitted', [(7200, AUTH, True), (60, AUTH, False), (7200, 'f'*64, False)])
def test_a_long_gone_worker_of_the_same_authority_no_longer_blocks_its_successor(cfg, seen_s, authority, admitted):
    """2026-10-24: the i9-NUC's app restarted while its local scheduler ran Mercenaries 3D; that 'running' row refused
    every later snapshot of the same PC for 49 hours. A same-authority worker unseen for 30 minutes owns nothing."""
    app,c=plane(cfg);store=app.state.store
    old='1'*16;sid=old+'-'+LOCAL
    fed={'authority':authority,'epoch':'0'*32,'last_seen':time.time()-seen_s}
    store.put('worker',old,WorkerInfo(id=old,name='Owned local fixture',os='windows',tools=[]).model_dump()
              |{'last_seen':time.time()-seen_s,'federation':fed})
    store.put('session',sid,{'session_id':sid,'state':'running','game_id':'owned','federation':fed})
    response=c.post('/api/federation/'+AUTH+'/snapshot',json=snapshot())
    assert (response.status_code==200)==admitted,response.text
    row=store.get('session',sid)
    if admitted:
        assert row['state']=='ended' and row['exit']=={'via':'stale_owner','worker':old,'superseded_by':WID}
        assert store.get('worker',WID)['federation']['authority']==AUTH
    else:
        assert response.status_code==409 and row['state']=='running'      # recently seen, or another PC: preserved


def test_positive_end_cannot_be_resurrected_and_blocks_inputs(cfg):
    app,c=plane(cfg);enroll(c)
    body=snapshot();body['sessions'][0]['state']='ended';body['sessions'][0]['ended']=time.time()
    assert c.post('/api/federation/'+AUTH+'/snapshot',json=body).status_code==200
    assert c.get('/api/federation/'+AUTH+'/sessions/'+SID+'/input').status_code==409
    assert c.post('/api/federation/'+AUTH+'/snapshot',json=snapshot()).status_code==409


def test_lost_command_response_reoffers_same_job_and_recovers_claim_gap(cfg):
    app,c=plane(cfg);enroll(c,sessions=False);jid=queued(app)
    path='/api/federation/'+AUTH+'/commands'
    first=c.post(path,json={'maximum':1}).json()['commands']
    again=c.post(path,json={'maximum':1}).json()['commands']
    assert first==again and first[0]['id']==jid
    assert first[0]['input_sha256']==sha256(canon({}))
    assert first[0]['command_sha256']==sha256(canon({'tool':'launch_game','input':{}}))
    assert len([a for a in app.state.store.audit_log() if a['action']=='job.claim'])==1
    app.state.store.delete('federation_command',jid)  # simulated crash after central claim, before outbox write
    assert c.post(path,json={'maximum':1}).json()['commands'][0]['id']==jid


def test_delegated_launch_result_is_idempotent_and_retains_actual_local_sid(cfg):
    app,c=plane(cfg);enroll(c,sessions=False);jid=queued(app)
    c.post('/api/federation/'+AUTH+'/commands',json={'maximum':1})
    path='/api/federation/'+AUTH+'/jobs/'+jid
    assert c.post(path,json={'local_job_id':LOCAL,'state':'running'}).status_code==200
    first=c.post(path,json=result(jid));again=c.post(path,json=result(jid))
    assert first.status_code==200,first.text
    assert again.json()==first.json() and first.json()['accepted'] is True
    delayed=c.post(path,json={'local_job_id':LOCAL,'state':'running'})
    assert delayed.json()==first.json()
    assert len(app.state.store.all('receipt'))==1
    native=app.state.store.get('session',SID)
    assert native['session_id']==SID and native['central_launch_job_id']==jid
    assert native['local_launch_job_id']==LOCAL
    changed=result(jid,'1'*32)
    assert c.post(path,json=changed).status_code==409
    assert c.post('/api/federation/'+'2'*64+'/jobs/'+jid,json=result(jid)).status_code==403


def test_queued_stop_is_not_starved_by_reoffered_running_commands(cfg):
    app,c=plane(cfg);enroll(c)
    first=queued(app)
    c.post('/api/federation/'+AUTH+'/commands',json={'maximum':1})
    stop=queued(app,jid='2'*32,tool='session_op',inp={'session_id':SID,'op':'stop_game'})
    offered=c.post('/api/federation/'+AUTH+'/commands',json={'maximum':1}).json()['commands']
    assert offered[0]['id']==stop and app.state.store.get('job',first)['state']=='running'


@pytest.mark.parametrize('tool,op',[('session_op','query_runtime'),('session_op','log_tail'),
                                  ('get_frame',None),('autoplay','start')])
def test_live_foreground_controls_pass_locally_queued_background_delivery(cfg,tool,op):
    app,c=plane(cfg);enroll(c)
    store=app.state.store
    worker=store.get('worker',WID)
    store.put('worker',WID,worker|{'tools':worker['tools']+['get_frame','autoplay']})
    path='/api/federation/'+AUTH+'/commands'
    first=queued(app)
    c.post(path,json={'maximum':1})
    # Delivery was accepted centrally, but local background admission has not
    # started execution. A foreground request must not wait for that job.
    record=store.get('federation_command',first)
    store.put('federation_command',first,record|{'local_state':'queued','local_job_id':'9'*32})
    second=queued(app,jid='3'*32)
    inp={'session_id':SID,**({'op':op} if op else {})}
    control=queued(app,jid='2'*32,tool=tool,inp=inp)
    offered=c.post(path,json={'maximum':1}).json()['commands']
    assert [j['id'] for j in offered]==[control]
    assert store.get('job',first)['state']=='running'
    assert store.get('job',second)['state']=='queued'
    later=queued(app,jid='4'*32,tool=tool,inp=inp)
    again=c.post(path,json={'maximum':1}).json()['commands']
    assert [j['id'] for j in again]==[control]
    assert store.get('job',later)['state']=='queued'  # only one extra control in flight
    stop=queued(app,jid='5'*32,tool='session_op',inp={'session_id':SID,'op':'stop_game'})
    assert c.post(path,json={'maximum':1}).json()['commands'][0]['id']==stop


@pytest.mark.parametrize('case',['agent','ended','other-worker','missing'])
def test_foreground_delivery_exception_requires_exact_live_operator_session(cfg,case):
    app,c=plane(cfg);enroll(c)
    store=app.state.store;path='/api/federation/'+AUTH+'/commands'
    first=queued(app);c.post(path,json={'maximum':1})
    sid=SID
    if case=='ended':store.put('session',SID,store.get('session',SID)|{'state':'ended'})
    if case=='other-worker':sid='1'*16+'-'+LOCAL
    if case=='missing':sid=WID+'-'+'1'*32
    control=queued(app,jid='2'*32,tool='session_op',inp={'session_id':sid,'op':'query_runtime'})
    if case=='agent':store.put('job',control,store.get('job',control)|{'agent_use':True})
    assert c.post(path,json={'maximum':1}).json()['commands'][0]['id']==first
    assert store.get('job',control)['state']=='queued'


@pytest.mark.parametrize('blocked',['tool','os','admission'])
@pytest.mark.parametrize('control_tool',['session_op','launch_game'])
def test_reserved_delivery_never_claims_background_when_control_is_ineligible(cfg,blocked,control_tool,monkeypatch):
    app,c=plane(cfg);enroll(c)
    store=app.state.store;path='/api/federation/'+AUTH+'/commands'
    first=queued(app);c.post(path,json={'maximum':1})
    backgrounds=[queued(app,jid=str(i)*32) for i in (3,4,5)]
    inp={'game':{'game_id':'fixture'}} if control_tool=='launch_game' else {'session_id':SID,'op':'query_runtime'}
    control=queued(app,jid='2'*32,tool=control_tool,inp=inp)
    if blocked=='tool':
        worker=store.get('worker',WID)
        store.put('worker',WID,worker|{'tools':['launch_game' if control_tool=='session_op' else 'session_op']})
    elif blocked=='os':
        store.put('job',control,store.get('job',control)|{'require_os':'linux'})
    else:
        from gbox import unlock_job_policy
        real=unlock_job_policy.admit
        monkeypatch.setattr(unlock_job_policy,'admit',lambda store,app,parent,tool,inp,**kw:
            'Fixture admission hold' if tool==control_tool else real(store,app,parent,tool,inp,**kw))
    for _ in range(3):
        assert c.post(path,json={'maximum':1}).json()['commands'][0]['id']==first
        assert all(store.get('job',jid)['state']=='queued' for jid in [control,*backgrounds])


def test_inflight_control_keeps_reserved_slot_when_its_session_ends(cfg):
    app,c=plane(cfg);enroll(c)
    store=app.state.store;path='/api/federation/'+AUTH+'/commands'
    queued(app);c.post(path,json={'maximum':1})
    control=queued(app,jid='2'*32,tool='session_op',inp={'session_id':SID,'op':'query_runtime'})
    assert c.post(path,json={'maximum':1}).json()['commands'][0]['id']==control
    original=store.get('session',SID)
    store.put('session',SID,original|{'state':'ended'})
    successor=WID+'-'+'8'*32
    store.put('session',successor,original|{'session_id':successor})
    next_control=queued(app,jid='3'*32,tool='session_op',inp={'session_id':successor,'op':'query_runtime'})
    for _ in range(3):
        assert c.post(path,json={'maximum':1}).json()['commands'][0]['id']==control
        assert store.get('job',next_control)['state']=='queued'


def test_exact_operator_launch_uses_one_reserved_delivery_without_cancelling_background(cfg):
    app,c=plane(cfg);enroll(c)
    store=app.state.store;path='/api/federation/'+AUTH+'/commands'
    first=queued(app)
    c.post(path,json={'maximum':1})
    record=store.get('federation_command',first)
    store.put('federation_command',first,record|{'local_state':'queued','local_job_id':'9'*32})
    launch=queued(app,jid='2'*32,inp={'game':{'game_id':'fixture'}})
    assert c.post(path,json={'maximum':1}).json()['commands'][0]['id']==launch
    later=queued(app,jid='3'*32,inp={'game':{'game_id':'fixture'}})
    for _ in range(3):
        assert c.post(path,json={'maximum':1}).json()['commands'][0]['id']==launch
        assert store.get('job',later)['state']=='queued'
        assert store.get('job',first)['state']=='running'


@pytest.mark.parametrize('case',['agent','unbound','other-worker','missing-game'])
def test_launch_delivery_exception_requires_exact_operator_worker(cfg,case):
    from gbox.federation import foreground_session_job
    app,c=plane(cfg);enroll(c)
    store=app.state.store
    jid=queued(app,inp={'game':{'game_id':'fixture'}})
    row=store.get('job',jid)
    assert foreground_session_job(store,row,WID)
    if case=='agent':row['agent_use']=True
    elif case=='unbound':row['require_worker']=None
    elif case=='other-worker':row['require_worker']='1'*16
    else:row['input']={}
    assert not foreground_session_job(store,row,WID)


def test_job_cannot_forge_a_different_native_sid(cfg):
    app,c=plane(cfg);enroll(c,sessions=False);jid=queued(app)
    c.post('/api/federation/'+AUTH+'/commands',json={'maximum':1})
    body=result(jid);body['result']['output']['session_id']='1'*16+'-'+LOCAL
    response=c.post('/api/federation/'+AUTH+'/jobs/'+jid,json=body)
    assert response.status_code==409 and not app.state.store.all('receipt')
    assert not app.state.store.get('federation_command',jid).get('local_job_id')


def test_input_and_rpc_response_keep_source_and_exact_owned_request(cfg):
    app,c=plane(cfg);enroll(c)
    rid='1'*32
    c.post('/api/sessions/'+SID+'/input',json={'events':[{'key':'a','down':True,'src':'player'},
                                                        {'rpc':rid,'op':'info','args':{},'expires_at':time.time()+10}]})
    events=c.get('/api/federation/'+AUTH+'/sessions/'+SID+'/input').json()
    assert events[0]['src']=='player' and events[1]['rpc']==rid
    path='/api/federation/'+AUTH+'/sessions/'+SID+'/rpc/'+rid
    body={'ok':True,'data':{'native':'fixture'}}
    assert c.post(path,json=body).status_code==200
    assert c.post(path,json=body).status_code==200
    assert c.post(path,json={'ok':True,'data':{'native':'changed'}}).status_code==409
    assert c.post(path.replace(rid,'2'*32),json=body).status_code==403


def test_expired_or_unbounded_rpc_is_not_forwarded(cfg):
    app,c=plane(cfg);enroll(c)
    c.post('/api/sessions/'+SID+'/input',json={'events':[
        {'rpc':'1'*32,'op':'reset','args':{},'expires_at':time.time()-1},
        {'rpc':'2'*32,'op':'reset','args':{}}]})
    assert c.get('/api/federation/'+AUTH+'/sessions/'+SID+'/input').json()==[]


def test_ordinary_input_ttl_is_stamped_at_enqueue_and_expired_during_outage(cfg):
    app,c=plane(cfg);enroll(c)
    c.post('/api/sessions/'+SID+'/input',json={'events':[{'key':'a','down':True}]})
    app.state.federation.clock=lambda:time.time()+2
    hints=c.get('/api/federation/'+AUTH+'/sessions/'+SID+'/input').json()
    assert hints==[{'key':'a','player':1,'down':False,'_federation_expired':True,'src':'bridge'}]
    # The native session and ownership survive transport loss; stale held input does not.
    assert app.state.store.get('session',SID)['state']=='running'


def test_watch_is_demand_driven_and_federated_windows_use_session_media(cfg):
    app,c=plane(cfg);enroll(c)
    assert c.get('/api/federation/'+AUTH+'/watch').json()['sessions']==[]
    hub=app.state.broadcast
    hub.ensure_thread=lambda:None
    row=hub.refresh(force=True)[0]
    assert row['federation']['media']=='session_stream' and row['kind']=='windows_stream'
    feed=hub.feed('fixture');feed.row=row;feed.viewers=1
    hub._cut_desktops([feed],time.time())
    assert WID not in hub.desktop_watch
    assert c.get('/api/federation/'+AUTH+'/watch').json()['sessions']==[SID]
    feed.viewers=0
    assert c.get('/api/federation/'+AUTH+'/watch').json()['sessions']==[]


def test_native_boundary_resolves_local_autoplay_parent_to_central_job(cfg):
    app,c=plane(cfg);enroll(c)
    jid=queued(app,tool='session_op',inp={'session_id':SID,'op':'pause'})
    c.post('/api/federation/'+AUTH+'/commands',json={'maximum':1})
    c.post('/api/federation/'+AUTH+'/jobs/'+jid,json={'local_job_id':'3'*32,'state':'running'})
    observed=[]
    app.state.federation.boundary=lambda body,parent:observed.append((body,parent)) or {'saved':True,'rotate_requested':True}
    response=c.post('/api/federation/'+AUTH+'/round-boundary',
                    json={'local_job_id':'3'*32,'body':{'session_id':SID,'round_id':'4'*32}})
    assert response.status_code==200 and response.json()['rotate_requested'] is True
    assert observed[0][1]['id']==jid


def test_actual_http_relay_launch_adoption_autoplay_and_native_boundary_rotation(cfg,monkeypatch):
    """Synthetic native receipts drive the real HTTP/store/scheduler seams; no game is run."""
    from gbox import mercmode as M,screensaver as S
    from tests.test_mercmode import boundary
    monkeypatch.setattr(S,'START_GRACE',0)
    app,c=plane(cfg);store=app.state.store
    body=snapshot(sessions=False)
    body['worker'].update(tools=['launch_game','autoplay','session_op'],idle_seconds=3600,
        features=['two_percent_audio'],resources={'sampled_at':time.time(),'cpu_percent':10,
            'memory_percent':40,'memory_available_bytes':32*2**30})
    for index,title in enumerate(('re4','re5')):
        spec=M.TITLES[title];gid=spec['game_ids'][0]
        store.upsert_catalog([{'game_id':gid,'title':spec['name'],'platform':spec['platform'],
            'source_paths':['/synthetic-owned-fixture.iso'],'format':'iso','profile_id':spec['platform']}])
        body['sessions'].append({'session_id':WID+'-'+str(index+1)*32,'game_id':gid,'adapter':'fixture',
                                 'state':'ended','detail':{'pid':100+index},'started':time.time()-100})
    assert c.post('/api/federation/'+AUTH+'/snapshot',json=body).status_code==200
    M.configure(store,body['worker']['name'],{'enabled':True,'titles':['re4','re5']})
    saver=app.state.autoplay_screensaver
    saver.tick()
    run=store.get(S.STATE,body['worker']['name'])
    assert run and run['phase']=='launching'
    offered=c.post('/api/federation/'+AUTH+'/commands',json={'maximum':4}).json()['commands']
    command=next(item for item in offered if item['tool']=='launch_game')
    native=result(command['id'])
    native['result']['output']['detail']['_game']={'game_id':run['game_id'],'title':'Synthetic native fixture'}
    accepted=c.post('/api/federation/'+AUTH+'/jobs/'+command['id'],json=native)
    assert accepted.status_code==200,accepted.text
    assert command['id']!=LOCAL and store.get('session',SID)['central_launch_job_id']==command['id']
    saver.tick();saver.tick()
    run=store.get(S.STATE,body['worker']['name'])
    assert run['phase']=='playing' and run['session_id']==SID
    offered=c.post('/api/federation/'+AUTH+'/commands',json={'maximum':4}).json()['commands']
    autoplay=next(item for item in offered if item['tool']=='autoplay')
    assert autoplay['input']['session_id']==SID and autoplay['id']==run['autoplay_job']
    local_autoplay='3'*32
    response=c.post('/api/federation/'+AUTH+'/jobs/'+autoplay['id'],json={
        'local_job_id':local_autoplay,'state':'succeeded','result':{'job_id':autoplay['id'],'ok':True,
            'output':{'result':{'running':True}},'artifacts':[],'log':[]}})
    assert response.status_code==200,response.text
    c.post('/api/autoplay/telemetry/'+SID,json={'running':True,'mode':'auto','stats':{}})
    response=c.post('/api/federation/'+AUTH+'/round-boundary',
                    json={'local_job_id':local_autoplay,'body':boundary(run,time.time())})
    assert response.status_code==200,response.text
    assert response.json()=={'saved':True,'rotate_requested':True}
    saver.tick()
    stops=[job for job in store.queued_jobs() if job['tool']=='session_op'
           and job['input'].get('op')=='stop_game']
    assert len(stops)==1 and stops[0]['input']['session_id']==SID


def test_http_accepted_prepare_result_makes_only_its_exact_hosts_fixture_rom_ready(cfg,tmp_path):
    from gbox import mercmode as M
    app,c=plane(cfg);store=app.state.store
    body=snapshot(sessions=False);body['worker']['tools']+=['mercmode','autoplay']
    assert c.post('/api/federation/'+AUTH+'/snapshot',json=body).status_code==200
    worker=store.get('worker',WID)
    gid=M.TITLES['re4']['game_ids'][0]
    rom=tmp_path/'owned-fixture.iso';rom.write_bytes(b'synthetic file access fixture; never executed')
    game={'game_id':gid,'title':'Owned RE4 path fixture','platform':'gamecube','source_paths':[str(rom)],
          'format':'iso','profile_id':'gamecube','launch':{'path':str(rom)}}
    store.upsert_catalog([game])
    before=next(row for row in M.inventory(store,worker) if row['title']=='re4')
    assert before['backend_playable'] and not before['playable']
    jid=queued(app,tool='mercmode',inp={'op':'prepare'})
    store.put(M.PREPARATION,worker['name'],{'job':jid,'state':'checking','requested_at':time.time()})
    offered=c.post('/api/federation/'+AUTH+'/commands',json={'maximum':1}).json()['commands']
    assert offered[0]['id']==jid
    preparation=M.inspect_preparation(cfg.runtime)
    preparation['games']={gid:M.inspect_rom_access(cfg,game)}
    assert preparation['games'][gid]['reachable'] is True
    response=c.post('/api/federation/'+AUTH+'/jobs/'+jid,json={'local_job_id':'5'*32,'state':'succeeded',
        'result':{'job_id':jid,'ok':True,'output':{'result':{'saved':True,'host':worker['name'],
            'preparation':preparation}},'log':[],'artifacts':[]}})
    assert response.status_code==200,response.text
    ready=next(row for row in M.inventory(store,worker) if row['title']=='re4')
    assert ready['playable'] and ready['rom_access']['source']=='worker_local_path_probe'
    assert M.host_preparation(store,worker)['source']=='accepted_worker_prepare_job'
    assert not next(row for row in M.inventory(store,worker|{'id':'6'*16}) if row['title']=='re4')['playable']


def test_local_scheduler_observations_do_not_overwrite_central_desired_settings(cfg):
    from gbox import mercmode as M
    app,c=plane(cfg);store=app.state.store;body=snapshot(sessions=False)
    name=body['worker']['name']
    desired=M.configure(store,name,{'enabled':False,'rounds_per_title':3})
    body.update(scheduler_owner='local',mercmode={'settings':{'enabled':True,'rounds_per_title':1},
        'history':{'last_game_id':'local-only-observation'},'preparation':{'checkedAt':1}})
    response=c.post('/api/federation/'+AUTH+'/snapshot',json=body)
    assert response.status_code==200,response.text
    observed=store.get('mercmode_observed',name)
    assert observed['worker_id']==WID and observed['authority']==AUTH
    assert observed['settings']['enabled'] is True and observed['history']['last_game_id']=='local-only-observation'
    assert M.settings(store,name)==desired
    enroll(c,sessions=False)
    assert store.get('worker',WID)['federation']['scheduler_owner']=='local'


def test_launch_autoplay_marker_requires_exact_central_pending_job_and_game(cfg):
    app,c=plane(cfg);enroll(c,sessions=False);store=app.state.store
    jid=queued(app,inp={'game':{'game_id':'owned'}})
    path='/api/federation/'+AUTH+'/commands'
    store.put('autoplay_on_launch',jid,{'job':jid,'game_id':'another','actor':'operator','agent':False})
    assert 'autoplay_on_launch' not in c.post(path,json={}).json()['commands'][0]
    store.put('autoplay_on_launch',jid,{'job':jid,'game_id':'owned','actor':'operator','agent':False})
    command=c.post(path,json={}).json()['commands'][0]
    assert command['autoplay_on_launch']=={'game_id':'owned','actor':'operator','agent':False}
    assert command['input_sha256']==sha256(canon({'game':{'game_id':'owned'}}))


def test_exact_mapped_autoplay_reports_deduplicate_each_observation_not_whole_kind(cfg,monkeypatch):
    app,c=plane(cfg);enroll(c);store=app.state.store
    worker=store.get('worker',WID);store.put('worker',WID,worker|{'tools':worker['tools']+['autoplay']})
    jid=queued(app,tool='autoplay',inp={'op':'start','session_id':SID})
    c.post('/api/federation/'+AUTH+'/commands',json={})
    response=c.post('/api/federation/'+AUTH+'/jobs/'+jid,json={'local_job_id':'3'*32,'state':'running'})
    assert response.status_code==200,response.text
    calls=[]
    monkeypatch.setattr(app.state.autoplay_screensaver,'yield_to_operator',lambda sid,reason:calls.append((sid,reason)) or True)
    path='/api/federation/'+AUTH+'/autoplay-report'
    body={'kind':'yield','local_job_id':'3'*32,'body':{'session_id':SID,'reason':'mouse'}}
    first=c.post(path,json=body);assert first.status_code==200,first.text
    assert c.post(path,json=body).json()==first.json() and calls==[(SID,'mouse')]
    body['body']['reason']='pad'
    assert c.post(path,json=body).json()['saved'] and calls[-1]==(SID,'pad')
    body['local_job_id']='4'*32
    assert c.post(path,json=body).status_code==403 and len(calls)==2


def test_pending_autoplay_report_recovers_same_observation_after_central_restart(cfg,monkeypatch):
    app,c=plane(cfg);enroll(c);store=app.state.store
    worker=store.get('worker',WID);store.put('worker',WID,worker|{'tools':worker['tools']+['autoplay']})
    jid=queued(app,tool='autoplay',inp={'op':'start','session_id':SID})
    c.post('/api/federation/'+AUTH+'/commands',json={})
    c.post('/api/federation/'+AUTH+'/jobs/'+jid,json={'local_job_id':'3'*32,'state':'running'})
    native={'session_id':SID,'result':{'score':123}}
    identifier=AUTH+':'+'3'*32+':result:'+sha256(canon(native))
    store.put('federation_autoplay_report',identifier,{'digest':sha256(canon(native)),'ack':None})
    calls=[]
    monkeypatch.setattr(app.state.autoplay_screensaver,'report',lambda sid,result:calls.append((sid,result)) or True)
    response=c.post('/api/federation/'+AUTH+'/autoplay-report',json={
        'kind':'result','local_job_id':'3'*32,'body':native})
    assert response.status_code==200,response.text
    assert response.json()['saved'] and calls==[(SID,{'score':123})]
    assert store.get('federation_autoplay_report',identifier)['ack']==response.json()
