import struct

import pytest

from gbox.mercs.titles import re5_switch_weapon_native as W
from test_re5_switch_native import controller


def fixture(monkeypatch, outcome=1):
    ctl = controller()
    ctl.ready = lambda: (ctl.player, ctl.generation)
    ctl.put(ctl.player + W.MANAGER, struct.pack('<Q', ctl.base + 0x1C78280))
    for i in range(24):
        ctl.put(ctl.player + W.R.P_INV + 56 * i, struct.pack('<Q', ctl.base + W.SLOT_VT))
    old, new = ctl.player + W.R.P_INV + 56 * 15, ctl.player + W.R.P_INV + 56 * 16
    previous, unit, scratch = 0x250000000, 0x260000000, ctl.heap + 0x800
    ctl.put(old + W.SLOT_ACTIVE, b'\1')
    ctl.put(old + W.R.INV_OBJ, struct.pack('<Q', previous))
    ctl.put(previous + 0x1A00, struct.pack('<Q', 71))
    ctl.put(previous + 0x1A10, struct.pack('<Q', ctl.player))
    calls = []

    def call(off, *args):
        calls.append((off, args))
        if off == W.STAGE:
            ctl.put(scratch + 0x35, b'\1')
            ctl.put(scratch + 8 + W.R.INV_OBJ, struct.pack('<Q', unit))
            ctl.put(unit + 0x1A00, struct.pack('<Q', 72))
            ctl.put(unit + 0x1A10, struct.pack('<Q', ctl.player))
            ctl.put(unit + 0x1B88, b'\1')
            return scratch + 8
        if off == W.COMMIT:
            assert args == (ctl.player, ctl.generation, scratch, unit, 72, old, previous, 71)
            if outcome == 'timeout':
                raise W.N.Uncertain('missing completion receipt')
            if outcome == 1:
                ctl.put(old + W.SLOT_ACTIVE, b'\0')
                ctl.put(new + W.SLOT_ACTIVE, b'\1')
                ctl.put(new + W.R.INV_ID, struct.pack('<I', 0x119))
                ctl.put(new + W.R.INV_OBJ, struct.pack('<Q', unit))
                ctl.put(new + W.R.INV_HAND, struct.pack('<I', 1))
                ctl.put(scratch + 0x35, b'\0')
            return outcome
        assert off == W.DISCARD
        ctl.put(scratch + 0x35, b'\0')
        return 1

    ctl.call = call
    monkeypatch.setattr(W.R, 'class_name', lambda *_: 'uWp19')
    return ctl, calls


def test_replacement_resolves_grid_zero_beyond_first_nine_records(monkeypatch):
    ctl, calls = fixture(monkeypatch)
    result = W.replace(ctl, 0x19)
    assert result['verified'] and result['weapon'] == 'Hydra' and result['grid'] == 0
    assert result['player_generation'] == 0x100000002
    assert [c[0] for c in calls] == [W.STAGE, W.COMMIT]
    assert ctl.q(ctl.player) == ctl.original
    assert not ctl.failed


def test_requested_player_life_is_checked_before_native_publication(monkeypatch):
    ctl, calls = fixture(monkeypatch)
    with pytest.raises(W.N.Unavailable, match='player life changed'):
        W.replace(ctl, 0x19, expected=(ctl.player, ctl.generation - 1))
    assert not calls and not ctl.writes


def test_busy_native_refusal_discards_staging_and_keeps_controller_available(monkeypatch):
    ctl, calls = fixture(monkeypatch, 0)
    with pytest.raises(W.N.Unavailable, match='busy'):
        W.replace(ctl, 0x19)
    assert [c[0] for c in calls] == [W.STAGE, W.COMMIT, W.DISCARD]
    assert ctl.q(ctl.player) == ctl.original and not ctl.failed
    assert len(W.records(ctl)) == 1


@pytest.mark.parametrize('outcome', [2, 'timeout'])
def test_uncertain_commit_never_discards_a_possibly_equipped_weapon(monkeypatch, outcome):
    ctl, calls = fixture(monkeypatch, outcome)
    with pytest.raises(W.N.Uncertain):
        W.replace(ctl, 0x19)
    assert [c[0] for c in calls] == [W.STAGE, W.COMMIT]
    assert ctl.q(ctl.player) == ctl.original and ctl.failed and not ctl.recoverable


def test_unexpected_native_class_is_cleaned_up_before_any_live_inventory_change(monkeypatch):
    ctl, calls = fixture(monkeypatch)
    monkeypatch.setattr(W.R, 'class_name', lambda *_: 'uWp08')
    with pytest.raises(W.N.Unavailable, match='class differs'):
        W.replace(ctl, 0x19)
    assert [c[0] for c in calls] == [W.STAGE, W.DISCARD]
    assert ctl.q(ctl.player) == ctl.original and not ctl.failed


@pytest.mark.parametrize('item', [True, -1, 0x118, 'Hydra'])
def test_catalogue_validation_precedes_native_publication(monkeypatch, item):
    ctl, calls = fixture(monkeypatch)
    with pytest.raises(ValueError):
        W.replace(ctl, item)
    assert not calls and not ctl.writes
