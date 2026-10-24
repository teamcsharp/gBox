"""Read-only recovery-item identification for RE5 Gold PS3 BLUS30491 01.01.

These are full inventory IDs, including category 03. Red herbs alone do not
restore HP. No actor names, colours, or generic Square prompts authorize pickup.
Item IDs: https://astralshade.wordpress.com/2013/12/19/resident-evil-5-ps3-mod-weapons-hack/
"""
from __future__ import annotations

import math
import struct


HEAL_NAMES = {0x304: "First Aid Spray", 0x305: "Green Herb",
              0x307: "Mixed Herb (G+G)", 0x309: "Mixed Herb (G+R)"}
HEAL_IDS = frozenset(HEAL_NAMES)
RED_HERB = 0x306
# Native BLUS30491 getDTI: uIt0304/0305/0307/0309. uIt0308 does
# not occur in this build's class table; it is deliberately not guessed.
HEALTH_VTABLES = {0x015BBE28: 0x304, 0x015BBC58: 0x305,
                 0x015BB8B8: 0x307, 0x015BB6E8: 0x309}
ITEM_MANAGER_VT, ITEM_DATA_VT, PICKUP_VOLUME_VT = 0x0157B630, 0x015ADD68, 0x01634B00
ITEM_HANDLE, ITEM_DATA, ITEM_ID, ITEM_COUNT = 0x1110, 0x1BC0, 0x1C36, 0x1C38
ITEM_VOLUME, ITEM_SELF, MAX_ITEMS = 0x1C60, 0x1C6C, 512


def ground_items(memory):
    """Verified native recovery actors with their game-owned pickup handles.

    Ghidra FUN_00158a98 walks sItem+28/+34, reads pickup volume +1c60,
    identifies inventory type at item data+76, and fills the prompt target
    from actor+1110. The pickup volume's +0c enables the actor; +10 is a
    nearby-player mask and must not hide distant health from pathfinding.
    This reads game memory only and returns nothing across an unstable list.
    """
    from . import re5_ps3 as R
    if not callable(getattr(memory, 'rd', None)):
        return []
    try:
        manager = R.u32(memory, R.S_ITEM)
        if not R.ptr_ok(manager) or manager % 4:
            return []
        header = memory.rd(manager, 0x38)
        if struct.unpack_from('>I', header)[0] != ITEM_MANAGER_VT:
            return []
        count, array = struct.unpack_from('>I', header, 0x28)[0], struct.unpack_from('>I', header, 0x34)[0]
        if not 0 < count <= MAX_ITEMS or not R.ptr_ok(array) or array % 4 or array + count * 4 > 0x40000000:
            return []
        raw = memory.rd(array, count * 4)
        result, seen = [], set()
        for actor in struct.unpack(f'>{count}I', raw):
            if not R.ptr_ok(actor) or actor % 4 or actor + ITEM_SELF + 4 > 0x40000000 or actor in seen:
                continue
            seen.add(actor)
            try:
                vtable = R.u32(memory, actor)
                item_id = HEALTH_VTABLES.get(vtable)
                if item_id is None or R.u32(memory, actor + ITEM_DATA) != ITEM_DATA_VT:
                    continue
                # The item identity/count/volume/back-pointer are read together.
                state = memory.rd(actor + 0x1C34, 0x3C)
                actual_id = struct.unpack_from('>H', state, 2)[0]
                quantity = struct.unpack_from('>I', state, 4)[0]
                volume = struct.unpack_from('>I', state, ITEM_VOLUME - 0x1C34)[0]
                own = struct.unpack_from('>I', state, ITEM_SELF - 0x1C34)[0]
                if actual_id != item_id or not 0 < quantity <= 0x7FFFFFFF or own != actor \
                        or not R.ptr_ok(volume) or volume % 4 or volume + 16 > 0x40000000:
                    continue
                collision = memory.rd(volume, 16)
                if struct.unpack_from('>3I', collision) != (PICKUP_VOLUME_VT, actor, 0x07000000 | item_id << 8) \
                        or collision[12] != 1:
                    continue
                handle = R.u32(memory, actor + ITEM_HANDLE)
                pos = struct.unpack('>3f', memory.rd(actor + 0x30, 12))
                if not 0 < handle < 0xFFFFFFFF or not all(math.isfinite(x) and abs(x) < 1e7 for x in pos):
                    continue
                # An actor may be collected/reused while its position is read.
                if R.u32(memory, actor) != vtable or R.u32(memory, actor + ITEM_HANDLE) != handle \
                        or memory.rd(actor + 0x1C34, 8) != state[:8] \
                        or R.u32(memory, actor + ITEM_VOLUME) != volume or R.u32(memory, actor + ITEM_SELF) != actor \
                        or memory.rd(volume, 16) != collision:
                    continue
                result.append({'ptr': actor, 'handle': handle, 'id': item_id, 'name': HEAL_NAMES[item_id],
                               'pos': pos, 'count': quantity, 'evidence': 'BLUS30491 native sItem/uIt030x pickup'})
            except (ValueError, OSError, struct.error, IndexError):
                continue
        if R.u32(memory, R.S_ITEM) != manager or R.u32(memory, manager) != ITEM_MANAGER_VT \
                or R.u32(memory, manager + 0x28) != count or R.u32(memory, manager + 0x34) != array \
                or memory.rd(array, count * 4) != raw:
            return []
        return result
    except (ValueError, OSError, struct.error, IndexError):
        return []


def carried_heals(inventory):
    """Usable, populated recovery records; preserve storage/grid/hand identity."""
    return [row for row in inventory or () if isinstance(row, dict)
            and type(row.get('id')) is int and row['id'] in HEAL_IDS
            and row.get('type', 3) == 3 and type(row.get('rounds')) is int
            and 0 < row['rounds'] <= 0x7FFFFFFF]


def needs_healing(player, threshold=0.4):
    """Living low HP only; DYING recovery and mandatory prompts own HP1."""
    try:
        hp, maximum = player['hp'], player['hp_max']
        return (not isinstance(hp, bool) and not isinstance(maximum, bool)
                and math.isfinite(hp) and math.isfinite(maximum)
                and 1 < hp <= maximum and maximum > 0 and hp <= maximum * threshold)
    except (TypeError, ValueError, KeyError):
        return False


def pickup_request(memory, request, rows):
    """An exact currently displayed health pickup, rechecked before pad input.

    ``rows`` is the observed goal set, not authorization: the native ground
    reader must still find the same item, and the selected prompt must survive
    those reads. A mine/ammo request with the same label never passes by label.
    """
    from . import re5_ps3 as R
    if not isinstance(request, dict) or request.get('token') != 'mash:square' \
            or request.get('kind') != R.BTN_STAGE or request.get('label') != R.PICKUP_LABEL:
        return None
    keys = ('token', 'button', 'kind', 'mode', 'label', 'owner', 'target')
    signature = tuple(request.get(key) for key in keys)
    try:
        manager = R.u32(memory, R.S_PLAYER)
        if not R.ptr_ok(manager):
            return None
        index, player = R.player_index(memory), R.player_pointer(memory)
        if index is None or not R.ptr_ok(player) or request.get('owner') != player:
            return None
        current = R.selected_prompt(memory, include_item_pickups=True)
        if not current or tuple(current.get(key) for key in keys) != signature:
            return None
        target = request.get('target')
        if type(target) is not int:
            return None
        observed = [row for row in rows or () if isinstance(row, dict)
                    and type(row.get('id')) is int and row['id'] in HEAL_IDS
                    and row.get('handle') == target and R.ptr_ok(row.get('ptr'))]
        if len(observed) != 1:
            return None
        fresh = [row for row in ground_items(memory) if row.get('handle') == target]
        if len(fresh) != 1 or any(fresh[0].get(key) != observed[0].get(key)
                                  for key in ('ptr', 'handle', 'id')):
            return None
        current = R.selected_prompt(memory, include_item_pickups=True)
        if not current or tuple(current.get(key) for key in keys) != signature \
                or R.u32(memory, R.S_PLAYER) != manager or R.player_index(memory) != index \
                or R.player_pointer(memory) != player:
            return None
        return fresh[0]
    except (ValueError, OSError, TypeError, KeyError, IndexError, struct.error):
        return None
