"""Offline DOA2 (Dreamcast) ranking-backdrop RTT trace helpers for request #1216.

Pure functions over extracted guest RAM/VRAM images produced by the texture-audit extractor.
No emulator calls; no ROM, executable or save-state bytes are bundled. Guest RAM is the
16 MiB image based at 0x8c000000.

Observed in both the original (4f57b817...) and clean slot35 (33cb8b26...) states:
* The game keeps 0x3c-byte texture-surface records. Allocator nodes point at a record's
  VRAM field P; the record starts at P-0x20:
  id, ?, ?, flags, width, height, size, kind, vram, 0, 0, 0, ?, ?, tcw.
  Record 4 (P=0x8c20cd28, id 0x28) is the ranking backdrop: 512x256, 0x40000 B,
  VRAM 0x473800, TCW 0x0c08e700 ((tcw & 0x1fffff) << 3 == vram).
* 0x8c2c28xx is the VRAM allocator list: {next, prev, vram, size, record P, flags}, 0x18 B.
* The clean surface is a one-shot in-engine render (player fighter in a win pose on a
  stage, no HUD). With RTT copying off it never reaches guest VRAM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import asdict, dataclass

RAM_BASE = 0x8C000000
RECORD_STRIDE = 0x3C
BACKDROP_P = 0x8C20CD28


@dataclass(frozen=True)
class Surface:
    p: int
    ident: int
    flags: int
    width: int
    height: int
    size: int
    kind: int
    vram: int
    tcw: int

    @property
    def tcw_vram(self) -> int:
        return (self.tcw & 0x1FFFFF) << 3


def u32(ram: bytes, addr: int) -> int:
    return struct.unpack_from("<I", ram, addr - RAM_BASE)[0]


def surface_at(ram: bytes, p: int) -> Surface:
    s = p - 0x20
    w = [u32(ram, s + 4 * i) for i in range(15)]
    return Surface(p, w[0], w[3], w[4], w[5], w[6], w[7], w[8], w[14])


def allocator_nodes(ram: bytes, start: int, limit: int = 256) -> list[dict]:
    """Walk the VRAM allocator list from node `start` along `next` until it repeats."""
    out, seen, n = [], set(), start
    while n and n not in seen and len(out) < limit and RAM_BASE <= n < RAM_BASE + len(ram) - 0x18:
        seen.add(n)
        nxt, prev, vram, size, rec, flags = (u32(ram, n + 4 * i) for i in range(6))
        out.append({"node": n, "next": nxt, "prev": prev, "vram": vram, "size": size, "record": rec, "flags": flags})
        n = nxt
    return out


def find_value(ram: bytes, value: int) -> list[int]:
    pat = struct.pack("<I", value)
    hits, i = [], ram.find(pat)
    while i >= 0:
        if i % 4 == 0:
            hits.append(RAM_BASE + i)
        i = ram.find(pat, i + 1)
    return hits


def sh4_pool_refs(code: bytes, base: int, wanted: set[int]) -> list[tuple[int, int, int]]:
    """mov.l @(disp,PC),Rn instructions whose literal is in `wanted`: (pc, rn, value)."""
    refs = []
    for off in range(0, len(code) - 1, 2):
        w = struct.unpack_from("<H", code, off)[0]
        if w >> 12 != 0xD:
            continue
        pc = base + off
        ea = (pc & ~3) + 4 + (w & 0xFF) * 4
        o = ea - base
        if 0 <= o <= len(code) - 4:
            v = struct.unpack_from("<I", code, o)[0]
            if v in wanted:
                refs.append((pc, (w >> 8) & 0xF, v))
    return refs


def surface_sha(vram: bytes, s: Surface) -> str:
    return hashlib.sha256(vram[s.vram:s.vram + s.size]).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("state_dir", nargs="+", help="extractor output dirs containing ram.bin and vram.bin")
    args = ap.parse_args(argv)
    for d in args.state_dir:
        ram = open(f"{d}/ram.bin", "rb").read()
        vram = open(f"{d}/vram.bin", "rb").read()
        s = surface_at(ram, BACKDROP_P)
        nodes = [n for n in allocator_nodes(ram, find_value(ram, BACKDROP_P)[0] - 0x10) if n["record"] == BACKDROP_P]
        print(json.dumps({"dir": d, "surface": {k: hex(v) for k, v in asdict(s).items()},
                          "tcw_vram_ok": s.tcw_vram == s.vram, "texture_sha256": surface_sha(vram, s),
                          "allocator_node": {k: hex(v) for k, v in nodes[0].items()} if nodes else None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
