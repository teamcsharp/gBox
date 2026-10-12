"""Reproducible code evidence for DMC3 SE (PS2) ``SLUS_213.61`` asset loading.

Headless Ghidra ``analyze_binary`` on this ELF failed with the worker's string
export bug (job 972a08970f264231: ``JSONDecodeError: Invalid control character``),
so this module re-derives the loader evidence with a tiny pure-Python R5900
scan (``lui``/``addiu`` pairs, ``jal`` call graph, prologue-based function
starts).  Only exact facts read from the owned executable are returned.

* ``archive_mounts``: the function that references the four archive names.  It
  calls CRI ADXF ``LoadPartitionNw(ptid, name, 0, ptinfo)`` after clearing a
  partition-info buffer of ``0x11c + 4 * files`` bytes, so each memset size
  yields the archive's file count (GData.afs: ptid 0, 3863 files).
* ``magic_classifier``: the routine that compares the model magic byte by byte
  and returns a type tag (``MOD `` -> 0x10000000, ``SHW `` -> 0x60000000 ...).
* ``function_summary``: loads (op, offset, base) and ``jal`` targets of one
  function, e.g. the model-instance init that copies MOD header bytes.
"""
from __future__ import annotations

import bisect
import struct
from pathlib import Path

SLUS_SHA256 = "a538ac05f313f193fbf86d44aa6cf97764456ce1994a896cc6ef5aff17b11a2b"
ARCHIVE_NAMES = ("GData.afs", "SData.afs", "MData1.afs", "MData2.afs")
PTINFO_HEADER = 0x11C
ZERO, A0, A1, A2, A3, V0, RA = 0, 4, 5, 6, 7, 2, 31
LOADS = {0x20: "lb", 0x24: "lbu", 0x21: "lh", 0x25: "lhu", 0x23: "lw", 0x37: "ld", 0x1E: "lq"}


def _sx(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


class Elf:
    """First PT_LOAD segment of a little-endian MIPS ELF as 32-bit words."""

    def __init__(self, data: bytes):
        if data[:4] != b"\x7fELF":
            raise ValueError("not an ELF file")
        self.data = data
        self.entry = struct.unpack_from("<I", data, 0x18)[0]
        phoff, phnum = struct.unpack_from("<I", data, 0x1C)[0], struct.unpack_from("<H", data, 0x2C)[0]
        segs = [struct.unpack_from("<8I", data, phoff + 32 * i) for i in range(phnum)]
        loads = [s for s in segs if s[0] == 1 and s[4]]
        self.off, self.va, self.size = loads[0][1], loads[0][2], loads[0][4]
        self.words = struct.unpack_from(f"<{self.size // 4}I", data, self.off)
        self.starts = [i for i, w in enumerate(self.words) if w >> 16 == 0x27BD and w & 0x8000]

    @classmethod
    def load(cls, path) -> "Elf":
        return cls(Path(path).read_bytes())

    def pc(self, i: int) -> int:
        return self.va + 4 * i

    def index(self, pc: int) -> int:
        return (pc - self.va) // 4

    def string_va(self, s: str) -> int:
        o = self.data.find(s.encode() + b"\0", self.off, self.off + self.size)
        if o < 0:
            raise KeyError(s)
        return self.va + o - self.off

    def func_start(self, pc: int) -> int:
        k = bisect.bisect_right(self.starts, self.index(pc)) - 1
        return self.pc(self.starts[k]) if k >= 0 else self.va

    def refs(self, targets: set[int], window: int = 24) -> list[tuple[int, int]]:
        """(pc, address) for every lui+addiu/ori/load pair that builds a target address."""
        out, hi = [], {}
        for i, w in enumerate(self.words):
            op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
            if op == 0x0F:
                hi[rt] = (imm << 16, i)
            elif op in (0x09, 0x0D, 0x19) or op in LOADS:
                if rs in hi and i - hi[rs][1] < window:
                    v = hi[rs][0] | imm if op == 0x0D else (hi[rs][0] + _sx(imm)) & 0xFFFFFFFF
                    if v in targets:
                        out.append((self.pc(i), v))
            elif op == 0 and w & 0x3F == 8:
                hi.clear()
        return out

    def jal_target(self, i: int) -> int | None:
        w = self.words[i]
        return (self.pc(i) & 0xF0000000) | ((w & 0x3FFFFFF) << 2) if w >> 26 == 3 else None

    def callers(self, target: int) -> list[int]:
        return [self.pc(i) for i in range(len(self.words)) if self.jal_target(i) == target]

    def function_summary(self, fn: int, limit: int = 2048) -> dict:
        loads, calls = set(), []
        for i in range(self.index(fn), min(self.index(fn) + limit, len(self.words))):
            w = self.words[i]
            op = w >> 26
            if op in LOADS:
                loads.add((LOADS[op], w & 0xFFFF, (w >> 21) & 31))
            t = self.jal_target(i)
            if t is not None:
                calls.append(t)
            if w == 0x03E00008:  # jr ra
                break
        return {"function": fn, "loads": loads, "calls": calls}


def _imm_to(w: int, reg: int) -> int | None:
    """Value of ``addiu reg, zero, imm`` or ``move reg, zero`` (addu/daddu/or)."""
    if w >> 16 == 0x2400 | reg:
        return _sx(w & 0xFFFF)
    if w >> 26 == 0 and (w >> 21) & 31 == 0 and (w >> 16) & 31 == 0 and (w >> 11) & 31 == reg \
            and w & 0x7FF in (0x21, 0x2D, 0x25):
        return 0
    return None


def archive_mounts(elf: Elf) -> dict:
    """Mount call, partition id, ptinfo size and implied file count per archive name."""
    names = {elf.string_va(n): n for n in ARCHIVE_NAMES}
    out = {}
    for pc, va in elf.refs(set(names)):
        i = elf.index(pc)
        j = next(k for k in range(i, i + 12) if elf.jal_target(k) is not None)
        ptid = size = None
        for k in range(i - 10, j + 2):
            v = _imm_to(elf.words[k], A0)
            if v is not None and k > i - 4:
                ptid = v
            v = _imm_to(elf.words[k], A2)
            if v is not None and k <= i:
                size = v
        out[names[va]] = {"name_va": va, "ref": pc, "function": elf.func_start(pc),
                          "mount_call": elf.pc(j), "mount_target": elf.jal_target(j), "ptid": ptid,
                          "ptinfo_bytes": size,
                          "files": (size - PTINFO_HEADER) // 4 if size and size > PTINFO_HEADER else None}
    return out


def magic_classifier(elf: Elf) -> dict:
    """Locate the byte-wise magic compare routine and its magic -> tag table."""
    for i, w in enumerate(elf.words):
        if w != 0x80820000:  # lb v0, 0(a0)
            continue
        chars, table = [], {}
        for k in range(i, min(i + 256, len(elf.words))):
            x = elf.words[k]
            if (x >> 26) == 0x09 and (x >> 21) & 31 == ZERO and 0x20 <= (x & 0xFFFF) < 0x7F:
                chars.append(x & 0xFFFF)
            elif x >> 16 == 0x3C00 | V0 and len(chars) >= 4:
                table[bytes(chars[-4:]).decode("ascii")] = (x & 0xFFFF) << 16
                chars = []
            if x == 0x03E00008:
                break
        if table.get("MOD ") is not None:
            return {"function": elf.pc(i), "tags": table, "callers": elf.callers(elf.pc(i))}
    raise LookupError("no MOD magic classifier found")
