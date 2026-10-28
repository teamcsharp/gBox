"""Native-round scheduling and exact-host selection, with no emulator processes."""
import copy
import random
from types import SimpleNamespace

import pytest

from gbox import mercmode as M, screensaver as S
from tests.test_screensaver import GIB, Store as BaseStore, worker


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
             'require_worker':req.require_worker,'agent_use':req.agent_use,'actor':actor}
        calls.append(job);store.put('job',job['id'],job);return job
    saver=S.Screensaver(store,SimpleNamespace(runs=lambda **kw:[]),submit,lambda:[w],rng=random.Random(4))
    def tick(dt=0):
        now[0]+=dt;w['resources']['sampled_at']=now[0];return saver.tick(now[0])
    return store,w,saver,calls,now,tick


def playing():
    store,w,saver,calls,now,tick=rig()
    M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
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
    M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
    sid='w1-current'
    session={'session_id':sid,'game_id':RE5,'state':'running','adapter':'rpcs3',
             'started':now[0]-20,'detail':{'pid':1234}}
    store.put('session',sid,session)
    store.put('job','current',{'id':'current','tool':'launch_game','state':'succeeded','actor':'operator',
        'agent_use':False,'created':now[0]-20,'worker_id':w['id'],'require_worker':w['id'],
        'input':{'game':{'game_id':RE5}},'output':{'session_id':sid}})
    job={'id':'active','tool':'autoplay','state':'succeeded','worker_id':w['id'],
         'require_worker':w['id'],'created':now[0]-10,'input':{'op':'start','session_id':sid}}
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
    assert len(store.all('job'))==2
    assert run['job']=='current' and store.get(M.ADOPTION,session['session_id'])['id']==run['warm_adoption']


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


def test_rotation_survives_only_registered_same_host_worker_restart_alias():
    store,w,saver,calls,now,tick,run,job=playing()
    saver.round_boundary(boundary(run,now[0]),job,now[0]);tick(1)
    old=store.get('session',run['session_id']);store.put('session',run['session_id'],old|{'state':'ended'})
    w['id']='freshworker'
    assert M.rotation_predecessor(store,w,now[0]) is None
    store.put('worker_alias','w1',{'to':w['id'],'name':'different-pc'})
    assert M.rotation_predecessor(store,w,now[0]) is None
    store.put('worker_alias','w1',{'to':w['id'],'name':w['name']})
    prior=M.rotation_predecessor(store,w,now[0])
    assert prior['source_worker_id']=='w1' and prior['worker_id']==w['id']
    launch={'id':'fresh-launch','tool':'launch_game','state':'succeeded','worker_id':w['id'],
        'require_worker':w['id'],'input':{'game':{'game_id':RE4}}}
    store.put('job',launch['id'],launch)
    newrun={'worker':w['name'],'worker_id':w['id'],'job':launch['id'],'game_id':RE4,
        'mercmode':{'title':'re4'},'mercmode_predecessor':prior}
    live={'session_id':w['id']+'-'+launch['id'],'game_id':RE4,'state':'running'}
    assert M.link_rotation(store,newrun,live,now[0])
    receipt=store.get('session',run['session_id'])['mercmode_rotation']
    assert receipt['source_worker_id']=='w1' and receipt['worker_id']==w['id']


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
    # the bots' stalemate rule rides along (gbox.mercs.stalemate: default on, the clock cut to 5 s); no modifiers do
    assert launch['game']['launch']['mercmode']=={'random_characters':True,'random_stages':True,
                                                  'stalemate_cut':True,'stalemate_cut_s':5}
    assert set(launch)=={'game','jump','memory_cards'}
    assert run['mercmode']['title'] in ('re4','re5')
    M.configure(store,w['name'],{'rounds_per_title':20})    # an hour of rounds, a boundary every 5 min (without any,
    for i in range(12):                                      # the no-progress watchdog would end the turn after 10)
        tick(5*60)
        S.telemetry_put(run['session_id'],{'running':True,'stats':{}},now=now[0])
        assert saver.round_boundary(boundary(run,now[0])|{'round_id':f'{i+1:032x}'},job,now[0])['saved'] is True
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


def test_a_turn_without_a_round_boundary_for_ten_minutes_ends_like_a_finished_turn():
    # 2026-10-27: RE4 resumed on its last Result screen, its reader called that a round and the bot "played" it for 24
    # minutes; nothing rotated MercMode until a service restart. Only accepted boundaries count as progress.
    store,w,saver,calls,now,tick,run,job=playing()
    sid=run['session_id']
    for _ in range(3):                                           # the bot is busy (turning, prompts): not progress
        tick(S.NO_PROGRESS_S/4)
        S.telemetry_put(sid,{'running':True,'stats':{'act':'turn','prompts':1499}},now=now[0])
    assert store.get(S.STATE,w['name'])['phase']=='playing' and calls[-1]['tool']=='autoplay'
    tick(S.NO_PROGRESS_S/4+1)
    assert calls[-1]['tool']=='session_op' and calls[-1]['input']=={'session_id':sid,'op':'stop_game','args':{}}
    assert store.get(S.STATE,w['name']) is None
    ended=[r for r in store.all(S.LOG) if r.get('session_id')==sid][-1]
    assert ended['why']==S.NO_PROGRESS.format(minutes=S.NO_PROGRESS_S/60)
    assert ended['mercmode_no_progress']['idle_s']>=S.NO_PROGRESS_S
    store.put('session',sid,{'session_id':sid,'state':'ended'})
    tick(1)
    assert calls[-1]['tool']=='launch_game' and calls[-1]['input']['game']['game_id']!=run['game_id']   # the next title


def test_the_no_progress_watchdog_counts_boundaries_and_never_cuts_the_operator():
    store,w,saver,calls,now,tick,run,job=playing()
    M.configure(store,w['name'],{'rounds_per_title':5})         # one round does not end the turn here
    sid=run['session_id']
    tick(S.NO_PROGRESS_S-60)
    S.telemetry_put(sid,{'running':True,'stats':{}},now=now[0])
    assert saver.round_boundary(boundary(run,now[0])|{'round_id':'c'*32},job,now[0])['saved'] is True
    tick(S.NO_PROGRESS_S-60)                                     # a boundary 9 min ago: still progressing
    assert store.get(S.STATE,w['name'])['phase']=='playing' and calls[-1]['tool']!='session_op'
    S.telemetry_put(sid,{'running':True,'stats':{'operator_control':True}},now=now[0]+120)
    tick(120)                                                    # 11 min, but the operator holds the pad
    assert store.get(S.STATE,w['name'])['phase']=='playing' and calls[-1]['tool']!='session_op'
    for flag in ({'handover':'mouse'},{'mercmode_pinned':True}):
        store2,w2,saver2,calls2,now2,tick2,run2,job2=playing()
        store2.put(S.STATE,w2['name'],store2.get(S.STATE,w2['name'])|flag)
        assert saver2._no_progress(w2,store2.get(S.STATE,w2['name']),now2[0]+S.NO_PROGRESS_S+1) is None


def test_a_switch_edition_run_accepts_round_boundaries_naming_its_own_title_id():
    # 2026-10-26: an RE5 Switch No Mercy run's boundaries name 010018100CD46000 (its RAM profile id), and accept_boundary
    # compared them with the PS3 BLUS30491 only: no round would have counted and the turn would never rotate
    from gbox import re_switch
    store,w,saver,calls,now,tick,run,job=playing()
    run=store.get(S.STATE,w['name']);run['mercmode']=dict(run['mercmode'],title='re5',map_id=re_switch.RE5_TITLE_ID)
    store.put(S.STATE,w['name'],run)
    body=boundary(run,now[0])
    assert M.accept_boundary(store,run,body,parent_job=job,now=now[0])['map_id']==re_switch.RE5_TITLE_ID
    with pytest.raises(ValueError):                                         # the other edition's id is not this run's
        M.accept_boundary(store,run,body|{'map_id':'BLUS30491','round_id':'b'*32},parent_job=job,now=now[0])


def test_the_switch_round_receipt_names_the_switch_title_id():
    from gbox import re_switch, tools
    assert tools._prepare_title({'game_id':re_switch.RE5_GAME_ID,'title':'Resident Evil 5'})==re_switch.RE5_TITLE_ID
    assert tools._prepare_title({'game_id':RE5,'title':'Resident Evil 5 - Gold Edition'})=='BLUS30491'


def test_autobot_restarted_inside_the_owned_session_keeps_rotating():
    """The operator's F3 / "Take control" or the bot's hang relaunch starts autoplay again under a new job; the
    game, worker and session are the same, so its native boundaries still rotate (live 2026-10-24: 422s)."""
    store,w,saver,calls,now,tick,run,job=playing()
    store.put('job',job['id'],job|{'created':now[0]-60})
    later={'id':'restart','tool':'autoplay','state':'succeeded','actor':'operator','worker_id':w['id'],
           'require_worker':w['id'],'input':{'session_id':run['session_id'],'op':'start'},'created':now[0]-5}
    store.put('job','restart',later)
    with pytest.raises(ValueError,match='does not belong'):     # not later than the accepted job: not a restart
        saver.round_boundary(boundary(run,now[0]),later|{'id':'stale','created':now[0]-61},now[0])
    assert saver.round_boundary(boundary(run,now[0]),later,now[0])=={'saved':True,'rotate_requested':True}
    assert store.get(S.STATE,w['name'])['autoplay_job']=='restart'
    foreign=later|{'id':'elsewhere','input':{'session_id':'w1-other','op':'start'}}
    with pytest.raises(ValueError,match='does not belong'):
        saver.round_boundary(boundary(run,now[0])|{'round_id':'c'*32},foreign,now[0])
    other_pc=later|{'id':'otherpc','require_worker':'w2','worker_id':'w2'}
    with pytest.raises(ValueError,match='does not belong'):
        saver.round_boundary(boundary(run,now[0])|{'round_id':'d'*32},other_pc,now[0])


def test_one_ready_title_keeps_warm_session_and_native_character_cycle():
    store,w,saver,calls,now,tick,run,job=playing()
    M.configure(store,w['name'],{'titles':[run['mercmode']['title'],'re6']})
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False
    tick(1)
    assert len(calls)==2


def test_turning_mercmode_off_keeps_same_bot_and_game_even_if_screensaver_is_off():
    store,w,saver,calls,now,tick,run,job=playing()
    store.put('setting',S.SETTING,S.settings(store)|{'enabled':False})
    M.configure(store,w['name'],{'enabled':False})
    tick(1);tick(4000)
    kept=store.get(S.STATE,w['name'])
    assert kept['session_id']==run['session_id'] and kept['autoplay_job']==job['id']
    assert kept['mercmode_pinned'] and len(calls)==2
    S.telemetry_put(run['session_id'],{'running':True,'stats':{}},now=now[0])
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False
    tick(1)
    assert len(calls)==2
    M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
    store.put('setting',S.SETTING,S.settings(store)|{'enabled':True})
    tick(1)
    body=boundary(run,now[0])|{'round_id':'b'*32}
    assert saver.round_boundary(body,job,now[0])['rotate_requested'] is True
    tick(1)
    assert calls[-1]['input']['op']=='stop_game'


def test_disabling_after_native_rotation_receipt_resumes_same_game_once_when_bot_stops():
    store,w,saver,calls,now,tick,run,job=playing()
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested']
    M.configure(store,w['name'],{'enabled':False})
    tick(1)
    assert len(calls)==2
    S.telemetry_put(run['session_id'],{'running':False,'stats':{'mercmode_rotate_requested':True}},now=now[0])
    tick(1);tick(1)
    assert len(calls)==3
    assert calls[-1]['tool']=='autoplay' and calls[-1]['input']['session_id']==run['session_id']
    assert not any(c['tool']=='session_op' for c in calls)


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
    game=world([],timer_s=2.0);now=[0.];rows=[];stats={}   # the round's last seconds: the clock runs down to 0
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
    M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
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
    store,w,saver,calls,now,tick=rig();M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
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
    store,w,saver,calls,now,tick=rig();M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
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
    store,w,saver,calls,now,tick=rig();M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
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
    from gbox import re_switch
    switch=(re_switch.RE5_GAME_ID,re_switch.RE6_GAME_ID)   # the Switch No Mercy editions a host may prefer
    merc3d=M.TITLES['merc3d']['game_ids']                    # the 3DS title the i9 loops (2026-10-27)
    assert requests==[('GET','/api/catalog/'+gid) for gid in (RE4,alternate,RE5,*switch,*merc3d)]+[('POST','/api/mercmode/preparation')]
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
    store,w,saver,calls,now,tick=rig();M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
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
    desired=M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
    actual=M.normalize({'enabled':False})
    store.put(M.OBSERVED,w['name'],{'authority':'authority','worker_id':w['id'],'at':now[0],
        'settings':actual,'history':{},'preparation':{}})
    host=saver.status()['mercmode']['hosts'][0]
    assert host['settings']==actual and host['desired_settings']==desired
    assert host['scheduler_owner']=='local' and host['settings_source']=='local_scheduler_observation'
    store.put(M.OBSERVED,w['name'],{'authority':'other','worker_id':w['id'],'settings':actual})
    saver._status_cache=(0.0,None)                           # the shared status copy lasts STATUS_TTL_S
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
        'titles':['re5'],'rounds_per_title':1,'presentation_priority':False,'queue':[]}
    # no keep_warm for a worker without the warm feature: an older mercmode tool forbids unknown fields
    assert store.get(M.COMMAND,w['name'])['settings']['keep_warm']==1                     # the default, still desired
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


def test_dj_queue_validates_rounds_against_each_titles_roster():
    store,w,saver,calls,now,tick=rig()
    cfg=M.configure(store,w['name'],{'queue':[{'title':'re5','mode':'mercenaries','character':'Wesker (STARS)','stage':7},
                                              {'title':'re4','character':'HUNK'},{'title':'re4'}]})
    assert [e['title'] for e in cfg['queue']]==['re5','re4','re4'] and cfg['queue'][1]['stage'] is None
    for bad in ({'title':'re4','character':'Chris (BSAA)'},{'title':'re5','stage':8},{'title':'re5','mode':'story'},
                {'title':'re6','character':'Wesker'},{'title':'re6','stage':10},{'title':'nope'},{'title':'re4','extra':1}):
        with pytest.raises(ValueError):M.configure(store,w['name'],{'queue':[bad]})
    with pytest.raises(ValueError,match='at most'):M.configure(store,w['name'],{'queue':[{'title':'re4'}]*21})
    sel=M.resolve_selection({'title':'re4','mode':None,'character':None,'stage':None},random.Random(1))
    assert sel['mode']=='mercenaries' and sel['character'] in M.catalog()['re4']['modes']['mercenaries'] and 0<=sel['stage']<4
    cfg=M.configure(store,w['name'],{'queue':[{'title':'re6','character':'Chris','stage':3},{'title':'re6'}]})  # RE6 Switch
    assert cfg['queue'][0]=={'title':'re6','mode':None,'character':'Chris','stage':3}
    sel=M.resolve_selection(cfg['queue'][1],random.Random(2))
    assert sel['mode']=='no_mercy' and sel['character'] in M.catalog()['re6']['modes']['no_mercy'] and 0<=sel['stage']<10
    assert sel['stage_name']==M.catalog()['re6']['stages'][sel['stage']]


def test_dj_queue_launches_the_queued_game_with_its_selection_and_pops_it():
    store,w,saver,calls,now,tick=rig()
    M.configure(store,w['name'],{'enabled':True,'titles':['re4'],
        'queue':[{'title':'re5','mode':'reunion','character':'Barry','stage':2},{'title':'re4','character':'Ada','stage':1}]})
    tick()
    launch=calls[0]['input']['game']
    assert launch['game_id']==RE5                  # the DJ's pick even though only RE4 is checked for rotation
    sel=launch['launch']['mercmode']['selection']
    assert (sel['mode'],sel['character'],sel['stage'],sel['stage_name'])==('reunion','Barry',2,'Village')
    assert [e['title'] for e in M.settings(store,w['name'])['queue']]==['re4']
    assert store.get(S.STATE,w['name'])['mercmode']['selection']['character']=='Barry'


def test_dj_queue_same_game_next_sends_the_selection_without_relaunching():
    store,w,saver,calls,now,tick,run,job=playing()
    title=run['mercmode']['title']
    pick={'title':title,'character':'Ada','stage':1} if title=='re4' else {'title':title,'mode':'reunion','character':'Josh','stage':3}
    M.configure(store,w['name'],{'queue':[pick]})
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False
    sent=calls[-1]
    assert sent['tool']==('re_mods' if title=='re4' else 're5_mods') and sent['input']['op']=='mercs_select'
    assert sent['input']['session_id']==run['session_id'] and sent['input']['character']==pick['character']
    assert M.settings(store,w['name'])['queue']==[]


def test_dj_queue_other_game_next_rotates_after_this_round_regardless_of_rounds_per_title():
    store,w,saver,calls,now,tick,run,job=playing()
    other='re5' if run['mercmode']['title']=='re4' else 're4'
    M.configure(store,w['name'],{'rounds_per_title':5,'queue':[{'title':other}]})
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is True


def test_re4_menu_layer_honours_a_requested_round_once_then_returns_to_random():
    from gbox import re4_menus as R
    sel=R.RandomSelections(rng=random.Random(3),key='ad1')
    R.request('ad1','Wesker',3)
    import unittest.mock as um
    with um.patch.object(R,'screen',side_effect=[{'where':'select_player'},{'where':'select_stage'},{'where':'playing'}]):
        assert sel.screen(None)['target']==4 and sel.screen(None)['target']==3
        sel.screen(None)
    assert 'ad1' not in R.REQUESTS
    with pytest.raises(ValueError):R.request('ad1','Leon',9)



# --- warm pool: the next title boots paused beside the playing one as soon as it is up, has its round prepared in the
# background, and is swapped in - already in gameplay - at the round boundary ---

def warm_playing(features=(M.WARM_FEATURE,),memory=None,**cfg):
    store,w,saver,calls,now,tick=rig()
    w['features']=list(features)
    if memory is not None:w['resources']['memory_available_bytes']=memory
    M.configure(store,w['name'],{'enabled':True,**cfg})                    # keep_warm 1 is the default
    tick();gid=calls[0]['input']['game']['game_id']
    sid='w1-'+calls[0]['id']
    store.put('session',sid,{'session_id':sid,'game_id':gid,'state':'running'})
    tick(1);tick(S.START_GRACE)
    run=store.get(S.STATE,w['name'])
    job=store.get('job',run['autoplay_job'])|{'state':'succeeded'}
    store.put('job',job['id'],job)
    clock(run,now,200)
    return store,w,saver,calls,now,tick,run,job


def clock(run,now,left):
    S.telemetry_put(run['session_id'],{'running':True,'stats':{'screen':'playing','timer':left}},now=now[0])


def preloads(calls):
    """The warm preloads submitted so far (launch_game warm=true), oldest first."""
    return [c for c in calls if c['tool']=='launch_game' and c['input'].get('warm') is True]


def prepares(calls,sid=None):
    """The round preparations submitted so far (autoplay op=prepare)."""
    return [c for c in calls if c['tool']=='autoplay' and c['input'].get('op')=='prepare'
            and (sid is None or c['input']['session_id']==sid)]


ROUND_READY={'state':'ready','ready':True,'paused':True,'prepared':True,'source':'native_round','screen':'playing'}


def round_ready(store,sid,title,prep=None,**fields):
    """The worker's receipt: this warm game's menus were driven to the first frame of a round and it is paused there
    (stamped with its prepare job when `prep` is given, as the worker does)."""
    receipt=ROUND_READY|{'title':M.TITLES[title]['map_id'],'character':'Ada','stage':'Castle','stage_index':1}\
        |({'job':prep['id']} if prep else {})|fields
    store.put('session',sid,store.get('session',sid)|{'detail':{'warm':receipt}})
    return receipt


def up(store,launch,w,paused=True):
    """The worker finished a warm launch: its session runs, paused (detail.warm) unless the emulator could not."""
    sid='w1-'+launch['id']
    store.put('session',sid,{'session_id':sid,'game_id':launch['input']['game']['game_id'],'state':'running'})
    title=next(spec['map_id'] for spec in M.TITLES.values() if launch['input']['game']['game_id'] in spec['game_ids'])
    store.put('job',launch['id'],store.get('job',launch['id'])|{'state':'succeeded','worker_id':w['id'],
        'output':{'session_id':sid,'detail':{'warm':{'paused':paused,'ready':paused,'state':'ready' if paused else 'failed',
                                                   'source':'native_menu','title':title}}}})
    return sid


def owned(store,w,title,key,now,state='parked'):
    """A pool game this scheduler launched on this PC (exact launch job: actor, agent_use, worker)."""
    gid=M.TITLES[title]['game_ids'][0];sid=w['id']+'-'+key
    store.put('job',key,{'id':key,'tool':'launch_game','state':'succeeded','actor':S.ACTOR,'agent_use':True,
        'require_worker':w['id'],'worker_id':w['id'],'input':{'game':{'game_id':gid},'warm':True},
        'output':{'session_id':sid,'detail':{'warm':{'paused':True,'ready':True,'state':'ready',
                                                   'source':'native_menu','title':M.TITLES[title]['map_id']}}}})
    store.put('session',sid,{'session_id':sid,'game_id':gid,'state':'running'})
    M.keep_warm(store,w['name'],title,{'session_id':sid,'game_id':gid,'job':key,'worker_id':w['id'],'state':state,'at':now})
    return sid


def ops(calls,sid,op=None):
    return [c for c in calls if c['tool']=='session_op' and c['input']['session_id']==sid and (op is None or c['input']['op']==op)]


def preloaded(**cfg):
    """A title plays and the next one's preload is on its way (submitted as soon as the playing one came up)."""
    store,w,saver,calls,now,tick,run,job=warm_playing(**cfg)
    return store,w,saver,calls,now,tick,run,job,preloads(calls)[-1]


def test_next_title_preloads_paused_beside_the_playing_one_as_soon_as_it_is_up():
    # operator 2026-10-24: "precaching of the next rom during the playing of the current rom"; 2026-10-26 (after a service
    # restart left the pool cold): the pool boots at once, not only when the first title's last round plays
    store,w,saver,calls,now,tick=rig()
    w['features']=[M.WARM_FEATURE];M.configure(store,w['name'],{'enabled':True,'rounds_per_title':5})
    tick();sid='w1-'+calls[0]['id']
    store.put('session',sid,{'session_id':sid,'game_id':calls[0]['input']['game']['game_id'],'state':'running'})
    assert not preloads(calls)                                               # nothing until this title's session is up
    tick(1)
    pre=preloads(calls)[-1];run=store.get(S.STATE,w['name'])
    assert run['phase']=='starting' and run['mercmode_prelaunch']['job']==pre['id']   # booted beside it, before autoplay even started
    assert not [c for c in calls if c['tool']=='autoplay']
    assert pre['actor']==S.ACTOR and pre['agent_use']
    assert pre['input']['warm'] is True and pre['input']['keep_sessions']==[sid]   # never closes this game
    assert pre['input']['game']['game_id']!=run['game_id']
    nxt=store.get(M.NEXT,w['name'])['title']
    assert pre['input']['game']['game_id'] in M.TITLES[nxt]['game_ids']
    assert M.warm_pool(store,w['name'])[nxt]['state']=='prelaunch'
    tick(S.START_GRACE);run=store.get(S.STATE,w['name']);clock(run,now,600);tick(1);clock(run,now,20);tick(1)
    assert preloads(calls)==[pre]                                            # preloaded once per run
    assert store.get(S.STATE,w['name'])['session_id']==sid                   # the current title plays on
    assert not ops(calls,sid,'pause') and not ops(calls,sid,'stop_game')
    assert len(store.all('job'))==3                                          # the launch, its preload, autoplay: nothing else


def test_preloaded_title_is_swapped_in_at_the_round_boundary_without_a_cold_boot():
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title'];title=run['mercmode']['title']
    psid=up(store,pre,w);tick(1)
    assert M.warm_pool(store,w['name'])[nxt]['session_id']==psid
    assert store.get('slabel',psid)['warm'] and store.get('slabel',psid)['owner']=='agent'   # labelled, not current
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is True
    launches=len([c for c in calls if c['tool']=='launch_game'])
    tick(1)                                                                  # the park and the swap in one tick (no 30 s gap)
    assert ops(calls,run['session_id'])[-1]['input']=={'session_id':run['session_id'],'op':'pause','args':{'warm':True}}
    assert not ops(calls,run['session_id'],'stop_game')                      # parked, never closed
    assert M.warm_pool(store,w['name'])[title]['state']=='parked'
    cur=store.get(S.STATE,w['name'])
    assert cur['session_id']==psid and cur['phase']=='starting' and cur['mercmode']['title']==nxt
    assert cur['warm_from']=='prelaunch'                                     # a live game: the PiP shows no loading screen
    assert ops(calls,psid)[-1]['input']=={'session_id':psid,'op':'resume','args':{'warm':False}}
    assert len([c for c in calls if c['tool']=='launch_game'])==launches     # no cold boot
    assert nxt not in M.warm_pool(store,w['name']) and store.get(M.NEXT,w['name']) is None
    assert store.get('slabel',psid)['task'].startswith('autoplay screensaver') and not store.get('slabel',psid).get('warm')
    tick(1)
    assert calls[-1]['tool']=='session_op'                                   # autoplay waits for the resume
    resume=ops(calls,psid,'resume')[-1];store.put('job',resume['id'],resume|{'state':'succeeded'})
    tick(1)
    assert calls[-1]['tool']=='autoplay' and calls[-1]['input']['session_id']==psid
    assert store.get(S.STATE,w['name'])['phase']=='playing'
    logged=[r for r in store.all(S.LOG) if r.get('session_id')==run['session_id']]
    assert logged and logged[-1]['mercmode_kept_warm'] and logged[-1]['why']=='verified native round boundary: next MercMode title'


def test_successful_launch_waits_for_live_native_readiness_before_rotation():
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    psid=up(store,pre,w,paused=False)
    loading={'state':'loading','ready':False,'paused':False,'screen':'loading'}
    session=store.get('session',psid)|{'detail':{'warm':loading}}
    store.put('session',psid,session)
    tick(1)
    assert nxt in M.warm_pool(store,w['name']) and not ops(calls,psid,'stop_game')
    assert store.get('slabel',psid)['warm_state']=='loading'
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False
    assert not ops(calls,psid,'resume') and not ops(calls,run['session_id'],'pause')
    store.put('session',psid,session|{'detail':{'warm':{'state':'ready','ready':True,'paused':True,'screen':'title',
                                                      'source':'native_menu','title':M.TITLES[nxt]['map_id']}}})
    tick(1)
    assert store.get('slabel',psid)['warm_state']=='ready'
    receipt=boundary(run,now[0])|{'round_id':'c'*32}
    assert saver.round_boundary(receipt,job,now[0])['rotate_requested'] is True
    tick(1);tick(1)
    assert ops(calls,psid,'resume')


def test_switch_taken_over_while_preparing_never_resumes_early():
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    psid=up(store,pre,w,paused=False)
    session=store.get('session',psid)|{'detail':{'warm':{'state':'loading','ready':False,'paused':False}}}
    store.put('session',psid,session)
    pick={'title':nxt,'name':M.TITLES[nxt]['name'],'game_id':session['game_id'],'map_id':M.TITLES[nxt]['map_id']}
    assert 'background load' in saver._resume_warm(w,pick,M.settings(store,w['name']),now[0])
    waiting=store.get(S.STATE,w['name'])
    assert waiting['prelaunched'] and waiting['phase']=='launching'
    saver._advance(w,waiting,S.settings(store),store.running_sessions(),now[0]+1)
    assert not ops(calls,psid,'resume')
    store.put('session',psid,session|{'detail':{'warm':{'state':'ready','ready':True,'paused':True,
                                                      'source':'native_menu','title':M.TITLES[nxt]['map_id']}}})
    saver._advance(w,waiting,S.settings(store),store.running_sessions(),now[0]+2)
    assert len(ops(calls,psid,'resume'))==1


def test_cancelled_preparation_leaves_controlled_session_untouched():
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    psid=up(store,pre,w,paused=False)
    session=store.get('session',psid)|{'detail':{'warm':{'state':'cancelled','ready':False,'paused':False}}}
    store.put('session',psid,session)
    saver._warm(w,store.running_sessions(),now[0])
    assert nxt not in M.warm_pool(store,w['name']) and not ops(calls,psid)
    assert not store.get('slabel',psid)['warm']


@pytest.mark.parametrize('late_session', [False, True])
def test_failed_claimed_preparation_closes_exact_launch_and_allows_cold_fallback(late_session):
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    psid=up(store,pre,w,paused=False)
    session=store.get('session',psid)|{'detail':{'warm':{'state':'loading','ready':False,'paused':False}}}
    if late_session:
        store.delete('session',psid)
        store.put('job',pre['id'],pre|{'state':'running'})
    else:
        store.put('session',psid,session)
    pick={'title':nxt,'name':M.TITLES[nxt]['name'],'game_id':session['game_id'],'map_id':M.TITLES[nxt]['map_id']}
    saver._resume_warm(w,pick,M.settings(store,w['name']),now[0])
    waiting=store.get(S.STATE,w['name'])
    assert waiting.get('session_id') == (None if late_session else psid)
    assert nxt not in M.warm_pool(store,w['name'])
    if late_session: up(store,pre,w,paused=False)
    store.put('session',psid,session|{'detail':{'warm':{'state':'failed','reason':'native timeout'}}})
    saver._advance(w,waiting,S.settings(store),store.running_sessions(),now[0]+1)
    stops=ops(calls,psid,'stop_game')
    assert len(stops)==1 and stops[0]['require_worker']==w['id']
    assert not ops(calls,run['session_id'],'stop_game')
    assert not store.get(S.STATE,w['name']) and store.get(M.NEXT,w['name'])['cold']
    # The stop completes; the old title is a parked game from the prior turn.
    store.put('session',psid,session|{'state':'ended'})
    store.put('session',run['session_id'],store.get('session',run['session_id'])|{'state':'ended'})
    tick(2)
    cold=calls[-1]
    assert cold['tool']=='launch_game' and cold['input']['game']['game_id']==session['game_id']
    assert 'warm' not in cold['input']


@pytest.mark.parametrize('change', ['cancelled', 'human_owner', 'wrong_game', 'wrong_worker'])
def test_claimed_preparation_fallback_never_stops_revoked_or_unrelated_session(change):
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    psid=up(store,pre,w,paused=False)
    session=store.get('session',psid)|{'detail':{'warm':{'state':'loading','ready':False,'paused':False}}}
    store.put('session',psid,session)
    pick={'title':nxt,'name':M.TITLES[nxt]['name'],'game_id':session['game_id'],'map_id':M.TITLES[nxt]['map_id']}
    saver._resume_warm(w,pick,M.settings(store,w['name']),now[0])
    waiting=store.get(S.STATE,w['name'])
    if change=='cancelled': session['detail']['warm']['state']='cancelled'
    elif change=='human_owner': store.put('slabel',psid,{'owner':'you'})
    elif change=='wrong_game': session['game_id']='another-game'
    else: store.put('job',pre['id'],store.get('job',pre['id'])|{'worker_id':'other-worker'})
    store.put('session',psid,session)
    saver._warm_fallback(w,waiting,now[0]+1,'native timeout')
    assert not ops(calls,psid) and not ops(calls,run['session_id'],'stop_game')


def test_legacy_worker_paused_launch_is_not_native_prepared():
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    psid=up(store,pre,w)
    legacy=store.get('job',pre['id'])
    legacy['output']['detail']['warm']={'paused':True}  # actual pre-readiness worker schema
    store.put('job',pre['id'],legacy)
    saver._warm(w,store.running_sessions(),now[0])
    assert nxt not in M.warm_pool(store,w['name']) and ops(calls,psid,'stop_game')
    assert not ops(calls,psid,'resume')


def second_turn():
    """The preloaded title took over at the first boundary and plays its own round; the first title waits parked."""
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    psid=up(store,pre,w);tick(1)
    saver.round_boundary(boundary(run,now[0]),job,now[0]);tick(1);tick(1)
    resume=ops(calls,psid,'resume')[-1];store.put('job',resume['id'],resume|{'state':'succeeded'});tick(1)
    second=store.get(S.STATE,w['name'])
    job2=store.get('job',second['autoplay_job'])|{'state':'succeeded'};store.put('job',job2['id'],job2)
    return store,w,saver,calls,now,tick,run,job,second,job2


def test_a_parked_game_whose_pause_failed_is_closed():
    store,w,saver,calls,now,tick,run,job,second,job2=second_turn()
    pause=ops(calls,run['session_id'],'pause')[-1];store.put('job',pause['id'],pause|{'state':'failed','error':'no debugger'})
    tick(1)
    assert ops(calls,run['session_id'],'stop_game') and run['mercmode']['title'] not in M.warm_pool(store,w['name'])


def test_parked_title_is_resumed_on_its_next_turn_without_any_launch():
    store,w,saver,calls,now,tick,run,job,second,job2=second_turn()
    launches=len([c for c in calls if c['tool']=='launch_game'])
    clock(second,now,25);tick(1)                                             # the next title (the first one) is warm
    assert len([c for c in calls if c['tool']=='launch_game'])==launches
    assert store.get(M.NEXT,w['name'])['title']==run['mercmode']['title']
    body=boundary(second,now[0])|{'round_id':'b'*32}
    assert saver.round_boundary(body,job2,now[0])['rotate_requested'] is True
    psid=second['session_id']
    assert 'finish pausing' in tick(1)[w['name']]                            # parked; the first waits for its pause to land
    assert 'finish pausing' in tick(1)[w['name']]
    pause=ops(calls,run['session_id'],'pause')[-1];store.put('job',pause['id'],pause|{'state':'succeeded'})
    tick(1)
    assert ops(calls,psid,'pause') and ops(calls,run['session_id'],'resume')
    assert store.get(S.STATE,w['name'])['session_id']==run['session_id']
    assert len([c for c in calls if c['tool']=='launch_game'])==launches
    assert not [c for c in calls if c['tool']=='session_op' and c['input']['op']=='stop_game']


def test_a_failed_preload_is_tried_again_next_round_and_never_a_cold_switch_while_this_title_plays():
    # operator 2026-10-26: "the transitions between loads is just too long and I need it to be a seamless swap"
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    store.put('job',pre['id'],pre|{'state':'failed','error':'boot failed'})
    for attempt in range(1,M.EXTRA_ROUNDS_MAX+1):
        body=boundary(run,now[0])|{'round_id':chr(ord('a')+attempt)*32}
        assert saver.round_boundary(body,job,now[0])['rotate_requested'] is False   # this title plays another round
        cur=store.get(S.STATE,w['name'])
        assert cur['mercmode_warm_attempts']==attempt and cur['mercmode_extra_rounds']==attempt
        assert not ops(calls,run['session_id'],'stop_game') and not ops(calls,run['session_id'],'pause')
        tick(1)
        if attempt<M.EXTRA_ROUNDS_MAX:
            again=preloads(calls)[-1]                                            # the same promised title, preloaded again
            assert again is not pre and again['input']['game']['game_id'] in M.TITLES[nxt]['game_ids']
            assert store.get(M.NEXT,w['name'])['title']==nxt
            store.put('job',again['id'],again|{'state':'failed','error':'boot failed'})
    cur=store.get(S.STATE,w['name'])
    assert 'staying in this title' in cur['mercmode_stay'] and M.TITLES[nxt]['name'] in cur['mercmode_stay']
    assert len(preloads(calls))==M.EXTRA_ROUNDS_MAX                           # no further attempts
    assert cur['session_id']==run['session_id'] and cur['phase']=='playing'    # never a cold switch: it keeps playing
    assert not [c for c in calls if c['tool']=='launch_game' and not c['input'].get('warm')][1:]


def test_failed_resume_closes_that_game_and_cold_launches_the_same_title():
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    psid=up(store,pre,w);tick(1)
    saver.round_boundary(boundary(run,now[0]),job,now[0]);tick(1);tick(1)
    resume=ops(calls,psid,'resume')[-1];store.put('job',resume['id'],resume|{'state':'failed','error':'no resume'})
    tick(1)
    assert ops(calls,psid,'stop_game')                                       # our own preload, closed
    assert store.get(M.NEXT,w['name'])['title']==nxt and not store.get(S.STATE,w['name'])
    store.put('session',psid,store.get('session',psid)|{'state':'ended'})
    tick(1)
    cold=calls[-1]
    assert cold['tool']=='launch_game' and cold['input']['game']['game_id'] in M.TITLES[nxt]['game_ids']
    assert 'warm' not in cold['input']


def test_a_preload_that_could_not_pause_is_closed_and_preloaded_again_at_the_next_round():
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    psid=up(store,pre,w,paused=False);tick(1)
    assert ops(calls,psid,'stop_game') and nxt not in M.warm_pool(store,w['name'])
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False   # nothing ready: play on
    store.put('session',psid,store.get('session',psid)|{'state':'ended'})
    tick(1)
    again=preloads(calls)[-1]
    assert again is not pre and again['input']['game']['game_id'] in M.TITLES[nxt]['game_ids']
    assert not ops(calls,run['session_id'],'stop_game') and not ops(calls,run['session_id'],'pause')


def test_low_memory_skips_the_preload_and_this_title_plays_on_instead_of_a_cold_switch():
    store,w,saver,calls,now,tick,run,job=warm_playing(memory=4*GIB)
    assert not preloads(calls)
    assert 'GiB' in store.get(S.STATE,w['name'])['mercmode_prelaunch']['skipped']
    nxt=store.get(M.NEXT,w['name'])['title']                                 # the pick holds for the next attempt
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False
    tick(1)
    assert not ops(calls,run['session_id'],'stop_game') and not ops(calls,run['session_id'],'pause')
    cur=store.get(S.STATE,w['name'])
    assert cur['mercmode_warm_attempts']==1 and store.get(M.NEXT,w['name'])['title']==nxt
    assert 'GiB' in cur['mercmode_prelaunch']['skipped'] and not preloads(calls)   # tried again this round: still no room
    assert saver.round_boundary(boundary(run,now[0])|{'round_id':'b'*32},job,now[0])['rotate_requested'] is False
    w['resources']['memory_available_bytes']=32*GIB                         # memory came back: the next attempt preloads
    tick(1)
    assert preloads(calls)[-1]['input']['game']['game_id'] in M.TITLES[nxt]['game_ids']
    assert store.get(S.STATE,w['name'])['mercmode_warm_attempts']==2


@pytest.mark.parametrize('cfg,features',[({'keep_warm':0},[M.WARM_FEATURE]),({},[])])
def test_keep_warm_zero_or_an_older_worker_keeps_the_cold_switch(cfg,features):
    store,w,saver,calls,now,tick,run,job=warm_playing(features=features,**cfg)
    launches=len([c for c in calls if c['tool']=='launch_game'])
    clock(run,now,25);tick(1)
    assert len([c for c in calls if c['tool']=='launch_game'])==launches and not M.warm_pool(store,w['name'])
    saver.round_boundary(boundary(run,now[0]),job,now[0]);tick(1)
    assert ops(calls,run['session_id'],'stop_game') and not ops(calls,run['session_id'],'pause')


@pytest.mark.parametrize('foreign',['operator_took_it','operator_launch','other_worker'])
def test_pool_never_touches_a_session_that_is_not_exactly_ours(foreign):
    store,w,saver,calls,now,tick,run,job=warm_playing()
    title=run['mercmode']['title'];other='re5' if title=='re4' else 're4'
    osid=owned(store,w,other,'warm-x',now[0])
    if foreign=='operator_took_it':
        store.put('slabel',osid,{'session_id':osid,'owner':'you'})
    elif foreign=='operator_launch':
        store.put('job','warm-x',store.get('job','warm-x')|{'actor':'operator','agent_use':False})
    else:
        store.put('job','warm-x',store.get('job','warm-x')|{'require_worker':'w9'})
    store.put(M.NEXT,w['name'],{'title':other,'selection':None,'at':now[0]})
    saver.round_boundary(boundary(run,now[0]),job,now[0]);tick(1);tick(1)
    assert not ops(calls,osid)                                               # never paused, resumed or stopped
    assert all(r.get('session_id')!=osid for r in M.warm_pool(store,w['name']).values())   # dropped, not adopted
    assert store.get(S.STATE,w['name']) is None or store.get(S.STATE,w['name']).get('session_id')!=osid


def test_pool_stays_at_keep_warm_titles_besides_the_next_one():
    store,w,saver,calls,now,tick,run,job=warm_playing()
    title=run['mercmode']['title'];other='re5' if title=='re4' else 're4'
    old=owned(store,w,'re6','warm-old',now[0]-100)                           # an older waiting game over the bound
    nxt=owned(store,w,other,'warm-next',now[0])
    store.put(M.NEXT,w['name'],{'title':other,'selection':None,'at':now[0]})
    saver.round_boundary(boundary(run,now[0]),job,now[0]);tick(1)
    assert ops(calls,old,'stop_game')                                        # oldest out
    assert set(M.warm_pool(store,w['name']))=={title,other}
    store.put('session',old,store.get('session',old)|{'state':'ended'})      # the worker closed it
    tick(1)
    assert store.get(S.STATE,w['name'])['session_id']==nxt
    assert set(M.warm_pool(store,w['name']))=={title}                        # keep_warm 1: one waits, one plays


def test_turning_mercmode_off_releases_the_warm_games():
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    psid=up(store,pre,w);tick(1)
    M.configure(store,w['name'],{'enabled':False})
    tick(1)
    assert ops(calls,psid,'stop_game') and not M.warm_pool(store,w['name']) and store.get(M.NEXT,w['name']) is None
    assert store.get(S.STATE,w['name'])['session_id']==run['session_id']     # the playing game stays (pinned)


def test_preload_gets_presentation_priority_like_the_launch_it_replaces():
    store,w,saver,calls,now,tick,run,job,pre=preloaded(presentation_priority=True)
    stored=store.get('job',pre['id'])
    assert M.presentation_launch(store,w,stored)
    assert not M.presentation_launch(store,w,stored|{'id':'other'})
    assert not M.presentation_launch(store,w,stored|{'actor':'operator'})


def test_the_preferred_edition_gets_presentation_priority_for_its_preload_and_launch():
    # 2026-10-26 21:55: RE5 Switch No Mercy selected, its preload sat queued behind the 70% background budget (CPU 77-92%)
    # because only the PS3 game ids counted as MercMode foreground work; the cold launch would have waited the same way
    from gbox import re_switch
    store,w,saver,calls,now,tick=rig()
    switch_pref={'re5':{'platform':'switch','mode':'no_mercy','title_id':re_switch.RE5_TITLE_ID}}
    M.configure(store,w['name'],{'enabled':True,'presentation_priority':True,'preferred_editions':switch_pref})
    def preload(gid):
        return {'id':'pj','tool':'launch_game','actor':S.ACTOR,'require_worker':w['id'],
                'input':{'warm':True,'game':{'game_id':gid}}}
    store.put(S.STATE,w['name'],{'worker_id':w['id'],'phase':'playing','mercmode':{'title':'re4'},
                                 'mercmode_prelaunch':{'title':'re5','job':'pj'}})
    assert M.presentation_launch(store,w,preload(re_switch.RE5_GAME_ID))
    assert not M.presentation_launch(store,w,preload(RE5))                       # the PS3 copy is not this host's RE5
    cfg=M.settings(store,w['name'])
    launch={'id':'lj','tool':'launch_game','actor':S.ACTOR,'require_worker':w['id'],
            'input':{'game':{'game_id':re_switch.RE5_GAME_ID,'launch':{'mercmode':M.launch_block(cfg)}}}}
    store.put(S.STATE,w['name'],{'worker_id':w['id'],'phase':'launching','job':'lj','game_id':re_switch.RE5_GAME_ID,
                                 'mercmode':{'title':'re5'}})
    assert M.presentation_launch(store,w,launch)                                 # the cold launch at its turn too
    M.configure(store,w['name'],{'preferred_editions':{}})                       # back to the native edition
    assert not M.presentation_launch(store,w,launch)
    store.put(S.STATE,w['name'],{'worker_id':w['id'],'phase':'playing','mercmode':{'title':'re4'},
                                 'mercmode_prelaunch':{'title':'re5','job':'pj'}})
    assert M.presentation_launch(store,w,preload(RE5)) and not M.presentation_launch(store,w,preload(re_switch.RE5_GAME_ID))


def test_keep_warm_setting_accepts_counts_and_legacy_booleans():
    assert M.normalize({'keep_warm':True})['keep_warm']==1 and M.normalize({'keep_warm':False})['keep_warm']==0
    assert M.normalize({'keep_warm':2})['keep_warm']==2
    for bad in (3,-1,'1',1.0):
        with pytest.raises(ValueError):M.normalize({'keep_warm':bad})


def test_ended_warm_sessions_leave_the_pool():
    store=Store()
    M.keep_warm(store,'pc','re4',{'session_id':'w1-a','state':'parked'})
    M.keep_warm(store,'pc','re5',{'session_id':None,'job':'j','state':'prelaunch'})
    assert set(M.warm_pool(store,'pc',running=[])) == {'re5'}


def test_configure_relay_carries_keep_warm_only_to_a_warm_capable_worker(cfg):
    import time
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app=create_app(cfg);store=app.state.store
    w=worker(time.time(),name='WarmOwner',os='linux')
    store.put('worker',w['id'],w|{'last_seen':time.time(),'tools':['mercmode','launch_game','autoplay'],
        'features':[M.WARM_FEATURE],'federation':{'authority':'authority','scheduler_owner':'local'}})
    client=TestClient(app,headers={'Authorization':'Bearer '+cfg.token()})
    assert client.post('/api/mercmode',json={'host':w['name'],'enabled':True,'keep_warm':2}).status_code==200
    job=next(job for job in store.all('job') if job['tool']=='mercmode')
    assert job['input']['keep_warm']==2


def test_a_title_still_loading_in_the_background_means_another_round_of_this_one():
    # "they could play a 2nd round of mercenaries and continue gaming while the game loads"
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    run=store.get(S.STATE,w['name'])
    body=boundary(run,now[0])
    assert saver.round_boundary(body,job,now[0])['rotate_requested'] is False      # its preload has not finished
    assert store.get(S.STATE,w['name'])['mercmode_extra_rounds']==1


def test_parking_a_title_stops_its_bot_before_pausing_the_game():
    # 2026-10-24: a bot left on a parked (paused) game reported a freeze and the parked game was relaunched cold
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    up(store,pre,w);tick(1)
    saver.round_boundary(boundary(run,now[0]),job,now[0]);tick(1)
    sid=run['session_id']
    stop=[i for i,c in enumerate(calls) if c['tool']=='autoplay' and c['input']=={'session_id':sid,'op':'stop'}]
    pause=[i for i,c in enumerate(calls) if c['tool']=='session_op' and c['input'].get('session_id')==sid and c['input']['op']=='pause']
    assert stop and pause and stop[0] < pause[0]


# --- round preparation (operator 2026-10-26: "continue playing a round of mercenaries while the next session is loading and
# preparing in the background so the swap is seamless"): a warm title's own menus are driven to the first frame of a round
# in the background (autoplay op=prepare), it is paused there ("ready"), and the swap resumes it straight into gameplay ---

PREPARED=(M.WARM_FEATURE,M.PREPARE_FEATURE)


def prepare_done(store,w,prep,result=None):
    """The worker took the prepare job (its tool call answered at once; the walk reports through the session detail)."""
    store.put('job',prep['id'],prep|{'state':'succeeded','worker_id':w['id'],
        'output':{'result':result or {'started':'prepare: re4_merc_bot','mode':'prepare','state':'preparing','prepared':False}}})


def prepared_flow():
    """A title plays; its successor was preloaded, paused at its boot menu, then prepared: the pool entry is 'ready'."""
    store,w,saver,calls,now,tick,run,job,pre=preloaded(features=PREPARED)
    nxt=store.get(M.NEXT,w['name'])['title']
    psid=up(store,pre,w);tick(1)
    prep=prepares(calls,psid)[-1];prepare_done(store,w,prep)
    round_ready(store,psid,nxt,prep);tick(1)
    return store,w,saver,calls,now,tick,run,job,pre,psid,nxt


def test_a_preload_paused_at_its_menu_is_prepared_to_its_round_start_and_swapped_in_playing():
    store,w,saver,calls,now,tick,run,job,pre=preloaded(features=PREPARED)
    nxt=store.get(M.NEXT,w['name'])['title']
    assert not prepares(calls)                                               # not before the boot has paused at its menu
    psid=up(store,pre,w);tick(1)
    prep=prepares(calls,psid)[-1]
    assert prep['actor']==S.ACTOR and prep['agent_use'] and prep['require_worker']==w['id']
    assert prep['input']=={'session_id':psid,'op':'prepare'}                 # the title's own menus, no selection queued
    row=M.warm_pool(store,w['name'])[nxt]
    assert row['state']=='prelaunch' and row['prepare_job']==prep['id']
    assert store.get('slabel',psid)['warm_state']=='preparing'
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False   # not ready: another round
    cur=store.get(S.STATE,w['name'])
    assert cur['mercmode_waiting_for']=='preparing' and cur['mercmode_extra_rounds']==1
    assert not ops(calls,run['session_id'],'pause') and not ops(calls,run['session_id'],'stop_game')
    prepare_done(store,w,prep)
    round_ready(store,psid,nxt,{'id':'an-earlier-prepare'});tick(1)
    assert M.warm_pool(store,w['name'])[nxt]['state']=='prelaunch'          # another preparation's receipt: not this one's
    round_ready(store,psid,nxt,prep);tick(1)
    row=M.warm_pool(store,w['name'])[nxt]
    assert row['state']=='ready' and row['prepared']['character']=='Ada' and row['prepared']['stage']=='Castle'
    assert store.get('slabel',psid)['warm_state']=='round_ready'
    assert len(prepares(calls))==1                                           # prepared once
    assert saver.round_boundary(boundary(run,now[0])|{'round_id':'b'*32},job,now[0])['rotate_requested'] is True
    launches=len([c for c in calls if c['tool']=='launch_game'])
    tick(1)                                                                  # the park and the resume in one tick
    cur=store.get(S.STATE,w['name'])
    assert cur['session_id']==psid and cur['phase']=='starting' and cur['warm_from']=='ready'
    assert cur['mercmode']['prepared']['character']=='Ada'
    assert ops(calls,psid,'resume') and ops(calls,run['session_id'],'pause')
    assert not any(c['tool'] in ('re_mods','re5_mods') for c in calls)      # the prepared round plays as prepared
    resume=ops(calls,psid,'resume')[-1];store.put('job',resume['id'],resume|{'state':'succeeded'})
    tick(1)
    start=calls[-1]
    assert start['tool']=='autoplay' and start['input']['session_id']==psid and start['input']['op']=='start'
    assert store.get(S.STATE,w['name'])['phase']=='playing'
    assert len([c for c in calls if c['tool']=='launch_game'])==launches     # no boot, no menu walk: gameplay
    assert [r for r in store.all(S.LOG) if r.get('session_id')==run['session_id']][-1]['why']==S.ROTATION


def test_a_worker_without_prepare_swaps_at_the_boot_menu_as_before():
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    psid=up(store,pre,w);tick(1)
    assert not prepares(calls)
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is True


def test_a_parked_title_is_prepared_again_once_it_is_picked_to_play_next():
    # ... and only after its pause and its bot's stop have landed (the worker refuses a prepare on a stopping bot)
    store,w,saver,calls,now,tick,run,job,pre,psid,nxt=prepared_flow()
    saver.round_boundary(boundary(run,now[0])|{'round_id':'b'*32},job,now[0]);tick(1)
    resume=ops(calls,psid,'resume')[-1];store.put('job',resume['id'],resume|{'state':'succeeded'});tick(1)
    second=store.get(S.STATE,w['name']);assert second['phase']=='playing'
    first=run['mercmode']['title'];fsid=run['session_id']
    row=M.warm_pool(store,w['name'])[first]
    assert row['state']=='parked' and row['prepare_wanted'] and store.get(M.NEXT,w['name'])['title']==first
    assert not prepares(calls,fsid)
    pause=ops(calls,fsid,'pause')[-1];store.put('job',pause['id'],pause|{'state':'succeeded'})
    tick(1)
    assert not prepares(calls,fsid)                                          # its bot's stop has not landed yet
    stop=[c for c in calls if c['tool']=='autoplay' and c['input']=={'session_id':fsid,'op':'stop'}][-1]
    store.put('job',stop['id'],stop|{'state':'succeeded'})
    tick(1)
    prep2=prepares(calls,fsid)[-1]
    assert M.warm_pool(store,w['name'])[first]['prepare_job']==prep2['id']
    job2=store.get('job',second['autoplay_job'])|{'state':'succeeded'};store.put('job',job2['id'],job2)
    clock(second,now,100)
    assert saver.round_boundary(boundary(second,now[0])|{'round_id':'c'*32},job2,now[0])['rotate_requested'] is False
    prepare_done(store,w,prep2)
    round_ready(store,fsid,first,prep2,character='HUNK',stage='Base');tick(1)
    assert M.warm_pool(store,w['name'])[first]['state']=='ready'
    assert saver.round_boundary(boundary(second,now[0])|{'round_id':'d'*32},job2,now[0])['rotate_requested'] is True
    launches=len([c for c in calls if c['tool']=='launch_game'])
    tick(1)
    cur=store.get(S.STATE,w['name'])
    assert cur['session_id']==fsid and cur['warm_from']=='ready' and cur['mercmode']['prepared']['character']=='HUNK'
    assert ops(calls,fsid,'resume') and ops(calls,psid,'pause')
    assert len([c for c in calls if c['tool']=='launch_game'])==launches
    assert not [c for c in calls if c['tool']=='session_op' and c['input']['op']=='stop_game']


@pytest.mark.parametrize('how',['job_failed','walk_failed'])
def test_a_failed_prepare_falls_back_to_the_boot_paused_game(how):
    store,w,saver,calls,now,tick,run,job,pre=preloaded(features=PREPARED)
    nxt=store.get(M.NEXT,w['name'])['title'];psid=up(store,pre,w);tick(1)
    prep=prepares(calls,psid)[-1]
    if how=='job_failed':
        store.put('job',prep['id'],prep|{'state':'failed','error':'Autoplay is stopping; wait for it to stop'})
    else:
        prepare_done(store,w,prep)                                           # the walk ended paused at a menu, not in a round
        store.put('session',psid,store.get('session',psid)|{'detail':{'warm':{'state':'ready','ready':True,'paused':True,
            'prepared':False,'source':'native_menu','title':M.TITLES[nxt]['map_id'],'screen':'select_player',
            'prepare_failed':'the menus did not reach a round within 600 s'}}})
    tick(1)
    row=M.warm_pool(store,w['name'])[nxt]
    assert row['state']=='prelaunch' and row['prepare_failed'] and not ops(calls,psid,'stop_game')
    assert store.get('slabel',psid)['warm_state']=='ready'
    assert len(prepares(calls))==1                                           # no second try on a preload
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is True   # the earlier swap: at its menu
    tick(1)
    cur=store.get(S.STATE,w['name'])
    assert cur['session_id']==psid and cur['warm_from']=='prelaunch' and ops(calls,psid,'resume')


def test_a_prepare_whose_game_did_not_pause_closes_it_and_the_next_round_preloads_again():
    store,w,saver,calls,now,tick,run,job,pre=preloaded(features=PREPARED)
    nxt=store.get(M.NEXT,w['name'])['title'];psid=up(store,pre,w);tick(1)
    prep=prepares(calls,psid)[-1];prepare_done(store,w,prep)
    round_ready(store,psid,nxt,state='failed',ready=False,paused=False,reason='Emulator did not confirm it paused.')
    tick(1)
    assert ops(calls,psid,'stop_game') and nxt not in M.warm_pool(store,w['name'])
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False
    store.put('session',psid,store.get('session',psid)|{'state':'ended'});tick(1)
    assert preloads(calls)[-1] is not pre and not ops(calls,run['session_id'],'stop_game')


def test_a_prepare_cancelled_by_the_player_leaves_the_game_untouched():
    store,w,saver,calls,now,tick,run,job,pre=preloaded(features=PREPARED)
    nxt=store.get(M.NEXT,w['name'])['title'];psid=up(store,pre,w);tick(1)
    prep=prepares(calls,psid)[-1];prepare_done(store,w,prep);before=len(calls)
    round_ready(store,psid,nxt,state='cancelled',ready=False,paused=False,prepared=False,
                reason='The player took control during round preparation.')
    tick(1)
    assert nxt not in M.warm_pool(store,w['name']) and len(calls)==before and not store.get('slabel',psid)['warm']


def test_a_queued_dj_selection_reaches_the_prepared_round():
    store,w,saver,calls,now,tick=rig()
    w['features']=list(PREPARED)
    M.configure(store,w['name'],{'enabled':True,'titles':['re4','re5'],
        'queue':[{'title':'re4','character':'HUNK','stage':2},{'title':'re5','mode':'reunion','character':'Barry','stage':3}]})
    tick();sid='w1-'+calls[0]['id']
    assert calls[0]['input']['game']['launch']['mercmode']['selection']['character']=='HUNK'   # the DJ's first pick plays first
    store.put('session',sid,{'session_id':sid,'game_id':calls[0]['input']['game']['game_id'],'state':'running'})
    tick(1)
    pre=preloads(calls)[-1];sel=pre['input']['game']['launch']['mercmode']['selection']
    assert (sel['mode'],sel['character'],sel['stage'],sel['stage_name'])==('reunion','Barry',3,'Ancient Ruins')
    assert M.settings(store,w['name'])['queue']==[] and store.get(M.NEXT,w['name'])['queued'] is True
    tick(S.START_GRACE);run=store.get(S.STATE,w['name']);clock(run,now,200)
    psid=up(store,pre,w);tick(1)
    prep=prepares(calls,psid)[-1]
    assert prep['input']['selection']==sel                                   # the worker's menus select the DJ's round
    prepare_done(store,w,prep);round_ready(store,psid,'re5',prep,character='Barry',stage='Ancient Ruins',stage_index=3);tick(1)
    job=store.get('job',run['autoplay_job'])|{'state':'succeeded'};store.put('job',job['id'],job)
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is True
    tick(1)
    cur=store.get(S.STATE,w['name'])
    assert cur['session_id']==psid and cur['mercmode']['selection']==sel and cur['mercmode']['prepared']['character']=='Barry'
    assert not any(c['tool']=='re5_mods' for c in calls)                     # nothing to queue: the round is the DJ's already


def test_a_dj_pick_queued_after_the_preparation_is_taken_at_the_next_menu_visit():
    # the prepared round is past its menus: it plays as prepared, and the DJ's pick for that title is taken by its bot
    # at the next native menu visit (the round after), never lost
    store,w,saver,calls,now,tick,run,job,pre,psid,nxt=prepared_flow()
    pick={'title':nxt,'character':'Ada','stage':1} if nxt=='re4' else {'title':nxt,'mode':'reunion','character':'Josh','stage':3}
    M.configure(store,w['name'],{'queue':[pick]})
    assert saver.round_boundary(boundary(run,now[0])|{'round_id':'b'*32},job,now[0])['rotate_requested'] is True
    tick(1)
    assert store.get(S.STATE,w['name'])['warm_from']=='ready' and ops(calls,psid,'resume')
    assert [e['title'] for e in M.settings(store,w['name'])['queue']]==[nxt]   # still queued for that title
    resume=ops(calls,psid,'resume')[-1];store.put('job',resume['id'],resume|{'state':'succeeded'});tick(1)
    second=store.get(S.STATE,w['name']);job2=store.get('job',second['autoplay_job'])|{'state':'succeeded'}
    store.put('job',job2['id'],job2);clock(second,now,100)
    assert saver.round_boundary(boundary(second,now[0])|{'round_id':'c'*32},job2,now[0])['rotate_requested'] is False
    sent=[c for c in calls if c['tool'] in ('re_mods','re5_mods')][-1]
    assert sent['input']['session_id']==psid and sent['input']['op']=='mercs_select' and sent['input']['character']==pick['character']
    assert M.settings(store,w['name'])['queue']==[]


def test_a_switch_forced_while_the_preparation_still_walks_takes_the_game_over_from_it():
    # the playing title ended on its own (a crash) while the next one's menus were still being driven: no wait, no
    # loading screen - autoplay starts on it at once (the worker ends the walk and plays on from wherever the menus are)
    store,w,saver,calls,now,tick,run,job,pre=preloaded(features=PREPARED)
    nxt=store.get(M.NEXT,w['name'])['title'];psid=up(store,pre,w);tick(1)
    prep=prepares(calls,psid)[-1];store.put('job',prep['id'],prep|{'state':'running','worker_id':w['id']})
    store.put('session',psid,store.get('session',psid)|{'detail':{'warm':{'state':'preparing','ready':False,'paused':False,
        'prepared':False,'source':'native_round','title':M.TITLES[nxt]['map_id'],'screen':'select_stage'}}})
    store.put('session',run['session_id'],store.get('session',run['session_id'])|{'state':'ended'})
    tick(1)                                                                  # the run ends (not a rotation: no same-tick start)
    assert store.get(S.STATE,w['name']) is None
    tick(1)
    cur=store.get(S.STATE,w['name'])
    assert cur['session_id']==psid and cur['phase']=='starting' and cur['warm_from']=='preparing'
    assert not ops(calls,psid,'resume')                                      # unpaused already: nothing to resume
    tick(1)
    start=calls[-1]
    assert start['tool']=='autoplay' and start['input']['op']=='start' and start['input']['session_id']==psid


def test_a_switch_before_the_worker_took_the_prepare_cancels_it_and_resumes_the_menu_paused_game():
    store,w,saver,calls,now,tick,run,job,pre=preloaded(features=PREPARED)
    nxt=store.get(M.NEXT,w['name'])['title'];psid=up(store,pre,w);tick(1)
    prep=prepares(calls,psid)[-1]
    store.put('session',run['session_id'],store.get('session',run['session_id'])|{'state':'ended'})
    tick(1);tick(1)
    assert store.get('job',prep['id'])['state']=='cancelled'
    cur=store.get(S.STATE,w['name'])
    assert cur['session_id']==psid and ops(calls,psid,'resume') and cur['warm_from']=='prelaunch'


def test_the_dj_queueing_the_prepared_title_keeps_it_next_and_plays_it():
    store,w,saver,calls,now,tick,run,job,pre,psid,nxt=prepared_flow()
    M.configure(store,w['name'],{'queue':[{'title':nxt}]})
    assert saver.round_boundary(boundary(run,now[0])|{'round_id':'b'*32},job,now[0])['rotate_requested'] is True
    assert store.get(M.NEXT,w['name'])['title']==nxt


def test_a_title_mercmode_stayed_in_tries_the_next_one_again_after_a_few_more_rounds():
    # 2026-10-27 on lilspark: RE6's warm boot failed three times on a bug a hot reload fixed minutes later, and RE5 stayed
    # for good ("could not be made ready 3 times: staying in this title") - 15 rounds and counting
    store,w,saver,calls,now,tick,run,job,pre=preloaded()
    nxt=store.get(M.NEXT,w['name'])['title']
    store.put('job',pre['id'],pre|{'state':'failed','error':'boot failed'})
    for attempt in range(1,M.EXTRA_ROUNDS_MAX+1):
        saver.round_boundary(boundary(run,now[0])|{'round_id':f'{attempt:032x}'},job,now[0])
        tick(1)
        again=preloads(calls)[-1]
        store.put('job',again['id'],again|{'state':'failed','error':'boot failed'})
    cur=store.get(S.STATE,w['name'])
    assert 'staying in this title' in cur['mercmode_stay'] and cur['mercmode_stay_round']==cur['mercmode_rounds_played']
    tries=len(preloads(calls))
    for k in range(1,M.STAY_RETRY_ROUNDS+1):
        saver.round_boundary(boundary(run,now[0])|{'round_id':f'{100+k:032x}'},job,now[0])
        cur=store.get(S.STATE,w['name'])
        if k<M.STAY_RETRY_ROUNDS:
            assert cur.get('mercmode_stay') and len(preloads(calls))==tries          # still staying, no new attempt
            tick(1)
    assert 'mercmode_stay' not in cur and cur['mercmode_warm_attempts']==1 and 'mercmode_prelaunch' not in cur
    tick(1)
    retry=preloads(calls)[-1]
    assert len(preloads(calls))==tries+1 and retry['input']['game']['game_id'] in M.TITLES[nxt]['game_ids']
    old=store.get(S.STATE,w['name'])|{'mercmode_stay':'gave up','mercmode_warm_attempts':3}
    old.pop('mercmode_stay_round',None)
    store.put(S.STATE,w['name'],old)                             # a stay set before this rule: tried again at once
    saver.round_boundary(boundary(run,now[0])|{'round_id':'f'*32},job,now[0])
    assert 'mercmode_stay' not in store.get(S.STATE,w['name'])


def test_the_dj_asking_for_a_title_mercmode_gave_up_on_tries_it_again():
    store,w,saver,calls,now,tick,run,job,pre=preloaded(features=PREPARED)
    nxt=store.get(M.NEXT,w['name'])['title']
    store.put(S.STATE,w['name'],store.get(S.STATE,w['name'])|{'mercmode_stay':'gave up','mercmode_warm_attempts':3})
    store.put('job',pre['id'],pre|{'state':'failed','error':'boot failed'})
    M.configure(store,w['name'],{'queue':[{'title':nxt}]})
    assert saver.round_boundary(boundary(run,now[0]),job,now[0])['rotate_requested'] is False   # not ready yet: play on
    cur=store.get(S.STATE,w['name'])
    assert 'mercmode_stay' not in cur and cur['mercmode_warm_attempts']==1 and 'mercmode_prelaunch' not in cur
    tick(1)
    assert preloads(calls)[-1] is not pre                                    # preloaded again for the DJ


def test_nudge_wakes_the_installed_schedule_loop_only():
    import threading
    store,w,saver,calls,now,tick=rig()
    saver.nudge('a job landed')                                              # without the installed loop (tests): nothing
    saver.wake=threading.Event();saver.nudge('a job landed')
    assert saver.wake.is_set() and saver.nudged=='a job landed'


def test_a_quick_death_is_a_retry_not_a_round_and_three_of_them_count_as_one():
    # operator 2026-10-26: "are sure it is playing 5 rounds of mercenaries in each game before moving onto the next one?"
    # - RE4 left after one stage per turn: each death + retry was a boundary, five quick deaths were five "rounds"
    store,w,saver,calls,now,tick,run,job=playing()
    t0=run.get('playing_since') or run['started']
    def death(n,at):
        now[0]=at
        S.telemetry_put(run['session_id'],{'running':True,'stats':{}},now=now[0])
        body=boundary(run,at,screen='dead',hp=0,tally_ready=False,timer=60)|{'round_id':f'{n:x}'*32}
        return saver.round_boundary(body,job,now[0])
    assert death(1,t0+30)=={'saved':True,'rotate_requested':False}       # 30 s in: a retry
    cur=store.get(S.STATE,w['name'])
    assert cur['mercmode_rounds']==0 and cur['mercmode_quick_deaths']==1
    assert death(2,t0+50)['rotate_requested'] is False                    # 20 s into the second attempt
    assert death(3,t0+60)['rotate_requested'] is True                     # the third quick death counts one round
    assert store.get(S.STATE,w['name'])['mercmode_rounds_played']==1


def test_a_death_after_a_real_attempt_is_a_round_played():
    store,w,saver,calls,now,tick,run,job=playing()
    t0=run.get('playing_since') or run['started']
    now[0]=t0+M.ROUND_MIN_S+5
    S.telemetry_put(run['session_id'],{'running':True,'stats':{}},now=now[0])
    body=boundary(run,now[0],screen='dead',hp=0,tally_ready=False,timer=40)|{'round_id':'e'*32}
    assert saver.round_boundary(body,job,now[0])['rotate_requested'] is True
    assert store.get(S.STATE,w['name'])['mercmode_rounds']==1


def test_inventory_walks_each_worker_alias_chain_once_however_many_sessions():
    # 2026-10-26: /api/mercmode took 20-40 s on the loaded Spark - the alias chain was walked per session
    store,w,saver,calls,now,tick=rig()
    for k in range(300):
        store.put('session',f'old{k%3}-s{k}',{'session_id':f'old{k%3}-s{k}','game_id':RE5,'state':'ended'})
    reads=[]
    real_get=store.get
    def counting(kind,key):
        if kind=='worker_alias':
            reads.append(key)
        return real_get(kind,key)
    store.get=counting
    M.inventory(store,w)
    assert len(reads)<=3*8                              # three old worker ids, each walked at most once


def test_a_frozen_game_wakes_the_scheduler_at_once():
    # 2026-10-26: RE4 froze on its results at 16:54:33, the stop came 15 s later and the prepared RE5 only at 16:55:58
    store,w,saver,calls,now,tick,run,job=playing()
    woke=[]
    saver.nudge=lambda why='': woke.append(why)
    assert saver.report(run['session_id'],{'bad_end':'hung'}) is True
    assert woke and 'bad end (hung)' in woke[0]
    assert store.get(S.STATE,w['name'])['yield']==S.BAD_ENDS['hung']


def orphan_rig():
    store,w,saver,calls,now,tick=rig()
    M.configure(store,w['name'],{'enabled':True,'keep_warm':False})
    return store,w,saver,calls,now,tick


def running_copy(store,sid,gid,started,actor,**extra):
    store.put('session',sid,{'session_id':sid,'game_id':gid,'state':'running','title':'Resident Evil','started':started,**extra})
    store.put('job',sid.split('-',1)[1],{'id':sid.split('-',1)[1],'tool':'launch_game','state':'succeeded','actor':actor})


def test_a_copy_the_bot_relaunched_after_mercmode_closed_its_run_is_closed():
    # 2026-10-26 17:58: RE4 froze, MercMode ended the run, the bot's reset relaunched RE4 and nothing played it; the
    # scheduler then waited behind that copy ("a game is already running there") for 9 minutes
    store,w,saver,calls,now,tick=orphan_rig()
    store.put('session','w1-old',{'session_id':'w1-old','game_id':RE4,'state':'ended','replaced_by':'w1-reset'})
    store.put('job','old',{'id':'old','tool':'launch_game','state':'succeeded','actor':S.ACTOR})
    running_copy(store,'w1-reset',RE4,now[0]-120,S.DEMO_ACTOR)
    assert saver._reap_orphans(w,store.running_sessions(),now[0])==['w1-reset']
    stops=[c for c in calls if c['tool']=='session_op']
    assert stops[0]['input']=={'session_id':'w1-reset','op':'stop_game','args':{}} and stops[0]['actor']==S.ACTOR
    assert saver._reap_orphans(w,store.running_sessions(),now[0])==[]        # its stop is on the way: never sent twice
    running_copy(store,'w1-stray',RE5,now[0]-120,S.ACTOR)                     # a scheduler copy nothing owns any more
    assert saver._reap_orphans(w,store.running_sessions(),now[0])==['w1-stray']


def test_operator_agent_young_played_and_owned_copies_are_never_closed():
    store,w,saver,calls,now,tick=orphan_rig()
    running_copy(store,'w1-op',RE5,now[0]-600,'operator')                    # the operator's own game
    running_copy(store,'w1-agent',RE5,now[0]-600,'agent')                    # an agent's test session
    running_copy(store,'w1-young',RE4,now[0]-10,S.ACTOR)                     # may still be on its way into a run
    running_copy(store,'w1-played',RE4,now[0]-600,S.ACTOR)
    S.telemetry_put('w1-played',{'running':True,'stats':{}},now=now[0])    # a bot plays it
    running_copy(store,'w1-yours',RE4,now[0]-600,S.ACTOR)
    store.put('slabel','w1-yours',{'session_id':'w1-yours','owner':'you'}) # the operator picked up the pad
    running_copy(store,'w1-demo',RE4,now[0]-600,S.DEMO_ACTOR)                # a bot's relaunch of a game MercMode never had
    running_copy(store,'w1-runreset',RE4,now[0]-600,S.DEMO_ACTOR)            # the current run's own game, relaunched
    store.put('session','w1-run',{'session_id':'w1-run','game_id':RE4,'state':'ended','replaced_by':'w1-runreset'})
    store.put('job','run',{'id':'run','tool':'launch_game','state':'succeeded','actor':S.ACTOR})
    store.put(S.STATE,w['name'],{'session_id':'w1-run','job':'run','phase':'playing','mercmode':{'title':'re4'}})
    running_copy(store,'w1-warm',RE5,now[0]-600,S.ACTOR)                     # a parked title
    M.keep_warm(store,w['name'],'re5',{'session_id':'w1-warm','job':'warm'})
    assert saver._reap_orphans(w,store.running_sessions(),now[0])==[]
    assert not [c for c in calls if c['tool']=='session_op']
    M.configure(store,w['name'],{'enabled':False})                          # MercMode off: nothing is closed at all
    running_copy(store,'w1-stray',RE5,now[0]-600,S.ACTOR)
    assert saver._reap_orphans(w,store.running_sessions(),now[0])==[]


def test_mercmode_status_is_computed_once_for_concurrent_callers(monkeypatch):
    # 2026-10-26 19:25: ~54 concurrent GET /api/mercmode each read every session; they held the store's readers and the
    # scheduler's tick stalled behind a round boundary waiting for one
    import threading,time as clock
    store,w,saver,calls,now,tick=rig()
    real,runs=saver._mercmode_status,[0]
    def slow():
        runs[0]+=1;clock.sleep(0.2);return real()
    saver._mercmode_status=slow
    out=[]
    threads=[threading.Thread(target=lambda:out.append(saver.mercmode_status())) for _ in range(8)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert runs[0]==1 and len(out)==8 and all(o is out[0] for o in out)
    assert saver.mercmode_status() is out[0]                                # within the TTL: the shared copy
    saver.mercmode_status(fresh=True);assert runs[0]==2                     # after a settings change: recomputed
    monkeypatch.setattr(S,'STATUS_TTL_S',0.0);saver.mercmode_status();assert runs[0]==3


def test_a_bot_may_not_relaunch_a_copy_mercmode_already_closed():
    store,w,saver,calls,now,tick=orphan_rig()
    store.put('job','run',{'id':'run','tool':'launch_game','actor':S.ACTOR})
    store.put('job','mine',{'id':'mine','tool':'launch_game','actor':'operator'})
    assert S.mercmode_closed(store,'w1-run',w['name'])                       # MercMode's copy, no longer its run
    store.put(S.STATE,w['name'],{'session_id':'w1-run','job':'run'})
    assert not S.mercmode_closed(store,'w1-run',w['name'])                   # still the run: the bot may reset it
    assert not S.mercmode_closed(store,'w1-mine',w['name'])                  # the operator's game is never MercMode's
    assert not S.mercmode_closed(store,'w1-run','another-host')              # a host without MercMode
