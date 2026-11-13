"""RE5 EBFFDB22 direct proximity mines, following native player drop 7B9340.

Research addresses are main-relative (the saved Ghidra project adds 0x100000).
Factory -> resource readiness -> dropped-item reset -> native configure ->
state 3 -> detach/ground. No equipment, inventory, input or detonation writes.
Live acceptance is deliberately separate from a successful native-call return.
"""
import math
import struct
import time

DTI, VTABLE, ITEM = 0x1D715A8, 0x1C5E478, 0x10A
RADIUS_CM, RING_COUNT = 152.4, 8
LIVE_VERIFIED = False
FUNCTIONS = {
    0x7E51A0: bytes.fromhex('f30f1ef8fd7b01a9fd430091f30300aa'),
    0x60D6D0: bytes.fromhex('f85fbca9f65701a9f44f02a9fd7b03a9'),
    0x790FE0: bytes.fromhex('f70f1cf8f65701a9f44f02a9fd7b03a9'),
    0x793AB0: bytes.fromhex('ffc302d1e84300fdf44f09a9fd7b0aa9'),
}


def points(center, count):
    if count not in (1, RING_COUNT):
        raise ValueError('one mine or the eight-mine ring')
    if len(center) != 3 or not all(math.isfinite(v) for v in center):
        raise ValueError('invalid mine center')
    if count == 1:
        return [tuple(center)]
    x, y, z = center
    return [(x + RADIUS_CM*math.cos(i*math.tau/count), y, z + RADIUS_CM*math.sin(i*math.tau/count))
            for i in range(count)]


def place(ctl, count=1, *, allow_unverified=False, allowed=None):
    from . import re5_switch as R
    from .re5_switch_native import Unavailable, Uncertain, AllocationLost
    if not LIVE_VERIFIED and not allow_unverified:
        raise Unavailable('RE5 direct proximity-mine placement is awaiting live validation')
    if type(count) is not int or count not in (1, RING_COUNT):
        raise ValueError('one mine or the eight-mine ring')
    ctl.ready()
    with ctl.lock:
        player, generation = ctl.ready()
        ctl.sp = ctl.q(ctl.base + R.S_PLAYER)
        ctl.player, ctl.generation = player, generation
        ctl.original = ctl.q(player)
        prepared, deployed = [], []
        started = time.monotonic()
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

        try:
            current()
            if ctl.pair() == 'pre_class':
                raise Unavailable('mine creation needs the class-aware native factory on a fresh title session')
            for off, expected in FUNCTIONS.items():
                if ctl.rd(ctl.base + off, len(expected)) != expected:
                    raise Unavailable(f'RE5 mine function mismatch at {off:#x}')
            # Bound both manual and future automatic placement independently of inventory.
            existing = R.ground_mines(ctl, ctl.base)
            if len(existing) + count > 40:
                raise Unavailable('active proximity-mine limit reached')
            receipt['weapon_before'] = ctl.current_weapon()
            ctl.attach()
            for i in range(count):
                current()
                unit = ctl.call(0x118E820, player, generation, DTI, timeout=2.5)
                if not R.ptr_ok(unit):
                    raise Unavailable('native proximity-mine factory refused allocation')
                row = {'index': i, 'unit': unit, 'generation': ctl.q(unit + 0x1A00)}
                prepared.append(row)

                def loaded():
                    actor(row)
                    if ctl.rd(unit + 0x27B9, 1) != b'\0' or ctl.rd(unit + 0x28C1, 1) != b'\0':
                        raise Uncertain('prepared mine became active before placement')
                    return (ctl.rd(unit + 0x1B88, 1) == b'\1' and ctl.w(unit + 0x1B28) >= 4
                            and R.ptr_ok(ctl.q(unit + 0x1FB8)) and R.ptr_ok(ctl.q(unit + 0x1D38))
                            and ctl.w(unit + 0x1D5C) > 0)
                ctl.wait(loaded, timeout=5)
                row['resources_ready'] = True
            current()
            center = struct.unpack('<3f', ctl.rd(player + R.P_POS, 12))
            receipt.update(center=list(center), center_source='commit_start_observation')
            commit = time.monotonic()
            for row, pos in zip(prepared, points(center, count)):
                unit = actor(row)
                if ctl.rd(unit + 0x27B9, 1) != b'\0' or ctl.rd(unit + 0x28C1, 1) != b'\0':
                    raise Uncertain('prepared mine became active; transform not written')
                # Inactive units only; native activation and transform processing follow.
                raw = struct.pack('<4f', *pos, 0)
                ctl.write(unit + 0x60, raw)
                ctl.write(unit + 0x2680, raw)
                row['requested_pos'] = list(pos)
                invoke(row, 0x7E51A0)
                invoke(row, 0x60D6D0, 1, 0, ITEM, 1)
                row['configured'] = True
                if invoke(row, 0x790FE0, 3, 0, 0, 0xFFFFFFFF, 0) != 1:
                    raise Uncertain('native mine drop state refused; activation not replayed')
                row['state_accepted'] = True
                invoke(row, 0x793AB0, 1)
                row['grounding'] = 'native_raycast_requested'
                row['pos'] = list(struct.unpack('<3f', ctl.rd(unit + 0x60, 12)))
                row['activation_elapsed_ms'] = round(1000*(time.monotonic()-commit), 1)
                deployed.append(row)
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
                    row['arming_timer'] = struct.unpack('<f', ctl.rd(unit + 0x2890, 4))[0]
                    if not math.isfinite(row['arming_timer']):
                        raise Uncertain('mine arming timer is not finite')
                    row['armed'] = bool(R.ptr_ok(volume) and ctl.rd(volume + 0x14, 1) == b'\1')
                    row['armed_observed'] = row.get('armed_observed', False) or row['armed']
                    row['active'] = ctl.rd(unit + 0x27B9, 1) == b'\1'
                    row['outcome'] = 'armed' if row['armed'] else 'arming'
                    pending |= not (row['active'] and row['armed'])
                return not pending
            ctl.wait(armed, timeout=6)
            receipt['weapon_after'] = ctl.current_weapon()
            receipt['weapon_unchanged'] = receipt['weapon_after'] == receipt['weapon_before']
            receipt.update(state='confirmed', verified=LIVE_VERIFIED)
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
