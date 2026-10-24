"""Madden NFL 2005 (GameCube, GNQE69) analysis stage: TERF archive index + main.dol loader xrefs (#2007).

Reproducible, read-only findings (all derived from the owned disc bytes):

TERF archive layout (big-endian), used by every ``.dat`` on the disc::

    0x00  "TERF"
    0x04  u32 dir_off          offset of the DIR1 block (0x40 or 0x800)
    0x08  u8[4] 02 02 01 06    version/flag bytes (identical across all archives)
    0x0c  u16 align?           0x0040 / 0x0800 (equals dir_off)
    0x0e  u16 count            number of directory entries (incl. empty slots)
    dir_off: "DIR1", u32 dir_size, u32 x, u32 y     (16-byte header)
             count * (u32 offset, u32 size)         offsets are relative to data_base
    data_base = dir_off + dir_size  (members are aligned; size==0 marks an empty slot)

Members are NOT RefPack-wrapped at the outer level: PLYRFACE members start ``MMAP`` (texture map),
FACEGEOM members start ``FAC\\0``; PLADATA/ANIMDATA members are raw/custom-packed (no 0x10FB header).

main.dol (sha256 06d96217...) keeps the ``.dat`` filename table at 0x8051ba78 (``animdata.dat`` first);
``find_lis_refs`` resolves PowerPC ``lis``+``addi``/``ori`` pairs to locate code that builds the
``TERF``/``DIR1`` magic constants and that references the filename table, i.e. the archive loader.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass

TERF = b"TERF"
DIR1 = b"DIR1"
FILENAME_TABLE_VA = 0x8051BA78


@dataclass(frozen=True)
class Member:
    index: int
    offset: int      # absolute offset in the archive
    size: int


@dataclass(frozen=True)
class TerfIndex:
    dir_off: int
    dir_size: int
    count: int
    data_base: int
    members: tuple


def parse_terf(buf) -> TerfIndex:
    """Parse and validate a TERF archive index. Raises ValueError on any out-of-range data."""
    if len(buf) < 0x40 or bytes(buf[:4]) != TERF:
        raise ValueError("not a TERF archive")
    dir_off = struct.unpack_from(">I", buf, 4)[0]
    count = struct.unpack_from(">H", buf, 0x0E)[0]
    if bytes(buf[dir_off:dir_off + 4]) != DIR1:
        raise ValueError("DIR1 block missing at %#x" % dir_off)
    dir_size = struct.unpack_from(">I", buf, dir_off + 4)[0]
    if dir_size < 16 + 8 * count or dir_off + dir_size > len(buf):
        raise ValueError("DIR1 size %#x inconsistent with count %d" % (dir_size, count))
    base = dir_off + dir_size
    members = []
    for i in range(count):
        off, size = struct.unpack_from(">II", buf, dir_off + 16 + 8 * i)
        if size and base + off + size > len(buf):
            raise ValueError("member %d [%#x+%#x] beyond archive end %#x" % (i, base + off, size, len(buf)))
        members.append(Member(i, base + off, size))
    live = sorted((m for m in members if m.size), key=lambda m: m.offset)
    for a, b in zip(live, live[1:]):
        if a.offset + a.size > b.offset:
            raise ValueError("members %d and %d overlap" % (a.index, b.index))
    return TerfIndex(dir_off, dir_size, count, base, tuple(members))


def member_bytes(buf, idx: TerfIndex, i: int) -> bytes:
    m = idx.members[i]
    return bytes(buf[m.offset:m.offset + m.size])


def dol_sections(dol: bytes):
    """[(file_off, vaddr, size, is_text)] for the DOL's populated sections (7 text + 11 data)."""
    offs = struct.unpack_from(">18I", dol, 0)
    addr = struct.unpack_from(">18I", dol, 0x48)
    size = struct.unpack_from(">18I", dol, 0x90)
    return [(o, a, s, i < 7) for i, (o, a, s) in enumerate(zip(offs, addr, size)) if s]


def va_to_off(dol: bytes, va: int):
    for o, a, s, _ in dol_sections(dol):
        if a <= va < a + s:
            return o + va - a
    return None


def find_lis_refs(dol: bytes, targets: set) -> dict:
    """Map each 32-bit constant in ``targets`` to the VAs of instructions that materialise it.

    Matches ``lis rD,hi`` followed within 8 instructions by ``addi rD2,rD,lo`` / ``ori rD2,rD,lo``
    (both with the register chain preserved). Returns {constant: [va_of_lis, ...]}.
    """
    out: dict = {t: [] for t in targets}
    for o, a, s, is_text in dol_sections(dol):
        if not is_text:
            continue
        words = struct.unpack_from(">%dI" % (s // 4), dol, o)
        for n, w in enumerate(words):
            if w >> 26 != 15 or (w >> 16) & 0x1F != 0:       # lis == addis rD,0,imm
                continue
            rd, hi = (w >> 21) & 0x1F, w & 0xFFFF
            for k in range(1, 9):
                if n + k >= len(words):
                    break
                v = words[n + k]
                op, rt, ra, imm = v >> 26, (v >> 21) & 0x1F, (v >> 16) & 0x1F, v & 0xFFFF
                if ra != rd:
                    continue
                if op == 14:                                   # addi
                    c = ((hi << 16) + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
                elif op == 24:                                 # ori (rS in 6..10, rA in 11..15)
                    ra2, rs = (v >> 16) & 0x1F, (v >> 21) & 0x1F
                    if rs != rd:
                        continue
                    c = (hi << 16) | imm
                else:
                    continue
                if c in out:
                    out[c].append(a + 4 * n)
                break
    return out


def function_start(dol: bytes, va: int, limit: int = 0x2000):
    """Walk backwards from ``va`` to the nearest ``stwu r1,-N(r1)`` prologue (0x9421xxxx)."""
    for back in range(0, limit, 4):
        o = va_to_off(dol, va - back)
        if o is None:
            return None
        if struct.unpack_from(">I", dol, o)[0] >> 16 == 0x9421:
            return va - back
    return None


def loader_xrefs(dol: bytes) -> dict:
    """Locate code that builds 'TERF'/'DIR1' constants and references the .dat filename table."""
    consts = {0x54455246: "TERF", 0x44495231: "DIR1", FILENAME_TABLE_VA: "filename_table"}
    refs = find_lis_refs(dol, set(consts))
    return {consts[c]: [{"lis_va": hex(v), "function": hex(function_start(dol, v) or 0)} for v in vs]
            for c, vs in refs.items()}


def filename_table(dol: bytes, va: int = FILENAME_TABLE_VA, max_names: int = 200) -> list:
    """The NUL-terminated lowercase archive names (``*.dat``/``*.qkl``) starting at ``va``."""
    o = va_to_off(dol, va)
    names, p = [], o
    while p is not None and len(names) < max_names:
        while dol[p] == 0:
            p += 1
        end = dol.index(b"\0", p)
        s = dol[p:end]
        if len(s) < 3 or not re.fullmatch(rb"[a-z0-9_.]+", s):
            break
        names.append(s.decode())
        p = end + 1
    return names
