"""Title: Resident Evil 3 - Nemesis (PlayStation, SLUS-00923), 'Operation Mad Jackal' Mercenaries mode.

This module records what is and is not yet proven for the PSX RE3 native runner, so the MercMode
scheduler can list RE3 honestly and a future verified combat driver can slot in without touching
the catalog schema.

Unlike RE4 (GameCube) and RE5 (PS3), the PSX RE3 runner does not yet expose a reviewed RAM map to
gBox. There is therefore no combat driver, no menu cursor, no Mercenaries timer reader and no
terminal-round reader to wire into the MercMode scheduler today. Those addresses must come from a
reviewed native inspection plan (see inspection_builds: op=plan) before this entry can turn
playable -- none are fabricated here.

The mode itself is a known quantity: RE3's unlockable 'Operation Mad Jackal' bonus mode (unlocked
as the 'Mercenaries' game after completing the story) gives three characters -- Carlos, Mikhail
and Nicholai -- each on a same-floor time-attack route from the cable car to the warehouse, with a
hostage-chip time-extend objective and a boss at the end (the Nemesis / Nemesis-2 in Nicholai's
route). Those facts are for the catalog and the plan; they are not live-RAM evidence.
"""
from __future__ import annotations

from ..driver import Driver


GAME_ID = None                     # resolved from the catalog game_ids, not guessed here
PLATFORM = "psx"
TITLE = "Resident Evil 3: Nemesis"
MAP_ID = "SLUS-00923"
MODES = ["mercenaries"]


# Operation Mad Jackal roster (catalog facts; native roster order to be verified).
OJ_ROSTER = ["Carlos", "Mikhail", "Nicholai"]

# Unlock: completing the story unlocks the 'Mercenaries' bonus game. Save-based; whether any of the
# three characters gate behind score ranks is part of the pending inspection plan.
UNLOCK_REASON = "Save-based story completion; live-RAM unlock address not yet reviewed."


class RE3PSX(Driver):
    """Honest, non-playing RE3 driver.

    The PSX runner exposes no reviewed RAM map to gBox, so every read-based hook degrades to
    'unavailable' rather than inventing an address. Replacing this class with a verified combat
    driver (later) is a drop-in: the catalog key and schema stay fixed.
    """

    map_id = MAP_ID

    def snapshot(self, m) -> dict:
        return {}                    # no reviewed RAM map: nothing to read

    def screen(self, m, snap: dict | None) -> str:
        return "unavailable"

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        raise NotImplementedError("RE3 Operation Mad Jackal has no verified Mercenaries combat driver")

    def prompt_source(self, m, stats: dict):
        return None

    def prompt_keys(self, button) -> list:
        return [(button,)]

    def progress(self, snap: dict) -> dict:
        return {}


DRIVER = RE3PSX


def profile() -> dict:
    """RE3 Operation Mad Jackal unlock/play profile (research-pending, honestly)."""
    return {
        "game_id": GAME_ID,
        "platform": PLATFORM,
        "title": TITLE,
        "map_id": MAP_ID,
        "status": "research_pending",
        "verified": False,
        "scope": [
            "Operation Mad Jackal (Mercenaries) mode: Carlos, Mikhail, Nicholai",
            "Three same-floor time-attack routes (cable car -> warehouse) with hostage-chip extends",
            "End-of-route boss (Nemesis); Nicholai route: Nemesis-2",
        ],
        "evidence": {"region": None, "roster": OJ_ROSTER, "unlock": UNLOCK_REASON},
        "known_gaps": [
            "No reviewed RAM map for the PSX RE3 runner",
            "No combat driver, menu cursor, timer or terminal-round reader",
            "Unlock rank thresholds per character not yet confirmed",
        ],
        "requires_live_testing": True,
        "next_steps": [
            "1. Produce a reviewed native inspection plan (inspection_builds op=plan) for the PSX RE3 runner",
            "2. Resolve the save-based story-completion unlock and per-character rank gates",
            "3. Map the Mercenaries timer, character/hp and boss fields from a live session",
            "4. Implement a verified RE3 driver and flip TITLES['re3']['playable']",
            "5. Test on Spark (2% audio), never JAYBUILTFINALE",
        ],
    }
