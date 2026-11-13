"""Replay the old-mine escape gap and final input priority, without game writes."""
import math
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_native_mine_escape as E, re5_switch_mines as M
from gbox.mercs.titles import re5_switch as R, re5_movement_safety as S
from gbox.mercs.titles.re5_nav import NavMesh


def mesh_grid():
    xs, zs = range(-3000, 3001, 250), range(-3000, 3001, 250)
    points = [(float(x), 0., float(z)) for z in zs for x in xs]
    tris = []
    for z in range(len(zs) - 1):
        for x in range(len(xs) - 1):
            a = z * len(xs) + x
            tris.extend(((a, a+1, a+len(xs)+1), (a, a+len(xs)+1, a+len(xs))))
    links, edges = [[] for _ in tris], {}
    for u, tri in enumerate(tris):
        for edge in range(3):
            pair = frozenset((tri[edge], tri[(edge+1) % 3]))
            if pair in edges:
                v, other = edges[pair]
                links[u].append((v, edge, 1.))
                links[v].append((u, other, 1.))
            else:
                edges[pair] = u, edge
    return NavMesh(points, tris, links)


def scene(pos=(50., 0., 350.), mines=None):
    bot = SimpleNamespace(stats={}, doing='walk', why='late wall rewrite', _sm=None,
                          _gun_down=lambda: None, _prompt_type=lambda *a: 'enemy')
    bot.mines = M.Mines(bot.stats)
    bot.mines.native = SimpleNamespace(job=None)
    bot.mines.bombs = mines or {1: (0., 0., 0.)}
    bot.mines._start_native_escape('request', next(iter(bot.mines.bombs.values())), 0.)
    snap = {'player': {'ptr': 10, 'generation': 1, 'pos': pos, 'rot': 0., 'hp': 1000, 'motion': 1},
            'mercenaries_phase': R.PHASE_PLAYING, 'enemies': [], 'ground_mines': [], 'nav': mesh_grid()}
    return bot, snap


def test_completed_recent_batch_cannot_hide_older_native_mine_within_three_meters():
    # Village 1bdc96ce: latest batch >15m clear, gen295 only251.8cm away.
    bot, snap = scene(pos=(-8126.58, 720., 4620.81), mines={295: (-8364.3, 720., 4537.91)})
    m = bot.mines
    latest = (-9429.33, 797.37, 2800.88)
    m._native_escape.update(center=latest, sites={99: latest}, pending=False, predicted=())
    m._native_tick(snap['player'], snap, [], 10.)
    assert m._native_escape is not None and bot.stats['native_mine_escape_required']
    assert bot.stats['native_mine_escape_clearance_cm'] == pytest.approx(251.8, abs=.1)
    assert bot.stats['native_mine_escape_hazards'] == 2


def test_new_escape_includes_still_active_older_completed_drop():
    bot, snap = scene()
    bot.mines._native_escape = None
    bot.mines._start_native_escape('new-request', (2000., 0., 0.), 2.)
    assert bot.mines._native_escape['sites'][1] == (0., 0., 0.)


def test_census_new_actor_constrains_completion_even_before_receipt_merge():
    bot, snap = scene(pos=(0., 0., 2000.))
    snap['ground_mines'] = [{'ptr': 2, 'pos': (0., 0., 2100.), 'active': True}]
    bot.mines._native_escape['pending'] = False
    bot.mines._native_tick(snap['player'], snap, [], 1.)
    assert bot.mines._native_escape is not None and bot.stats['native_mine_escape_clearance_cm'] == 100.
    snap['ground_mines'][0]['trigger_observed'] = True
    bot.mines._native_tick(snap['player'], snap, [], 2.)
    assert bot.mines._native_escape is None


def test_missing_census_cannot_erase_retained_native_mine():
    bot, snap = scene()
    snap['ground_mines'] = None
    assert bot.mines.native_sites(snap) == {1: (0., 0., 0.)}


def test_all_mine_route_does_not_enter_older_armed_mine_to_escape_latest():
    bot, snap = scene(pos=(50., 0., 350.), mines={1: (0., 0., 0.), 2: (0., 0., 1700.)})
    path = E.route(bot, snap, snap['player']['pos'])
    assert path
    assert all(M.flat(path[-1], p) >= M.RETREAT_CM for p in bot.mines.bombs.values())
    assert all(E._clear(bot, snap, a, b) for a, b in zip([snap['player']['pos']] + path, path))
    assert any(abs(p[0]) > 1000. for p in path)  # a supported sideways exit between mines


@pytest.mark.parametrize('action', [{'hold': ('zl', 'zr')}, {'hold': ('ldown', 'lleft')}, {'hold': ()}])
def test_final_guard_replaces_combat_wall_or_idle_rewrite_with_clear_escape(action):
    bot, snap = scene()
    out = E.guard(bot, action, snap, 1.)
    heading = S._travel_heading(snap['player'], out['hold'])
    assert heading is not None and not set(out['hold']) & {'zl', 'zr', 'dup', 'ddown', 'dleft', 'dright'}
    assert E._clear(bot, snap, snap['player']['pos'], S._end(snap['nav'], snap['player']['pos'], heading))
    assert bot.doing == 'mine' and bot.stats['native_mine_escape_final']['requested_hold'] == list(action['hold'])


@pytest.mark.parametrize('cause', ['held', 'prompt', 'equip', 'heal', 'operator'])
def test_mandatory_input_and_animation_synchronization_are_preserved(cause):
    bot, snap = scene()
    action = {'hold': ('a',)}
    if cause == 'held': snap['player']['motion'] = next(iter(R.MOTION_HELD))
    elif cause == 'prompt': bot.doing, snap['prompt'] = 'prompt', {'kind': 1}
    elif cause == 'equip': bot.doing = 'native_equip'
    elif cause == 'heal': bot.doing = 'heal'
    else: bot.stats['operator_control'] = True
    assert E.guard(bot, action, snap, 1.) is action
    if cause != 'operator': assert bot.stats['native_mine_escape_pause']


@pytest.mark.parametrize('cause', ['shot', 'tail'])
def test_shot_movement_lock_releases_trigger_so_escape_cannot_be_starved(cause):
    bot, snap = scene()
    if cause == 'shot': snap['player']['motion'] = R.MOTION_SHOT
    else: bot._shot_until = 2.
    assert E.guard(bot, {'hold': ('zl', 'zr', 'lup')}, snap, 1.) == {'hold': ()}
    assert 'boosted shot' in bot.stats['native_mine_escape_pause']
    snap['player']['motion'], bot._shot_until = 1, 1.15
    assert S._travel_heading(snap['player'], E.guard(bot, {'hold': ()}, snap, 1.2)['hold']) is not None


def test_census_discovery_requires_departure_even_when_no_receipt_started_escape():
    bot, snap = scene()
    bot.mines.bombs.clear()
    bot.mines._native_escape = None
    snap['ground_mines'] = [{'ptr': 2, 'pos': (0., 0., 0.), 'active': True}]
    out = E.guard(bot, {'hold': ('zl', 'zr')}, snap, 1.)
    assert S._travel_heading(snap['player'], out['hold']) is not None
    assert bot.doing == 'mine'


def test_guard_does_not_invent_floor_or_walk_through_solid_room_collision():
    for unavailable in (True, False):
        bot, snap = scene()
        if unavailable: snap['nav'] = None
        else: bot._sm = SimpleNamespace(walk_block=lambda *a, **kw: 'wall')
        out = E.guard(bot, {'hold': ('lup', 'b')}, snap, 1.)
        assert out['hold'] == ()
        assert bot.stats['native_mine_escape_final']['safe_end'] is None


def test_safe_route_and_final_guard_escape_identified_five_foot_ring():
    points = {i: (152.4*math.sin(i*math.tau/5), 0., 152.4*math.cos(i*math.tau/5)) for i in range(5)}
    bot, snap = scene(pos=(0., 0., 0.), mines=points)
    bot.mines._native_escape['center'] = (0., 0., 0.)
    out = E.guard(bot, {'hold': ('zl',)}, snap, 1.)
    h = S._travel_heading(snap['player'], out['hold'])
    assert h is not None and E._clear(bot, snap, snap['player']['pos'], S._end(snap['nav'], snap['player']['pos'], h))


def test_after_completed_departure_final_guard_still_blocks_reentry_to_old_mine():
    bot, snap = scene(pos=(50., 0., 1600.))
    bot.mines._native_escape = None
    out = E.guard(bot, {'hold': ('ldown',)}, snap, 1.)
    assert out['hold'] != ('ldown',)
    h = S._travel_heading(snap['player'], out['hold'])
    assert h is not None and S._mine_clear(bot, snap, snap['player']['pos'], S._end(snap['nav'], snap['player']['pos'], h))


def test_safely_departed_combat_is_left_unchanged():
    bot, snap = scene(pos=(50., 0., 1800.))
    action = {'hold': ('zl', 'zr')}
    assert E.guard(bot, action, snap, 1.) is action


def test_aim_write_needs_fresh_heading_but_early_escape_prevents_new_aim():
    bot,snap = scene()
    bot.stats['target_feedback_ram'] = True
    assert E.guard(bot,{'hold':('zl','zr')},snap,1.) == {'hold':()}
    # Before aim runs, the current snapshot is authoritative; a previous tick's
    # feedback flag cannot prevent taking the escape lane this tick.
    out = E.guard(bot,{'hold':('zl','zr')},snap,1.,before_aim=True)
    assert 'zl' not in out['hold'] and 'zr' not in out['hold']
    assert S._travel_heading(snap['player'],out['hold']) is not None


def test_same_tick_aim_flag_cannot_override_mandatory_held_qte():
    bot,snap = scene()
    bot.stats['target_feedback_ram'] = True
    snap['player']['motion'] = next(iter(R.MOTION_HELD))
    action = {'hold':('lup',)}
    assert E.guard(bot,action,snap,1.) is action


def test_stage_incinerator_remains_a_hard_exclusion_during_mine_escape():
    from test_re5_stage_hazards import floor_grid
    bot, snap = scene(pos=(-2713., 470., -22500.), mines={1: (-2713., 470., -22000.)})
    snap['nav'] = floor_grid()
    snap['player']['rot'] = math.pi
    out = E.guard(bot, {'hold': ('lup', 'b')}, snap, 1.)
    h = S._travel_heading(snap['player'], out['hold'])
    if h is not None:
        end = S._end(snap['nav'], snap['player']['pos'], h)
        assert E.hazards.blocked_segment(snap['nav'], snap['player']['pos'], end, departing=True) is None
    assert out['hold'] != ('lup', 'b')
