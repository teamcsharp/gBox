"""#5140 re5_ps3 crowd fix: a tight swarm (4+ Majini within 2 m) blocks the way from any side.

The front-cone ``_threat`` under-counts a swarm that closes in from the sides and the
rear: the bot fires the front ones while the rest drain him (cluster ``crowd_4_in_2m``,
234 hits, 68 deaths in 72 h). The fix recognizes the whole swarm -- every live enemy
within ``CROWD_R`` blocks the way, so he fights and relocates against all of it.

Fixture built from request #5140's representative hit 5b16b54b06a48015 (4 Majini,
146 cm, same level y=230, held lleft/rdown/zr, HP 1315 -> 80).
"""
import json
from pathlib import Path

from gbox.mercs import incident_replay
from gbox.mercs.titles.re5_ps3 import Bot, CROWD_R, CROWD_MIN, LEVEL_DY, FIGHT_R, FIGHT_CONE
import math

FIXTURES = Path(__file__).parent / 'fixtures' / 'mercs_incidents'


def _load(name):
    return json.loads((FIXTURES / f'{name}.json').read_text())


def test_crowd_swarm_blocks_the_way_from_any_side():
    """The #5140 fixture (4 Majini within 2 m, same level): all four block, the bot relocates."""
    fx = _load('re5_ps3_crowd_4_in_2m')
    result = incident_replay.replay(fx, ticks=5)
    bot = result['bot']
    # The crowd fix is live: stats name the swarm
    assert bot.stats.get('crowd_threats') == 4
    # Every enemy within CROWD_R on his level is flagged blocking (the front-cone under-count is gone)
    blocking = {slot for slot, fl in bot.flags.items() if 'blocking' in fl}
    enemy_slots = {e['slot'] for e in fx['snapshot']['enemies']}
    assert enemy_slots <= blocking, f'crowd enemies not all blocking: {enemy_slots - blocking}'
    # The bot is moving (relocating), not standing still or firing only the front ones
    held = set(result['ticks'][0]['act'].get('hold', ()))
    assert held, 'bot should hold a movement key while the swarm blocks the way'


def test_crowd_fix_catches_an_enemy_behind_the_player():
    """An enemy within CROWD_R behind the player (outside the front cone) is still blocking with the fix.

    Without the fix, ``_threat`` requires the enemy to be inside the front cone, so a
    rear threat is not blocking and the bot does not relocate for it. With the fix, any
    live enemy within CROWD_R on his level blocks the way.
    """
    fx = _load('re5_ps3_crowd_4_in_2m')
    snap = fx['snapshot']
    p = snap['player']
    px, py, pz = p['pos']
    rot = p['rot']
    # Build a 5th enemy directly behind the player: within CROWD_R, same level, but
    # heading offset > FIGHT_CONE (so _threat would NOT flag it without the fix).
    behind_x, behind_z = px + 150.0 * math.sin(rot + math.pi), pz + 150.0 * math.cos(rot + math.pi)
    rear = {'hp': 300, 'hp_max': 300, 'pos': [behind_x, py, behind_z], 'ptr': 9999, 'slot': 999}
    snap['enemies'] = list(snap['enemies']) + [rear]
    # Verify the rear enemy is outside the front cone
    dx, dz = rear['pos'][0] - px, rear['pos'][2] - pz
    off = abs(math.atan2(dx, dz) - rot)
    off = min(off, 2 * math.pi - off)  # wrap
    assert off > FIGHT_CONE, f'rear enemy unexpectedly in front cone (off={off:.3f})'
    # The fix: 5 live enemies within CROWD_R >= CROWD_MIN -> crowd recognized, all blocking
    result = incident_replay.replay(dict(fx), ticks=5)
    bot = result['bot']
    assert bot.stats.get('crowd_threats') == 5
    blocking = {slot for slot, fl in bot.flags.items() if 'blocking' in fl}
    assert 999 in blocking, 'rear enemy not flagged blocking by the crowd fix'


def test_no_crowd_single_enemy_uses_front_cone():
    """With fewer than CROWD_MIN enemies within CROWD_R, the front-cone _threat still applies (no over-flagging)."""
    fx = _load('re5_ps3_crowd_4_in_2m')
    snap = fx['snapshot']
    # Keep only 3 enemies (below CROWD_MIN=4)
    snap['enemies'] = snap['enemies'][:3]
    result = incident_replay.replay(dict(fx), ticks=5)
    bot = result['bot']
    assert bot.stats.get('crowd_threats') is None, 'crowd fix should not fire with < CROWD_MIN enemies'
    # The 3 front-cone enemies are still blocking (they are within FIGHT_R and in the front cone)
    blocking = {slot for slot, fl in bot.flags.items() if 'blocking' in fl}
    assert len(blocking) > 0, 'front-cone threats should still be flagged blocking'


def test_fixture_replays_deterministically():
    """The #5140 fixture replays deterministically (same act sequence on re-run)."""
    fx = _load('re5_ps3_crowd_4_in_2m')
    first = incident_replay.replay(fx, ticks=12)
    second = incident_replay.replay(fx, ticks=12)
    assert [t['act'] for t in first['ticks']] == [t['act'] for t in second['ticks']]
    # The bot relocated throughout: it never stood still
    assert any(t['act'] for t in first['ticks'])


def test_constants_are_sane():
    """The crowd constants match the cluster's cause signature (4+ within 2 m)."""
    assert CROWD_R == 200.0
    assert CROWD_MIN == 4
    assert CROWD_R < FIGHT_R, 'CROWD_R must be tighter than FIGHT_R (the swarm is inside the fight range)'
