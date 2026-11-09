"""#5053 (faced_melee cluster, RE5): the swing that hits is the one the bot can see winding up.

Every incident's frame shows the bot mid-aim: doing=aim with the left stick down (turning), the laser dead and no
trigger - the slow aim turn (turn, then the laser settle, the trigger only once the aim is on them) cannot finish
before a close swing lands. In the recorded frame a nearby live Majini is in a wind-up motion (WINDUP_MOTIONS) or
flagged attacking (E_ATTACKING).

The rule (operator 2026-11-09, every title: "enemies transitioning into attack animations need to be shot,
dispatched, meleed or interrupted"): a wind-up within WINDUP_FIRE_R on his level is the target at once. Behind him
(past QUICK_ERR) ONE quick turn brings the gun round; in front or at his side the fight fires on him with no detour.

The first version of the fix took over on every tick a wind-up showed and restarted the quick turn each time, so in
a No Mercy crowd (someone is always swinging) he only ever held the stick back with the gun down: live 2026-11-09,
2,218 quick-turn starts in 183 s, 46 % of the round, the trigger held 0.6 s. The storm test below is that round.
"""
import copy
import json
import math
from pathlib import Path

from gbox.mercs import incident_replay
from gbox.mercs.titles import re5_switch as R
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


def ticking(snap_, seconds, dt=1 / 30):
    """A bot ticked on the same frame for `seconds` at the engine's cadence -> (bot, [(act, doing)])."""
    clock = [1000.0]
    b = Bot(stats={}, clock=lambda: clock[0])
    out = []
    for _ in range(int(seconds / dt)):
        act = b.tick(copy.deepcopy(snap_))
        out.append((act, b.doing))
        clock[0] += dt
    return b, out


def test_windup_behind_him_one_quick_turn_brings_the_gun_round():
    """A Majini 2 m behind him in a wind-up motion: the quick turn (the gun down for it), once - the stick back, + B,
    let go - and it is never restarted while it plays."""
    foe = at(0.0, -200.0, motion=80)               # rot 0 faces +z: dead behind
    b, act = tick1(snap([foe], motion=26, laser=False))
    assert act == {'hold': ('ldown',)} and b.doing == 'quick_turn' and 'swing' in b.why and b.target == foe['slot']
    b, acts = ticking(snap([foe], motion=26, laser=False), 0.5)
    assert acts[0] == ({'hold': ('ldown',)}, 'quick_turn')
    assert acts[1][0] == {'hold': ('ldown', 'b')} and acts[2][0] == {'hold': ()}
    assert b.stats['quick_turns'] == 1 and b.stats['behind_turns'] == 1


def test_windup_at_his_side_or_in_front_is_fired_on_not_turned_away_from():
    """A quick turn is a half turn: for a swing winding up beside him or ahead of him it showed him his back. He is
    the target and the fight has him - the gun up or the turn onto him, no quick turn, never a bare stick back."""
    for foe in (at(200.0, 0.0, motion=80), at(240.0, 0.0, motion=91, act=E_ATTACKING), at(0.0, 200.0, motion=80)):
        b, act = tick1(snap([foe], motion=26))
        assert b.doing != 'quick_turn' and b.stats['quick_turns'] == 0, (foe['pos'], b.doing, b.why)
        assert b.target == foe['slot']
        assert {'zl', 'zr', 'rleft', 'rright'} & set(act['hold']), (foe['pos'], act)


def test_a_crowd_that_is_always_swinging_never_freezes_him_in_quick_turns():
    """lilspark 2026-11-09: 2,218 quick-turn starts in 183 s (12 a second). Five seconds with a wind-up behind him on
    every tick (the frame never changes here, so the swing never ends): quick turns QUICK_GAP_S apart at most, and
    the rest of the time he is on a Majini - the gun up or the stick turning onto one."""
    crowd = [at(0.0, -200.0, motion=80), dict(at(150.0, 150.0, motion=80), slot=2), dict(at(-180.0, 60.0), slot=3)]
    seconds = 5.0
    b, acts = ticking(snap(crowd, motion=26, laser=False), seconds)
    assert 1 <= b.stats['quick_turns'] <= seconds / R.QUICK_GAP_S + 1
    turning = sum(1 for _act, doing in acts if doing == 'quick_turn')
    assert turning < 0.35 * len(acts), f"{turning} of {len(acts)} ticks in the quick turn"
    idle = sum(1 for act, _doing in acts if set(act.get('hold', ())) <= {'ldown'})   # nothing held, or the stick back
    assert idle < 0.35 * len(acts), f"{idle} of {len(acts)} ticks with nothing but the stick back"
    armed = sum(1 for act, _doing in acts if {'zl', 'zr'} & set(act.get('hold', ())))
    assert armed > 0.4 * len(acts), f"the gun up on only {armed} of {len(acts)} ticks"


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
    rot = math.pi / 2  # facing +x (the foe's direction)
    b, act = tick1(snap([at(350.0, 0.0, motion=80)], motion=26, rot=rot))
    assert b.doing != 'quick_turn'
    assert 'zl' in act['hold']


def test_recorded_frames_a_visible_windup_behind_is_quick_turned_and_one_in_front_is_fought():
    """The replay of the recorded cluster frames. A live Majini within WINDUP_FIRE_R in a wind-up motion or flagged
    attacking: behind him (past QUICK_ERR) the first tick is the quick turn; anywhere else there is no quick turn (the
    fight takes him), and no frame starts more than one quick turn in its three ticks.

    The snapshot captured the bot at hp 0/1 AFTER the swing - replay the decision from hp_before (the bot alive,
    the swing incoming)."""
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
        p = fx['snapshot']['player']
        px, py, pz = p['pos']
        winding = []
        for e in fx['snapshot']['enemies']:
            if (e.get('hp') or 0) <= 0:
                continue
            ex, ey, ez = e['pos']
            d2 = math.hypot(ex - px, ez - pz)
            if d2 <= WINDUP_FIRE_R and abs(ey - py) <= 120.0 and (
                    (e.get('motion') in WINDUP_MOTIONS) or ((e.get('act') or 0) & E_ATTACKING)):
                winding.append((d2, R.wrap(R.heading(ex - px, ez - pz) - p['rot'])))
        if winding:
            _dist, err = min(winding)
            if abs(err) > R.QUICK_ERR:
                assert first['act'] == {'hold': ('ldown',)} and first['doing'] == 'quick_turn', (
                    f"{fx['event_id']}: a wind-up behind him must be the quick turn, "
                    f"got {first['act']} ({first['doing']})")
            else:
                assert first['doing'] != 'quick_turn', (
                    f"{fx['event_id']}: a wind-up {math.degrees(err):+.0f} deg off his front must be fought, "
                    f"not turned from")
            assert result['stats'].get('quick_turns', 0) <= 1, f"{fx['event_id']}: the quick turn restarted"
            n_windup += 1
        n_total += 1
    assert n_total >= 3, f'only {n_total} replayable frames in the fixture'
    assert n_windup >= 2, f'only {n_windup} frames with a visible wind-up (2+ expected in the cluster data)'
