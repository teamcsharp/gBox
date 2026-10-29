"""What each enemy type is, for the live tactical map, the run maps and the run reviewer (operator 2026-10-29: "an
intimate understanding of enemies, what type of enemies ... the level of threat ... show them in the merc live map and
run reviewer with profile pictures as a legend representing what enemies are being represented on the map").

A type is the enemy's RAM class (its vtable's DTI name: uEm10, uEm5200 ...). Its name comes only from a source that
verified it (gbox/mercs/enemy_db.py's shape notes, docs/research/re5-switch-ram.md, re6-switch-ram.md); any other class
shows as its class name until one is confirmed - its portrait, captured from the game itself while the bot's laser sits
on one (gbox/tactical_map.py), shows what it is. The threat comes from the type's maximum health."""
from __future__ import annotations

import re

NAMES = {
    "010018100CD46000": {"uEm10": "Majini", "uEm11": "Majini", "uEm32": "Licker", "uEm62": "Critter (1 health)"},
    "BLUS30491": {"uEm10": "Majini", "uEm11": "Majini", "uEm32": "Licker"},
    "01002A000CD48000": {"uEm5200": "Zombie", "uEm5210": "Zombie", "uEm1000": "J'avo"},
}
THREAT_HP = ((1, "none"), (999, "low"), (1999, "medium"))   # maximum health at or under each: its threat; else "high"
CLASS_RE = re.compile(r"[A-Za-z0-9_.-]{1,40}")
TITLE_RE = re.compile(r"[A-Za-z0-9]{4,24}")


def name(title: str | None, cls: str | None) -> str:
    """The type's verified name, else its class name ("unknown" without one)."""
    return NAMES.get(str(title or ""), {}).get(str(cls or "")) or (str(cls) if cls else "unknown")


def threat(hp_max) -> str | None:
    """none / low / medium / high from the maximum health; None without one."""
    if not isinstance(hp_max, (int, float)) or isinstance(hp_max, bool) or hp_max <= 0:
        return None
    for top, label in THREAT_HP:
        if hp_max <= top:
            return label
    return "high"


def valid_class(cls) -> bool:
    return isinstance(cls, str) and bool(CLASS_RE.fullmatch(cls))


def valid_title(title) -> bool:
    return isinstance(title, str) and bool(TITLE_RE.fullmatch(title))
