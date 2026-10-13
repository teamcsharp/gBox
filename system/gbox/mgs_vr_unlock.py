"""Metal Gear Solid: VR Missions (USA): unlock every mission through the game's own clear-flag store.

Where the game keeps "which missions are cleared" (read from SLUS_009.57 and the stage overlays, see
docs/mgs_vr_decomp.md):
  * A 16 x 6-word bit grid, clearflags[row][bit], lives in VRAM at RECT {x=160, y=224, w=12, h=16} (384 bytes), so
    it survives stage loads.  RetroArch cannot address VRAM, so it is never written directly.
  * The result screen (vrclear.c, in every mission overlay) does StoreImage(RECT -> a BSS copy), sets the bit of the
    mission just cleared (GCL param "s": area, stage), then LoadImage(BSS copy -> RECT).
  * The mission-select stage (selectvr.stg overlay 33127.bin) StoreImages the grid into its RAM mirror 0x800E543C at
    menu entry, counts it (the total of all VR missions is 300 = 0x12C), and enables menu items from it: entry
    (category c, level l) is open when bit base[c] + l of row rows[c] - 1 is set (tables 0x800D1DF0 / 0x800D1E38 /
    0x800D1F34 in that overlay; MENU_BITS below is their union, 277 bits).  The memory-card save copies the mirror.

unlock_all rides a normal clear: during a running mission it fills the result routine's BSS copy with MENU_BITS and
turns that routine's StoreImage call into a nop, then completes the mission.  The result screen then sets its own bit
and LoadImages the full grid into VRAM; the menu reads it on the way back.  The overlay is reloaded from the disc on
the next stage load, so the one-instruction patch never outlives the mission.  The patched routine runs for the
first time at the result screen, so a recompiler (lightrec) has no stale copy of it.
"""
from __future__ import annotations

import struct

# selectvr overlay tables (category -> clear-grid row (1-based), first bit, level count); read from 33127.bin
_ROWS = bytes([0, 0, 0, 0, 13, 0, 0, 3, 4, 1, 2, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2,
               0, 0, 0, 0, 0, 0, 0, 0, 3, 4, 3, 4, 3, 4, 3, 4, 3, 4, 3, 4, 3, 4, 3, 4, 0, 0, 6, 5, 11, 10, 9, 12, 13,
               7, 16, 0, 0])
_BASE = bytes([0, 0, 0, 0, 135, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 21, 21, 31, 31, 41, 41, 51, 51, 61, 61, 71, 71,
               81, 81, 91, 91, 0, 0, 0, 0, 0, 0, 0, 0, 21, 21, 31, 31, 41, 41, 51, 51, 61, 61, 71, 71, 81, 81, 91, 91,
               0, 0, 101, 101, 121, 121, 147, 157, 131, 111, 183, 0, 0])
_COUNT = bytes([0, 0, 0, 0, 5, 0, 0, 15, 15, 15, 15, 0, 0, 0, 0, 0, 0, 0, 0, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
                5, 0, 0, 0, 0, 0, 0, 0, 0, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 0, 0, 0, 0, 8, 10, 10, 13,
                0, 3, 8, 0, 0])
MENU_BITS = sorted({(_ROWS[c] - 1, _BASE[c] + lv) for c in range(len(_ROWS)) if _ROWS[c] for lv in range(_COUNT[c])})
TOTAL_MISSIONS = 300           # selectvr compares its count of the grid with 0x12C
GRID_ROWS, GRID_WORDS = 16, 6
SELECT_MIRROR = 0x800E543C     # selectvr's RAM copy of the grid (valid while the stage "selectvr" runs)

STORE_IMAGE, LOAD_IMAGE, DRAW_SYNC = 0x8009060C, 0x800905AC, 0x80090300
NOP = 0


def _jal(target: int) -> int:
    return 0x0C000000 | ((target & 0x0FFFFFFF) >> 2)


def grid_bytes(bits=MENU_BITS, base: bytes | None = None) -> bytes:
    words = list(struct.unpack(f"<{GRID_ROWS * GRID_WORDS}I", base)) if base else [0] * (GRID_ROWS * GRID_WORDS)
    for row, bit in bits:
        words[row * GRID_WORDS + bit // 32] |= 1 << (bit % 32)
    return struct.pack(f"<{GRID_ROWS * GRID_WORDS}I", *words)


def count(grid: bytes) -> int:
    """The game's own count (selectvr 0x800DE8C0): one per set bit; row 12, word 4, bit 12 counts 10."""
    n = 0
    for i, w in enumerate(struct.unpack(f"<{GRID_ROWS * GRID_WORDS}I", grid)):
        row, word = divmod(i, GRID_WORDS)
        for b in range(32):
            if w >> b & 1:
                n += 10 if (row == 12 and word == 4 and b == 12) else 1
    return n


def menu_open(grid: bytes) -> int:
    words = struct.unpack(f"<{GRID_ROWS * GRID_WORDS}I", grid)
    return sum(1 for r, b in MENU_BITS if words[r * GRID_WORDS + b // 32] >> (b % 32) & 1)


def find_flag_store(code: bytes, base: int) -> list[dict]:
    """The result routine's   lui v0,HI / addiu s2,v0,LO / jal StoreImage / move a1,s2 / jal DrawSync / move a0,zero
    followed (within 0x100 bytes) by   jal LoadImage / move a1,s2.  Returns [{grid, store_call, load_call}]."""
    out = []
    tail = (0x02402821, _jal(DRAW_SYNC), 0x00002021)
    for i in range(8, len(code) - 16, 4):
        w = struct.unpack_from("<4I", code, i)
        if w[1:] != tail or w[0] not in (_jal(STORE_IMAGE), NOP):       # NOP: unlock_all already ran this stage
            continue
        lui, addiu = struct.unpack_from("<2I", code, i - 8)
        if lui >> 16 != 0x3C02 or addiu >> 16 != 0x2452:
            continue
        lo = addiu & 0xFFFF
        grid = ((lui & 0xFFFF) << 16) + (lo - 0x10000 if lo & 0x8000 else lo)
        load = None
        for k in range(i + 16, min(len(code) - 4, i + 0x100), 4):
            if struct.unpack_from("<2I", code, k) == (_jal(LOAD_IMAGE), 0x02402821):
                load = base + k
                break
        if load:
            out.append({"grid": grid & 0xFFFFFFFF, "store_call": base + i, "load_call": load})
    return out


def unlock_all(mem) -> dict:
    from . import mgs_vr_tool as T
    stage = T.stage_name(mem)
    if stage == "selectvr":
        mirror = mem.rd(SELECT_MIRROR, GRID_ROWS * GRID_WORDS * 4)
        return {"stage": stage, "unlocked": False, "open_entries": menu_open(mirror), "menu_entries": len(MENU_BITS),
                "cleared_count": count(mirror),
                "error": "the mission-select menu reads the clear grid from VRAM when it opens, so it cannot be "
                         "changed from here: start any mission and run mgs_vr op=unlock_all there (it rides that "
                         "mission's clear), then return to the menu"}
    if not T.is_mission(stage):
        return {"stage": stage, "unlocked": False,
                "error": "start any VR mission, then run unlock_all: it completes that mission and stores every "
                         "clear through the result screen"}
    mgr = T.find_manager(mem)
    if not mgr:
        return {"stage": stage, "unlocked": False, "error": "no vr.c mission manager is running on this stage"}
    lay = T.manager_layout(mem, mgr)
    if mem.u32(lay["state"]) != 1:
        return {"stage": stage, "unlocked": False,
                "error": "the mission is not running (already cleared or over): restart it and run unlock_all again"}
    code = mem.rd(T.OVERLAY_BASE, 0x28000)
    hits = find_flag_store(code, T.OVERLAY_BASE)
    if len(hits) != 1:
        return {"stage": stage, "unlocked": False,
                "error": f"the result screen's clear-flag store was not found uniquely ({len(hits)} matches)"}
    h = hits[0]
    if mem.u32(h["store_call"]) != _jal(STORE_IMAGE):
        return {"stage": stage, "unlocked": False, "error": "the result routine was already changed on this run"}
    grid = grid_bytes(MENU_BITS, mem.rd(h["grid"], GRID_ROWS * GRID_WORDS * 4))
    mem.wr(h["grid"], grid)
    mem.wr(h["store_call"], struct.pack("<I", NOP))
    done = T.complete(mem)
    patched = mem.u32(h["store_call"]) == NOP and mem.rd(h["grid"], len(grid)) == grid
    return {"stage": stage, "unlocked": bool(done.get("completed")) and patched,
            "grid_address": f"{h['grid']:#x}", "store_call": f"{h['store_call']:#x}",
            "menu_entries": len(MENU_BITS), "bits_written": count(grid), "complete": done,
            "note": "the CLEARED screen stores the full grid; back on the mission select every training, weapon, "
                    "advanced and special entry the menu checks is open (mgs_vr op=unlock_all on the menu shows the "
                    "count). Save from the menu to keep it on the memory card. Of the game's 300 clear marks, the "
                    f"menu checks {len(MENU_BITS)}; the other {TOTAL_MISSIONS - len(MENU_BITS)} (photograph / "
                    "variety extras without a menu table entry) are not forced."}
