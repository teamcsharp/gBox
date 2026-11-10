"""Operator-directed bot control: the wire model for guiding an autonomous bot and
adjusting its logic from the outside (request #5326).

Goal (operator): "the bot is autonomous and plays the game, but I am able to guide and
dictate them and adjust their logic on the outside, which creates an entirely different
game out of this game."

This module is the game-agnostic data layer that sits between the operator's control
surface (gbox/bot_control.py's HTTP endpoints) and the brain (gbox/bot_brain.py, which
already turns a perception into one Intent per tick and reads a difficulty preset).
It is pure Python and carries no game-specific imports, so it is unit-testable on its
own. Three capabilities, matching the goal:

  * guide and dictate  ->  ``Directive``: a single operator instruction issued at runtime
    (move, fight, flee, follow, hold, wait, set-objective, stop). The brain consumes a
    per-tick ``DirectiveQueue`` instead of a hard-coded script, so the operator can
    steer a running bot without relaunching it.
  * adjust the logic on the outside ->  ``ParamSet``: the brain's logic knobs
    (difficulty, reaction, aim error, turn rate, burst, ...) that can be changed live;
    ``merged()`` applies only the fields the operator set, leaving the rest of the
    brain's configuration untouched.
  * an entirely different game ->  ``LogicPreset``: a named, swappable bundle of params
    + objective. Swapping presets mid-run is how the same game becomes a different one.

Everything round-trips through ``to_dict`` / ``from_dict`` (JSON) so it can travel over
the existing gBox HTTP surface. The queue is thread-safe (a control thread enqueues
while the brain's tick thread dequeues).
"""
from __future__ import annotations

import heapq
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# Directive kinds the operator may issue to an autonomous bot at runtime.
MOVE_TO = "move_to"        # go to a world position (target=(x, y, z))
FIGHT = "fight"            # engage a target
FLEE = "flee"              # disengage and retreat
FOLLOW = "follow"          # keep up with a target
HOLD = "hold"              # hold current position
WAIT = "wait"              # pause for `seconds`
OBJECTIVE = "objective"    # set/replace the active objective (target=objective id)
PARAM_SET = "param_set"    # adjust the brain's logic params live (params=ParamSet)
STOP = "stop"              # stop taking over; return control to the operator
RESUME = "resume"          # resume after a STOP

DIRECTIVE_KINDS = frozenset({
    MOVE_TO, FIGHT, FLEE, FOLLOW, HOLD, WAIT, OBJECTIVE, PARAM_SET, STOP, RESUME,
})

# Kinds that need a world-space target tuple.
_NEEDS_TARGET = frozenset({MOVE_TO, FIGHT, FLEE, FOLLOW})
_DEFAULT_TTL_S = 30.0      # an un-acknowledged directive expires this long


class DirectiveError(ValueError):
    """Raised when a directive is malformed or unknown."""


@dataclass(frozen=True)
class Directive:
    """One operator instruction. Immutable: the queue hands out the exact object."""
    kind: str
    target: tuple[float, float, float] | None = None
    seconds: float = 0.0
    params: dict[str, Any] | None = None
    note: str = ""
    priority: int = 100             # lower value runs first
    expires_in_s: float | None = None   # TTL from issue time; None = default

    def __post_init__(self) -> None:
        if self.kind not in DIRECTIVE_KINDS:
            raise DirectiveError(f"unknown directive kind: {self.kind!r}")
        if self.kind in _NEEDS_TARGET:
            if not (isinstance(self.target, (list, tuple)) and len(self.target) == 3):
                raise DirectiveError(f"{self.kind} needs a 3-tuple target, got {self.target!r}")
            object.__setattr__(self, "target", (float(self.target[0]),
                                                float(self.target[1]), float(self.target[2])))
        if self.kind == WAIT and self.seconds <= 0:
            raise DirectiveError("wait needs seconds > 0")
        if self.kind == PARAM_SET and not isinstance(self.params, dict):
            raise DirectiveError("param_set needs a params dict (ParamSet.to_dict())")
        if self.priority < 0:
            raise DirectiveError("priority must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        if self.target is not None:
            d["target"] = list(self.target)
        if self.seconds:
            d["seconds"] = self.seconds
        if self.params is not None:
            d["params"] = self.params
        if self.note:
            d["note"] = self.note
        if self.priority != 100:
            d["priority"] = self.priority
        if self.expires_in_s is not None:
            d["expires_in_s"] = self.expires_in_s
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Directive":
        return cls(
            kind=d["kind"],
            target=d.get("target"),
            seconds=float(d.get("seconds", 0.0)),
            params=d.get("params"),
            note=d.get("note", ""),
            priority=int(d.get("priority", 100)),
            expires_in_s=d.get("expires_in_s"),
        )


@dataclass
class ParamSet:
    """The brain's adjustable logic knobs. ``None`` = "leave as-is"; only set fields
    are applied, so an operator can nudge one knob without clobbering the rest."""
    difficulty: str | None = None       # name of a brain PRESET (see bot_brain.PRESETS)
    reaction_s: float | None = None
    aim_jitter_deg: float | None = None
    turn_rate: float | None = None
    cone_scale: float | None = None
    burst_s: float | None = None
    rest_s: float | None = None
    strafe: bool | None = None
    memory_s: float | None = None

    KNOBS = ("difficulty", "reaction_s", "aim_jitter_deg", "turn_rate", "cone_scale",
             "burst_s", "rest_s", "strafe", "memory_s")

    def set_fields(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.KNOBS if getattr(self, k) is not None}

    def merged(self, base: dict[str, Any]) -> dict[str, Any]:
        """Apply this set over ``base`` (the brain's current config); only set fields
        change. Returns a new dict, never mutates ``base``."""
        out = dict(base)
        out.update(self.set_fields())
        return out

    def to_dict(self) -> dict[str, Any]:
        return self.set_fields()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ParamSet":
        known = {k: d[k] for k in cls.KNOBS if k in d and d[k] is not None}
        for k in ("reaction_s", "aim_jitter_deg", "turn_rate", "cone_scale",
                  "burst_s", "rest_s", "memory_s"):
            if k in known:
                known[k] = float(known[k])
        if "strafe" in known:
            known["strafe"] = bool(known["strafe"])
        return cls(**known)


@dataclass
class LogicPreset:
    """A named, swappable 'different game': a bundle of logic params + an objective.
    Swapping presets mid-run is the operator's lever for 'an entirely different game'."""
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    objective: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "params": self.params, "objective": self.objective}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LogicPreset":
        return cls(name=d["name"], params=dict(d.get("params", {})),
                   objective=d.get("objective"))

    def apply(self, current: dict[str, Any]) -> dict[str, Any]:
        """Replace the brain's config with this preset's params (a full swap, unlike
        ``ParamSet.merged`` which only nuds)."""
        return dict(self.params)


@dataclass
class _Queued:
    seq: int
    priority: int
    issued_at: float
    expires_at: float | None
    directive: Directive

    def __lt__(self, other: "_Queued") -> bool:
        return (self.priority, self.seq) < (other.priority, other.seq)


class DirectiveQueue:
    """Thread-safe, priority-ordered, TTL-bound queue the brain drains each tick.
    The control thread enqueues (from the operator's HTTP surface); the brain's tick
    thread dequeues. Higher urgency = lower ``priority`` value; expired directives are
    dropped and reported, never silently lost."""
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._heap: list[_Queued] = []
        self._seq = 0

    def add(self, directive: Directive, now: float | None = None) -> float:
        """Enqueue; returns the absolute expiry time (for the caller's bookkeeping)."""
        issued = now if now is not None else time.time()
        ttl = directive.expires_in_s if directive.expires_in_s is not None else _DEFAULT_TTL_S
        expires = issued + ttl
        with self._lock:
            self._seq += 1
            self._heap.append(_Queued(self._seq, directive.priority, issued, expires, directive))
            heapq.heapify(self._heap)
        return expires

    def pop_due(self, now: float | None = None) -> list[Directive]:
        """Return every non-expired directive, best priority first, in FIFO order
        within the same priority. Expired ones are dropped and returned separately so
        the caller can log them."""
        now = now if now is not None else time.time()
        with self._lock:
            due: list[_Queued] = []
            stale: list[Directive] = []
            for q in self._heap:
                if q.expires_at is not None and q.expires_at <= now:
                    stale.append(q.directive)
                else:
                    due.append(q)
            due.sort(key=lambda q: (q.priority, q.seq))
            self._heap = []          # pop_due drains the queue; keep nothing behind
        return [q.directive for q in due], stale

    def pending(self) -> list[Directive]:
        """Snapshot of what is still queued (for the operator's status view)."""
        now = time.time()
        with self._lock:
            out = [q.directive for q in self._heap
                   if q.expires_at is None or q.expires_at > now]
        out.sort(key=lambda d: (d.priority, d.kind))
        return out

    def size(self) -> int:
        with self._lock:
            return len(self._heap)

    def clear(self) -> int:
        with self._lock:
            n = len(self._heap)
            self._heap = []
            return n
