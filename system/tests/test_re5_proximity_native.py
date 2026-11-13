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
        if off == 0x793AB0:
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
        if off == 0x793AB0:
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

