"""Resident Evil 6 (PS3, BLUS30855) — revision-scoped observer for request 3275 Step 2.

Reads screen, mode, character/stage cursors, timer, health, score/combo, and terminal
result/death from a live RPCS3 PS3 session through the gBox RAM reader.

This is a SCAFFOLD: field offsets are declared from the MT Framework pattern (same engine
as RE5 PS3) and the Xbox 360 partial map, but PS3 offsets are not yet live-measured.
Every pointer field carries evidence "pending-live-measurement".  Do not mark
mercs.ready=true until the i9-NUC live session confirms each address.

Host rule: live RE6 sessions run on i9-NUC (ec678a28567942b3), never Spark, never
JAYBUILTFINALE.
"""
from __future__ import annotations

from gbox.mercs import vocab
from gbox import ram_map

MAP_ID = "6fc93ff62e4eb868"


def profile():
    """Load the PS3 RAM map and resolve the Mercenaries vocabulary."""
    return vocab.profile(MAP_ID)


def check() -> list[str]:
    """Vocabulary problems: required names still unknown, names pointing at no field."""
    return vocab.check(profile())


def read_all(reader) -> dict:
    """Read every mapped field from a live RPCS3 PS3 session.

    reader: anything with .read(addr, n) -> bytes (the gBox session RAM reader).
    Returns a flat dict of field name -> value, with unmapped fields as None.
    """
    m = ram_map.load(MAP_ID)
    return m.read(reader)


def observe(reader) -> dict:
    """Revision-scoped observation: screen, mode, cursors, timer, health, score, result.

    Returns a dict with keys:
        screen      – str | None   (title/menu/char_select/stage_select/playing/paused/results/dead)
        mode        – str | None   ("mercenaries" when in Mercenaries mode)
        char_cursor – int | None  (character cursor at char_select)
        stage_cursor– int | None  (stage cursor at stage_select)
        timer       – float | None (Mercenaries round timer, seconds remaining)
        hp          – int | None  (player 1 current HP)
        hp_max      – int | None  (player 1 max HP)
        score       – int | None  (Mercenaries score)
        combo       – int | None  (current combo count)
        kills       – int | None  (kill count)
        result      – str | None  ("clear" | "death" | None while round is running)
    """
    m = ram_map.load(MAP_ID)
    values = m.read(reader)

    # --- screen / mode -------------------------------------------------------
    # RE6 PS3 screen detection is not yet mapped; leave as unknown until live measurement.
    screen = None
    mode = None

    # --- cursors -------------------------------------------------------------
    # Character/stage cursors live in the save-data block; offsets pending live measurement.
    char_cursor = None
    stage_cursor = None

    # --- timer / score / combo -----------------------------------------------
    # cGameSys fields (RE5 PS3 pattern: sBioMain+0x182D4 -> cGameSys); RE6 PS3 offsets pending.
    timer = None
    score = None
    combo = None
    kills = None

    # --- health ---------------------------------------------------------------
    hp = values.get("player.hp")
    hp_max = values.get("player.hp_max")

    # --- terminal result ------------------------------------------------------
    # Death / clear detection requires live observation of the round-state machine.
    result = None

    return {
        "screen": screen,
        "mode": mode,
        "char_cursor": char_cursor,
        "stage_cursor": stage_cursor,
        "timer": timer,
        "hp": hp,
        "hp_max": hp_max,
        "score": score,
        "combo": combo,
        "kills": kills,
        "result": result,
    }


def is_ready(prof=None) -> bool:
    """True when every required vocab name is mapped to a verified live address."""
    prof = prof or profile()
    return not check()
