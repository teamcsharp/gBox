"""RE4 weapon-choice policy delegation tests: one shared policy (weapon_choice) keyed on
families, mapped from RE4 item ids; behaviour mirrors re5_weapons.suitability."""
import math

import pytest

from gbox.mercs import weapon_choice
from gbox.mercs.titles import re4_weapon_policy as pol
from gbox.mercs.titles import re4_weapons as re4


def item(iid, loaded=10, in_use=True):
    return {"id": iid, "name": re4.name(iid), "in_use": in_use, "loaded": loaded}


def snap(d=500.0, hp_max=100, enemies=0):
    # player at origin, target at (d, 0); enemies optionally packed within CROWD_RADIUS
    return {"player": {"pos": (0.0, 0.0, 0.0)},
            "enemies": tuple({"pos": (d + 30.0 * k, 0.0, 0.0), "hp": 1} for k in range(enemies))}


def target(d=500.0, hp_max=100):
    return {"pos": (d, 0.0, 0.0), "hp": 1, "hp_max": hp_max}


# --- family mapping: every Mercenaries loadout gun maps, and matches its weapon-table class
@pytest.mark.parametrize("iid,cls", [(0x27, 0x04), (0x94, 0x21), (0x2F, 0x0A), (0x2A, 0x06), (0x30, 0x0B)])
def test_loadout_weapons_have_families(iid, cls):
    assert re4.CLASS_OF[iid] == cls
    assert pol.family(iid) in pol.DIRECT


@pytest.mark.parametrize("iid,fam", [(0x23, "handgun"), (0x27, "handgun"), (0x25, "handgun"),
                                     (0x2C, "shotgun"), (0x2D, "shotgun"), (0x94, "shotgun"),
                                     (0x2E, "rifle"), (0x2F, "rifle"), (0x6C, "rifle"),
                                     (0x29, "magnum"), (0x2A, "magnum"),
                                     (0x30, "automatic"), (0x3E, "automatic")])
def test_family_of(iid, fam):
    assert pol.family(iid) == fam


def test_non_direct_families_exist_but_score_floor():
    assert pol.family(0x52) == "bow"
    assert pol.family(0x35) == "rocket"
    assert pol.suitability(item(0x52), snap(), target()) == -1000.0


def test_unknown_item_scores_floor():
    assert pol.suitability(item(0x05), snap(), target()) == -1000.0  # First Aid Spray


def test_unloaded_or_unused_scores_floor():
    assert pol.suitability(item(0x27, loaded=0), snap(), target()) == -1000.0
    assert pol.suitability(item(0x27, in_use=False), snap(), target()) == -1000.0


def test_missing_snapshot_scores_floor():
    assert pol.suitability(item(0x27), {}, target()) == -1000.0


# --- the shared policy, through the RE4 mapping (mirrors test_re5_weapons expectations)
def test_shotgun_wins_close_crowd():
    s, t = snap(d=400, enemies=4), target(d=400)
    shot = pol.suitability(item(0x2C), s, t)
    hand = pol.suitability(item(0x27), s, t)
    assert shot == weapon_choice.family_score("shotgun", 400, False, True) + 10.0
    assert shot > hand


def test_shotgun_loses_at_long_range():
    s, t = snap(d=2000), target(d=2000)
    assert pol.suitability(item(0x2C), s, t) < pol.suitability(item(0x2E), s, t)


def test_rifle_wins_long():
    s, t = snap(d=2000), target(d=2000)
    assert pol.suitability(item(0x2E), s, t) == 50.0
    assert pol.suitability(item(0x2E), s, t) > pol.suitability(item(0x27), s, t)


def test_magnum_only_for_boss():
    s, t = snap(d=400), target(d=400, hp_max=weapon_choice.BOSS_HP_MIN)
    assert pol.suitability(item(0x2A), s, t) == 60.0
    mob = target(d=400, hp_max=weapon_choice.BOSS_HP_MIN - 1)
    assert pol.suitability(item(0x2A), s, mob) == 48.0


def test_crowd_needs_three_neighbours():
    s, t = snap(d=400, enemies=2), target(d=400)
    shot = pol.suitability(item(0x2C), s, t)
    assert shot == weapon_choice.family_score("shotgun", 400, False, False)  # no crowd bonus
    assert pol.suitability(item(0x2C), snap(d=400, enemies=3), target(d=400)) == shot + 10.0


# --- best_item picks across a real decoded Mercenaries loadout
def _decoded_loadout(character):
    out = []
    for iid, count in re4.MERC_LOADOUTS[character]["items"]:
        if pol.family(iid) in pol.DIRECT:
            out.append(item(iid, loaded=5))
    return out


def test_best_item_leon_long_range_prefers_nothing_worse_than_default():
    items = _decoded_loadout(0)  # Blacktail + Riot Gun
    s, t = snap(d=2000), target(d=2000)
    best = pol.best_item(items, s, t)
    assert best["id"] == 0x27  # rifle-class score beats far shotgun (15) with handgun 30


def test_best_item_wesker_close_crowd_magnum_boss():
    items = _decoded_loadout(5)  # Handgun + Killer7 + semi-auto rifle
    s, t = snap(d=400, enemies=4), target(d=400, hp_max=5000)
    assert pol.best_item(items, s, t)["id"] == 0x2A  # magnum 60 beats shotgun-less field


def test_best_item_none_when_all_empty():
    items = [item(0x27, loaded=0), item(0x2C, loaded=0)]
    assert pol.best_item(items, snap(), target()) is None


def test_decode_item_roundtrip_feeds_policy():
    # a real 14-byte item record (Blacktail, loaded 7) decodes and scores
    b = bytes.fromhex("27000100010000003800" + "00000000")
    it = re4.decode_item(b)
    assert it["id"] == 0x27 and it["in_use"]
    it["loaded"] = it.get("loaded", 0) or 7
    assert pol.suitability(it, snap(), target()) > -1000.0
