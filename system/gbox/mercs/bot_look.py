"""The bot's last shots and decisions, for "look at the bot" (operator 2026-10-26: "when i say 'look at the bot' i want
you able to see the last things and results of the last bullets being fired by the bot. They are shooting at walls and
just sitting here amongst foes").

A bounded live view that every Mercenaries bot publishes as stats["look"] (RE4: gbox.re4_merc_bot, RE5: the
gbox.mercs titles), one shape for all of them. BotLook keeps it and snapshot() returns it as JSON:

    {"shots": [...],              # up to MAX_SHOTS, newest last
     "decisions": [...],          # up to MAX_DECISIONS, newest last
     "idle_among_foes_s": float,  # how long the bot has stood without moving or shooting with a foe near (0: busy)
     "walls_shot": int}           # shots this round whose aim line met a wall

A shot: {"t": epoch s, "weapon": str, "gate": str (why the trigger was pulled: the title's fire gate),
         "target": {"id": str | None, "kind": str, "dist_m": float, "bearing_deg": float},
         "aim_err_deg": float | None, "dot_on": "target" | "wall" | "floor" | "none" | "off",
         "outcome": "hit:<kind>" | "miss:<cause>" | "unknown", "hp_delta": int | None}
  * target: the foe the bot aimed at. id is the title's own (a slot, an address); None when the bot fired at no foe.
    kind is "ganado", "majini", "chicken", "boss", "thrown", ..., or "none". dist_m is measured on the ground.
    bearing_deg is measured from the player's facing, positive to the right (clockwise seen from above), -180 .. 180.
    Unknown numbers are 0.0;
  * aim_err_deg: where the gun pointed against the target, in the same sense (positive: the target is to the right of
    the aim); None when unknown;
  * dot_on: what the aim line (the laser dot) met first: a foe ("target"), a wall, the floor, nothing in range ("none"),
    or "off" when the gun was not up or no aim was read;
  * outcome: "unknown" until the title's hit window has passed, then "hit:<kind of the foe hurt>" or "miss:<cause>",
    with the cause taken from MISS_CAUSES; hp_delta: the hurt foe's health change (negative), else None.
A decision: {"t": epoch s, "phase": str, "decision": str, "reason": str}. A new entry is added only when the phase or the
decision changes; the same decision again only updates its reason. So the 30 entries cover the last 30 changes, not
the last 1.5 s of ticks.

BotLook is not thread-safe; the bot's own thread records and publishes. snapshot() returns copies, so the server can
serialise stats["look"] while the bot carries on.
"""
from __future__ import annotations

import math
import time
from collections import deque

MAX_SHOTS = 30
MAX_DECISIONS = 30
DOT_ON = ("target", "wall", "floor", "none", "off")
MISS_CAUSES = ("wall",          # the aim line met a wall before the foe
               "floor",         # ... the floor (aimed too low)
               "off_target",    # the line passed beside the foe
               "no_damage",     # the line was on a foe and no health fell (armour, a shield, out of the gun's reach)
               "gun_down",      # the gun was not up
               "nothing",       # no foe was aimed at and the line met nothing
               "out_of_range")  # further than the gun reaches
REASON_MAX = 160
IDLE_STEP_MAX_S = 1.0           # a stalled caller adds at most this much to the idle streak per call


def _num(v, nd: int = 1) -> float | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _int(v) -> int | None:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def wrap_deg(deg: float) -> float:
    """-180 .. 180."""
    d = (float(deg) + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def make_target(id=None, kind: str | None = None, dist_m=None, bearing_deg=None) -> dict:
    """A shot's target block, in the shared shape (unknown numbers are 0.0)."""
    b = _num(bearing_deg, 6)
    return {"id": None if id is None else str(id), "kind": str(kind or ("none" if id is None else "foe")),
            "dist_m": _num(dist_m) or 0.0, "bearing_deg": round(wrap_deg(b), 1) if b is not None else 0.0}


def outcome_text(o) -> str:
    """'hit:<kind>' / 'miss:<cause>' / 'unknown' (anything else is 'unknown')."""
    o = str(o or "unknown")
    if (o.startswith("hit:") and len(o) > 4) or (o.startswith("miss:") and len(o) > 5):
        return o
    return "unknown"


class BotLook:
    """The ring buffers behind stats["look"]: the last MAX_SHOTS shots and the last MAX_DECISIONS decisions (newest
    last), the idle streak among foes, the walls shot this round. epoch: the clock the entries are stamped with
    (time.time live; a bot passes its own clock, which is time.time live and a fake one in tests)."""

    def __init__(self, epoch=time.time, max_shots: int = MAX_SHOTS, max_decisions: int = MAX_DECISIONS):
        self.epoch = epoch
        self.shots: deque = deque(maxlen=max_shots)
        self.decisions: deque = deque(maxlen=max_decisions)
        self.walls_shot = 0
        self.idle_s = 0.0                 # the current streak (snapshot: idle_among_foes_s)
        self.idle_max_s = 0.0             # the round's longest streak (for the round's audit)
        self._idle_t = None
        self.version = 0                  # moves on every change: publish the snapshot when it moved

    def _t(self, t) -> float:
        return round(float(self.epoch() if t is None else t), 3)

    def new_round(self) -> None:
        """A new round: walls_shot and the idle streaks start over. The last shots and decisions stay in view."""
        self.walls_shot = 0
        self.idle_s = self.idle_max_s = 0.0
        self._idle_t = None
        self.version += 1

    def record_shot(self, weapon, gate, target: dict | None = None, aim_err_deg=None, dot_on: str = "none",
                    outcome: str = "unknown", hp_delta=None, t=None) -> dict:
        """One shot as it left the gun; returns its entry for resolve() once the hit window has passed."""
        dot = dot_on if dot_on in DOT_ON else "none"
        tg = make_target(**{k: target.get(k) for k in ("id", "kind", "dist_m", "bearing_deg")}) \
            if isinstance(target, dict) else make_target()
        shot = {"t": self._t(t), "weapon": str(weapon or "unknown"), "gate": str(gate or "")[:REASON_MAX],
                "target": tg, "aim_err_deg": _num(aim_err_deg), "dot_on": dot, "outcome": outcome_text(outcome),
                "hp_delta": _int(hp_delta)}
        self.shots.append(shot)
        if dot == "wall":
            self.walls_shot += 1
        self.version += 1
        return shot

    def resolve(self, shot: dict | None, outcome: str, hp_delta=None) -> None:
        """A shot's result: 'hit:<kind>' or 'miss:<cause>' (a 'miss:wall' whose line was not read on a wall counts
        among the walls shot too)."""
        if shot is None:
            return
        out = outcome_text(outcome)
        if out == "miss:wall" and shot.get("dot_on") != "wall" and shot.get("outcome") != "miss:wall":
            self.walls_shot += 1
        shot["outcome"], shot["hp_delta"] = out, _int(hp_delta)
        self.version += 1

    def record_decision(self, phase, decision, reason: str = "", t=None) -> bool:
        """What the bot does now and why. True when this is a new entry; a repeat of the last (phase, decision) only
        updates its reason."""
        phase, decision, reason = str(phase or ""), str(decision or ""), str(reason or "")[:REASON_MAX]
        last = self.decisions[-1] if self.decisions else None
        if last is not None and last["phase"] == phase and last["decision"] == decision:
            if last["reason"] != reason:
                last["reason"] = reason
                self.version += 1
            return False
        self.decisions.append({"t": self._t(t), "phase": phase, "decision": decision, "reason": reason})
        self.version += 1
        return True

    def tick_idle(self, foes_near: bool, busy: bool, t=None) -> float:
        """Is the bot sitting among foes? While foes_near (a live foe within the title's reach) and not busy (neither
        moving nor shooting, nor held by the game), the streak grows by the time since the last call (at most
        IDLE_STEP_MAX_S a call); anything else ends it. Returns the streak in seconds."""
        now = float(self.epoch() if t is None else t)
        if foes_near and not busy:
            if self._idle_t is not None:
                self.idle_s += max(0.0, min(now - self._idle_t, IDLE_STEP_MAX_S))
                self.idle_max_s = max(self.idle_max_s, self.idle_s)
            self._idle_t = now
        elif self.idle_s or self._idle_t is not None:
            self.idle_s, self._idle_t = 0.0, None
            self.version += 1
        return self.idle_s

    def snapshot(self) -> dict:
        """stats["look"]: copies, in the shared shape."""
        return {"shots": [dict(s, target=dict(s["target"])) for s in self.shots],
                "decisions": [dict(d) for d in self.decisions],
                "idle_among_foes_s": round(self.idle_s, 1), "walls_shot": int(self.walls_shot)}
