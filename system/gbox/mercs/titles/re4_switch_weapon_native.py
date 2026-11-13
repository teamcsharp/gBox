"""RE4 Switch equipment refresh through the game's complete native lifecycle.

004af630 is the equipment synchronizer: compare the selected inventory item,
retire the old weapon, load class/variant assets, initialize the new weapon and
reset its animation. Writing G_CLASS first makes it skip all of that work.
"""
from __future__ import annotations

import math
import struct
import time

from . import re4_switch as R, re4_weapons as W

REFRESH = 0x4AF630
REFRESH_HEAD = bytes.fromhex('f85fbca9f65701a9f44f02a9fd7b03a9fdc30091b53300d0b5b247f9')
SELECT = 0x294600
SELECT_HEAD = bytes.fromhex('ffc300d1f44f01a9fd7b02a9fd830091f30301aaf40300aab30700b4')
# The weapon table includes campaign guns which lack upgrade rows (launchers,
# bow, PRL). Those remain selectable; random draws use the separate policy.
WEAPONS = frozenset(W.CLASS_OF) - {0x01, 0x02, 0x0E, 0x38, 0x08, 0x09, 0x0A, 0x10, 0x28, 0x47}


def active(ctl):
    wep = ctl.q(ctl.player + R.PL_WEP)
    if not R.ptr_ok(wep):
        return None
    obj = ctl.q(wep + R.WEP_OBJ)
    if not R.ptr_ok(obj):
        return None
    item = struct.unpack('<H', ctl.rd(obj + R.OBJ_ITEM, 2))[0]
    return {'item': item, 'object': obj, 'controller': wep}


def choices(ctl):
    ctl.ready()
    rows = W.decode_weapon_table(ctl.rd(ctl.base + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ))
    held = active(ctl) or {}
    inv = W.Reader(ctl.rd, ctl.base).items(owner=0)
    out = []
    for item in sorted(WEAPONS & rows.keys()):
        cls = rows[item]['class']
        damage = struct.unpack('<f', ctl.rd(ctl.base + W.FIREPOWER_TBL + cls * 28, 4))[0]
        damage = round(damage, 2) if math.isfinite(damage) and 0 <= damage <= 1e9 else None
        out.append({'item': item, 'weapon': W.name(item), 'damage': damage,
                    'damage_basis': 'live_level0_firepower' if damage is not None else 'unmeasured',
                    'family': 'shotgun' if cls in W.SHOTGUN_FAR_CLASSES else
                              'magnum' if cls in (5, 6, 15) else 'gun',
                    'equipped': held.get('item') == item,
                    'in_inventory': any(i['id'] == item for i in inv)})
    return sorted(out, key=lambda x: (x['damage'] is None, -(x['damage'] or 0), x['weapon']))


def replace(ctl, item, *, expected=None, allowed=None):
    from .re4_switch_native import Unavailable, Uncertain
    if type(item) is not int or item not in WEAPONS:
        raise ValueError('unknown RE4 weapon')
    with ctl.lock:
        life = ctl.ready()
        if expected is not None and life != expected:
            raise Unavailable('requested player changed')
        def guard():
            if (allowed is not None and not allowed()) or ctl.ready() != life:
                raise Unavailable('weapon handover cancelled or player changed')
            game = R.game_state(ctl, ctl.base) or {}
            if game.get('phase') != 'playing' or not game.get('in_control'):
                raise Unavailable('weapon replacement needs a live controllable player')
        guard()
        if getattr(ctl, 'weapon_uncertain', False):
            raise Uncertain('previous native equip is unresolved; no repeat published')
        for off, head in ((REFRESH, REFRESH_HEAD), (SELECT, SELECT_HEAD)):
            if ctl.rd(ctl.base + off, len(head)) != head:
                raise Unavailable('native equipment routine signature changed')
        reader = W.Reader(ctl.rd, ctl.base)
        held = reader.equipped()
        current = active(ctl)
        rows = W.decode_weapon_table(ctl.rd(ctl.base + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ))
        if not held or not current or item not in rows or current['item'] not in rows:
            raise Unavailable('native equipped inventory/weapon cannot be identified')
        if reader.game_obj() != ctl.base + W.GAME_OBJ:
            raise Unavailable('game-state allocation changed')
        # Wait for the gun to lower after the bot has released its inputs.
        deadline = time.monotonic() + .8
        while ctl.rd(current['object'] + R.OBJ_STAT, 1)[0] in R.LASER_UP_STATS:
            guard()
            if time.monotonic() >= deadline:
                raise Unavailable('gun is still raised; release inputs before equipping')
            time.sleep(.01)
            current = active(ctl)
            if current is None:
                raise Unavailable('weapon changed while lowering')
        guard()
        ctl.ensure_attached()
        slot = held['addr']
        lv = W.max_levels(item) or {'packed': 0, 'capacity': 0}
        cap = rows[item]['capacity'][lv['capacity']]
        loaded = 99 if cap in (0, W.CAP_INFINITE) else min(cap, 0x1FFF)
        old = ctl.rd(slot, W.ITEM_SZ)
        # Preserve slot ownership and case placement. No fabricated object or
        # stale heap pointer is installed. SELECT supplies the native levels.
        payload = bytearray(old)
        struct.pack_into('<H', payload, 0, item)
        struct.pack_into('<HH', payload, 6, lv['packed'], loaded << 3)
        published = False
        try:
            ctl.write(slot, bytes(payload))
            guard()
            published = True
            ctl.call(SELECT, ctl.base + W.ITEM_MGR, slot)
            guard()
            # Repair an earlier data-only swap's stale class using the actual
            # active object, so the native comparison cannot silently skip it.
            actual_row = rows[current['item']]
            ctl.write(ctl.base + W.GAME_OBJ + W.G_CLASS,
                      bytes((actual_row['class'], actual_row['variant'])))
            ctl.call(REFRESH, timeout=5.0)
            guard()
            got = active(ctl)
            selected = reader.equipped()
            cls = ctl.rd(ctl.base + W.GAME_OBJ + W.G_CLASS, 2)
            if not got or got['item'] != item or not selected or selected['id'] != item \
                    or cls != bytes((rows[item]['class'], rows[item]['variant'])):
                raise Uncertain('native weapon object did not confirm the selected weapon')
            return {'state': 'confirmed', 'verified': True, 'op': 'equip_primary',
                    'item': item, 'weapon': W.name(item), 'player': life[0],
                    'player_generation': life[1], 'weapon_generation': got['object'],
                    'weapon_object_item': got['item'], 'loaded': loaded}
        except Exception:
            if published:
                ctl.weapon_uncertain = True  # no replay/rollback after native teardown may have begun
            else:
                ctl.write(slot, old)
            raise
