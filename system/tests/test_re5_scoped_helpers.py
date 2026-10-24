"""P2 prerequisites remain read-only and cannot borrow the human's state."""
import copy
import struct

from gbox.mercs.titles import re5_combat as B, re5_health as H
from gbox.mercs.titles import re5_inventory_health as I, re5_ps3 as R
from test_re5_coop import world

P1, P2, A1, A2 = 0x303F7800, 0x30407800, 0x30500000, 0x30510000
ENEMY, ITEM, UI1, UI2 = 0x30600000, 0x30700000, 0x30800000, 0x30810000


def scoped_world():
    m=world(True);m.mercs_player_index=1
    for player,action in ((P1,A1),(P2,A2)):
        m.u(player+B.P_ACTION_OBJ,action);m.u(action,B.READY_VT);m.u(action+0x18,player)
        m.put(action+B.ACT_FRAMES,struct.pack('>f',1.))
    return m


def state(player=P2,hp=800,kills=0):
    return {'player':{'ptr':player,'hp':600,'hp_max':1000,'action':B.AIMING,'pos':(101.,0.,200.),'rot':0.},
        'inventory':[{'slot':0,'id':0x112,'item':0x12,'type':1,'rounds':6,'hand':True}],
        'enemies':[{'ptr':ENEMY,'slot':0,'hp':hp,'hp_max':800,'pos':(101.,0.,600.)}],
        'timer':100.,'kills':kills}


def test_scoped_health_pickup_accepts_only_own_current_prompt_and_actor(monkeypatch):
    m=scoped_world();item={'ptr':ITEM,'handle':35,'id':0x305,'pos':(0.,0.,0.)}
    request={'token':'mash:square','kind':R.BTN_STAGE,'label':R.PICKUP_LABEL,
             'button':A2,'mode':1,'owner':P2,'target':35}
    monkeypatch.setattr(R,'selected_prompt',lambda *_args,**_kwargs:dict(request))
    monkeypatch.setattr(H,'ground_items',lambda _m:[dict(item)])
    before=dict(m.data)
    assert H.pickup_request(m,request,[item])==item and m.data==before
    assert H.pickup_request(m,{**request,'owner':P1},[item]) is None
    def change_scope(_memory):
        m.mercs_player_index=0
        return [dict(item)]
    monkeypatch.setattr(H,'ground_items',change_scope)
    assert H.pickup_request(m,request,[item]) is None


def test_inventory_decodes_scoped_actor_but_unproven_p2_owner_never_emits_input():
    m=scoped_world()
    for address,data in I.SIGNATURES.items():m.put(address,data)
    m.put(I.GRID_TABLE,struct.pack('>36i',*(n for row in I.GRID_NEIGHBORS for n in row)))
    for player,ui,cursor in ((P1,UI1,2),(P2,UI2,8)):
        m.u(player+I.PLAYER_INVENTORY_UI,ui)
        raw=bytearray(0x80);raw[4]=2
        struct.pack_into('>I',raw,8,cursor);struct.pack_into('>I',raw,0x10,1 if player==P2 else 0)
        struct.pack_into('>2f',raw,0x50,1.,0.);m.put(ui,raw)
    before=dict(m.data)
    assert I.read_state(m,P2)['pointer']==UI2 and I.read_state(m,P2)['cursor']==8
    assert I.read_state(m,P1) is None
    ctl=I.Controller();s=state();item={'slot':2,'id':0x304,'rounds':1,'grid':8,'hand':False}
    s['inventory']=[item]
    for observed_owner in (0,1):
        ctl.reader=lambda *_args:{'owner':observed_owner}  # neither value is verified authorization
        assert ctl.tick(m,s,item,1.) is None and not ctl.active
        assert 'Player 2 unsupported' in ctl.stats['inventory_heal_status']
    assert m.data==before


def test_combat_uses_only_scoped_owned_action_not_human_fire(tmp_path):
    m=scoped_world();combat=B.Combat(m,{},learn_dir=tmp_path,lessons=lambda _e:None)
    combat.observe(state(),1.)
    m.u(A1,B.FIRE_VT)
    assert not combat.observe(state(),1.1)[3] and combat.stats['shots']==0
    m.u(A2,B.FIRE_VT)
    assert combat.observe(state(),1.2)[3] and combat.stats['shots']==1
    m.u(A2+0x18,P1)
    assert combat._action(P2) is None and combat._action(P1) is None


def test_global_laser_scan_never_supplies_player2_aim_feedback(tmp_path):
    m=scoped_world();combat=B.Combat(m,{},learn_dir=tmp_path,lessons=lambda _e:None)
    def forbidden(_now):raise AssertionError('global laser has no verified player owner')
    combat.laser.read=forbidden
    assert combat._ray(state(),1.) is None
    m.mercs_player_index=None
    assert combat._ray(state(),1.) is None


def test_shared_hp_loss_and_team_kills_never_become_p2_accuracy_or_aim_training(tmp_path):
    m=scoped_world();events=[];combat=B.Combat(m,{},learn_dir=tmp_path,lessons=events.append)
    combat.observe(state(),1.)
    m.u(A2,B.FIRE_VT);combat.observe(state(),1.1)
    combat.observe(state(hp=500,kills=1),1.2)
    combat.observe(state(hp=500,kills=1),1.6)
    assert combat.stats['shots']==1
    assert combat.stats['hits']==combat.stats['misses']==0
    assert combat.stats['accuracy'] is None and combat.stats['round_accuracy'] is None
    assert combat.stats['enemy_hp_loss_unattributed']==300
    assert combat.stats['team_kills_seen_by_combat']==1
    assert not combat.stats.get('kills_seen_by_combat') and combat.stats['shots_per_kill'] is None
    assert combat.stats['shot_impacts_unattributed']==1 and not combat.stunned
    before=copy.deepcopy(combat.tun.d)
    combat.end_round(2.)
    assert combat.tun.d==before
    assert events[-1]['damage_attribution']=='unattributed_multiple_players' and events[-1]['hit_rate'] is None


def test_missing_or_replaced_p2_never_observes_or_controls_p1(tmp_path):
    m=scoped_world();combat=B.Combat(m,{},learn_dir=tmp_path,lessons=lambda _e:None)
    human=state(P1);before=dict(m.data)
    assert combat.tick(human,human['player'],human['enemies'][0],1.)=={'hold':set()}
    m.put(P2+0x2F14,b'\0')
    own=state()
    assert combat.tick(own,own['player'],own['enemies'][0],1.1)=={'hold':set()}
    assert combat.stats['shots']==0 and m.data=={**before,P2+0x2F14:0}


def test_human_also_present_disables_individual_attribution_even_when_controlling_p1(tmp_path):
    m=scoped_world();m.mercs_player_index=0
    combat=B.Combat(m,{},learn_dir=tmp_path,lessons=lambda _e:None)
    combat.observe(state(P1),1.)
    m.u(A1,B.FIRE_VT);combat.observe(state(P1),1.1)
    combat.observe(state(P1,hp=500),1.2);combat.observe(state(P1,hp=500),1.6)
    assert combat.stats['shots']==1 and combat.stats['enemy_hp_loss_unattributed']==300
    assert combat.stats['accuracy'] is None and combat.stats['hits']==combat.stats['misses']==0


def test_legacy_solo_action_and_temporal_hit_detection_remain_available(tmp_path):
    m=world();m.u(P1+B.P_ACTION_OBJ,A1);m.u(A1,B.READY_VT)
    m.put(A1+B.ACT_FRAMES,struct.pack('>f',1.))
    # The old solo action fixture has no owner field; default behavior is preserved.
    combat=B.Combat(m,{},learn_dir=tmp_path,lessons=lambda _e:None)
    combat.observe(state(P1),1.)
    m.u(A1,B.FIRE_VT);combat.observe(state(P1),1.1)
    combat.observe(state(P1,hp=500),1.2)
    assert combat.stats['shots']==combat.stats['hits']==1
    assert combat.stats['accuracy']==1. and not combat.damage_unattributed


def test_action_ownership_changed_during_observation_is_not_a_p2_fire_action(tmp_path):
    m=scoped_world();combat=B.Combat(m,{},learn_dir=tmp_path,lessons=lambda _e:None)
    original=m.rd
    def changing_read(address,size):
        value=original(address,size)
        if address==A2+B.ACT_FRAMES:m.u(A2+0x18,P1)
        return value
    m.rd=changing_read
    assert combat._action(P2) is None
