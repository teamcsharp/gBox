"""Code-derived asset-loader facts for Yoshi's Story (N64, USA NYSE rev 0).

Analysis stage of #1323.  Every fact here is re-read from the owned ROM's
``main`` code (ROM 0x1070 -> VRAM 0x80000470) instead of being trusted as a
constant, so a different build fails loudly:

* ``boot_file_tables``: the init routine at 0x80007d88 stores three RAM file
  tables (0x800B4860, 0x800B4360, 0x800B4C80) and relocates each one with
  ``FileTable_Relocate`` (0x800067EC) against a ROM base passed in ``a1``
  (0x4F3930, 0xB58B0, 0xE1AD0).  A table is ``s16 count`` + 0x10 header,
  then 0x10-byte entries ``{u32 offset, u32 size, u8 kind, u8 sub, ...}``;
  entries with kind 2 get ``offset += rom_base``.
* those three tables are the AUDIO bank: 62 instrument banks (ADPCM books,
  0xB58B0-0xE1AD0), 2 sample tables (0xE1AD0-0x4F3930) and 65 sequences
  (0x4F3930-0x526EC0).  The high-entropy span the inventory flagged as a
  possible sprite codec is ADPCM sample data; sprites are not compressed
  there.
* ``ROM_COPY`` (0x80007674) is the generic ROM->RAM loader: it invalidates
  the destination (0x8000AC90) and copies in 0x400-byte PI chunks through
  the handle at 0x800B6848.  The texture-slot loaders (0x80008C3C,
  0x8000938C) read ``{u32 mode<<26 | size24, u32 rom}`` records from the
  slot table at 0x800B0180; mode 1 goes to ``DECOMPRESS_STUB`` (0x80007798),
  which is an empty function in retail, every other mode is a raw copy.
  So retail sprite texture data is stored uncompressed.
* ``OBJ_DRAW`` (0x8007BEE8) emits GBI1 (F3DEX) ``G_MOVEWORD`` 0xBC
  segment words itself: segment ``(seg_addr >> 24) & 0xF`` gets base
  ``dl_ram - (seg_addr & 0xFFFFFF)``.  A frame's segment-3 offsets are
  therefore offsets into the loaded sprite *file* that contains its display
  list, not a separate texture buffer.  No ``gSPSegment`` word or
  ``lui 0xDB06`` exists anywhere in the ROM (the microcode is GBI1).
"""
from __future__ import annotations

import struct

MAIN_ROM, MAIN_VRAM, MAIN_END = 0x1070, 0x80000470, 0xB58B0

FILE_TABLE_RELOCATE = 0x800067EC
ROM_COPY = 0x80007674
DECOMPRESS_STUB = 0x80007798
OBJ_DRAW = 0x8007BEE8
BOOT_TABLES_AT = 0x80007D88
SLOT_LOADERS = (0x80008C3C, 0x8000938C)
PI_HANDLE = 0x800B6848
SLOT_TABLE = 0x800B0180

AUDIO_ROLE = {0x800B4360: "instrument_banks", 0x800B4C80: "sample_tables",
              0x800B4860: "sequences"}


def _w(rom: bytes, va: int) -> int:
    return struct.unpack_from(">I", rom, va - MAIN_VRAM + MAIN_ROM)[0]


def _ram(va: int) -> int:
    return va - MAIN_VRAM + MAIN_ROM


def _lui_pairs(rom: bytes, start: int, end: int):
    """Yield (pc, rt, value) for lui+addiu/ori pairs in [start, end)."""
    hi: dict[int, int] = {}
    for pc in range(start, end, 4):
        w = _w(rom, pc)
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 0x0F:
            hi[rt] = imm << 16
        elif op in (0x09, 0x0D) and rs in hi:
            v = (hi[rs] | imm) if op == 0x0D else (hi[rs] + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
            yield pc, rt, v


def _jal(target: int) -> int:
    return (3 << 26) | ((target >> 2) & 0x3FFFFFF)


def boot_file_tables(rom: bytes) -> list[dict]:
    """Re-derive the (table, rom_base) pairs relocated at boot from code."""
    start, end = BOOT_TABLES_AT, BOOT_TABLES_AT + 0x6C
    tables, bases, calls = {}, [], []
    regs: dict[int, int] = {}
    for pc, rt, v in _lui_pairs(rom, start, end):
        regs[rt] = v
        if 0x800B0000 <= v < 0x800C0000:
            tables[rt] = v
        if rt == 5 and v < 0x1000000:  # a1 = ROM base
            bases.append((pc, v))
    for pc in range(start, end, 4):
        if _w(rom, pc) == _jal(FILE_TABLE_RELOCATE):
            calls.append(pc)
    if len(calls) != 3 or len(bases) != 3:
        raise ValueError("boot file-table relocation calls not found; wrong build?")
    # call order: a0 = t7 table (sequences), then lw 0x1d68/0x1d6c (s1 slots) in
    # the order they were stored: t6 -> 0x1d68, t8 -> 0x1d6c.
    order = [tables.get(4), tables.get(14), tables.get(24)]
    out = []
    for (pc, base), table in zip(bases, order):
        if table is None:
            raise ValueError("file-table address not resolved")
        out.append({"table": table, "rom_base": base, "set_at": pc,
                    "role": AUDIO_ROLE.get(table), "entries": file_table(rom, table, base)})
    return out


def file_table(rom: bytes, table: int, rom_base: int) -> list[dict]:
    """Parse one relocatable file table (``s16 count``, 0x10-byte entries at +0x10)."""
    o = _ram(table)
    n = struct.unpack_from(">h", rom, o)[0]
    if not 0 < n < 0x400:
        raise ValueError(f"implausible file-table count {n} at {table:#x}")
    ents = []
    for k in range(n):
        off, size, kind, sub = struct.unpack_from(">IIBB", rom, o + 0x10 + k * 0x10)
        rom_off = off + rom_base if kind == 2 else off
        ents.append({"index": k, "rom": rom_off, "size": size, "kind": kind, "sub": sub})
    return ents


def is_empty_stub(rom: bytes, va: int) -> bool:
    """True when ``va`` only spills a0-a3 to the caller's frame and returns."""
    expect = (0xAFA40000, 0xAFA50004, 0xAFA60008, 0x03E00008, 0xAFA7000C)
    return tuple(_w(rom, va + 4 * i) for i in range(5)) == expect


def rom_copy_chunk(rom: bytes) -> int:
    """Return the PI chunk size compared by ROM_COPY (``sltiu at, s0, N``)."""
    for pc in range(ROM_COPY, ROM_COPY + 0x80, 4):
        w = _w(rom, pc)
        if w >> 26 == 0x0B:  # sltiu
            return w & 0xFFFF
    raise ValueError("ROM_COPY chunk compare not found")


def slot_loader_modes(rom: bytes, func: int) -> dict:
    """Find the mode test (``(w<<4)>>30 == 1``) and the two loader calls."""
    calls = []
    sll4 = srl30 = False
    for pc in range(func, func + 0x400, 4):
        w = _w(rom, pc)
        if (w & 0xFC00003F) == 0 and (w >> 6) & 31 == 4:
            sll4 = True
        if (w & 0xFC00003F) == 2 and (w >> 6) & 31 == 30:
            srl30 = True
        if w in (_jal(DECOMPRESS_STUB), _jal(ROM_COPY)):
            calls.append((pc, "decompress_stub" if w == _jal(DECOMPRESS_STUB) else "rom_copy"))
    return {"func": func, "mode_bits_26_27": sll4 and srl30, "calls": calls}


def segment_setter(rom: bytes) -> dict:
    """Confirm OBJ_DRAW builds ``0xBC000006 | (seg*4)<<8`` and base = dl - off."""
    words = [_w(rom, OBJ_DRAW + 4 * i) for i in range(0x50)]
    lui_bc = any(w == 0x3C01BC00 for w in words)  # lui at, 0xbc00
    ori6 = any(w >> 26 == 0x0D and w & 0xFFFF == 6 for w in words)
    subu = any((w & 0xFC0007FF) == 0x23 for w in words)
    dl = any(w == 0x3C0B0600 for w in words)  # lui t3, 0x0600 (G_DL)
    if not (lui_bc and ori6 and subu and dl):
        raise ValueError("OBJ_DRAW segment pattern not found")
    return {"func": OBJ_DRAW, "gbi": "GBI1/F3DEX", "moveword": 0xBC, "base": "dl_ram - (seg_addr & 0xFFFFFF)"}


def gbi1_vtx(w0: int, w1: int) -> dict:
    """Decode a GBI1/F3DEX ``G_VTX`` (0x04) command."""
    if w0 >> 24 != 0x04:
        raise ValueError("not a GBI1 G_VTX")
    n = (w0 >> 10) & 0x3F
    return {"v0": ((w0 >> 16) & 0xFF) // 2, "n": n, "length": (w0 & 0x3FF) + 1,
            "segment": (w1 >> 24) & 0xF, "offset": w1 & 0xFFFFFF}


def audio_kind(rom: bytes, ent: dict) -> str:
    """Cheap content check: instrument banks carry ADPCM books (order 2, 2 predictors)."""
    blob = rom[ent["rom"]:ent["rom"] + ent["size"]]
    if b"\x00\x00\x00\x02\x00\x00\x00\x02" in blob:
        return "ctl"
    return "data"


def analysis(rom: bytes) -> dict:
    tables = boot_file_tables(rom)
    spans = []
    for t in tables:
        e = t["entries"]
        spans.append({"role": t["role"], "table": hex(t["table"]), "rom_base": hex(t["rom_base"]),
                      "count": len(e), "start": hex(e[0]["rom"]), "end": hex(e[-1]["rom"] + e[-1]["size"])})
    return {
        "file_tables": spans,
        "rom_copy": {"func": hex(ROM_COPY), "chunk": rom_copy_chunk(rom), "pi_handle": hex(PI_HANDLE)},
        "decompress_stub_empty": is_empty_stub(rom, DECOMPRESS_STUB),
        "slot_loaders": [slot_loader_modes(rom, f) for f in SLOT_LOADERS],
        "segment_setter": segment_setter(rom),
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys
    from . import n64_rom
    r = n64_rom.read(sys.argv[1]) if not sys.argv[1].endswith(".z64") else open(sys.argv[1], "rb").read()
    print(json.dumps(analysis(r), indent=1, default=str))
