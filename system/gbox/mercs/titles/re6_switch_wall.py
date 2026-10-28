"""Bound forward wall pressure using the final pad output and observed displacement."""
from __future__ import annotations

import math

WINDOW, PROGRESS, GAP = .4, 15., .5
PROBE_S, RECOVERY_S, SKIP_S = .25, 1.2, 12.
MOVEMENT = frozenset(("lup", "ldown", "lleft", "lright", "b", "rleft", "rright"))


def _count(bot, name):
    bot.stats[name] = bot.stats.get(name, 0) + 1


def _state(bot):
    state = getattr(bot, "_movement_guard", None)
    if state is None:
        state = bot._movement_guard = {"previous": None, "anchor": None, "effort": 0., "recovery": None,
                                       "walls": [], "actor": None}
    return state


def _flat(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


def _eligible(bot, snap, action):
    from . import re6_switch as R
    p, hold = snap.get("player") or {}, action.get("hold")
    navigating = bot.doing in ("walk", "bonus") or (bot.doing == "no_foes"
                 and (getattr(bot, "_movement_guard", None) or {}).get("recovery") is not None)
    return (snap.get("mercenaries_phase") == R.PHASE_PLAYING and navigating
            and hold is not None and not {"zl", "zr"} & set(hold)
            and not bot.in_hold and not bot.down and (p.get("hp") or 0) > 0
            and p.get("action") not in R.BOOSTED_ACTIONS
            and not (p.get("action") == "cPlAction_pl_act_weapon_fire" and p.get("weapon_id") in R.MAGNUM_IDS))


def apply(bot, snap, action, now):
    from . import re6_switch as R
    state, p = _state(bot), snap.get("player") or {}
    if snap.get("mercenaries_phase") != R.PHASE_PLAYING:
        state["walls"], state["actor"], bot._walk_skip = [], None, {}
    if not _eligible(bot, snap, action) or not p.get("pos"):
        state["previous"], state["anchor"], state["effort"], state["recovery"] = None, None, 0., None
        return action
    pos, yaw = tuple(p["pos"]), (snap.get("camera") or {}).get("yaw", p["rot"])
    previous, state["previous"] = state["previous"], None
    actor = (p.get("ptr"), getattr(bot, "_round_started", None), getattr(snap.get("navmesh"), "name", None))
    if state["actor"] != actor:
        if state["actor"] is not None:
            bot._walk_skip = {}
        state["walls"], state["recovery"], previous = [], None, None
        state["actor"] = actor
    if previous is None or not 0 < now - previous[0] <= GAP or _flat(pos, previous[1]) > 100. \
            or abs(pos[1] - previous[1][1]) > 40.:
        state["anchor"], state["effort"] = pos, 0.
    elif previous[2]:
        if state["anchor"] is None or _flat(pos, state["anchor"]) >= PROGRESS:
            state["anchor"], state["effort"] = pos, 0.
        else:
            state["effort"] += now - previous[0]
    else:
        state["anchor"], state["effort"] = pos, 0.
    state["walls"] = [w for w in state["walls"] if w[3] > now]
    rec, hold = state["recovery"], action["hold"]
    remembered = next((w for w in state["walls"] if _flat(pos, w[0]) < 80. and abs(pos[1] - w[0][1]) < 40.
                       and abs(R.wrap(yaw - w[1])) < math.radians(40.)), None)
    if rec is None and "lup" in hold and (state["effort"] >= WINDOW or remembered is not None):
        if remembered is not None:
            return {**action, "hold": tuple(k for k in hold if k not in MOVEMENT)
                    + tuple(bot._turn(R.wrap(remembered[2] - yaw), R.TURN_TOL))}
        _count(bot, "movement_blocks")
        rec = state["recovery"] = {"at": now, "pos": pos, "head": R.wrap(yaw + math.pi)}
        state["walls"] = (state["walls"] + [(pos, yaw, rec["head"], now + SKIP_S)])[-32:]
        state["effort"] = 0.
        bot.nav_path = None
        if bot.doing == "bonus" and bot.run_target is not None:
            bot.bonus_skip[bot.run_target] = now + SKIP_S
            bot.run_target, bot.run_hit_since = None, None
            _count(bot, "bonus_skips")
        target = getattr(bot, "_walk_target", None)
        if target is not None:
            skip = getattr(bot, "_walk_skip", {})
            bot._walk_skip = {**skip, target: now + SKIP_S}
    if rec is None:
        return action
    keys = tuple(k for k in hold if k not in MOVEMENT)
    if _flat(pos, rec["pos"]) >= PROGRESS:
        _count(bot, "movement_recoveries")
        state["recovery"] = None
        return {**action, "hold": keys}
    elapsed = now - rec["at"]
    if elapsed >= RECOVERY_S:
        _count(bot, "movement_recovery_failures")
        state["recovery"] = None
    movement = ("ldown",) if elapsed < PROBE_S else ("lleft",) if elapsed < 2 * PROBE_S else \
        tuple(bot._turn(R.wrap(rec["head"] - yaw), R.TURN_TOL))
    bot.why = "blocked movement: bounded back/side probe, waiting for observed displacement"
    return {**action, "hold": keys + movement}


def feedback(bot, snap, action, now):
    state, p = _state(bot), snap.get("player") or {}
    hold = action.get("hold") or ()
    forward = _eligible(bot, snap, action) and "lup" in hold and state["recovery"] is None
    state["previous"] = (now, tuple(p["pos"]), forward) if p.get("pos") else None
