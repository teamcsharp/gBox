"""Conservative native RE4 shot evidence; never infer discharge from HP loss.

The pinned Switch image's shotgun handler 3351a0 dispatches r2=2 through
b0a100[2] -> 3355e0, then r3=0 through b0a168[0] -> 336510.
The magnum handler 3270f0 dispatches through b09ce8[2] -> 3274d0,
then b09d68[0] -> 328190. Both fire00 functions call 33b770 before
publishing r3=1. The current handler pointer is the native 1265a28 global.
Killer7 class6 uses 31cc60 -> b09758[2] -> 31cfe0 -> b097c8[0]
-> 31ddd0, which also emits through 33b770 before object state3 and r3=1.

Only an observed same-owner 0->1 transition is accepted. Host polling can
miss fast cycles; a missing observation remains unconfirmed, never invented.
"""
from __future__ import annotations

import math
import struct

from ..native.re4_82c2a04a import code as C

HANDLER = 0x1265A28
HANDLERS = {0x3351A0: 'shotgun', 0x3270F0: 'magnum', 0x31CC60: 'magnum'}
# 31cc60 also handles other guns. Only the measured Killer7 class is admitted;
# sharing a fire routine does not establish another weapon's identity policy.
CLASSES = {0x3351A0: {7, 8, 33}, 0x3270F0: {5, 6, 15}, 0x31CC60: {6}}
PLAYER_CLASSES = tuple(C.TICK_BY_CLASS)
MAX_AGE = .25


def _ptr(n):
    return type(n) is int and 0x10000 <= n < 1 << 48 and n % 4 == 0


def _player_class(memory, base, player, player_id, vtable):
    """Admit a known original, or this reader's exact owned native-hook clone.

    The rate/defense callback replaces the player's vtable. Its pointer alone
    cannot authorize evidence: retain the controller's original class and
    current actor identity, as the main player reader does while attached.
    """
    if vtable-base in PLAYER_CLASSES:
        return vtable-base
    ad = getattr(memory, 'adapter', None) or getattr(memory, 'ad', None) or getattr(memory, '_ad', None)
    ctl = getattr(ad, '_re4_switch_harness', None)
    if (ctl is not None and ctl.base == base and ctl.player == player and ctl.player_id == player_id
            and ctl.original in (base+c for c in PLAYER_CLASSES)
            and ctl.clone_address == vtable and ctl.attached()):
        ctl.check()
        return ctl.original-base
    return None


def read(memory, base, snap, now):
    """Read identity, chain, held item and routine twice; torn reads are unknown."""
    from . import re4_weapons as W
    try:
        player = snap['player']
        p = player['ptr']
        if not _ptr(p) or not math.isfinite(now):
            return None

        def fields():
            header = bytes(memory.rd(p, 12))
            vtable, flags = struct.unpack('<QI', header)
            raw = bytes(memory.rd(p+0x110, 8))
            player_id = struct.unpack_from('<I', raw)[0]
            player_class = _player_class(memory, base, p, player_id, vtable)
            wep = struct.unpack('<Q', memory.rd(p+0x938, 8))[0]
            if not _ptr(wep):
                return None
            obj = struct.unpack('<Q', memory.rd(wep+0x38, 8))[0]
            if not _ptr(obj):
                return None
            obj_id = struct.unpack('<I', memory.rd(obj+0x110, 4))[0]
            item, state = struct.unpack('<HB', memory.rd(obj+0x400, 3))
            cls = bytes(memory.rd(base+W.GAME_OBJ+W.G_CLASS, 1))[0]
            equipped = struct.unpack('<H', memory.rd(base+W.ITEM_MGR+W.M_EQUIPPED_ID, 2))[0]
            handler = struct.unpack('<Q', memory.rd(base+HANDLER, 8))[0]-base
            return (vtable, flags, player_id, wep, obj, obj_id, item, state, cls, equipped, handler, tuple(raw[4:]), player_class)

        a = fields()
        if a is None or fields() != a:
            return None
        vt, flags, pid, wep, obj, oid, item, state, cls, equipped, handler, routine, player_class = a
        family = HANDLERS.get(handler)
        if (player_class is None or flags & 0x201 != 1 or player.get('id') != pid
                or family is None or cls not in CLASSES[handler] or W.CLASS_OF.get(item) != cls or equipped != item
                or (snap.get('aim') or {}).get('obj') != obj):
            return None
        return {'identity': (p, pid, wep, obj, oid, item, cls, handler), 'routine': routine,
                'at': now, 'object_state': state, 'family': family, 'source': 'native_post_emission_step'}
    except (KeyError, TypeError, ValueError, OSError, RuntimeError, AttributeError, OverflowError, IndexError, struct.error):
        return None


def identity(snap, now):
    row = snap.get('fire_witness')
    try:
        return tuple(row['identity']) if 0 <= now-row['at'] <= MAX_AGE else None
    except (KeyError, TypeError, ValueError):
        return None


def edge(previous, current, now):
    """Evidence of emission completion, not an impact or hit counter."""
    try:
        return (previous['identity'] == current['identity']
                and 0 < current['at']-previous['at'] <= MAX_AGE
                and 0 <= now-current['at'] <= MAX_AGE
                and tuple(previous['routine']) == (0, 6, 2, 0)
                and tuple(current['routine']) == (0, 6, 2, 1)
                and current['object_state'] == 3)
    except (KeyError, TypeError, ValueError):
        return False


def unconfounded(bot, snap, now):
    """Do not learn gun aim across rings, throws, or live owned explosives.

    Event values are compared as opaque identities: ring clocks mix wall and
    monotonic time. Only this helper's own quiet-window clock is subtracted.
    """
    state = bot.__dict__.setdefault('_aim_damage_sources', {'seen': {}, 'until': now})
    st = bot.stats
    for key in ('ring_last_at', 'mine_ring_last_at', 'grenade_throws', 'mine_darts_initiated'):
        value = st.get(key)
        if value not in (None, 0) and value != state['seen'].get(key):
            state['until'] = now+6.
        state['seen'][key] = value
    explosive = bool(snap.get('own_hazards') or snap.get('ground_mines') or st.get('mine_darts_live')
                     or bot.__dict__.get('_mine_ring') or bot.__dict__.get('_uc_throw'))
    if explosive:
        state['until'] = now+6.
    return now >= state['until'] and not explosive


def observe(bot, snap, now, core):
    clear = unconfounded(bot, snap, now)
    previous = bot.__dict__.get('_native_fire_seen')
    current = snap.get('fire_witness')
    bot.__dict__['_native_fire_seen'] = current
    if not edge(previous, current, now):
        return
    bot.stats['native_discharge_observations'] = bot.stats.get('native_discharge_observations', 0)+1
    matched = core.confirm_discharge(now, tuple(current['identity']), snap.get('enemies') or (),
                                    unconfounded=clear, source='native_post_emission_step')
    bot.stats['native_discharge_last'] = {'at': now, 'weapon': current['identity'][5],
        'family': current['family'], 'matched_request': bool(matched), 'unconfounded': clear,
        'source': 'native_post_emission_step', 'impact_confirmed': False}
