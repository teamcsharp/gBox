import math
from types import SimpleNamespace

from gbox.mercs.titles import re5_movement_safety as S
from gbox.mercs.titles import re5_stage_hazards as H


def setup(pos=(-2713.36, 470., -22600.), rot=math.pi):
    mesh = SimpleNamespace(sig=H.MISSILE_GEOMETRY, floor_segment=lambda a, b: True)
    bot = SimpleNamespace(stats={}, _mroute={'pts': [(-2700.,470.,-23000.)], 'at': 10.},
                          _mesh_wp=(0., 0., 10.), mines=None, _sm=None)
    snap = {'nav': mesh, 'player': {'pos': pos, 'rot': rot, 'hp': 1000}}
    return bot, snap


def endpoint(snap, hold):
    return S._end(snap['nav'], snap['player']['pos'], S._travel_heading(snap['player'], hold))


def test_recorded_death_approach_is_vetoed_before_native_boundary():
    b, snap = setup()
    out = S.guard(b, {'hold': ('lup', 'b')}, snap, 10.)
    assert out['hold'] != ('lup', 'b')
    assert H.blocked_segment(snap['nav'], snap['player']['pos'], endpoint(snap, out['hold']), departing=True) is None
    assert b.stats['stage_hazard_last']['hazard']['name'] == 'incineratorC'
    assert b._mroute['pts'] is None and b._mesh_wp is None


def test_sideways_and_backwards_escape_commands_are_checked_in_world_space():
    for rot, keys in ((math.pi/2, ('lleft',)), (0., ('ldown',))):
        b, snap = setup(rot=rot)
        out = S.guard(b, {'hold': keys}, snap, 10.)
        assert out['hold'] != keys
        assert H.blocked_segment(snap['nav'], snap['player']['pos'], endpoint(snap,out['hold']), departing=True) is None


def test_native_box_is_not_excluded_on_a_different_floor_or_geometry():
    for y, sig in ((0., H.MISSILE_GEOMETRY), (470., 'another stage')):
        b, snap = setup(pos=(-2713., y, -22600.))
        snap['nav'].sig = sig
        action = {'hold': ('lup', 'b')}
        assert S.guard(b, action, snap, 10.) is action


def test_safe_departure_from_margin_is_not_trapped():
    b, snap = setup(pos=(-2713., 470., -22700.), rot=0.)
    action = {'hold': ('lup', 'b')}
    assert S.guard(b, action, snap, 10.) is action


def test_no_safe_floor_stops_movement_but_keeps_combat_controls():
    b, snap = setup()
    snap['nav'].floor_segment = lambda a,b: False
    out = S.guard(b, {'hold': ('lup','b','zl','zr')}, snap, 10.)
    assert out['hold'] == ('zl','zr')
    assert b.stats['stage_hazard_last']['safe_end'] is None


def test_detour_cannot_run_toward_another_live_mine():
    b, snap = setup()
    # Reject every geometrically safe heading except north. Mine is south, so
    # the chosen retreat must monotonically increase its clearance.
    b.mines = SimpleNamespace(bombs={1:(-2713.,470.,-23000.)})
    out = S.guard(b, {'hold': ('lup','b')}, snap, 10.)
    assert S._mine_clear(b, snap, snap['player']['pos'], endpoint(snap,out['hold']))


def test_solid_collision_still_vetoes_hazard_detour():
    b, snap = setup()
    b._sm = SimpleNamespace(walk_block=lambda *a,**kw: 'wall')
    out = S.guard(b, {'hold': ('lup','b')}, snap, 10.)
    assert out['hold'] == ()


def test_final_bot_tick_vetoes_a_late_postprocessor_movement(monkeypatch):
    from test_re5_switch_nav import bot, snap as make_snap
    b, _ = bot()
    _, state = setup()
    snap = make_snap()
    snap['player'].update(state['player'])
    snap['nav'] = state['nav']
    monkeypatch.setattr(b, '_tick', lambda *a: {'hold': ()})
    for name in ('_mesh_guard','_room_guard','_wall_gov','_never_stand','_calm_sticks',
                 '_governor','_shot_tail','_native_equipment'):
        monkeypatch.setattr(b, name, lambda action,*a: action)
    monkeypatch.setattr(b, '_special', lambda phase,*a: {'hold': ('lup','b')} if phase == 'post' else None)
    out = b.tick(snap)
    assert out['hold'] != ('lup','b')
    assert b.stats['combat_action'] == 'hazard_avoid'
    assert b.stats['combat_hold'] == ','.join(out['hold'])


def test_ring_center_can_escape_between_mines_without_waiving_external_mine():
    b, snap = setup()
    center = snap['player']['pos']
    sites = {i: (center[0]+152.4*math.sin(i*2*math.pi/5), center[1],
                 center[2]+152.4*math.cos(i*2*math.pi/5)) for i in range(5)}
    b.mines = SimpleNamespace(bombs=sites.copy(), _native_escape={'center':center,'sites':sites})
    gap = math.pi/5
    end = (center[0]+200*math.sin(gap),center[1],center[2]+200*math.cos(gap))
    assert S._mine_clear(b,snap,center,end)
    # A direct step across the north mine remains forbidden.
    assert not S._mine_clear(b,snap,center,(center[0],center[1],center[2]+200))
    b.mines.bombs[99] = (end[0]*2-center[0], center[1], end[2]*2-center[2])
    assert not S._mine_clear(b,snap,center,end)


def test_hazard_coverage_is_cleared_on_unknown_geometry():
    b,snap = setup()
    S.guard(b,{'hold':()},snap,1.)
    assert b.stats['stage_hazard_coverage']['volumes'] == 3
    snap['nav'].sig = 'other'
    S.guard(b,{'hold':()},snap,2.)
    assert b.stats['stage_hazard_coverage']['volumes'] == 0


def test_prompt_admission_blocks_hazard_traversal_and_preserves_grab_qte():
    from gbox.mercs.titles import re5_switch as R, re5_switch_prompt as P
    b = R.Bot(stats={}, clock=lambda:10.)
    _,snap = setup()
    snap['prompt'] = {'kind':P.KIND_PLAYER, 'token':'press:y', 'label':9876}
    assert not b.prompt_ok('y',snap,10.)
    assert not b._prompt_wanted('traverse',snap['player'],snap)
    snap['prompt'] = {'kind':P.KIND_ENEMY, 'mode':6}
    assert b.prompt_ok('y',snap,10.)


def test_final_stage_guard_preserves_verified_grab_stick_qte():
    from gbox.mercs.titles import re5_switch as R, re5_switch_prompt as P
    b,snap = setup()
    snap['player']['motion'] = next(iter(R.MOTION_HELD))
    action = {'hold':('lup',)}
    assert S.guard(b,action,snap,10.) is action
    snap['player']['motion'] = 0
    snap['prompt'] = {'kind':P.KIND_ENEMY,'mode':6}
    b.doing = 'prompt'
    b._prompt_type = lambda *a: 'enemy'
    assert S.guard(b,action,snap,11.) is action
