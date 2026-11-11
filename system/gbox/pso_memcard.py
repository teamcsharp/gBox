"""Read a GameCube memory card's directory: what saves it holds, and whether they have any data blocks.

The format (public, and confirmed against the lane's card):

* `0x0000-0x1FFF` directory entries, 0x40 bytes each (`0x0000/0x0040/...`); the entry's checksums live at
  `0x1FE0-0x1FFF`.
* `0x2000-0x3FFF` the spare directory, `0x4000-0x5FFF` the block allocation table, `0x6000+` the data blocks (8 KiB).
* Entry layout: game code `+0x00` (4), company `+0x04` (2), banner `+0x06`, filename length `+0x07`, filename
  `+0x08` (32), last modified `+0x28` (4), image offset `+0x2C` (4), icon format `+0x30` (2), animation `+0x32` (2),
  icon speed `+0x34`, permissions `+0x36` (2), copy counter `+0x38` (2), **first block `+0x3A` (2)**, block count
  `+0x3C` (2).

A first block of `0xFFFF` with a count of 0 means an entry with **no data**, which is exactly what the lane's
`MemoryCardA.USA.raw` shows for all three of its PSO entries (`PSO_SYSTEM`, `PSO_CHARACTER`, `PSO_GUILDCARD`, game
`GPOE`/`8P`) - the reason SELECT CHARACTER shows four `NO DATA` slots.
"""
from __future__ import annotations

import struct
from pathlib import Path

CARD_SIZE = 16 * 1024 * 1024
BLOCK = 0x2000
DIRECTORY = 0x0000
SPARE_DIRECTORY = 0x2000
BAT = 0x4000
DATA = 0x6000
ENTRY = 0x40
FIRST_BLOCK_FREE = 0xFFFF


def entries(card: bytes) -> list:
    """Every valid directory entry: {dir_off, game, company, name, last_modified, first_block, blocks, bytes}."""
    out = []
    for start in (DIRECTORY, SPARE_DIRECTORY):
        for off in range(start, start + 0x2000, ENTRY):
            raw = card[off:off + ENTRY]
            if len(raw) < ENTRY or not raw[0:4].isalpha() or not raw[0:4].isupper():
                continue
            name = raw[0x08:0x28].split(b"\x00")[0].decode("latin-1", "replace")
            first, count = struct.unpack_from(">HH", raw, 0x3A)
            out.append({"dir_off": off, "game": raw[0:4].decode("ascii"),
                        "company": raw[4:6].decode("latin-1", "replace"),
                        "name": name, "last_modified": struct.unpack_from(">I", raw, 0x28)[0],
                        "first_block": first, "blocks": count,
                        "bytes": count * BLOCK, "has_data": first != FIRST_BLOCK_FREE and count > 0})
    return out


def chain(card: bytes, entry: dict, limit: int = 256) -> list:
    """The entry's block chain from the BAT (each block's next pointer is the first u16 of its BAT slot)."""
    if not entry["has_data"]:
        return []
    blocks, block = [], entry["first_block"]
    for _ in range(min(limit, entry["blocks"] + 1)):
        blocks.append(block)
        nxt = struct.unpack_from(">H", card, BAT + block * ENTRY)[0]
        if nxt in (0, 0xFFFF) or nxt in blocks:
            break
        block = nxt
    return blocks


def saves(card: bytes, game: str | None = None) -> list:
    """The card's saves (optionally only one game code), with their chains."""
    found = [e for e in entries(card) if game is None or e["game"] == game]
    for entry in found:
        entry["chain"] = chain(card, entry)
    return found


def read(path) -> bytes:
    data = Path(path).read_bytes()
    if len(data) != CARD_SIZE:
        raise ValueError(f"{path}: {len(data)} bytes, not a 16 MiB GameCube card")
    return data
