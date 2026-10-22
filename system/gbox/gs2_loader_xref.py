"""Ghidra-free string->code xref finder for PS2 (MIPS R5900 LE) ELF executables.

Built for RE Survivor 2 CV (SLES_506.50) where the Ghidra bridge was down: finds
ASCII strings in PT_LOAD segments, then scans executable code for the standard
``lui rt,%hi`` + ``addiu/ori/load/store rt,%lo(rt)`` address materialisation to
list which functions reference a string (candidate AFS/MDL/TIM2 loaders).
Results are hypotheses until confirmed by reading the code.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field


@dataclass
class Segment:
    offset: int
    vaddr: int
    filesz: int
    memsz: int
    flags: int


@dataclass
class Elf:
    data: bytes
    entry: int
    segments: list = field(default_factory=list)

    def vaddr_to_off(self, va):
        for s in self.segments:
            if s.vaddr <= va < s.vaddr + s.filesz:
                return s.offset + va - s.vaddr
        return None

    def off_to_vaddr(self, off):
        for s in self.segments:
            if s.offset <= off < s.offset + s.filesz:
                return s.vaddr + off - s.offset
        return None


def parse_elf(data: bytes) -> Elf:
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 1:
        raise ValueError("not an ELF32 little-endian file")
    machine = struct.unpack_from("<H", data, 0x12)[0]
    if machine != 8:
        raise ValueError(f"not MIPS (e_machine={machine})")
    entry, phoff = struct.unpack_from("<II", data, 0x18)
    phentsize, phnum = struct.unpack_from("<HH", data, 0x2A)
    elf = Elf(data, entry)
    for i in range(phnum):
        t, off, va, _pa, fsz, msz, fl, _al = struct.unpack_from("<8I", data, phoff + i * phentsize)
        if t == 1 and fsz:
            elf.segments.append(Segment(off, va, fsz, msz, fl))
    return elf


def find_string(elf: Elf, needle: bytes):
    """Yield (file_offset, vaddr) of each NUL-delimited occurrence of needle."""
    pos = 0
    while True:
        i = elf.data.find(needle + b"\x00", pos)
        if i < 0:
            return
        pos = i + 1
        if i and elf.data[i - 1] >= 0x20:
            continue  # suffix of a longer string
        va = elf.off_to_vaddr(i)
        if va is not None:
            yield i, va


def _sx(v):
    return v - 0x10000 if v & 0x8000 else v


LOAD_STORE = {0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B, 0x37, 0x3F, 0x1E, 0x1F, 0x27}


def find_code_refs(elf: Elf, target: int, window: int = 8):
    """Return vaddrs of instructions that complete an address == target via lui+lo."""
    refs = []
    for s in elf.segments:
        if not s.flags & 1:
            continue
        words = struct.unpack_from(f"<{s.filesz // 4}I", elf.data, s.offset)
        hi = {}  # reg -> (hi value, index)
        for i, w in enumerate(words):
            op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
            if op == 0x0F:  # lui
                hi[rt] = (imm << 16, i)
                continue
            if rs in hi and i - hi[rs][1] <= window:
                base = hi[rs][0]
                if op == 0x09 and (base + _sx(imm)) & 0xFFFFFFFF == target:  # addiu
                    refs.append(s.vaddr + i * 4)
                elif op == 0x0D and (base | imm) == target:  # ori
                    refs.append(s.vaddr + i * 4)
                elif op in LOAD_STORE and (base + _sx(imm)) & 0xFFFFFFFF == target:
                    refs.append(s.vaddr + i * 4)
            # a write to rt (addiu/ori/lw) kills a tracked lui in that reg
            if op in (0x09, 0x0D, 0x23, 0x0F) and rt in hi and op != 0x0F and rt != rs:
                hi.pop(rt, None)
    return refs


def function_start(elf: Elf, va: int, max_back: int = 0x1000):
    """Heuristic: walk back to `addiu sp,sp,-N` prologue (nearest preceding)."""
    off = elf.vaddr_to_off(va)
    if off is None:
        return None
    for back in range(0, max_back, 4):
        o = off - back
        if o < 0:
            break
        w = struct.unpack_from("<I", elf.data, o)[0]
        # addiu sp,sp,-N  (0x27BDxxxx with negative imm); R5900 also uses daddiu (0x67BD)
        if (w >> 16) in (0x27BD, 0x67BD) and w & 0x8000:
            return elf.off_to_vaddr(o)
    return None


def report(elf: Elf, names):
    out = {}
    for n in names:
        entries = []
        for off, va in find_string(elf, n.encode()):
            refs = find_code_refs(elf, va)
            entries.append({
                "file_offset": off, "vaddr": va,
                "refs": [{"pc": r, "func_start": function_start(elf, r)} for r in refs],
            })
        out[n] = entries
    return out


def read_symbols(elf: Elf):
    """Parse .symtab/.strtab (PS2 retail ELF here is unstripped). Returns list of
    dicts: name, value, size, type (1=OBJECT, 2=FUNC)."""
    d = elf.data
    shoff, = struct.unpack_from("<I", d, 0x20)
    shentsize, shnum, _ = struct.unpack_from("<HHH", d, 0x2E)
    out = []
    for i in range(shnum):
        _n, typ, _f, _a, off, size, link, _i, _al, ent = struct.unpack_from("<10I", d, shoff + i * shentsize)
        if typ != 2 or ent != 16:
            continue
        _n2, _t2, _f2, _a2, soff, ssize, *_ = struct.unpack_from("<10I", d, shoff + link * shentsize)
        for j in range(size // 16):
            nm, val, sz, info, _o, _sh = struct.unpack_from("<IIIBBH", d, off + j * 16)
            end = d.index(b"\0", soff + nm)
            out.append({"name": d[soff + nm:end].decode("latin1"), "value": val, "size": sz, "type": info & 15})
    return out


def callees(elf: Elf, start: int, size: int):
    """vaddrs targeted by `jal` inside [start, start+size)."""
    off = elf.vaddr_to_off(start)
    res = []
    for i in range(size // 4):
        w, = struct.unpack_from("<I", elf.data, off + i * 4)
        if w >> 26 == 3:
            res.append(((start + i * 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2))
    return res


def call_tree(elf: Elf, syms, names):
    byaddr = {s["value"]: s for s in syms if s["type"] == 2}
    byname = {s["name"]: s for s in syms if s["type"] == 2}
    out = {}
    for n in names:
        f = byname.get(n)
        if not f:
            out[n] = None
            continue
        out[n] = {"addr": f["value"], "size": f["size"],
                  "calls": [byaddr[c]["name"] if c in byaddr else hex(c)
                            for c in callees(elf, f["value"], f["size"])]}
    return out


if __name__ == "__main__":
    import json
    import sys
    e = parse_elf(open(sys.argv[1], "rb").read())
    print(json.dumps(report(e, sys.argv[2:] or ["SYSTEM.AFS", "MRY.AFS", "TSUIKA.AFS"]), indent=1))
