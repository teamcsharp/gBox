"""RE5 EBFFDB22 direct proximity mines, following native player drop 7B9340.

Research addresses are main-relative (the saved Ghidra project adds 0x100000).
Factory -> resource readiness -> dropped-item reset -> inactive ground validation
for every requested point -> native configure -> state 3. No equipment,
inventory, input or detonation writes.
Live acceptance is deliberately separate from a successful native-call return.
"""
import hashlib
import math
import struct
import time
from contextlib import contextmanager

DTI, VTABLE, ITEM = 0x1D715A8, 0x1C5E478, 0x10A
RADIUS_CM, RING_COUNT = 152.4, 5
COUNTS = (1, RING_COUNT, 8)  # retain the earlier eight-mine research request
# Placement policy, not a claimed blast height: match the existing escape
# floor lookup's 61cm tolerance and refuse distant floors before activation.
FLOOR_SLOP_CM = 61.0
GROUND, GROUND_SIZE = 0x793AB0, 0x108
GROUND_SHA256 = '9e9c111b224aa84d19a69bdaff46128beb6bf69ca50d6dfefb4cdfa246dab347'
# 2026-11-13: live single drops and five-mine ring, native armed volumes read
# back with the Hydra still equipped. See docs/research/re5-automine.md.
LIVE_VERIFIED = True
FUNCTIONS = {
    0x7E51A0: bytes.fromhex('f30f1ef8fd7b01a9fd430091f30300aa'),
    0x60D6D0: bytes.fromhex('f85fbca9f65701a9f44f02a9fd7b03a9'),
    0x790FE0: bytes.fromhex('f70f1cf8f65701a9f44f02a9fd7b03a9'),
    0x793AB0: bytes.fromhex('ffc302d1e84300fdf44f09a9fd7b0aa9'),
}


class _FloorRefused(Exception):
    """Known inactive batch, with no activation submitted."""


def points(center, count):
    if type(count) is not int or count not in COUNTS:
        raise ValueError('one mine, five mines, or the legacy eight-mine ring')
    if len(center) != 3 or not all(math.isfinite(v) for v in center):
        raise ValueError('invalid mine center')
    if count == 1:
        return [tuple(center)]
    x, y, z = center
    return [(x + RADIUS_CM*math.cos(i*math.tau/count), y, z + RADIUS_CM*math.sin(i*math.tau/count))
            for i in range(count)]


@contextmanager
def mine_lock(lock, wait):
    if not lock.acquire(blocking=wait):
        from .re5_switch_native import Unavailable
        raise Unavailable('native controller busy; mine placement was not queued')
    try:
        yield
    finally:
        lock.release()


def place(ctl, count=1, *, allow_unverified=False, allowed=None, expected=None, wait_for_lock=True,
          center=None, on_deployed=None):
    from . import re5_switch as R
    from .re5_switch_native import Unavailable, Uncertain, AllocationLost
    if not LIVE_VERIFIED and not allow_unverified:
        raise Unavailable('RE5 direct proximity-mine placement is awaiting live validation')
    if type(count) is not int or count not in COUNTS:
        raise ValueError('one mine, five mines, or the legacy eight-mine ring')
    if center is not None:
        if (not isinstance(center, (tuple, list)) or len(center) != 3
                or not all(type(v) in (int, float) and math.isfinite(v) for v in center)):
            raise ValueError('mine center requires three finite coordinates')
        center = tuple(center)
    started = time.monotonic()
    ctl.ready()
    with mine_lock(ctl.lock, wait_for_lock):
        player, generation = ctl.ready()
        if expected is not None and tuple(expected) != (player, generation):
            raise AllocationLost('mine request player changed before execution')
        ctl.sp = ctl.q(ctl.base + R.S_PLAYER)
        ctl.player, ctl.generation = player, generation
        ctl.original = ctl.q(player)
        prepared, deployed = [], []
        receipt = {'op': 'proximity_mine_ring' if count > 1 else 'proximity_mine_drop',
                   'effect': 'native_re5_proximity_mines', 'requested': count, 'placed': 0, 'armed': 0,
                   'radius_cm': RADIUS_CM if count > 1 else 0, 'inventory_consumed': False,
                   'player_generation': generation, 'probe': not LIVE_VERIFIED,
                   'mines': deployed, 'prepared': prepared}

        def current():
            ctl.check()
            if time.monotonic() - started > 22:
                raise Unavailable('mine placement deadline reached; not replayed')
            if allowed is not None and not allowed():
                raise Unavailable('mine request expired or round changed')
            if ctl.ready() != (player, generation):
                raise AllocationLost('mine request player changed')

        def actor(row):
            current()
            unit = row['unit']
            if ctl.q(unit) != ctl.base + VTABLE or ctl.q(unit + 0x1A00) != row['generation'] \
                    or ctl.q(unit + 0x1A10) != player:
                raise AllocationLost('proximity-mine allocation changed; not replayed')
            return unit

        def invoke(row, off, *args):
            unit = actor(row)
            result = ctl.call(off, unit, *args, timeout=2.5)
            row.setdefault('calls_completed', []).append(hex(off))
            return result

        def inactive(row):
            unit = actor(row)
            primary = ctl.q(unit + 0x2710)
            if (ctl.rd(unit + 0x27B9, 1) != b'\0' or ctl.rd(unit + 0x28C1, 1) != b'\0'
                    or ctl.q(unit + 0x48) != 0
                    or (primary and (not R.ptr_ok(primary) or ctl.rd(primary + 0x14, 1) != b'\0'))):
                raise Uncertain('prepared mine is active or attached; placement refused')
            return actor(row)  # reject allocation recycling during the flag/attachment reads

        try:
            current()
            if ctl.pair() == 'pre_class':
                raise Unavailable('mine creation needs the class-aware native factory on a fresh title session')
            for off, expected in FUNCTIONS.items():
                if ctl.rd(ctl.base + off, len(expected)) != expected:
                    raise Unavailable(f'RE5 mine function mismatch at {off:#x}')
            # The complete function must preserve the raycast W0 through RET;
            # a prologue match cannot establish that return-value contract.
            if hashlib.sha256(ctl.rd(ctl.base + GROUND, GROUND_SIZE)).hexdigest() != GROUND_SHA256:
                raise Unavailable('RE5 mine ground-hit return contract mismatch')
            # Bound both manual and future automatic placement independently of inventory.
            existing = R.ground_mines(ctl, ctl.base)
            if len(existing) + count > 40:
                raise Unavailable('active proximity-mine limit reached')
            receipt['weapon_before'] = ctl.current_weapon()
            receipt['hp_before'] = struct.unpack('<h', ctl.rd(player + R.P_HP, 2))[0]
            receipt['player_pos_before'] = list(struct.unpack('<3f', ctl.rd(player + R.P_POS, 12)))
            ctl.attach()
            # A rejected floor must not leak another batch of inactive native
            # allocations on each retry. Retain at most one bounded batch,
            # scoped to this exact player life; never reuse an uncertain actor.
            pool = getattr(ctl, '_proximity_prepared', None)
            if not isinstance(pool, dict) or pool.get('owner') != (player, generation):
                pool = {'owner': (player, generation), 'rows': []}
                ctl._proximity_prepared = pool
            for i in range(count):
                current()
                if pool['rows']:
                    cached = pool['rows'].pop()
                    unit = inactive(cached)
                    row = {'index': i, 'unit': unit, 'generation': cached['generation'], 'reused_inactive': True}
                else:
                    unit = ctl.call(0x118E820, player, generation, ctl.base + DTI, timeout=2.5)
                    if not R.ptr_ok(unit):
                        raise Unavailable('native proximity-mine factory refused allocation')
                    row = {'index': i, 'unit': unit, 'generation': ctl.q(unit + 0x1A00)}
                prepared.append(row)

                def loaded():
                    inactive(row)
                    return (ctl.rd(unit + 0x1B88, 1) == b'\1' and ctl.w(unit + 0x1B28) >= 4
                            and R.ptr_ok(ctl.q(unit + 0x1FB8)) and R.ptr_ok(ctl.q(unit + 0x1D38))
                            and ctl.w(unit + 0x1D5C) > 0)
                ctl.wait(loaded, timeout=5)
                row['resources_ready'] = True
            current()
            if center is None:
                center = struct.unpack('<3f', ctl.rd(player + R.P_POS, 12))
                center_source = 'commit_start_observation'
            else:
                center_source = 'request_event_observation'
            receipt.update(center=list(center), center_source=center_source)
            commit = time.monotonic()
            for row, pos in zip(prepared, points(center, count)):
                unit = inactive(row)
                # Inactive units only; native activation and transform processing follow.
                raw = struct.pack('<4f', *pos, 0)
                ctl.write(unit + 0x60, raw)
                ctl.write(unit + 0x2680, raw)
                row['requested_pos'] = list(pos)
                invoke(row, 0x7E51A0)
                inactive(row)
                # 793AB0's native raycast preserves W0 through its epilogue.
                # It only changes Y on a hit. Run it while the mine is still
                # inactive, so a lower floor can never become a live hazard.
                hit = invoke(row, GROUND, 1) & 0xFFFFFFFF
                inactive(row)
                projected = struct.unpack('<3f', ctl.rd(unit + 0x60, 12))
                row.update(ground_hit=bool(hit), ground_pos=list(projected),
                           grounding='native_raycast_before_activation', floor_slop_cm=FLOOR_SLOP_CM)
                floor_ok = (hit and all(math.isfinite(v) for v in projected)
                            and abs(projected[1]-pos[1]) <= FLOOR_SLOP_CM
                            and math.hypot(projected[0]-pos[0], projected[2]-pos[2]) <= 1.)
                if not floor_ok:
                    # No configure/state-3 call has been made for this batch.
                    # Recheck every identity before retaining safe inactive units.
                    for item in prepared:
                        inactive(item)
                    pool['rows'].extend({'unit': item['unit'], 'generation': item['generation']}
                                        for item in prepared)
                    receipt.update(state='refused', verified=False, floor_refused=True,
                                   reason='native mine floor missed, moved sideways, or differs from requested floor',
                                   refused_index=row['index'])
                    break
                row['floor_validated'] = True
                row['pos'] = list(projected)
            else:
                receipt['all_floors_validated'] = True
            if receipt.get('floor_refused'):
                raise _FloorRefused(receipt['reason'])
            # All ring members are checked before the first active mine exists.
            for row in prepared:
                unit = inactive(row)
                observed = struct.unpack('<3f', ctl.rd(unit + 0x60, 12))
                if any(not math.isfinite(v) for v in observed) or math.dist(observed, row['ground_pos']) > 1.:
                    raise Uncertain('inactive mine moved after floor validation; activation refused')
                # The third native argument sets +273F. The put action's first
                # tick (91E6D0) uses it to enable the primary collision volume.
                # Passing zero leaves a visible mine that cannot detonate even
                # when its separate proximity volume detects an enemy.
                invoke(row, 0x60D6D0, 1, 1, ITEM, 1)
                row['configured'] = True
                if invoke(row, 0x790FE0, 3, 0, 0, 0xFFFFFFFF, 0) != 1:
                    raise Uncertain('native mine drop state refused; activation not replayed')
                row['state_accepted'] = True
                row['pos'] = list(struct.unpack('<3f', ctl.rd(unit + 0x60, 12)))
                row['activation_elapsed_ms'] = round(1000*(time.monotonic()-commit), 1)
                deployed.append(row)
                # Navigation must leave immediately, not wait for the arming
                # timer. Publish a physical hazard without claiming it is armed.
                if on_deployed is not None:
                    try:
                        on_deployed({'unit': unit, 'generation': row['generation'],
                                     'pos': tuple(row['pos']), 'center': tuple(center), 'active': True,
                                     'armed_observed': False})
                    except Exception as exc:
                        row['hazard_notice_error'] = str(exc)[:160]
            receipt['placement_span_ms'] = round(1000*(time.monotonic()-commit), 1)
            # Read the game's own arming lifecycle, without setting a trigger flag.
            def armed():
                pending = False
                for row in deployed:
                    if row.get('trigger_observed'):
                        continue  # native destruction after an observed trigger is expected
                    unit = actor(row)
                    row['trigger_observed'] = ctl.rd(unit + 0x28C1, 1) == b'\1'
                    if row['trigger_observed']:
                        row['outcome'] = 'native_explosion_latch_observed'
                        continue
                    volume = ctl.q(unit + 0x28C8)
                    row['volume'] = volume
                    primary = ctl.q(unit + 0x2710)
                    row['primary_volume'] = primary
                    row['arming_timer'] = struct.unpack('<f', ctl.rd(unit + 0x2890, 4))[0]
                    if not math.isfinite(row['arming_timer']):
                        raise Uncertain('mine arming timer is not finite')
                    row['proximity_enabled'] = bool(R.ptr_ok(volume) and ctl.rd(volume + 0x14, 1) == b'\1')
                    row['primary_enabled'] = bool(R.ptr_ok(primary) and ctl.rd(primary + 0x14, 1) == b'\1')
                    row['armed'] = row['proximity_enabled'] and row['primary_enabled']
                    row['armed_observed'] = row.get('armed_observed', False) or row['armed']
                    row['active'] = ctl.rd(unit + 0x27B9, 1) == b'\1'
                    row['pos'] = list(struct.unpack('<3f', ctl.rd(unit + 0x60, 12)))
                    row['outcome'] = 'armed' if row['armed'] else 'arming'
                    pending |= not (row['active'] and row['armed'])
                return not pending
            ctl.wait(armed, timeout=6)
            receipt['weapon_after'] = ctl.current_weapon()
            receipt['weapon_unchanged'] = receipt['weapon_after'] == receipt['weapon_before']
            receipt['hp_after'] = struct.unpack('<h', ctl.rd(player + R.P_HP, 2))[0]
            receipt['player_pos_after'] = list(struct.unpack('<3f', ctl.rd(player + R.P_POS, 12)))
            receipt['hp_loss_observed'] = receipt['hp_before'] - receipt['hp_after']
            receipt['damage_attribution'] = 'unattributed; enemies may attack during native placement'
            receipt.update(state='confirmed', verified=LIVE_VERIFIED)
        except _FloorRefused:
            pass  # explicit refused receipt; inactive allocations are bounded and reusable
        except Exception as exc:
            if prepared:
                ctl._fail(exc, recoverable=True)
            receipt.update(state='uncertain' if prepared else 'failed', verified=False, reason=str(exc)[:300])
        finally:
            try:
                ctl.detach_completed()
            except Exception as exc:
                receipt.update(state='uncertain', verified=False, detach_error=str(exc)[:300])
        receipt.update(placed=len(deployed), armed=sum(bool(r.get('armed_observed')) for r in deployed),
                       triggered=sum(bool(r.get('trigger_observed')) for r in deployed),
                       elapsed_ms=round(1000*(time.monotonic()-started), 1))
        return receipt
