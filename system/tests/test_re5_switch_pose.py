"""Native posed geometry replaces the standing capsule, without inventing hits."""
import math
import struct
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_switch as R, re5_switch_aim as A, re5_switch_pose as P
from tests.test_re5_switch_aim import Guest, final_read_scene
from tests.test_re5_target_feedback import controller, scene


ENEMY, JOINTS, CONV, MODEL, ACTION = (0x5D70000000+i*0x10000 for i in range(5))


def plant(g, e=ENEMY, pos=(0., 0., 300.), lying=True):
    g.q(e, 0x3CA8000000); g.q(e+P.GENERATION, 42)
    g.q(e+P.MODEL, MODEL); g.q(e+P.JOINTS, JOINTS); g.q(e+P.CONVERSION, CONV)
    g.put(e+P.COUNT, struct.pack('<I', 58)); g.q(e+P.ACTION, ACTION); g.q(ACTION, 0x3CA9000000)
    mapping = bytearray([255]*22)
    # Measured uEm10 indices from live replacement skeleton, not file bind-pose order.
    for ident, index in zip(P.IDS, (13, 47, 15, 32, 2, 6, 3, 7)):
        mapping[ident] = index
    g.put(CONV, mapping)
    coords = ({2: (0., 18., 15.), 4: (0., 18., 55.), 6: (-18., 20., 40.),
               11: (18., 20., 40.), 16: (-9., 17., -15.), 20: (9., 17., -15.),
               17: (-9., 6., -60.), 21: (9., 6., -60.)}
              if lying else {2: (0., 132., 0.), 4: (0., 165., 0.), 6: (-18., 150., 0.),
                             11: (18., 150., 0.), 16: (-9., 100., 0.), 20: (9., 100., 0.),
                             17: (-9., 57., 0.), 21: (9., 57., 0.)})
    for ident, relative in coords.items():
        address = JOINTS+mapping[ident]*P.STRIDE
        g.put(address+P.WORLD, struct.pack('<3f', *(pos[i]+relative[i] for i in range(3))))
        g.q(address+P.OWNER, e)
    return {'ptr': e, 'generation': 42, 'pos': pos, 'hp': 800, 'class': 'uEm10'}


def test_native_conversion_and_world_geometry_follow_lying_body(monkeypatch):
    g = Guest(); e = plant(g)
    monkeypatch.setattr(R, 'enemy_class', lambda *args: 'cEm10ActRiseFaceDown')
    pose = P.read(g, e)
    assert pose['aim'] == (0., 18., 315.)
    assert pose['head'] == (0., 18., 355.)
    assert pose['hips'] == (0., 17., 285.)
    assert pose['action'] == 'cEm10ActRiseFaceDown'
    assert not g.writes


def test_captured_live_downed_majini_has_no_standing_phantom_body(monkeypatch):
    row = json.loads((Path(__file__).parent/'fixtures/mercs_incidents/re5_downed_pose_20261113.json').read_text())
    g = Guest(); enemy = plant(g, pos=tuple(row['pos']))
    monkeypatch.setattr(R, 'enemy_class', lambda *args: row['action'])
    for key, point in row['joints'].items():
        index = g.rd(CONV+int(key), 1)[0]
        g.put(JOINTS+index*P.STRIDE+P.WORLD, struct.pack('<3f', *point))
    pose = P.read(g, enemy)
    assert pose['aim'][1]-enemy['pos'][1] == pytest.approx(18.404052734375)
    standing = (enemy['pos'][0], enemy['pos'][1]+R.CHEST_H, enemy['pos'][2])
    assert R.dot_on(standing, enemy['pos']) == 'body'
    assert P.dot_on(standing, pose) is None
    assert P.dot_on(pose['aim'], pose) == 'body'


@pytest.mark.parametrize('bad', ['joint_owner', 'generation', 'mapping', 'count', 'nan', 'far', 'collapsed', 'creature'])
def test_unknown_foreign_or_corrupt_pose_is_unavailable(bad):
    g = Guest(); e = plant(g)
    a = JOINTS+13*P.STRIDE
    if bad == 'joint_owner': g.q(a+P.OWNER, ENEMY+8)
    if bad == 'generation': e['generation'] = 43
    if bad == 'mapping': g.put(CONV+2, b'\xff')
    if bad == 'count': g.put(ENEMY+P.COUNT, struct.pack('<I', 256))
    if bad == 'nan': g.put(a+P.WORLD, struct.pack('<f', float('nan')))
    if bad == 'far': g.put(a+P.WORLD, struct.pack('<f', 50000.))
    if bad == 'collapsed':
        for i in P.IDS:
            idx=g.rd(CONV+i, 1)[0]
            g.put(JOINTS+idx*P.STRIDE+P.WORLD, struct.pack('<3f', 0., 0., 300.))
    if bad == 'creature': e['class'] = 'uEm62'
    assert P.read(g, e) is None and not g.writes


@pytest.mark.parametrize('bad', ['life', 'model', 'joints', 'conversion', 'mapping', 'action', 'action_class'])
def test_read_rechecks_model_pose_and_action_ownership(bad):
    g = Guest(); e = plant(g); rd = g.rd
    def changing(address, size):
        result = rd(address, size)
        if address == JOINTS+6*P.STRIDE:
            if bad == 'life': g.q(ENEMY+P.GENERATION, 43)
            if bad == 'model': g.q(ENEMY+P.MODEL, MODEL+0x100)
            if bad == 'joints': g.q(ENEMY+P.JOINTS, JOINTS+0x100)
            if bad == 'conversion': g.q(ENEMY+P.CONVERSION, CONV+0x100)
            if bad == 'mapping': g.put(CONV+2, b'\x0e')
            if bad == 'action': g.q(ENEMY+P.ACTION, ACTION+0x100)
            if bad == 'action_class': g.q(ACTION, 0x3CA9000100)
        return result
    g.rd = changing
    assert P.read(g, e) is None


def test_late_refresh_replaces_old_pose_and_retains_its_sample_budget(monkeypatch):
    g, old, where = final_read_scene(monkeypatch)
    plant(g, where['enemy'], (40., 10., 330.))
    old['enemies'][0]['aim_pose'] = {'aim': (0., 110., 300.)}
    fresh, target, why = A.refresh_target(g, old, old['enemies'][0])
    assert why is None and target['aim_pose']['aim'] == (40., 28., 345.)
    g.q(where['enemy']+P.JOINTS, 0)
    fresh, target, why = A.refresh_target(g, old, old['enemies'][0])
    assert why is None and target['aim_pose'] is None  # stale standing or lying geometry cannot survive


def pose_scene(distance=490., lying=True):
    g = Guest(); e = plant(g, pos=(0., 0., distance), lying=lying)
    pose = P.read(g, e)
    s = scene(distance=distance)
    e.update(ptr=2, aim_pose=dict(pose, owner=2))
    s['enemies'] = [e]
    s['inventory'][0]['item'] = 0x0B  # M29: no shotgun spread escape hatch
    return s


def point_ray(s, point):
    origin = s['laser']['from']
    delta = tuple(point[i]-origin[i] for i in range(3))
    s['aim_cam']['heading'] = math.atan2(delta[0], delta[2])
    s['aim_cam']['pitch'] = math.atan2(delta[1], math.hypot(delta[0], delta[2]))
    s['laser']['at'] = tuple(origin[i]+5*delta[i] for i in range(3))


def test_grounded_torso_ray_fires_and_continues_while_correcting():
    bot, writes = controller(); s = pose_scene()
    point_ray(s, s['enemies'][0]['aim_pose']['aim'])
    for now in (.3, .45, .6, .75):
        act = A.apply(bot, s, {'hold': ('zl', 'zr')}, now)
        assert set(act['hold']) == {'zl', 'zr'} and bot.doing == 'fire'
        assert bot.stats['target_feedback_pose']['height_cm'] == 18.
        assert bot._aimctx['body_contact'] and bot._aimctx['ray_observed']
    assert len(writes) == 4


def test_ray_through_old_standing_capsule_is_rejected_and_pitched_down():
    bot, writes = controller(); s = pose_scene()
    point_ray(s, (0., 110., 490.))
    old_pitch = s['aim_cam']['pitch']
    # First acquisition owns no elapsed budget; the next same-context sample does.
    A.apply(bot, s, {'hold': ('zl', 'zr')}, .3)
    act = A.apply(bot, s, {'hold': ('zl', 'zr')}, .45)
    assert 'zr' not in act['hold'] and writes[-1][0] < old_pitch
    assert bot.stats['target_feedback_pitch_deg'] < -9.
    assert not bot.stats['target_feedback_on']


def test_correcting_camera_does_not_count_as_current_pose_contact():
    bot, writes = controller(); s = pose_scene()
    point_ray(s, (0., 110., 490.))
    for now in (.3, .45, .6, .75):
        assert 'zr' not in A.apply(bot, s, {'hold': ('zl', 'zr')}, now)['hold']
    assert len(writes) == 4 and bot._feedback_contact is None


def test_wall_before_lying_body_still_blocks_a_perfectly_aimed_gun():
    bot, _ = controller(); s = pose_scene()
    point_ray(s, s['enemies'][0]['aim_pose']['aim'])
    origin, dot = s['laser']['from'], s['laser']['at']
    s['laser']['at'] = tuple(origin[i]+.05*(dot[i]-origin[i]) for i in range(3))
    assert 'zr' not in A.apply(bot, s, {'hold': ('zl', 'zr')}, .3)['hold']


def test_shotgun_does_not_use_standing_point_blank_window_over_grounded_body():
    bot, _ = controller(); s = pose_scene(distance=250.)
    s['inventory'][0]['item'] = 0x04
    point_ray(s, (0., 110., 250.))
    assert 'zr' not in A.apply(bot, s, {'hold': ('zl', 'zr')}, .3)['hold']


def test_standing_pose_and_same_pose_after_getting_up_are_accepted():
    bot, _ = controller()
    for now, lying in ((.3, True), (.45, False)):
        s = pose_scene(lying=lying); point_ray(s, s['enemies'][0]['aim_pose']['aim'])
        assert 'zr' in A.apply(bot, s, {'hold': ('zl', 'zr')}, now)['hold']
    assert bot.stats['target_feedback_pose']['height_cm'] == 132.


@pytest.mark.parametrize('height,joint', [(R.CHEST_H, 'aim'), (R.HEAD_H, 'head'), (R.KNEE_H, 'knees')])
def test_requested_head_and_stagger_sites_follow_current_pose(height, joint):
    bot, _ = controller(); s = pose_scene()
    bot._aim_h = lambda *args: height
    pose = s['enemies'][0]['aim_pose']
    point_ray(s, pose[joint])
    assert 'zr' in A.apply(bot, s, {'hold': ('zl', 'zr')}, .3)['hold']
    assert bot.stats['target_feedback_pose']['point'] == list(pose[joint])
    assert bot._aimctx['posed_point'] == pose[joint]


def test_pose_keeps_learned_lead_without_restoring_standing_height(monkeypatch):
    bot = R.Bot(stats={})
    correction = SimpleNamespace(lead_s=.1, yaw=0., pitch=0.)
    # Deliberately different standing body-plan point. Its physical lead remains valid.
    plan = SimpleNamespace(point=(0., 160., 500.), chest=(0., 110., 500.),
                           point0=(0., 160., 500.), corr=correction, vel=(100., 0., 0.))
    bot._aim_core = lambda: SimpleNamespace(plan=lambda *a, **k: plan)
    monkeypatch.setattr(R, 'AIM_BOOK', True)
    e = {'ptr': 2, 'class': 'uEm10', 'pos': (0., 0., 500.)}
    point = bot._aim_book_point(e, (0., 18., 515.), 18., (0., 140., 0.), .3, posed=True)
    assert point == pytest.approx((10., 18., 515.))
    assert bot._ab_physical == (2, (10., 18., 515.))


@pytest.mark.parametrize('a,b,c,d,want', [
    ((0,0,0),(0,0,10),(-5,0,5),(5,0,5),0),
    ((0,0,0),(0,0,10),(0,3,0),(0,3,10),3),
    ((0,0,0),(0,0,0),(0,3,0),(0,3,0),3),
    ((0,0,0),(0,0,5),(0,0,10),(0,0,20),5),
])
def test_finite_segment_geometry(a, b, c, d, want):
    assert P.segment_distance(a,b,c,d) == pytest.approx(want)
    assert P.segment_distance(c,d,a,b) == pytest.approx(want)
