"""Scoped magnum playback writes stay with the current living player and owned animation instance."""
import struct

import pytest

from gbox.mercs.titles import re5_fire_animation as F

SP, PLAYER, ACTION = 0x388369C0, 0x303F8A00, 0x30400000
SCOPE = ("test-session", 123, "process-start-1")


class Memory:
    def __init__(self):
        self.data, self.writes = {}, []
        self.before_read = self.after_write = None
        self.fail_write = False
        for address, raw in F.SIGNATURES.items():
            self.put(address, raw)
        self.pack(F.S_PLAYER, ">I", SP)
        self.pack(SP + 0x28, ">I", PLAYER)
        self.pack(PLAYER + F.P_HP, ">hh", 1000, 1000)
        self.pack(PLAYER + F.P_ACTION, ">I", ACTION)
        self.pack(ACTION, ">I", F.FIRE_VT)
        self.pack(ACTION + 0x18, ">I", PLAYER)
        self.pack(ACTION + 0x1C, ">2f", 0.1, 480.0)
        self.pack(PLAYER + F.P_LAYER_COUNT, ">I", 6)
        self.pack(PLAYER + F.P_INVENTORY + 8, ">I", 0x11B)
        self.pack(PLAYER + F.P_INVENTORY + 0x20, ">I", 1)
        self.put(PLAYER + F.P_INVENTORY + 0x2D, b"\1")
        for base, motion in F.LAYERS:
            self.pack(PLAYER + base + 4, ">H", motion)
            self.pack(PLAYER + base + 0x18, ">2f", 6.0, 47.0)
            self.put(PLAYER + base + 0x24, F.BASE_RATE)

    def put(self, address, raw):
        self.data.update((address + i, b) for i, b in enumerate(raw))

    def pack(self, address, fmt, *values):
        self.put(address, struct.pack(fmt, *values))

    def rd(self, address, size):
        if self.before_read:
            self.before_read(address, size)
        return bytes(self.data.get(address + i, 0) for i in range(size))

    def wr(self, address, raw):
        self.writes.append((address, raw))
        if self.fail_write:
            return False
        self.put(address, raw)
        if self.after_write:
            self.after_write(address, raw)
        return True


def snapshot():
    return {"player": {"ptr": PLAYER, "hp": 1000}, "timer": 100.0,
            "inventory": [{"slot": 0, "id": 0x11B, "hand": True}]}


def update(helper, memory, snap=None, **kwargs):
    return helper.update(memory, snapshot() if snap is None else snap,
                         **({"enabled": True, "multiplier": 8.0, "scope": SCOPE} | kwargs))


def rates(memory):
    return [struct.unpack(">f", memory.rd(PLAYER + base + 0x24, 4))[0] for base, _ in F.LAYERS]


def test_only_three_playback_floats_are_changed_and_repeated_maintenance_does_not_compound():
    memory, helper = Memory(), F.FireAnimation()
    before = dict(memory.data)
    result = update(helper, memory)
    assert result["active"] and result["verified"] and result["writes"] == 3
    assert rates(memory) == [8.0] * 3 and len(helper.owned) == 3
    addresses = [PLAYER + base + 0x24 for base, _ in F.LAYERS]
    assert memory.writes == [(address, struct.pack(">f", 8.0)) for address in addresses]
    changed = {address for address in memory.data if memory.data[address] != before.get(address)}
    assert changed <= {address + i for address in addresses for i in range(4)}
    assert update(helper, memory)["writes"] == 0
    assert update(helper, memory, multiplier=4.0)["writes"] == 3 and rates(memory) == [4.0] * 3


@pytest.mark.parametrize("address", F.SIGNATURES)
def test_every_exact_code_signature_is_required(address):
    memory = Memory()
    memory.put(address, b"bad!")
    assert not update(F.FireAnimation(), memory)["active"] and not memory.writes


@pytest.mark.parametrize("multiplier", [0, 0.5, 8.01, float("nan"), float("inf"), True, "8"])
def test_invalid_or_unbounded_multiplier_never_writes(multiplier):
    memory = Memory()
    assert not update(F.FireAnimation(), memory, multiplier=multiplier)["verified"] and not memory.writes


@pytest.mark.parametrize("address,fmt,value", [
    (PLAYER + F.P_HP, ">h", 0), (PLAYER + F.P_HP, ">h", 1),
    (ACTION, ">I", 0x0163E038), (PLAYER + F.P_ACTION, ">I", ACTION + 1),
    (ACTION + 0x18, ">I", PLAYER + 0x1000),
    (SP + 0x28, ">I", PLAYER + 0x1000), (PLAYER + F.P_LAYER_COUNT, ">I", 2),
    (PLAYER + F.P_INVENTORY + 8, ">I", 0x112),
    (PLAYER + 0x304, ">H", 0x123), (PLAYER + 0x3E4, ">H", 0x123), (PLAYER + 0x4C4, ">H", 0x123),
    (PLAYER + 0x324, ">f", 2.0), (PLAYER + 0x404, ">f", float("nan")),
    (PLAYER + 0x4E4, ">f", 0.0), (PLAYER + 0x324, ">f", 9.0),
    (ACTION + 0x20, ">f", float("inf")),
])
def test_wrong_player_action_weapon_motion_health_or_rate_never_writes(address, fmt, value):
    memory = Memory()
    memory.pack(address, fmt, value)
    assert not update(F.FireAnimation(), memory)["active"] and not memory.writes


def test_snapshot_scope_and_prompt_do_not_authorize_unrelated_playback_writes():
    for snap in ({}, snapshot() | {"player": {"ptr": PLAYER + 4, "hp": 1000}},
                 snapshot() | {"inventory": [{"slot": 1, "id": 0x11B, "hand": True}]},
                 snapshot() | {"prompt": "mash"}, snapshot() | {"recovery_active": True},
                 snapshot() | {"stage_prompt": "climb"}):
        memory = Memory()
        assert not update(F.FireAnimation(), memory, snap)["active"] and not memory.writes
    memory = Memory()
    result = F.FireAnimation().update(memory, None, enabled=True, multiplier=8.0, scope=SCOPE)
    assert not result["active"] and not memory.writes


def test_each_write_rechecks_action_and_signatures_before_touching_the_next_layer():
    for mutate in (lambda m: m.pack(ACTION, ">I", 0x0163E038),
                   lambda m: m.pack(PLAYER + 0x3E4, ">H", 0x222),
                   lambda m: m.pack(SP + 0x28, ">I", PLAYER + 0x1000),
                   lambda m: m.pack(PLAYER + F.P_HP, ">h", 1),
                   lambda m: m.put(next(iter(F.SIGNATURES)), b"bad!")):
        memory = Memory()
        memory.after_write = lambda address, raw: mutate(memory)
        result = update(F.FireAnimation(), memory)
        assert not result["verified"] and len(memory.writes) == 1
        assert memory.writes[0][0] == PLAYER + 0x324


def test_action_change_between_initial_observation_and_first_write_is_rejected():
    memory = Memory()
    counts = [0]
    def before_read(address, size):
        if address == next(iter(F.SIGNATURES)):
            counts[0] += 1
            if counts[0] == 2:
                memory.pack(PLAYER + F.P_ACTION, ">I", ACTION + 0x100)
    memory.before_read = before_read
    assert not update(F.FireAnimation(), memory)["verified"] and not memory.writes


def test_late_health_weapon_or_motion_change_during_prewrite_guard_is_rejected():
    for mutate in (lambda m: m.pack(PLAYER + F.P_HP, ">h", 1),
                   lambda m: m.pack(PLAYER + F.P_INVENTORY + 8, ">I", 0x10D),
                   lambda m: m.pack(PLAYER + 0x4C4, ">H", 0x222),
                   lambda m: m.pack(PLAYER + F.P_LAYER_COUNT, ">I", 2),
                   lambda m: m.pack(PLAYER + 0x404, ">f", 2.0),
                   lambda m: m.pack(ACTION + 0x18, ">I", PLAYER + 0x1000),
                   lambda m: m.pack(ACTION + 0x20, ">f", 0.0),
                   lambda m: m.pack(PLAYER + 0x318, ">f", 0.0),
                   lambda m: m.pack(PLAYER + 0x31C, ">f", 48.0)):
        memory, counts = Memory(), [0]
        def before_read(address, size):
            if address == F.S_PLAYER:
                counts[0] += 1
                if counts[0] == 4:              # final pointer fence of the first prewrite full guard
                    mutate(memory)
        memory.before_read = before_read
        assert not update(F.FireAnimation(), memory)["verified"] and not memory.writes


def test_failed_write_and_unexpected_readback_do_not_claim_activation_or_overwrite_external_value():
    for fail in (True, False):
        memory, helper = Memory(), F.FireAnimation()
        memory.fail_write = fail
        if not fail:
            memory.after_write = lambda address, raw: memory.pack(address, ">f", 2.0)
        result = update(helper, memory)
        assert not result["active"] and not result["verified"] and len(memory.writes) == 1
        memory.after_write, memory.fail_write = None, False
        result = update(helper, memory, enabled=False)
        assert result["restored"] == 0 and len(memory.writes) == 1
        assert rates(memory)[0] == (1.0 if fail else 2.0)


def test_disabled_or_prompt_cleanup_restores_only_unchanged_owned_values_without_a_snapshot():
    memory, helper = Memory(), F.FireAnimation()
    update(helper, memory)
    memory.pack(PLAYER + 0x404, ">f", 2.0)       # another writer owns this value now
    result = helper.update(memory, None, enabled=False, multiplier=8.0, scope=SCOPE)
    assert result["verified"] and result["restored"] == 2 and rates(memory) == [1.0, 2.0, 1.0]
    assert len(helper.owned) == 0
    memory, helper = Memory(), F.FireAnimation()
    update(helper, memory)
    result = update(helper, memory, snapshot() | {"prompt": "mash:square"})
    assert not result["active"] and result["restored"] == 3 and rates(memory) == [1.0] * 3


def test_scope_action_instance_reset_or_changed_motion_never_restores_a_replacement():
    for mutate, scope in ((lambda m: None, ("test-session", 123, "new-process-start")),
                          (lambda m: m.pack(ACTION + 0x1C, ">2f", 0.0, 0.0), SCOPE),
                          (lambda m: m.pack(PLAYER + 0x318, ">f", 0.0), SCOPE),
                          (lambda m: m.pack(PLAYER + 0x304, ">H", 0x222), SCOPE),
                          (lambda m: m.pack(PLAYER + F.P_ACTION, ">I", ACTION + 0x100), SCOPE)):
        memory, helper = Memory(), F.FireAnimation()
        update(helper, memory)
        mutate(memory)
        result = update(helper, memory, enabled=False, scope=scope)
        assert result["restored"] == 0 and len(memory.writes) == 3
        assert len(helper.owned) <= 3


def test_observed_new_shot_can_be_accelerated_only_after_the_game_restores_baseline_rates():
    memory, helper = Memory(), F.FireAnimation()
    update(helper, memory)
    memory.pack(ACTION + 0x1C, ">2f", 0.0, 0.0)
    assert not update(helper, memory)["active"] and len(memory.writes) == 3
    for base, _ in F.LAYERS:
        memory.put(PLAYER + base + 0x24, F.BASE_RATE)
    assert update(helper, memory)["active"] and len(memory.writes) == 6


def test_an_observed_nonfire_gap_drops_ownership_even_if_the_action_address_is_reused():
    memory, helper = Memory(), F.FireAnimation()
    update(helper, memory)
    memory.pack(ACTION, ">I", 0x0163E038)
    assert not update(helper, memory, enabled=False)["verified"] and not helper.owned
    memory.pack(ACTION, ">I", F.FIRE_VT)
    assert update(helper, memory, enabled=False)["restored"] == 0
    assert rates(memory) == [8.0] * 3 and len(memory.writes) == 3


def test_disabled_with_no_owned_rates_is_a_verified_no_write_even_outside_fire():
    memory = Memory()
    memory.pack(ACTION, ">I", 0x0163E038)
    result = F.FireAnimation().update(memory, None, enabled=False, multiplier=8.0, scope=SCOPE)
    assert result["verified"] and not result["active"] and not result["restored"] and not memory.writes
    assert result["reason"] == "no owned rates to restore"


def test_postwrite_reset_is_compared_with_latest_prewrite_clock():
    memory, helper, observations = Memory(), F.FireAnimation(), [0]
    def before_read(address, size):
        if address == next(iter(F.SIGNATURES)):
            observations[0] += 1
            if observations[0] == 2:
                memory.pack(PLAYER + 0x318, ">f", 10.0)
    memory.before_read = before_read
    memory.after_write = lambda address, raw: memory.pack(PLAYER + 0x318, ">f", 8.0)
    result = update(helper, memory)
    assert not result["verified"] and not result["active"] and len(memory.writes) == 1
    assert not helper.owned
