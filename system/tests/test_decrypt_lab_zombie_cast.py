"""Zombies -> cast: which enemy archive wears which character, and which ones the tree even holds.

The MercMode panel's "Zombies -> cast" action has to cover EVERY enemy archive a round spawns, because RE5's round
reads sEnemy as "uEm10 / uEm11 Majini, uEm21, uEm62" while its driver also names uEm6c / uEm71 - swapping one arc
left a round looking stock (measured 2026-11-06: three ordinary Majini). These tests pin the two decisions that make
the whole-set build correct: nobody is left without a donor, and no two enemies get the same one until the cast is
exhausted.
"""
from gbox import decrypt_lab as L
from gbox import skin_swap


def test_every_enemy_arc_gets_a_donor_and_none_is_left_out():
    arcs = list(skin_swap.ZOMBIE_ARCS["010018100CD46000"])
    worn = L.zombie_donors(["chris", "sheva", "jill", "wesker"], arcs)
    assert set(worn) == set(arcs)
    assert all(donor for donor in worn.values())


def test_enemies_get_different_donors_until_the_cast_runs_out():
    arcs = list(skin_swap.ZOMBIE_ARCS["010018100CD46000"])
    cast = ["chris", "sheva", "jill", "wesker", "josh", "excella"]
    worn = L.zombie_donors(cast, arcs[:6])
    assert len(set(worn.values())) == 6, "six enemies should show six different characters"
    # a cast smaller than the enemy set repeats, but only after every member has been used once
    small = L.zombie_donors(["chris", "sheva"], arcs[:6])
    order = list(small.values())
    assert order[:2] == ["chris", "sheva"]
    assert set(order[:2]) == {"chris", "sheva"}


def test_the_rotation_start_moves_so_a_rebuild_is_not_identical():
    arcs = list(skin_swap.ZOMBIE_ARCS["010018100CD46000"])[:3]
    cast = ["chris", "sheva", "jill"]
    first = list(L.zombie_donors(cast, arcs).values())
    second = list(L.zombie_donors(cast, arcs, start=1).values())
    assert first != second
    assert set(first) == set(second) == set(cast)


def test_an_enemy_archive_the_tree_does_not_hold_is_reported_not_failed():
    arc = skin_swap.ZOMBIE_ARCS["010018100CD46000"][0]
    rows = L.zombie_cast_plan("010018100CD46000", [], ["chris"])
    assert rows and all(row["status"] == "absent" for row in rows)
    assert [row["arc"] for row in rows][0] == arc
    # the ones that ARE on disk are planned, with a donor
    rows = L.zombie_cast_plan("010018100CD46000", [arc], ["chris"])
    planned = [row for row in rows if row["status"] == "planned"]
    assert planned == [{"arc": arc, "donor": "chris", "status": "planned"}]


def test_a_title_with_no_enemy_map_plans_nothing():
    assert L.zombie_cast_plan("0000000000000000", ["whatever.arc"], ["chris"]) == []
    assert L.zombie_donors([], ["a"]) == {}
    assert L.zombie_donors(["chris"], []) == {}
