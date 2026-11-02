"""#5053 (faced_melee cluster, RE5): the swing that hits is the one the bot can see winding up.

Every incident's frame shows the bot mid-aim: doing=aim with the left stick down (turning), the laser dead and no
trigger - the slow aim turn (turn, then the laser settle, the trigger only once the aim is on them) cannot finish
before a close swing lands. In the recorded frame a nearby live Majini is in a wind-up motion (WINDUP_MOTIONS) or
flagged attacking (E_ATTACKING).

The fix: in Bot._tick, before the melee decision, a wind-up within WINDUP_FIRE_R on his level takes over with the
quick turn - the gun down for it - instead of the slow aim turn. Replay of the recorded frames (the incident replay
fixtures in tests/fixtures/mercs_incidents/) proves the decision: frames with a visible wind-up produce the quick
turn, not aim-with-no-trigger.
"""
import copy
import json
from pathlib import Path

import pytest

from gbox.mercs import incident_replay
from gbox.mercs.titles.re5_switch import WINDUP_FIRE_R, WINDUP_MOTIONS, E_ATTACKING, Bot

SCHEMA = 'gbox.mercs.incident-replay/1'
TITLE = '010018100CD46000'                 # RE5

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'mercs_incidents'


def at(x, z, motion=None, act=None):
    e = {'slot': 1, 'hp': 100, 'hp_max': 100, 'pos': (x, 0.0, z), 'class': 'uEm10'}
    if motion is not None:
        e['motion'] = motion
    if act is not None:
        e['act'] = act
    return e


def snap(foes, motion=26, laser=False, held=True, rot=0.0):
    inv = []
    if held:
        inv.append({'hand': True, 'id': 4, 'item': 4, 'type': 1, 'grid': 0})
    return {'player': {'pos': (0.0, 0.0, 0.0), 'rot': rot, 'hp': 250, 'hp_max': 250, 'motion': motion,
                       'aim_pitch': 0.0},
            'enemies': foes, 'inventory': inv,
            'laser': ({} if not laser else {'up': False, 'from': (0.0, 0.0, 0.0), 'at': (0.0, 0.0, 0.0)}),
            'kills': 0, 'timer': 60.0, 'score': 0, 'combo': 0, 'mercenaries_phase': 'fight'}


def tick1(snap_):
    b = Bot(stats={}, clock=lambda: 0.0)
    return b, b.tick(copy.deepcopy(snap_))


def test_windup_in_front_the_quick_turn_takes_over_not_the_slow_aim_turn():
    """A Majini at 2 m dead ahead in a wind-up motion - the bot must quick-turn (gun down for it) instead of
    aiming with no trigger and taking the swing."""
    foe = at(200.0, 0.0, motion=80)                # a wind-up motion (WINDUP_MOTIONS), 2.0 m dead ahead
    b, act = tick1(snap([foe], motion=26, laser=False))
    assert act == {'hold': ('ldown',)}
    assert b.doing == 'quick_turn'
    assert 'swing' in b.why
    assert b.stats['quick_turns'] == 1


def test_windup_flag_behind_the_quick_turn_too():
    """A close Majini flagged attacking (E_ATTACKING, act & 0x80) at his shoulder - the quick turn instead of the
    slow aim turn that misses him by more than the swing's window."""
    foe = at(240.0, 0.0, motion=91, act=E_ATTACKING)  # 2.4 m, flagged
    b, act = tick1(snap([foe], motion=26))
    assert act == {'hold': ('ldown',)}
    assert b.doing == 'quick_turn'


def test_no_windup_the_slow_aim_turn_still_aims():
    """Aim at an un-attacking close foe keeps the existing behavior: the gun up, the stick turning -
    not a quick turn (the wind-up is what changes the decision)."""
    foe = at(200.0, 0.0)                            # no motion, no flag
    b, act = tick1(snap([foe], motion=26))
    assert b.doing != 'quick_turn'
    # the normal aim turn: the gun up, the stick turning
    assert 'zl' in act['hold']


def test_windup_beyond_range_no_quick_turn():
    """No quick turn for a wind-up beyond WINDUP_FIRE_R: far swings are not in this cluster, aim stays the aim.

    Foe 3.5 m dead ahead (WINDUP_FIRE_R = 2.5 m). The bot is facing the foe (rot = heading(+x) = pi/2 in
    the game's radian convention), so err is small and the normal aim path fires (zl), not the quick turn."""
    import math
    rot = math.pi / 2  # facing +x (the foe's direction)
    b, act = tick1(snap([at(350.0, 0.0, motion=80)], motion=26, rot=rot))
    assert b.doing != 'quick_turn'
    assert 'zl' in act['hold']


def test_recorded_frames_the_visible_windups_produce_the_quick_turn():
    """The replay of the recorded cluster frames: frames where a live Majini within WINDUP_FIRE_R is in a wind-up
    motion or flagged attacking must produce the quick turn on the first tick, not aim-with-no-trigger.

    The snapshot captured the bot at hp 0/1 AFTER the swing - replay the decision from hp_before (the bot alive,
    the swing incoming). Frames without a visible wind-up (the motion bytes not in WINDUP_MOTIONS) are the cluster
    trend, not the wind-up trigger - they keep the existing aim decision."""
    import math
    path = FIXTURES / 're5_faced_melee.json'
    d = json.loads(path.read_text())
    assert d['fixtures'], 'the replay fixture is missing from tests/fixtures/mercs_incidents/'
    n_windup = 0
    n_total = 0
    for fx in d['fixtures']:
        assert fx['schema'] == SCHEMA
        assert fx['title'] == TITLE
        assert fx['snapshot'].get('enemies'), 'a recorded frame with no enemies'
        fx = dict(fx)
        fx['snapshot'] = dict(fx['snapshot'])
        fx['snapshot']['player'] = dict(fx['snapshot']['player'])
        fx['snapshot']['player']['hp'] = fx.get('hp_before', 1000)
        result = incident_replay.replay(fx, ticks=3)
        first = result['ticks'][0]
        # Check if this frame has a visible wind-up
        p = fx['snapshot']['player']
        px, py, pz = p['pos']
        has_windup = False
        for e in fx['snapshot']['enemies']:
            if (e.get('hp') or 0) <= 0:
                continue
            ex, ey, ez = e['pos']
            d2 = math.hypot(ex - px, ez - pz)
            dy = abs(ey - py)
            if d2 <= WINDUP_FIRE_R and dy <= 120.0:
                if (e.get('motion') in WINDUP_MOTIONS) or ((e.get('act') or 0) & E_ATTACKING):
                    has_windup = True
                    break
        if has_windup:
            assert first['act'] == {'hold': ('ldown',)}, \
                f"{fx['event_id']}: wind-up visible but first tick must be the quick turn, " \
                f"got {first['act']} ({first['doing']})"
            assert first['doing'] == 'quick_turn', \
                f"{fx['event_id']}: wind-up visible but first tick must be quick_turn, got {first['doing']}"
            n_windup += 1
        n_total += 1
    assert n_total >= 3, f'only {n_total} replayable frames in the fixture'
    assert n_windup >= 2, f'only {n_windup} frames with a visible wind-up (2+ expected in the cluster data)'
    # The remaining frames (no visible wind-up) keep the existing aim - the cluster trend, not the trigger
