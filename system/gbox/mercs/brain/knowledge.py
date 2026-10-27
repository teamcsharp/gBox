"""The brain's hook to the enemy knowledge database (gbox.mercs.enemy_db, K): how to dispatch an enemy, and what each
shot and hit taught. A thin adapter: the brain's units are centimetres, K's metres; K answers every plan field as a
Learned(value, confidence, samples, source), and only a learned one (source other than "default") replaces the brain's
own constant - with no data the plan is exactly DefaultKnowledge's, today's behaviour.

    dispatch_plan(title, enemy_class, state, distance_cm, weapon, hp=, hp_max=) -> DispatchPlan
    record(outcome)                    # the brain's outcome dict -> K.record_outcome (one per shot / damage event)
    record_shot(...), record_damage(...), observe(title, enemies, t)    # K's own calls, passed straight through

Precedence: a provider registered with set_provider (tests, an experiment) answers first; then K; then the defaults.
Nothing here raises into a tick: K never raises, and an error of a registered provider falls back to the default (kept
in last_error). K is looked up on each call, so its hot reload or a late deploy is seen.

An outcome is a dict (K.record_outcome reads it):
    kind        "shot" | "damage"
    title       the adapter's title id ("BLUS30491", "010018100CD46000" ...)
    t           the brain's clock at the event
    enemy_id, enemy_class, state       the enemy the shot was for / the one that hurt the player (None when unknown)
    distance    cm on the ground; weapon: the weapon id; aim_offset: cm (x, y up, z) from his feet the aim used
    hit, kill   True / False (a shot); hp_delta: the enemy's health change (a shot) or the player's (damage)
    where       what the laser dot was on ("head" / "body" / "leg" / "wall" / "floor" / "none" / None)
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Protocol

from .body import CHEST_H

RANGE_BANDS = (("point_blank", 150.0), ("close", 300.0), ("mid", 800.0), ("far", 2200.0))   # cm: up to this
RELOAD_KEEP = ("_PROVIDER",)           # gbox.hot_reload: a registered provider survives a bot reload
K_MODULE = "gbox.mercs.enemy_db"


@dataclass(frozen=True)
class DispatchPlan:
    """How to dispatch one enemy now. aim_offset: cm from his position (his feet) to the point to aim at (x, y up, z;
    the lateral part is aim_lateral, across the line of fire, + the shooter's right); range_band: RANGE_BANDS' name;
    fire_mode: "hold" / "tap" / "burst"; danger: 0 (harmless) .. 1 (about to hurt the player within a second);
    source: "default" or "enemy_db: <the learned fields>". The rest are None until K has learned them."""
    aim_offset: tuple = (0.0, CHEST_H, 0.0)
    range_band: str = "mid"
    fire_mode: str = "hold"
    danger: float = 0.0
    source: str = "default"
    aim_lateral: float = 0.0
    zone: str | None = None
    range_cm: tuple | None = None      # (near, far) where his shots do the most
    lead_s: float | None = None        # from his state's onset to his hit
    windup: float | None = None        # the share of this state's onsets followed by damage
    attack: str | None = None          # what he hits with
    shots_to_kill: float | None = None
    hit_rate: float | None = None
    confidence: float = 0.0            # the learned fields' lowest confidence (0: none learned)


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
_PROVIDER: list = [None]               # a registered provider (a list: the same object survives a reload)
last_error: list = [None]              # the last provider / K error ("Type: message")


def set_provider(provider) -> None:
    """Register a provider ahead of K (None: K, then the defaults). It needs dispatch_plan() and record()."""
    _PROVIDER[0] = provider


def provider():
    return _PROVIDER[0] or _DEFAULT


def _k():
    """The enemy knowledge module, or None (not deployed, or it failed to import)."""
    try:
        return importlib.import_module(K_MODULE)
    except Exception as exc:                              # noqa: BLE001 - no database: the defaults
        last_error[0] = f"enemy_db: {type(exc).__name__}: {exc}"[:200]
        return None


def _learned(field) -> bool:
    return field is not None and getattr(field, "source", "default") not in ("default", None, "") \
        and (getattr(field, "samples", 0) or 0) > 0


def from_k(plan, base: DispatchPlan) -> DispatchPlan:
    """K's Plan on the brain's DispatchPlan: each learned field over base's constant, metres -> centimetres."""
    out = dict(base.__dict__)
    used, confidence = [], []

    def take(name, field, value):
        if _learned(field):
            out[name] = value(field.value)
            used.append(name)
            confidence.append(float(getattr(field, "confidence", 0.0) or 0.0))
    take("aim_offset", plan.aim, lambda a: (0.0, float(a.up_m) * 100.0, 0.0))
    if "aim_offset" in used:
        out["aim_lateral"] = float(plan.aim.value.lateral_m or 0.0) * 100.0
        out["zone"] = plan.aim.value.zone
    take("range_cm", plan.range, lambda r: (float(r[0]) * 100.0, float(r[1]) * 100.0))
    take("fire_mode", plan.fire_mode, str)
    take("danger", plan.danger, lambda v: round(max(0.0, min(1.0, float(v))), 3))
    for name in ("lead_s", "windup", "shots_to_kill", "hit_rate"):
        take(name, getattr(plan, name, None), lambda v: None if v is None else float(v))
    take("attack", getattr(plan, "attack", None), lambda v: None if v is None else str(v))
    if used:
        out["source"] = "enemy_db: " + ", ".join(used)
        out["confidence"] = round(min(confidence), 3)
    return DispatchPlan(**out)


def dispatch_plan(title, enemy_class=None, state=None, distance=None, weapon=None, *, hp=None,
                  hp_max=None) -> DispatchPlan:
    """How to dispatch him (distance in cm): a registered provider's plan, else K's learned fields over the defaults."""
    p = _PROVIDER[0]
    if p is not None:
        try:
            plan = p.dispatch_plan(title, enemy_class, state, distance, weapon)
            if isinstance(plan, DispatchPlan):
                return plan
            last_error[0] = f"TypeError: dispatch_plan returned {type(plan).__name__}"
        except Exception as exc:                          # noqa: BLE001 - a provider error never stops a tick
            last_error[0] = f"{type(exc).__name__}: {exc}"[:200]
        return _DEFAULT.dispatch_plan(title, enemy_class, state, distance, weapon)
    base = _DEFAULT.dispatch_plan(title, enemy_class, state, distance, weapon)
    K = _k()
    if K is None:
        return base
    try:
        dist_m = None if distance is None else float(distance) / 100.0
        return from_k(K.dispatch_plan(title, enemy_class, state, dist_m, weapon, hp=hp, hp_max=hp_max), base)
    except Exception as exc:                              # noqa: BLE001 - K never raises; a mismatch answers the defaults
        last_error[0] = f"enemy_db plan: {type(exc).__name__}: {exc}"[:200]
        return base


def record(outcome: dict) -> None:
    """One resolved shot or damage event (the outcome dict above): a registered provider's, else K's."""
    p = _PROVIDER[0]
    try:
        if p is not None:
            p.record(dict(outcome))
            return
        K = _k()
        if K is not None:
            K.record_outcome(dict(outcome))
    except Exception as exc:                              # noqa: BLE001 - a lost fact never stops a tick
        last_error[0] = f"{type(exc).__name__}: {exc}"[:200]


def _call(name, *args, **kw) -> None:
    K = _k()
    if K is None:
        return
    try:
        getattr(K, name)(*args, **kw)
    except Exception as exc:                              # noqa: BLE001
        last_error[0] = f"enemy_db {name}: {type(exc).__name__}: {exc}"[:200]


def record_shot(title, enemy_class, state, distance_m, weapon, aim_point, outcome, hp_delta=None, **kw) -> None:
    """K.record_shot (metres; aim_point (up_m, lateral_m) or a world point with enemy_pos, shooter_pos, units_per_m)."""
    _call("record_shot", title, enemy_class, state, distance_m, weapon, aim_point, outcome, hp_delta, **kw)


def record_damage(title, enemy_class, state, distance_m, what_hit_us, hp_loss, **kw) -> None:
    """K.record_damage: one player health loss, blamed on enemy_class (None: unattributed)."""
    _call("record_damage", title, enemy_class, state, distance_m, what_hit_us, hp_loss, **kw)


def observe(title, enemies, t=None) -> None:
    """K.observe: the live enemies within ~15 m ({"id", "cls", "state", "dist_m"}), 5-20 times a second."""
    _call("observe", title, enemies, t)
