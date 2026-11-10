"""PSO's small-data areas, read from the executable's own initialisation code.

The CRT sets the two bases before `main`, in the DOL's init section at `0x8000C180`:

    r2  = 0x805CFD00     (_SDA2_BASE_: the small read-only float pool)
    r13 = 0x805CA600     (_SDA_BASE_: the small data area)

`r13` is why so much of the game's static state has no `lis`/`ori` reference: a global within ±32 KiB of `0x805CA600`
is reached with a displacement - `lwz r3, -0x5260(r13)` - which Ghidra shows as `unaff_r13 + -0x5260`. Anything
*above* `0x805D25FF` (the top of that window) cannot be addressed that way at all, which is why the class-name table at
`0x805D3138` has no direct code reference (it must be resolved through a pointer variable).

`globals_used(dol)` decodes every D-form load/store that uses `r13` as its base and returns
`{absolute address: [instruction addresses]}`, so the lane can name the globals it already knows
(`pso_ram`'s addresses) and find the ones it does not.
"""
from __future__ import annotations

import struct

SDA_BASE = 0x805CA600
SDA2_BASE = 0x805CFD00
INIT_SECTION_CODE = 0x8000C180          # the two lis/addi pairs that set r2 and r13

#: D-form (displacement) opcodes that load or store through a base register, by primary opcode
D_FORM = frozenset(range(32, 56))


def _s16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def sda_address(displacement: int, base: int = SDA_BASE) -> int:
    """The absolute address of an `r13`-relative global. Raises ValueError outside the ±32 KiB window."""
    if not -0x8000 <= displacement <= 0x7FFF:
        raise ValueError(f"{displacement:#x} does not fit the r13 displacement window")
    return (base + displacement) & 0xFFFFFFFF


def globals_used(dol: bytes) -> dict:
    """{absolute address: [pc, ...]} for every D-form access through r13 (and the addi/addis forms)."""
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    out: dict[int, list[int]] = {}
    for i in range(18):
        if not sizes[i]:
            continue
        blob = dol[offs[i]:offs[i] + sizes[i]]
        for p in range(0, len(blob) - 4, 4):
            pc = addrs[i] + p
            w = struct.unpack_from(">I", blob, p)[0]
            op, ra, disp = w >> 26, (w >> 16) & 31, w & 0xFFFF
            if ra != 13:
                continue
            if op in D_FORM:
                out.setdefault((SDA_BASE + _s16(disp)) & 0xFFFFFFFF, []).append(pc)
            elif op in (14, 15):                      # addi / addis rd, r13, imm
                rd = (w >> 21) & 31
                nxt_off = p + 4
                if nxt_off + 4 <= len(blob):
                    nxt = struct.unpack_from(">I", blob, nxt_off)[0]
                    if (nxt >> 26) == 14 and ((nxt >> 21) & 31) == rd and ((nxt >> 16) & 31) == rd:
                        total = (disp << 16) + _s16(nxt & 0xFFFF)
                        out.setdefault((SDA_BASE + total) & 0xFFFFFFFF, []).append(pc)
                        continue
                out.setdefault((SDA_BASE + _s16(disp)) & 0xFFFFFFFF, []).append(pc)
    return {addr: sorted(pcs) for addr, pcs in sorted(out.items())}


def candidates(dol: bytes, known: dict | None = None) -> list:
    """The globals the code touches, with the name of a known one when `known` maps address -> name."""
    known = known or {}
    return [{"address": addr, "name": known.get(addr), "uses": len(pcs), "first": pcs[0]}
            for addr, pcs in globals_used(dol).items()]
