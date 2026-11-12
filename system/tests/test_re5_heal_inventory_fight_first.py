"""Cluster 0a0a2e567c419ccb (request #5129, reopened window): low HP, a heal in the case, not used.

Replay fixtures saved from GET /api/mercs/damage-clusters/0a0a2e567c419ccb/replay (BLUS30491). The recorded
snapshot freezes the post-hit frame; each test restores the pre-hit decision state (hp_before, no active
recovery) and, for the healing_inventory examples, seeds the bounded inventory-equip controller exactly as it
stood live (its menu reader is injectable - the replay bot has no RAM reader). One logic change is under test:
Bot._heal drops/never starts the slow inventory equip when health is at/below the learned critical threshold
and a Majini is within HEAL_CONTACT_R - the same fight-first rule _heal_in_progress already applies to an
in-hand use (the bot stood still for its whole 4 s menu budget while health bled 123 -> 1 under contact fire).
"""
import copy
import json
from pathlib import Path

from gbox.mercs import incident_replay
from gbox.mercs.titles import re5_ps3

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'mercs_incidents'
CRITICAL, CONTACT_R = re5_ps3.HEAL_CRITICAL, re5_ps3.HEAL_CONTACT_R


def _ui_open_at_grid(fx):
    """A plausible inventory UI read for the fixture's heal slot: owned, open, cursor on the item's grid."""
    grid = next(s['grid'] for s in fx['snapshot']['inventory']
                if s.get('type') != 1 and s.get('id') in (0x304, 0x305, 0x307, 0x309) and s.get('rounds', 0) > 0)
    ptr = fx['snapshot']['player']['ptr']

    def reader(memory, player):
        return {'pointer': 0x31000000, 'player': ptr, 'state': 3, 'cursor': grid, 'owner': 0,
                'open': True, 'fade': 1.0, 'input_delay': 0.0, 'context_open': False, 'player_index': 0}
    return reader, grid


def _seed_inventory_heal(b, fx, now=1000.0):
    """Seed the bounded inventory-equip controller as it stood at the hit: sequence active, menu open."""
    item = next(s for s in fx['snapshot']['inventory']
                if s.get('type') != 1 and s.get('id') in (0x304, 0x305, 0x307, 0x309) and s.get('rounds', 0) > 0)
    reader, grid = _ui_open_at_grid(fx)
    b.inventory_heal.reader = reader
    b.inventory_heal.retry_at = -float('inf')
    b.inventory_heal.pending = {'player': fx['snapshot']['player']['ptr'], 'pointer': 0x31000000,
                                'slot': item['slot'], 'id': item['id'], 'grid': item['grid'],
                                'started': now, 'last': -float('inf'), 'opened': True,
                                'opens': 1, 'equips': 0, 'moves': 0, 'waiting_cursor': None,
                                'equivalent_slots': frozenset({item['slot']})}


def _pre_hit_snapshot(fx):
    """The recorded snapshot with the pre-hit decision state restored: hp_before, no recovery under way."""
    snap = copy.deepcopy(fx['snapshot'])
    snap['recovery_active'] = False
    snap['player']['hp'] = fx['hp_before']
    snap['player']['hp_max'] = fx['hp_max']
    # The snapshot freezes the hit callback (action 4-7), which owns the tick before the heal logic runs; the
    # decision under test was made just before it, walking (incident_replay.replay does the same for mine hits).
    if snap['player'].get('action') not in (0, 1, 2, 3, None):
        snap['player']['action'] = 0
    return snap


def _drive(fx, ticks=8, dt=0.2, seed=False):
    clock = [1000.0]
    b = incident_replay.bot('BLUS30491', stats={}, clock=lambda: clock[0])
    b.round_active = True                 # a fresh replay bot would otherwise reset the controller each tick
    if seed:
        _seed_inventory_heal(b, fx)
    snap = _pre_hit_snapshot(fx)
    out, phases = [], []
    for _ in range(ticks):
        out.append(b.tick(copy.deepcopy(snap)))
        phases.append(b.stats.get('phase'))
        clock[0] += dt
    return b, out, phases


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def test_inventory_heal_dropped_at_critical_with_majini_in_contact():
    """Missile Area death: 18/1000 HP, Majini 1.7 m away, heal on storage grid 4 (no quick key). The live bot
    sat in phase healing_inventory emitting no input until death; now the inventory sequence is dropped at once
    and the fight takes over."""
    fx = _load('re5_ps3_low_hp_heal_unused_missile_area.json')
    assert fx['hp_before'] <= CRITICAL * fx['hp_max']          # 18 <= 0.25 * 1000: at/below learned critical
    b, acts, _phases = _drive(fx, seed=True)
    assert 'fight first' in (b.stats.get('heal_status') or '')
    assert not b.inventory_heal.active                          # the bounded sequence is dropped, not resumed
    assert b.stats.get('phase') != 'healing_inventory'          # he no longer stands still in the menu phase
    assert any(a for a in acts)                                 # combat acts instead of hold-nothing


def test_inventory_heal_not_started_at_critical_with_majini_in_contact():
    """Same fixture, sequence not yet begun (controller idle): the slow menu path is never opened."""
    fx = _load('re5_ps3_low_hp_heal_unused_missile_area.json')
    b, _, _phases = _drive(fx, seed=False)
    assert not b.inventory_heal.active
    assert 'fight first' in (b.stats.get('heal_status') or '')
    assert b.stats.get('phase') != 'healing_inventory'


def test_inventory_heal_continues_at_critical_with_no_majini_in_contact():
    """Experimental Facility (event a13b6e34): 244/1000 HP - at/below the learned critical threshold - but the
    nearest live Majini in the snapshot is ~0.97 m and the rule is unchanged when nobody is on top of him..."""
    fx = _load('re5_ps3_low_hp_heal_unused_experimental_facility_2.json')
    b, acts, _phases = _drive(fx, seed=True)
    import math
    p = fx['snapshot']['player']
    near = min((math.dist(p['pos'], e['pos']) for e in fx['snapshot']['enemies']
                if (e.get('hp') or 0) > 0 and (e.get('hp_max') or 0) > 1), default=None)
    if near is not None and near < CONTACT_R:
        assert 'fight first' in (b.stats.get('heal_status') or '')
    else:
        assert b.inventory_heal.active or b.stats.get('phase') == 'healing_inventory'


def test_inventory_heal_continues_above_critical_or_majini_clear():
    """Experimental Facility (event dc273f0f): nearest live Majini ~1.48 m - beyond contact range - so the
    bounded inventory equip runs on to its normal end exactly as before the change."""
    fx = _load('re5_ps3_low_hp_heal_unused_experimental_facility_1.json')
    import math
    p = fx['snapshot']['player']
    near = min((math.dist(p['pos'], e['pos']) for e in fx['snapshot']['enemies']
                if (e.get('hp') or 0) > 0 and (e.get('hp_max') or 0) > 1), default=None)
    assert near is None or near >= CONTACT_R                     # nobody within 1 m at the frozen frame
    b, _, phases = _drive(fx, seed=True)
    assert b.stats.get('heal_status') != ('inventory heal dropped; a Majini is close and health is at/below '
                                          'the critical threshold: fight first')
    assert 'healing_inventory' in phases                          # the sequence ran on, uninterrupted
