"""Sonic Shuffle (USA, MK-51060 V1.000) analysis: pinned board-character loader facts.

All addresses are SH-4 VAs in the unscrambled 1ST_READ.BIN (base 0x8C010000,
sha256 e765a5f5...dd04) and were read from the owned disc with capstone; the
role of each routine is inferred from its call pattern (labelled below).

Board-character load path (per player slot 0..3, struct array 0x8C21D940, stride 0x200):
  setup fn (~0x8C084870): char id = byte [slot+4] (1..8)
    -> alloc 0x8C090282(4, 32) -> buffer stored at [slot+0x80]
    -> open/load file 0x8C096544(NAME_TABLE[char-1])  (C00.MDL..C07.MDL) -> handle byte at [slot+0x84]
    -> model  0x8C084B6A -> 0x8C095A60(handle, 0, MODEL_SEL[char-1])    entry type mask 1<<1 'NJCM'
    -> texture0x8C084BB4 -> 0x8C095B14(handle, 0, TEXLIST_SEL[char-1])   type mask 2? (PVM)
    -> 27 motion slots 0x8C084BE0 -> 0x8C095BA4(handle, slot, MOTION_MAP[slot]) magic 'NMDM'
  The lookup helper 0x8C095186(handle, type_mask, n) returns the n-th entry OF THAT TYPE, so the
  indices above are type-local, not absolute MDL rows (PVMs come first, then NJCM, then NMDM).
Hypotheses (not proved by runtime): which model sub-index is the body, how 0x8C095B14 selects PVMs.
"""
from __future__ import annotations

import struct

BASE = 0x8C010000
FIRST_READ_SHA256 = "e765a5f5e998a9f549d8f062c65fdc478bc4e5e3641b1d2b02f13b156370dd04"

NAME_TABLE_VA = 0x8C0FA624         # 8 x char* -> "C00.MDL".."C07.MDL" (strings at 0x8C0EF8FC, 8 B stride)
NAME_TABLE_XREF_LITERALS = (0x8C083E00, 0x8C08496C)   # literal pools holding the table address
NAME_TABLE_USERS = (0x8C083D28, 0x8C083D5E, 0x8C084918, 0x8C084932)   # mov.l @(pc) loads
PLAYER_NAME_TABLE_VA = 0x8C0FB08C  # pointer table into 0x8C0F1060 player display names (no code xref found)
PLAYER_STRUCT_VA = 0x8C21D940      # 4 slots, stride 0x200; +4 char id (1..8), +0x80 buffer, +0x84 mdl handle
PLAYER_STRIDE = 0x200
MODEL_SEL_VA = 0x8C0FA644          # 8 bytes, all 0 : first NJCM of the MDL is the board model
TEXLIST_SEL_VA = 0x8C0FA64C        # 8 bytes, all 0 : first PVM
MOTION_MAP_VA = 0x8C0FA654         # 27 bytes: motion slot -> NMDM index (type-local)
MOTION_MAP = (0, 1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 33, 34, 38, 93, 0)
FUNCS = {
    "alloc": 0x8C090282, "heap_select": 0x8C0928C4, "mdl_open": 0x8C096544, "mdl_wait": 0x8C09580C,
    "mdl_model": 0x8C095A60, "mdl_texlist": 0x8C095B14, "mdl_motion": 0x8C095BA4,
    "mdl_entry_by_type": 0x8C095186, "board_char_setup_xrefs": 0x8C084918,
    "slot_model": 0x8C084B6A, "slot_texlist": 0x8C084BB4, "slot_motion": 0x8C084BE0,
}
TYPE_MASK = {"pvm": 1, "njcm": 2, "nmdm": 4}   # 0x8C095186 r5 (2 and 4 confirmed by 'NJCM'/'NMDM' magics)
MAGICS = {"njcm": 0x4E4A434D, "nmdm": 0x4E4D444D, "mspc": 0x4350534D}


def u32(exe: bytes, va: int) -> int:
    return struct.unpack_from("<I", exe, va - BASE)[0]


def cstr(exe: bytes, va: int) -> str:
    o = va - BASE
    return exe[o:exe.index(b"\0", o)].decode("latin1")


def literal_loads(exe: bytes, targets) -> dict[int, list[int]]:
    """mov.l @(disp,PC),Rn (0xDnxx) sites whose literal address is in `targets`."""
    targets = set(targets)
    out: dict[int, list[int]] = {}
    for o in range(0, len(exe) - 1, 2):
        op = struct.unpack_from("<H", exe, o)[0]
        if op >> 12 == 0xD:
            a = BASE + o
            t = ((a + 4) & ~3) + (op & 0xFF) * 4
            if t in targets:
                out.setdefault(t, []).append(a)
    return out


def probe(exe: bytes) -> dict:
    """Read the pinned loader tables from 1ST_READ and return them for assertions."""
    names = [cstr(exe, u32(exe, NAME_TABLE_VA + 4 * i)) for i in range(8)]
    loads = literal_loads(exe, NAME_TABLE_XREF_LITERALS)
    # a literal pool slot -> table address is what the code loads
    pools = {va: u32(exe, va) for va in NAME_TABLE_XREF_LITERALS}
    o = MOTION_MAP_VA - BASE
    return {
        "names": names,
        "name_table_ptrs": [hex(u32(exe, NAME_TABLE_VA + 4 * i)) for i in range(8)],
        "literal_pools": {hex(k): hex(v) for k, v in pools.items()},
        "users": sorted(hex(a) for v in loads.values() for a in v),
        "model_sel": list(exe[MODEL_SEL_VA - BASE:MODEL_SEL_VA - BASE + 8]),
        "texlist_sel": list(exe[TEXLIST_SEL_VA - BASE:TEXLIST_SEL_VA - BASE + 8]),
        "motion_map": list(exe[o:o + len(MOTION_MAP)]),
        "player_names": [cstr(exe, u32(exe, PLAYER_NAME_TABLE_VA + 4 * i)) for i in range(8)],
    }


def type_local(entries: list[dict], kind: str, n: int) -> dict:
    """n-th MDL entry of `kind` (what 0x8C095186 resolves) from mdl_table() entries."""
    return [e for e in entries if e["kind"] == kind][n]
