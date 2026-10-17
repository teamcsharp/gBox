"""Resident Evil: The Mercenaries 3D (3DS) exe-analysis helpers: xref scanner + uPl roster table.

Analysis-stage tools for the owned EUR build's decompressed .code (ARM11, base 0x100000,
sha256 85a34c86...821be). Pure python (stdlib only) so the scan is reproducible anywhere;
Scanned words are candidate references, not proof of instruction boundaries or
ARM/Thumb execution mode. Follow candidates in a mode-aware disassembler before
using them as loader evidence.

Pinned findings this module reproduces (pl0000 analysis, ticket #1320 / PR #46):

  * A bounded scan beginning at 0x76AC10 finds 18 aligned uPl name strings,
    representing 16 unique names; Chris and Jill occur again in another registration
    cluster. Intervening bytes include executable code. They must not be treated as
    uniform 16-byte model descriptors or a complete roster binding table.
  * 'archive\\%s' at 0x4D6CE4 is referenced by ARM-mode code at 0x4D6C68
    (``add r2, pc, #0x74``) inside the archive-path cluster 0x4D6A40-0x4D6D90, which
    calls the formatter at 0x100E7C and the global-object accessor at 0x804818.
  * The ro table at 0x812720 = {thunk_ptr, 0} pairs followed by archive path strings
    ("archive\\sound\\em", ...); its 0x4D6CF4 entry points back into the cluster.
  * The "region strings" range 0x80FFC-0x8127C from the inventory checkpoint is NOT
    strings: it is a u16 lookup table (0x000901xx / 0x000900xx pattern). The EUR label
    fix remains a catalog/DB item for the operator.

Usage: ``python -m gbox.merc3d_exe code.bin --targets 0x4d6ce4 0x76ac10 0x478e44``
prints a JSON xref report (ref kinds: u32 pointer, Thumb LDR-literal/ADR/ADD-pc,
ARM LDR-literal/ADR, BL callers).
"""
from __future__ import annotations

import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

BASE = 0x100000
TEXT_END = 0x8110E4  # text 0x100000..0x8110E4, ro 0x812000, data 0x8AA000


class ExeError(ValueError):
    pass


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def match_range(ranges, value):
    """Ranges = [(lo, hi), ...]; exact membership."""
    for lo, hi in ranges:
        if lo <= value < hi:
            return True
    return False


# ---------------------------------------------------------------- data refs

def find_u32_refs(data: bytes, ranges, base: int = BASE) -> list[dict]:
    """File-wide LE u32 pointer scan (4-aligned): offsets whose value falls in `ranges`."""
    out = []
    for off in range(0, len(data) - 3, 4):
        v = _u32(data, off)
        if match_range(ranges, v):
            out.append({"site": base + off, "target": v, "kind": "u32"})
    return out


# ---------------------------------------------------------------- Thumb refs

def _thumb_pc(site: int) -> int:
    return (site + 4) & ~3


def thumb_ldr_literal_refs(data: bytes, ranges, base: int = BASE) -> list[dict]:
    """Thumb LDR Rt, [pc, #imm8]: hw & 0xF800 == 0x4800, target = (pc&~3) + imm8*4."""
    out = []
    for off in range(0, len(data) - 1, 2):
        hw = _u16(data, off)
        if (hw & 0xF800) == 0x4800:
            t = _thumb_pc(base + off) + (hw & 0xFF) * 4
            if match_range(ranges, t):
                out.append({"site": base + off, "target": t, "kind": "thumb_ldr_lit"})
    return out


def thumb_adr_refs(data: bytes, ranges, base: int = BASE) -> list[dict]:
    """Thumb ADR Rt, #imm8: hw & 0xF800 == 0xA000, target = (pc&~3) + imm8*4."""
    out = []
    for off in range(0, len(data) - 1, 2):
        hw = _u16(data, off)
        if (hw & 0xF800) == 0xA000:
            t = _thumb_pc(base + off) + (hw & 0xFF) * 4
            if match_range(ranges, t):
                out.append({"site": base + off, "target": t, "kind": "thumb_adr"})
    return out


def thumb_add_pc_refs(data: bytes, ranges, base: int = BASE) -> list[dict]:
    """Thumb ADD Rd, pc, #imm8 — the 0xA000-0xA7FF form that assemblers alias as ADR.
    (Kept under its encoding name: 0xA8xx is ADD SP, not PC.)"""
    out = []
    for off in range(0, len(data) - 1, 2):
        hw = _u16(data, off)
        if (hw & 0xF800) == 0xA000:
            t = _thumb_pc(base + off) + (hw & 0xFF) * 4
            if match_range(ranges, t):
                out.append({"site": base + off, "target": t, "kind": "thumb_add_pc"})
    return out


# ---------------------------------------------------------------- ARM refs

def arm_ldr_literal_refs(data: bytes, ranges, base: int = BASE) -> list[dict]:
    """ARM LDR Rt, [pc, #+-imm12]: (w & 0x0F7F0000) == 0x051F0000, target = (pc&~3) +- imm12."""
    out = []
    for off in range(0, len(data) - 3, 4):
        w = _u32(data, off)
        if w >> 28 != 15 and (w & 0x0F7F0000) == 0x051F0000:
            imm = w & 0xFFF
            t = ((base + off + 8) & ~3) + (imm if (w >> 23) & 1 else -imm)
            if match_range(ranges, t):
                out.append({"site": base + off, "target": t, "kind": "arm_ldr_lit"})
    return out


def arm_adr_refs(data: bytes, ranges, base: int = BASE) -> list[dict]:
    """A32 ADD/SUB Rd, pc, immediate: imm8 rotated right by twice rotate_imm."""
    out = []
    for off in range(0, len(data) - 3, 4):
        w = _u32(data, off)
        op = w & 0x0FFF0000
        if w >> 28 != 15 and op in (0x028F0000, 0x024F0000):
            value, rotate = w & 0xFF, ((w >> 8) & 15) * 2
            immediate = ((value >> rotate) | (value << (32 - rotate))) & 0xFFFFFFFF
            t = (base + off + 8 + (immediate if op == 0x028F0000 else -immediate)) & 0xFFFFFFFF
            if match_range(ranges, t):
                out.append({"site": base + off, "target": t, "kind": "arm_adr"})
    return out


def arm_b_bl(data: bytes, base: int = BASE) -> list[tuple[int, int]]:
    """ARM B/BL immediate targets: (site, target), target = pc + imm24<<2."""
    out = []
    for off in range(0, len(data) - 3, 4):
        w = _u32(data, off)
        if w >> 28 != 15 and (w & 0x0F000000) in (0x0A000000, 0x0B000000):
            imm = (w & 0xFFFFFF) << 2
            if imm & (1 << 25):
                imm -= 1 << 26
            out.append((base + off, base + off + 8 + imm))
    return out


def thumb_bl(data: bytes, base: int = BASE) -> list[tuple[int, int]]:
    """ARM11/ARMv6 Thumb BL immediate targets; not Thumb-2 encodings."""
    out = []
    for off in range(0, len(data) - 3, 2):
        hw1, hw2 = _u16(data, off), _u16(data, off + 2)
        if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xF800) == 0xF800:
            high = hw1 & 0x7FF
            if high & 0x400:
                high -= 0x800
            imm = (high << 12) + ((hw2 & 0x7FF) << 1)
            out.append((base + off, (base + off + 4 + imm) & 0xFFFFFFFF))
    return out


def callers_of(data: bytes, ranges, base: int = BASE) -> list[dict]:
    """Sites (Thumb or ARM) that BL into `ranges`."""
    out = [{"site": s, "target": t, "kind": "thumb_bl"} for s, t in thumb_bl(data, base)
           if match_range(ranges, t)]
    out += [{"site": s, "target": t, "kind": "arm_bl"} for s, t in arm_b_bl(data, base)
            if (_u32(data, s - base) & 0x01000000) and match_range(ranges, t)]
    return out


# ---------------------------------------------------------------- tables

def strings_in(data: bytes, lo: int, hi: int, base: int = BASE, min_len: int = 3) -> list[tuple[int, str]]:
    """NUL-separated printable ASCII strings in [lo, hi)."""
    out = []
    cur = bytearray()
    start = None
    for i in range(max(0, lo - base), min(len(data), hi - base)):
        b = data[i]
        if 0x20 <= b < 0x7F:
            if start is None:
                start = i
            cur.append(b)
        else:
            if start is not None and len(cur) >= min_len:
                out.append((base + start, cur.decode()))
            cur = bytearray()
            start = None
    return out


def upl_table(data: bytes, addr: int = 0x76AC10, base: int = BASE,
              max_names: int = 64) -> list[dict]:
    """Bounded candidate name scan; descriptor layout and loader bindings are unproven.

    Preserve repeated names rather than interpreting them as extra costumes. The
    following words are raw evidence only and may include code or unrelated data.
    """
    import re
    if type(max_names) is not int or not 0 <= max_names <= 64:
        raise ExeError("max_names must be between zero and 64")
    pos = addr - base
    if not 0 <= pos < len(data):
        raise ExeError(f"table addr {addr:#x} outside image")
    limit = min(len(data), pos + 0x2000)
    out = []
    for off in range(pos, limit - 3, 4):
        if len(out) >= max_names:
            break
        end = data.find(b"\0", off, min(limit, off + 64))
        if end < 0 or not re.fullmatch(rb"uPl< [A-Za-z0-9]+ >", data[off:end]):
            continue
        after = (end + 4) & ~3
        out.append({"name":data[off:end].decode('ascii'), "va":base+off,
                    "following_words":[_u32(data, p) for p in range(after,min(after+16,limit-3),4)],
                    "layout_verified":False})
    return out


# ---------------------------------------------------------------- driver

@dataclass
class CodeImage:
    data: bytes
    base: int = BASE

    @classmethod
    def load(cls, path: str | Path) -> "CodeImage":
        return cls(Path(path).read_bytes())

    def refs_to(self, ranges: list[tuple[int, int]]) -> list[dict]:
        fns = (find_u32_refs, thumb_ldr_literal_refs, thumb_adr_refs,
               arm_ldr_literal_refs, arm_adr_refs)
        out = []
        for fn in fns:
            out.extend(fn(self.data, ranges, self.base))
        return out

    def report(self, targets: dict[str, list[tuple[int, int]]]) -> dict:
        rep = {}
        for name, ranges in targets.items():
            rep[name] = self.refs_to(ranges)
            rep[name].extend(callers_of(self.data, ranges, self.base))
        return rep


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("code_bin")
    ap.add_argument("--targets", nargs="+",
                    help="addresses or lo:hi ranges, e.g. 0x4d6ce4 0x76ac10:0x76b100")
    ap.add_argument("--upl", type=lambda s: int(s, 0), default=None,
                    help="parse the uPl roster table at this address")
    a = ap.parse_args(argv)
    img = CodeImage.load(a.code_bin)
    out: dict = {}
    if a.targets:
        targets = {}
        for spec in a.targets:
            if ":" in spec:
                lo, hi = (int(x, 0) for x in spec.split(":"))
                targets[spec] = [(lo, hi)]
            else:
                v = int(spec, 0)
                targets[spec] = [(v, v + 16)]
        out["xrefs"] = img.report(targets)
    if a.upl is not None:
        out["upl"] = upl_table(img.data, a.upl, img.base)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
