from gbox.mercs.titles import re5_weapons as W
from gbox.re5_mods_tool import WEAPONS
from gbox.mercs.titles.re5_eggs import EGG_ID


def slot(wid, n, hand=False):
    return {"item": wid, "type": 1, "slot": n, "grid": n, "hand": hand, "rounds": 5}


def scene(distance=500, weapons=()):
    target = {"pos": (0, 0, distance), "hp": 800, "hp_max": 800}
    return {"player": {"pos": (0, 0, 0)}, "enemies": [target], "inventory": list(weapons)}, target


def test_all_verified_weapon_ids_have_an_explicit_policy():
    # Eggs live outside the first 0x24 modifiable weapon-table records.
    assert set(WEAPONS) | {EGG_ID & 0xff} == set(W.WEAPONS)
    assert W.WEAPONS[0x15].automatic


def test_close_splash_switches_to_loaded_magnum_without_guessing_launcher_ammo():
    s, e = scene(150, [slot(0x0C, 0, True), slot(0x1A, 1)])
    assert W.best_quick_slot(s, e)["item"] == 0x1A
    assert not W.fire_policy(0x0C, s, e, e["pos"])[0]
    assert not W.fire_policy(0x0D, s, e, e["pos"])[0]


def test_distant_target_does_not_switch_to_a_sniper_rifle():
    s, e = scene(2200, [slot(0x19, 1, True), slot(0x05, 3)])
    assert W.best_quick_slot(s, e) is None


def test_existing_rocket_or_sniper_switches_to_loaded_quick_slot_magnum():
    for weapon in (0x0D, 0x05, 0x1C, 0x20):
        s, e = scene(2200, [slot(weapon, 1, True), slot(0x0B, 3)])
        assert W.best_quick_slot(s, e)["item"] == 0x0B
    s["inventory"][1]["grid"] = 2
    assert W.best_quick_slot(s, e) is None


def test_quick_slot_uses_ui_grid_and_never_falls_back_to_storage_index():
    s, e = scene(200, [slot(0x0D, 0, True), slot(0x19, 1)])
    other = s["inventory"][1]
    other["grid"] = 5
    assert W.best_quick_slot(s, e) is other and W.quick_key(other) == "dright"
    other["slot"] = 12
    assert W.best_quick_slot(s, e) is other
    assert W.best_quick_slot(s, e, {W.inventory_key(other)}) is None
    other["slot"] = 1
    for grid in (None, 9, -1, "1", True):
        other["grid"] = grid
        assert W.quick_key(other) is None and W.best_quick_slot(s, e) is None
    del other["grid"]
    assert W.best_quick_slot(s, e) is None


def test_close_crowd_prefers_shotgun_and_usable_current_does_not_churn():
    s, e = scene(500, [slot(0x02, 1, True), slot(0x19, 3)])
    s["enemies"] *= 3
    assert W.best_quick_slot(s, e)["item"] == 0x19
    s["inventory"] = [slot(0x1A, 1, True), slot(0x09, 3)]
    assert W.best_quick_slot(s, e) is None


def test_splash_clearance_accounts_for_partner_and_does_not_trust_health_mod():
    s, e = scene(1500)
    assert W.fire_policy(0x0D, s, e, e["pos"])[0]
    s["partner"] = {"pos": (0, 0, 1400)}
    s["unlimited_health"] = True
    assert not W.fire_policy(0x0D, s, e, e["pos"])[0]


def test_unknown_and_unverified_trajectory_do_not_inherit_hitscan_permission():
    s, e = scene()
    for wid in (0x99, 0x06, 0x0A, 0x0F, 0x22):
        assert not W.fire_policy(wid, s, e, e["pos"])[0]
    assert W.fire_policy(0x1A, s, e, e["pos"])[0]
