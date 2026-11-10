"""What an enemy is, in tiers the combat rules can use (boss / heavy / normal / unknown).

The tactical map names a type from its RAM class (``gbox.mercs.enemy_kinds``); the bot needs one step more: is this
thing dangerous enough to spend a grenade ring on? This module answers that with two honest bases only:

* a **measured class table** per title (``CLASS_TIERS``): a class is boss/heavy only once a live round showed it is
  (its name and health were read from RAM). An empty table is not a guess - an unknown class stays "unknown";
* the **maximum health** the game reports for the enemy (``enemy_kinds.threat``): 2000 and up is "heavy" here.

No tier is inferred from a class name pattern. A rule that needs bosses can therefore be tested today (a fake enemy
with the tier), keeps growing as classes are measured, and never upgrades an unknown zombie into a boss.
"""
from __future__ import annotations

from . import enemy_kinds

TIERS = ("boss", "heavy", "normal", "unknown")
HEAVY_HP = 2000                      # maximum health at or above: a heavy hitter even when its class is unnamed

# title id -> class -> tier. Only classes a live round has measured; add rows with the evidence that named them
# (docs/research/re5-switch-ram.md, re6-switch-ram.md, the tactical map's legend).
CLASS_TIERS: dict = {
    "010018100CD46000": {},          # RE5 Switch
    "BLUS30491": {},                 # RE5 PS3
    "01002A000CD48000": {},          # RE6 Switch
}


def tier(enemy, title: str | None = None) -> tuple:
    """(tier, basis, name) for one snapshot enemy: the class table first, then the maximum health."""
    if not isinstance(enemy, dict):
        return "unknown", "none", "unknown"
    cls = enemy.get("class")
    label = enemy_kinds.name(title, cls)
    table = CLASS_TIERS.get(str(title or ""), {})
    if isinstance(cls, str) and cls in table:
        return table[cls], "class_table", label
    maximum = enemy.get("hp_max", enemy.get("max_hp"))
    threat = enemy_kinds.threat(maximum)
    if threat == "high" or (isinstance(maximum, (int, float)) and not isinstance(maximum, bool)
                            and maximum >= HEAVY_HP):
        return "heavy", "hp_max", label
    if threat in ("medium", "low", "none"):
        return "normal", "hp_max", label
    return "unknown", "none", label


def dangerous(enemy, title: str | None = None) -> bool:
    """A boss or a heavy: worth the ring even without a crowd."""
    return tier(enemy, title)[0] in ("boss", "heavy")
