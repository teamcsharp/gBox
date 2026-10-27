"""Resident Evil 4 Mercenaries bot: per-edition RAM offset relocation (GC -> other editions).

The GameCube bot (gbox/re4_merc_bot.py) hard-codes the GC (G4BE08) RAM layout. Porting the bot
to another RE4 edition (Wii 79c3a3eccb34fe62 / RB4P08 first, then PS2/Xbox360/UHD, then the
remake) means reading the same values at the edition's real addresses. This module is that
provider:

  * EDITIONS maps each catalog game id to its mapped edition;
  * edition(game_id) -> the edition id or None if not mapped;
  * offsets(game_id) -> the per-edition RAM offsets the bot reads (the GC values verbatim until
    a relocation against the target edition's executable succeeds);
  * locate(haystack) -> {name: address} relocated into another edition's executable image
    (the extracted main.dol bytes, or the Dolphin RAM view), by masked code-signature scan.

How relocation works (evidence-backed, no fall-through):

Each relocatable global is materialized in code by a `lis rt,<hi>; addi rt,rt,<lo>` pair whose
sum is the GC address. The surrounding instruction window is stable across builds of the same
engine, while the lis/addi immediates move with the new layout. So each signature is a 5-word
window (the two words before the pair, the pair itself with the low 16 bits of each masked, and
the word after). A match must be unique in the haystack; the new address is read from the
target's own immediates. locate() returns None unless every signature matches exactly once.

Evidence discipline (request #3350): every address cites the exact executable revision and its
SHA256. The GC anchors below come from the G4BE08 main.dol,
SHA256 f7cc1074b4cecc861b4b541d649c2bb644de248e62bed15f96b873bdb93ad4c2
(/home/ehm_eckx/gBox_alt/scratch/re4-ram/main.dol, on the Spark). The Wii SHA256 must be filled
from the extracted RB4P08 main.dol (gbox/re4wii.py ensure_base) before Wii reads are trusted:
`python -m gbox.re4_editions --sha <main.dol>`.

Known limit: P_GLOBAL and P_PLAYER_PTR are read via the small-data register (lwz -0x7500(r13) /
lwz -0x673C(r13)); r13's runtime value is not materialized in code, so those two anchors cannot
be relocated by code scan alone. They need one live read of r13 on the target (Dolphin
register/context dump) or a Ghidra pass on the target's __init. locate() therefore reports them
as None until a target r13 is supplied (locate(..., r13=...)); the caller must refuse to run the
bot on an edition whose table has Nones.
"""
from __future__ import annotations

import hashlib
import json
import struct

# The GameCube layout the bot reads (G4BE08). Values match re4_merc_bot.py constants exactly
# (cross-checked against system/profiles/gamedata/G4BE08-ram.json: player.ptr 0x802B3044 =
# 0x802B9780 - 0x673C, game.global 0x802B2280, emmgr.base 0x8027DF20, pad.stick 0x80287E90,
# merc.timer 0x80279308, merc.combo base 0x8021392C, player.aim_pitch 0x80218738).
R13 = 0x802B9780  # the game's small-data-area base (live 2026-10-20 on the Spark)
GC_OFFSETS = {
    "EMMGR": 0x8027DF20,              # EmMgr: every live Ganado's slot table
    "P_PLAYER_PTR": R13 - 0x673C,     # stored pointer to the player em (slot 0)
    "P_GLOBAL": R13 - 0x7500,         # global game struct (aim pitch parent, routine)
    "MERC_TIMER": 0x80279308,         # the Mercenaries clock (frames at 30 fps)
    "MERC": 0x8021392C,               # Mercenaries mode state (combo bonus, kills)
    "AIM_PITCH": 0x80218738,          # aim vertical blend, f32 -1..+1 (global, kept between aims)
    "GAME_PAD": 0x80287E90,           # the game's pad as the aim routine reads it
}

# 5-word masked code windows from the G4BE08 main.dol
# (SHA256 f7cc1074b4cecc861b4b541d649c2bb644de248e62bed15f96b873bdb93ad4c2).
# words: (w[-8], w[-4], lis, addi, w[+8]); mask 0xFFFF0000 on the lis/addi immediates.
# MERC_TIMER and AIM_PITCH have no direct code materialization in this build (they were found by
# AR-code / live probing); they inherit the data-section delta of the confirmed anchors only if
# every confirmed anchor agrees on one delta, else they stay unresolved.
CODE_SIGS = {
    "EMMGR": (0x8027DF20,
              (0x2C000000, 0x4082001C, 0x3C608028, 0x3863DF20, 0x480C3AAD)),
    "GAME_PAD": (0x80287E90,
                 (0x7D696379, 0x418200B4, 0x3D208028, 0x39097E90, 0x89680001)),
    "MERC": (0x8021392C,
             (0x38210020, 0x4E800020, 0x3D208021, 0x38C9392C, 0x2C060000)),
}
_SIG_MASKS = (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF0000, 0xFFFF0000, 0xFFFFFFFF)

# Anchors the code scan cannot relocate by itself (r13-relative; see module docstring).
R13_RELATIVE = ("P_PLAYER_PTR", "P_GLOBAL")
# Anchors with no code materialization at all; resolved only by a common confirmed delta.
DELTA_ONLY = ("MERC_TIMER", "AIM_PITCH")

# Catalog game id -> edition. GC is the reference the bot already plays; the Wii catalog id
# (79c3a3eccb34fe62) is the first port target (same engine, Dolphin, RB4P08 image).
EDITIONS = {
    "G4BE08": "gc",
    "79c3a3eccb34fe62": "wii",      # PAL disc header RB4P08, English (see gbox/re4wii.py)
}

# SHA256 of the exact executable each edition's offsets were derived against.
EXEC_SHA256 = {
    "gc": "f7cc1074b4cecc861b4b541d649c2bb644de248e62bed15f96b873bdb93ad4c2",
    "wii": "",                      # run: python -m gbox.re4_editions --sha <RB4P08 main.dol>
}


def edition(game_id: str) -> str | None:
    """GAME_IDS/catalog key -> edition id, or None if this catalog id is not mapped."""
    return EDITIONS.get(game_id)


def offsets(game_id: str) -> dict | None:
    """The RAM offsets the bot must read for this edition (copy of GC_OFFSETS until relocated)."""
    return dict(GC_OFFSETS) if edition(game_id) else None


def _s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def locate(haystack: bytes, r13: int | None = None) -> dict | None:
    """Relocate GC_OFFSETS into another edition's executable image (main.dol bytes, or a Dolphin
    RAM view that contains the loaded text).

    Every CODE_SIGS window must match exactly once, word-aligned; each match's own lis/addi
    immediates give that anchor's new address. MERC_TIMER/AIM_PITCH (no code refs) are resolved
    only if all confirmed anchors agree on a single delta. P_PLAYER_PTR/P_GLOBAL need the
    target's runtime r13 (small-data base); pass it to resolve them, else they are None.

    Returns {name: address-or-None}, or None if any code signature fails (never a fall-through:
    a wrong relocation silently corrupts the bot's reads).
    """
    if not haystack or len(haystack) < 20:
        return None
    found: dict[str, int] = {}
    for name, (gc_addr, words) in CODE_SIGS.items():
        hits = []
        for i in range(0, len(haystack) - 20, 4):
            ok = True
            for w, m, want in zip(struct.unpack_from(">5I", haystack, i), _SIG_MASKS, words):
                if w & m != want & m:
                    ok = False
                    break
            if ok:
                w2, w3 = struct.unpack_from(">2I", haystack, i + 8)
                hits.append(((w2 & 0xFFFF) << 16) + _s16(w3 & 0xFFFF))
        if len(hits) != 1:
            return None
        found[name] = hits[0]
    deltas = {a - CODE_SIGS[n][0] for n, a in found.items()}
    table = dict.fromkeys(GC_OFFSETS)
    table.update(found)
    if len(deltas) == 1:
        d = deltas.pop()
        for n in DELTA_ONLY:
            table[n] = GC_OFFSETS[n] + d
    if r13 is not None:
        for n in R13_RELATIVE:
            if table[n] is None:
                table[n] = r13 - (R13 - GC_OFFSETS[n])
    return table


def sha256_file(path: str) -> str:
    """The exact SHA256 of an edition's executable (main.dol), for the evidence citation."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def self_check(dol_path: str) -> bool:
    """The GC dol itself must relocate to the exact GC_OFFSETS addresses (identity proof)."""
    with open(dol_path, "rb") as f:
        data = f.read()
    if sha256_file(dol_path) != EXEC_SHA256["gc"]:
        return False
    table = locate(data, r13=R13)
    return bool(table) and all(table[n] == GC_OFFSETS[n] for n in CODE_SIGS) \
        and all(table[n] == GC_OFFSETS[n] for n in R13_RELATIVE)


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--sha":
        print(sha256_file(sys.argv[2]))
        sys.exit(0)
    print(json.dumps({"editions": EDITIONS, "gc_offsets": GC_OFFSETS,
                      "code_sigs": list(CODE_SIGS), "wii_sha256_set": bool(EXEC_SHA256["wii"])},
                     indent=2))
