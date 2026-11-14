"""A valid narrow departure must not be lost between the eight pad headings.

Synthetic geometry is repository-safe. Optional exact NAV/round replays read
the user's Spark-local analysis only; no extracted game payload is bundled.
"""
import json
import math
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_native_mine_escape as E, re5_movement_safety as S
from gbox.mercs.titles import re5_switch as R, re5_switch_mines as M
from gbox.mercs.titles.re5_nav import NavMesh
from test_re5_native_mine_escape import scene


def corridor():
    # A synthetic 8cm-wide lane between the current 45-degree pad axes.
    heading = math.radians(285.)
    def point(along, side):
        return (along*math.sin(heading)+side*math.cos(heading), 0.,
                along*math.cos(heading)-side*math.sin(heading))
    vertices = [point(along, side) for along in range(-100, 2001, 100) for side in (-4., 4.)]
    tris = []
    for i in range(0, len(vertices)-2, 2):
        tris += [(i, i+1, i+3), (i, i+3, i+2)]
    edges, links = {}, [[] for _ in tris]
    for u, tri in enumerate(tris):
        for edge in range(3):
            pair = frozenset((tri[edge], tri[(edge+1) % 3]))
            if pair in edges:
                v, other = edges[pair]
                links[u].append((v, edge, 1.)); links[v].append((u, other, 1.))
            else:
                edges[pair] = u, edge
    bot, snap = scene(pos=(0., 0., 0.), mines={1: point(-500., 0.)})
    snap['nav'] = NavMesh(vertices, tris, links)
    snap['player']['rot'] = math.radians(163.8)
    bot.stats['round_evidence_id'] = 'alignment'
    return bot, snap


def test_narrow_verified_lane_turns_only_until_fresh_heading_supports_motion():
    bot, snap = corridor()
    a = E.assess(bot, snap, 1.)
    assert a['safe'] is None and a['alignment'] is not None
    out = E.guard(bot, {'hold': ('zl', 'zr', 'lup')}, snap, 1.)
    assert out['hold'] == ('rleft',)
    assert S._travel_heading(snap['player'], out['hold']) is None
    assert not E.blocked(bot, snap, 1.)
    assert E._clear(bot, snap, snap['player']['pos'], a['alignment'][1])
    snap['player']['rot'] = a['alignment'][0]
    out = E.guard(bot, {'hold': ('zl', 'zr')}, snap, 1.1)
    heading = S._travel_heading(snap['player'], out['hold'])
    assert heading is not None
    assert E._clear(bot, snap, snap['player']['pos'], S._end(snap['nav'], snap['player']['pos'], heading))
    assert bot._native_align_turn is None


def test_scan_finds_local_supported_step_without_claiming_complete_route(monkeypatch):
    bot, snap = corridor()
    monkeypatch.setattr(E, 'route', lambda *a: None)
    out = E.guard(bot, {'hold': ('zl',)}, snap, 1.)
    assert out['hold'] == ('rleft',)
    report = bot.stats['native_mine_escape_final']
    assert report['route'] == [] and report['safe_end'] is None
    assert report['alignment_end'] and 'before moving' in report['state']


def test_rotation_without_native_heading_progress_times_out_and_keeps_defense():
    bot, snap = corridor()
    for i in range(20):
        out = E.guard(bot, {'hold': ('zl', 'zr')}, snap, 1.+i*.1)
    assert out['hold'] == ('zl', 'zr') and E.blocked(bot, snap, 3.)
    assert bot.stats['native_mine_alignment_failure']['elapsed_s'] <= E.ALIGN_PROGRESS_S+.1
    assert E.guard(bot, {'hold': ('zl',)}, snap, 20.)['hold'] == ('zl',)


def test_alignment_cache_refresh_cannot_extend_total_turn_budget():
    bot, snap = corridor()
    initial = snap['player']['rot']
    for i in range(46):
        # Enough measured progress to renew the short progress budget, but
        # insufficient to reach any of the lane's safe discrete stick axes.
        snap['player']['rot'] = initial + math.radians(i*.4)
        out = E.guard(bot, {'hold': ('zl',)}, snap, 1.+i*.1)
    assert out['hold'] == ('zl',)
    failure = bot.stats['native_mine_alignment_failure']
    assert failure['elapsed_s'] == pytest.approx(E.ALIGN_MAX_S, abs=.1)
    assert bot._native_align_turn['started'] == 1.


@pytest.mark.parametrize('change', ['menu', 'no_mines', 'missing_player'])
def test_inactive_play_clears_alignment_state(change):
    bot, snap = corridor()
    E.guard(bot, {'hold': ()}, snap, 1.)
    assert bot._native_align_turn is not None
    if change == 'menu': snap['mercenaries_phase'] = 0
    elif change == 'missing_player': snap['player'] = {}
    else:
        bot.mines.bombs.clear(); bot.mines._native_escape = None
    E.guard(bot, {'hold': ()}, snap, 1.1)
    assert bot._native_align_turn is None and bot._native_alignment is None


@pytest.mark.parametrize('change', ['life', 'round', 'operator', 'hazard'])
def test_alignment_failure_does_not_cross_owner_or_hazard_changes(change):
    bot, snap = corridor()
    for i in range(20):
        E.guard(bot, {'hold': ('zl',)}, snap, 1.+i*.1)
    if change == 'life': snap['player']['generation'] += 1
    elif change == 'round': bot.stats['round_evidence_id'] = 'another'
    elif change == 'operator':
        bot.stats['operator_control'] = True
        E.guard(bot, {'hold': ()}, snap, 3.)
        bot.stats['operator_control'] = False
    else:
        bot.mines.bombs[2] = bot.mines.bombs.pop(1)
        bot.mines._native_escape['sites'] = dict(bot.mines.bombs)
    assert E.guard(bot, {'hold': ('zl',)}, snap, 3.1)['hold'] == ('rleft',)


def test_cached_alignment_does_not_waive_new_floor_room_or_mine_exclusion():
    for cause in ('floor', 'room', 'mine'):
        bot, snap = corridor()
        assert E.guard(bot, {'hold': ('zl',)}, snap, 1.)['hold'] == ('rleft',)
        if cause == 'floor': snap['nav'].floor_segment = lambda *a: False
        elif cause == 'room': bot._sm = SimpleNamespace(walk_block=lambda *a, **kw: 'wall')
        else:
            bot.mines.bombs[2] = (200.*math.sin(math.radians(285)), 0., 200.*math.cos(math.radians(285)))
        out = E.guard(bot, {'hold': ('zl', 'zr')}, snap, 1.1)
        assert out['hold'] == ('zl', 'zr')


def test_same_tick_native_aim_write_and_grab_preserve_existing_priority():
    bot, snap = corridor()
    bot.stats['target_feedback_ram'] = True
    assert E.guard(bot, {'hold': ('zl',)}, snap, 1.)['hold'] == ()
    snap['player']['motion'] = next(iter(R.MOTION_HELD))
    action = {'hold': ('lup',)}
    assert E.guard(bot, action, snap, 1.1) is action


def full_tick(monkeypatch, source, snap):
    from test_re5_target_feedback import scene as aim_scene
    monkeypatch.setattr(R, 'PS3_BRAIN', False)
    monkeypatch.setattr(R, 'HEAL_ENABLED', False)
    clock = [1.]
    bot = R.Bot(stats={}, clock=lambda: clock[0])
    bot._round_started = 0.; bot._new_round(0.); bot._start_facing_done = True
    bot.mines = source.mines; bot.mines.stats = bot.stats
    bot.mines.observe_native = lambda *a: None
    combat = aim_scene()
    for name in ('inventory', 'aim_cam', 'laser', 'enemies'):
        snap[name] = combat[name]
    snap['inventory'][0].update(id=0x11b, slot=0, type=1, rounds=50, cap=50, grid=0)
    snap.update(timer=180., bonuses=[])
    monkeypatch.setattr(bot, '_room_map', lambda *a: None)
    writes = []
    monkeypatch.setattr(bot, '_writer', lambda: lambda *args: writes.append(args) or True)
    # A real final-guard use case: a later wall governor proposes unsafe travel.
    monkeypatch.setattr(bot, '_wall_gov', lambda *a: {'hold': ('lup', 'b')})
    first = bot.tick(snap)
    assert set(first['hold']) <= {'rleft', 'rright'} and first['hold']
    assert not writes and not bot.stats.get('target_feedback_ram')
    assert bot.stats['combat_hold'] == ','.join(first['hold'])
    assert S._travel_heading(snap['player'], first['hold']) is None
    target = E.assess(bot, snap, clock[0])['alignment'][0]
    # This is an observed pose update in the fixture, not a gameplay memory write.
    snap['player']['rot'] = target
    clock[0] += .1
    second = bot.tick(snap)
    heading = S._travel_heading(snap['player'], second['hold'])
    assert heading is not None and not writes
    assert E._clear(bot, snap, snap['player']['pos'], S._end(snap['nav'], snap['player']['pos'], heading))
    assert bot.stats['combat_hold'] == ','.join(second['hold'])


def test_complete_tick_preserves_rotation_then_verified_translation(monkeypatch):
    full_tick(monkeypatch, *corridor())


def native_scene(monkeypatch, source=None, snap=None, *, sticky=True):
    """Real owned aim writer on a bounded in-memory native-layout fixture."""
    from test_re5_switch_aim import guest, Session, BASE, PLAYER
    from test_re5_target_feedback import scene as aim_scene
    from gbox.mercs.titles import re5_switch_aim as A
    if source is None:
        source, snap = corridor()
    clock = [1.]
    monkeypatch.setattr(A.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(R, 'PS3_BRAIN', False)
    monkeypatch.setattr(R, 'HEAL_ENABLED', False)
    bot = R.Bot(stats={}, clock=lambda: clock[0])
    bot._round_started = 0.; bot._new_round(0.); bot._start_facing_done = True
    bot.mines = source.mines; bot.mines.stats = bot.stats
    bot.mines.observe_native = lambda *a: None
    for name in ('inventory', 'laser', 'enemies'):
        snap[name] = aim_scene()[name]
    snap['inventory'][0].update(id=0x11b, slot=0, type=1, rounds=50, cap=50, grid=0)
    snap.update(timer=180., bonuses=[], module_base=BASE)
    snap['player'].update(ptr=PLAYER, generation=1, motion=1)
    g = guest(heading=snap['player']['rot'], sticky=sticky)
    manager, main, gs = (0x5D41000000, 0x5D42000000, 0x5D43000000)
    g.put(BASE+R.SIG_OFF, R.SIGNATURE)
    g.q(BASE+R.S_PLAYER, manager); g.q(manager+R.P_FIRST, PLAYER)
    g.q(BASE+R.S_MAIN, main); g.q(main+R.MAIN_GAMESYS, gs)
    g.put(gs+R.GS_PHASE, struct.pack('<i', R.PHASE_PLAYING))
    g.q(PLAYER+0x1A00, 1)
    g.put(PLAYER+R.P_POS, struct.pack('<3f', *snap['player']['pos']))
    g.put(PLAYER+R.P_HP, struct.pack('<h', 1000))
    g.put(PLAYER+R.P_MOTION, b'\x01')
    # Include slope tilt: a yaw-only correction must preserve it.
    tilt, yaw = math.radians(20)/2, snap['player']['rot']/2
    g.put(PLAYER+A.P_ROT, struct.pack('<4f', math.cos(yaw)*math.sin(tilt),
        math.sin(yaw)*math.cos(tilt), -math.sin(yaw)*math.sin(tilt), math.cos(yaw)*math.cos(tilt)))
    bot._m = Session(g)
    monkeypatch.setattr(bot, '_room_map', lambda *a: None)
    monkeypatch.setattr(bot, '_wall_gov', lambda *a: {'hold': ('lup', 'b')})

    def refresh():
        snap['aim_cam'] = A.aim_state(bot._m, BASE, PLAYER)
        if snap['aim_cam']:
            snap['player']['rot'] = snap['aim_cam']['heading']
        snap['player']['motion'] = g.rd(PLAYER+R.P_MOTION, 1)[0]
    refresh()
    return bot, snap, g, clock, refresh


def verify_native_departure(monkeypatch, dt, source=None, snap=None):
    from test_re5_switch_aim import PLAYER, CTRL
    from gbox.mercs.titles import re5_switch_aim as A
    bot, snap, g, clock, refresh = native_scene(monkeypatch, source, snap)
    pitch = g.rd(CTRL+A.CTRL_QFPS+A.QF_PITCH, 4)
    state = {off: g.rd(PLAYER+off, size) for off, size in ((R.P_POS, 12), (R.P_HP, 2), (R.P_MOTION, 1))}
    previous_heading = snap['player']['rot']
    writes = 0
    for _ in range(10):
        refresh()  # actual writer readback becomes the following observed pose
        out = bot.tick(snap)
        moving = S._travel_heading(snap['player'], out['hold'])
        if len(g.writes) > writes:
            assert out['hold'] == ()  # including late wall-governor rewrite
            after = A.aim_state(bot._m, snap['module_base'], PLAYER)['heading']
            assert abs(A.wrap(after-previous_heading)) <= A.YAW_RATE*min(dt, A.MAX_DT)+1e-5
            previous_heading = after
            writes = len(g.writes)
        if moving is not None:
            assert writes and clock[0] < 1.+E.ALIGN_MAX_S
            assert not set(out['hold']) & {'rleft', 'rright', 'rup', 'rdown', 'zl', 'zr'}
            assert bot.stats['native_mine_alignment_native']['state'] == 'fresh_pose'
            assert bot.stats['native_mine_alignment_native']['observed'] is True
            assert E._clear(bot, snap, snap['player']['pos'], S._end(snap['nav'], snap['player']['pos'], moving))
            break
        assert out['hold'] == ()  # this verified native path never digital-overshoots
        clock[0] += dt
    else:
        pytest.fail('bounded native heading did not establish an observed safe stick axis')
    assert all(addr == PLAYER+A.P_ROT and len(data) == 16 for addr, data in g.writes)
    assert g.rd(CTRL+A.CTRL_QFPS+A.QF_PITCH, 4) == pitch
    assert all(g.rd(PLAYER+off, len(value)) == value for off, value in state.items())
    x, y, z, w = struct.unpack('<4f', g.rd(PLAYER+A.P_ROT, 16))
    assert x*x+y*y+z*z+w*w == pytest.approx(1., abs=1e-6)
    assert math.hypot(x, z) == pytest.approx(math.sin(math.radians(10)), abs=1e-6)
    assert bot.stats['combat_hold'] == ','.join(out['hold'])


@pytest.mark.parametrize('dt', [.1, .2, .3])
def test_owned_heading_survives_sampled_turn_intervals_and_final_governor(monkeypatch, dt):
    verify_native_departure(monkeypatch, dt)


@pytest.mark.parametrize('change', ['gun_up', 'phase', 'life', 'camera', 'base', 'operator', 'disabled'])
def test_native_alignment_refuses_changed_owner_or_gun_not_down(monkeypatch, change):
    from test_re5_switch_aim import BASE, PLAYER, CTRL
    from gbox.mercs.titles import re5_switch_aim as A
    bot, snap, g, clock, refresh = native_scene(monkeypatch)
    assert E.guard(bot, {'hold': ('zl',)}, snap, clock[0])['hold'] == ()
    clock[0] += .2
    if change == 'gun_up': g.put(PLAYER+R.P_MOTION, bytes([R.MOTION_AIMED]))
    elif change == 'phase': g.put(0x5D43000000+R.GS_PHASE, struct.pack('<i', 3))
    elif change == 'life': g.q(PLAYER+0x1A00, 2)
    elif change == 'camera': g.q(CTRL+A.CTRL_ACTIVE, 0)
    elif change == 'base': g.put(BASE+R.SIG_OFF, bytes(len(R.SIGNATURE)))
    elif change == 'operator': bot.stats['operator_control'] = True
    else: bot._m.mercs_no_modifications = True
    E.guard(bot, {'hold': ('zl',)}, snap, clock[0])
    assert not g.writes


def test_unobserved_heading_wait_is_bounded_without_renewing_total_budget(monkeypatch):
    bot, snap, g, clock, refresh = native_scene(monkeypatch)
    E.guard(bot, {'hold': ()}, snap, clock[0])
    clock[0] += .2
    assert E.guard(bot, {'hold': ()}, snap, clock[0])['hold'] == ()
    assert len(g.writes) == 1
    # Keep the old snapshot even after successful native readback. That cannot
    # authorize movement or keep restarting the four-second turn allowance.
    started = bot._native_align_turn['started']
    for _ in range(25):
        clock[0] += .2
        out = E.guard(bot, {'hold': ('zl',)}, snap, clock[0])
        assert S._travel_heading(snap['player'], out['hold']) is None
    assert out['hold'] == ('zl',) and len(g.writes) == 1
    assert bot._native_align_turn['started'] == started
    assert bot._native_align_turn['failed'] is True


def test_failed_readback_keeps_same_tick_neutral_then_observes_actual_pose(monkeypatch):
    bot, snap, g, clock, refresh = native_scene(monkeypatch, sticky=False)
    E.guard(bot, {'hold': ()}, snap, clock[0])
    clock[0] += .2
    assert E.guard(bot, {'hold': ()}, snap, clock[0])['hold'] == ()
    assert g.writes and bot.stats['native_mine_alignment_native']['readback'] is False
    assert E.guard(bot, {'hold': ('lup', 'b')}, snap, clock[0])['hold'] == ()
    clock[0] += .2; refresh()
    out = E.guard(bot, {'hold': ('lup',)}, snap, clock[0])
    assert S._travel_heading(snap['player'], out['hold']) is None


@pytest.mark.parametrize('change', ['stale_reads', 'round', 'life', 'phase', 'operator'])
def test_heading_refresh_revalidates_races_before_existing_writer(monkeypatch, change):
    from test_re5_switch_aim import PLAYER
    from gbox.mercs.titles import re5_switch_aim as A
    bot, snap, g, clock, refresh = native_scene(monkeypatch)
    E.guard(bot, {'hold': ()}, snap, clock[0])
    clock[0] += .2
    original = A.aim_state
    def raced(*args):
        result = original(*args)
        if change == 'stale_reads': clock[0] += A.MAX_SAMPLE_AGE+.01
        elif change == 'round': bot.stats['round_evidence_id'] = 'new-round'
        elif change == 'life': g.q(PLAYER+0x1A00, 99)
        elif change == 'phase': g.put(0x5D43000000+R.GS_PHASE, struct.pack('<i', 3))
        else: bot.stats['operator_control'] = True
        return result
    monkeypatch.setattr(A, 'aim_state', raced)
    out = E.guard(bot, {'hold': ('lup',)}, snap, clock[0])
    assert out['hold'] == () and not g.writes
    assert bot.stats['native_mine_alignment_native']['state'] == 'refused'


@pytest.mark.parametrize('dt', [.1, .2, .3])
@pytest.mark.parametrize('stage,archive,stamp', [
    ('s404', 'post-4b7b12cc-7bceb6173a6e480f81fa08ca20908eec-audit.json', 1794582787.901),
    ('s406', 'post-dd05a9ef-45d5f7f89e9646c793ab37ac935f96fc-audit.json', 1794583182.001),
])
def test_exact_spark_native_geometry_incidents_complete_tick(monkeypatch, stage, archive, stamp, dt):
    root = Path(os.environ.get('GBOX_RE5_ALIGNMENT_EVIDENCE',
        '/home/ehm_eckx/gBox/system/gbox-data/analysis/merc-tuning-20261113'))
    if not (root/archive).is_file():
        pytest.skip('requires the user-owned Spark-local native NAV and completed-round evidence')
    run = json.loads((root/archive).read_text())['run']
    rows = sum([v for v in (run['flight'].get(k) for k in ('tail', 'timeline', 'first')) if isinstance(v, list)], [])
    row = min(rows, key=lambda r: abs(r['t']-stamp)); diagnostics = row['diagnostics']
    geo = json.loads((root/f're5-{stage}-exact-nav.json').read_text())
    mesh = NavMesh(geo['points'], geo['tris'], geo['links']); mesh.name = geo['resource']
    from gbox.mercs.titles.re5_switch_nav import geometry_identity
    assert geometry_identity(mesh) == diagnostics['navigation_identity']
    pos = tuple(diagnostics['native_mine_escape_final']['pos'])
    source, snap = scene(pos=pos)
    snap['nav'] = mesh; snap['player']['rot'] = row['heading']
    source.mines.bombs.clear()
    source.mines._native_escape = None
    if stage == 's404':
        active = next(m for m in row['ground_mines'] if m.get('active'))
        source.mines.bombs[active['ptr']] = tuple(active['pos'])
        source.mines._start_native_escape('incident', active['pos'], 0.)
        source.mines._native_escape.update(pending=False, predicted=())
    else:
        from gbox.mercs.titles.re5_proximity_native import points
        center = (369.63140869140625, 299.92071533203125, -2266.42919921875)
        source.mines._start_native_escape('incident', center, 0., predicted=points(center, 5))
    assessment = E.assess(source, snap, 1.)
    assert assessment['safe'] is None
    assert assessment['vetoes'] == diagnostics['native_mine_escape_final']['candidate_vetoes']
    assert assessment['alignment'] is not None
    verify_native_departure(monkeypatch, dt, source, snap)
