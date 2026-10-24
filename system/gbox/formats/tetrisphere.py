"""Tetrisphere (N64, USA) native asset inventory helpers.

Derived from the owned build for game_id c48ed290c9f63122
("Tetrisphere (USA).z64").  All multi-byte fields in the owned build are
big-endian (N64 native).

Block layout confirmed against the owned build bytes:

  * ``DCM1`` blocks - compiled resource containers (model/animation payload).
  * ``SQSH`` blocks - geometry/animation blocks (one per asset slot).
  * A flat rodata name pool holds the six CPU opponents (ROCKET, GEAR, GYRO,
    STOMP, WHEELS, TURBINE), the human player slot (JAK) and the three
    difficulty names (EASY, NORMAL, HARD).

This is an *inventory* reader: it enumerates and describes the owned build's
native assets and identifies the character roster.  It never mutates the ROM.
"""

from __future__ import annotations

import array
import hashlib
import struct
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

KSEG0 = 0x80000000
N64_ROM_MAGIC = b"\x80\x37\x12\x40"
DCM1_MAGIC = b"DCM1"
SQSH_MAGIC = b"SQSH"

CPU_CHARACTERS = ("ROCKET", "GEAR", "GYRO", "STOMP", "WHEELS", "TURBINE")
PLAYER_SLOT = "JAK"
DIFFICULTIES = ("EASY", "NORMAL", "HARD")
ROSTER_NAMES = CPU_CHARACTERS + (PLAYER_SLOT,) + DIFFICULTIES


@dataclass(frozen=True)
class Block:
    """One native asset block located in the owned build."""

    magic: str
    index: int
    offset: int
    size: int

    @property
    def rom_address(self) -> int:
        return KSEG0 | self.offset

    def as_dict(self) -> Dict[str, int]:
        return {
            "magic": self.magic,
            "index": self.index,
            "offset": self.offset,
            "size": self.size,
            "rom_address": self.rom_address,
        }


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    """Hash the owned source by streaming its bytes (never a copied hash)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def read_rom_header(data: bytes) -> Dict[str, object]:
    """Decode the 0x40-byte N64 ROM header of the owned build."""
    if len(data) < 0x40:
        raise ValueError("ROM shorter than the 0x40-byte N64 header")
    magic = data[0:4]
    if magic != N64_ROM_MAGIC:
        raise ValueError("unexpected N64 ROM magic %r" % (magic,))
    return {
        "magic": magic.hex(),
        "revision": data[4],
        "country_code": chr(data[0x3E]),
        "cartridge_name": data[0x20:0x34].decode("ascii", "replace").rstrip("\x00 "),
        "size_bytes": len(data),
    }


def iter_blocks(data: bytes, magic: bytes) -> List[Block]:
    """Enumerate every block of `magic` with its ROM offset and size."""
    offsets: List[int] = []
    start = 0
    while True:
        pos = data.find(magic, start)
        if pos < 0:
            break
        offsets.append(pos)
        start = pos + 1
    blocks: List[Block] = []
    for i, off in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        blocks.append(Block(magic.decode("ascii"), i, off, end - off))
    return blocks


def parse_block_header(data: bytes, offset: int) -> Dict[str, object]:
    """Decode the fixed header words of a DCM1/SQSH block (big-endian)."""
    magic = data[offset:offset + 4]
    if magic not in (DCM1_MAGIC, SQSH_MAGIC):
        raise ValueError("no block magic at 0x%06X" % offset)
    words = [
        struct.unpack(">H", data[offset + 4 + 2 * i:offset + 6 + 2 * i])[0]
        for i in range(8)
    ]
    return {"magic": magic.decode("ascii"), "offset": offset, "u16": words}


def find_character_names(data: bytes) -> List[Dict[str, object]]:
    """Locate the character-roster name pool in the owned build."""
    found: List[Dict[str, object]] = []
    for name in ROSTER_NAMES:
        needle = name.encode("ascii").ljust(8, b"\x00")
        pos = data.find(needle)
        if pos < 0:
            continue
        if name in CPU_CHARACTERS:
            role = "cpu-character"
        elif name == PLAYER_SLOT:
            role = "player-slot"
        else:
            role = "difficulty"
        found.append({
            "name": name,
            "name_offset": pos,
            "rom_address": KSEG0 | pos,
            "role": role,
        })
    return found


def _u32(data: bytes, off: int) -> Optional[int]:
    if off < 0 or off + 4 > len(data):
        return None
    return struct.unpack(">I", data[off:off + 4])[0]


def _u32_array(data: bytes) -> array.array:
    words = array.array("I")
    words.frombytes(data[:(len(data) // 4) * 4])
    if sys.byteorder == "little":
        words.byteswap()
    return words


def find_pointer_references(data: bytes, address: int) -> List[int]:
    """ROM offsets that store a 32-bit pointer to `address`."""
    needle = struct.pack(">I", address & 0xFFFFFFFF)
    out: List[int] = []
    start = 0
    while True:
        pos = data.find(needle, start)
        if pos < 0:
            break
        out.append(pos)
        start = pos + 1
    return out


def find_index_runs(data: bytes, limit: int, min_len: int = 4) -> List[Tuple[int, List[int]]]:
    """Contiguous u32 runs that could be block-index tables."""
    words = _u32_array(data)
    runs: List[Tuple[int, List[int]]] = []
    n = len(words)
    i = 0
    while i < n:
        if words[i] < limit:
            j = i + 1
            while j < n and words[j] < limit:
                j += 1
            if j - i >= min_len:
                runs.append((i * 4, list(words[i:j])))
                i = j
                continue
        i += 1
    return runs


def resolve_character_assets(data: bytes) -> List[Dict[str, object]]:
    """Bind each roster name to a native block using pointer/index evidence.

    A name is only reported as ``resolved`` when a 32-bit pointer to its name
    string has an adjacent block-index word; ``candidate`` means an index run
    of the right length exists but no direct pointer adjacency was found.
    """
    sqsh = iter_blocks(data, SQSH_MAGIC)
    dcm1 = iter_blocks(data, DCM1_MAGIC)
    entries: List[Dict[str, object]] = []
    for entry in find_character_names(data):
        refs = find_pointer_references(data, int(entry["rom_address"]))
        links: List[Dict[str, object]] = []
        for ref in refs:
            for value in (_u32(data, ref - 4), _u32(data, ref + 4)):
                if value is None:
                    continue
                if value < len(sqsh):
                    links.append(sqsh[value].as_dict())
                elif value < len(dcm1):
                    links.append(dcm1[value].as_dict())
        unique: List[Dict[str, object]] = []
        for link in links:
            if link not in unique:
                unique.append(link)
        entries.append({
            **entry,
            "references": refs,
            "blocks": unique,
            "status": "resolved" if unique else "unresolved",
        })
    return entries


def build_manifest(path: str, include_index_runs: bool = True) -> Dict[str, object]:
    """Authoritative owned-build manifest: identity, counts, roster, slots."""
    with open(path, "rb") as handle:
        data = handle.read()
    sqsh = iter_blocks(data, SQSH_MAGIC)
    dcm1 = iter_blocks(data, DCM1_MAGIC)
    manifest: Dict[str, object] = {
        "source_path": path,
        "source_sha256": sha256_file(path),
        "size_bytes": len(data),
        "header": read_rom_header(data),
        "byte_order": "big-endian",
        "counts": {
            "sqsh_blocks": len(sqsh),
            "dcm1_blocks": len(dcm1),
            "roster_names": len(find_character_names(data)),
        },
        "blocks": {
            "sqsh": [b.as_dict() for b in sqsh],
            "dcm1": [b.as_dict() for b in dcm1],
        },
        "roster": find_character_names(data),
        "character_assets": resolve_character_assets(data),
    }
    if include_index_runs:
        manifest["index_run_candidates"] = {
            "sqsh": [{"offset": o, "values": v}
                     for o, v in sorted(find_index_runs(data, max(len(sqsh), 1)), key=lambda r: -len(r[1]))[:8]],
            "dcm1": [{"offset": o, "values": v}
                     for o, v in sorted(find_index_runs(data, max(len(dcm1), 1)), key=lambda r: -len(r[1]))[:8]],
        }
    return manifest
