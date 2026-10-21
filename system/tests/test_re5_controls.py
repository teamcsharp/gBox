import pytest

from gbox import re5_mods_tool as M
from gbox.mercs.titles import re5_controls as C
from test_re5_mods import FakeRE5, fresh_originals  # noqa: F401
from test_re5_mods_loadout import with_template


def world():
    return {"player": {"ptr": 123, "hp": 1000}, "inventory": [
        {"slot": 8, "grid": 3, "type": 1, "item": 0x12, "rounds": 20, "hand": True},
        {"slot": 9, "grid": 5, "type": 1, "item": 0x1B, "rounds": 5, "hand": False},
        {"slot": 10, "grid": 1, "type": 1, "item": 0x0D, "rounds": 1, "hand": False},
        {"slot": 11, "grid": 7, "type": 1, "item": 0x20, "rounds": 5, "hand": False}]}


def test_operator_off_survives_round_randomizer_and_can_be_changed_again():
    memory = with_template(FakeRE5())
    for op in ("fire_rate", "bullet_damage", "turn_speed", "infinite_ammo"):
        assert M.run(memory, op, on=False, operator=True)["verified"]
    result = M.run(memory, "random_cheats", seed=3)
    assert result["verified"]
    assert result["telemetry"]["fire_rate_x"] == 1
    assert result["telemetry"]["bullet_damage_x"] == 1
    assert result["telemetry"]["turn_speed_x"] == 1
    assert result["telemetry"]["infinite_ammo"] is False
    assert M.run(memory, "fire_rate", multiplier=80, operator=True)["status"]["fire_rate_x"] == 80
    assert M.run(memory, "fire_rate", multiplier=2)["status"]["fire_rate_x"] == 80
    assert M.run(memory, "revert_all")["status"]["operator_overrides"] == {}


def test_failed_write_does_not_remember_operator_override(monkeypatch):
    memory = FakeRE5()
    monkeypatch.setattr(memory, "write_memory", lambda *_: None)
    result = M.run(memory, "infinite_ammo", operator=True)
    assert not result["verified"] and result["status"]["operator_overrides"] == {}


def test_revert_cancels_pending_weapon_request_and_pin():
    memory = FakeRE5()
    state = M.RE5(memory).orig
    C.publish(state, 7, world(), True)
    C.request(state)
    state["weapon_pin"] = {"until": 100}
    assert M.run(memory, "revert_all")["status"]["random_weapon_request"]["state"] == "rejected"
    assert "weapon_pin" not in state


def test_random_request_uses_single_owner_and_only_confirms_actual_equipment():
    state, snap = {}, world()
    C.publish(state, 7, snap, True, now=10)
    queued = C.request(state, now=10)
    assert queued["queued"] and not queued["verified"] and queued["request"]["weapon"] == "S&W M500"
    assert C.request(state, now=11)["request"]["id"] == queued["request"]["id"]
    calls = []
    def switch(item, now, why):
        calls.append(item)
        return {"tap": "dright"}
    assert C.consume(state, 7, snap, switch, 20, monotonic=11) == {"tap": "dright"}
    assert state["random_weapon_request"]["state"] == "pending"
    snap["inventory"][0]["hand"] = False
    snap["inventory"][1]["hand"] = True
    assert C.consume(state, 7, snap, switch, 21, monotonic=12) is None
    assert state["random_weapon_request"]["state"] == "confirmed"
    assert len(calls) == 1 and C.pinned(state, snap, 22) and not C.pinned(state, snap, 37)


@pytest.mark.parametrize("change", ["owner", "player", "inventory", "timeout"])
def test_changed_request_context_never_presses_a_button(change):
    state, snap = {}, world()
    C.publish(state, 7, snap, True, now=10)
    C.request(state, now=10)
    if change == "player":
        snap["player"]["ptr"] += 1
    if change == "inventory":
        snap["inventory"][1]["item"] = 0x20
    def forbidden(*_):
        pytest.fail("stale request must not press the pad")
    C.consume(state, 8 if change == "owner" else 7, snap, forbidden, 20,
              monotonic=41 if change == "timeout" else 11)
    assert state["random_weapon_request"]["state"] == "rejected"


def test_idle_or_stale_bot_cannot_accept_requests_and_pending_request_expires():
    state = {}
    assert not C.request(state, now=10)["queued"]
    C.publish(state, 7, world(), True, now=10)
    C.request(state, now=10)
    assert C.request_status(state, now=16)["state"] == "rejected"
    assert not C.request(state, now=16)["queued"]


def test_threat_defers_input_but_does_not_hide_an_equipment_confirmation():
    state, snap = {}, world()
    C.publish(state, 7, snap, True, now=10)
    C.request(state, now=10)
    def forbidden(*_):
        pytest.fail("do not delay nearby combat for an optional switch")
    C.consume(state, 7, snap, forbidden, 20, monotonic=11, input_allowed=False)
    assert state["random_weapon_request"]["state"] == "pending"
    snap["inventory"][1]["hand"] = True
    C.consume(state, 7, snap, forbidden, 21, monotonic=12, input_allowed=False)
    assert state["random_weapon_request"]["state"] == "confirmed"


@pytest.mark.parametrize("wid", [0x105, 0x11C, 0x120, 0x10D])
def test_rocket_and_every_sniper_template_is_replaced_with_a_magnum(wid):
    memory = with_template(FakeRE5())
    offset = 24 * M.TEMPLATE_BLOCK + 6 * M.TEMPLATE_REC
    memory.u32(M.TEMPLATE + offset, wid)
    result = M.run(memory, "replace_long_guns", seed=1)
    assert result["verified"] and result["effective_next_round"]
    records = M.template_records(memory.read_memory(M.TEMPLATE, M.TEMPLATE_BLOCKS * M.TEMPLATE_BLOCK))
    assert all(item not in M.REPLACE_WITH_MAGNUM for _, item, *_ in records)
    assert next(item for off, item, *_ in records if off == offset) in M.MAGNUMS
    generated = M.run(memory, "loadout", weapons=[wid], seed=1)
    assert set(generated["barry"]) <= {M.WEAPONS[item & 0xFF] for item in M.MAGNUMS}
