"""Learn from the operator's own play: gameplay-memory pad events -> an imitation playbook the bot can replay.

The plane already has the two halves: `imitate.learn(timeline)` extracts the operator's style (distinct bursts with their timing, what
follows what, the idle gaps, the menu keys), and `autoplay` runs missions step by step (`press {key, n}`, `wait {secs}`, ...). This
module joins them:

* `timeline(events)` - the archive's `pad` events as `[(seconds, frozenset(keys))]`;
* `learn(timeline)` - `imitate.learn`, unchanged;
* `mission(learned, ...)` - a mission JSON whose steps are the learned bursts in their follow order, each press separated by the
  recorded sub-burst delay and each burst separated by the recorded idle gap.

Every step keeps its provenance: the mission records the run id, the number of bursts and the menu keys it was learned from.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from . import imitate

STICK = 0.3            # the same touch threshold padstate uses
MISSION_VERSION = 1


def _directions(payload: dict) -> set[str]:
    """The pad names a `pad` event's sticks and buttons amount to."""
    keys: set[str] = set()
    for row in payload.get("events") or []:
        key = row.get("key")
        if key and row.get("down"):
            keys.add(str(key))
    stick = payload.get("stick") or {}
    if abs(float(stick.get("x") or 0)) >= STICK or abs(float(stick.get("y") or 0)) >= STICK:
        if (stick.get("y") or 0) <= -STICK:
            keys.add("up")
        if (stick.get("y") or 0) >= STICK:
            keys.add("down")
        if (stick.get("x") or 0) <= -STICK:
            keys.add("left")
        if (stick.get("x") or 0) >= STICK:
            keys.add("right")
    rstick = payload.get("rstick") or {}
    if abs(float(rstick.get("x") or 0)) >= STICK or abs(float(rstick.get("y") or 0)) >= STICK:
        if (rstick.get("y") or 0) <= -STICK:
            keys.add("cup")
        if (rstick.get("y") or 0) >= STICK:
            keys.add("cdown")
        if (rstick.get("x") or 0) <= -STICK:
            keys.add("cleft")
        if (rstick.get("x") or 0) >= STICK:
            keys.add("cright")
    return keys


def timeline(events: list[dict]) -> list[tuple[float, frozenset]]:
    """The archive's events as `(seconds since the first pad event, keys held)`; non-pad events are ignored."""
    pads = [e for e in events if e.get("kind") == "pad"]
    if not pads:
        return []
    base = float(pads[0].get("at") or 0.0)
    out = []
    for event in pads:
        keys = _directions(event.get("payload") or {})
        out.append((round(float(event.get("at") or 0.0) - base, 3), frozenset(keys)))
    return out


def learn(timeline_rows: list[tuple[float, frozenset]]) -> dict:
    """The operator's style, via the plane's own learner."""
    return imitate.learn(timeline_rows)


def _burst_steps(burst: dict) -> list[dict]:
    """One learned burst as mission steps: press each key group, wait the recorded sub-delay."""
    steps: list[dict] = []
    last = 0.0
    for dt, keys in burst.get("steps") or []:
        delay = max(0.0, round(float(dt) - last, 3))
        if delay:
            steps.append({"op": "wait", "secs": delay})
            last = float(dt)
        if not keys:
            continue
        steps.append({"op": "press", "key": str(keys[0]), "n": 1})
        for extra in keys[1:]:
            steps.append({"op": "press", "key": str(extra), "n": 1})
    return steps


def follow_order(learned: dict) -> list[int]:
    """A deterministic walk through the learned `follows` graph, most-likely successor first."""
    follows = learned.get("follows") or {}
    if not follows:
        return list(range(len(learned.get("bursts") or [])))
    starts = Counter()
    seen_targets = set()
    for src, row in follows.items():
        for dst, count in (row or {}).items():
            starts[int(src)] += int(count)
            seen_targets.add(int(dst))
    # the first burst is the one that is still a target of nothing (or the most frequent source)
    roots = [i for i in starts if i not in seen_targets] or [starts.most_common(1)[0][0]]
    order, used, current = [], set(), roots[0]
    while current is not None and current not in used:
        used.add(current)
        order.append(current)
        row = (follows.get(str(current)) or {})
        nxt = max(row.items(), key=lambda kv: kv[1])[0] if row else None
        current = int(nxt) if nxt is not None else None
    # anything unreachable goes at the end, in index order
    order += [i for i in range(len(learned.get("bursts") or [])) if i not in used]
    return order


def mission(learned: dict, *, game_id: str, name: str, run: str = "", objective: str = "") -> dict:
    """A mission JSON an `autoplay` run can replay: the learned bursts in follow order with their recorded timing."""
    bursts = learned.get("bursts") or []
    gaps = learned.get("gaps") or []
    gap = sorted(gaps)[len(gaps) // 2] if gaps else 0.4
    steps: list[dict] = []
    for index in follow_order(learned):
        burst = bursts[index]
        for _ in range(max(1, int(burst.get("n") or 1))):
            steps.extend(_burst_steps(burst))
            steps.append({"op": "wait", "secs": round(float(gap), 3)})
    return {
        "name": name,
        "game_id": game_id,
        "objective": objective or "Replay the operator's own learned bursts (imitation of a recorded play session)",
        "policy": "learned-from-operator",
        "provenance": {"source": "gameplay-memory", "run": run, "bursts": len(bursts),
                       "gap_s": round(float(gap), 3), "menu": learned.get("menu") or [],
                       "version": MISSION_VERSION},
        "steps": steps,
    }


def from_events(events: list[dict], *, game_id: str, name: str, run: str = "", objective: str = "") -> tuple[dict, dict]:
    """(mission, the learned style) from an archive run's events."""
    rows = timeline(events)
    if not rows:
        raise ValueError("this run has no pad events to learn from")
    learned = learn(rows)
    return mission(learned, game_id=game_id, name=name, run=run, objective=objective), learned


def save(mission_dict: dict, directory: str | Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{mission_dict['name']}.json"
    path.write_text(json.dumps(mission_dict, indent=1), encoding="utf-8")
    return path
