"""Autoplay that learns from the operator's own play (gameplay memory).

While the operator plays, padstate.watch_xinput reports their controller at 30 Hz and gameplay memory keeps each report
as a 'pad' event (buttons pressed/released plus both sticks, server-time stamped). Two autoplay modes are built from it:

  replay   one recorded run played back on the operator's timing from the moment its session started: title screen,
           menus, loading and the run itself. Idle gaps longer than IDLE_CAP (the operator away) are shortened.
           Open-loop and approximate (server receipt times, not core frames): not a TAS.
  learned  a style model for any game with enough recorded play: the operator's input bursts (a combo, a dash, a guard,
           a jump) with their own hold times, and which burst tends to follow which. Played as a loop; it never presses
           Start/Select. Fighting games (SoulCalibur survival) play best with it.

The operator touching their pad hands control back (tools._takeover). Nothing here reads or writes game memory.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict

IDLE_CAP = 20.0          # s: a longer gap in a recording plays as this long
BURST_GAP = 0.25         # s: idle this long ends an input burst
MAX_BURST = 2.0          # s: a longer burst (holding a direction while attacking) is cut into moves this long
NO_LEARN = frozenset({"start", "select", "l3", "r3"})   # pause / menus / camera clicks: the learned loop never presses them
MIN_REPLAY_PADS = 200    # a run with fewer pad reports is a test poke, not a run worth replaying
MIN_LEARN_BURSTS = 20
STICK_ON = 0.3           # stick deflection that counts as a direction (same threshold as gameplay_demo)

# Dolphin on Windows (SendInput keyboard binding) wants GameCube names; physical XInput reports are positional RetroPad
# labels (Xbox A = 'b'). gameplay_demo.pad_events learned this mapping on the observed PSO demos.
DOLPHIN_GC = {"a": "b", "b": "a", "x": "y", "y": "x", "r": "z", "l2": "l", "r2": "r",
              "up": "t", "down": "g", "left": "f", "right": "h"}


def _stick_keys(stick, names) -> set[str]:
    if not isinstance(stick, dict):
        return set()
    neg_x, pos_x, neg_y, pos_y = names
    out = set()
    x, y = stick.get("x", 0), stick.get("y", 0)
    if type(x) in (int, float):
        out |= {neg_x} if x < -STICK_ON else {pos_x} if x > STICK_ON else set()
    if type(y) in (int, float):
        out |= {neg_y} if y < -STICK_ON else {pos_y} if y > STICK_ON else set()
    return out


def held_timeline(events: list[dict], adapter: str = "retroarch", platform: str | None = None) -> list[tuple[float, frozenset]]:
    """[(at, held)] after every pad report: the buttons and stick directions the operator held, named for `adapter`.

    RetroArch takes the physical labels as they are (network RetroPad) and the left stick as lleft/lright/lup/ldown.
    Dolphin on Windows takes the GameCube keyboard names (main stick = arrows, D-pad = t/g/f/h, C-stick = c*)."""
    gc = adapter == "dolphin" and platform == "gamecube"
    stick_names = ("left", "right", "up", "down") if gc else ("lleft", "lright", "lup", "ldown")
    buttons: set[str] = set()
    out = []
    for e in events:
        if e.get("kind") != "pad":
            continue
        p = e.get("payload") or {}
        for row in p.get("events") or []:
            if not isinstance(row, dict) or not isinstance(row.get("key"), str):
                continue
            k = row["key"].lower()
            buttons.add(k) if row.get("down", True) else buttons.discard(k)
        keys = set(buttons)
        if gc:
            keys = {DOLPHIN_GC.get(k, k) for k in keys if k != "l"}
        keys |= _stick_keys(p.get("stick"), stick_names)
        if gc:
            keys |= _stick_keys(p.get("rstick"), ("cleft", "cright", "cup", "cdown"))
        out.append((float(e["at"]), frozenset(keys)))
    return out


def diff(before: frozenset, after: frozenset) -> list[dict]:
    """Input rows from one held set to the next: releases first (a stick axis shares one RetroPad value)."""
    return [{"key": k, "down": False} for k in sorted(before - after)] + [{"key": k, "down": True} for k in sorted(after - before)]


def replay_plan(timeline: list[tuple[float, frozenset]], started: float, idle_cap: float = IDLE_CAP) -> list[tuple[float, list[dict]]]:
    """[(t, rows)]: t seconds after the recorded session started, gaps over idle_cap shortened to idle_cap."""
    plan, held, shift, last = [], frozenset(), 0.0, started
    for at, keys in timeline:
        if at < started:
            continue
        gap = at - last
        if gap > idle_cap:
            shift += gap - idle_cap
        last = at
        rows = diff(held, keys)
        if rows:
            plan.append((round(at - started - shift, 3), rows))
            held = keys
    if held:
        plan.append((plan[-1][0] + 0.1, diff(held, frozenset())))
    return plan


def pick_run(runs: list[dict], adapter: str = "", run_id: str = "") -> dict | None:
    """The run to replay: the one asked for, else the newest real run (enough pad reports) on the same emulator."""
    if run_id:
        return next((r for r in runs if r.get("id") == run_id), None)
    real = [r for r in runs if (r.get("events") or {}).get("pad", 0) >= MIN_REPLAY_PADS]
    same = [r for r in real if not adapter or r.get("adapter") == adapter]
    pool = same or real
    return max(pool, key=lambda r: r.get("updated") or 0) if pool else None


def bursts(timeline: list[tuple[float, frozenset]], gap: float = BURST_GAP) -> list[tuple[float, list[tuple[float, frozenset]]]]:
    """Split the held timeline into bursts: (start time, [(offset, held)]) from the first press until everything was let
    go for `gap`. Each burst ends with its release step (offset, empty)."""
    out, cur, t0, idle_since = [], [], None, None
    for at, keys in timeline:
        keys = keys - NO_LEARN
        if keys:
            if cur and idle_since is not None and at - idle_since >= gap:
                out.append((t0, cur + [(round(idle_since - t0, 3), frozenset())]))
                cur, t0 = [], None
            elif cur and at - t0 > MAX_BURST:                  # still holding: the next move starts here
                out.append((t0, cur + [(round(at - t0, 3), frozenset())]))
                cur, t0 = [], None
            elif cur and idle_since is not None:                # let go briefly (a double tap): keep the release
                cur.append((round(idle_since - t0, 3), frozenset()))
            if t0 is None:
                t0 = at
            idle_since = None
            if not cur or cur[-1][1] != keys:
                cur.append((round(at - t0, 3), keys))
        elif cur and idle_since is None:
            idle_since = at
    if cur:
        end = idle_since if idle_since is not None else t0 + cur[-1][0] + 0.1
        out.append((t0, cur + [(round(end - t0, 3), frozenset())]))
    return out


def _sig(burst) -> tuple:
    return tuple(tuple(sorted(k)) for _, k in burst)


def learn(timeline: list[tuple[float, frozenset]]) -> dict:
    """The operator's style: distinct bursts (with one recorded timing each), how often, what follows what, idle gaps."""
    index, model, follows, gaps = {}, [], defaultdict(Counter), []
    prev_end, prev = None, None
    seq = bursts(timeline)
    for start, b in seq:
        s = _sig(b)
        if s not in index:
            index[s] = len(model)
            model.append({"steps": [[dt, sorted(k)] for dt, k in b], "n": 0})
        i = index[s]
        model[i]["n"] += 1
        if prev is not None:
            follows[prev][i] += 1
        if prev_end is not None and 0 <= start - prev_end < 2.0:
            gaps.append(round(start - prev_end, 3))
        prev, prev_end = i, start + b[-1][0]
    return {"bursts": model, "follows": {str(k): dict(v) for k, v in follows.items()}, "gaps": gaps[-500:],
            "total": len(seq)}


class Style:
    """Plays a learned model: the next burst follows the last one the way the operator's did (70%), else by frequency."""

    def __init__(self, model: dict, rng: random.Random | None = None):
        self.m, self.rng, self.prev = model, rng or random.Random(), None
        self.weights = [b["n"] for b in model["bursts"]]

    def next(self) -> list[tuple[float, frozenset]]:
        follow = self.m["follows"].get(str(self.prev)) if self.prev is not None else None
        if follow and self.rng.random() < 0.7:
            ids, w = zip(*((int(k), v) for k, v in follow.items()))
            i = self.rng.choices(ids, w)[0]
        else:
            i = self.rng.choices(range(len(self.weights)), self.weights)[0]
        self.prev = i
        return [(dt, frozenset(k)) for dt, k in self.m["bursts"][i]["steps"]]

    def gap(self) -> float:
        g = self.m.get("gaps") or [0.15]
        return max(0.03, min(0.8, self.rng.choice(g)))


def play_plan(plan, *, send, stopped, clock, sleep, offset: float = 0.0) -> dict:
    """Send each [(t, rows)] at its time (t >= offset; rows before offset are skipped). Stops when stopped() is true."""
    began, sent = clock() - offset, 0
    for t, rows in plan:
        if t < offset:
            continue
        while clock() - began < t:
            if stopped():
                return {"completed": False, "sent": sent, "at": round(clock() - began, 2)}
            sleep(min(0.05, max(0.0, t - (clock() - began))))
        if stopped():
            return {"completed": False, "sent": sent, "at": round(clock() - began, 2)}
        send(rows)
        sent += 1
    return {"completed": True, "sent": sent, "at": round(clock() - began, 2)}


def play_style(style: Style, *, send, stopped, sleep, limit: int | None = None) -> int:
    """Loop the learned bursts until stopped (or `limit` bursts). Releases everything it holds between bursts."""
    n = 0
    while not stopped() and (limit is None or n < limit):
        held, t = frozenset(), 0.0
        for dt, keys in style.next():
            if dt > t:
                sleep(dt - t)
                t = dt
            if stopped():
                break
            rows = diff(held, keys)
            if rows:
                send(rows)
            held = keys
        if held:
            send(diff(held, frozenset()))
        n += 1
        sleep(style.gap())
    return n
