"""Killer Instinct Gold (N64) — analysis-stage probes.

Follows the inventory leads (``gbox.kigold_inventory``) and turns them into
reproducible, testable format facts for this exact build (No-Intro
"Killer Instinct Gold (USA) (Rev 2)", rom sha256
f80cae340efadf5725cd0f75441addb9186be9860267595be2b4a2d317b05f8a):

* A minimal R4300i (MIPS III, big-endian) disassembler and an entry-point
  control-flow trace from 0x80000400 (ROM offset 0x400 — Rare's boot stub,
  verified by decoding: ``bne at,zero,-3; addiu t0,t0,0x10; b +19``).
* A detector for the frame-table format discovered in this build: runs of
  u16 pairs where one half is a constant "tag" whose low byte is 0xFE
  (0x36FE / 0x54FE / 0x73FE ...) and the other half is a ladder stepping
  +4 per entry (== 0x40000 in the u32 reading). The ladder half, read as
  ``ladder << 16``, lands inside the dense asset blob (0x1000-0xBFB000) and
  points at high-entropy (compressed) frame blocks.
* Validation of the 0x7160 bit-shuffle LUT and the 0x7180 block-size ladder
  used by the sprite decompressor.
* A negative-result referent scan: this build holds NO absolute u32 pointer
  to the frame tables (0x80992D54 / 0x809AA85C anywhere in 0x1000-0xBFB000),
  so the loader must compute those addresses (base register + offset) —
  the Ghidra project (seeded from this ROM, image base 0x80000000, entry
  0x80000400) is the instrument for resolving that.

Usage:
    python -m gbox.kigold_analysis rom.z64 [--out report.json]
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from collections import Counter

# ROM image offset <-> virtual address (cached mirror; entry 0x80000400).
ROM_BASE = 0x80000000
DENSE = (0x1000, 0xBFB000)
CODE_WINDOW = (0x1000, 0x90000)
ENTRY_VADDR = 0x80000400

REGS = [
    "zero", "at", "v0", "v1", "a0", "a1", "a2", "a3",
    "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
    "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
    "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra",
]

# Known tables in this build (byte-exact observations).
FRAME_TABLE_A = 0x992D58   # tag 0x36FE, 7 entries, ladder 0x0036..0x004E
FRAME_TABLE_B = 0x9AA85C   # tag 0x54FE, 15 entries, ladder 0x0054..0x008C
SIZE_LADDER_LUT = 0x7180
SHUFFLE_LUT = 0x7160


def rname(n: int) -> str:
    return REGS[n & 0x1F]


def sign16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def dis(word: int, addr: int = 0) -> tuple[str, str, str]:
    """Decode one big-endian R4300i word.

    Returns (kind, mnemonic, operands). kind is 'j' (jump), 'b' (branch),
    'c' (call), 'r' (return), 'x' (flow stop), or ' ' (fallthrough).
    """
    op = word >> 26
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    rd = (word >> 11) & 0x1F
    sa = (word >> 6) & 0x1F
    fn = word & 0x3F
    imm = sign16(word & 0xFFFF)
    tgt = (addr & 0xF0000000) | ((word & 0x03FFFFFF) << 2)

    if op == 0:
        special = {
            0x00: lambda: ("sll", f"{rname(rd)}, {rname(rt)}, {sa}"),
            0x02: lambda: ("srl", f"{rname(rd)}, {rname(rt)}, {sa}"),
            0x03: lambda: ("sra", f"{rname(rd)}, {rname(rt)}, {sa}"),
            0x04: lambda: ("sllv", f"{rname(rd)}, {rname(rt)}, {rname(rs)}"),
            0x06: lambda: ("srlv", f"{rname(rd)}, {rname(rt)}, {rname(rs)}"),
            0x07: lambda: ("srav", f"{rname(rd)}, {rname(rt)}, {rname(rs)}"),
            0x08: lambda: ("jr", f"{rname(rs)}"),
            0x09: lambda: ("jalr", f"{rname(rs)}, {rname(rd)}"),
            0x0C: lambda: ("syscall", ""),
            0x0D: lambda: ("break", ""),
            0x0F: lambda: ("sync", ""),
            0x10: lambda: ("mfhi", f"{rname(rd)}"),
            0x11: lambda: ("mthi", f"{rname(rs)}"),
            0x12: lambda: ("mflo", f"{rname(rd)}"),
            0x13: lambda: ("mtlo", f"{rname(rs)}"),
            0x18: lambda: ("mult", f"{rname(rs)}, {rname(rt)}"),
            0x19: lambda: ("multu", f"{rname(rs)}, {rname(rt)}"),
            0x1A: lambda: ("div", f"{rname(rs)}, {rname(rt)}"),
            0x1B: lambda: ("divu", f"{rname(rs)}, {rname(rt)}"),
            0x20: lambda: ("add", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
            0x21: lambda: ("addu", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
            0x22: lambda: ("sub", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
            0x23: lambda: ("subu", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
            0x24: lambda: ("and", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
            0x25: lambda: ("or", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
            0x26: lambda: ("xor", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
            0x27: lambda: ("nor", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
            0x2A: lambda: ("slt", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
            0x2B: lambda: ("sltu", f"{rname(rd)}, {rname(rs)}, {rname(rt)}"),
        }
        if fn in special:
            m, o = special[fn]()
            if fn in (0x08,):
                return ("r", m, o)
            if fn == 0x09:
                return ("c", m, o)
            if fn in (0x0C, 0x0D):
                return ("x", m, o)
            return (" ", m, o)
        return (" ", ".word", f"0x{word:08x}")

    if op == 1:  # REGIMM
        regimm = {
            0x00: "bltz", 0x01: "bgez", 0x02: "bltzl", 0x03: "bgezl",
            0x08: "tgei", 0x09: "tgeiu", 0x0A: "tlti", 0x0B: "tltiu",
            0x0C: "teqi", 0x10: "bltzal", 0x11: "bgezal",
            0x12: "bltzall", 0x13: "bgezall",
        }
        m = regimm.get(rt, "re.gimm")
        if rt in (0x10, 0x11, 0x12, 0x13):
            return ("c", m, f"{rname(rs)}, {imm}")
        if rt in (0x08, 0x09, 0x0A, 0x0B, 0x0C):
            return (" ", m, f"{rname(rs)}, {imm}")
        t = addr + 4 + (imm << 2)
        return ("b", m, f"{rname(rs)}, 0x{t:08x}")

    if op in (0x02,):  # j
        return ("j", "j", f"0x{tgt:08x}")
    if op == 0x03:  # jal
        return ("c", "jal", f"0x{tgt:08x}")
    if op in (0x04, 0x05, 0x06, 0x07, 0x14, 0x15, 0x16, 0x17):
        t = addr + 4 + (imm << 2)
        names = {0x04: "beq", 0x05: "bne", 0x06: "blez", 0x07: "bgtz",
                 0x14: "beql", 0x15: "bnel", 0x16: "blezl", 0x17: "bgtzl"}
        return ("b", names[op], f"{rname(rs)}, {rname(rt)}, 0x{t:08x}")
    if op == 0x08:
        return (" ", "addi", f"{rname(rt)}, {rname(rs)}, {imm}")
    if op == 0x09:
        return (" ", "addiu", f"{rname(rt)}, {rname(rs)}, {imm}")
    if op == 0x0A:
        return (" ", "slti", f"{rname(rt)}, {rname(rs)}, {imm}")
    if op == 0x0B:
        return (" ", "sltiu", f"{rname(rt)}, {rname(rs)}, {imm}")
    if op == 0x0C:
        return (" ", "andi", f"{rname(rt)}, {rname(rs)}, 0x{word & 0xFFFF:04x}")
    if op == 0x0D:
        return (" ", "ori", f"{rname(rt)}, {rname(rs)}, 0x{word & 0xFFFF:04x}")
    if op == 0x0E:
        return (" ", "xori", f"{rname(rt)}, {rname(rs)}, 0x{word & 0xFFFF:04x}")
    if op == 0x0F:
        return (" ", "lui", f"{rname(rt)}, 0x{word & 0xFFFF:04x}")
    if op == 0x10:  # COP0
        if rs in (0x00, 0x04):
            return (" ", "mtc0" if rs == 0x04 else "mfc0", f"{rname(rt)}, ${rd}")
        if word == 0x42000018:
            return ("x", "eret", "")
        return (" ", "cop0", f"0x{word & 0x1FFFFFF:07x}")
    if op == 0x11:  # COP1
        fmt = rs
        if fmt == 0x08:
            nd, tf = rd & 1, rt & 1
            t = addr + 4 + (imm << 2)
            m = ["bc1f", "bc1t"][tf] + ("l" if nd else "")
            return ("b", m, f"0x{t:08x}")
        if fmt in (0x00, 0x02, 0x04, 0x06):
            return (" ", ["mfc1", "cfc1", "mtc1", "ctc1"][fmt // 2],
                    f"{rname(rt)}, $f{rd}")
        return (" ", "cop1", f"0x{word & 0x1FFFFFF:07x}")
    if op in (0x12, 0x13):
        return (" ", "cop2" if op == 0x12 else "cop3", "")
    loads = {0x20: ("lb", 1), 0x21: ("lh", 2), 0x22: ("lwl", 4),
             0x23: ("lw", 4), 0x24: ("lbu", 1), 0x25: ("lhu", 2),
             0x26: ("lwr", 4)}
    stores = {0x28: "sb", 0x29: "sh", 0x2A: "swl", 0x2B: "sw", 0x2E: "swr"}
    if op in loads:
        m, _ = loads[op]
        return (" ", m, f"{rname(rt)}, {imm}({rname(rs)})")
    if op in stores:
        return (" ", stores[op], f"{rname(rt)}, {imm}({rname(rs)})")
    if op == 0x31:
        return (" ", "lwc1", f"$f{rt}, {imm}({rname(rs)})")
    if op == 0x39:
        return (" ", "swc1", f"$f{rt}, {imm}({rname(rs)})")
    if op == 0x2F:
        return (" ", "cache", f"0x{rt:x}, {imm}({rname(rs)})")
    return (" ", ".word", f"0x{word:08x}")


def u32(rom: bytes, off: int) -> int:
    return struct.unpack(">I", rom[off:off + 4])[0]


def u16(rom: bytes, off: int) -> int:
    return struct.unpack(">H", rom[off:off + 2])[0]


def vaddr_to_off(vaddr: int) -> int:
    return vaddr - ROM_BASE


def entry_trace(rom: bytes, start: int = ENTRY_VADDR, max_insns: int = 2000) -> dict:
    """Linear-flow trace from the entry point; follows branches/jumps,
    records call targets without descending (calls need $sp/$ra semantics)."""
    insns: list[tuple[int, str, str, str]] = []
    calls: list[int] = []
    seen: set[int] = set()
    queue: list[int] = [start]
    while queue and len(insns) < max_insns:
        v = queue.pop(0)
        while v not in seen and len(insns) < max_insns:
            seen.add(v)
            off = vaddr_to_off(v)
            if not (0 <= off < len(rom) - 3):
                break
            kind, m, o = dis(u32(rom, off), v)
            insns.append((v, kind, m, o))
            if kind == "c":
                t = int(o.rsplit(" ", 1)[-1], 16)
                if t != 0:
                    calls.append(t)
                break
            if kind in ("x", "r"):
                break
            if kind in ("b", "j"):
                t = int(o.rsplit(" ", 1)[-1], 16)
                queue.append(t)
                if kind == "b":
                    queue.append(v + 4)  # follow the fallthrough path too
                break
            v += 4
    return {"insns": insns, "calls": sorted(set(calls)), "count": len(insns)}


def ladder_tables(rom: bytes, lo: int = DENSE[0], hi: int = DENSE[1],
                  min_run: int = 4, stride: int = 4) -> list[dict]:
    """Detect {tag, ladder} u16-pair runs: one half constant (low byte 0xFE),
    the other an arithmetic ladder stepping +stride per entry."""
    runs: list[dict] = []
    i = lo
    while i + 3 < hi:
        a, b = u16(rom, i), u16(rom, i + 2)
        tag, start, ladder_first = None, None, True
        if (a & 0xFF) == 0xFE:
            tag, start, ladder_first = a, b, False
        elif (b & 0xFF) == 0xFE:
            tag, start, ladder_first = b, a, True
        if tag is None:
            i += 2
            continue
        n = 1
        j = i + 4
        while j + 3 < hi:
            a2, b2 = u16(rom, j), u16(rom, j + 2)
            if ladder_first and b2 == tag and a2 == start + n * stride:
                n += 1
                j += 4
            elif (not ladder_first) and a2 == tag and b2 == start + n * stride:
                n += 1
                j += 4
            else:
                break
        if n >= min_run:
            runs.append({"offset": i, "tag": tag, "ladder_first": ladder_first,
                         "ladder_start": start, "count": n, "stride": stride})
            i = j
        else:
            i += 2
    return runs


def block_targets(entries: dict) -> list[int]:
    """Interpret a ladder run as u32 entries whose ladder half is the
    high 16 bits of a ROM offset (block = ladder << 16)."""
    start, count, stride = entries["ladder_start"], entries["count"], entries["stride"]
    return [((start + k * stride) << 16) for k in range(count)]


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    c = Counter(data)
    n = len(data)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def entry_offsets(entries: dict) -> list[dict]:
    """Both readings of a ladder run: the u32 as-is (ladder<<16 | tag) and
    the block base (ladder<<16). The report records which lands in ROM."""
    out = []
    for k in range(entries["count"]):
        ladder = entries["ladder_start"] + k * entries["stride"]
        out.append({"ladder": ladder, "u32": (ladder << 16) | entries["tag"],
                    "block": ladder << 16})
    return out


def _block_summary(rom: bytes, targets: list[dict]) -> list[dict]:
    out = []
    for t in targets:
        u32v, block = t["u32"], t["block"]
        ok_u, ok_b = 0 < u32v + 4096 <= len(rom), 0 < block + 4096 <= len(rom)
        out.append({
            "ladder": hex(t["ladder"]),
            "u32_target": hex(u32v),
            "u32_in_rom": ok_u,
            "u32_entropy": round(entropy(rom[u32v:u32v + 4096]), 3) if ok_u else None,
            "block_target": hex(block),
            "block_in_dense": DENSE[0] < block < DENSE[1],
            "block_entropy": round(entropy(rom[block:block + 4096]), 3) if ok_b else None,
        })
    return out


def probe_frame_tables(rom: bytes) -> dict:
    runs = ladder_tables(rom)
    out = []
    for r in runs:
        blocks = _block_summary(rom, entry_offsets(r))
        out.append({
            "offset": hex(r["offset"]), "tag": hex(r["tag"]),
            "ladder_first": r["ladder_first"],
            "ladder_start": hex(r["ladder_start"]),
            "count": r["count"], "stride": r["stride"],
            "entries": blocks,
            "all_u32_in_rom": all(b["u32_in_rom"] for b in blocks),
            "all_blocks_in_dense": all(b["block_in_dense"] for b in blocks),
        })
    return {"runs": out}


def probe_luts(rom: bytes) -> dict:
    shuffle = list(rom[SHUFFLE_LUT:SHUFFLE_LUT + 32])
    ladder = [u16(rom, SIZE_LADDER_LUT + 2 * i) for i in range(24)]
    ladder_trim = ladder[:ladder.index(0)] if 0 in ladder else ladder
    return {
        "shuffle_lut": {
            "offset": hex(SHUFFLE_LUT),
            "bytes": [hex(b) for b in shuffle[:20]],
        },
        "size_ladder": {
            "offset": hex(SIZE_LADDER_LUT),
            "values": ladder_trim,
            "monotonic_increasing": all(a < b for a, b in
                                        zip(ladder_trim, ladder_trim[1:])),
        },
    }


def probe_referents(rom: bytes) -> dict:
    """Scan for absolute u32 references to the frame tables anywhere in the
    ROM image (documented negative result for this build)."""
    table_vaddrs = [0x80992D54, 0x809AA85C, 0x80992D50, 0x80992D58]
    hits: dict[int, list[int]] = {t: [] for t in table_vaddrs}
    for i in range(0x40, len(rom) - 3, 4):
        w = u32(rom, i)
        if w in hits:
            hits[w].append(i)
    return {
        "tables": {hex(t): {"absolute_u32_hits": [hex(h) for h in hits[t]]}
                   for t in table_vaddrs},
        "scan_range": "0x40..EOF, 4-aligned",
    }


def analyze(rom: bytes) -> dict:
    trace = entry_trace(rom)
    return {
        "entry_trace": {
            "start": hex(ENTRY_VADDR),
            "count": trace["count"],
            "first_insns": [(hex(v), k, m + " " + o)
                            for v, k, m, o in trace["insns"][:16]],
            "call_targets": [hex(t) for t in trace["calls"][:32]],
        },
        "frame_tables": probe_frame_tables(rom),
        "luts": probe_luts(rom),
        "referents": probe_referents(rom),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="kigold_analysis")
    ap.add_argument("rom")
    ap.add_argument("--out")
    args = ap.parse_args(argv[1:])
    with open(args.rom, "rb") as fh:
        rom = fh.read()
    report = analyze(rom)
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
