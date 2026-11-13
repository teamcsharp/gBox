import hashlib
import math
import struct

import pytest

from gbox.mercs.titles import re5_proximity_native as M
from gbox.mercs.titles import re5_switch_native as N
from test_re5_switch_native import controller


@pytest.fixture(autouse=True)
def probe_mode(monkeypatch):
    # Exercise the refusal/probe branch even after the pinned build is verified.
    monkeypatch.setattr(M, 'LIVE_VERIFIED', False)


def mine_controller(monkeypatch):
    ctl = controller()
    ctl.ready = lambda: (ctl.player, ctl.generation)
    ctl.pair = lambda: 'class'
    ctl.current_weapon = lambda: 25
    ctl.attach = lambda: None
    ctl.detach_completed = lambda: None
    ctl.native_calls = []
    ctl.units = []
    ctl.put(ctl.player + N.R.P_POS, struct.pack('<3f', 100, 200, 300))
    for off, raw in M.FUNCTIONS.items():
        ctl.put(ctl.base + off, raw)
    # Controller tests use synthetic memory; the separate offline ARM64 suite
    # verifies this hash/return contract against the pinned Spark-local ELF.
    monkeypatch.setattr(M, 'GROUND_SHA256', hashlib.sha256(ctl.rd(ctl.base + M.GROUND, M.GROUND_SIZE)).hexdigest())
    monkeypatch.setattr(N.R, 'ground_mines', lambda *_: [])

    def call(off, *args, **_):
        ctl.native_calls.append((off, args))
        if off == 0x118E820:
            assert args == (ctl.player, ctl.generation, ctl.base + M.DTI)
            unit = 0x230000000 + len(ctl.units) * 0x10000
            ctl.units.append(unit)
            for at, value in ((unit, ctl.base + M.VTABLE), (unit + 0x1A00, len(ctl.units)),
                              (unit + 0x1A10, ctl.player), (unit + 0x1FB8, 0x240000000),
                              (unit + 0x1D38, 0x240000000), (unit + 0x28C8, unit + 0x3000),
                              (unit + 0x2710, unit + 0x4000)):
                ctl.put(at, struct.pack('<Q', value))
            ctl.put(unit + 0x1B28, struct.pack('<I', 29))
            ctl.put(unit + 0x1B88, b'\1')
            ctl.put(unit + 0x1D5C, struct.pack('<I', 1))
            return unit
        unit = args[0]
        if off == 0x60D6D0:
            ctl.put(unit + 0x27B9, b'\1')
            ctl.put(unit + 0x4014, b'\0')
            ctl.put(unit + 0x273F, bytes([args[2] & 1]))
        if off == 0x790FE0 and ctl.rd(unit + 0x273F, 1) == b'\1':
            ctl.put(unit + 0x4014, b'\1')  # native put action's first tick
            ctl.put(unit + 0x3014, b'\1')
        return 1

    ctl.call = call
    return ctl


def test_default_refuses_unverified_before_any_write(monkeypatch):
    ctl = mine_controller(monkeypatch)
    with pytest.raises(N.Unavailable, match='live validation'):
        M.place(ctl)
    assert not ctl.writes and not ctl.native_calls


def test_verified_button_requires_native_armed_mines(monkeypatch):
    monkeypatch.setattr(M, 'LIVE_VERIFIED', True)
    ctl = mine_controller(monkeypatch)
    out = M.place(ctl, 5)
    assert out['verified'] and out['state'] == 'confirmed'
    assert out['armed'] == 5 and all(m['active'] for m in out['mines'])
    assert all(m['primary_enabled'] and m['proximity_enabled'] for m in out['mines'])


def test_proximity_enabled_without_primary_gate_cannot_confirm_armed(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    def call(off, *args, **kw):
        result = original(off, *args, **kw)
        if off == 0x790FE0:
            ctl.put(args[0] + 0x4014, b'\0')
        return result  # native return alone is not evidence of an enabled volume
    ctl.call = call
    def wait(predicate, **_):
        if not predicate():
            raise N.Unavailable('native arming not observed')
    ctl.wait = wait
    out = M.place(ctl, allow_unverified=True)
    assert out['state'] == 'uncertain' and out['armed'] == 0
    row = out['mines'][0]
    assert row['proximity_enabled'] and not row['primary_enabled']
    assert not row['armed_observed']


@pytest.mark.parametrize('count', [5, 8])
def test_mine_ring_fixed_radius_native_arming_no_weapon_or_input_writes(monkeypatch, count):
    ctl = mine_controller(monkeypatch)
    out = M.place(ctl, count, allow_unverified=True)
    assert out['state'] == 'confirmed' and not out['verified']
    assert out['placed'] == out['armed'] == count and out['triggered'] == 0
    assert out['weapon_unchanged'] and not out['inventory_consumed']
    assert out['center'] == [100, 200, 300]
    for row in out['mines']:
        x, y, z = row['requested_pos']
        assert math.hypot(x-100, z-300) == pytest.approx(152.4)
        assert y == 200 and row['state_accepted'] and row['configured']
    # Only inactive projectile positions were written by Python; all lifecycle changes were native calls.
    assert {at for at, _ in ctl.writes} == {u+off for u in ctl.units for off in (0x60, 0x2680)}
    assert {off for off, _ in ctl.native_calls} == {0x118E820, *M.FUNCTIONS}
    assert N.Controller.drop_bomb is None


def test_trigger_between_observations_counts_native_trigger_without_claiming_arming_or_damage(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    def call(off, *args, **kw):
        result = original(off, *args, **kw)
        if off == 0x790FE0:
            ctl.put(args[0]+0x28C1, b'\1')
            ctl.put(args[0]+0x3014, b'\0')
        return result
    ctl.call = call
    out = M.place(ctl, allow_unverified=True)
    assert out['state'] == 'confirmed' and out['placed'] == out['triggered'] == 1
    assert out['armed'] == 0
    assert out['mines'][0]['outcome'] == 'native_explosion_latch_observed'


def test_partial_ring_is_preserved_and_never_replayed(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    def call(off, *args, **kw):
        if off == 0x60D6D0 and args[0] == ctl.units[1]:
            raise N.Uncertain('completion lost')
        return original(off, *args, **kw)
    ctl.call = call
    out = M.place(ctl, 8, allow_unverified=True)
    assert out['state'] == 'uncertain' and out['placed'] == 1
    assert len(out['prepared']) == 8
    assert sum(off == 0x118E820 for off, _ in ctl.native_calls) == 8
    assert sum(off == 0x60D6D0 for off, _ in ctl.native_calls) == 1


@pytest.mark.parametrize('change', ['code', 'epoch', 'count', 'class'])
def test_invalid_request_refused_before_native_mutation(monkeypatch, change):
    ctl = mine_controller(monkeypatch)
    if change == 'code':
        ctl.put(ctl.base + next(iter(M.FUNCTIONS)), b'bad!')
    if change == 'class':
        ctl.pair = lambda: 'pre_class'
    if change == 'count':
        with pytest.raises(ValueError):
            M.place(ctl, True, allow_unverified=True)
    else:
        out = M.place(ctl, allow_unverified=True, allowed=lambda: change != 'epoch')
        assert out['state'] == 'failed' and out['placed'] == 0
    assert not ctl.native_calls and not ctl.writes


def test_prepared_unit_reuse_cannot_write_transform(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    def call(off, *args, **kw):
        result = original(off, *args, **kw)
        if off == 0x118E820 and len(ctl.units) == 8:
            ctl.put(ctl.units[0]+0x1A00, struct.pack('<Q', 999))
        return result
    ctl.call = call
    out = M.place(ctl, 8, allow_unverified=True)
    assert out['state'] == 'uncertain' and out['placed'] == 0
    assert not ctl.writes


def test_new_life_rejects_queued_native_mine_before_mutation(monkeypatch):
    ctl = mine_controller(monkeypatch)
    with pytest.raises(N.AllocationLost, match='player changed'):
        M.place(ctl, allow_unverified=True, expected=(ctl.player, ctl.generation + 1))
    assert not ctl.native_calls and not ctl.writes


def test_background_mine_refuses_busy_controller_without_waiting(monkeypatch):
    ctl = mine_controller(monkeypatch)
    class Busy:
        def acquire(self, *, blocking):
            assert blocking is False
            return False
        def release(self):
            pytest.fail('an unacquired lock must not be released')
    ctl.lock = Busy()
    with pytest.raises(N.Unavailable, match='mine placement was not queued'):
        M.place(ctl, allow_unverified=True, wait_for_lock=False)
    assert not ctl.native_calls and not ctl.writes


def test_mine_receipt_records_concurrent_movement_health_and_native_ground_position(monkeypatch):
    ctl = mine_controller(monkeypatch)
    ctl.put(ctl.player + N.R.P_HP, struct.pack('<h', 900))
    original = ctl.call
    def call(off, *args, **kw):
        result = original(off, *args, **kw)
        if off == 0x793AB0:
            ctl.put(ctl.player + N.R.P_POS, struct.pack('<3f', 200, 200, 400))
            ctl.put(ctl.player + N.R.P_HP, struct.pack('<h', 850))
            ctl.put(args[0] + 0x60, struct.pack('<3f', 100, 190, 300))
        return result
    ctl.call = call
    out = M.place(ctl, allow_unverified=True, expected=(ctl.player, ctl.generation), wait_for_lock=False)
    assert out['hp_before'] == 900 and out['hp_after'] == 850
    assert out['hp_loss_observed'] == 50 and out['damage_attribution'].startswith('unattributed')
    assert out['player_pos_before'] == [100, 200, 300] and out['player_pos_after'] == [200, 200, 400]
    assert out['mines'][0]['pos'] == [100, 190, 300]


def test_hit_ring_uses_event_position_and_publishes_hazards_before_arming_wait(monkeypatch):
    ctl = mine_controller(monkeypatch)
    hazards = []
    original = ctl.wait
    def wait(predicate, **kw):
        if len(ctl.units) == 5 and all(ctl.rd(u + 0x27B9, 1) == b'\1' for u in ctl.units):
            assert len(hazards) == 5
            assert all(h['armed_observed'] is False for h in hazards)
        return original(predicate, **kw)
    ctl.wait = wait
    out = M.place(ctl, 5, allow_unverified=True, center=(400, 200, 800), on_deployed=hazards.append)
    assert out['center'] == [400, 200, 800]
    assert out['center_source'] == 'request_event_observation'
    assert out['armed'] == 5
    assert all(math.hypot(h['pos'][0]-400, h['pos'][2]-800) == pytest.approx(152.4) for h in hazards)
    assert all(args[1:] == (1, 1, M.ITEM, 1) for off, args in ctl.native_calls if off == 0x60D6D0)


@pytest.mark.parametrize('center', [(True, 0, 0), (float('nan'), 0, 0), [1, 2], 'bad'])
def test_invalid_event_center_refused_before_native_calls(monkeypatch, center):
    ctl = mine_controller(monkeypatch)
    with pytest.raises(ValueError):
        M.place(ctl, allow_unverified=True, center=center)
    assert not ctl.native_calls and not ctl.writes


def test_every_native_floor_hit_is_checked_before_first_mine_is_activated(monkeypatch):
    ctl = mine_controller(monkeypatch)
    out = M.place(ctl, 5, allow_unverified=True)
    calls = [off for off, _ in ctl.native_calls]
    first_active = calls.index(0x60D6D0)
    assert calls[:first_active].count(M.GROUND) == 5
    assert M.GROUND not in calls[first_active:]
    assert out['all_floors_validated'] and out['armed'] == 5
    assert all(row['floor_validated'] and row['ground_hit'] for row in out['mines'])


@pytest.mark.parametrize('bad', ['lower_floor', 'upper_floor', 'miss', 'nan', 'sideways'])
def test_bad_last_ring_point_cannot_arm_any_member_or_publish_a_hazard(monkeypatch, bad):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    notices = []
    def call(off, *args, **kw):
        result = original(off, *args, **kw)
        if off == M.GROUND and args[0] == ctl.units[-1]:
            if bad == 'miss':
                return 0
            x, y, z = struct.unpack('<3f', ctl.rd(args[0]+0x60, 12))
            if bad == 'lower_floor': y -= 1454.1220397949219  # captured Experimental Facility defect
            elif bad == 'upper_floor': y += M.FLOOR_SLOP_CM + 1
            elif bad == 'nan': y = float('nan')
            else: x += 100
            ctl.put(args[0]+0x60, struct.pack('<3f', x, y, z))
        return result
    ctl.call = call
    out = M.place(ctl, 5, allow_unverified=True, on_deployed=notices.append)
    assert out['state'] == 'refused' and out['floor_refused'] and not out['verified']
    assert out['placed'] == out['armed'] == out['triggered'] == 0 and not notices
    assert out['refused_index'] == 4
    assert all(off not in (0x60D6D0, 0x790FE0) for off, _ in ctl.native_calls)
    assert all(ctl.rd(u+0x27B9, 1) == b'\0' for u in ctl.units)
    assert len(ctl._proximity_prepared['rows']) == 5


def test_repeated_floor_refusal_reuses_bounded_inactive_allocations_then_arms_valid_points(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    attempts = [0]
    def call(off, *args, **kw):
        result = original(off, *args, **kw)
        return 0 if off == M.GROUND and attempts[0] < 3 else result
    ctl.call = call
    for i in range(3):
        attempts[0] = i
        out = M.place(ctl, 5, allow_unverified=True)
        assert out['state'] == 'refused' and out['placed'] == 0
        assert len(ctl.units) == len(ctl._proximity_prepared['rows']) == 5
    attempts[0] = 3
    out = M.place(ctl, 5, allow_unverified=True)
    assert out['state'] == 'confirmed' and out['armed'] == 5
    assert all(row['reused_inactive'] for row in out['mines'])
    assert len(ctl.units) == 5 and not ctl._proximity_prepared['rows']


@pytest.mark.parametrize('change', ['generation', 'owner', 'active', 'attachment', 'primary_volume'])
def test_cached_inactive_unit_cannot_be_reused_after_ownership_or_state_changes(monkeypatch, change):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    ctl.call = lambda off, *a, **kw: 0 if off == M.GROUND else original(off, *a, **kw)
    assert M.place(ctl, allow_unverified=True)['state'] == 'refused'
    unit = ctl.units[0]
    if change == 'generation': ctl.put(unit+0x1A00, struct.pack('<Q', 999))
    elif change == 'owner': ctl.put(unit+0x1A10, struct.pack('<Q', ctl.player+0x1000))
    elif change == 'active': ctl.put(unit+0x27B9, b'\1')
    elif change == 'primary_volume': ctl.put(unit+0x4014, b'\1')
    else: ctl.put(unit+0x48, struct.pack('<Q', ctl.player))
    before = len(ctl.native_calls), len(ctl.writes)
    out = M.place(ctl, allow_unverified=True)
    assert out['state'] in ('failed', 'uncertain') and out['placed'] == 0
    assert (len(ctl.native_calls), len(ctl.writes)) == before


def test_changed_ground_return_code_refuses_before_allocating(monkeypatch):
    ctl = mine_controller(monkeypatch)
    ctl.put(ctl.base + M.GROUND + M.GROUND_SIZE - 4, b'bad!')
    out = M.place(ctl, allow_unverified=True)
    assert out['state'] == 'failed' and 'return contract' in out['reason']
    assert not ctl.writes and not ctl.native_calls


def test_mine_moved_after_preflight_cannot_be_activated(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    def call(off, *args, **kw):
        result = original(off, *args, **kw)
        if off == M.GROUND and args[0] == ctl.units[-1]:
            ctl.put(ctl.units[0]+0x64, struct.pack('<f', -1900))
        return result
    ctl.call = call
    out = M.place(ctl, 5, allow_unverified=True)
    assert out['state'] == 'uncertain' and out['placed'] == 0
    assert 'moved after floor validation' in out['reason']
    assert all(off not in (0x60D6D0, 0x790FE0) for off, _ in ctl.native_calls)


def test_round_expiry_during_grounding_cannot_activate_or_cache_the_old_batch(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    live = [True]
    def call(off, *args, **kw):
        result = original(off, *args, **kw)
        if off == M.GROUND: live[0] = False
        return result
    ctl.call = call
    out = M.place(ctl, 5, allow_unverified=True, allowed=lambda: live[0])
    assert out['state'] == 'uncertain' and out['placed'] == 0
    assert not ctl._proximity_prepared['rows']
    assert all(off not in (0x60D6D0, 0x790FE0) for off, _ in ctl.native_calls)


def test_new_player_life_never_reuses_previous_lifes_inactive_pool(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    ctl.call = lambda off, *a, **kw: 0 if off == M.GROUND else original(off, *a, **kw)
    assert M.place(ctl, allow_unverified=True)['state'] == 'refused'
    old_unit = ctl.units[0]
    ctl.generation += 1
    ctl.call = original
    out = M.place(ctl, allow_unverified=True)
    assert out['state'] == 'confirmed' and out['mines'][0]['unit'] != old_unit
    assert not out['mines'][0].get('reused_inactive')
    assert ctl._proximity_prepared['owner'] == (ctl.player, ctl.generation)


def test_generation_change_during_cached_inactive_check_prevents_transform_write(monkeypatch):
    ctl = mine_controller(monkeypatch)
    original = ctl.call
    ctl.call = lambda off, *a, **kw: 0 if off == M.GROUND else original(off, *a, **kw)
    assert M.place(ctl, allow_unverified=True)['state'] == 'refused'
    unit, before = ctl.units[0], len(ctl.writes)
    read = ctl.rd
    def racing(at, size):
        result = read(at, size)
        if at == unit+0x28C1:
            ctl.put(unit+0x1A00, struct.pack('<Q', 888))
        return result
    ctl.rd = racing
    out = M.place(ctl, allow_unverified=True)
    assert out['placed'] == 0 and 'allocation changed' in out['reason']
    assert len(ctl.writes) == before

