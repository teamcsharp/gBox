"""Reunion tradeoffs, close-threat interruption, and honest round evidence."""
import copy
import math

import pytest

from gbox.mercs.titles import re5_strategy as S


def snapshot(**changes):
    value = {"player": {"hp": 800, "hp_max": 1000, "pos": (0, 0, 0)},
             "timer": 120.0, "combo": 20, "combo_timer": 8.0, "enemies": []}
    value.update(changes)
    return value


def enemy(distance=200, **changes):
    value = {"hp": 500, "hp_max": 500, "pos": (0, 0, distance)}
    value.update(changes)
    return value


def test_no_combo_initial_time_collection_then_chain_protection():
    assert S.detour_allowed(snapshot(combo=0), 20)
    assert not S.detour_allowed(snapshot(combo=140, combo_timer=3), 20)
    assert S.detour_allowed(snapshot(combo=140, combo_timer=3), 0, at_bonus=True)


def test_emergency_clock_can_sacrifice_chain_but_never_travel_past_timeout():
    assert S.detour_allowed(snapshot(timer=10, combo_timer=1), 5)
    assert not S.detour_allowed(snapshot(timer=5, combo_timer=1), 5)
    assert not S.detour_allowed(snapshot(timer=5, combo_timer=1), 0, immediate_threat=True)


@pytest.mark.parametrize("eta", [None, -1, math.nan, math.inf, True])
def test_bad_eta_is_not_repaired_by_at_bonus(eta):
    assert not S.detour_allowed(snapshot(), eta, at_bonus=True)


def test_unknown_combo_window_does_not_imply_spare_time():
    assert not S.detour_allowed(snapshot(combo_timer=None), 1)
    assert not S.detour_allowed(snapshot(combo=None), 1)
    assert S.detour_allowed(snapshot(combo=0, combo_timer=None), 1)


def test_reunion_combo_chest_policy_and_positive_time_return():
    assert S.detour_allowed(snapshot(combo=49), 1, kind="combo")
    assert not S.detour_allowed(snapshot(combo=50), 1, kind="combo")
    assert not S.detour_allowed(snapshot(combo=0), 10, gain_s=5)
    assert S.detour_allowed(snapshot(combo=0), 10, gain_s=30)


def test_healing_route_overrides_combo_but_not_invalid_route():
    snap = snapshot(player={"hp": 250, "hp_max": 1000, "pos": (0, 0, 0)}, combo_timer=1)
    assert S.detour_allowed(snap, 2, kind="heal", immediate_threat=True)
    assert not S.detour_allowed(snap, 2, kind="heal", safe=False)
    assert not S.detour_allowed(snap, 2, kind="time")


@pytest.mark.parametrize("hp", [0, 1, None, math.nan])
def test_death_recovery_or_bad_health_never_enters_optional_policy(hp):
    snap = snapshot(player={"hp": hp, "hp_max": 1000, "pos": (0, 0, 0)})
    assert not S.detour_allowed(snap, 0)
    assert not S.melee_allowed(snap, eta=1, prompt_verified=True, lethal=True)
    assert not S.item_decision(snap, {"heal"}, heal_safe=True).allowed


def test_close_exposed_threat_interrupts_optional_travel_and_melee():
    snap = snapshot(enemies=[enemy(exposed=True)])
    assert S.close_exposed_threat(snap)
    assert not S.detour_allowed(snap, 0, at_bonus=True)
    assert not S.melee_allowed(snap, eta=1, prompt_verified=True, lethal=True)
    snap["enemies"][0]["exposed"] = False
    assert not S.close_exposed_threat(snap)
    assert S.detour_allowed(snap, 0, at_bonus=True)


def test_melee_requires_verified_kill_and_enough_combo_time():
    assert S.melee_allowed(snapshot(), eta=2, prompt_verified=True, lethal=True)
    assert not S.melee_allowed(snapshot(combo_timer=2), eta=2, prompt_verified=True, lethal=True)
    assert not S.melee_allowed(snapshot(), eta=2, prompt_verified=False, lethal=True)
    assert not S.melee_allowed(snapshot(), eta=2, prompt_verified=True, lethal=None)
    assert not S.melee_allowed(snapshot(), eta=2, prompt_verified=True, lethal=True, boss=True, boss_melees=1)
    assert S.MELEE_KILL_SECONDS == 5


def test_critical_target_dominates_boss_delay_heads_and_groups():
    snap = snapshot(combo_timer=1)
    close = S.target_priority(snap, enemy(300, is_boss=True), exposed=True)
    far = S.target_priority(snap, enemy(700), exposed=True, head_exposed=True,
                            immediate_threat=True, group_count=100)
    assert close > far
    assert S.target_priority(snap, enemy(200), exposed=True) > close


def test_critical_distance_order_is_strict_regardless_of_optional_target_labels():
    snap = snapshot()
    scores = [S.target_priority(snap, enemy(d, is_boss=(d == 100)), exposed=True,
                                head_exposed=(d == 300), group_count=5) for d in (100, 200, 300)]
    assert scores[0] > scores[1] > scores[2]


def test_hp_does_not_invent_boss_class_or_visibility():
    snap = snapshot()
    high_hp = enemy(600, hp_max=9000)
    ordinary = enemy(600)
    assert S.target_priority(snap, high_hp) == S.target_priority(snap, ordinary)
    assert S.target_priority(snap, ordinary, exposed=True) > S.target_priority(snap, high_hp)
    assert not S.close_exposed_threat(snapshot(enemies=[enemy(1, hp_max=9000)]))


def test_boss_delay_is_overridden_by_urgency_and_terminal_targets_rejected():
    snap = snapshot()
    boss, normal = enemy(600, is_boss=True), enemy(600)
    assert S.target_priority(snap, boss) < S.target_priority(snap, normal)
    urgent = snapshot(combo_timer=1)
    assert S.target_priority(urgent, boss, exposed=True) == S.target_priority(urgent, normal, exposed=True)
    assert S.target_priority(snap, enemy(hp=0)) == -math.inf
    assert S.target_priority(snap, enemy(pos=(math.nan, 0, 0))) == -math.inf


def test_item_use_requires_benefit_and_verified_safe_control():
    snap = snapshot()
    assert not S.item_decision(snap, {"grenade"}, cluster_count=4).allowed
    assert S.item_decision(snap, {"grenade"}, cluster_count=4, explosive_safe=True).action == "grenade"
    assert S.item_decision(snap, {"flash"}, flash_vulnerable=True, explosive_safe=True).action == "flash"
    assert not S.item_decision(snap, {"mine"}, approaching_threat=True).allowed
    assert S.item_decision(snap, {"mine"}, approaching_threat=True, mine_placement_safe=True).action == "mine"
    snap["enemies"] = [enemy(exposed=True)]
    assert not S.item_decision(snap, {"mine"}, approaching_threat=True, mine_placement_safe=True).allowed


def test_heal_item_precedes_offensive_item_use_and_red_herb_is_not_a_heal():
    snap = snapshot(player={"hp": 100, "hp_max": 1000, "pos": (0, 0, 0)})
    assert S.item_decision(snap, {"heal", "grenade"}, heal_safe=True,
                           explosive_safe=True, cluster_count=5).action == "heal"
    assert not S.item_decision(snap, {"red_herb"}, heal_safe=True).allowed


def test_round_evaluation_never_fills_gaps_from_proxies_or_high_score():
    observed = {"score": 100000, "kills": 90, "elapsed_s": 180, "bonus_s": 60,
                "bonuses_taken": 2, "qte_presses": 200, "finishers": 10, "headshots": 40}
    result = S.evaluate_round(observed)
    assert result["s_rank_observed"] is None
    assert result["survived"] is None
    assert result["observed"]["time"] == {"elapsed_s": 180}
    assert "melee_kills" in result["missing"] and "boss_kills" in result["missing"]
    assert result["derived"] == {"observed_kills_per_minute": 30.0}
    assert result["observed"]["proxies"]["bonus_s"] == 60


def test_only_completed_observed_result_can_report_s_rank():
    assert S.evaluate_round({"end_reason": "results", "result_rank": "SS"})["s_rank_observed"] is True
    dead = S.evaluate_round({"end_reason": "dead", "score": 100000, "result_rank": "SS"})
    assert dead["survived"] is False and dead["s_rank_observed"] is None
    assert S.evaluate_round({"end_reason": "results", "rank": "S"})["result_rank"] is None


def test_evaluator_rejects_invalid_counters_and_inconsistent_accuracy():
    result = S.evaluate_round({"kills": -1, "score": math.inf, "melee_kills": True,
                               "round_shots": 3, "round_hits": 4})
    assert set(result["invalid"]) == {"kills", "score", "melee_kills", "round_hits exceeds round_shots"}
    assert "observed_hit_fraction" not in result["derived"]
    assert S.evaluate_round({"round_shots": 10, "round_hits": 9})["derived"]["observed_hit_fraction"] == .9


def test_policy_never_mutates_caller_snapshot():
    snap = snapshot(enemies=[enemy(exposed=True)])
    before = copy.deepcopy(snap)
    S.detour_decision(snap, 2)
    S.target_priority(snap, snap["enemies"][0])
    S.item_decision(snap, {"mine"})
    S.evaluate_round({"kills": 2})
    assert snap == before
