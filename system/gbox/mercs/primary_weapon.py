"""Operator primary weapon: minimum two-minute bot lock, match-long preference."""
from __future__ import annotations

import time

LOCK_SECONDS = 120.0


def install(ad, result, pid, *, clock=time.monotonic):
    if result.get('verified') is not True or result.get('state') != 'confirmed':
        raise ValueError('primary weapon needs verified native equipment')
    ad._merc_primary_weapon = {k: result[k] for k in
        ('item', 'weapon', 'player', 'player_generation', 'weapon_generation')}
    ad._merc_primary_weapon.update(pid=pid, lock_until=clock() + LOCK_SECONDS)


def snapshot(ad, snap, *, clock=time.monotonic):
    chosen = getattr(ad, '_merc_primary_weapon', None)
    if not chosen:
        return None
    player = (snap or {}).get('player') or {}
    try:
        same_process = ad._guest()[0] == chosen['pid']
    except (OSError, ValueError, RuntimeError):
        same_process = False
    if not same_process or (player.get('ptr'), player.get('generation')) != \
            (chosen['player'], chosen['player_generation']) or snap.get('mercenaries_phase') != 1:
        ad._merc_primary_weapon = None
        return None
    remaining = max(0.0, chosen['lock_until'] - clock())
    return {k: chosen[k] for k in ('item', 'weapon', 'player', 'player_generation')} | {
        'locked': remaining > 0, 'lock_remaining_s': round(remaining, 1), 'scope': 'current_match'}


def decision_snapshot(snap):
    """Keep native/UI telemetry intact; limit only the bot's equipment choices.

    Native flash/mines can be injected without changing the held primary. After
    the mandatory lock, existing healing items remain available. Other guns do
    not override the operator's match-long preference.
    """
    primary = snap.get('primary_weapon')
    if not primary:
        return snap
    return snap | {'inventory': [row for row in snap.get('inventory') or ()
        if (row.get('type') == 1 and row.get('item') == primary['item'] and row.get('grid') == 0)
        or (row.get('type') != 1 and not primary['locked'])],
        'preferred_weapon': primary}


def quiescing(stats, snap, *, clock=time.monotonic):
    pending = stats.get('native_weapon_pending') or {}
    player = snap.get('player') or {}
    return bool(clock() < pending.get('until', 0) and
                (player.get('ptr'), player.get('generation')) ==
                (pending.get('player'), pending.get('generation')))


def release_for_handover(stats, snap, hold):
    """Acknowledge only after the engine has sent releases for its held keys."""
    if stats.get('operator_control') or not quiescing(stats, snap):
        return False
    pending = stats['native_weapon_pending']
    hold(set())
    if stats.get('native_weapon_pending') is pending:
        pending['released'] = True
    return True
