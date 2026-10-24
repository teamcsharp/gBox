"""Native-round scheduling and exact-host selection, with no emulator processes."""
import copy
import random
from types import SimpleNamespace

import pytest

from gbox import mercmode as M, screensaver as S
from tests.test_screensaver import Store as BaseStore, worker


RE4,RE5=M.TITLES['re4']['game_ids'][0],M.TITLES['re5']['game_ids'][0]


class Store(BaseStore):
    def catalog_get(self,gid):
        for row in M.TITLES.values():
            if gid in row['game_ids']:
                return {'game_id':gid,'title':row['name'],'platform':row['platform']}


def rig():
    store=Store();now=[10000.];w=worker(now[0],name='lilspark',os='linux');calls=[]
    for title,gid in (('re4',RE4),('re5',RE5)):
        store.put('session','w1-prior-'+title,{'session_id':'w1-prior-'+title,'game_id':gid,'state':'ended'})
    def submit(req,actor,origin):
        job={'id':str(len(calls)),'state':'queued','tool':req.tool,'input':req.input,
             'require_worker':req.require_worker,'agent_use':req.agent_use}
        calls.append(job);store.put('job',job['id'],job);return job
    saver=S.Screensaver(store,SimpleNamespace(runs=lambda **kw:[]),submit,lambda:[w],rng=random.Random(4))
    def tick(dt=0):
        now[0]+=dt;w['resources']['sampled_at']=now[0];return saver.tick(now[0])
    return store,w,saver,calls,now,tick


def playing():
    store,w,saver,calls,now,tick=rig()
    M.configure(store,w['name'],{'enabled':True})
    tick();gid=calls[0]['input']['game']['game_id']
    sid='w1-'+calls[0]['id']
    store.put('session',sid,{'session_id':sid,'game_id':gid,'state':'running'})
    tick(1);tick(S.START_GRACE)
    run=store.get(S.STATE,w['name'])
    job=store.get('job',run['autoplay_job'])|{'state':'succeeded'}
    store.put('job',job['id'],job)
    S.telemetry_put(sid,{'running':True,'stats':{}},now=now[0])
    return store,w,saver,calls,now,tick,run,job


def boundary(run,now,**witness):
    return {'session_id':run['session_id'],'round_id':'a'*32,'at':now,
            'map_id':run['mercmode']['map_id'],'role':'solo_p1','source':'native_terminal_reader',
            'mode':'mercenaries','stage':'observed','character':'observed',
            'witness':{'playing_observed':True,'player_verified':True,'screen':'results',
                       'tally_ready':True,'timer':0,'game_routine':3,'room':0x400,**witness}}


def adoptable():
    store,w,saver,calls,now,tick=rig()
    M.configure(store,w['name'],{'enabled':True})
    sid='w1-current'
    session={'session_id':sid,'game_id':RE5,'state':'running'}
    job={'id':'active','tool':'autoplay','state':'succeeded','worker_id':w['id'],
         'require_worker':w['id'],'input':{'op':'start','session_id':sid}}
    store.put('job',job['id'],job)
    telemetry={'running':True,'age_s':1,'stats':{'source_session_id':sid,
        'source_autoplay_job_id':job['id'],'team_role':'solo_p1','screen':'playing'}}
    return store,w,session,telemetry,now


def test_adoption_keeps_exact_current_solo_job_without_launch_or_input():
    store,w,session,telemetry,now=adoptable()
    run=M.adopt_current(store,w,session,telemetry,now=now[0])
    assert run['session_id']==session['session_id'] and run['autoplay_job']=='active'
    assert run['adopted_existing_solo'] and run['mercmode']['title']=='re5'
    assert M.adopt_current(store,w,session,telemetry,now=now[0]+1)==run
    assert len(store.all('job'))==1


@pytest.mark.parametrize('change',[{'running':False},{'age_s':9},{'age_s':float('nan')},
    {'stats':{'team_role':'observe_human'}},{'stats':{'source_session_id':'other'}},
    {'stats':{'source_autoplay_job_id':'foreign'}},{'stats':{'screen':'dead'}}])
def test_adoption_refuses_stale_human_or_foreign_runtime(change):
    store,w,session,telemetry,now=adoptable()
    if 'stats' in change:change={'stats':telemetry['stats']|change['stats']}
    with pytest.raises(ValueError):M.adopt_current(store,w,session,telemetry|change,now=now[0])
    assert not store.get(S.STATE,w['name'])


@pytest.mark.parametrize('target,patch',[('worker',{'federation':{'authority':'other'}}),
    ('worker',{'online':False}),('session',{'session_id':'other-current'}),
    ('session',{'state':'ended'}),('job',{'worker_id':'other'}),('job',{'state':'failed'})])
def test_adoption_requires_native_host_and_accepted_job(target,patch):
    store,w,session,telemetry,now=adoptable()
    if target=='worker':w.update(patch)
    elif target=='session':session.update(patch)
    else:store.put('job','active',store.get('job','active')|patch)
    with pytest.raises(ValueError):M.adopt_current(store,w,session,telemetry,now=now[0])


def test_only_verified_terminal_and_exact_successor_launch_link_title_rotation():
    store,w,saver,calls,now,tick,run,job=playing()
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested']
    tick(1)
    old=store.get('session',run['session_id'])
    store.put('session',run['session_id'],old|{'state':'ended'})
    tick(1)
    launch=calls[-1];newrun=store.get(S.STATE,w['name'])
    live={'session_id':w['id']+'-'+launch['id'],'game_id':newrun['game_id'],'state':'running'}
    assert newrun['mercmode_predecessor']['round_id']=='a'*32
    assert not M.link_rotation(store,newrun,live,now[0]),'queued launch cannot create lineage'
    store.put('session',live['session_id'],live)
    tick(1)                            # registration may precede launch completion
    assert store.get('session',run['session_id']).get('replaced_by') is None
    store.put('job',launch['id'],launch|{'state':'succeeded','worker_id':w['id']})
    assert not M.link_rotation(store,newrun,live|{'session_id':'other-'+launch['id']},now[0])
    tick(1)                            # a later starting-phase tick links the accepted launch
    linked=store.get('session',run['session_id'])
    assert linked['replaced_by']==live['session_id']
    assert linked['mercmode_rotation']['to_game']!=linked['game_id']
    assert not M.link_rotation(store,newrun,live,now[0]),'never replace an existing successor'


def test_no_operator_handover_or_plain_stop_becomes_rotation_lineage():
    store,w,*_=rig()
    for why in ('handed to the operator','screensaver turned off','the game ended'):
        store.put(S.LOG,'old',{'worker_id':w['id'],'why':why,'ended':10000,
            'mercmode_rotate_requested':True,'mercmode_last_round':{'round_id':'a'*32}})
        assert M.rotation_predecessor(store,w,10001) is None


def test_hosts_are_independent_and_unknown_config_is_rejected():
    store=Store();M.configure(store,'lilspark',{'enabled':True,'titles':['re5']})
    assert M.settings(store,'i9-NUC')['enabled'] is False
    assert M.settings(store,'lilspark')['titles']==['re5']
    for patch in ({'titles':['re6','re6']},{'rounds_per_title':True},{'enabled':1},{'modifiers':True},{'presentation_priority':1}):
        with pytest.raises(ValueError):M.configure(store,'lilspark',patch)


@pytest.mark.parametrize('priority,memory,expected',[(False,40,204),(True,40,200),(True,90,204)])
def test_real_claim_presentation_keeps_gpu_budget_for_other_jobs_and_memory_guard(cfg,priority,memory,expected):
    import time
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app=create_app(cfg);store=app.state.store;now=time.time()
    w=worker(now,name='lilspark',os='linux')
    w['resources'].update(cpu_percent=96,memory_percent=memory,gpus=[{'name':'GPU','utilization_percent':99}])
    store.put('worker',w['id'],w|{'last_seen':now,'tools':['launch_game']})
    M.configure(store,w['name'],{'enabled':True,'presentation_priority':priority})
    job={'id':'owned-launch','tool':'launch_game','state':'queued','actor':S.ACTOR,'require_os':None,
         'require_worker':w['id'],'agent_use':True,'low_priority':True,'created':now,
         'input':{'game':{'game_id':RE4,'launch':{'mercmode':{'random_characters':True,'random_stages':True}}}}}
    store.put('job',job['id'],job)
    store.put(S.STATE,w['name'],{'worker_id':w['id'],'phase':'launching','job':job['id'],
        'game_id':RE4,'mercmode':{'title':'re4'}})
    client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token()})
    # A copied hint without the exact scheduler job cannot obtain foreground admission.
    foreign=job|{'id':'unrelated','created':now-1}
    store.put('job',foreign['id'],foreign)
    response=client.post('/api/workers/'+w['id']+'/claim',json={'idle_seconds':0,'active_jobs':0})
    assert response.status_code==expected,response.text
    if expected==200:assert response.json()['id']==job['id']
    assert store.get('job',foreign['id'])['state']=='queued'
    if memory==90:assert 'memory headroom' in store.get('job',job['id'])['admission_wait']['reason']


def test_only_verified_titles_are_playable_and_preparation_does_not_claim_rpc_states():
    store,w,*_=rig()
    rows={r['title']:r for r in M.inventory(store,w)}
    assert rows['re4']['playable'] and rows['re5']['playable']
    assert not rows['re6']['playable'] and 'no verified' in rows['re6']['reason']
    assert rows['re5']['preparation']['instant_state_supported'] is False
    assert 'No save-state' in rows['re5']['preparation']['reason']
    w['tools']=['launch_game']
    assert not any(r['playable'] for r in M.inventory(store,w))


def test_mode_launches_without_recorded_play_and_never_changes_modifiers():
    store,w,saver,calls,now,tick,run,job=playing()
    launch=calls[0]['input']
    assert launch['game']['launch']['mercmode']=={'random_characters':True,'random_stages':True}
    assert set(launch)=={'game','jump','memory_cards'}
    assert run['mercmode']['title'] in ('re4','re5')
    tick(60*60)
    assert len(calls)==2                        # no session_minutes interruption mid-round


def test_actual_boundary_rotates_once_then_waits_for_owned_game_stop():
    store,w,saver,calls,now,tick,run,job=playing()
    body=boundary(run,now[0])
    assert saver.round_boundary(body,job,now[0])=={'saved':True,'rotate_requested':True}
    assert saver.round_boundary(body,job,now[0])['duplicate'] is True
    tick(1)
    assert calls[-1]['tool']=='session_op' and calls[-1]['input']['op']=='stop_game'
    tick(1)
    assert len(calls)==3                        # prior running session blocks parallel launch
    store.put('session',run['session_id'],{'session_id':run['session_id'],'state':'ended'})
    tick(1)
    assert calls[-1]['tool']=='launch_game'
    assert calls[-1]['input']['game']['game_id']!=run['game_id']


def test_one_ready_title_keeps_warm_session_and_native_character_cycle():
    store,w,saver,calls,now,tick,run,job=playing()
    M.configure(store,w['name'],{'titles':[run['mercmode']['title'],'re6']})
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False
    tick(1)
    assert len(calls)==2


@pytest.mark.parametrize('change',[
    {'role':'observe_human'}, {'role':'teammate_p2'}, {'map_id':'BH6'},
    {'source':'telemetry'}, {'round_id':'invented'}, {'at':1},
    {'witness':{'screen':'loading','playing_observed':True,'player_verified':True}},
    {'witness':{'screen':'results','playing_observed':True,'player_verified':True,'tally_ready':False,'timer':0}},
    {'witness':{'screen':'dead','playing_observed':True,'player_verified':False,'hp':0}},
    {'witness':{'screen':'dead','playing_observed':True,'player_verified':True,'hp':500}},
])
def test_untrusted_or_incomplete_boundaries_cannot_rotate(change):
    store,w,saver,calls,now,tick,run,job=playing()
    with pytest.raises(ValueError):saver.round_boundary(boundary(run,now[0])|change,job,now[0])
    assert not store.get(S.STATE,w['name']).get('mercmode_rotate_requested')


def test_exact_job_current_live_runtime_and_handover_are_required():
    store,w,saver,calls,now,tick,run,job=playing()
    for changed in (job|{'id':'old'},job|{'require_worker':'other'},job|{'state':'failed'}):
        with pytest.raises(ValueError):saver.round_boundary(boundary(run,now[0]),changed,now[0])
    S.telemetry_put(run['session_id'],{'running':False},now=now[0])
    with pytest.raises(ValueError):saver.round_boundary(boundary(run,now[0]),job,now[0])
    store.put(S.STATE,w['name'],run|{'handover':'mouse'})
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['saved'] is False


def test_preparation_inspection_does_no_launch_or_creation(tmp_path):
    result=M.inspect_preparation(tmp_path)
    assert list(tmp_path.iterdir())==[]
    assert not result['emulator_launched'] and not result['configuration_changed']
    assert not result['rpcs3']['instant_state_supported']


def test_re4_native_cursor_routes_reach_every_character_and_stage():
    from gbox import re4_menus as R
    from tests.test_re4_menus import FakeRE4,TW
    for count,where,offset,step in ((5,'select_player',R.TW_PLAYER_CURSOR,8),(4,'select_stage',R.TW_STAGE_CURSOR,12)):
        for start in range(count):
            for target in range(count):
                game=FakeRE4(routine=6,step=step)
                game.put(TW+offset,'B',start)
                for _ in range(6):
                    scr=R.screen(game)|{'target':target}
                    key=R.step(scr)
                    if key=='a':break
                    game.send([{'key':key,'down':True}])
                assert game.u8(TW+offset)==target
                assert key=='a'


def test_re4_random_targets_are_instance_local_and_stable_until_round():
    from gbox import re4_menus as R
    from tests.test_re4_menus import FakeRE4
    a,b=R.RandomSelections(random.Random(2)),R.RandomSelections(random.Random(3))
    game=FakeRE4(routine=6,step=8)
    first=a.screen(game)['target']
    assert a.screen(game)['target']==first
    assert b.player is None
    game.round();a.screen(game)
    game.title_task(True);game.tw(6,8)
    assert a.screen(game)['target']!=first


def test_legacy_re4_emits_only_native_terminal_after_playing(tmp_path):
    from gbox import re4_merc_bot as B
    from tests.test_re4_merc_bot import world,PG
    game=world([]);now=[0.];rows=[];stats={}
    def sleep(dt):
        now[0]+=dt
        if now[0]>.1:game.put(B.MERC_TIMER,'>I',0)
    def boundary(body,live):
        rows.append(body);live['mercmode_rotate_requested']=True;return True
    B.play(None,lambda events:None,lambda:now[0]>10,m=game,sleep=sleep,clock=lambda:now[0],
           stats=stats,learn_dir=tmp_path,hooks=lambda:[],ram_prompt=False,round_boundary=boundary)
    assert len(rows)==1 and rows[0]['witness']['screen']=='results'
    assert rows[0]['witness']['timer']==0 and rows[0]['witness']['player_verified']
    assert now[0]<1


def test_engine_reports_terminal_tally_and_never_observation(tmp_path,monkeypatch):
    import json,sqlite3
    from gbox.mercs import engine
    from tests.test_mercs_engine import Clock
    from gbox.mercs import lessons
    monkeypatch.setattr(lessons,'ROOT',tmp_path/'lessons')
    calls=[]
    monkeypatch.setattr(M,'publish_boundary',lambda sink,body,stats:calls.append(body))
    class Driver:
        prompt_unknown=(LookupError,)
        def snapshot(self,m):
            return {'player':{'hp':1000},'timer':0 if clk.t>.1 else 2,'kills':0}
        def screen(self,m,snap):return 'results' if snap['timer']==0 else 'playing'
        def prompt_source(self,m,stats):return None
        def prompt_keys(self,button):return []
        def progress(self,snap):return {'timer':snap['timer']}
        def result_ready(self,snap,now):return True
    class Brain:
        def tick(self,snap):return {'hold':set()}
        def save(self):pass
    def publisher(*args):pass
    publisher.sink=SimpleNamespace(sid='exact-worker-exact-session',client=SimpleNamespace(headers={
        'x-gbox-parent-job':'exact-parent','authorization':'Bearer synthetic-secret-do-not-persist'}))
    for observed in (False,True):
        clk=Clock()
        engine.play_round({'map_id':'G4BE08'},object(),lambda e:None,lambda:clk.t>3,{},
            driver=Driver(),brain=Brain(),clock=clk,sleep=clk.sleep,learn_dir=tmp_path,observe_only=observed,
            tactical=publisher)
    assert len(calls)==1 and calls[0]['witness']['tally_ready']
    with sqlite3.connect(tmp_path/'curriculum/G4BE08/rounds.sqlite') as db:
        rows=[json.loads(raw) for raw, in db.execute('select data from rounds')]
    assert len(rows)==2 and all(row['source_session_id']=='exact-worker-exact-session' for row in rows)
    assert all(row['source_autoplay_job_id']=='exact-parent' for row in rows)
    assert 'synthetic-secret' not in json.dumps(rows)


def test_random_selection_survives_real_typed_launch_handoff():
    from gbox.tools import LaunchIn
    game={'game_id':RE4,'title':'RE4','platform':'gamecube','source_paths':['/owned/re4.iso'],
          'format':'iso','profile_id':'gamecube','launch':{'kind':'rom',
          'mercmode':{'random_characters':True,'random_stages':True}}}
    typed=LaunchIn.model_validate({'game':game}).model_dump()['game']
    assert typed['launch']['mercmode']['random_characters'] is True
    assert typed['launch']['kind']=='rom'


def test_new_host_needs_its_own_rom_access_not_another_hosts_tools(tmp_path):
    from gbox.config import Config
    store,w,*_=rig();w['id']='other'
    rows={r['title']:r for r in M.inventory(store,w)}
    assert rows['re4']['backend_playable'] and not rows['re4']['playable']
    assert 'not been verified' in rows['re4']['reason']
    game={'game_id':RE4,'title':'RE4','platform':'gamecube','source_paths':[],
          'format':'iso','profile_id':'gamecube','launch':{'path':str(tmp_path/'missing.iso')}}
    cfg=Config(data_dir=tmp_path/'data')
    missing=M.inspect_rom_access(cfg,game)
    assert not missing['reachable']
    (tmp_path/'missing.iso').write_bytes(b'owned-fixture')
    found=M.inspect_rom_access(cfg,game)
    assert found['reachable']
    store.put(M.PREPARATION,w['name'],{'games':{RE4:found}})
    assert next(r for r in M.inventory(store,w) if r['title']=='re4')['playable']


def test_unknown_host_access_queues_only_one_readonly_prepare_job_before_any_game():
    store,w,saver,calls,now,tick=rig()
    w.update(id='new-host',tools=['launch_game','autoplay','mercmode'])
    M.configure(store,w['name'],{'enabled':True})
    assert 'checking ROM access' in tick()[w['name']]
    assert calls[0]['tool']=='mercmode' and calls[0]['input']=={'op':'prepare'}
    tick(1)
    assert len(calls)==1 and not store.all(S.STATE)


def delegated_launch(store, launch, *, local='local-launch'):
    """Accepted relay metadata: central launch IDs never replace native SIDs."""
    jid=launch['id'];wid=launch['require_worker'];gid=launch['input']['game']['game_id'];sid=wid+'-'+local
    session={'session_id':sid,'game_id':gid,'adapter':'rpcs3','detail':{'pid':1234},'state':'running',
             'central_launch_job_id':jid,'local_launch_job_id':local,'federation':{'authority':'authority'}}
    job=launch|{'worker_id':wid,'state':'succeeded','output':{'session_id':sid,'adapter':'rpcs3',
               'detail':{'pid':1234,'_game':{'game_id':gid}}}}
    store.put('job',jid,job);store.put('session',sid,session)
    store.put('federation_command',jid,{'authority':'authority','worker_id':wid,'local_job_id':local,
              'local_state':'succeeded','ack':{'accepted':True}})
    store.put('federation_local_job',sid,{'authority':'authority','central_job_id':jid,'local_job_id':local})
    return session


def test_accepted_relay_keeps_native_sid_through_play_and_native_boundary_rotation():
    store,w,saver,calls,now,tick=rig();M.configure(store,w['name'],{'enabled':True})
    tick();session=delegated_launch(store,calls[0])
    assert session['session_id']!='w1-'+calls[0]['id']
    tick(1);tick(S.START_GRACE)
    run=store.get(S.STATE,w['name']);job=calls[-1]|{'state':'succeeded'}
    assert run['phase']=='playing' and run['session_id']==session['session_id']
    assert calls[-1]['tool']=='autoplay' and calls[-1]['input']['session_id']==session['session_id']
    S.telemetry_put(session['session_id'],{'running':True,'stats':{}},now=now[0])
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is True
    tick(1)
    assert calls[-1]['tool']=='session_op' and calls[-1]['input']['session_id']==session['session_id']


@pytest.mark.parametrize('kind,key,patch',[
    ('job','0',{'state':'running'}),('job','0',{'worker_id':'other'}),
    ('session','w1-local-launch',{'game_id':RE5+'other'}),
    ('session','w1-local-launch',{'central_launch_job_id':'other'}),
    ('session','w1-local-launch',{'detail':{'pid':9999}}),
    ('federation_command','0',{'local_job_id':'another'}),
    ('federation_command','0',{'ack':{'accepted':False}}),
    ('federation_local_job','w1-local-launch',{'authority':'other'}),
])
def test_unaccepted_or_mismatched_relay_never_adopts_same_game(kind,key,patch):
    store,w,saver,calls,now,tick=rig();M.configure(store,w['name'],{'enabled':True})
    tick();session=delegated_launch(store,calls[0])
    store.put(kind,key,store.get(kind,key)|patch)
    tick(1);tick(S.START_GRACE)
    assert len(calls)==1 and store.get(S.STATE,w['name'])['phase']=='launching'
    assert store.get('slabel',session['session_id']) is None


def test_explicit_bot_demo_pending_and_badge_use_only_exact_accepted_relay():
    store,w,saver,calls,now,tick=rig()
    store.put('setting',S.SETTING,S.settings(store)|{'enabled':False})
    launch={'id':'central','tool':'launch_game','require_worker':w['id'],'input':{'game':{'game_id':RE5}}}
    session=delegated_launch(store,launch)
    S.autoplay_on_launch(store,'central',RE5)
    assert S.bot_demo(store,session['session_id'])['central_launch_job_id']=='central'
    tick(1);tick(S.START_GRACE)
    assert len(calls)==1 and calls[0]['tool']=='autoplay'
    assert calls[0]['input']['session_id']==session['session_id']
    assert store.all(S.PENDING)==[]
    store.put('federation_command','central',store.get('federation_command','central')|{'local_job_id':'other'})
    assert S.bot_demo(store,session['session_id']) is None


def test_federation_never_bypasses_mapping_when_local_and_central_ids_coincide():
    store,w,saver,calls,now,tick=rig();M.configure(store,w['name'],{'enabled':True})
    tick();session=delegated_launch(store,calls[0],local=calls[0]['id'])
    store.delete('federation_local_job',session['session_id'])
    tick(1);tick(S.START_GRACE)
    assert len(calls)==1 and store.get(S.STATE,w['name'])['phase']=='launching'


def test_re4_disc_access_never_transfers_between_catalog_ids():
    import time
    store,w,*_=rig();alternate=M.TITLES['re4']['game_ids'][1]
    store.delete('session','w1-prior-re4')
    store.put('session','w1-alt',{'session_id':'w1-alt','game_id':alternate,'state':'ended'})
    row=next(r for r in M.inventory(store,w) if r['title']=='re4')
    assert row['playable'] and row['game_id']==alternate
    assert row['rom_access']['session_id']=='w1-alt'
    # A fresh failed check supersedes only that disc's historic launch evidence.
    store.put(M.PREPARATION,w['name'],{'games':{alternate:{'reachable':False,'checked_at':time.time()}}})
    assert not next(r for r in M.inventory(store,w) if r['title']=='re4')['playable']
    store.put(M.PREPARATION,w['name'],{'games':{RE4:{'reachable':True,'checked_at':time.time()},
        alternate:{'reachable':False,'checked_at':time.time()}}})
    row=next(r for r in M.inventory(store,w) if r['title']=='re4')
    assert row['playable'] and row['game_id']==RE4


def test_registered_prepare_uses_real_typed_catalog_path_for_each_verified_disc(tmp_path,monkeypatch):
    import json
    import httpx
    from gbox.config import Config
    from gbox.mercmode_tool import MercModeIn,mercmode
    alternate=M.TITLES['re4']['game_ids'][1];owned=tmp_path/'owned.gcz';owned.write_bytes(b'owned-fixture')
    requests=[];posted=[];Client=httpx.Client
    def transport(request):
        requests.append((request.method,request.url.path))
        if request.method=='GET':
            gid=request.url.path.rsplit('/',1)[-1]
            if gid!=alternate:return httpx.Response(404)
            return httpx.Response(200,json={'game_id':gid,'title':'RE4 Disc2','platform':'gamecube',
                'format':'gcz','profile_id':'gamecube','source_paths':[], 'launch':{'path':str(owned)}})
        posted.append(json.loads(request.content))
        return httpx.Response(200,json={'saved':True})
    monkeypatch.setattr(httpx,'Client',lambda **kw:Client(transport=httpx.MockTransport(transport),**kw))
    cfg=Config(data_dir=tmp_path/'data',cache_dir=tmp_path/'cache')
    result=mercmode(MercModeIn(op='prepare'),SimpleNamespace(server='http://fixture',headers={},worker='w1',config=cfg))
    assert result['result']['saved'] is True
    assert requests==[('GET','/api/catalog/'+gid) for gid in (RE4,alternate,RE5)]+[('POST','/api/mercmode/preparation')]
    assert posted[0]['worker_id']=='w1' and posted[0]['result']['games'][alternate]['reachable'] is True
    assert posted[0]['result']['emulator_launched'] is False
    assert posted[0]['result']['configuration_changed'] is False


def prepared_relay():
    import time
    store,w,*_=rig();w['id']='new-host';stamp=time.time()-1
    receipt={'checked_at':stamp,'emulator_launched':False,'configuration_changed':False,
        'games':{RE5:{'reachable':True,'checked_at':stamp,'path':'/owned/RE5.7z','reason':''}}}
    job={'id':'prepare-exact','state':'succeeded','tool':'mercmode','input':{'op':'prepare'},
        'worker_id':w['id'],'require_worker':w['id'],'output':{'result':{
        'saved':True,'host':w['name'],'preparation':receipt}}}
    store.put(M.PREPARATION,w['name'],{'job':job['id'],'state':'checking'})
    store.put('job',job['id'],job)
    return store,w,job,receipt


def test_only_requested_completed_prepare_job_can_supply_central_host_readiness():
    store,w,job,receipt=prepared_relay()
    row=next(r for r in M.inventory(store,w) if r['title']=='re5')
    assert row['playable'] and row['rom_access']['source']=='worker_local_path_probe'
    assert M.host_preparation(store,w)['state']=='checked'
    assert store.get(M.PREPARATION,w['name'])['state']=='checking'  # read-only derived receipt
    store.put(M.PREPARATION,w['name'],{'job':'another-job'})
    assert not next(r for r in M.inventory(store,w) if r['title']=='re5')['playable']


@pytest.mark.parametrize('field,value',[
    ('state','running'),('worker_id','other-host'),('require_worker','other-host'),
    ('tool','launch_game'),('input',{'op':'status'}),
])
def test_foreign_or_incomplete_prepare_job_never_proves_host_access(field,value):
    store,w,job,receipt=prepared_relay();store.put('job',job['id'],job|{field:value})
    assert not next(r for r in M.inventory(store,w) if r['title']=='re5')['playable']


@pytest.mark.parametrize('change',[
    {'emulator_launched':True},{'configuration_changed':True},{'checked_at':float('nan')},
    {'checked_at':float('inf')},{'checked_at':0},{'games':{'unknown-game':{}}},
    {'games':{RE5:{'reachable':True,'checked_at':0,'path':'/owned/RE5.7z'}}},
    {'games':{RE5:{'reachable':True,'checked_at':float('inf'),'path':'/owned/RE5.7z'}}},
    {'games':{RE5:{'reachable':True,'checked_at':1,'path':'x'*9000}}},
])
def test_nonfinite_stale_oversized_or_mutating_preparation_receipts_are_ignored(change):
    store,w,job,receipt=prepared_relay()
    job['output']['result']['preparation']=receipt|change;store.put('job',job['id'],job)
    assert not next(r for r in M.inventory(store,w) if r['title']=='re5')['playable']


def test_paired_local_scheduler_alone_starts_new_games_and_explicit_demos():
    store,w,saver,calls,now,tick=rig();M.configure(store,w['name'],{'enabled':True})
    w['federation']={'authority':'authority','scheduler_owner':'local'}
    assert 'local control plane' in tick()[w['name']] and not calls
    launch={'id':'central','tool':'launch_game','require_worker':w['id'],'input':{'game':{'game_id':RE5}}}
    delegated_launch(store,launch)
    S.autoplay_on_launch(store,'central',RE5)
    tick(1);tick(S.START_GRACE)
    assert not calls and len(store.all(S.PENDING))==1


def test_pairing_does_not_take_over_or_abandon_an_existing_central_owned_run():
    store,w,saver,calls,now,tick,run,job=playing()
    w['federation']={'authority':'authority','scheduler_owner':'local'}
    tick(1)
    assert store.get(S.STATE,w['name'])['session_id']==run['session_id']
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is True
    tick(1)
    assert calls[-1]['tool']=='session_op'


def test_only_exact_paired_observations_set_actual_status_not_pending_desired():
    store,w,saver,calls,now,tick=rig()
    w['federation']={'authority':'authority','scheduler_owner':'local'}
    desired=M.configure(store,w['name'],{'enabled':True})
    actual=M.normalize({'enabled':False})
    store.put(M.OBSERVED,w['name'],{'authority':'authority','worker_id':w['id'],'at':now[0],
        'settings':actual,'history':{},'preparation':{}})
    host=saver.status()['mercmode']['hosts'][0]
    assert host['settings']==actual and host['desired_settings']==desired
    assert host['scheduler_owner']=='local' and host['settings_source']=='local_scheduler_observation'
    store.put(M.OBSERVED,w['name'],{'authority':'other','worker_id':w['id'],'settings':actual})
    host=saver.status()['mercmode']['hosts'][0]
    assert host['settings']['enabled'] is False and host['settings_source']=='unobserved_local_scheduler'
    assert host['desired_settings']==desired


def test_central_settings_delegate_once_and_manual_prepare_tracks_exact_job(cfg):
    import time
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app=create_app(cfg);store=app.state.store
    w=worker(time.time(),name='LocalOwner',os='linux')
    store.put('worker',w['id'],w|{'last_seen':time.time(),'tools':['mercmode','launch_game','autoplay'],
        'federation':{'authority':'authority','scheduler_owner':'local'}})
    client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token()})
    for _ in range(2):
        response=client.post('/api/mercmode',json={'host':w['name'],'enabled':True,'titles':['re5']})
        assert response.status_code==200,response.text
        assert response.json()['hosts'][0]['settings']['enabled'] is False
        assert response.json()['hosts'][0]['desired_settings']['enabled'] is True
    jobs=[job for job in store.all('job') if job['tool']=='mercmode']
    assert len(jobs)==1 and jobs[0]['require_worker']==w['id']
    assert jobs[0]['input']=={'op':'configure','host':w['name'],'enabled':True,
        'titles':['re5'],'rounds_per_title':1,'presentation_priority':False}
    assert store.get(M.COMMAND,w['name'])['job']==jobs[0]['id']
    response=client.post('/api/mercmode/prepare',json={'worker_id':w['id']})
    assert response.status_code==200,response.text
    pending=store.get(M.PREPARATION,w['name']);prepared=store.get('job',pending['job'])
    assert prepared['tool']=='mercmode'
    assert {key:value for key,value in prepared['input'].items() if value is not None}=={'op':'prepare'}
    assert all(prepared['input'].get(key) is None for key in ('enabled','host','rounds_per_title','titles'))
    assert prepared['require_worker']==w['id'] and response.json()['job_id']==prepared['id']


def test_native_handover_cancels_only_queued_owned_stops_after_rotation_state_was_removed():
    store,w,saver,calls,now,tick,run,job=playing()
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is True
    tick(1)
    stop=calls[-1]|{'actor':S.ACTOR};store.put('job',stop['id'],stop)
    assert store.get(S.STATE,w['name']) is None
    controls=[stop|{'id':'operator','actor':'operator'},stop|{'id':'offered','state':'running'},
        stop|{'id':'foreign','require_worker':'another'},
        stop|{'id':'other-sid','input':{'session_id':'w1-other','op':'stop_game'}}]
    for control in controls:store.put('job',control['id'],control)
    assert saver.yield_to_operator(run['session_id'],'native pad') is True
    assert store.get('job',stop['id'])['state']=='cancelled'
    assert store.get('slabel',run['session_id'])['owner']=='you'
    for control in controls:assert store.get('job',control['id'])['state']==control['state']
    assert saver.yield_to_operator(run['session_id'],'duplicate native pad') is True
