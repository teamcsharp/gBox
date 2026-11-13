"""Regression for Castle round aa770748: stale Waterworld bonus and wall pressure."""
import math

import pytest

import re4_nav_fixture as F
from gbox import re4switch_bot as B
from gbox.mercs.titles import re4_movement_safety as S
from gbox.mercs.titles import re4_nav as N, re4_switch as D, re4_walk as W, re4_traversal as T

CASTLE_WALL = (6241.9, 3073.2, -22228.5)
WATERWORLD_BONUS = (-4500., 12000., -22100.)


def snap(pos=(1000., 0., 2600.), yaw=0., mesh=None):
    return {'player': {'ptr': 101, 'generation': 7, 'pos': pos, 'rot': yaw, 'hp': 1000},
            'nav': mesh if mesh is not None else F.mesh(), 'enemies': [], 'timer': 90.}


def walker(s=None):
    w = W.Walker({'round_evidence_id': 'round-a'})
    w.observe(s or snap(), 0.)
    return w


def test_captured_castle_wall_cannot_walk_directly_to_foreign_waterworld_bonus():
    mesh = N.load('r402')
    assert mesh.member(CASTLE_WALL) == 3903
    assert mesh.route(CASTLE_WALL, WATERWORLD_BONUS, clearance=350.) is None
    w = walker(snap(CASTLE_WALL, -1.725, mesh))
    assert w.approach(WATERWORLD_BONUS) == ()
    assert w.no_exit() and w.stats['nav_direct_refused'] == 1
    assert not w.stats.get('nav_direct_ticks')


def test_combat_approach_honors_the_walkers_empty_safe_result():
    b = D.Bot(stats={}, director=False)
    s = snap(CASTLE_WALL, -1.725, N.load('r402'))
    W.walker_of(b).observe(s, 1.)
    keys, why = b._approach(s['player'], WATERWORLD_BONUS, .1, s, True)
    assert keys == set() and why == 'the mesh walker'


def test_actual_geometry_change_replaces_foreign_goal_and_issued_ids():
    b = D.Bot(stats={}, director=False)
    assert B.bonus_goal(b, snap(WATERWORLD_BONUS, mesh=N.load('r404')), 1.)
    g = W.goals_of(b)
    old = g.goal
    assert old['id'] == 'bonus-ITA[29]'
    assert B.bonus_goal(b, snap(CASTLE_WALL, mesh=N.load('r402')), 2.)
    assert old['state'] == 'unavailable'
    assert 'Stage geometry changed' in old['reason']
    assert g.goal['id'] != old['id']
    assert g.goal['geometry'][1] == 'r402'
    assert old['id'] not in b._bonus_issued
    assert b.stats['bonus_stage_invalidations'] == 1


def test_castle_combo_pickup_is_not_issued_as_time_bonus_even_when_nearest():
    mesh = N.load('r402')
    combo = next(r for r in mesh.bonuses if r['source'] == 'ITA[1]')
    assert combo['kind'] == 'combo_bonus'
    b = D.Bot(stats={}, director=False)
    assert B.bonus_goal(b, snap(tuple(combo['stand']), mesh=mesh), 1.)
    assert W.goals_of(b).goal['id'] != 'bonus-ITA[1]'
    selected = W.goals_of(b).goal['id'][6:]
    assert next(r for r in mesh.bonuses if r['source'] == selected)['kind'] == 'time_bonus'


def test_leaving_floor_during_same_stage_traversal_does_not_cancel_time_goal():
    b = D.Bot(stats={}, director=False)
    s = snap(WATERWORLD_BONUS, mesh=N.load('r404'))
    assert B.bonus_goal(b, s, 1.)
    goal = W.goals_of(b).goal
    old_state = goal['state']
    s['player']['pos'] = (-4500., 20000., -22100.)
    assert not B.bonus_goal(b, s, 2.)
    assert W.goals_of(b).goal is goal and goal['state'] == old_state


def test_picker_geometry_without_player_floor_does_not_issue_foreign_goals():
    b = D.Bot(stats={}, director=False)
    assert not B.bonus_goal(b, snap(CASTLE_WALL, mesh=N.load('r404')), 1.)
    assert W.goals_of(b).goal is None


def test_final_gate_checks_actual_heading_not_nominal_route_waypoint():
    w = walker(snap((2800., 0., 2800.), math.pi/2))
    w.wp = (2800., 1600., w.now)  # safe route goes south; actual gun-down stick goes east into wall
    out = S.guard(w, {'hold': {'lup', 'b', 'y'}, 'tap': 'y'})
    assert 'lup' not in out['hold'] and 'ldown' not in out['hold']
    assert 'y' in out['hold'] and out['tap'] == 'y'
    assert w.stats['walk_final_vetoes'] == 1


def test_route_outer_decorator_also_guards_bonus_commands(monkeypatch):
    b = D.Bot(stats={}, director=False)
    monkeypatch.setattr(W, 'operator_goal_act', lambda *a: {'hold': {'lup', 'b'}})
    out = b.tick(snap((2800., 0., 2800.), math.pi/2), now=0.)
    assert not set(out['hold']) & {'lup', 'ldown'}
    assert b._re4_last_act[1] == out
    assert b.stats['walk_final_vetoes'] == 1


def test_real_stationary_pressure_blocks_heading_and_turns_before_moving():
    w = walker()
    for t in (0., .2, .4, .6, .8, 1., 1.2, 1.4, 1.6):
        w.now = t
        out = S.guard(w, {'hold': {'lup', 'b'}})
    assert w.stats['walk_stalled_headings'] == 1
    assert w.stats['walk_failure']['net_mm'] == 0.
    assert w.stats['walk_failure']['units'] == 'mm'
    assert not set(out['hold']) & {'lup', 'ldown'}
    heading = w._final_walk['recovery']['heading']
    w.p['rot'] = heading
    w.now = 1.8
    out = S.guard(w, {'hold': {'lup', 'b'}})
    assert 'lup' in out['hold']
    assert S.clear(w, w._pos(), heading)


def test_real_progress_does_not_trigger_wall_failure():
    w = walker()
    for i in range(10):
        w.now = i*.2
        w.p['pos'] = (1000.+i*100., 0., 2600.)
        w.p['rot'] = math.pi/2
        S.guard(w, {'hold': {'lup'}})
    assert not w.stats.get('walk_stalled_headings')


def test_no_native_floor_escape_never_becomes_a_blind_backstep():
    w = walker(snap((4500., 3000., 3300.), 0.))
    out = S.guard(w, {'hold': {'lup', 'ldown', 'b', 'y'}})
    assert not set(out['hold']) & {'lup', 'ldown', 'b'}
    assert 'y' in out['hold']


def test_stationary_door_action_is_not_rewritten_by_prior_recovery():
    w = walker(snap((2800., 0., 2800.), math.pi/2))
    S.guard(w, {'hold': {'lup'}})
    w.now = .1
    act = {'hold': set(), 'tap': 'y'}
    assert S.guard(w, act) == act
    assert w._final_walk['recovery'] is None


def test_gun_stick_is_aim_not_floor_walking():
    w = walker(snap((2800., 0., 2800.), math.pi/2))
    act = {'hold': {'zl', 'zr', 'lup'}}
    assert S.guard(w, act) == act
    assert not w.stats.get('walk_final_vetoes')


def native_fact(w):
    return {'state': 'native', 'owner': T.identity(w.snap, w.stats), 'at': w.now,
            'routine': [0, 16, 0, 0], 'kind': 'ladder', 'handler': T.HANDLERS[16],
            'pos': list(w._pos())}


def test_owned_fresh_native_ladder_preserves_required_movement():
    w = walker(snap((4500., 1500., 2700.)))
    w.stats['traversal_observation'] = native_fact(w)
    act = {'hold': {'lup', 'y'}}
    assert S.guard(w, act) == act


def test_off_floor_native_traversal_defers_route_without_discarding_goal():
    w = walker(snap((4500., 1500., 2700.)))
    w.stats['traversal_observation'] = native_fact(w)
    assert w.approach((4500., 3000., 3300.)) == ()
    assert not w.no_exit()
    assert w.how == 'native traversal in progress'


@pytest.mark.parametrize('change', [lambda f: f.update(at=-1.),
    lambda f: f.update(owner=['old-round', 101, 7]), lambda f: f.update(handler=123),
    lambda f: f.update(routine=[0, 0, 0, 0]), lambda f: f.update(pos=[0, float('nan'), 0]),
    lambda f: f.update(routine=[0, [], 0, 0])])
def test_stale_or_unverified_traversal_never_bypasses_floor_admission(change):
    w = walker(snap((4500., 1500., 2700.)))
    fact = native_fact(w)
    change(fact)
    w.stats['traversal_observation'] = fact
    assert 'lup' not in S.guard(w, {'hold': {'lup'}})['hold']


def test_round_change_clears_pressure_and_blocked_heading():
    w = walker()
    S.guard(w, {'hold': {'lup'}})
    w._final_walk['blocked'] = {'pos': w._pos(), 'heading': 0., 'until': 100.}
    w.stats['round_evidence_id'] = 'new-round'
    w.now = .1
    assert 'lup' in S.guard(w, {'hold': {'lup'}})['hold']
    assert w._final_walk['blocked'] is None
