"""Crazy Taxi 2 (Dreamcast) analysis probe, request #2454: 1ST_READ.BIN model-table semantics vs the pol/tex files.

For every player model number (PP1A..PP2D) and detail it checks, from the executable's own tables:
  slots    - the slot table's offsets are exactly the object offsets of the pol file (permutation, empties allowed)
  textures - the 16-byte texture table lays the tex file out to its 32-byte aligned size
  alloc    - the pol buffer word * 4 equals the pol file size rounded up to 32 bytes
and lists the literal-pool references to each table (SH-4 `mov.l @(disp,pc)` pools) = the loader's xrefs.
"""
from __future__ import annotations

import struct

from . import crazy_taxi2 as c2

LOADER_VA = 0x0C05AD20


def literal_refs(exe: bytes, va: int) -> list[int]:
    """Virtual addresses (0x0C010000 mirror) of every 4-aligned u32 in the executable equal to `va`."""
    needle = struct.pack("<I", va)
    out, i = [], exe.find(needle)
    while i >= 0:
        if i % 4 == 0:
            out.append(c2.EXE_BASE + i)
        i = exe.find(needle, i + 1)
    return out


def check_model(exe: bytes, pol: bytes, tex: bytes, key: str, high: bool) -> dict:
    t = c2.player_tables(exe, key, high)
    offs = sorted(o.offset for o in c2.walk(pol))
    slots = [s for s in t["slots"] if s != c2.EMPTY]
    tab = t["textures"]
    tex_end = c2._align32(tab[-1]["offset"] + tab[-1]["size"]) if tab else 0
    return {"key": key, "high": high, "slot_count": len(t["slots"]), "empty_slots": len(t["slots"]) - len(slots),
            "slots_subset_of_objects": set(slots) <= set(offs), "objects": len(offs),
            "textures": len(tab), "tex_layout_ok": tex_end == c2._align32(len(tex)),
            "alloc": t["alloc"], "alloc_ok": t["alloc"] == c2._align32(len(pol)), "va": t["va"]}


def probe(disc) -> dict:
    exe = disc.read("1ST_READ.BIN")
    rows = []
    for key in c2.PLAYER_KEYS:
        for high in (False, True):
            stem = key + ("H" if high else "")
            try:
                rows.append(check_model(exe, disc.read(f"POL{stem}.BIN"), disc.read(f"TEX{stem}.BIN"), key, high))
            except (KeyError, ValueError) as e:
                rows.append({"key": key, "high": high, "error": str(e)})
    tbl = c2.known_build(exe)
    refs = {f"{d}.{n}": [hex(r) for r in literal_refs(exe, va)]
            for d, vas in (tbl or {}).items() for n, va in zip(("slots", "counts", "textures", "alloc"), vas)}
    return {"exe_size": len(exe), "known_build": tbl is not None, "loader_va": hex(LOADER_VA),
            "loader_in_exe": 0 <= LOADER_VA - c2.EXE_BASE < len(exe), "models": rows, "table_literal_refs": refs}
