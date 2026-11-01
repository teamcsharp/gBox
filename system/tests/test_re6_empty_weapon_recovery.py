"""Finite-ammunition recovery dependencies for Merc weapon selection; no aim or bonus policy changes."""
import struct

import pytest

from gbox.mercs.titles import re6_switch as R
from test_re6_switch import BASE, _fresh_caches, brain, round_guest, run


def contact_brain(dot=(0.0, R.CHEST_H, 900.0), ammo=18):
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 900.0, 700),), ammo=ammo,
                                        laser=(dot, (0.0, R.CHEST_H, 0.0), 0.86)))
    bot.held = lambda p, now: False
    return bot, clock, snap


def test_empty_magazine_holds_trigger_between_reload_requests_then_resumes():
    bot, clock, snap = contact_brain(ammo=0)
    acts = run(bot, snap, clock, 40)
    assert sum("y" in a.get("hold", ()) for a in acts) == 2
    assert all("zr" not in a.get("hold", ()) for a in acts)
    assert bot.stats["shots"] == bot.stats["confirmed_shots"] == 0
    snap["player"]["ammo"] = 6
    assert any("zr" in a.get("hold", ()) for a in run(bot, snap, clock, 3))


@pytest.mark.parametrize("rounds", [(18, 0), (0, 6)])
def test_snapshot_reads_equipped_wheel_index_instead_of_first_slot(rounds):
    g = round_guest(ammo=rounds[0])
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    g.i32(p + R.P_EQUIPPED, 1)
    for physical, (wheel, count) in enumerate(zip((0, 1), rounds)):
        slot = p + R.P_SLOTS + physical * R.SLOT_STRIDE
        g.put(slot + 8, struct.pack("<BBH", 1, wheel, 0x100 + wheel))
        g.put(slot + 0xE, struct.pack("<h", count))
    player = R.snapshot(g)["player"]
    assert player["ammo"] == rounds[1]
    assert player["gun_ammo"] == {0: rounds[0], 1: rounds[1]}


def test_unresolved_equipped_slot_does_not_borrow_another_guns_ammo():
    g = round_guest(ammo=18)
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    g.i32(p + R.P_EQUIPPED, 2)
    assert R.snapshot(g)["player"]["ammo"] is None


def test_failed_reload_selects_an_owned_loaded_gun_without_spawning_ammo(monkeypatch):
    from test_re6_switch_equip import NativeBridge
    bridge = NativeBridge()
    bot = R.Bot(stats={}, equip=bridge)
    p = {"ptr": 123, "generation": 1, "pos": (0, 0, 0), "ammo": 0, "equipped": 0,
         "guns": {0x107: 0, 0x111: 1, 0x108: 2}, "gun_ammo": {0: 0, 1: 30, 2: 5}}
    monkeypatch.setattr(R, "AUTO_SWITCH", False)
    assert bot._weapon_switch(p, 0) is None
    assert bot._weapon_switch(p, R.EMPTY_RELOAD_WAIT_S - .01) is None
    assert bridge.targets == []
    assert bot._weapon_switch(p, R.EMPTY_RELOAD_WAIT_S + .01) == {"hold": ()}
    assert bridge.targets == [1]
    assert p["gun_ammo"] == {0: 0, 1: 30, 2: 5}
    p.update(equipped=1, ammo=30)
    monkeypatch.setattr(R, "WANT_WEAPON", 0)
    monkeypatch.setattr(R, "WANT_WEAPON_AT", 100)
    assert bot._weapon_switch(p, 4) is None
    assert bridge.targets == [1]                            # never bounce back to the now-empty preferred weapon


def test_successful_reload_cancels_empty_weapon_fallback():
    from test_re6_switch_equip import NativeBridge
    bridge = NativeBridge()
    bot = R.Bot(stats={}, equip=bridge)
    p = {"ptr": 123, "generation": 1, "pos": (0, 0, 0), "ammo": 0, "equipped": 0,
         "guns": {0x107: 0, 0x111: 1}, "gun_ammo": {0: 0, 1: 30}}
    bot._weapon_switch(p, 0)
    p.update(ammo=7, gun_ammo={0: 7, 1: 30})
    assert bot._weapon_switch(p, 4) is None
    assert bridge.targets == []


def test_an_empty_unlocked_primary_does_not_redirect_a_loaded_fallback():
    from test_re6_switch_equip import NativeBridge
    bridge = NativeBridge()
    bot = R.Bot(stats={}, equip=bridge)
    bot._operator_primary = {"item": 7, "locked": False}
    p = {"ptr": 123, "generation": 1, "pos": (0, 0, 0), "ammo": 0, "equipped": 0,
         "guns": {0x107: 0, 0x111: 1}, "gun_ammo": {0: 0, 1: 30}}
    bot._weapon_switch(p, 0)
    bot._weapon_switch(p, 4)
    assert bridge.targets == [1]


def test_no_loaded_gun_means_bounded_reload_retries_and_no_empty_trigger_pulls():
    bot, clock, snap = contact_brain(ammo=0)
    snap["player"].update(guns={0x107: 0}, gun_ammo={0: 0})
    acts = run(bot, snap, clock, 200)
    assert sum("y" in a.get("hold", ()) for a in acts) <= 3
    assert all("zr" not in a.get("hold", ()) for a in acts)
    assert bot.stats["shots"] == 0


def test_loaded_fallback_releases_inputs_between_native_requests_then_times_out():
    from test_re6_switch_equip import NativeBridge
    bridge = NativeBridge()
    bot, clock, snap = contact_brain(ammo=0)
    bot.native_equip = bridge
    bot.held = lambda p, now: False
    p = snap["player"]
    p.update(guns={0x107: 0, 0x111: 1}, gun_ammo={0: 0, 1: 30})
    snap["enemies"][0]["pos"] = (0.0, 0.0, 75.0)
    bot._weapon_switch(p, 0)
    clock[0] = R.EMPTY_RELOAD_WAIT_S + .01
    acts = run(bot, snap, clock, 12)
    assert acts == [{"hold": ()}] * 12                    # no crowd kick restarts the busy action
    assert bridge.targets and set(bridge.targets) == {1}
    assert bot.stats["native_equip_state"] == "requested"
    clock[0] += 2.0
    assert bot._weapon_switch(p, clock[0]) is None
    assert bot.weapon_rest > clock[0]                    # refusal cannot produce an endless input hold


def test_loaded_fallback_settle_window_does_not_delay_critical_tablets():
    from test_re6_switch_equip import NativeBridge
    bridge = NativeBridge()
    bot = R.Bot(stats={}, equip=bridge)
    p = {"ptr": 123, "generation": 1, "pos": (0, 0, 0), "ammo": 0, "equipped": 0,
         "guns": {0x107: 0, 0x111: 1}, "gun_ammo": {0: 0, 1: 30},
         "hp": 100, "hp_max": 1000, "tablets": 5}
    bot._weapon_switch(p, 0)
    assert bot._weapon_switch(p, 4) is None
    assert bridge.targets == []


def test_uncertain_loaded_weapon_is_skipped_without_retrying_its_publication():
    from test_re6_switch_equip import NativeBridge
    class RefusedFirst(NativeBridge):
        def select(self, p, index):
            result = super().select(p, index)
            if index == 1:
                result.update(state='unconfirmed', reason='previous_request_unconfirmed')
            return result
    bridge = RefusedFirst()
    bot = R.Bot(stats={}, equip=bridge)
    p = {'ptr': 123, 'generation': 1, 'pos': (0, 0, 0), 'ammo': 0, 'equipped': 0,
         'guns': {0x107: 0, 0x111: 1, 0x108: 2}, 'gun_ammo': {0: 0, 1: 30, 2: 5}}
    bot._weapon_switch(p, 0)
    bot._weapon_switch(p, 4)
    assert bot.stats['weapon_switches'] == 0
    assert bot.stats['empty_weapon_reason'] == 'previous_request_unconfirmed'
    bot._weapon_switch(p, 4.4)
    assert bridge.targets == [1, 2]
    assert bot.stats['weapon_switches'] == 1
    assert p['gun_ammo'] == {0: 0, 1: 30, 2: 5}


def test_a_different_pending_kind_cannot_count_as_the_loaded_weapon_request():
    class WrongTicket:
        def select(self, p, index):
            return {'state': 'pending', 'kind': 0x115, 'index': 11}
    bot = R.Bot(stats={}, equip=WrongTicket())
    p = {'ptr': 123, 'generation': 1, 'pos': (0, 0, 0), 'ammo': 0, 'equipped': 0,
         'guns': {0x107: 0, 0x111: 1}, 'gun_ammo': {0: 0, 1: 30}}
    bot._weapon_switch(p, 0)
    bot._weapon_switch(p, 4)
    assert bot.stats['weapon_switches'] == 0
    assert bot.stats['empty_weapon_reason'] == 'target_request_mismatch'


def test_ordinary_weapon_cycle_waits_for_idle_native_context_and_actual_ammo_readback():
    from test_re6_switch_equip import NativeBridge
    class Refused(NativeBridge):
        ready = False
        def select(self, p, index):
            result = super().select(p, index)
            result.update(state='unconfirmed', reason='previous_request_unconfirmed')
            return result
        def cycle_ready(self, p, index):
            return self.ready
    bridge = Refused()
    bot = R.Bot(stats={}, equip=bridge)
    p = {'ptr': 123, 'generation': 1, 'pos': (0, 0, 0), 'ammo': 0, 'equipped': 0,
         'guns': {0x107: 0, 0x111: 1}, 'gun_ammo': {0: 0, 1: 30}}
    bot._weapon_switch(p, 0)
    bot._weapon_switch(p, 4)
    assert bot._weapon_switch(p, 4.4) is None             # unresolved/free-state refusal cannot cause pad input
    bridge.ready = True
    assert bot._weapon_switch(p, 4.5) == {'tap': 'dright'}
    assert bot._weapon_switch(p, 4.6) == {'hold': ()}      # releases edge; no repeated cycle before readback
    p.update(equipped=1, ammo=30)
    assert bot._weapon_switch(p, 4.7) is None
    assert bot.stats['empty_weapon_cycles'] == 1
    assert p['gun_ammo'] == {0: 0, 1: 30}


def test_optional_ordnance_waits_until_the_empty_gun_has_a_loaded_replacement(monkeypatch):
    bot = R.Bot(stats={})
    p = {'pos': (0, 0, 0), 'ammo': 0, 'equipped': 0, 'gun_ammo': {0: 0, 1: 30},
         'bomb': {'count': 20, 'out': False}, 'nades': {0x115: (11, 20)}}
    monkeypatch.setattr(R, 'NADES', True)
    monkeypatch.setattr(R, 'FLASH', True)
    monkeypatch.setattr(R, 'BOMBS', True)
    assert bot._nade(p, [], [], lambda e: 10, 0, {}, 10) is None
    assert bot.nade is None
    assert bot._bomb(p, [], lambda e: 10, 0, {}, 10) is None
    assert bot.bomb_phase is None
    assert R.NADES and R.FLASH and R.BOMBS              # policy priority does not mutate operator configuration


def test_native_ack_without_equipped_readback_eventually_uses_guarded_normal_input():
    from test_re6_switch_equip import NativeBridge
    class Acknowledged(NativeBridge):
        def cycle_ready(self, p, index):
            return True
    bot = R.Bot(stats={}, equip=Acknowledged())
    p = {'ptr': 123, 'generation': 1, 'pos': (0, 0, 0), 'ammo': 0, 'equipped': 0,
         'guns': {0x107: 0, 0x111: 1}, 'gun_ammo': {0: 0, 1: 30}}
    bot._weapon_switch(p, 0)
    assert bot._weapon_switch(p, 4) == {'hold': ()}
    assert bot._weapon_switch(p, 5.6) is None
    assert bot._weapon_switch(p, 5.7) == {'tap': 'dright'}
    assert bot._weapon_switch(p, 5.8) == {'hold': ()}


def test_empty_locked_preference_yields_to_existing_loaded_gun():
    from test_re6_switch_equip import NativeBridge
    bridge = NativeBridge()
    bot = R.Bot(stats={}, equip=bridge)
    bot._operator_primary = {"item": 7, "locked": True}
    p = {"ptr": 123, "generation": 1, "pos": (0, 0, 0), "ammo": 0, "equipped": 0,
         "guns": {0x107: 0, 0x111: 1}, "gun_ammo": {0: 0, 1: 30}}
    bot._weapon_switch(p, 0)
    assert bot._weapon_switch(p, 4) == {"hold": ()}
    assert bridge.targets == [1]
    assert p["gun_ammo"] == {0: 0, 1: 30}
