"""Mega Man 64 (USA, NM6E rev0): static MIPS xref scan of the resident code.

Resolves lui+(addiu|ori|load|store) address materialisations and function
starts (addiu sp,sp,-N prologues) so archive/directory readers can be bound to
their callers without Ghidra. Hypothesis generator: verify against Ghidra."""
from __future__ import annotations

import struct

from .mm64_inventory import RAM_DELTA, rom_to_ram

CODE_LO, CODE_HI = 0x1000, 0xAE8D0
_LOADSTORE = {0x20, 0x21, 0x23, 0x24, 0x25, 0x27, 0x28, 0x29, 0x2B, 0x31, 0x35, 0x39, 0x3D}


def _s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def function_starts(rom: bytes, lo: int = CODE_LO, hi: int = CODE_HI) -> list[int]:
    """ROM offsets of `addiu sp,sp,-N` (0x27BDxxxx, N>0) prologues."""
    out = []
    for off in range(lo, hi, 4):
        w = struct.unpack_from(">I", rom, off)[0]
        if w >> 16 == 0x27BD and w & 0x8000:
            out.append(off)
    return out


def address_refs(rom: bytes, lo: int = CODE_LO, hi: int = CODE_HI) -> list[dict]:
    """Every materialised 32-bit constant: {rom, value, kind}."""
    regs: dict[int, int] = {}
    refs = []
    for off in range(lo, hi, 4):
        w = struct.unpack_from(">I", rom, off)[0]
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 0x0F:
            regs[rt] = imm << 16
        elif rs in regs and op in (0x09, 0x0D, *_LOADSTORE):
            v = (regs[rs] + (_s16(imm) if op != 0x0D else 0)) & 0xFFFFFFFF
            if op == 0x0D:
                v = regs[rs] | imm
            refs.append({"rom": off, "value": v,
                         "kind": "addiu" if op == 9 else "ori" if op == 0x0D else "mem"})
            if op in (0x09, 0x0D):
                regs[rt] = v
            elif rt == rs:
                regs.pop(rt, None)
        elif op in (0x02, 0x03) or w == 0x03E00008:
            regs.clear()
        else:
            # destination clobber for common ALU/load forms
            if op == 0 and w:
                regs.pop((w >> 11) & 31, None)
            elif op in _LOADSTORE and op < 0x28:
                regs.pop(rt, None)
    return refs


def refs_to(rom: bytes, targets: set[int], span: int = 0) -> list[dict]:
    """Constants within [t, t+span] for each target, annotated with enclosing function."""
    starts = function_starts(rom)
    import bisect
    out = []
    for r in address_refs(rom):
        if any(t <= r["value"] <= t + span for t in targets):
            i = bisect.bisect_right(starts, r["rom"]) - 1
            fn = starts[i] if i >= 0 else None
            out.append({**r, "ram": rom_to_ram(r["rom"]), "func_rom": fn,
                        "func_ram": None if fn is None else rom_to_ram(fn)})
    return out


RES_TABLE_RAM = 0x800C2DF4     # 8-byte rows {u32 ptr, u16 count, u16 pad}
RES_IDS = 1675
LOADER_BY_ID = 0x80081398      # reads RES_TABLE; called from 0x800359BC
LOADER_ALL = 0x80081690        # same table; dir 0x800BDF70 + base 0x2CAC60
DIR_RAM, ARCHIVE_BASE = 0x800BDF70, 0x2CAC60


def resource_table(rom: bytes) -> list[int]:
    """Resource id -> directory entry index (archive 0x2CAC60) for all ids."""
    from .mm64_inventory import ram_to_rom
    t = ram_to_rom(RES_TABLE_RAM)
    out = []
    for i in range(RES_IDS):
        ptr, cnt, pad = struct.unpack_from(">IHH", rom, t + 8 * i)
        if cnt != 1 or pad:
            raise ValueError("resource row %d malformed" % i)
        out.append(struct.unpack_from(">h", rom, ram_to_rom(ptr))[0])
    return out
