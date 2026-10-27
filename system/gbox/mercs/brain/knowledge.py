"""The brain's hook to the enemy knowledge database: how to dispatch an enemy, and what each shot and hit taught.

The database (another agent's work, operator 2026-10-27: "the aimbot learns enemy activity and builds a database of
how to dispatch them") learns from the RAM bytes and the outcomes, per title, enemy class and state: the best aim point
(an offset from the enemy's position to where hits land), the weapon, the range, the timing and the danger. The brain
asks it through two calls and never depends on its internals:

    dispatch_plan(title, enemy_class, state, distance, weapon) -> DispatchPlan
    record(outcome)                                            # one per resolved shot and per damage event

Until the database registers a provider (set_provider), DefaultKnowledge answers with the constants the RE5 PS3 combat
layer uses today (the chest, the hold-fire rapid fire, danger by distance), and record() drops the outcome. A provider
that raises never stops a tick: the default answers that call instead, and the error is kept in last_error.

An outcome is a dict; the keys the brain sends (the database may ignore any and the brain may add more):
    kind        "shot" | "damage"
    title       the adapter's title id ("BLUS30491", "010018100CD46000" ...)
    t           the brain's clock at the event
    enemy_id, enemy_class, state       the enemy the shot was for / the one that hurt the player (None when unknown)
    distance    cm on the ground; weapon: the weapon id; aim_offset: the plan's offset the aim used
    hit         True / False (a shot); hp_delta: the enemy's health change (a shot) or the player's (damage)
    where       what the laser dot was on ("head" / "body" / "leg" / "wall" / "floor" / "none" / None)
    plan_source the DispatchPlan.source the aim followed
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .body import CHEST_H

RANGE_BANDS = (("point_blank", 150.0), ("close", 300.0), ("mid", 800.0), ("far", 2200.0))   # cm: up to this
RELOAD_KEEP = ("_PROVIDER",)           # gbox.hot_reload: a registered database survives a bot reload


@dataclass(frozen=True)
class DispatchPlan:
    """How to dispatch one enemy now. aim_offset: cm from his position (his feet) to the point to aim at;
    range_band: RANGE_BANDS' name; fire_mode: "hold" (the trigger down: rapid fire, automatics) or "tap";
    danger: 0 (harmless) .. 1 (about to kill the player); source: who answered ("default" or the database's id)."""
    aim_offset: tuple = (0.0, CHEST_H, 0.0)
    range_band: str = "mid"
    fire_mode: str = "hold"
    danger: float = 0.0
    source: str = "default"


class Knowledge(Protocol):
    def dispatch_plan(self, title: str, enemy_class, state, distance: float, weapon) -> DispatchPlan: ...

    def record(self, outcome: dict) -> None: ...


def range_band(distance) -> str:
    try:
        d = float(distance)
    except (TypeError, ValueError):
        return "mid"
    return next((name for name, r in RANGE_BANDS if d <= r), "beyond")


class DefaultKnowledge:
    """Today's constants: the chest, the trigger held (x80 rapid fire and automatics), danger rising as he closes in."""

    source = "default"

    def dispatch_plan(self, title, enemy_class, state, distance, weapon) -> DispatchPlan:
        band = range_band(distance)
        try:
            d = max(0.0, float(distance))
        except (TypeError, ValueError):
            d = RANGE_BANDS[2][1]
        danger = round(max(0.0, min(1.0, 1.0 - d / RANGE_BANDS[2][1])), 3)
        return DispatchPlan(aim_offset=(0.0, CHEST_H, 0.0), range_band=band, fire_mode="hold", danger=danger,
                            source=self.source)

    def record(self, outcome: dict) -> None:
        return None


_DEFAULT = DefaultKnowledge()
_PROVIDER: list = [None]               # the registered database (a list: the same object survives a reload)
last_error: list = [None]              # the last provider error ("Type: message"), for the look and the reports


def set_provider(provider) -> None:
    """Register the knowledge database (None: back to the defaults). It needs dispatch_plan() and record()."""
    _PROVIDER[0] = provider


def provider():
    return _PROVIDER[0] or _DEFAULT


def dispatch_plan(title, enemy_class=None, state=None, distance=None, weapon=None) -> DispatchPlan:
    p = _PROVIDER[0]
    if p is not None:
        try:
            plan = p.dispatch_plan(title, enemy_class, state, distance, weapon)
            if isinstance(plan, DispatchPlan):
                return plan
            last_error[0] = f"TypeError: dispatch_plan returned {type(plan).__name__}"
        except Exception as exc:                          # noqa: BLE001 - a database error never stops a tick
            last_error[0] = f"{type(exc).__name__}: {exc}"[:200]
    return _DEFAULT.dispatch_plan(title, enemy_class, state, distance, weapon)


def record(outcome: dict) -> None:
    p = _PROVIDER[0]
    if p is None:
        return
    try:
        p.record(dict(outcome))
    except Exception as exc:                              # noqa: BLE001 - a database error never stops a tick
        last_error[0] = f"{type(exc).__name__}: {exc}"[:200]
