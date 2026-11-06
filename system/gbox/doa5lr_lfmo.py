"""DOA5LR LFMO index parser (request #2450).

LFMO (magic ``LFMO``) is the name/index container paired with a CHCM asset
container (e.g. ``chara_common.bin`` alongside ``chara_common.lnk``).

Layout (big-endian, verified against the owned PS3 build 2026-11-06):

* ``0x00`` magic ``LFMO``
* ``0x04`` u32BE reserved (0)
* ``0x08`` u32BE entry count (2355 for chara_common)
* ``0x28`` entry table, 12-byte rows: (u32 zero, u32 seq, u32 abs_name_offset)
  - ``seq`` == row index for every row in the owned sample
  - ``abs_name_offset`` points into the name region
* table end: NUL-terminated string ``chara_common.order``
* name region: NUL-terminated names, one per entry, from ``abs_name_offset``
  to EOF. Names are identifier codes (e.g. ``/BR87Y@10T10000@...``), NOT
  monoalphabetic shifts of character names (single-byte XOR vs a 50-name
  roster: 0 hits; exact/prefix match: 0 hits). See
  ``evidence/lfmo_name_grammar.json`` on the ticket.

This module resolves entry names and groups entries by base code
(``/XXXXX`` field0 + ``@token`` field1). It does not identify characters:
252 char-magic entries = 14 roster characters x 18 assets, but the code ->
character mapping lives in the executable/order layer, not in the names.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"LFMO"
HEADER_SIZE = 0x28
ROW_SIZE = 12


@dataclass(frozen=True)
class LfmoEntry:
    index: int
    seq: int
    name_offset: int
    name: str


@dataclass
class Lfmo:
    count: int
    table_end: int
    order_name: str
    entries: tuple = field(default=())

    def name_at(self, index: int) -> str:
        return self.entries[index].name


def parse(data: bytes) -> Lfmo:
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise ValueError("not an LFMO container")
    count = struct.unpack_from(">I", data, 8)[0]
    if count == 0 or HEADER_SIZE + count * ROW_SIZE > len(data):
        raise ValueError("LFMO table out of bounds")

    entries = []
    for i in range(count):
        _zero, seq, name_off = struct.unpack_from(">III", data, HEADER_SIZE + i * ROW_SIZE)
        end = data.find(b"\x00", name_off)
        if end < 0:
            raise ValueError(f"LFMO name {i} not NUL-terminated")
        entries.append(LfmoEntry(i, seq, name_off, data[name_off:end].decode("latin1")))

    table_end = HEADER_SIZE + count * ROW_SIZE
    end = data.find(b"\x00", table_end)
    order_name = data[table_end:end].decode("latin1") if end > 0 else ""
    return Lfmo(count=count, table_end=table_end, order_name=order_name, entries=tuple(entries))


def base_code(name: str) -> str:
    """``/BR87Y@10T10000@...`` -> ``BR87Y`` (field0 without leading slash)."""
    body = name[1:] if name.startswith("/") else name
    return body.split("@", 1)[0]


def variant_index(name: str) -> int:
    """2nd char of field0 is a per-costume variant index (R..Z observed).

    ``/BR87Y`` -> 1 (R). Raises ValueError when field0 is shorter than 2.
    """
    code = base_code(name)
    if len(code) < 2:
        raise ValueError(f"short base code: {code!r}")
    c = code[1]
    if not ("R" <= c <= "Z"):
        raise ValueError(f"variant char not R..Z in {name!r}")
    return ord(c) - ord("R") + 1


def group_by_base(entries) -> dict:
    """Group entry indices by base code, preserving table order."""
    groups: dict[str, list] = {}
    for e in entries:
        groups.setdefault(base_code(e.name), []).append(e.index)
    return groups


def char_magic_candidates(entries, min_payload_size: int = 149):
    """Indices whose 2nd field is a ``@10T...``/``@10S...`` token.

    In the owned sample these are the large char_dat payloads (>= 149 B);
    ``@1S100`` entries are the small 36 B / 148 B payloads. This is a shape
    heuristic, not a character identification.
    """
    out = []
    for e in entries:
        parts = e.name.split("@")
        if len(parts) >= 2 and (
            parts[1].startswith("1S")
            or (parts[1].startswith("10") and len(parts[1]) >= 3 and parts[1][2] in ("T", "S"))
        ):
            out.append(e.index)
    return out
