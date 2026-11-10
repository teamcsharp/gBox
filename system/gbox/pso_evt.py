"""The `.evt` event table: first-pass structure.

Door transitions are the thing this lane has never been able to find in the placement sets -- the `o.dat` records place
objects, and whether a placed door transitions is decided elsewhere. The `event` archive's `.evt` entries are the only files
named for events, so this is where that decision should be.

What the bytes say (measured on `map_forest01_00.evt`, 500 bytes, i9-NUC 2026-11-10):

```
0000  8c 01 00 00  10 00 00 00  13 00 00 00  00 00 00 00     header: 0x18c, 0x10, 0x13, 0
0010  6f 00 00 00  00 00 01 00  0b 00 01 00  32 00 00 00  00 00 00 00
0024  57 04 00 00  00 00 01 00  0b 00 02 00  32 00 00 00  06 00 00 00
0038  58 04 00 00  00 00 01 00  0b 00 03 00  32 00 00 00  0c 00 00 00
```

A 16-byte header (396, 16, 19, 0 in this file), then **20-byte records**, then a 4-byte footer. The records come in
**groups**, not one run: the first group is `0x6f`, `0x457`, `0x458`, `0x459` with opcode `0x0b`, arguments 1..4 and the last
word stepping 0, 6, 12, 18; the next group starts again lower (`0x65`, `0x3f3`, `0x3f4`) with opcode `0x0a` and a 60/25
pair. So a record looks like ``{id, flags, page, opcode, arg, value, offset}`` and a *group* of records shares an opcode --
which is what a script of operations over a set of event ids would look like.

This is a first pass. The field names are honest guesses and the opcode meanings are unknown; what is measured is the
framing (16 + n*20 + 4), the header values, the group structure, and the fact that the trailing word steps by six within a
group.
"""
from __future__ import annotations

import struct

HEADER_SIZE = 16
RECORD_SIZE = 20


class EventError(ValueError):
    """The bytes are not an event table this parser recognises."""


def header(data: bytes) -> dict:
    """The 16-byte preamble: three u32 values then a zero word in every file seen so far."""
    if len(data) < HEADER_SIZE:
        raise EventError(f"{len(data)} bytes is smaller than the {HEADER_SIZE}-byte header")
    a, b, c, d = struct.unpack_from("<4I", data, 0)
    return {"a": a, "b": b, "c": c, "d": d}


def table_end(data: bytes) -> int:
    """Where the record table ends and the event's script begins: ``header.a == HEADER_SIZE + RECORD_SIZE * header.c``.

    Every one of the 147 event files on the owned disc satisfies that identity (`tests/test_pso_evt.py` checks it for
    all of them). Reading ``(len(data) - HEADER_SIZE) // RECORD_SIZE`` records instead - what this module did before
    CP6 - fabricates records **out of the script's bytes** in 138 of the 147 files, because the script is not a
    multiple of 20. The count is in the file; it has to be used.
    """
    h = header(data)
    end = HEADER_SIZE + RECORD_SIZE * h["c"]
    if h["a"] != end:
        raise EventError(f"the header's size field is {h['a']} but {h['c']} records of {RECORD_SIZE} bytes need {end}")
    if end > len(data):
        raise EventError(f"the table claims {h['c']} records ({end} bytes) but the file has {len(data)}")
    return end


def script(data: bytes) -> bytes:
    """The event's script blob: everything after the record table (0 to 404 bytes across the disc)."""
    return data[table_end(data):]


def build(header_fields: dict, recs: list[dict], script: bytes = b"") -> bytes:
    """The inverse of :func:`header`/:func:`records`/:func:`script` - byte-identical for every event file on the disc."""
    body = b"".join(struct.pack("<IHHHHII", r["id"], r["flags"], r["page"], r["opcode"], r["arg"], r["value"],
                                r["offset"]) for r in recs)
    head = struct.pack("<4I", HEADER_SIZE + len(body), header_fields["b"], len(recs), header_fields["d"])
    return head + body + script


def records(data: bytes) -> list[dict]:
    """The 20-byte records after the header, interpreting each word the way the offsets in the file suggest.

    ``id`` looks like the event id (sequential across records), ``opcode`` the operation, ``arg`` its parameter, and
    ``value``/``offset`` the two trailing words -- the last of which steps by six per record in the file measured.
    The count comes from the header (:func:`table_end`), so the script is never read as records.
    """
    h = header(data)
    out = []
    body = data[HEADER_SIZE:table_end(data)]
    for i in range(len(body) // RECORD_SIZE):
        off = i * RECORD_SIZE
        rid, flags, index, opcode, arg, value, offset = struct.unpack_from("<IHHHHII", body, off)
        out.append({"index": i, "id": rid, "flags": flags, "page": index, "opcode": opcode,
                    "arg": arg, "value": value, "offset": offset})
    return out


def summary(data: bytes) -> dict:
    """A block a lane doc or a CLI can print: the header, the record count, and the opcodes present."""
    h = header(data)
    recs = records(data)
    ops = {}
    for r in recs:
        ops[r["opcode"]] = ops.get(r["opcode"], 0) + 1
    ids = [r["id"] for r in recs]
    runs = sum(1 for a, b in zip(ids, ids[1:]) if b == a + 1)
    return {"header": h, "records": len(recs), "script_bytes": len(script(data)),
            "trailing_bytes": (len(data) - HEADER_SIZE) % RECORD_SIZE,
            "opcodes": dict(sorted(ops.items())),
            "first_id": ids[0] if ids else None,
            "id_min": min(ids) if ids else None, "id_max": max(ids) if ids else None,
            "consecutive_pairs": runs}   # the file is a set of groups, so this is small relative to the record count
