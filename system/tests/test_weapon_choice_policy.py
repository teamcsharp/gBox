"""The shared, title-agnostic weapon-choice policy: one rule for RE4/RE5/RE6.

These asserts encode the operator's stated policy (2026-11-10) directly, independent of any
title's weapon IDs, inventory layout or RAM offsets.
"""
from gbox.mercs import weapon_choice as WC


def test_operator_rule_by_distance_boss_and_crowd():
    # Operator override (2026-11-10): the handgun is a last-resort fallback, never a
    # preferred pick -- every direct-fire family outranks it. Rapid-fire magnum / shotgun /
    # machine gun / SMG are reached for first; the handgun only fires when nothing else is
    # loaded.
    assert WC.family_score("handgun", 500, False, False) == WC.HANDGUN_FALLBACK
    assert WC.family_score("automatic", 500, False, False) == 45
    assert WC.family_score("magnum", 500, False, False) == 48
    assert WC.family_score("magnum", 500, True, False) == 60
    assert WC.family_score("rifle", 500, False, False) == 25
    assert WC.family_score("rifle", 2000, False, False) == 50


def test_handgun_still_scores_above_zero_so_it_fires_when_only_loaded():
    # Never refuse to fire: the handgun must still be usable, just not chosen over a
    # preferred family.
    assert WC.HANDGUN_FALLBACK > 0
    assert WC.family_score("handgun", 400, False, False) == WC.HANDGUN_FALLBACK
    assert WC.family_score("handgun", 2000, False, False) == WC.HANDGUN_FALLBACK


def test_shotgun_up_close_into_a_crowd():
    assert WC.family_score("shotgun", 400, False, False) == 55
    assert WC.family_score("shotgun", 2000, False, False) == 15
    assert WC.shotgun_crowd_bonus("shotgun", True, 400) == 10
    assert WC.shotgun_crowd_bonus("shotgun", True, 2000) == 0
    assert WC.shotgun_crowd_bonus("handgun", True, 400) == 0


def test_choose_family_picks_the_right_family_for_each_case():
    assert WC.choose_family(2000, False, False) == "rifle"
    assert WC.choose_family(1500, True, False) == "magnum"
    assert WC.choose_family(400, False, False) == "shotgun"  # automatic 45 < shotgun 55
    assert WC.choose_family(400, False, False,
                            loaded={"magnum": 70}) == "magnum"  # caller override wins


def test_handgun_is_never_chosen_when_any_preferred_family_is_available():
    # Across close / mid / far with no caller override, choose_family must never settle on
    # the handgun: automatic (45), magnum (48), shotgun (55 close) and rifle (50 far) all
    # outrank the fallback (5). Only an explicit loaded-only override can force it back.
    for distance in (200, 400, 500, 1500, 2000, 4000):
        pick = WC.choose_family(distance, False, False)
        assert pick != "handgun", f"handgun chosen at {distance}cm"
    # A handgun-only loadout still resolves to the handgun (last resort, still fireable).
    assert WC.choose_family(500, False, False, loaded={"handgun": 1}) == "handgun"


def test_rejects_non_direct_families():
    try:
        WC.family_score("egg", 500, False, False)
    except ValueError:
        pass
    else:
        raise AssertionError("non-direct family must not score")
    assert WC.choose_family(500, False, False, loaded={}) is None
