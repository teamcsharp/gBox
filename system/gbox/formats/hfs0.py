"""Shared HFS0 (Switch gamecard partition filesystem) reader for retail-layout / headerless-flasher XCI dumps.

Layout (all little-endian): header 0x10 = b"HFS0", u32 file_count, u32 string_table_size, u32 reserved; then
file_count 0x40-byte entries {u64 offset, u64 size, u32 name_off, u32 hashed_size, u64 reserved, 32B sha256 of the
first hashed_size bytes}; then the string table; file data follows it. Entry offsets are relative to the end of the
string table. Pure reads through read_at(offset, n); never writes.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable

MAGIC = b"HFS0"
ROOT_DEFAULT = 0xF000          # card header (HEAD at 0x100) normally places the root HFS0 here
MAX_ENTRIES = 4096
MAX_POOL = 1 << 20


@dataclass
class Hfs0Entry:
    name: str
    offset: int                 # absolute file offset of the data
    size: int
    hashed_size: int
    sha256: str                 # stored hash (hex) of the first hashed_size bytes


def parse_hfs0(read_at: Callable[[int, int], bytes], base: int, file_size: int | None = None) -> list[Hfs0Entry]:
    hdr = read_at(base, 0x10)
    if len(hdr) < 0x10:
        raise ValueError("truncated HFS0 header")
    if hdr[:4] != MAGIC:
        raise ValueError("not an HFS0 partition")
    count, pool, _ = struct.unpack_from("<III", hdr, 4)
    if count > MAX_ENTRIES or pool > MAX_POOL:
        raise ValueError(f"implausible HFS0 geometry (count={count}, string table={pool})")
    ents = read_at(base + 0x10, count * 0x40)
    names = read_at(base + 0x10 + count * 0x40, pool)
    if len(ents) < count * 0x40 or len(names) < pool:
        raise ValueError("truncated HFS0 entry table")
    data = base + 0x10 + count * 0x40 + pool
    out = []
    for i in range(count):
        off, size, no, hs, _res = struct.unpack_from("<QQIIQ", ents, i * 0x40)
        end = names.find(b"\0", no)
        if no >= pool or end < 0:
            raise ValueError(f"HFS0 entry {i}: name offset outside string table")
        if file_size is not None and data + off + size > file_size:
            raise ValueError(f"HFS0 entry {i}: data beyond end of file")
        out.append(Hfs0Entry(names[no:end].decode("utf-8", "replace"), data + off, size, hs,
                             ents[i * 0x40 + 32:(i + 1) * 0x40].hex()))
    return out


def card_root(read_at: Callable[[int, int], bytes]) -> int:
    """Root HFS0 offset of a card dump: the HEAD header's field at 0x130 when valid, else the 0xF000 default."""
    head = read_at(0x100, 0x40)
    if len(head) < 0x40 or head[:4] != b"HEAD":
        raise ValueError("not a Switch card image (no HEAD header at 0x100)")
    root = struct.unpack_from("<Q", head, 0x30)[0]
    return root if root and read_at(root, 4) == MAGIC else ROOT_DEFAULT


def list_card(read_at: Callable[[int, int], bytes], file_size: int | None = None) -> dict[str, list[Hfs0Entry]]:
    """{partition name: entries} for update/normal/secure/logo partitions of a headerless-flasher card dump."""
    root = card_root(read_at)
    parts = {}
    for p in parse_hfs0(read_at, root, file_size):
        parts[p.name] = parse_hfs0(read_at, p.offset, file_size)
    return parts
