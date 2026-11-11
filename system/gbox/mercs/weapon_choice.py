"""Shared weapon-choice policy for the Mercenaries titles.

The operator's rule (2026-11-10) is one policy across RE4, RE5 and RE6, keyed only on
*family* plus the match state every title already produces: shotgun up close and into crowds,
rifle at long range, magnum for bosses (Garrador, Chainsaw, Executioner, Gatling), automatic
in between. Operator override (2026-11-10): stop treating the handgun as the default and stop
reaching for a pistol when a rapid-fire magnum, shotgun, machine gun or SMG can be used
instead; the handgun stays as a last-resort fallback, not a preferred pick.

This module owns that scoring rule. Each title maps its own weapons to a ``family`` and
supplies a snapshot of distance / boss flag / crowd flag; no title's weapon IDs, inventory
grid layout, quick-key mapping or RAM offsets leak in here. It is deliberately small: the
policy is the scores in :func:`family_score`, and the rest is the stable input shape.

The exact score table below is carried over verbatim from RE5's verified
``re5_weapons.suitability`` (tests/test_re5_weapons.py), which now delegates to it, so a
behaviour change here is caught by RE5's regression suite.
"""

from __future__ import annotations

# Distance and crowd thresholds are bot tuning values (see re5-weapon-strategy.md), not
# measured game limits. Boss = target hp_max >= 3000, matching the existing RE5 gate.
BOSS_HP_MIN = 3000
CROWD_COUNT = 3
CROWD_RADIUS = 250  # cm from the target, same as the RE5 neighbourhood
SHOTGUN_CLOSE_CM = 800
RIFLE_LONG_CM = 1200

# The four direct-fire families the generic laser/aim controller can fire, plus automatic.
DIRECT_FAMILIES = frozenset({"handgun", "automatic", "shotgun", "rifle", "magnum"})

# Operator override (2026-11-10): the handgun is a last-resort fallback, never a preferred
# pick. It still scores above zero so the bot fires it when it is the only loaded gun, but it
# sits below every direct-fire family in its preferred range, so choose_family and
# best_quick_slot reach for rapid-fire magnum / shotgun / machine gun / SMG first.
HANDGUN_FALLBACK = 5.0


def family_score(family: str, distance: float, boss: bool, crowd: bool) -> float:
    """Score a direct-fire family for a single target at ``distance`` cm.

    Returns the base score before per-family bonuses. ``distance <= SHOTGUN_CLOSE_CM`` is
    "close"; ``distance >= RIFLE_LONG_CM`` is "long". The caller may add bonuses (crowd)
    or penalties (beyond preferred range) on top of this base, exactly as RE5 does.
    """
    base = {
        "handgun": HANDGUN_FALLBACK,
        "automatic": 45.0,
        "shotgun": 55.0 if distance <= SHOTGUN_CLOSE_CM else 15.0,
        "rifle": 50.0 if distance >= RIFLE_LONG_CM else 25.0,
        "magnum": 60.0 if boss else 48.0,
    }
    score = base.get(family)
    if score is None:
        raise ValueError(f"not a direct-fire family: {family!r}")
    return score


def choose_family(distance: float, boss: bool, crowd: bool,
                  loaded: dict[str, float] | None = None) -> str | None:
    """Pick the best direct-fire family for the situation.

    ``loaded`` is an optional {family: adjusted_score} mapping the caller already computed
    (e.g. with a preferred-range penalty applied); when omitted the raw base scores are used.
    Returns the highest-scoring family, or None when nothing is usable.
    """
    candidates = loaded if loaded is not None else {
        f: family_score(f, distance, boss, crowd) for f in DIRECT_FAMILIES
    }
    if not candidates:
        return None
    return max(candidates, key=lambda f: candidates[f])


def shotgun_crowd_bonus(family: str, crowd: bool, distance: float) -> float:
    """+10 for a shotgun into a packed crowd up close (the operator's "spray the crowd")."""
    if family == "shotgun" and crowd and distance <= SHOTGUN_CLOSE_CM:
        return 10.0
    return 0.0
