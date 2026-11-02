import copy
import json
import pytest
from gbox import pso_coop as C
from test_pso_margin_controller import margin_state, controller


def rig(tmp_path, monkeypatch):
    st = margin_state()
    c, commands = controller(st, tmp_path, monkeypatch)
    c.inputs.stats = {}
    return st, c, commands


def events(c):
    return json.loads(c.inputs.stats['steering_evidence_json'])['events']


def test_actual_margin_tick_records_exact_command_and_next_existing_observation(tmp_path, monkeypatch):
    st,c,commands = rig(tmp_path,monkeypatch)
    snapshots=[]
    def snapshot():
        snapshots.append(True)
        value=copy.deepcopy(st)
        if len(snapshots)==2:value['players'][2]['z']+=3
        return value
    c.reader.snapshot=snapshot
    assert c.tick(st)
    assert len(snapshots)==2  # Existing camera reobserve and ordinary after-move read only.
    row=events(c)[-1];p=row['players']['2']
    assert row['state']=='observed' and row['after_verified'] and row['same_area']
    assert p['source']=='margin_recovery' and p['waypoint']==[22.5,27.5]
    assert p['before']['z']==22.5 and p['after']['z']==25.5 and p['same_actor']
    move=next(x for x in commands if x[1]!=['l'])
    assert p['keys']==move[1] and p['requested_game_seconds']==move[2]==.04
    assert p['geometry_layer']=='floor' and p['requested_speed']==2
    assert row['hold_call_started_monotonic']<=row['hold_call_returned_monotonic']
    assert isinstance(row['hold_call_started_wall_time'],float) and row['hold_call_started_wall_time']>0
    assert row['post_observation_interval_started_monotonic']<=row['post_observation_returned_monotonic']
    assert row['pre_pose_exact_sample_time_known'] is False


def test_deferred_delivery_preserves_exception_and_never_claims_motion(tmp_path,monkeypatch):
    st,c,commands=rig(tmp_path,monkeypatch)
    def hold(rows):
        commands.extend(rows)
        if any(keys!=['l'] for _,keys,_ in rows):raise C.InputDeferred('held by operator')
    c.inputs.hold=hold
    with pytest.raises(C.InputDeferred,match='held by operator'):c.tick(st)
    row=events(c)[-1]
    assert row['state']=='delivery_interrupted'
    assert 'after' not in row['players']['2'] and 'post_observation_returned_monotonic' not in row
    assert c.margin_attempts[2]['attempts']==0


def test_after_read_failure_keeps_original_error_and_ack_only(tmp_path,monkeypatch):
    st,c,_=rig(tmp_path,monkeypatch);calls=[]
    def snapshot():
        calls.append(True)
        if len(calls)==2:raise OSError('area disappeared')
        return copy.deepcopy(st)
    c.reader.snapshot=snapshot
    with pytest.raises(OSError,match='area disappeared'):c.tick(st)
    row=events(c)[-1]
    assert row['state']=='post_observation_failed'
    assert 'hold_call_returned_monotonic' in row and 'after' not in row['players']['2']


def test_telemetry_write_failure_never_changes_command_or_tick_result(tmp_path,monkeypatch):
    class BrokenStats(dict):
        def __setitem__(self,*args):raise RuntimeError('telemetry unavailable')
    st,c,commands=rig(tmp_path,monkeypatch);c.inputs.stats=BrokenStats()
    assert c.tick(st)
    assert len([x for x in commands if x[1]!=['l']])==1
    assert c.margin_attempts[2]['attempts']==1


def test_ring_is_bounded_and_pose_is_copied(tmp_path,monkeypatch):
    st,c,_=rig(tmp_path,monkeypatch)
    p=st['players'][2];before=p['x']
    for _ in range(30):
        row=c._steering_begin(st,{2:(p,(22.5,27.5),'margin_recovery')},[(2,['lup'],.04)])
        c._steering_delivered(row);c._steering_finish(row,st,'observed')
    p['x']=9999
    raw=c.inputs.stats['steering_evidence_json']
    assert len(raw.encode())<=6000 and 1<=len(events(c))<=4
    assert events(c)[-1]['players']['2']['before']['x']==before


def test_held_no_movement_records_no_fabricated_steering(tmp_path,monkeypatch):
    st,c,commands=rig(tmp_path,monkeypatch);st['geometry_recovery_players']={}
    assert not c.tick(st)
    assert all(keys==['l'] for _,keys,_ in commands)
    assert 'steering_evidence_json' not in c.inputs.stats


def test_post_actor_replacement_is_visible_without_motion_attribution(tmp_path,monkeypatch):
    st,c,_=rig(tmp_path,monkeypatch);calls=[]
    def snapshot():
        calls.append(True);value=copy.deepcopy(st)
        if len(calls)==2:value['players'][2]['ptr']='other'
        return value
    c.reader.snapshot=snapshot
    assert c.tick(st)
    assert events(c)[-1]['players']['2']['same_actor'] is False
