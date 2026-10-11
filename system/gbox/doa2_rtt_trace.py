"""Offline DOA2 ranking-backdrop surface and allocator diagnostics for #1216.

Only extracted guest RAM/VRAM bytes are read; this module does not control an
emulator. The observed 0x3c-byte surface starts 0x20 bytes before its VRAM field
P. Allocator nodes are 0x18 bytes: flags, next, prev, vram, size, record P.

Both private R4 snapshots contain the backdrop surface at P=0x8c20cd28 and a
reciprocally linked allocator node at 0x8c2c2928. Surface metadata match, while
the backing VRAM hashes differ. These observations do not identify the RTT
producer, its redraw trigger, or whether a render occurred only once. Literal
pool scans below return instruction candidates, not a control-flow trace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

RAM_BASE = 0x8C000000
RECORD_STRIDE = 0x3C
ALLOCATOR_STRIDE = 0x18
ALLOCATOR_RECORD_OFFSET = 0x14
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


def _ram_offset(ram: bytes, addr: int, size: int) -> int:
    if not isinstance(addr, int) or isinstance(addr, bool) or addr % 4:
        raise ValueError("guest RAM address must be a word-aligned integer")
    offset = addr - RAM_BASE
    if offset < 0 or offset + size > len(ram):
        raise ValueError(f"guest RAM read outside capture: {addr:#x}, {size} bytes")
    return offset


def u32(ram: bytes, addr: int) -> int:
    return struct.unpack_from("<I", ram, _ram_offset(ram, addr, 4))[0]


def surface_at(ram: bytes, p: int) -> Surface:
    # Validate the whole record before reading individual fields.
    if not isinstance(p, int) or isinstance(p, bool):
        raise ValueError("surface pointer must be an integer")
    offset = _ram_offset(ram, p - 0x20, RECORD_STRIDE)
    w = struct.unpack_from("<15I", ram, offset)
    return Surface(p, w[0], w[3], w[4], w[5], w[6], w[7], w[8], w[14])


def _allocator_node(ram: bytes, addr: int) -> dict[str, int]:
    offset = _ram_offset(ram, addr, ALLOCATOR_STRIDE)
    flags, nxt, prev, vram, size, rec = struct.unpack_from("<6I", ram, offset)
    return {"node": addr, "flags": flags, "next": nxt, "prev": prev,
            "vram": vram, "size": size, "record": rec}


def allocator_nodes(ram: bytes, start: int, limit: int = 256) -> list[dict[str, int]]:
    """Boundedly walk next links, stopping at zero, a cycle, or ``limit``.

    A malformed nonzero pointer raises ValueError instead of silently returning
    a partial traversal. This raw walker does not itself prove list membership.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("allocator traversal limit must be a positive integer")
    if not isinstance(start, int) or isinstance(start, bool):
        raise ValueError("allocator start must be an integer")
    out, seen, addr = [], set(), start
    while addr and addr not in seen and len(out) < limit:
        node = _allocator_node(ram, addr)
        seen.add(addr)
        out.append(node)
        addr = node["next"]
    return out


def find_value(ram: bytes, value: int) -> list[int]:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("searched value must be a uint32")
    pat = struct.pack("<I", value)
    hits, offset = [], ram.find(pat)
    while offset >= 0:
        if offset % 4 == 0:
            hits.append(RAM_BASE + offset)
        offset = ram.find(pat, offset + 1)
    return hits


def surface_allocator_nodes(ram: bytes, s: Surface) -> list[dict[str, int]]:
    """Find candidates matching surface fields and both reciprocal neighbours.

    A pointer literal alone is insufficient. Nodes lacking either neighbour are
    not established members by this check. A self-linked singleton is valid.
    This validates local links, not reachability from an unknown allocator head.
    """
    out = []
    for hit in find_value(ram, s.p):
        try:
            node = _allocator_node(ram, hit - ALLOCATOR_RECORD_OFFSET)
            if (node["record"], node["vram"], node["size"]) != (s.p, s.vram, s.size):
                continue
            if not node["next"] or not node["prev"]:
                continue
            nxt = _allocator_node(ram, node["next"])
            prev = _allocator_node(ram, node["prev"])
            if nxt["prev"] != node["node"] or prev["next"] != node["node"]:
                continue
        except ValueError:
            continue
        out.append(node)
    return out


def sh4_pool_refs(code: bytes, base: int, wanted: set[int]) -> list[tuple[int, int, int]]:
    """Candidate mov.l PC-relative literals: (pc, register, value).

    Raw instruction scanning may also match data; callers must establish code
    boundaries independently before using the result as execution evidence.
    """
    if not isinstance(base, int) or isinstance(base, bool) or base < 0 or base % 2:
        raise ValueError("SH4 base must be a nonnegative halfword-aligned integer")
    refs = []
    for off in range(0, len(code) - 1, 2):
        word = struct.unpack_from("<H", code, off)[0]
        if word >> 12 != 0xD:
            continue
        pc = base + off
        offset = (pc & ~3) + 4 + (word & 0xFF) * 4 - base
        if 0 <= offset <= len(code) - 4:
            value = struct.unpack_from("<I", code, offset)[0]
            if value in wanted:
                refs.append((pc, (word >> 8) & 0xF, value))
    return refs


def surface_sha(vram: bytes, s: Surface) -> str:
    if (not isinstance(s.vram, int) or isinstance(s.vram, bool) or s.vram < 0
            or not isinstance(s.size, int) or isinstance(s.size, bool) or s.size <= 0
            or s.vram + s.size > len(vram)):
        raise ValueError("surface VRAM span must be positive and fully contained in capture")
    return hashlib.sha256(vram[s.vram:s.vram + s.size]).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("state_dir", nargs="+", help="extractor dirs containing ram.bin and vram.bin")
    args = ap.parse_args(argv)
    failed = False
    for directory in args.state_dir:
        try:
            ram = (Path(directory) / "ram.bin").read_bytes()
            vram = (Path(directory) / "vram.bin").read_bytes()
            surface = surface_at(ram, BACKDROP_P)
            digest = surface_sha(vram, surface)
            nodes = surface_allocator_nodes(ram, surface)
            status = "unique" if len(nodes) == 1 else "missing" if not nodes else "ambiguous"
            row = {"dir": directory, "surface": {k: hex(v) for k, v in asdict(surface).items()},
                   "tcw_vram_ok": surface.tcw_vram == surface.vram,
                   "texture_sha256": digest, "allocator_status": status,
                   "allocator_candidates": [{k: hex(v) for k, v in node.items()} for node in nodes],
                   "allocator_node": {k: hex(v) for k, v in nodes[0].items()} if len(nodes) == 1 else None}
            failed |= status != "unique" or not row["tcw_vram_ok"]
        except (OSError, ValueError) as exc:
            row = {"dir": directory, "error": str(exc)}
            failed = True
        print(json.dumps(row))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
