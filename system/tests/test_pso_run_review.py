import copy
import json
from types import SimpleNamespace

import pytest

from gbox import pso_run_review as R
from gbox.pso_coop_nav import Maps


def state(room=16, floor=1):
    return {'verified':True,'phase':14,'episode':1,'floor':floor,'difficulty':0,
        'players':{1:{'ptr':'81230000','class':'TObjPlayer','x':550.,'y':0.,'z':560.,'room':room,'hp':33,'tp':0},
                   2:{'ptr':'81240000','class':'TObjPlayer','x':590.,'y':0.,'z':560.,'room':room,'hp':38,'tp':40}},
        'entities':[{'ptr':'81300000','entity_id':16507,'class':'TObjContainerItem','kind':'object',
                     'room':room,'x':583.74,'y':1.88,'z':570.776}]}


def fixture(tmp_path):
    now=[0.]
    sampler=R.Sampler('worker-session','436e0bb84d5337d1',clock=lambda:now[0],wall=lambda:100+now[0])
    controller=SimpleNamespace(goals={},maps=Maps(tmp_path/'maps'))
    stats={'action':'inspect_field','observed_enemy_damage':0,'observed_kills':0,'remembered_blocked_edges':0}
    return sampler,controller,stats,now


def test_native_container_remains_container_and_empty_room_is_not_complete(tmp_path):
    sampler,c,stats,now=fixture(tmp_path)
    assert sampler.offer(state(),c,stats)
    frame=stats['pso_review']
    assert frame['entities'][0]['class']=='TObjContainerItem'
    assert frame['room_clear_verified'] is False
    assert frame['door_requirements']['state']=='unverified'
    assert frame['maps'][0]['geometry_available'] is False
    assert len(json.dumps(frame).encode())<R.FRAME_BYTES
    assert not sampler.offer(state(),c,stats)


def test_native_gate_condition_is_bounded_and_does_not_claim_passability(tmp_path):
    sampler,c,stats,now=fixture(tmp_path);s=state()
    s['entities']=[dict(s['entities'][0],entity_id=n,class_='unused',x=550.+n,
        door_requirements={'source':'3OE2:8015DAE4','code_verified':True,
            'mode':1,'native_state':2,'enable_bit':True,'predicate':'unconditional_enable',
            'predicate_verified':True,'predicate_scope':'native mode branch; global overrides unknown',
            'passability_verified':True}) for n in range(12)]
    sampler.offer(s,c,stats)
    evidence=stats['pso_review']['door_requirements']
    assert evidence['state']=='partial' and evidence['entries_omitted']==4
    assert len(evidence['entries'])==8
    assert all(row['requirements']['passability_verified'] is False for row in evidence['entries'])
    assert evidence['entries'][0]['requirements']['predicate_scope'].startswith('native mode branch')
    now[0]=1;s['travelling']=True;sampler.offer(s,c,stats)
    assert stats['pso_review']['door_requirements']['entries']==[]
    now[0]=2;s['travelling']=False
    for row in s['entities']:row['door_requirements']['code_verified']=False
    sampler.offer(s,c,stats)
    assert stats['pso_review']['door_requirements']['state']=='unverified'


def test_navigation_objective_must_match_current_geometry_and_player_room(tmp_path):
    sampler,c,stats,now=fixture(tmp_path);s=state();s['geometry_identity']='forest-1-layout'
    c.field=SimpleNamespace(status={'state':'routing','geometry_identity':'forest-1-layout',
        'players':{'1':{'room':16,'dependency':'combat','outcome':'active','enemy_count':3,
                       'goal':{'x':20.,'z':30.},'predicate':'unknown'},
                   '2':{'room':15,'dependency':'explore','outcome':'active'}}})
    sampler.offer(s,c,stats);nav=stats['pso_review']['navigation']
    assert set(nav['players'])=={'1'} and nav['players']['1']['enemy_count']==3
    assert nav['room_clear_verified'] is False
    assert stats['pso_review']['goals']==[{'player':1,'x':20.,'z':30.,'room':16,
        'reason':'combat','source':'field_controller','route_verified':False}]
    now[0]=1;s['geometry_identity']='replacement-layout';sampler.offer(s,c,stats)
    assert stats['pso_review']['navigation']=={'state':'unavailable','players':{}}


def test_room_changes_and_damage_are_observed_without_completion_credit(tmp_path):
    sampler,c,stats,now=fixture(tmp_path)
    sampler.offer(state(),c,stats)
    now[0]=1;s=state();s['players'][1]['hp']=20
    sampler.offer(s,c,stats)
    now[0]=2;sampler.offer(state(room=17),c,stats)
    events=stats['pso_review']['events']
    assert any(e['kind']=='damage_taken' for e in events)
    assert len([e for e in events if e['kind']=='room_changed'])==2
    assert not stats['pso_review']['completion_verified']


def test_native_actor_replacement_or_floor_transition_does_not_invent_damage(tmp_path):
    sampler,c,stats,now=fixture(tmp_path);sampler.offer(state(),c,stats)
    now[0]=1;s=state();s['players'][1].update(ptr='81400000',hp=1);sampler.offer(s,c,stats)
    now[0]=2;s=state(floor=2);s['players'][2]['hp']=1;sampler.offer(s,c,stats)
    assert not any(e['kind']=='damage_taken' for e in stats['pso_review']['events'])


def test_stall_is_descriptive_not_a_wall_or_room_clear(tmp_path):
    sampler,c,stats,now=fixture(tmp_path)
    for n in range(20):
        now[0]=n;sampler.offer(state(),c,stats)
    frame=stats['pso_review']
    assert len([e for e in frame['events'] if e['kind']=='stationary'])==2
    assert not frame['maps'][0]['blocked']
    assert not frame['room_clear_verified']


def test_geometry_requires_native_identity_and_layer(tmp_path):
    sampler,c,stats,now=fixture(tmp_path);s=state()
    s.update(geometry_identity='collisionhash',collision_grid={'size':12.,'floor':[(45,46)],'walls':[(46,46)]})
    c.maps.get(s,s['players'][1]);sampler.offer(s,c,stats)
    assert not stats['pso_review']['maps'][0]['geometry_available']
    s['geometry_layer']='forest-ground';c.maps.get(s,s['players'][1]);now[0]=1;sampler.offer(s,c,stats)
    assert stats['pso_review']['maps'][0]['geometry_available']
    assert stats['pso_review']['maps'][0]['walls']==[[46,46]]


def test_events_retained_between_telemetry_posts_and_reset_on_recording_segment(tmp_path):
    sampler,c,stats,now=fixture(tmp_path);sampler.offer(state(),c,stats)
    now[0]=2;sampler.offer(state(room=17),c,stats);run=stats['pso_review']['run_id']
    now[0]=5;sampler.offer(state(room=17),c,stats)
    assert any(e['kind']=='room_changed' for e in stats['pso_review']['events'])
    now[0]=601;sampler.offer(state(room=17),c,stats)
    assert stats['pso_review']['run_id']!=run
    assert [e['kind'] for e in stats['pso_review']['events']]==['recording_started']


def test_per_player_collision_layers_are_not_borrowed_from_the_other_buddy(tmp_path,monkeypatch):
    from gbox import pso_coop_nav as navigation
    sampler,c,stats,now=fixture(tmp_path);s=state()
    s.update(geometry_identity='wrong-shared-layer',geometry_layer='wrong')
    views={'81230000':{'geometry_identity':'forest','geometry_layer':'bridge'},
           '81240000':{'geometry_identity':'forest','geometry_layer':'ground'}}
    monkeypatch.setattr(navigation,'geometry_view',lambda state,player:views[player['ptr']],raising=False)
    monkeypatch.setattr(navigation,'room_key',lambda state,player:(player['ptr'],True))
    c.maps.maps={ptr:navigation.RoomMap(floor=[(45+i,46)],walls=[])
                 for i,ptr in enumerate(views)}
    sampler.offer(s,c,stats)
    rows=stats['pso_review']['maps']
    assert [r['geometry_layer'] for r in rows]==['bridge','ground']
    assert [r['floor'] for r in rows]==[[[45,46]],[[46,46]]]
    assert all(r['geometry_identity']=='forest' for r in rows)


def test_walkable_outlines_keep_holes_and_never_draw_crop_edges(tmp_path):
    floor={(x,z) for x in range(30) for z in range(30)}-{(15,15)}
    outlines=R.walkable_boundaries(floor)
    assert len(outlines)==8  # Four outer boundaries plus the four edges of the hole.
    assert [[15,15],[16,15]] in outlines
    assert [[0,0],[30,0]] in outlines
    sampler,c,stats,now=fixture(tmp_path);s=state()
    s.update(geometry_identity='full-layer',geometry_layer='ground',
             collision_grid={'size':12.,'floor':sorted(floor),'walls':[]})
    c.maps.get(s,s['players'][1]);sampler.offer(s,c,stats)
    row=stats['pso_review']['maps'][0]
    assert len(row['floor'])==240 and row['geometry_truncated'] is True
    assert sorted(row['boundaries'])==outlines
    assert row['boundaries_truncated'] is False


def test_duplicate_bridge_delivery_does_not_refresh_stale_frame(tmp_path):
    sampler,c,stats,now=fixture(tmp_path);sampler.offer(state(),c,stats)
    store=R.ReviewStore(tmp_path,clock=lambda:now[0]);session={'session_id':sampler.sid,'game_id':sampler.gid}
    assert store.ingest(sampler.sid,stats['pso_review'],session,'job1')
    now[0]=20
    assert not store.ingest(sampler.sid,stats['pso_review'],session,'job1')
    assert store.live(sampler.sid)['live'] is False
    assert store.live(sampler.sid)['age_s']==20
    saved=store.run(sampler.run)
    assert saved['run']['frames']==1
    assert len(saved['events'])==1


def test_exact_session_binding_and_nonfinite_data_rejected(tmp_path):
    sampler,c,stats,now=fixture(tmp_path);sampler.offer(state(),c,stats)
    store=R.ReviewStore(tmp_path)
    with pytest.raises(ValueError):store.ingest(sampler.sid,stats['pso_review'],{'session_id':'other','game_id':sampler.gid})
    with pytest.raises(ValueError):store.ingest(sampler.sid,stats['pso_review'],{'session_id':sampler.sid,'game_id':'other'})
    frame=copy.deepcopy(stats['pso_review']);frame['players']['1']['x']=float('nan')
    with pytest.raises(ValueError):R.validate(frame,sampler.sid,sampler.gid)


def test_store_survives_restart_and_out_of_order_does_not_replace_current(tmp_path):
    sampler,c,stats,now=fixture(tmp_path);session={'session_id':sampler.sid,'game_id':sampler.gid}
    sampler.offer(state(),c,stats);old=copy.deepcopy(stats['pso_review'])
    now[0]=2;sampler.offer(state(room=17),c,stats)
    store=R.ReviewStore(tmp_path);store.ingest(sampler.sid,stats['pso_review'],session)
    assert not store.ingest(sampler.sid,old,session)
    recovered=R.ReviewStore(tmp_path)
    assert recovered.live(sampler.sid)['frame']['players']['1']['room']==17
    assert recovered.runs()['runs'][0]['frames']==1


@pytest.mark.parametrize('observed_at,session_state,active,expected',[
    (100.,'running',True,True),(50.,'running',True,False),
    (120.,'running',True,False),(100.,'ended',True,False),(100.,'running',False,False)])
def test_live_requires_fresh_source_and_running_exact_session(tmp_path,observed_at,session_state,active,expected):
    sampler,c,stats,now=fixture(tmp_path);sampler.offer(state(),c,stats)
    stats['pso_review']['observed_at']=observed_at
    store=R.ReviewStore(tmp_path,clock=lambda:100.)
    store.ingest(sampler.sid,stats['pso_review'],{'session_id':sampler.sid,'game_id':sampler.gid,'state':session_state})
    assert store.live(sampler.sid,active=active)['live'] is expected


def test_http_routes_auth_and_export_has_no_navigation_authority(tmp_path):
    from fastapi import FastAPI,HTTPException
    from fastapi.testclient import TestClient
    app=FastAPI();allow=[False]
    def auth():
        if not allow[0]:raise HTTPException(401)
        return 'test'
    R.install(app,SimpleNamespace(data_dir=tmp_path),auth,None)
    sampler,c,stats,now=fixture(tmp_path);sampler.offer(state(),c,stats)
    app.state.pso_review.ingest(sampler.sid,stats['pso_review'],{'session_id':sampler.sid,'game_id':sampler.gid})
    with TestClient(app) as client:
        assert client.get('/api/pso/reviewer/runs').status_code==401
        allow[0]=True
        assert client.get('/api/pso/reviewer/live/'+sampler.sid).json()['frame']['run_id']==sampler.run
        data=client.get('/api/pso/reviewer/crystal/'+sampler.run).json()
        assert data['navigation_authority'] is False
        assert data['room_clear_inference'] is False
        assert len(data['sha256'])==64
        assert client.get('/api/pso/reviewer/run/not-a-run').status_code==422


def test_existing_telemetry_ingests_review_without_requiring_game_inputs(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gbox import screensaver as S
    from gbox import tools
    sampler,c,stats,now=fixture(tmp_path);sampler.offer(state(),c,stats)
    session={'session_id':sampler.sid,'game_id':sampler.gid,'state':'running'}
    store=SimpleNamespace(get=lambda kind,key:session if kind=='session' and key==sampler.sid else None)
    app=FastAPI();R.install(app,SimpleNamespace(data_dir=tmp_path),lambda:'worker',store)
    S.install(app,store,None,lambda:'worker',lambda *a,**k:None,lambda:[],None)
    block=tools._telemetry_blocks(stats)
    assert block['pso_review']['run_id']==sampler.run
    with TestClient(app) as client:
        result=client.post('/api/autoplay/telemetry/'+sampler.sid,json={'running':True,'stats':block})
        assert result.status_code==200
        assert app.state.pso_review.runs()['runs'][0]['id']==sampler.run
        # Recorder failure leaves normal controller telemetry available.
        bad=copy.deepcopy(block);bad['pso_review']['game_id']='wrong-title'
        assert client.post('/api/autoplay/telemetry/'+sampler.sid,json={'running':True,'stats':bad}).status_code==200
        assert 'unavailable' in app.state.pso_review.error


def test_telemetry_combined_blocks_remain_bounded():
    from gbox import tools
    result=tools._telemetry_blocks({'pso_review':{'payload':'x'*30000},'look':{'payload':'y'*30000}})
    assert 'pso_review' in result
    assert len(json.dumps(result).encode())<=tools.TELEMETRY_BLOCK_MAX


def test_event_response_limit_is_explicit_without_discarding_recorded_events(tmp_path):
    sampler,c,stats,now=fixture(tmp_path);sampler.offer(state(),c,stats)
    store=R.ReviewStore(tmp_path)
    store.ingest(sampler.sid,stats['pso_review'],{'session_id':sampler.sid,'game_id':sampler.gid})
    with store._connect() as db:
        db.executemany('INSERT OR REPLACE INTO events VALUES(?,?,?)',
                       [(sampler.run,i,json.dumps({'id':i,'kind':'room_changed','at_s':i})) for i in range(2001)])
        db.commit()
    result=store.run(sampler.run)
    assert result['events_truncated'] is True
    assert len(result['events'])==2000
    with store._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM events WHERE run=?',(sampler.run,)).fetchone()[0]==2001


def test_current_unix_timestamp_is_valid_and_recent_cells_are_shown(tmp_path):
    import time
    sampler=R.Sampler('worker-session','436e0bb84d5337d1')
    c=SimpleNamespace(goals={},maps=Maps(tmp_path/'maps'))
    stats={};sampler.offer(state(),c,stats)
    assert stats['pso_review']['observed_at']>1e9
    store=R.ReviewStore(tmp_path)
    store.ingest(sampler.sid,stats['pso_review'],{'session_id':sampler.sid,'game_id':sampler.gid,'state':'running'})
    assert store.live(sampler.sid,active=True)['live'] is True
    assert R._cells({(i,i) for i in range(1000)},2,(500,500))==[[500,500],[499,499]]
