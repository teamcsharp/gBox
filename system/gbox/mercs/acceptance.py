"""Pure Mercenaries run-acceptance contract (request #2964, run-acceptance-v1).

Offline and title-agnostic: it takes per-sample RAM observations (the ``combat_observation`` events a validation
sidecar writes) plus optional per-round driver summaries, and returns explicit ``passed`` / ``failed`` / ``unknown``
criteria with evidence references.  Title rules (rank table, melee clock, counter rule) are *data* (``RE5_RULES`` /
``RE6_RULES``); nothing here reads RAM, drives a pad or touches a live driver, and nothing here shows that gameplay
improved - it only grades what a run actually recorded.

Evidence vocabulary (kept apart on purpose):
  * RAM facts: score, kills, timer, hp (``samples``).
  * associated hits / shot events: driver counters ``round_hits`` / ``round_shots`` - not exact projectiles and not
    confirmed hit identity.
  * issued inputs: ``prompt_presses`` / ``qte_presses`` - an input is not an effect.
  * missing metrics stay ``unknown`` (never 0, never success).
"""
from __future__ import annotations

import math

PASSED, FAILED, UNKNOWN = "passed", "failed", "unknown"

RE5_RULES = {
    "title": "re5",
    "rank_scores": (("SS", 90000), ("S", 60000), ("A", 40000), ("B", 20000), ("C", 10000), ("D", 0)),
    "target_rank": "S",
    "start_timer_s": 120.0,
    "melee_kill_time_s": 5.0,        # RE5: a melee kill adds 5 s; knife kills do not
    "kill_counter_time_s": None,     # RE5 has no kill-counter time rule (RE6's +10 s must not leak in)
    "time_tolerance_s": 0.6,         # samples are ~1 s apart; a rise below this is jitter, not a bonus
    "near_threat_cm": 500.0,
    "modified_hp_at_least": 30000,   # HP at/above this means the HP/immunity patch ran, not ordinary play
}
RE6_RULES = dict(RE5_RULES, title="re6", melee_kill_time_s=None, kill_counter_time_s=10.0)


def num(v):
    """A finite non-negative number, else None (bool/str/NaN/inf/negative are invalid evidence)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        return None
    return v


def rank_of(score, rules):
    score = num(score)
    return None if score is None else next((r for r, at in rules["rank_scores"] if score >= at), None)


def _c(status, reason, evidence=None, **extra):
    return {"status": status, "reason": reason, "evidence": evidence or [], **extra}


def split_rounds(samples):
    """Group samples by their ``round`` tag and drop post-reset leakage: once the counters fall back to the next
    round's start (score/kills decrease, or the timer jumps up) the sample belongs to the next round even if the
    driver still tagged it with the old number.  Returns {round: {"samples": [...], "excluded": [...]}}."""
    out, seen = {}, set()
    for s in samples:
        key = s.get("id", s.get("sample", id(s)))
        rnd = s.get("round")
        if (rnd, key) in seen:        # no double counting of a replayed sample
            continue
        seen.add((rnd, key))
        out.setdefault(rnd, {"samples": [], "excluded": []})
    for rnd in out:
        rows = [s for s in samples if s.get("round") == rnd]
        keep, cut = [], False
        dedup = set()
        for s in rows:
            k = s.get("id", s.get("sample"))
            if k in dedup:
                continue
            dedup.add(k)
            if keep and not cut:
                p = keep[-1]
                sc, ps = num(s.get("score")), num(p.get("score"))
                ki, pk = num(s.get("kills")), num(p.get("kills"))
                t, pt = num(s.get("timer")), num(p.get("timer"))
                reset = (sc is not None and ps is not None and sc < ps) or (ki is not None and pk is not None and ki < pk)
                if reset and t is not None and pt is not None and t > pt:
                    cut = True        # round boundary leaked into this tag
            (out[rnd]["excluded"] if cut else out[rnd]["samples"]).append(s)
            if not cut:
                keep.append(s)
    return out


def _ref(s):
    return {"sample": s.get("sample"), "line": s.get("line")}


def _clock(samples, rules):
    """Observed clock rises (each adjacent pair once) and the kills gained in the same interval."""
    rises = []
    for a, b in zip(samples, samples[1:]):
        ta, tb = num(a.get("timer")), num(b.get("timer"))
        if ta is None or tb is None or tb <= ta + rules["time_tolerance_s"]:
            continue
        ka, kb = num(a.get("kills")), num(b.get("kills"))
        rises.append({"gain_s": round(tb - ta, 2), "kills_in_interval": None if ka is None or kb is None else kb - ka,
                      "from": _ref(a), "to": _ref(b)})
    return rises


def _attribute(rise, rules):
    """Name the cause of a clock rise from the title's own rules, else leave it unattributed."""
    k, g, tol = rise["kills_in_interval"], rise["gain_s"], 1.0
    mt, ct = rules.get("melee_kill_time_s"), rules.get("kill_counter_time_s")
    if k and mt and abs(g - mt * k) <= tol:
        return "melee_kill"
    if k and ct and abs(g - ct) <= tol:
        return "kill_counter"
    return "unattributed"


def evaluate_round(samples, rules, summary=None, round_no=None, modified=None, excluded=()):
    """Grade one round.  ``summary`` is the driver's round_return stats (counters, never RAM truth)."""
    summary = summary or {}
    samples = list(samples)
    last = samples[-1] if samples else {}
    crit = {}
    if modified is None:
        hp = [num(s.get("hp_max")) for s in samples]
        modified = any(h is not None and h >= rules["modified_hp_at_least"] for h in hp) or bool(summary.get("hit_immunity"))
    score, kills, timer = num(last.get("score")), num(last.get("kills")), num(last.get("timer"))
    # RAM score/kills can also be missing on the final sample: fall back to the best earlier RAM value, never to 0
    valid_scores = [num(s.get("score")) for s in samples if num(s.get("score")) is not None]
    score = max(valid_scores) if valid_scores else None
    valid_kills = [num(s.get("kills")) for s in samples if num(s.get("kills")) is not None]
    kills = max(valid_kills) if valid_kills else None
    ev_last = [_ref(last)] if last else []
    anomalies = [{"counter": k, "from": _ref(a), "to": _ref(b)} for k in ("score", "kills")
                 for a, b in zip(samples, samples[1:])
                 if num(a.get(k)) is not None and num(b.get(k)) is not None and num(b.get(k)) < num(a.get(k))]

    # --- survival / healing --------------------------------------------------------------------------------
    hps = [num(s.get("hp")) for s in samples if s.get("hp") is not None]
    if modified:
        crit["survival"] = _c(UNKNOWN, "modified run (HP/immunity patch): survival is not ordinary-play evidence", ev_last, modified=True)
        crit["healing"] = _c(UNKNOWN, "modified run: healing was never required or exercised", modified=True)
    elif not hps or all(h is None for h in hps):
        crit["survival"] = _c(UNKNOWN, "no valid hp samples")
        crit["healing"] = _c(UNKNOWN, "no healing events recorded")
    else:
        alive = [s.get("alive") for s in samples if s.get("alive") is not None]
        died = any(a is False for a in alive) or any(h == 0 for h in hps if h is not None)
        crit["survival"] = _c(FAILED if died else PASSED, "player dead in a sample" if died else "alive in every valid sample", ev_last)
        crit["healing"] = _c(UNKNOWN, "no healing events recorded")

    # --- natural finish vs timeout ---------------------------------------------------------------------------
    if timer is None:
        ending = None
        crit["ending"] = _c(UNKNOWN, "no valid final timer", ev_last)
    elif timer <= 0.0:
        ending = "timeout"
        crit["ending"] = _c(PASSED, "clock reached 0 (timeout)", ev_last, ending=ending)
    elif summary.get("finished_naturally") or summary.get("quota_complete"):
        ending = "natural_finish"
        crit["ending"] = _c(PASSED, "round completed with clock left", ev_last, ending=ending)
    else:
        ending = None
        crit["ending"] = _c(UNKNOWN, "clock not at 0 and no completion record: truncated sample, not a finish", ev_last)

    # --- score / rank ---------------------------------------------------------------------------------------
    target = rules["target_rank"]
    need = dict(rules["rank_scores"]).get(target)
    rank = rank_of(score, rules)
    if score is None:
        crit["score_rank"] = _c(UNKNOWN, "no valid score")
    elif ending is None:
        crit["score_rank"] = _c(UNKNOWN, "round not finished; score %s is partial" % score, ev_last, score=score, rank_so_far=rank)
    else:
        ok = score >= need
        crit["score_rank"] = _c(PASSED if ok else FAILED, "%s rank, target %s needs %s" % (rank, target, need), ev_last,
                                score=score, rank=rank, target_rank=target, shortfall=max(0, need - score))

    # --- kills / boss kills ---------------------------------------------------------------------------------
    crit["kills"] = _c(UNKNOWN if kills is None else PASSED, "RAM kill counter" if kills is not None else "no valid kills",
                       ev_last, kills=kills)
    boss = num(summary.get("boss_kills"))
    crit["boss_kills"] = _c(UNKNOWN, "no boss-kill evidence" if boss is None else "driver boss counter, unverified", boss_kills=boss)

    # --- time bonuses / extension / melee time -------------------------------------------------------------
    rises = _clock(samples, rules)
    for r in rises:
        r["cause"] = _attribute(r, rules)
    gained = round(sum(r["gain_s"] for r in rises), 2)
    timer_ok = sum(1 for s in samples if num(s.get("timer")) is not None) >= 2
    pressed = num(summary.get("prompt_presses"))
    taken = num(summary.get("bonuses_taken"))
    bonus_rises = [r for r in rises if r["cause"] != "melee_kill" and r["cause"] != "kill_counter"]
    if not timer_ok:
        crit["time_bonus"] = _c(UNKNOWN, "timer not observable")
    elif bonus_rises:
        crit["time_bonus"] = _c(PASSED, "clock rose %.1f s without a kill to explain it (RAM, authoritative)" % sum(r["gain_s"] for r in bonus_rises),
                                [r["to"] for r in bonus_rises], rises=bonus_rises)
    elif taken is not None and taken > 0:
        crit["time_bonus"] = _c(UNKNOWN, "driver claims %d pickups but no clock rise observed (claim unverified)" % taken)
    elif pressed:
        crit["time_bonus"] = _c(FAILED, "inputs issued (%d) but no clock rise observed: failed pickup" % pressed)
    else:
        crit["time_bonus"] = _c(UNKNOWN, "no clock rise; bonus availability/attempts not recorded")
    melee_rises = [r for r in rises if r["cause"] == "melee_kill"]
    crit["melee_qte_time"] = (_c(PASSED, "clock rise matches melee kill time", [r["to"] for r in melee_rises], rises=melee_rises)
                              if melee_rises else _c(UNKNOWN, "no verified melee/QTE clock rise (QTE presses are issued inputs, not effect)",
                                                     qte_presses=num(summary.get("qte_presses"))))
    crit["time_extension"] = (_c(UNKNOWN, "timer not observable") if not timer_ok else
                              _c(PASSED if gained > 0 else FAILED, "observed clock gain %.1f s" % gained, gained_s=gained, rises=rises))

    # --- combos / group kills / items / headshots -----------------------------------------------------------
    combo = num(summary.get("max_combo"))
    crit["combos"] = _c(UNKNOWN, "driver max_combo=%s (no combo threshold in rules)" % combo if combo is not None else "no combo evidence", max_combo=combo)
    crit["group_kills"] = _c(UNKNOWN, "no group-kill evidence")
    crit["items"] = _c(UNKNOWN, "item acquisition/use events not recorded (inventory strings are snapshots)")
    crit["headshots"] = _c(UNKNOWN, "no verified headshot identity (a driver counter of 0 is not evidence of none)")

    # --- nearby-threat clearance ----------------------------------------------------------------------------
    near = rules["near_threat_cm"]
    with_vis = [s for s in samples if s.get("nearest_enemy_visible") is not None]
    dists = [num(s.get("nearest_enemy_distance_cm")) for s in samples if num(s.get("nearest_enemy_distance_cm")) is not None]
    if not with_vis:
        crit["threat_clearance"] = _c(UNKNOWN, "visibility not recorded: cannot tell exposed from blocked-by-geometry",
                                      samples_with_distance=len(dists), min_distance_cm=min(dists) if dists else None)
    else:
        exposed = [s for s in with_vis if s["nearest_enemy_visible"] is True and (num(s.get("nearest_enemy_distance_cm")) or 1e9) <= near]
        crit["threat_clearance"] = _c(FAILED if exposed else PASSED, "%d samples with an exposed threat within %.0f cm" % (len(exposed), near),
                                      [_ref(s) for s in exposed[:5]], exposed_samples=len(exposed))

    # --- navigation progress --------------------------------------------------------------------------------
    arrivals, tris, gave_up = (num(summary.get(k)) for k in ("nav_route_arrivals", "nav_visited_triangles", "routes_given_up"))
    if arrivals is None and tris is None:
        crit["navigation"] = _c(UNKNOWN, "no navigation counters")
    elif arrivals is not None and arrivals == 0 and (gave_up or 0) > 0:
        crit["navigation"] = _c(FAILED, "0 route arrivals, %d routes given up (visited triangles: %s)" % (gave_up, tris), nav_visited_triangles=tris)
    else:
        crit["navigation"] = _c(PASSED if arrivals else UNKNOWN, "route arrivals %s, visited triangles %s" % (arrivals, tris), nav_visited_triangles=tris)

    # --- combat counters (associated, not exact) --------------------------------------------------------------
    shots, hits = num(summary.get("round_shots")), num(summary.get("round_hits"))
    counters = {"observed_shot_events": shots, "associated_hits": hits, "issued_prompt_presses": pressed}
    return {"round": round_no, "modified": bool(modified), "ending": ending, "final": {"score": score, "kills": kills, "timer": timer},
            "samples": len(samples), "excluded_post_reset_samples": len(list(excluded)), "criteria": crit, "counters": counters,
            "counter_anomalies": anomalies,
            "counter_note": "shot events/associated hits are driver counters, not exact projectiles or confirmed hit identity"}


def evaluate_run(samples, summaries=None, rules=None, modified=None):
    """Grade every round independently.  ``summaries`` maps round number -> driver stats."""
    rules = rules or RE5_RULES
    groups = split_rounds(samples)
    rounds = [evaluate_round(g["samples"], rules, (summaries or {}).get(r), r, modified, g["excluded"])
              for r, g in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0]))]
    return {"title": rules["title"], "rounds": rounds,
            "tally": {st: sum(1 for r in rounds for c in r["criteria"].values() if c["status"] == st) for st in (PASSED, FAILED, UNKNOWN)}}


def recommend(state, rules=None):
    """One pure priority decision.  Mandatory QTE escape / healing preempt; an immediate *exposed* nearby threat
    outranks optional travel, bonus, melee and weapon change.  Unknown visibility is not blocked geometry."""
    rules = rules or RE5_RULES
    if state.get("qte_escape"):
        return {"action": "qte_escape", "why": "mandatory escape prompt"}
    if state.get("healing_needed"):
        return {"action": "heal", "why": "healing preempts optional work"}
    d, vis = num(state.get("nearest_enemy_distance_cm")), state.get("nearest_enemy_visible")
    if d is not None and d <= rules["near_threat_cm"]:
        if vis is True:
            return {"action": "clear_threat", "why": "exposed threat within %.0f cm" % rules["near_threat_cm"]}
        if vis is None:
            return {"action": "clear_threat", "why": "threat near, visibility unknown: not assumed blocked", "visibility": "unknown"}
        # visibility False: geometry blocks the line; fall through to progress
    for want, name in (("time_bonus_near", "collect_time_bonus"), ("melee_ready", "melee"), ("weapon_change", "change_weapon"),
                       ("travel", "travel")):
        if state.get(want):
            return {"action": name, "why": "no exposed immediate threat"}
    return {"action": "hold", "why": "nothing to do"}
