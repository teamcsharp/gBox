"""RE6 loaded-weapon selection through its existing guarded native equip action."""
from __future__ import annotations

import time

from . import re6_switch as R, re6_switch_equip as E, re6_switch_native as N


def choices(ctl):
    from .re6_switch_mods import WEAPON_NAMES, WEAPON_KIND
    epoch = ctl.ready()
    player, _ = epoch
    guns = R.inventory_guns(ctl, player)
    index, active, _ = R.inventory_state(ctl, player)
    rows = []
    for item, name in WEAPON_NAMES.items():
        kind = 0x100 + item
        loaded = kind in guns
        supported = kind in E.GUNS
        reason = ('' if loaded and supported else
                  'This weapon hand lifecycle is not verified on this RE6 build.' if not supported else
                  'Not loaded this round; native weapon creation and resource registration are not yet verified.')
        rows.append({'item': item, 'weapon': name, 'family': WEAPON_KIND.get(item, 'weapon'),
                     'in_inventory': loaded, 'equipped': loaded and guns[kind] == index and active == item,
                     'available': loaded and supported, 'reason': reason})
    if ctl.ready() != epoch:
        raise N.Unavailable('player allocation changed during weapon catalogue readback')
    return rows


def select(ctl, item, *, expected, allowed, clock=time.monotonic, sleep=time.sleep):
    """Caller holds ctl.lock and the bot's acknowledged input handover.

    One published action only. Selection uses loaded native hand objects; it
    never constructs a weapon or assigns active inventory/hand cells itself.
    """
    from .re6_switch_mods import WEAPON_NAMES
    if type(item) is not int or item not in WEAPON_NAMES or 0x100 + item not in E.GUNS:
        raise N.Unavailable('unsupported RE6 primary weapon')
    player, generation = expected
    def guard():
        if not allowed() or ctl.ready() != expected:
            raise N.Unavailable('player, round, input owner, or request deadline changed')
        if ctl.rd(ctl.base + R.SIG_OFF, len(R.SIGNATURE)) != R.SIGNATURE:
            raise N.Unavailable('RE6 executable changed')
    guard()
    index = R.inventory_guns(ctl, player).get(0x100 + item)
    if index is None:
        raise N.Unavailable('selected RE6 weapon is not loaded in this round')
    until = clock() + .8
    while R.unit_action(ctl, player) not in E.FREE_ACTIONS:
        guard()
        if clock() >= until:
            raise N.Unavailable('player is busy; no weapon selection published')
        sleep(.002)
    class Memory:
        def rd(self, at, length):
            return ctl.rd(at, length)
        def wr(self, at, data):
            guard()
            ctl.ad.write_memory(at, data)
    memory = Memory()
    result = E.request(memory, ctl.base, player, 0x100 + item, expected_index=index)
    while result.get('state') in ('requested', 'pending'):
        guard()
        sleep(.002)
        result = E.poll(memory)
    if result.get('state') != 'equipped' or result.get('player_generation') != generation:
        raise N.Uncertain('native weapon selection was not confirmed; not replayed')
    guard()
    hand = result['object']
    return {'state': 'confirmed', 'verified': True, 'op': 'equip_primary', 'item': item,
            'weapon': WEAPON_NAMES[item], 'player': player, 'player_generation': generation,
            'weapon_generation': ctl.w(hand + E.GENERATION), 'object': hand, 'index': index}


def replace(ctl, item, *, expected=None, allowed=None):
    with ctl.lock:
        expected = ctl.ready() if expected is None else expected
        return select(ctl, item, expected=expected, allowed=allowed or (lambda: True))
