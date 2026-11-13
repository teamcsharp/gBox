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

# 00495040 chooses these writable resource tables by G_CHARACTER. Empty
# character rows return without loading anything, even after G_CLASS changes.
# Each row contains the game's model/behavior resource IDs, not host assets.
ASSET_TABLES = {0: (0xB288C0, 0xB14D30), 2: (0xB288B8, 0xB14EB8),
                3: (0xB288C8, 0xB15040), 4: (0xB288D0, 0xB15350),
                5: (0xB288D8, 0xB151C8)}


def asset_index(character, cls, variant):
    """The pinned loader's table index (00495040, including its jump table)."""
    if character in (2, 3, 4):
        if 0 <= cls - 0x13 < 14 and (0x3059 >> (cls - 0x13)) & 1:
            return 0x17 if character == 4 else 0x13
        return cls
    if character == 5:
        if cls <= 0x20 and (0x182C80000 >> cls) & 1:
            return 4
        return 5 if cls == 10 else cls
    if 0 <= cls - 0x16 < 11 and (0x60B >> (cls - 0x16)) & 1:
        return 0x13
    if cls == 3 and variant == 2:
        return 0x12
    if cls == 11 and variant > 1:
        return 0x14
    return {(10, 1): 0x1F, (10, 2): 0x20, (9, 1): 0x15, (9, 2): 0x18,
            (14, 1): 0x19, (46, 1): 0x2F, (13, 2): 0x1E}.get((cls, variant), cls)


def prepare_assets(ctl, row):
    """Fill only a completely empty character row from a verified campaign row.

    Native refresh still loads/constructs the object, which must independently
    confirm the requested item. Existing character-specific resources stay intact.
    """
    from .re4_switch_native import Unavailable
    character = ctl.rd(ctl.base + W.GAME_OBJ + W.G_CHARACTER, 1)[0]
    if character not in ASSET_TABLES:
        raise Unavailable('unsupported character weapon resource table')
    if character == 0:
        return {'source': 'native_character'}
    got, table = ASSET_TABLES[character]
    source_got, source_table = ASSET_TABLES[0]
    if ctl.q(ctl.base + got) != ctl.base + table or ctl.q(ctl.base + source_got) != ctl.base + source_table:
        raise Unavailable('native weapon resource table pointer changed')
    index = asset_index(character, row['class'], row['variant'])
    source_index = asset_index(0, row['class'], row['variant'])
    if not 0 <= index < W.N_CLASSES or not 0 <= source_index < W.N_CLASSES:
        raise Unavailable('weapon resource index is out of range')
    at = ctl.base + table + index * 8
    before = ctl.rd(at, 8)
    if struct.unpack_from('<H', before)[0]:
        return {'source': 'native_character', 'character': character, 'index': index}
    resource = ctl.rd(ctl.base + source_table + source_index * 8, 8)
    if any(before) or not all(struct.unpack('<HH', resource[:4])) or any(resource[4:]):
        raise Unavailable('empty weapon resource row has no verified campaign fallback')
    ctl.write(at, resource)
    if ctl.rd(at, 8) != resource:
        raise Unavailable('campaign weapon resource row did not read back')
    return {'source': 'native_campaign_fallback', 'character': character, 'index': index,
            'resources': list(struct.unpack('<HH', resource[:4]))}


def active(ctl):
    wep = ctl.q(ctl.player + R.PL_WEP)
    if not R.ptr_ok(wep):
        return None
    obj = ctl.q(wep + R.WEP_OBJ)
    if not R.ptr_ok(obj):
        return None
    item = struct.unpack('<H', ctl.rd(obj + R.OBJ_ITEM, 2))[0]
    return {'item': item, 'object': obj, 'controller': wep}


def current_weapon(ctl):
    """A temporarily absent/zero object is unknown, never an invalid wire ID."""
    ctl.ready()
    item = (active(ctl) or {}).get('item')
    return item if type(item) is int and item in WEAPONS else None


def reconcile(ctl, life, held, current, rows):
    """Retire uncertainty only on native completion plus coherent equipment.

    Never resubmit an outstanding call. A new player life may establish its own
    equipment; on the same life only the requested weapon resolves the receipt.
    Legacy boolean uncertainty has no evidence and remains blocked.
    """
    from .re4_switch_native import Uncertain
    receipt = getattr(ctl, 'weapon_uncertain', None)
    if not receipt:
        return
    quiet = getattr(ctl, 'equipment_quiescent', None)
    coherent = bool(held and current and current['item'] in WEAPONS and
                    current['item'] == held['id'] == held.get('held_id') and held['id'] in rows)
    if coherent:
        row = rows[held['id']]
        coherent = ctl.rd(ctl.base + W.GAME_OBJ + W.G_CLASS, 2) == bytes((row['class'], row['variant']))
    if isinstance(receipt, dict) and callable(quiet) and quiet() and coherent:
        new_life = tuple(receipt['life']) != tuple(life)
        confirmed_late = receipt.get('stage') == 'refresh_returned' and held['id'] == receipt.get('item')
        if new_life or confirmed_late:
            ctl.weapon_resolution = dict(receipt, resolved='new_native_life' if new_life else 'late_object',
                                         resolved_life=life, resolved_item=held['id'])
            ctl.weapon_uncertain = None
            return
    detail = f"; first failure at {receipt.get('stage')}: {receipt.get('error')}" if isinstance(receipt, dict) else ''
    raise Uncertain('previous native equip is unresolved; no repeat published' + detail)


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
        for off, head in ((REFRESH, REFRESH_HEAD), (SELECT, SELECT_HEAD)):
            if ctl.rd(ctl.base + off, len(head)) != head:
                raise Unavailable('native equipment routine signature changed')
        reader = W.Reader(ctl.rd, ctl.base)
        held = reader.equipped()
        current = active(ctl)
        rows = W.decode_weapon_table(ctl.rd(ctl.base + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ))
        reconcile(ctl, life, held, current, rows)
        if not held or not current or item not in rows or held['id'] not in rows:
            raise Unavailable('native equipped inventory/weapon cannot be identified')
        if reader.game_obj() != ctl.base + W.GAME_OBJ:
            raise Unavailable('game-state allocation changed')
        actual_row = rows.get(current['item']) if current['item'] in WEAPONS else None
        if actual_row is None:
            # Live Ada/Punisher: the weapon object exists with its owner, but
            # its +0x400 item field is zero. Do not mistake that observation for
            # a missing inventory gun and postpone every round's loadout.
            # A coherent native selection can establish the old class for a
            # DIFFERENT-class refresh; final success still requires the actual
            # new object's item. Never manufacture that identity from inventory.
            selected_row = rows[held['id']]
            selected_class = bytes((selected_row['class'], selected_row['variant']))
            if current['item'] != 0 or ctl.q(current['object'] + 0x3F8) != ctl.player \
                    or held.get('held_id') != held['id'] \
                    or ctl.rd(ctl.base + W.GAME_OBJ + W.G_CLASS, 2) != selected_class \
                    or rows[item]['class'] == selected_row['class']:
                raise Unavailable('weapon object identity is unavailable and selection is not a coherent recovery source')
            actual_row = selected_row
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
        assets = prepare_assets(ctl, rows[item])
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
        published, stage = False, 'inventory'
        try:
            ctl.write(slot, bytes(payload))
            guard()
            published = True
            stage = 'select_pending'
            ctl.call(SELECT, ctl.base + W.ITEM_MGR, slot)
            stage = 'select_returned'
            guard()
            # Repair an earlier data-only swap's stale class using the actual
            # active object, so the native comparison cannot silently skip it.
            ctl.write(ctl.base + W.GAME_OBJ + W.G_CLASS,
                      bytes((actual_row['class'], actual_row['variant'])))
            stage = 'refresh_pending'
            ctl.call(REFRESH, timeout=5.0)
            stage = 'refresh_returned'
            guard()
            got = active(ctl)
            deadline = time.monotonic() + 1.0
            while (not got or got['item'] != item) and time.monotonic() < deadline:
                guard()
                time.sleep(.01)
                got = active(ctl)
            selected = reader.equipped()
            cls = ctl.rd(ctl.base + W.GAME_OBJ + W.G_CLASS, 2)
            if not got or got['item'] != item or not selected or selected['id'] != item \
                    or cls != bytes((rows[item]['class'], rows[item]['variant'])):
                raise Uncertain('native weapon object did not confirm the selected weapon')
            return {'state': 'confirmed', 'verified': True, 'op': 'equip_primary',
                    'item': item, 'weapon': W.name(item), 'player': life[0],
                    'player_generation': life[1], 'weapon_generation': got['object'],
                    'weapon_object_item': got['item'], 'loaded': loaded, 'assets': assets}
        except Exception as exc:
            if published:
                ctl.weapon_uncertain = {'life': life, 'item': item, 'stage': stage,
                                        'error': f'{type(exc).__name__}: {exc}'[:240]}
            else:
                ctl.write(slot, old)
            raise
