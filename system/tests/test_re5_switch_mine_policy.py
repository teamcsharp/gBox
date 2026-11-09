"""Persistent mine supply and fleeing integration, independent of selected slot/stage."""
from types import SimpleNamespace

from gbox import mercs_bot
from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_mods as SM
from tests.test_re5_switch_directives import BOMB, GUN, snap


def test_boot_round_ops_prepare_supply_before_native_inventory_exists(monkeypatch):
    calls = []
    monkeypatch.setattr(SM, "RE5Switch", lambda ad: object())
    monkeypatch.setattr(SM, "run", lambda *a, **kw: calls.append("round_loadout") or {})
    def maintain(ad, snapshot, **kw):
        assert snapshot is None and kw == {"enabled": False, "prepare_mines": True}
        calls.append("mine_templates")
        return {"mine_supply": {"verified": True, "status": "ready_next_round"}}
    monkeypatch.setattr(SM, "maintain", maintain)
    stats = {}
    assert mercs_bot.apply_ops(object(), [("loadout", {})], {"map_id": R.MAP_ID}, stats) == []
    assert calls == ["round_loadout", "mine_templates"]
    assert stats["mine_supply"]["status"] == "ready_next_round"


def test_driver_prepares_mines_before_play_and_reports_supply(monkeypatch):
    calls = []
    supply = {"verified": True, "effective": "next_round"}
    def maintain(ad, snapshot, **kw):
        calls.append(kw)
        return {"verified": True, "mine_supply": supply}
    monkeypatch.setattr(SM, "maintain", maintain)
    driver = R.RE5Switch()
    driver.stats = {}
    memory = SimpleNamespace(adapter=object())
    driver._mods(memory, None, False)
    assert calls == [{"enabled": False, "prepare_mines": True}]
    assert driver.stats["mine_supply"] == supply
    memory.mercs_no_modifications = True
    driver._mods(memory, None, False)
    assert len(calls) == 1


def test_due_mine_can_begin_during_flight_when_site_is_clear(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINE_EVERY_S", 30.0)
    clock = [0.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0])
    state = snap([(0.0, 0.0, 1500.0)], [dict(GUN), dict(BOMB)])
    bot.tick(state)
    bot.escape = (0.0, 35.0)
    clock[0] = 30.1
    assert bot.tick(state) == {"hold": ()}
    assert bot.doing == "mine" and bot.mines.state == "neutral"
    assert bot.escape is None


def test_held_player_is_not_interrupted_to_place_due_mine(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    clock = [0.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0])
    state = snap([(0.0, 0.0, 1500.0)], [dict(GUN), dict(BOMB)])
    bot.tick(state)
    state["player"]["motion"] = next(iter(R.MOTION_HELD))
    clock[0] = 31.0
    bot.tick(state)
    assert bot.doing == "held" and bot.mines.state == "idle"
