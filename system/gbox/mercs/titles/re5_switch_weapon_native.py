"""Native RE5 weapon replacement; shared controller lock and mailbox only.

No inventory UI or controller-input fallback. Confirmation means native equip
readback; combat hit accounting remains the bot's separate responsibility.
"""
from __future__ import annotations

import struct
import time

from . import re5_switch as R, re5_switch_native as N, re5_weapons

STAGE, DISCARD, COMMIT = 0x118EB70, 0x118EC38, 0x118EECC
MANAGER, SLOT_VT, SLOT_ACTIVE = 0x30E8, 0x1C782C0, 0x2D


def records(ctl):
    raw = ctl.rd(ctl.player + R.P_INV, 24 * R.INV_SLOT)
    out = []
    for index in range(24):
        offset = index * R.INV_SLOT
        if struct.unpack_from('<Q', raw, offset)[0] != ctl.base + SLOT_VT:
            raise N.Unavailable('native item record identity changed')
        if raw[offset + SLOT_ACTIVE]:
            out.append({'slot': ctl.player + R.P_INV + offset,
                        'id': struct.unpack_from('<I', raw, offset + R.INV_ID)[0],
                        'grid': struct.unpack_from('<I', raw, offset + R.INV_GRID)[0],
                        'hand': struct.unpack_from('<I', raw, offset + R.INV_HAND)[0],
                        'unit': struct.unpack_from('<Q', raw, offset + R.INV_OBJ)[0]})
    return out


def replace(ctl, item, *, expected=None):
    """Construct, initialize, replace grid0 and read back native equipment.

    item is the catalogue's low-byte weapon ID. The caller must relinquish bot
    inputs briefly so the native idle guard can succeed, and preserve operator
    takeover. A refusal never opens the inventory or falls back to button input.
    """
    if type(item) is not int or item not in re5_weapons.WEAPONS:
        raise ValueError('unknown RE5 weapon')
    with ctl.lock:
        ctl.prepare()
        player, generation = ctl.ready()
        if expected is not None and (player, generation) != expected:
            raise N.Unavailable('requested player life changed')
        ctl.sp = ctl.q(ctl.base + R.S_PLAYER)
        ctl.player, ctl.generation = player, generation
        ctl.original = ctl.q(player)
        if ctl.q(player + MANAGER) != ctl.base + 0x1C78280:
            raise N.Unavailable('native inventory manager changed')
        inventory = records(ctl)
        old = [r for r in inventory if r['grid'] == 0]
        if len(old) > 1 or len(inventory) >= 24:
            raise N.Unavailable('main slot is ambiguous or inventory storage is full')
        old_slot = old[0]['slot'] if old else 0
        old_unit = old[0]['unit'] if old else 0
        old_born = ctl.q(old_unit + 0x1A00) if old_unit else 0
        if old_unit and ctl.q(old_unit + 0x1A10) != player:
            raise N.Unavailable('previous main weapon owner changed')
        scratch = ctl.heap + 0x800
        unit = born = None
        commit_published = False
        started = time.monotonic()
        try:
            ctl.attach()
            slot = ctl.call(STAGE, player, generation, scratch, 0x100 + item)
            if not slot:
                raise N.Unavailable('native weapon constructor refused')
            if slot != scratch + 8:
                raise N.Uncertain('native weapon constructor returned an unexpected record')
            unit = ctl.q(slot + R.INV_OBJ)
            if not R.ptr_ok(unit):
                raise N.Uncertain('native weapon object is missing')
            born = ctl.q(unit + 0x1A00)

            def identity():
                if ctl.q(unit + 0x1A00) != born or ctl.q(unit + 0x1A10) != player:
                    raise N.AllocationLost('staged weapon allocation changed')

            def initialized():
                identity()
                return ctl.rd(unit + 0x1B88, 1) == b'\1' and ctl.rd(unit + 0x1A71, 1) == b'\0'

            ctl.wait(initialized)
            if (R.class_name(ctl, unit) or '').lower() != f'uwp{item:02x}':
                raise N.Unavailable('native weapon class differs from the selected catalogue item')
            commit_published = True  # A missing receipt after this point must never retry or discard.
            result = ctl.call(COMMIT, player, generation, scratch, unit, born,
                              old_slot, old_unit, old_born)
            if result == 0:
                commit_published = False
                raise N.Unavailable('native replacement refused: player busy or inventory changed')
            if result != 1:
                raise N.Uncertain('native replacement needs inspection; request will not be repeated')
            identity()
            equipped = [r for r in records(ctl) if r['grid'] == 0]
            if len(equipped) != 1 or equipped[0]['unit'] != unit or equipped[0]['id'] != 0x100 + item \
                    or equipped[0]['hand'] != 1 or ctl.rd(scratch + 0x35, 1) != b'\0':
                raise N.Uncertain('native equipped weapon readback did not confirm the selection')
            return {'state': 'confirmed', 'verified': True, 'op': 'equip_primary',
                    'item': item, 'weapon': re5_weapons.WEAPONS[item].name,
                    'player': player, 'player_generation': generation, 'weapon_generation': born,
                    'grid': 0, 'elapsed_ms': round(1000 * (time.monotonic() - started), 1)}
        except Exception as exc:
            if commit_published or isinstance(exc, (N.Uncertain, N.AllocationLost, OSError)):
                ctl.failed, ctl.recoverable = True, False
            raise
        finally:
            try:
                if unit is not None and born is not None and not commit_published:
                    if ctl.call(DISCARD, player, generation, scratch, unit, born) != 1:
                        ctl.failed, ctl.recoverable = True, False
                        raise N.Uncertain('staged weapon cleanup unconfirmed')
            finally:
                ctl.check()
                if ctl.q(player) in (ctl.heap, ctl.base + N.TEMP):
                    ctl.write(player, struct.pack('<Q', ctl.original))
