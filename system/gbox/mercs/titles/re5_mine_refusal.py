"""Read-only admission proof for a definitely unactivated floor-refused batch.

An uncertain native call, partial placement, recycled actor, or attached/pending
mailbox never becomes a retry opportunity. The next placement independently
revalidates every pooled actor before any transform or lifecycle call.
"""
import struct
import time

MAX_READ_S = .15
SAFE_CALLS = frozenset(('0x7e51a0', '0x793ab0'))


def candidate(receipt, requested):
    """Only the explicit floor-before-activation refusal can be reconciled."""
    if (not isinstance(receipt, dict) or receipt.get('state') != 'refused'
            or receipt.get('floor_refused') is not True or receipt.get('verified') is not False
            or type(requested) is not int or requested not in (1, 5)
            or receipt.get('requested') != requested
            or any(type(receipt.get(k)) is not int or receipt[k] != 0 for k in ('placed', 'armed', 'triggered'))
            or receipt.get('mines') != [] or receipt.get('detach_error')):
        return False
    rows, index = receipt.get('prepared'), receipt.get('refused_index')
    if (not isinstance(rows, list) or len(rows) != requested
            or type(index) is not int or not 0 <= index < requested):
        return False
    identities = set()
    for i, row in enumerate(rows):
        if (not isinstance(row, dict) or row.get('index') != i
                or type(row.get('unit')) is not int or type(row.get('generation')) is not int
                or row.get('resources_ready') is not True
                or any(row.get(k) for k in ('configured', 'state_accepted', 'active', 'armed',
                                          'armed_observed', 'trigger_observed'))
                or not isinstance(row.get('calls_completed', []), list)
                or any(k not in SAFE_CALLS for k in row.get('calls_completed', []))):
            return False
        identities.add((row['unit'], row['generation']))
    return len(identities) == requested


class _Unsafe(Exception):
    pass


class _Paused(Exception):
    pass


def verify(memory, owner, receipt, *, allowed=lambda: True):
    """Return detached/no-collision evidence; never call ready()/recover/write."""
    from . import re5_switch as R, re5_proximity_native as native
    from .re5_switch_native import Unavailable
    if not candidate(receipt, receipt.get('requested') if isinstance(receipt, dict) else None):
        return {'state': 'unsafe', 'reason': 'receipt does not prove a floor-before-activation refusal', 'verified_actors': 0}
    ctl = getattr(getattr(memory, 'adapter', None), '_re5_native_flash', None)
    if ctl is None or not hasattr(ctl, 'lock'):
        return {'state': 'unknown', 'reason': 'native controller unavailable', 'verified_actors': 0}
    if not ctl.lock.acquire(blocking=False):
        return {'state': 'busy', 'reason': 'native controller owned by another operation', 'verified_actors': 0}
    started = time.monotonic()
    rows = receipt['prepared']
    expected = owner[1:]
    try:
        def build():
            try:
                ctl.check_build()
            except Unavailable as exc:
                raise _Unsafe(str(exc)) from exc

        def admission():
            if not allowed() or getattr(ctl.ad, 'paused', False):
                raise _Paused('live automatic admission paused; full inactive proof must be repeated')

        build()
        admission()
        if getattr(ctl, 'failed', True):
            raise _Unsafe('native controller is failed')
        if (getattr(ctl, 'player', None), getattr(ctl, 'generation', None)) != expected:
            raise _Unsafe('native player life changed')
        try:
            ctl.validate_heap()
        except Unavailable as exc:
            raise _Unsafe(str(exc)) from exc

        def gate():
            admission()
            pool = getattr(ctl, '_proximity_prepared', None)
            if (not isinstance(pool, dict) or pool.get('owner') != expected
                    or not isinstance(pool.get('rows'), list)):
                raise _Unsafe('inactive native pool owner changed')
            pool_ids = [(r.get('unit'), r.get('generation')) for r in pool['rows'] if isinstance(r, dict)]
            if (len(pool_ids) != len(pool['rows']) or len(pool_ids) > 8
                    or any(pool_ids.count((r['unit'], r['generation'])) != 1 for r in rows)):
                raise _Unsafe('prepared actors are no longer uniquely retained by the inactive pool')
            player, generation = expected
            gs = R.game_sys(ctl, ctl.base)
            if (getattr(ctl, 'failed', True) or getattr(ctl, 'ring_projectile_pending', None)
                    or ctl.q(ctl.base+R.S_PLAYER) != ctl.sp or ctl.q(ctl.sp+R.P_FIRST) != player
                    or ctl.q(player+0x1A00) != generation or ctl.q(player) != ctl.original
                    or ctl.q(ctl.heap+0x680) != ctl.original or ctl.q(ctl.heap+0x690) != player
                    or ctl.q(ctl.heap+0x698) != generation or ctl.w(ctl.heap+0x6A8) not in (0, 3)
                    or not R.ptr_ok(gs) or ctl.w(gs+R.GS_PHASE) != R.PHASE_PLAYING
                    or struct.unpack('<h', ctl.rd(player+R.P_HP, 2))[0] <= R.DYING_HP):
                raise _Unsafe('native handoff, player or live phase is not safely detached')
            if time.monotonic()-started > MAX_READ_S:
                raise TimeoutError('inactive proof exceeded freshness budget')

        def actor(row):
            unit, born = row['unit'], row['generation']
            identity = (ctl.base+native.VTABLE, born, expected[0])
            observed = lambda: (ctl.q(unit), ctl.q(unit+0x1A00), ctl.q(unit+0x1A10))
            if observed() != identity:
                raise _Unsafe('prepared native allocation identity changed')
            primary, proximity = ctl.q(unit+0x2710), ctl.q(unit+0x28C8)
            if (ctl.rd(unit+0x27B9, 1) != b'\0' or ctl.rd(unit+0x28C1, 1) != b'\0'
                    or ctl.q(unit+0x48) != 0 or not R.ptr_ok(primary) or not R.ptr_ok(proximity)
                    or ctl.rd(primary+0x14, 1) != b'\0' or ctl.rd(proximity+0x14, 1) != b'\0'
                    or observed() != identity):
                raise _Unsafe('prepared mine is active, attached, triggered or collision state is unknown')

        gate()
        for _ in range(2):
            for row in rows:
                actor(row)
            gate()
        build()
        gate()
        return {'state': 'verified_inactive', 'reason': 'complete owned batch remains inactive and detached',
                'verified_actors': len(rows), 'player': expected[0], 'generation': expected[1],
                'mailbox_state': ctl.w(ctl.heap+0x6A8), 'elapsed_ms': round((time.monotonic()-started)*1000, 3)}
    except _Unsafe as exc:
        return {'state': 'unsafe', 'reason': str(exc), 'verified_actors': 0}
    except _Paused as exc:
        return {'state': 'paused', 'reason': str(exc), 'verified_actors': 0}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, struct.error, RuntimeError) as exc:
        return {'state': 'unknown', 'reason': f'{type(exc).__name__}: {exc}'[:200], 'verified_actors': 0}
    finally:
        ctl.lock.release()
