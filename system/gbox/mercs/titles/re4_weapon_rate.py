"""Lease the Switch RE4 firearm rate to the owned player's per-frame callback.

The host never accelerates a sampled gun animation. The native callback checks
the current routine every frame, and relinquishes only speeds it still owns.
Frame counters below are animation observations, never bullets or hit evidence.
"""
from __future__ import annotations

import math
import struct
import time

from ..native.re4_82c2a04a import code as C
from . import re4_switch as R, re4_weapons as W

MAX_X = 20.0
LEASE_FRAMES = 60
GUN_CLASSES = frozenset((*range(1, 16), 17, 33, 46))


def observation(ctl):
    """Read one bounded coherent native publication; an odd/torn read is unknown."""
    at = ctl.mailbox
    for _ in range(2):
        first = ctl.w(at + C.RATE['sequence'])
        if first & 1:
            continue
        raw = bytes(ctl.rd(at + 0x60, 0x38))
        last = ctl.w(at + C.RATE['sequence'])
        if len(raw) != 0x38 or first != last or first & 1:
            continue
        desired, player_id, owned, applied, obj, obj_id, lease, frames, restores, routine, cls, seq, item = \
            struct.unpack('<fIIfQ8I', raw)
        if seq != first or player_id != ctl.player_id:
            return {'state': 'unknown', 'reason': 'native player observation changed'}
        return {'state': 'native' if seq else 'pending', 'sequence': seq, 'player': ctl.player,
                'player_id': player_id, 'desired_x': desired, 'owned': owned,
                'applied_x': applied if owned & 1 else 1.0, 'object': obj,
                'object_id': obj_id, 'lease_frames': lease, 'scaled_frames': frames,
                'restores': restores, 'routine': list(routine.to_bytes(4, 'little')),
                'weapon_class': cls, 'item': item, 'observed_at': time.time()}
    return {'state': 'unknown', 'reason': 'native publication was in flight'}


def configure(ctl, multiplier, expected):
    """Caller holds the controller lock. Publish only a bounded expiring lease."""
    value = float(multiplier)
    if not math.isfinite(value) or not 1.0 <= value <= MAX_X:
        raise ValueError('firearm rate must be between 1 and 20')
    if ctl.ready() != expected:
        raise RuntimeError('player changed before firearm-rate lease')
    ctl.ensure_attached()
    # Only this appended section is touched; pending calls retain their ABI.
    # Disable before changing ownership, and publish desired last. Native writes
    # neither field, so the callback cannot extend an expired host lease.
    if ctl.w(ctl.mailbox + C.RATE['player_id']) != expected[1]:
        ctl.write(ctl.mailbox + C.RATE['desired'], struct.pack('<f', 1.0))
        ctl.write(ctl.mailbox + C.RATE['lease'], struct.pack('<I', 0))
        ctl.write(ctl.mailbox + C.RATE['player_id'], struct.pack('<I', expected[1]))
    ctl.write(ctl.mailbox + C.RATE['lease'], struct.pack('<I', LEASE_FRAMES if value > 1 else 0))
    ctl.write(ctl.mailbox + C.RATE['desired'], struct.pack('<f', value))
    return observation(ctl)


def release_stopped(ctl):
    """Restore before unhooking, with the process stopped and ownership rechecked."""
    if ctl.mailbox is None:
        return
    at = ctl.mailbox
    raw = bytes(ctl.rd(at + 0x60, 0x20))
    if not any(raw):
        return
    desired, player_id, owned, applied, obj, obj_id, lease = struct.unpack('<fIIfQII', raw)
    ctl.write(at + C.RATE['desired'], struct.pack('<f', 1.0))
    ctl.write(at + C.RATE['lease'], struct.pack('<I', 0))
    if player_id == ctl.player_id and ctl.w(ctl.player + R.U_ID) == player_id:
        speed = struct.pack('<f', applied)
        if owned & 1 and ctl.rd(ctl.player + W.P_MOTION_SPEED, 4) == speed:
            ctl.write(ctl.player + W.P_MOTION_SPEED, struct.pack('<f', 1.0))
        wep = ctl.q(ctl.player + R.PL_WEP)
        current = ctl.q(wep + R.WEP_OBJ) if R.ptr_ok(wep) else None
        if owned & 2 and R.ptr_ok(obj) and current == obj and ctl.w(obj + R.U_ID) == obj_id \
                and ctl.rd(obj + W.OBJ_MOTION_SPEED, 4) == speed:
            ctl.write(obj + W.OBJ_MOTION_SPEED, struct.pack('<f', 1.0))
    ctl.write(at + C.RATE['owned'], struct.pack('<I', 0))
    ctl.write(at + C.RATE['object'], struct.pack('<Q', 0))


def maintain(ad, snap, st):
    """Nonblocking admission alongside rings/equip; lost host ticks expire natively."""
    multiplier = min(MAX_X, max(1.0, float(st.get('fire_rate', 1.0) or 1.0)))
    p = snap.get('player') or {}
    live = (snap.get('game') or {}).get('phase') == 'playing' and not snap.get('operator_active')
    value = multiplier if live else 1.0
    if value <= 1 and not st.get('gun_rate_leased'):
        return
    now = time.monotonic()
    if now < st.get('gun_rate_retry_at', 0):
        return
    try:
        from .. import interventions
        ctl = interventions.native_controller(ad)
        if not ctl.lock.acquire(blocking=False):
            st['gun_rate_state'] = 'busy'
            return
        try:
            row = configure(ctl, value, (p.get('ptr'), p.get('id')))
        finally:
            ctl.lock.release()
        st['gun_rate_leased'] = value > 1
        st['gun_rate_state'] = row['state']
        st['gun_rate_observation'] = row
        st['gun_rate_configured_x'] = value
        st['gun_rate_scaled_frames'] = row.get('scaled_frames', 0)
        st['gun_rate_applied_x'] = row.get('applied_x', 1.0)
        st['gun_rate_restores'] = row.get('restores', 0)
        st.pop('gun_rate_error', None)
    except (ValueError, OSError, RuntimeError, struct.error, TypeError, AttributeError) as exc:
        st['gun_rate_state'] = 'unavailable'
        st['gun_rate_error'] = f'{type(exc).__name__}: {exc}'[:180]
        st['gun_rate_retry_at'] = now + 3.0
