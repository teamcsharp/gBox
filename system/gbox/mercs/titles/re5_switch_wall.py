"""Stop observed wall pressure; recover in bounded steps without walking while facing the wall."""
from __future__ import annotations

import math

MAX_SAMPLE_GAP, MAX_TRAIL_STEP, MAX_FLOOR_CHANGE = .5, 100., 40.
FACE = math.radians(25.)
RECOVERY_S, RETRY_S = 2., 2.
PASS_CORRIDOR, PASS_OVERSHOOT = 6., 40.   # cm: accept a discrete step past a point, not an arbitrary plane crossing
MOVE_KEYS = frozenset(("lup", "ldown", "lleft", "lright", "b", "rleft", "rright"))
PRIORITY = frozenset(("held", "dead", "quick_turn", "prompt", "heal"))


def _state(bot):
    state = getattr(bot, "_wall_guard", None)
    if state is None:
        state = bot._wall_guard = {"seen": None, "trail": [], "previous": None, "anchor": None,
                                   "effort": 0., "retry_at": -math.inf, "retry_head": None}
    return state


def _flat(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


def _passed(pos, start, target):
    if abs(pos[1] - target[1]) > MAX_FLOOR_CHANGE:
        return False
    if _flat(pos, target) < 1.:
        return True
    dx, dz = target[0] - start[0], target[2] - start[2]
    length = math.hypot(dx, dz)
    if length < 1.:
        return False
    px, pz = pos[0] - start[0], pos[2] - start[2]
    along = (px * dx + pz * dz) / length
    lateral = abs(px * dz - pz * dx) / length
    return length <= along <= length + PASS_OVERSHOOT and lateral <= PASS_CORRIDOR


def _observe(bot, player, now, config):
    state, pos = _state(bot), tuple(player["pos"])
    seen = state["seen"]
    if seen is not None:
        at, before, actor = seen
        if not 0 <= now - at <= MAX_SAMPLE_GAP or player.get("ptr") != actor \
                or _flat(pos, before) > MAX_TRAIL_STEP or abs(pos[1] - before[1]) > MAX_FLOOR_CHANGE:
            state["trail"], state["previous"], state["anchor"], state["effort"] = [], None, None, 0.
            bot._wall_rec = None
    if not state["trail"] or math.dist(pos, state["trail"][-1]) >= 5.:
        state["trail"] = (state["trail"] + [pos])[-64:]
    state["seen"] = now, pos, player.get("ptr")
    previous, state["previous"] = state["previous"], None
    if previous is not None and 0 < now - previous[0] <= MAX_SAMPLE_GAP and previous[2]:
        anchor = state["anchor"]
        if anchor is None or _flat(pos, anchor) >= config.WALL_MIN_CM:
            state["anchor"], state["effort"] = pos, 0.
        else:
            state["effort"] += now - previous[0]
    else:
        state["anchor"], state["effort"] = pos, 0.
    return state


def start(bot, player, now, preempt):
    from . import re5_switch as config
    state, pos = _state(bot), tuple(player["pos"])
    if not preempt:
        bot.wall_memory(pos[0], pos[2], player["rot"])
    # Each adjacent breadcrumb was actually traversed at normal tick cadence.
    # Old sparse trail points can lie across walls or on another floor.
    path, previous, distance = [], pos, 0.
    for point in reversed(state["trail"]):
        step = _flat(point, previous)
        if step < 1.:
            continue
        if step > MAX_TRAIL_STEP or abs(point[1] - previous[1]) > MAX_FLOOR_CHANGE:
            break
        path.append(point)
        distance += step
        previous = point
        if distance >= 20.:
            break
    target = path[0] if path else None
    head = config.heading(target[0] - pos[0], target[2] - pos[2]) if target else config.wrap(player["rot"] + math.pi)
    bot._wall_rec = {"since": now, "until": now + RECOVERY_S, "head": head, "target": target,
                     "path": path if path else None, "origin": pos, "segment_start": pos}
    state["effort"], state["anchor"], state["previous"] = 0., None, None
    bot._wall_push, bot._wall_hist = None, []
    # A failed statue approach must not immediately request the same wall again.
    bonus = getattr(bot, "_bonus", None)
    if bonus is not None:
        bot._bonus_block[bonus["ptr"]] = now + config.BONUS_BLOCK_S
        bot._bonus = None


def _recover(bot, action, player, now, config):
    state, rec, pos = _state(bot), bot._wall_rec, player["pos"]
    keys = tuple(k for k in action.get("hold", ()) if k not in MOVE_KEYS)
    moved = _flat(pos, rec["origin"])
    target = rec["target"]
    if rec["path"] is not None:
        while rec["path"] and _passed(pos, rec["segment_start"], rec["path"][0]):
            rec["segment_start"] = rec["path"].pop(0)
        target = rec["target"] = rec["path"][0] if rec["path"] else None
        if target is not None:
            rec["head"] = config.heading(target[0] - pos[0], target[2] - pos[2])
    complete = moved >= config.WALL_MIN_CM if rec["path"] is None else not rec["path"] and moved >= 5.
    if complete:
        bot.stats["wall_recoveries"] += 1
        bot._wall_rec = None
        state["retry_at"] = now + RETRY_S
        state["retry_head"] = rec["head"]
        return {**action, "hold": keys}
    if now >= rec["until"]:
        bot.stats["wall_recovery_failures"] = bot.stats.get("wall_recovery_failures", 0) + 1
        bot._wall_rec = None
        state["retry_at"] = now + RETRY_S
        state["retry_head"] = rec["head"]
        return {**action, "hold": keys + tuple(bot._turn(config.wrap(rec["head"] - player["rot"]), config.TURN_TOL))}
    err = config.wrap(rec["head"] - player["rot"])
    if target is not None:
        # Turning governors may suppress this turn; only observed facing allows forward.
        movement = tuple(bot._turn(err, config.TURN_TOL))
        if abs(err) <= FACE:
            movement += ("lup",)
        why = "returning along an observed movement segment"
    elif rec["path"] is None:
        # No observed way out: bounded back/side probes, then turn away. Never
        # turn-and-run blindly forward or call an elapsed timer a successful escape.
        elapsed = now - rec["since"]
        movement = ("ldown",) if elapsed < config.WALL_BACK_S else \
            (("lleft",) if bot.stats.get("wall_hits", 0) % 2 else ("lright",)) \
            if elapsed < 2 * config.WALL_BACK_S else tuple(bot._turn(err, config.TURN_TOL))
        why = "bounded back/side probe; waiting for observed movement"
    else:
        movement, why = (), "recorded return path exhausted; waiting for observed movement"
    bot.doing, bot.why = "walk", "wall: " + why
    return {**action, "hold": keys + movement}


def apply(bot, action, snap, now):
    from . import re5_switch as config
    player, hold = snap.get("player"), action.get("hold")
    if not config.WALL_GOV or not player:
        bot._wall_guard, bot._wall_rec = None, None
        return action
    state = _observe(bot, player, now, config)
    if hold is None or bot.doing in PRIORITY or {"zl", "zr"} & set(hold) \
            or player.get("motion") == config.MOTION_SHOT or now < getattr(bot, "_shot_until", -math.inf):
        state["previous"], state["effort"], state["anchor"] = None, 0., None
        bot._wall_rec = None
        return action
    if bot._wall_rec is not None:
        return _recover(bot, action, player, now, config)
    if "lup" not in hold:
        return action
    pos = player["pos"]
    remembered = any(math.hypot(w[0] - pos[0], w[1] - pos[2]) <= config.WALL_MEM_R
                     and abs(config.wrap(player["rot"] - w[2])) <= math.radians(config.WALL_MEM_DEG)
                     for w in bot._walls)
    stalled = state["effort"] >= config.WALL_WINDOW_S
    if not (remembered or stalled):
        return action
    if now < state["retry_at"]:
        head = state["retry_head"]
        turn = tuple(bot._turn(config.wrap(head - player["rot"]), config.TURN_TOL)) if head is not None else ()
        return {**action, "hold": tuple(k for k in hold if k not in MOVE_KEYS)
                + turn}
    counter = "wall_preempts" if remembered else "wall_hits"
    bot.stats[counter] += 1
    if stalled:
        bot.stats["wall_push_s"] = round(bot.stats["wall_push_s"] + state["effort"], 2)
    start(bot, player, now, remembered)
    return _recover(bot, action, player, now, config)


def feedback(bot, action, snap, now):
    """Sample the final pad output after calm/heading/shot-tail governors."""
    state, player = _state(bot), snap.get("player")
    hold = action.get("hold") or ()
    forward = bool(player and "lup" in hold and not {"zl", "zr"} & set(hold)
                   and bot.doing not in PRIORITY and bot._wall_rec is None)
    state["previous"] = (now, tuple(player["pos"]), forward) if player else None
