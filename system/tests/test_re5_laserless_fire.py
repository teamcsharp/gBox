"""Real weapon policy -> combat/driver input, including the bow's absent laser and known mesh walls."""
import math

import pytest

from gbox.mercs.titles import re5_combat as C, re5_ps3 as R, re5_weapons as W
from gbox.mercs.titles.re5_nav import NavMesh
from test_re5_combat import ACT, PL, world, snap


def scene(wid=0x0F):
    memory = world(enemy=(0.,0.,1000.))
    state = snap(memory,enemy=(0.,0.,1000.))
    state.update(inventory=[{'slot':0,'id':0x100+wid,'item':wid,'type':1,'rounds':5,
                             'cap':5,'grid':3,'hand':True}],laser={'from':(0.,0.,0.),'at':(0.,0.,0.)},
                 bonuses=[],camera={'eye':(0.,140.,0.),'at':(0.,110.,1000.)})
    state['player']['pitch'] = math.atan2(-30.,1000.)
    state['nav'] = NavMesh([(-500.,0.,-500.),(500.,0.,-500.),(500.,0.,1500.),(-500.,0.,1500.)],
                          [(0,1,2),(0,2,3)],[[(1,2,1.)],[(0,0,1.)]])
    return memory,state


def test_real_longbow_policy_driver_presses_and_releases_without_laser_or_weapon_swap(tmp_path):
    memory,state = scene()
    bot = R.Bot(memory,clock=lambda:10.,learn_dir=tmp_path)
    other = dict(state['inventory'][0],slot=1,grid=1,item=0x1A,id=0x11A,hand=False)
    state['inventory'].append(other)
    assert W.best_quick_slot(state,state['enemies'][0]) is None
    memory.writes.clear()
    keys = []
    for index in range(6):
        bot.clock = lambda index=index:10.+index*.05
        keys.append(bot._tick(dict(state))['hold'])
    assert all('l1' in hold for hold in keys)
    assert ['r1' in hold for hold in keys] == [True,False,True,False,True,False]
    assert bot.stats['shots'] == 0  # Trigger pulses are not fabricated arrows.
    assert 'cover unconfirmed' in bot.stats['weapon_policy']
    assert not memory.writes or all(address != PL+C.P_PITCH for address,_ in memory.writes)


@pytest.mark.parametrize('wid',[0x0F,0x12])
def test_known_unlinked_mesh_wall_prevents_fire_even_at_close_range(tmp_path,wid):
    memory,state = scene(wid)
    state['nav'].links = [[],[]]  # Adjacent floor triangles separated by a native non-opening.
    # Across their shared diagonal, unlike the start/end which lie in the same triangle in scene().
    state['player']['pos'] = (-300.,0.,0.)
    state['enemies'][0]['pos'] = (300.,0.,0.)
    combat = C.Combat(memory,{},learn_dir=tmp_path)
    for now in (1.,1.1,2.):
        assert not ({'l1','r1'} & combat.tick(dict(state),state['player'],state['enemies'][0],now)['hold'])
    assert combat.needs_firing_position
    assert 'known-wall veto' in combat.stats['fire_gate']


def test_gun_without_ray_fires_from_finite_camera_then_returns_to_laser_when_available(tmp_path):
    memory,state = scene(0x12)
    combat = C.Combat(memory,{},learn_dir=tmp_path)
    assert {'l1','r1'} <= combat.tick(state,state['player'],state['enemies'][0],1.)['hold']
    assert 'camera direction' in combat.stats['aim_feedback']
    state['laser'] = {'from':(0.,149.,46.),'at':(0.,110.,1000.)}
    assert {'l1','r1'} <= combat.tick(state,state['player'],state['enemies'][0],1.1)['hold']
    assert combat.stats['aim_feedback'] == 'ray direction'
    assert combat.stats['shots'] == 0


@pytest.mark.parametrize('wid',[0x0F,0x12])
def test_missing_camera_uses_native_pitch_and_unknown_pitch_has_bounded_reacquisition(tmp_path,wid):
    memory,state = scene(wid)
    del state['camera']
    combat = C.Combat(memory,{},learn_dir=tmp_path)
    assert {'l1','r1'} <= combat.tick(state,state['player'],state['enemies'][0],1.)['hold']
    assert 'body/pitch estimate' in combat.stats['aim_feedback']
    del state['player']['pitch']
    assert combat.tick(state,state['player'],state['enemies'][0],2.) == {'hold':{'l1'}}
    assert combat.tick(state,state['player'],state['enemies'][0],2.5) == {'hold':set()}
    assert combat.needs_firing_position and combat.stats['shots'] == 0


def test_camera_points_at_wall_direction_turns_toward_enemy_before_any_arrow(tmp_path):
    memory,state = scene()
    state['camera']['at'] = (1000.,140.,0.)
    combat = C.Combat(memory,{},learn_dir=tmp_path)
    action = combat.tick(state,state['player'],state['enemies'][0],1.)
    assert 'r1' not in action['hold'] and {'rleft','rright'} & action['hold']
    assert 'aligning' in combat.stats['weapon_policy']


def test_actual_bow_native_fire_action_counts_once_without_inventing_dot_miss(tmp_path):
    memory,state = scene()
    combat = C.Combat(memory,{},learn_dir=tmp_path,lessons=lambda _:None)
    combat.tick(state,state['player'],state['enemies'][0],1.)
    memory.put(ACT,'>I',C.FIRE_VT)
    combat.tick(state,state['player'],state['enemies'][0],1.1)
    combat.tick(state,state['player'],state['enemies'][0],1.2)
    assert combat.stats['shots'] == 1
    combat.observe(dict(state),3.2)
    assert combat.stats['bow_unconfirmed_impacts'] == 1
    assert combat.stats['miss_beside'] == 0
    assert combat.stats['misses'] == 0 and combat.stats['accuracy'] is None


def test_no_laser_does_not_enable_unverified_splash_or_mine_controllers(tmp_path):
    memory,state = scene(0x0D)
    combat = C.Combat(memory,{},learn_dir=tmp_path)
    assert 'r1' not in combat.tick(state,state['player'],state['enemies'][0],1.)['hold']
    for wid in (0x0D,0x0C,0x0A,0x06):
        assert not W.laserless_fire_policy(wid,corridor=True,aligned=True,loaded=True)[0]


@pytest.mark.parametrize('wid',[0x0F,0x12])
def test_finite_but_unmoving_camera_releases_aim_and_yields_real_route_movement(tmp_path,wid):
    memory,state = scene(wid)
    state['camera']['at'] = (1000.,140.,0.)
    bot = R.Bot(memory,clock=lambda:10.,learn_dir=tmp_path)
    assert 'l1' in bot._tick(dict(state))['hold']
    bot.clock = lambda:12.6
    assert bot._tick(dict(state)) == {'hold':set()}
    assert bot.combat.needs_firing_position
    bot.clock = lambda:12.7
    action = bot._tick(dict(state))
    assert bot.stats['phase'] == 'pursue' and bot._following_route
    assert 'lup' in action['hold'] and not ({'l1','r1'} & action['hold'])
    bot.clock = lambda:13.2
    assert 'lup' in bot._tick(dict(state))['hold']
    assert bot.stats['shots'] == 0


def test_measured_aim_progress_extends_acquisition_within_finite_bow_lease(tmp_path):
    memory,state = scene()
    state['camera']['at'] = (1000.,140.,1000.)
    combat = C.Combat(memory,{},learn_dir=tmp_path)
    combat.tick(state,state['player'],state['enemies'][0],1.)
    state['camera']['at'] = (500.,140.,1000.)
    combat.tick(state,state['player'],state['enemies'][0],3.)
    combat.tick(state,state['player'],state['enemies'][0],3.9)
    assert not combat.needs_firing_position and combat.stats['shots'] == 0
    combat.tick(state,state['player'],state['enemies'][0],4.1)
    assert combat.needs_firing_position  # aiming progress alone cannot sustain an ineffective burst forever


def test_eggs_only_withholds_existing_gun_and_unverified_native_egg(tmp_path):
    memory,state=scene(0x12);state['rotten_egg_only']=True
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert 'r1' not in combat.tick(state,state['player'],state['enemies'][0],1.)['hold']
    state['inventory'][0].update(id=0x136,item=0x36)
    assert 'r1' not in combat.tick(state,state['player'],state['enemies'][0],1.1)['hold']


def test_egg_aligned_throw_ignores_unrelated_gun_laser_but_respects_floor_wall(tmp_path):
    memory,state=scene(0x36);state.update(rotten_egg_only=True,rotten_egg_native_equipped=True)
    state['laser']={'from':(0.,140.,0.),'at':(0.,140.,100.)}
    combat=C.Combat(memory,{},learn_dir=tmp_path)
    assert {'l1','r1'}<=combat.tick(state,state['player'],state['enemies'][0],1.)['hold']
    assert 'calibration' in combat.stats['laserless_visibility'] and combat.stats['shots']==0
    assert not W.fire_policy(0x36,state,state['enemies'][0],(0,0,1000))[0]
    state['nav'].links=[[],[]]
    state['player']['pos']=(-300.,0.,0.);state['enemies'][0]['pos']=(300.,0.,0.)
    assert 'r1' not in combat.tick(state,state['player'],state['enemies'][0],1.2)['hold']


def test_native_unequipped_egg_uses_ordinary_quick_equip_without_queuing_more_supply(tmp_path,monkeypatch):
    from gbox.mercs.titles import re5_eggs as E
    memory,state=scene(0x0F)
    egg={'slot':5,'id':0x136,'item':0x36,'type':1,'rounds':5,'grid':7,'hand':False}
    state['inventory'].append(egg);address=PL+R.P_INV+5*R.INV_SLOT
    memory.put(address+8,'>I',0x136);memory.put(address+0xC,'>I',5);memory.put(address+0x2D,'>B',1)
    bot=R.Bot(memory,learn_dir=tmp_path);bot._control_state={'rotten_eggs':{'on':True}}
    monkeypatch.setattr(E,'queue_supply',lambda ad:pytest.fail('existing native egg must not request more supply'))
    assert bot._egg_action(state['player'],state,10.)=={'hold':set()}
    state['player']['action']=0  # A neutral pad has lowered the previously aimed weapon.
    action=bot._egg_action(state['player'],state,11.1)
    assert action=={'tap':'ddown'}
    assert not bot._control_state['rotten_eggs']['native_equipped']
    assert bot.egg_return_weapon==W.inventory_key(state['inventory'][0])


def test_live_off_immediately_clears_native_egg_telemetry_and_pending_status(tmp_path):
    from gbox.mercs.titles import re5_eggs as E
    memory,state=scene(0x36);address=PL+R.P_INV;weapon=0x31D00000
    for offset,value in ((8,0x136),(0xC,5),(0x20,1),(0x30,weapon)):
        memory.put(address+offset,'>I',value)
    memory.put(address+0x2D,'>B',1);memory.put(weapon,'>I',E.EGG_VT)
    memory.put(weapon+0x111C,'>I',PL)
    bot=R.Bot(memory,learn_dir=tmp_path);cfg={'on':True,'status':'waiting for egg'}
    bot._control_state={'rotten_eggs':cfg}
    assert bot._egg_action(state['player'],state,10.) is None
    assert bot.stats['egg_native_equipped'] and state['rotten_egg_native_equipped']
    assert bot.stats['egg_status'].startswith('active:')
    cfg.update(on=False,status='disabled; ordinary weapon restore requested')
    bot._egg_action(state['player'],state,10.1)
    assert not bot.stats['egg_native_equipped'] and not state['rotten_egg_native_equipped']
    assert not cfg['native_equipped'] and bot.stats['egg_status']=='returning to existing gun'


def test_egg_mode_returns_to_new_preferred_gun_instead_of_cached_original(tmp_path):
    memory,state=scene(0x36)
    original={'slot':3,'id':0x112,'item':0x12,'type':1,'rounds':10,'cap':10,'grid':3,'hand':False}
    preferred={'slot':8,'id':0x11B,'item':0x1B,'type':1,'rounds':5,'cap':5,'grid':5,'hand':False}
    state['inventory'] += [original,preferred]
    bot=R.Bot(memory,learn_dir=tmp_path)
    bot._control_state={'rotten_eggs':{'on':False},'preferred_weapon':{'item':0x1B,'weapon':'S&W M500',
                        'target':W.inventory_key(preferred)}}
    bot.egg_requested=True;bot.egg_return_weapon=W.inventory_key(original)
    state['player']['action']=0
    assert bot._egg_action(state['player'],state,10.)=={'hold':set()}
    assert bot._egg_action(state['player'],state,11.1)=={'tap':'dright'}
