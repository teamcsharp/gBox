"""A life-scoped operator weapon selection, lasting exactly three minutes."""
from __future__ import annotations

import time
import threading

LOCK_SECONDS = 180.0
_LOCK = threading.RLock()
RELOAD_KEEP = ('_LOCK',)


def _clear(ad, chosen):
    with _LOCK:
        if getattr(ad, '_merc_primary_weapon', None) is chosen:
            ad._merc_primary_weapon = None


def install(ad, result, pid, *, clock=time.monotonic):
    if result.get('verified') is not True or result.get('state') != 'confirmed':
        raise ValueError('primary weapon needs verified native equipment')
    chosen = {k: result[k] for k in
        ('item', 'weapon', 'player', 'player_generation', 'weapon_generation')}
    chosen.update(pid=pid, lock_until=clock() + LOCK_SECONDS)
    with _LOCK:
        ad._merc_primary_weapon = chosen  # publish a complete record to the bot thread


def record(stats, primary):
    """The general telemetry publisher sends scalar stats; keep the lock visible.

    Retain the structured local state too, for the bot and in-process tools.
    A title/life ending must clear the previous weapon's reported countdown.
    """
    stats['primary_weapon'] = primary
    stats.update(primary_weapon_item=(primary or {}).get('item', 0),
                 primary_weapon_name=(primary or {}).get('weapon', ''),
                 primary_weapon_locked=bool((primary or {}).get('locked')),
                 primary_weapon_lock_remaining_s=(primary or {}).get('lock_remaining_s', 0))


def snapshot(ad, snap, *, clock=time.monotonic, pid=None):
    chosen = getattr(ad, '_merc_primary_weapon', None)
    if not chosen:
        return None
    player = (snap or {}).get('player') or {}
    try:
        same_process = (ad._guest()[0] if pid is None else pid) == chosen['pid']
    except (AttributeError, OSError, ValueError, RuntimeError):
        same_process = False
    if not same_process or (player.get('ptr'), player.get('generation')) != \
            (chosen['player'], chosen['player_generation']) or snap.get('mercenaries_phase') != 1:
        _clear(ad, chosen)
        return None
    remaining = max(0.0, chosen['lock_until'] - clock())
    if remaining <= 0:
        _clear(ad, chosen)
        return None
    # A known empty magazine must not hide the other usable guns. Unknown
    # counts are not proof of depletion; native infinite-ammo flags can also
    # permit fire without spending a round (RE5).
    rounds = None
    row = next((r for r in snap.get('inventory') or ()
                if r.get('type') == 1 and r.get('item') == chosen['item']), None)
    missing = isinstance(snap.get('inventory'), list) and row is None
    if row is not None:
        rounds = row.get('rounds')
    else:
        slot = (player.get('guns') or {}).get(0x100 + chosen['item'])
        if isinstance(player.get('guns'), dict):
            missing = slot is None
        if slot is not None:
            rounds = (player.get('gun_ammo') or {}).get(slot)
    empty = type(rounds) in (int, float) and rounds <= 0 and snap.get('infinite_ammo') is not True
    return {k: chosen[k] for k in ('item', 'weapon', 'player', 'player_generation')} | {
        'locked': True, 'lock_remaining_s': round(remaining, 1), 'scope': 'three_minutes',
        'usable': not (empty or missing),
        'fallback_reason': ('selected weapon is unavailable in current inventory' if missing else
                            'selected weapon is out of ammo' if empty else '')}


def decision_snapshot(snap):
    """Keep native/UI telemetry intact; limit only the bot's equipment choices.

    Healing remains available and the selected gun resumes afterward. A known
    empty selection temporarily releases the restriction so combat can continue.
    """
    primary = snap.get('primary_weapon')
    if not primary:
        return snap
    if primary.get('usable') is False:
        return snap | {'primary_weapon': None, 'preferred_weapon': None}
    return snap | {'inventory': [row for row in snap.get('inventory') or ()
        if (row.get('type') == 1 and row.get('item') == primary['item'])
        or row.get('type') != 1],
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
    if hold(set()) is False:
        return False
    if stats.get('native_weapon_pending') is pending:
        pending['released'] = True
    return True
