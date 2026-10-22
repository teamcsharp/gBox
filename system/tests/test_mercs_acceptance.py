import json
import math
import pathlib

from gbox.mercs import acceptance as A

FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "re5_run9_acceptance.json").read_text())
SUMM = {int(k): v for k, v in FX["summaries"].items()}


def S(sample, rnd, score, kills, timer, **kw):
    return {"sample": sample, "round": rnd, "score": score, "kills": kills, "timer": timer, "hp": 30, "hp_max": 100, **kw}


def crit(r, name):
    return r["criteria"][name]


def test_fixture_provenance_and_run9_rounds():
    assert len(FX["provenance"]["sha256"]) == 64 and FX["provenance"]["modified"] is True
    run = A.evaluate_run(FX["samples"], SUMM)
    r1, r2 = run["rounds"]
    assert (r1["round"], r2["round"]) == (1, 2)
    # round 1: the post-reset sample (score 0 / timer 120, still tagged round 1) is excluded, not final
    assert r1["excluded_post_reset_samples"] >= 1
    assert r1["final"] == {"score": 10860, "kills": 23, "timer": 0.0}
    assert r2["final"] == {"score": 10860, "kills": 23, "timer": 0.0}
    for r in (r1, r2):
        assert r["ending"] == "timeout" and r["modified"] is True
        sr = crit(r, "score_rank")
        assert sr["status"] == A.FAILED and sr["rank"] == "C" and sr["shortfall"] == 49140


def test_run9_denominators_are_per_round_driver_counters():
    r1, r2 = A.evaluate_run(FX["samples"], SUMM)["rounds"]
    assert (r1["counters"]["observed_shot_events"], r1["counters"]["associated_hits"]) == (275, 42)
    assert (r2["counters"]["observed_shot_events"], r2["counters"]["associated_hits"]) == (317, 31)
    assert "not exact projectiles" in r1["counter_note"]


def test_run9_modified_survival_unknown_and_unknowns_stay_unknown():
    r1 = A.evaluate_run(FX["samples"], SUMM)["rounds"][0]
    assert crit(r1, "survival")["status"] == A.UNKNOWN and crit(r1, "survival")["modified"] is True
    for name in ("healing", "boss_kills", "headshots", "combos", "group_kills", "items", "melee_qte_time"):
        assert crit(r1, name)["status"] == A.UNKNOWN, name
    assert crit(r1, "headshots")["status"] != A.PASSED
    assert crit(r1, "time_bonus")["status"] == A.FAILED   # 10 presses issued, no clock rise
    assert crit(r1, "time_extension")["status"] == A.FAILED and crit(r1, "time_extension")["gained_s"] == 0
    assert crit(r1, "navigation")["status"] == A.FAILED
    assert crit(r1, "threat_clearance")["status"] == A.UNKNOWN


def test_round_isolation_second_round_not_polluted_by_first():
    samples = [S(1, 1, 0, 0, 120), S(2, 1, 5000, 10, 3), S(3, 1, 0, 0, 120),  # leaked reset sample tagged round 1
               S(4, 2, 0, 0, 120), S(5, 2, 300, 1, 100)]
    r1, r2 = A.evaluate_run(samples)["rounds"]
    assert r1["final"]["score"] == 5000 and r1["excluded_post_reset_samples"] == 1
    assert r2["final"]["score"] == 300 and r2["samples"] == 2


def test_natural_finish_versus_timeout_versus_truncated():
    rules = A.RE5_RULES
    s = [S(1, 1, 0, 0, 120), S(2, 1, 61000, 100, 40)]
    assert A.evaluate_round(s, rules, {"finished_naturally": True})["ending"] == "natural_finish"
    cut = A.evaluate_round(s, rules)
    assert cut["ending"] is None and crit(cut, "score_rank")["status"] == A.UNKNOWN   # truncated: partial, not a result
    done = A.evaluate_round(s + [S(3, 1, 61000, 100, 0)], rules)
    assert done["ending"] == "timeout" and crit(done, "score_rank")["status"] == A.PASSED


def test_counter_decrease_without_reset_is_flagged_and_not_used_as_final():
    s = [S(1, 1, 0, 0, 120), S(2, 1, 900, 3, 100), S(3, 1, 600, 2, 90), S(4, 1, 1200, 4, 0)]
    r = A.evaluate_round(s, A.RE5_RULES)
    assert r["counter_anomalies"] and {a["counter"] for a in r["counter_anomalies"]} == {"score", "kills"}
    assert r["final"]["score"] == 1200


def test_absent_invalid_nan_values_never_become_zero_or_success():
    s = [S(1, 1, float("nan"), None, "x"), S(2, 1, True, -5, float("inf"))]
    r = A.evaluate_round(s, A.RE5_RULES, modified=False)
    assert r["final"] == {"score": None, "kills": None, "timer": None}
    assert crit(r, "score_rank")["status"] == A.UNKNOWN and crit(r, "kills")["status"] == A.UNKNOWN
    assert crit(r, "time_extension")["status"] == A.UNKNOWN and crit(r, "ending")["status"] == A.UNKNOWN
    assert crit(r, "survival")["status"] in (A.PASSED, A.UNKNOWN)
    assert A.num(float("nan")) is None and A.num("5") is None and A.num(False) is None and A.num(0) == 0


def test_missing_visibility_is_unknown_blocked_geometry_is_not_exposed():
    base = {"nearest_enemy_distance_cm": 200}
    unk = A.evaluate_round([S(1, 1, 0, 0, 100, **base), S(2, 1, 0, 0, 90, **base)], A.RE5_RULES)
    assert crit(unk, "threat_clearance")["status"] == A.UNKNOWN
    blk = A.evaluate_round([S(i, 1, 0, 0, 100 - i, nearest_enemy_visible=False, **base) for i in range(3)], A.RE5_RULES)
    assert crit(blk, "threat_clearance")["status"] == A.PASSED
    exp = A.evaluate_round([S(i, 1, 0, 0, 100 - i, nearest_enemy_visible=True, **base) for i in range(3)], A.RE5_RULES)
    assert crit(exp, "threat_clearance")["status"] == A.FAILED
    assert A.recommend({"nearest_enemy_distance_cm": 200, "nearest_enemy_visible": None})["visibility"] == "unknown"


def test_failed_pickup_versus_observed_clock_increase():
    flat = [S(1, 1, 0, 0, 100), S(2, 1, 0, 0, 99), S(3, 1, 0, 0, 98)]
    failed = A.evaluate_round(flat, A.RE5_RULES, {"prompt_presses": 4})
    assert crit(failed, "time_bonus")["status"] == A.FAILED
    claim = A.evaluate_round(flat, A.RE5_RULES, {"bonuses_taken": 2})
    assert crit(claim, "time_bonus")["status"] == A.UNKNOWN          # a driver claim is not RAM evidence
    jump = [S(1, 1, 0, 0, 100), S(2, 1, 0, 0, 99), S(3, 1, 0, 0, 114.5)]
    ok = A.evaluate_round(jump, A.RE5_RULES, {"prompt_presses": 4})
    assert crit(ok, "time_bonus")["status"] == A.PASSED and crit(ok, "time_extension")["gained_s"] == 15.5


def test_no_double_counting_replayed_samples():
    s = [S(1, 1, 0, 0, 100), S(2, 1, 0, 0, 90), S(2, 1, 0, 0, 90), S(3, 1, 0, 0, 105), S(3, 1, 0, 0, 105)]
    r = A.evaluate_round([x for g in A.split_rounds(s).values() for x in g["samples"]], A.RE5_RULES)
    assert r["samples"] == 3 and crit(r, "time_extension")["gained_s"] == 15


def test_re5_melee_five_seconds_does_not_inherit_re6_counter_rule():
    s = [S(1, 1, 0, 0, 100), S(2, 1, 300, 1, 105)]                  # +5 s with one kill
    re5 = A.evaluate_round(s, A.RE5_RULES)
    assert crit(re5, "melee_qte_time")["status"] == A.PASSED
    assert crit(re5, "time_bonus")["status"] != A.PASSED             # explained by the melee kill, not a pickup
    s10 = [S(1, 1, 0, 0, 100), S(2, 1, 300, 1, 110)]                 # +10 s with one kill
    re5_10 = A.evaluate_round(s10, A.RE5_RULES)
    assert crit(re5_10, "melee_qte_time")["status"] == A.UNKNOWN     # RE5 has no +10 counter rule
    assert crit(re5_10, "time_bonus")["status"] == A.PASSED          # unexplained rise stays a bonus candidate
    re6 = A.evaluate_round(s10, A.RE6_RULES)
    assert A.RE6_RULES["kill_counter_time_s"] == 10.0 and crit(re6, "time_bonus")["status"] != A.PASSED
    assert A.RE5_RULES["kill_counter_time_s"] is None


def test_modified_run_labeled_and_not_performance():
    r = A.evaluate_round([S(1, 1, 0, 0, 120, hp_max=30000), S(2, 1, 100, 1, 0, hp_max=30000)], A.RE5_RULES)
    assert r["modified"] is True and crit(r, "survival")["status"] == A.UNKNOWN
    plain = A.evaluate_round([S(1, 1, 0, 0, 120), S(2, 1, 100, 1, 0)], A.RE5_RULES)
    assert plain["modified"] is False and crit(plain, "survival")["status"] == A.PASSED


def test_policy_priority_threat_outranks_optional_work_qte_and_heal_preempt():
    opt = {"time_bonus_near": True, "melee_ready": True, "weapon_change": True, "travel": True}
    assert A.recommend(dict(opt, nearest_enemy_distance_cm=300, nearest_enemy_visible=True))["action"] == "clear_threat"
    assert A.recommend(dict(opt, nearest_enemy_distance_cm=300, nearest_enemy_visible=False))["action"] == "collect_time_bonus"
    assert A.recommend(dict(opt, nearest_enemy_distance_cm=300, nearest_enemy_visible=True, qte_escape=True))["action"] == "qte_escape"
    assert A.recommend(dict(opt, nearest_enemy_distance_cm=300, nearest_enemy_visible=True, healing_needed=True))["action"] == "heal"
    assert A.recommend({"nearest_enemy_distance_cm": math.nan, "travel": True})["action"] == "travel"
