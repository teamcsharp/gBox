"""The shared, title-agnostic weapon-choice policy: one rule for RE4/RE5/RE6.

These asserts encode the operator's stated policy (2026-10-24) directly, independent of any
title's weapon IDs, inventory layout or RAM offsets.
"""
from gbox.mercs import weapon_choice as WC


def test_operator_rule_by_distance_boss_and_crowd():
    # handgun is the default; automatic beats it; magnum for a boss; rifle only wins far out.
    assert WC.family_score("handgun", 500, False, False) == 30
    assert WC.family_score("automatic", 500, False, False) == 45
    assert WC.family_score("magnum", 500, False, False) == 48
    assert WC.family_score("magnum", 500, True, False) == 60
    assert WC.family_score("rifle", 500, False, False) == 25
    assert WC.family_score("rifle", 2000, False, False) == 50


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


def test_rejects_non_direct_families():
    try:
        WC.family_score("egg", 500, False, False)
    except ValueError:
        pass
    else:
        raise AssertionError("non-direct family must not score")
    assert WC.choose_family(500, False, False, loaded={}) is None
