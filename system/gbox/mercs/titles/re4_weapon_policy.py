"""RE4 (Switch, 010099A00BC1E000 v1.0.2) weapon families and the shared weapon-choice policy.

The operator's rule (2026-10-24) is ONE policy across RE4, RE5 and RE6: shotgun up close
and into crowds, rifle at long range, handgun as the default, magnum for bosses. The
scoring lives in gbox.mercs.weapon_choice; this module only maps RE4 item ids to that
policy's families and supplies the situation snapshot (distance / boss / crowd) from the
fields re4_weapons already decodes. The operator's RE4 boss set for the magnum rule:
Garrador, Chainsaw (Dr. Salvador), Executioner (for the RE5-side naming; RE4's own
chainsaw majors are the same rule), Gatling man - all are hp_max >= BOSS_HP_MIN targets
in Mercenaries, so the shared hp gate covers them.

No RAM offsets here (re4_weapons owns those, read-only); no RE5/RE6 ids leak in.
"""
from __future__ import annotations

import math

from gbox.mercs import weapon_choice
from gbox.mercs.titles import re4_weapons as re4

# item id -> family, one row per gun the Mercenaries loadouts can hold (re4_weapons.NAMES /
# CLASS_OF are the measured table; the family is the shared policy's key). Ammo-only ids,
# attachments and grenades are not families and stay out.
FAMILY_OF = {
    # handguns
    0x03: "handgun", 0x21: "handgun", 0x23: "handgun", 0x24: "handgun", 0x25: "handgun",
    0x26: "handgun", 0x27: "handgun", 0x40: "handgun",
    # shotguns
    0x2C: "shotgun", 0x2D: "shotgun", 0x94: "shotgun", 0x47: "shotgun",
    # rifles (scoped, the long-range family)
    0x2E: "rifle", 0x2F: "rifle", 0x6B: "rifle", 0x6C: "rifle", 0x51: "rifle", 0x99: "rifle",
    # magnums
    0x29: "magnum", 0x2A: "magnum",
    # automatics
    0x30: "automatic", 0x32: "automatic", 0x3E: "automatic",
    # specials: not in the shared direct-fire table; suitability gates them behind -1000
    0x52: "bow", 0x36: "mine", 0x35: "rocket", 0x17: "rocket", 0x6D: "rocket", 0x41: "rocket",
    0x38: "knife",
}
DIRECT = weapon_choice.DIRECT_FAMILIES

# RE4 has no RE5-style boss switch beyond hp: the Mercenaries majors (Garrador,
# Chainsaw, Gatling man, Super Salvador) are all >= the shared BOSS_HP_MIN, so the same
# hp_max gate is the boss flag.
def family(iid: int) -> str | None:
    return FAMILY_OF.get(iid)


def suitability(item: dict, snap: dict, target: dict) -> float:
    """Score one decoded re4_weapons item (dict from decode_item / Reader.items) for a
    target, exactly the way RE5's re5_weapons.suitability does: -1000 when the family is
    not one the generic policy scores (or the magazine is empty), else the shared
    family_score + shotgun crowd bonus. RE4-specific additions stay out on purpose; when
    a per-title penalty is ever measured it is added here, not in weapon_choice.
    """
    iid = item.get("id")
    fam = FAMILY_OF.get(iid) if iid is not None else None
    if fam is None or fam not in DIRECT:
        return -1000.0
    if not item.get("in_use") or not item.get("loaded"):
        return -1000.0
    try:
        distance = math.dist(snap["player"]["pos"], target["pos"])
    except (KeyError, TypeError, ValueError):
        return -1000.0
    boss = (target.get("hp_max") or 0) >= weapon_choice.BOSS_HP_MIN
    crowd = sum(1 for e in snap.get("enemies", ()) if (e.get("hp") or 0) > 0
                and math.dist(target["pos"], e["pos"]) < weapon_choice.CROWD_RADIUS
                ) >= weapon_choice.CROWD_COUNT
    score = weapon_choice.family_score(fam, distance, boss, crowd)
    score += weapon_choice.shotgun_crowd_bonus(fam, crowd, distance)
    return score


def best_item(items: list, snap: dict, target: dict, margin: float = 0.0) -> dict | None:
    """The best-scoring loaded weapon of the decoded item list (None when nothing scores
    above -1000, or nothing beats the incumbent by ``margin`` when the incumbent is
    passed in as the item with ``hand`` True)."""
    loaded = [it for it in items if suitability(it, snap, target) > -1000.0]
    if not loaded:
        return None
    return max(loaded, key=lambda it: suitability(it, snap, target))
