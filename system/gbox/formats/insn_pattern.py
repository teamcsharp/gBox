"""Find code by instruction shape: masked instruction words with register captures.

Overlays, per-stage builds and other regions of a game often hold the same routine at different addresses (MGS VR
Missions: 91 stage overlays, one clear routine each; AKI Revenge PAL patch sites; Nightfire lis/addi pairs). A
pattern names each instruction's fixed bits and the register/immediate fields to capture; a capture used twice must
hold the same value, so "the register loaded here is the one stored there" is part of the pattern.

    P = [Insn(0x3C000000, 0xFC000000, {"rS": (16, 5), "hi": (0, 16)}),        # lui   rS, hi
         Insn(0x24000002, 0xFFE0FFFF, {"rV": (16, 5)}),                       # addiu rV, $zero, 2
         Insn(0xAC000000, 0xFC000000, {"rS": (21, 5), "rV": (16, 5), "lo": (0, 16)})]   # sw rV, lo(rS)
    for hit in search(code, P, base=0x800C4350, big_endian=False): hit.address, hit.fields["hi"], ...

Fixed-width ISAs only: MIPS / PowerPC (4 bytes), SH-4 (2 bytes, width=2).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Insn:
    value: int
    mask: int
    fields: dict = field(default_factory=dict)       # name -> (shift, bits)


@dataclass
class Hit:
    address: int
    offset: int
    fields: dict


def word(code: bytes, off: int, width: int = 4, big_endian: bool = False) -> int:
    return int.from_bytes(code[off:off + width], "big" if big_endian else "little")


def match_at(code: bytes, off: int, pattern: list[Insn], *, width: int = 4, big_endian: bool = False) -> dict | None:
    caps: dict = {}
    for k, ins in enumerate(pattern):
        o = off + k * width
        if o + width > len(code):
            return None
        w = word(code, o, width, big_endian)
        if w & ins.mask != ins.value & ins.mask:
            return None
        for name, (shift, bits) in ins.fields.items():
            v = (w >> shift) & ((1 << bits) - 1)
            if caps.setdefault(name, v) != v:
                return None
    return caps


def search(code: bytes, pattern: list[Insn], *, base: int = 0, width: int = 4, big_endian: bool = False,
           step: int | None = None) -> list[Hit]:
    """Every aligned offset where the whole pattern matches with consistent captures."""
    out = []
    for off in range(0, len(code) - len(pattern) * width + 1, step or width):
        caps = match_at(code, off, pattern, width=width, big_endian=big_endian)
        if caps is not None:
            out.append(Hit(base + off, off, caps))
    return out


def s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def hi_lo(hi: int, lo: int) -> int:
    """lui hi + signed lo (MIPS addiu/lw/sw, PowerPC lis/addi) -> the 32-bit address they build."""
    return ((hi << 16) + s16(lo)) & 0xFFFFFFFF


# MIPS helpers: the common shapes, so a pattern reads like the disassembly
def mips_lui(reg: str, imm: str = "hi") -> Insn:
    return Insn(0x0F << 26, 0xFFE00000, {reg: (16, 5), imm: (0, 16)})


def mips_addiu_imm(reg: str, src: str, imm: str) -> Insn:
    return Insn(0x09 << 26, 0xFC000000, {src: (21, 5), reg: (16, 5), imm: (0, 16)})


def mips_mem(op: int, reg: str, base: str, imm: str) -> Insn:
    """op: 0x23 lw, 0x2B sw, 0x24 lbu, 0x20 lb, 0x25 lhu, 0x21 lh, 0x29 sh, 0x28 sb."""
    return Insn(op << 26, 0xFC000000, {base: (21, 5), reg: (16, 5), imm: (0, 16)})


def mips_jal_targets(code: bytes, base: int, big_endian: bool = False) -> dict[int, list[int]]:
    """{callee: [call sites]} from every jal in the region (call graph without Ghidra)."""
    out: dict[int, list[int]] = {}
    for off in range(0, len(code) - 3, 4):
        w = word(code, off, 4, big_endian)
        if w >> 26 == 3:
            pc = base + off
            out.setdefault(((pc + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2), []).append(pc)
    return out


def ppc_lis_addi(code: bytes, base: int) -> dict[int, list[int]]:
    """{address: [sites]} built by PowerPC lis rX,hi / addi rY,rX,lo pairs (string and table xrefs on GC/Wii)."""
    out: dict[int, list[int]] = {}
    for off in range(0, len(code) - 7, 4):
        a, b = word(code, off, 4, True), word(code, off + 4, 4, True)
        if a >> 26 != 15 or (a >> 16) & 31:                       # lis rD, hi (addis rD, 0, hi)
            continue
        rd = (a >> 21) & 31
        if b >> 26 == 14 and (b >> 16) & 31 == rd:                 # addi rY, rD, lo (signed)
            out.setdefault(hi_lo(a & 0xFFFF, b & 0xFFFF), []).append(base + off)
        elif b >> 26 == 24 and (b >> 21) & 31 == rd:               # ori rY, rD, lo (unsigned)
            out.setdefault((a & 0xFFFF) << 16 | (b & 0xFFFF), []).append(base + off)
    return out
