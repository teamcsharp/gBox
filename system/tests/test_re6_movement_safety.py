"""Final floor safety survives late movement rewrites and stale native yaw."""
import math
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re6_switch as R, re6_movement_safety as S
from gbox.mercs.titles.re6_switch_wall import stick_heading
from tests.test_re6_switch_wall import setup


def square(size=400.):
    return R.NavMesh([(0., 0., 0.), (size, 0., 0.), (size, 0., size), (0., 0., size)],
                     [(0, 1, 2), (0, 2, 3)], [[1], [0]], 'square_floor')


def view(mesh=None, pos=(200., 0., 330.)):
    return dict(mercenaries_phase=R.PHASE_PLAYING, navmesh=mesh or square(), camera={'yaw': 0.},
                player=dict(ptr=123, hp=900, pos=pos, rot=0., action='cPlAction_pl_act_walk'))


def bot(**kw):
    return SimpleNamespace(stats={}, in_hold=False, down=False, nav_path=[(0., 0., 1000.)], **kw)


def end(snap, held):
    yaw, pos = snap['camera']['yaw'], snap['player']['pos']
    heading = stick_heading(held, yaw)
    return (pos[0] + S.LOOKAHEAD_CM * math.sin(heading), pos[1], pos[2] + S.LOOKAHEAD_CM * math.cos(heading))


@pytest.mark.parametrize('late', ['_never_stand', '_govern'])
def test_late_movement_rewrite_cannot_restore_walk_off_ledge(monkeypatch, late):
    b, clock, snap = setup(monkeypatch, hold=())
    snap.update(view())
    monkeypatch.setattr(b, late, (lambda action, s, now: {'hold': ('lup',)}) if late == '_never_stand'
                        else (lambda s, action, now: {'hold': ('lup',)}))
    out = b.tick(snap)
    assert out['hold'] != ('lup',)
    assert snap['navmesh'].clear(snap['player']['pos'], end(snap, out['hold'])) is True
    assert b.stats['floor_safety_blocks'] == 1
    assert b._movement_guard['previous'][3] == out['hold']  # feedback sees actual guarded pad


def test_firing_is_preserved_while_unsafe_backstep_is_redirected():
    b, snap = bot(), view(pos=(200., 0., 50.))
    out = S.guard(b, snap, {'hold': ('ldown', 'zl', 'zr')}, 100.)
    assert {'zl', 'zr'} <= set(out['hold'])
    assert snap['navmesh'].clear(snap['player']['pos'], end(snap, out['hold'])) is True
    assert b.nav_path is None


def test_no_safe_floor_direction_stops_movement_but_retains_gunfire():
    b, snap = bot(), view(square(100.), (50., 0., 50.))
    out = S.guard(b, snap, {'hold': ('lup', 'b', 'rleft', 'zl', 'zr')}, 100.)
    assert out['hold'] == ('zl', 'zr')
    assert 'no verified floor' in b.stats['floor_safety_last']['reason']


def test_off_floor_start_is_not_rescued_by_nearest_triangle_fallback():
    b, snap = bot(), view(pos=(500., 0., 500.))
    assert snap['navmesh'].locate(snap['player']['pos']) is not None
    assert S.guard(b, snap, {'hold': ('lup',)}, 100.)['hold'] == ()


def test_camera_world_yaw_controls_the_actual_quantized_safe_direction():
    b, snap = bot(), view(pos=(330., 0., 200.))
    snap['camera']['yaw'] = math.pi / 2
    out = S.guard(b, snap, {'hold': ('lup',)}, 100.)
    assert out['hold'] != ('lup',)
    assert snap['navmesh'].clear(snap['player']['pos'], end(snap, out['hold'])) is True


def test_native_aim_write_does_not_reuse_snapshot_yaw_near_edge():
    b, snap = bot(lock_write_at=100.), view()
    action = {'hold': ('ldown', 'zl', 'zr')}  # safe under the old yaw alone
    assert S.guard(b, snap, action, 100.)['hold'] == ('zl', 'zr')
    assert b.stats['floor_safety_last']['native_heading_write']
    assert S.guard(b, snap, action, 100.1) == action  # fresh later camera sample


def test_same_tick_gun_down_cannot_erase_native_heading_write_evidence():
    b, snap = bot(lock_write_at=None, _floor_heading_written_at=100.), view()
    assert S.guard(b, snap, {'hold': ('ldown',)}, 100.)['hold'] == ()


def test_native_aim_write_keeps_running_where_the_entire_disk_is_floor():
    b, snap = bot(lock_write_at=100.), view(square(1000.), (500., 0., 500.))
    action = {'hold': ('lup', 'zl', 'zr')}
    assert S._all_headings_on_floor(snap['navmesh'], snap['player']['pos'])
    assert S.guard(b, snap, action, 100.) == action


@pytest.mark.parametrize('act', ['break_free', 'held_auto_qte', 'prompt_stick'])
def test_mandatory_qte_sticks_are_not_mistaken_for_free_walking(act):
    b, snap = bot(), view(square(100.), (50., 0., 50.))
    b.stats['act'] = act
    action = {'hold': ('lup', 'lleft', 'a')}
    assert S.guard(b, snap, action, 100.) == action


def test_native_active_ladder_retains_controls_until_its_grounded_exit():
    b, snap = bot(), view(pos=(200., -200., 330.))
    snap['player']['action'] = 'cSmVLadderEventCh_Climb'
    action = {'hold': ('lup',)}
    assert S.guard(b, snap, action, 100.) == action
    snap['player']['action'], snap['player']['pos'] = 'cPlAction_pl_act_walk', (200., 0., 330.)
    assert S.guard(b, snap, action, 100.1) != action


def test_safe_original_bomb_escape_is_preserved_and_floor_detour_avoids_external_bomb():
    b, snap = bot(), view()
    b.stats['mine_avoid_positions'] = [[330., 0., 330.]]
    out = S.guard(b, snap, {'hold': ('lup',)}, 100.)
    assert 'lright' in out['hold']  # world left, away from the bomb to the east
    assert S._bomb_clear(b, snap, snap['player']['pos'], end(snap, out['hold']))


def test_identified_surrounding_remote_ring_permits_escape_without_weakening_external_clearance():
    b, snap = bot(), view()
    center = snap['player']['pos']
    sites = [[center[0] + 200 * math.cos(i * math.tau / 15), 0.,
              center[2] + 200 * math.sin(i * math.tau / 15)] for i in range(15)]
    b.stats.update(mine_avoid_positions=sites,
                   mine_ring_last=dict(op='bomb_ring', requested=15, radius_cm=200.,
                                       units=[dict(pos=p, armed=True) for p in sites]))
    out = S.guard(b, snap, {'hold': ('lup',)}, 100.)
    assert set(out['hold']) & S.LEFT
    point = end(snap, out['hold'])
    assert S._bomb_clear(b, snap, center, point)
    # A separate bomb on this detour remains protected by the full distance rule.
    b.stats['mine_avoid_positions'] = sites + [[point[0], point[1], point[2]]]
    assert not S._bomb_clear(b, snap, center, point)


def test_ring_kept_in_mine_rings_stays_escapable_after_a_later_travel_receipt():
    # The controller publishes every confirmed ring's constructor geometry to mine_rings. A later travel drop
    # overwrites mine_ring_last; without the retained geometry the movement guard loses its radial-escape proof
    # while the ring still lies around him (live 2026-11-13: floor_safety_blocks climbing, armed ring left pending).
    b, snap = bot(), view()
    center = snap['player']['pos']
    sites = [[center[0] + 200 * math.cos(i * math.tau / 15), 0.,
              center[2] + 200 * math.sin(i * math.tau / 15)] for i in range(15)]
    travel = dict(op='bomb_trail', requested=1, radius_cm=0.,
                  units=[dict(pos=[center[0] + 5., 0., center[2]], armed=True)])
    b.stats.update(mine_avoid_positions=sites,
                   mine_rings=[dict(op='bomb_ring', requested=15, radius_cm=200.,
                                    units=[dict(pos=p, armed=True) for p in sites])],
                   mine_ring_last=travel)
    out = S.guard(b, snap, {'hold': ('lup',)}, 100.)
    point = end(snap, out['hold'])
    assert set(out['hold']) & S.LEFT
    assert S._bomb_clear(b, snap, center, point)
    # The identical step is refused when the ring geometry was not retained (the pre-fix behaviour).
    b2, snap2 = bot(), view()
    b2.stats.update(mine_avoid_positions=sites, mine_ring_last=travel)
    assert not S._bomb_clear(b2, snap2, center, point)


def test_departure_from_nearest_bomb_cannot_approach_another_unsafe_bomb():
    b = bot()
    b.stats['mine_avoid_positions'] = [[-100., 0., 0.], [600., 0., 0.]]
    # Nearest clearance improves 100->250, but the other bomb closes 600->450.
    assert not S._bomb_clear(b, {}, (0., 0., 0.), (150., 0., 0.))
    assert S._bomb_clear(b, {}, (0., 0., 0.), (0., 0., 150.))


def test_already_safe_external_bomb_keeps_margin_along_whole_detour_segment():
    b = bot()
    b.stats['mine_avoid_positions'] = [[0., 0., 0.]]
    assert not S._bomb_clear(b, {}, (1200., 0., 0.), (1050., 0., 0.))
    # Both endpoints exceed 1100cm, yet the connecting chord enters the margin.
    assert not S._bomb_clear(b, {}, (-150., 0., 1099.), (150., 0., 1099.))
    assert S._bomb_clear(b, {}, (1250., 0., 0.), (1100., 0., 0.))


def test_external_bomb_margin_honors_larger_configured_clearance():
    b = bot()
    b.stats.update(mine_avoid_positions=[[0., 0., 0.]], remote_mines={'detonate_safe_cm': 1500.})
    assert not S._bomb_clear(b, {}, (1550., 0., 0.), (1400., 0., 0.))
    assert S._bomb_clear(b, {}, (1400., 0., 0.), (1450., 0., 0.))


def test_external_bomb_margin_honors_native_stage_tuning():
    b = bot()
    b.stats.update(mine_avoid_positions=[[0., 0., 0.]], mine_required_clearance_cm=1200.)
    assert not S._bomb_clear(b, {}, (1250., 0., 0.), (1150., 0., 0.))
    assert S._bomb_clear(b, {}, (1150., 0., 0.), (1250., 0., 0.))


def test_deadline_final_move_checks_bomb_clearance_even_on_open_floor():
    b, snap = bot(), view(square(2000.), (1000., 0., 1000.))
    b.stats.update(mine_escape_required=True, mine_avoid_positions=[[1000., 0., 1200.]])
    out = S.guard(b, snap, {'hold': ('lup',)}, 100.)
    assert out['hold'] != ('lup',)
    assert snap['navmesh'].clear(snap['player']['pos'], end(snap, out['hold'])) is True
    assert S._bomb_clear(b, snap, snap['player']['pos'], end(snap, out['hold']))


def test_deadline_escape_waits_for_fresh_camera_even_on_open_floor():
    b, snap = bot(lock_write_at=100.), view(square(2000.), (1000., 0., 1000.))
    b.stats.update(mine_escape_required=True, mine_avoid_positions=[[1000., 0., 800.]])
    action = {'hold': ('lup',)}
    assert S.guard(b, snap, action, 100.)['hold'] == ()
    assert 'bomb escape' in b.stats['floor_safety_last']['reason']
    assert S.guard(b, snap, action, 100.1) == action
