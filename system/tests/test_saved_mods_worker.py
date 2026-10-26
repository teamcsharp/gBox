"""The worker side of saved menu settings (gbox/game_prefs.py): apply_saved puts each one on as the operator's own change,
and RE4 keeps the operator's choices so the bots' packages apply them instead of their defaults (like re5_mods' operator
overrides). Synthetic tool bodies: no game memory."""
import pytest

from gbox import re5_mods_tool as R5, re_mods_tool as R4


class G:
    def status(self):
        return {"ok": True}


@pytest.fixture
def re4(monkeypatch):
    calls = []

    def body(ad, op, **kw):
        calls.append((R4.canonical(op), kw.get("on"), kw.get("multiplier"), kw.get("count")))
        return {"op": R4.canonical(op), "verified": True}
    monkeypatch.setattr(R4, "_run", body)
    ad = object()
    yield ad, calls
    R4.STATE.pop(id(ad), None)


def test_re4_operator_choice_survives_the_bots_boot_package(re4):
    ad, calls = re4
    R4.run(ad, "combo_freeze", on=False, g=G(), operator=True)           # the PiP menu
    R4.run(ad, "combo_freeze", on=True, g=G())                            # mercs_bot / re4_merc_bot package
    R4.run(ad, "combo_time", multiplier=4.5, on=True, g=G(), operator=True)
    R4.run(ad, "combo_time", multiplier=3, g=G())
    R4.run(ad, "spawn_multiplier", count=1, on=False, g=G(), operator=True)
    R4.run(ad, "more_enemies", count=3, on=True, g=G())                   # an alias of spawn_multiplier
    assert calls == [("combo_freeze", False, 2.0, 0), ("combo_freeze", False, 2.0, 0),
                     ("combo_time", True, 4.5, 0), ("combo_time", True, 4.5, 0),
                     ("spawn_multiplier", False, 2.0, 1), ("spawn_multiplier", False, 2.0, 1)]
    R4.run(ad, "give", item="handgun", g=G())                             # not a kept setting: passes straight through
    assert calls[-1][0] == "give"


def test_an_unverified_operator_change_is_not_kept(monkeypatch, re4):
    ad, calls = re4
    monkeypatch.setattr(R4, "_run", lambda ad, op, **kw: calls.append(kw.get("on")) or {"op": op, "verified": False})
    R4.run(ad, "infinite_ammo", on=False, g=G(), operator=True)
    R4.run(ad, "infinite_ammo", on=True, g=G())
    assert calls == [False, True]


def test_the_operators_loadout_is_not_replaced_by_the_bots_loadout_ops(re4):
    ad, calls = re4
    R4.run(ad, "merc_loadout", character="leon", reset=True, g=G(), operator=True)     # Reset weapons
    package = R4.run(ad, "merc_loadout", character="leon", items=["handcannon"], on=True, g=G())
    per_round = R4.run(ad, "random_loadout", character="all", damage="99.9", on=True, g=G(), weapon="handcannon")
    assert package["skipped"] and per_round["skipped"] and package["verified"] and per_round["verified"]
    assert [c[0] for c in calls] == ["merc_loadout"], "only the operator's own loadout went in"


def test_re4_apply_saved_puts_each_setting_on_as_the_operators(re4):
    ad, calls = re4
    out = R4.apply_saved(ad, [{"name": "combo_freeze", "op": "combo_freeze", "on": False},
                              {"name": "combo_time", "op": "combo_time", "on": True, "multiplier": 4.5},
                              {"name": "loadout", "op": "merc_loadout", "reset": True, "character": "leon"},
                              {"name": "loadout2", "op": "merc_loadout", "items": ["rocket launcher"]},
                              {"name": "warp", "op": "warp"}], g=G())
    assert {n: r["verified"] for n, r in out["results"].items()} == {
        "combo_freeze": True, "combo_time": True, "loadout": True, "loadout2": False, "warp": False}
    assert out["verified"] is False and out["status"] == {"ok": True}
    R4.run(ad, "combo_freeze", on=True, g=G())
    assert calls[-1] == ("combo_freeze", False, 2.0, 0), "apply_saved made it the operator's choice"


def test_re4_apply_saved_reports_a_failing_item_and_carries_on(monkeypatch, re4):
    ad, _ = re4

    def body(ad, op, **kw):
        if R4.canonical(op) == "combo_time":
            raise RuntimeError("the game did not run the request (paused)")
        return {"op": op, "verified": True}
    monkeypatch.setattr(R4, "_run", body)
    out = R4.apply_saved(ad, [{"name": "combo_time", "op": "combo_time", "multiplier": 3},
                              {"name": "grenade_safe", "op": "grenade_safe", "on": True}], g=G())
    assert out["results"]["combo_time"] == {"op": "combo_time", "verified": False,
                                           "reason": "RuntimeError: the game did not run the request (paused)"}
    assert out["results"]["grenade_safe"]["verified"] is True


def test_re5_apply_saved_runs_each_saved_setting_with_operator_semantics(monkeypatch):
    calls = []

    def run(ad, op, multiplier=None, on=True, g=None, **extra):
        calls.append((op, multiplier, on, extra))
        if op == "turn_speed":
            raise RuntimeError("sParameter is not up yet (the game is still booting)")
        return {"op": op, "verified": op != "bullet_damage", "reason": "not confirmed"}
    monkeypatch.setattr(R5, "run", run)
    out = R5.apply_saved(object(), [{"name": "fire_rate", "op": "fire_rate", "on": True, "multiplier": 120.0},
                                    {"name": "mines", "op": "mines", "on": True, "multiplier": "only"},
                                    {"name": "weapon_override", "op": "weapon_override", "on": True, "weapon": 15,
                                     "only": True},
                                    {"name": "turn_speed", "op": "turn_speed", "on": True, "multiplier": 3},
                                    {"name": "bullet_damage", "op": "bullet_damage", "on": True, "multiplier": 10},
                                    {"name": "x", "op": "random_weapon"}], g=G())
    assert all(extra["operator"] is True for *_, extra in calls)
    assert calls[2] == ("weapon_override", None, True, {"operator": True, "weapon": 15, "only": True})
    assert calls[1][:3] == ("mines", "only", True)
    assert {n: r["verified"] for n, r in out["results"].items()} == {
        "fire_rate": True, "mines": True, "weapon_override": True, "turn_speed": False, "bullet_damage": False, "x": False}
    assert "still booting" in out["results"]["turn_speed"]["reason"]
    assert out["results"]["x"]["reason"] == "not a saved RE5 setting"
    assert [c[0] for c in calls] == ["fire_rate", "mines", "weapon_override", "turn_speed", "bullet_damage"]


def test_both_tools_accept_the_saved_ops_field():
    assert R5.RE5ModsIn(session_id="s", op="apply_saved", ops=[{"op": "infinite_ammo", "on": True}]).ops
    assert R4.REModsIn(session_id="s", op="apply_saved", ops=[{"op": "combo_freeze", "on": False}]).ops
