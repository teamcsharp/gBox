"""Free walking rejects near-vertical NAV transitions, not normal stairs.

Repository fixtures are authored geometry. Optional exact replay reads only
the user's existing Spark-local archive; no extracted game vertices are bundled.
"""
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re6_switch as R, re6_movement_safety as S
from gbox.mercs.titles import re6_walk_floor as W
from gbox.mercs.titles.re6_switch_wall import stick_heading
from tests.test_re6_switch_wall import setup


def strip(rows):
    vertices = [(x, y, z) for z, y in rows for x in (-500., 500.)]
    tris = []
    for i in range(0, len(vertices)-2, 2):
        tris.extend(((i, i+1, i+3), (i, i+3, i+2)))
    links, edges = [[] for _ in tris], {}
    for k, tri in enumerate(tris):
        for i in range(3):
            edge = tuple(sorted((tri[i], tri[(i+1) % 3])))
            if edge in edges:
                other = edges[edge]
                links[k].append(other); links[other].append(k)
            else:
                edges[edge] = k
    return R.NavMesh(vertices, tris, links, 'authored_grade_fixture')


def steep():
    return strip([(-500., 0.), (120., 0.), (200., 320.), (500., 320.)])


def scene(mesh=None):
    snap = {'mercenaries_phase': R.PHASE_PLAYING, 'navmesh': mesh or steep(),
            'camera': {'yaw': 0.}, 'player': {'ptr': 1, 'hp': 900, 'pos': (0., 0., 0.),
                'rot': 0., 'action': 'cPlAction_pl_act_walk'}}
    bot = SimpleNamespace(stats={}, in_hold=False, down=False, nav_path=None)
    return bot, snap


def endpoint(snap, keys):
    p, yaw = snap['player']['pos'], snap['camera']['yaw']
    way = stick_heading(keys, yaw)
    return p[0]+150*math.sin(way), p[1], p[2]+150*math.cos(way)


def test_native_endpoint_tolerance_does_not_prove_nearvertical_floor_walkable():
    bot, snap = scene()
    pos, end = snap['player']['pos'], endpoint(snap, ('lup',))
    assert snap['navmesh'].clear(pos, end) is True
    assert not W.walk_segment(snap['navmesh'], pos, end)
    out = S.guard(bot, snap, {'hold': ('lup', 'zl', 'zr')}, 10.)
    assert {'zl', 'zr'} <= set(out['hold']) and {'lleft', 'lright'} & set(out['hold'])
    assert W.walk_segment(snap['navmesh'], pos, endpoint(snap, out['hold']))


@pytest.mark.parametrize('grade', [.25, .7, 1., 1.5, 3.])
def test_continuous_stairs_preserve_uphill_and_downhill_walking(grade):
    mesh = strip([(-500., -500*grade), (500., 500*grade)])
    for direction in (-1, 1):
        assert W.walk_segment(mesh, (0., 0., 0.), (0., 0., direction*60.))


def test_thin_steep_ridge_between_level_endpoints_is_rejected():
    mesh = strip([(-500., 0.), (120., 0.), (121., 100.), (122., 0.), (500., 0.)])
    start, end = (0., 0., 0.), (0., 0., 150.)
    assert mesh.clear(start, end) is True
    assert not W.walk_segment(mesh, start, end)


def test_off_floor_or_unlinked_overlap_cannot_supply_walking_proof():
    mesh = strip([(-500., 0.), (120., 0.), (500., 0.)])
    assert not W.walk_segment(mesh, (0., 31., 0.), (0., 31., 150.))
    # Even overlapping projected surfaces do not permit an unlinked transition.
    for row in mesh.edge_nb:
        row.clear()
    assert not W.walk_segment(mesh, (0., 0., 0.), (0., 0., 150.))


def test_vertical_degenerate_and_nonfinite_geometry_refuses_proof():
    mesh = steep()
    assert not W.walk_segment(mesh, (0., math.nan, 0.), (0., 0., 150.))
    mesh.V[0] = (0., 0., 0.)
    mesh.V[1] = (0., 100., 0.)
    mesh.V[3] = (0., 200., 0.)
    assert not W.triangle_walkable_all_directions(mesh, 0)


def test_stale_yaw_whole_disk_certificate_checks_grade_on_connected_triangles():
    bot, snap = scene()
    # Every nearby XZ edge is linked, but a near-vertical patch enters the disk.
    assert not S._all_headings_on_floor(snap['navmesh'], snap['player']['pos'])
    bot.lock_write_at = 10.
    assert S.guard(bot, snap, {'hold': ('lright', 'zl', 'zr')}, 10.)['hold'] == ('zl', 'zr')
    flat = strip([(-500., 0.), (500., 0.)])
    assert S._all_headings_on_floor(flat, (0., 0., 0.))


@pytest.mark.parametrize('native', ['cSmVLadderEventCh_Climb', 'cPlAction_pl_act_land'])
def test_verified_native_traversal_and_landing_keep_existing_exemption(native):
    bot, snap = scene()
    snap['player']['action'] = native
    action = {'hold': ('lup',)}
    assert S.guard(bot, snap, action, 10.) is action


def test_mandatory_qte_and_external_bomb_clearance_remain_independent():
    bot, snap = scene()
    bot.stats['act'] = 'break_free'
    action = {'hold': ('lup', 'a')}
    assert S.guard(bot, snap, action, 10.) is action
    bot.stats = {'mine_escape_required': True, 'mine_avoid_positions': [[-150., 0., 0.]]}
    out = S.guard(bot, snap, {'hold': ('lup',)}, 10.)
    if set(out['hold']) & S.LEFT:
        end = endpoint(snap, out['hold'])
        assert W.walk_segment(snap['navmesh'], snap['player']['pos'], end)
        assert S._bomb_clear(bot, snap, snap['player']['pos'], end)


@pytest.mark.parametrize('late', ['_never_stand', '_govern'])
def test_complete_tick_late_rewrite_cannot_restore_nearvertical_walking(monkeypatch, late):
    bot, clock, snap = setup(monkeypatch, hold=())
    snap.update(scene()[1])
    monkeypatch.setattr(bot, late, (lambda action, s, now: {'hold': ('lup',)}) if late == '_never_stand'
                        else (lambda s, action, now: {'hold': ('lup',)}))
    out = bot.tick(snap)
    assert out['hold'] != ('lup',)
    assert W.walk_segment(snap['navmesh'], snap['player']['pos'], endpoint(snap, out['hold']))
    assert bot._movement_guard['previous'][3] == out['hold']


def test_exact_spark_cached_ccb6_floor_profile_without_claiming_active_stage_binding():
    root = Path(os.environ.get('GBOX_RE6_GRADE_EVIDENCE',
        '/home/ehm_eckx/gBox/system/gbox-data/analysis/merc-tuning-20261113'))
    path = root/'re6-ccb6-native-geometry-1794584433.json'
    if not path.is_file():
        pytest.skip('requires the existing user-owned Spark-local navigation archive')
    archive = json.loads(path.read_text())
    raw = archive['mesh']
    mesh = R.NavMesh(raw['V'], raw['T'], raw['N'], raw['name'])
    bot, snap = scene(mesh)
    snap.update(player=dict(archive['player'], hp=900), camera=archive['camera'])
    start = snap['player']['pos']
    assert mesh.clear(start, endpoint(snap, ('lup',))) is True
    assert not W.walk_segment(mesh, start, endpoint(snap, ('lup',)))
    for keys in (('lright',), ('lup', 'lright')):
        assert mesh.clear(start, endpoint(snap, keys)) is True
        assert W.walk_segment(mesh, start, endpoint(snap, keys))
    out = S.guard(bot, snap, {'hold': ('lup',)}, 10.)
    assert out['hold'] != ('lup',)
    assert W.walk_segment(mesh, start, endpoint(snap, out['hold']))
    # This proves a floor-filter correction only. The real bomb forbids these
    # three floor candidates under the unchanged all-bomb clearance rule.
    snap['throwables'] = archive['throwables']
    bot.stats['mine_escape_required'] = True
    for keys in (('lup',), ('lright',), ('lup', 'lright')):
        assert not S._bomb_clear(bot, snap, start, endpoint(snap, keys))
    assert S.guard(bot, snap, {'hold': ('lup',)}, 10.1)['hold'] == ()
