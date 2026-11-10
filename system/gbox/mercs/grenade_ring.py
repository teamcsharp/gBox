"""When the bot fires the grenade ring by itself - one rule for every Mercenaries title.

The ring (``grenade_ring`` on each title's native controller) spawns ten grenades around the player that bloom
outward and detonate. The operator (2026-10-31, 2026-11-10) wants the bot to fire it without being asked:

* when it is **surrounded**: several enemies within a few metres;
* when it faces a **boss or heavy class** (``gbox.mercs.enemy_identity`` tiers);
* when a crowd is **not thinning** (pressure that stays for seconds).

It must **never fire inside the learned blast reach of the player** (the last blasts the title's own BlastBook
measured: ``bomb_radius_cm`` / ``bomb_safe_cm`` in the live stats grow the ring's radius instead of trusting a
constant), at most once every ``cooldown_s``, and it keeps ``rings_deployed`` / ``ring_kills`` in the live stats.

The rule lives here once; a title contributes one line - ``engine.play_round`` builds ``control(ad, prof)`` and
calls it on every playing tick. Its tunables are the title module's ``RING``, ``RING_N``, ``RING_EVERY_S`` and
``RING_KIND`` constants (the PiP's bot-logic sidebar can set them) over this module's defaults.
"""
from __future__ import annotations

import importlib
import math

from . import enemy_identity

DEFAULTS = {
    "enabled": True,
    "min_enemies": 4,              # a crowd this size inside near_cm is "surrounded"
    "near_cm": 400.0,              # "a few metres" around the player
    "cooldown_s": 20.0,            # at most one ring this often
    "kind": "flash",               # flash is the verified kind on every title that has the ring
    "count": 10,
    "radius_cm": 600.0,
    "inner_cm": 150.0,
    "ripple_ms": 40.0,
    "min_safe_cm": 250.0,          # never closer than this, whatever the blast book says
    "margin_cm": 250.0,            # extra clearance past the learned safe distance
    "max_radius_cm": 2500.0,       # the native ring's own ceiling
    "not_thinning_s": 8.0,         # pressure this long counts as a crowd that is not thinning
    "kill_window_s": 12.0,         # kills inside this window after a ring are attributed to it
}
HISTORY_MAX_S = 20.0
HISTORY_ROUNDS = 32

# (started, count) samples per round for the "not thinning" test, keyed by the round's evidence id.
_HISTORY: dict = {}


def policy(title_module=None, stats=None) -> dict:
    """The defaults, then the title module's operator-set constants, then a ``stats['ring']`` override (tests/tools).

    Bounds are enforced here so a bad saved value can never turn the ring into a zero-radius or one-per-second tic.
    """
    out = dict(DEFAULTS)
    for source in (title_module, (stats or {}).get("ring") if isinstance(stats, dict) else None):
        if source is None:
            continue
        for key, name in (("enabled", "RING"), ("min_enemies", "RING_N"), ("cooldown_s", "RING_EVERY_S"),
                          ("kind", "RING_KIND"), ("radius_cm", "RING_RADIUS_CM")):
            value = source.get(key) if isinstance(source, dict) else getattr(source, name, None)
            if value is not None:
                out[key] = value
    try:
        out["min_enemies"] = max(1, min(int(out["min_enemies"]), 32))
        out["cooldown_s"] = max(1.0, min(float(out["cooldown_s"]), 600.0))
        out["radius_cm"] = max(0.0, min(float(out["radius_cm"]), float(out["max_radius_cm"])))
        out["near_cm"] = max(50.0, min(float(out["near_cm"]), 2000.0))
        out["enabled"] = bool(out["enabled"])
        out["kind"] = str(out["kind"] or "flash")
    except (TypeError, ValueError):
        out.update({k: DEFAULTS[k] for k in ("enabled", "min_enemies", "cooldown_s", "kind", "radius_cm")})
    return out


def _player(snap: dict) -> tuple:
    player = (snap or {}).get("player")
    if isinstance(player, dict):
        pos = player.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            return player, tuple(float(v) for v in pos)
    return None, None


def enemies_near(snap: dict, near_cm: float) -> list:
    """[(distance_cm, enemy)] for the living enemies within near_cm of the player, nearest first."""
    player, pos = _player(snap)
    if player is None or not all(math.isfinite(v) for v in pos):
        return []
    out = []
    for enemy in (snap or {}).get("enemies") or []:
        if not isinstance(enemy, dict) or (enemy.get("hp") or 0) <= 0:
            continue
        epos = enemy.get("pos")
        if not isinstance(epos, (list, tuple)) or len(epos) != 3:
            continue
        try:
            distance = math.dist(pos, (float(epos[0]), float(epos[1]), float(epos[2])))
        except (TypeError, ValueError):
            continue
        if math.isfinite(distance) and distance <= near_cm:
            out.append((distance, enemy))
    return sorted(out, key=lambda row: row[0])


def _history(round_id, now: float) -> list:
    if not round_id:
        round_id = "unbound"
    rows = _HISTORY.setdefault(round_id, [])
    rows.append((now, 0))
    del rows[:-int(HISTORY_MAX_S * 10)]
    while len(_HISTORY) > HISTORY_ROUNDS:
        _HISTORY.pop(next(iter(_HISTORY)))
    return rows


def _not_thinning(round_id, near: int, now: float, policy_: dict) -> bool:
    """Pressure that neither grew nor fell away for not_thinning_s: a crowd the bot is not clearing."""
    rows = _HISTORY.get(round_id or "unbound")
    if not rows:
        return False
    floor = max(2, int(policy_["min_enemies"]) - 2)
    if near < floor:
        return False
    recent = [r for r in rows if now - r[0] <= float(policy_["not_thinning_s"])]
    if len(recent) < 2 or now - rows[0][0] < float(policy_["not_thinning_s"]):
        return False
    return all(count >= floor for _, count in recent)


def observe(stats: dict, snap: dict, now: float, policy_: dict | None = None) -> dict:
    """Per-tick bookkeeping: the crowd history and the kills attributed to the last ring."""
    policy_ = policy_ or policy(stats=stats)
    round_id = stats.get("round_evidence_id") or ""
    player, pos = _player(snap)
    near = len(enemies_near(snap, float(policy_["near_cm"]))) if pos else 0
    rows = _history(round_id, now)
    if rows:
        rows[-1] = (now, near)
    stats["ring_near"] = near
    pending = stats.get("ring_pending")
    if isinstance(pending, dict):
        if now - float(pending.get("at") or 0) > float(policy_["kill_window_s"]):
            stats.pop("ring_pending", None)               # the window closed: later kills are not this ring's
        else:
            kills = snap.get("kills") if isinstance(snap, dict) else None
            if isinstance(kills, int) and isinstance(pending.get("kills"), int) and kills > pending["kills"]:
                stats["ring_kills"] = int(stats.get("ring_kills", 0)) + (kills - pending["kills"])
                pending["kills"] = kills
    return {"near": near, "round": round_id}


def decide(snap: dict, stats: dict, now: float, policy_: dict | None = None, *, title: str | None = None) -> dict:
    """Fire or not, with the reason. Pure apart from the read-only crowd history."""
    policy_ = policy_ or policy(stats=stats)
    player, pos = _player(snap)
    near_rows = enemies_near(snap, float(policy_["near_cm"])) if pos else []
    near = len(near_rows)
    round_id = stats.get("round_evidence_id") or ""
    dangerous = [row for row in near_rows if enemy_identity.dangerous(row[1], title)]
    safe_cm = max(float(stats.get("bomb_safe_cm") or 0.0), float(policy_["min_safe_cm"]))
    radius = max(float(policy_["radius_cm"]), safe_cm + float(policy_["margin_cm"]))
    out = {"fire": False, "kind": policy_["kind"], "radius_cm": round(radius, 1), "near": near,
           "dangerous": len(dangerous), "reason": "", "count": int(policy_["count"]),
           "inner_cm": float(policy_["inner_cm"]), "ripple_ms": float(policy_["ripple_ms"]),
           "safe_cm": round(safe_cm, 1)}
    if not policy_["enabled"]:
        return {**out, "reason": "the ring is switched off (RING)"}
    if stats.get("operator_control") is True:
        return {**out, "reason": "the operator has the pad"}
    screen = stats.get("screen") or (snap or {}).get("screen")
    if screen not in (None, "playing", "unknown"):
        return {**out, "reason": f"the round is not being played ({screen})"}
    if player is None:
        return {**out, "reason": "no player in this snapshot"}
    if radius > float(policy_["max_radius_cm"]):
        return {**out, "reason": (f"the learned blast reach ({safe_cm:.0f} cm) is wider than the ring can place "
                                  f"grenades ({float(policy_['max_radius_cm']):.0f} cm)")}
    last = stats.get("ring_last_at")
    if isinstance(last, (int, float)) and now - last < float(policy_["cooldown_s"]):
        return {**out, "reason": f"{float(policy_['cooldown_s']) - (now - last):.1f} s of the ring cooldown left"}
    if dangerous:
        return {**out, "fire": True, "reason": f"{len(dangerous)} boss/heavy within {policy_['near_cm']:.0f} cm"}
    if near >= int(policy_["min_enemies"]):
        return {**out, "fire": True, "reason": f"surrounded: {near} within {policy_['near_cm']:.0f} cm"}
    if _not_thinning(round_id, near, now, policy_):
        return {**out, "fire": True, "reason": f"a crowd of {near} is not thinning"}
    return {**out, "reason": f"nothing worth a ring: {near} within {policy_['near_cm']:.0f} cm"}


def controller(ad):
    """The title's native controller - the same instance the PiP's worker uses, so its lock serializes both."""
    from . import interventions
    return interventions.native_controller(ad)


def fire(ad, decision: dict, stats: dict, now: float, *, ring=None) -> dict:
    """Run the native ring once and keep the stats. Never raises for a game-side refusal; reports it."""
    target = ring or controller(ad)
    kind = decision.get("kind") or "flash"
    module = type(target).__module__.rsplit(".", 1)[-1]
    try:
        if module == "re4_gc_native":
            receipt = target.grenade_ring(kind)          # RE4's ring picks its own count and radius
        else:
            receipt = target.grenade_ring(kind, count=decision.get("count"), radius_cm=decision.get("radius_cm"),
                                          inner_cm=decision.get("inner_cm"), ripple_ms=decision.get("ripple_ms"))
    except Exception as exc:                             # noqa: BLE001 - a refused ring is a stat, not a crash
        stats["ring_last_at"] = now
        stats["ring_error"] = f"{type(exc).__name__}: {exc}"[:200]
        stats["rings_attempted"] = int(stats.get("rings_attempted", 0)) + 1
        return {"state": "failed", "reason": stats["ring_error"]}
    stats["ring_last_at"] = now
    stats["rings_attempted"] = int(stats.get("rings_attempted", 0)) + 1
    stats.pop("ring_error", None)
    confirmed = isinstance(receipt, dict) and receipt.get("state") == "confirmed"
    if confirmed:
        stats["rings_deployed"] = int(stats.get("rings_deployed", 0)) + 1
        stats["ring_kind_fired"] = receipt.get("kind", kind)
        stats["ring_last_detonated"] = receipt.get("detonated")
        kills = stats.get("kills")
        stats["ring_pending"] = {"at": now, "kills": kills if isinstance(kills, int) else None}
    else:
        stats["ring_last_failure"] = str((receipt or {}).get("reason") or "the ring did not confirm")[:200]
    return receipt if isinstance(receipt, dict) else {"state": "failed", "reason": "no receipt"}


def control(ad, prof, *, ring=None):
    """The engine's one-line hook: build the per-round step that decides, fires and keeps the stats."""
    title_mod = None
    try:
        title_mod = importlib.import_module((prof or {}).get("menus") or "")
    except Exception:                                    # noqa: BLE001 - a title without its own module: defaults
        title_mod = None
    title = (prof or {}).get("map_id")

    def step(snap: dict, stats: dict, now: float, hold=None) -> dict:
        policy_ = policy(title_mod, stats)
        observe(stats, snap, now, policy_)
        decision = decide(snap, stats, now, policy_, title=title)
        stats["ring_decision"] = (decision["reason"] if not decision["fire"] else "fire: " + decision["reason"])[:200]
        if not decision["fire"]:
            return decision
        if hold is not None and hold(set()) is False:
            return {**decision, "fire": False, "reason": "the bot's keys did not release before the ring"}
        try:
            receipt = fire(ad, decision, stats, now, ring=ring)
        except Exception as exc:                         # noqa: BLE001 - a ring never ends the round
            stats["ring_error"] = f"{type(exc).__name__}: {exc}"[:200]
            return {**decision, "fire": False, "reason": stats["ring_error"]}
        decision = {**decision, "fired": True, "receipt": receipt}
        stats["ring_last_reason"] = decision["reason"][:200]
        return decision

    return step


def reset() -> None:
    """Forget the crowd history (tests, and a title change)."""
    _HISTORY.clear()
