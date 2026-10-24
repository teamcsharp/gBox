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
    assert len(calls) == 1 and C.pinned(state, snap, 22) and C.pinned(state, snap, 10000)


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
    offset = 24 * M.TEMPLATE_BLOCK  # native preset row 0 is a complete, existing gun record
    memory.u32(M.TEMPLATE + offset, wid)
    result = M.run(memory, "replace_long_guns", seed=1)
    assert result["verified"] and result["effective_next_round"]
    records = M.template_records(memory.read_memory(M.TEMPLATE, M.TEMPLATE_BLOCKS * M.TEMPLATE_BLOCK))
    assert all(item not in M.REPLACE_WITH_MAGNUM for _, item, *_ in records)
    assert next(item for off, item, *_ in records if off == offset) in M.MAGNUMS
    generated = M.run(memory, "loadout", weapons=[wid], seed=1)
    assert set(generated["barry"]) <= {M.WEAPONS[item & 0xFF] for item in M.MAGNUMS}


def test_equipped_sniper_or_rocket_is_swapped_to_a_loaded_magnum_first():
    snap = world()
    snap["inventory"][0]["hand"] = False
    snap["inventory"][3]["hand"] = True            # Dragunov SVD in hand
    snap["inventory"][1]["grid"] = 3                # S&W M500, quick slot
    snap["inventory"][0]["grid"] = 5
    calls = []
    out = C.leave_long_gun(snap, lambda item, now, why: calls.append(item["item"]) or {"tap": "dleft"}, 1.0)
    assert out == {"tap": "dleft"} and calls == [0x1B]
    snap["inventory"][3]["hand"], snap["inventory"][0]["hand"] = False, True
    assert C.leave_long_gun(snap, lambda *a: pytest.fail("not a long gun"), 2.0) is None


def test_selected_gun_persists_after_confirmation_and_follows_real_inventory_identity():
    state,snap={},world();C.publish(state,7,snap,True,now=10)
    assert C.request(state,now=10,weapon=0x1B)['preference_saved']
    snap['inventory'][0]['hand']=False;snap['inventory'][1]['hand']=True
    C.consume(state,7,snap,lambda *a:pytest.fail('already equipped'),20,monotonic=11)
    assert C.pinned(state,snap,10000)
    # The mine constructor can move the gun's grid/storage record. A stale
    # quick key must not equip the different item now occupying that position.
    snap['inventory'][1].update(slot=15,grid=1,hand=False)
    snap['inventory'][0].update(slot=9,grid=5,hand=True)
    C.publish(state,7,snap,True,now=100)
    calls=[]
    action=C.consume(state,7,snap,lambda item,*a:calls.append(item) or {'tap':'dup'},10000,monotonic=100)
    assert action=={'tap':'dup'} and calls[0]['item']==0x1B and calls[0]['slot']==15
    assert state['preferred_weapon']['item']==0x1B


def test_unavailable_preference_remains_saved_without_switching_to_original_loadout():
    state,snap={},world();C.publish(state,7,snap,True,now=10)
    C.request(state,now=10,weapon=0x1B)
    snap['inventory']=[snap['inventory'][0]]
    C.publish(state,7,snap,True,now=11)
    C.consume(state,7,snap,lambda *a:pytest.fail('unavailable gun must not equip another item'),20,monotonic=11)
    status=C.preference_status(state,now=11)
    assert status['item']==0x1B and not status['available'] and not status['equipped']


def test_deferred_choice_waits_for_gunplay_then_equips_under_new_current_controller():
    state,snap={},world();C.publish(state,7,snap,True,now=10)
    result=C.request(state,now=10,weapon=0x1B,deferred=True)
    assert result['deferred'] and result['request']['state']=='deferred'
    snap['player']['ptr']=321;C.publish(state,8,snap,True,now=100)
    actions=[]
    C.consume(state,8,snap,lambda item,*a:actions.append(item['item']) or {'tap':'dright'},1000,monotonic=100)
    assert actions==[0x1B] and state['random_weapon_request']['state']=='pending'
    assert state['random_weapon_request']['player']==321


def test_auto_clears_only_weapon_choice_and_stale_requests():
    state,snap={'operator_overrides':{'unlimited_health':{'on':False}}},world()
    C.publish(state,7,snap,True,now=10);C.request(state,now=10,weapon=0x1B,deferred=True)
    assert C.clear_preference(state)['automatic']
    assert 'preferred_weapon' not in state and state['random_weapon_request']['state']=='rejected'
    assert state['operator_overrides']=={'unlimited_health':{'on':False}}


def test_another_adapter_session_cannot_inherit_an_old_gun_preference():
    first,second=FakeRE5(),FakeRE5();state={}
    C.bind_adapter(state,first);C.publish(state,7,world(),True,now=10);C.request(state,now=10,weapon=0x1B)
    C.bind_adapter(state,first);assert state['preferred_weapon']['item']==0x1B
    C.bind_adapter(state,second)
    assert 'preferred_weapon' not in state and 'random_weapon_request' not in state


def test_tool_selection_status_and_auto_never_change_health(monkeypatch):
    from gbox.mercs.titles import re5_mines
    monkeypatch.setattr(re5_mines,'settings',lambda:dict(re5_mines.DEFAULT))
    memory=FakeRE5();state=M.RE5(memory).orig
    C.publish(state,7,world(),True)
    before=M.run(memory,'status')['status']['unlimited_health']
    selected=M.run(memory,'select_weapon',weapon=0x1B,operator=True)
    assert selected['preference_saved'] and selected['status']['preferred_weapon']['item']==0x1B
    assert selected['status']['capabilities']['select_weapon']['available']
    assert all(row['item'] not in (0x0D,0x20) for row in selected['status']['available_weapons'])
    assert not M.run(memory,'select_weapon',weapon=0x0D)['queued']
    automatic=M.run(memory,'select_weapon',on=False)
    assert automatic['verified'] and automatic['status']['preferred_weapon'] is None
    assert automatic['status']['unlimited_health']==before
