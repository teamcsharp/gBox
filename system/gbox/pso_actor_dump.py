"""A raw field dump of one live actor, so a pad's or a door's handler field can be found without guessing.

The static hunt for the placement-class dispatch is exhausted (no vtable, no name-comparison code, no city event set -
`docs/research/pso-travel-and-gate.md`), so the remaining discriminator is a live object: dump its first bytes and read
which fields are pointers into code or into the class tables. `actor_fields()` does that from any `pso_ram.Reader`, so a
live window (or a savestate) answers it in one call, and the shape of the answer is testable offline.
"""
from __future__ import annotations

import struct

from .pso_ram import RAM_END, RAM_START, RamError

#: the fields `pso_ram` already names, so a dump can label what it can
KNOWN_FIELDS = {
    0x000: "class pointer",
    0x028: "room",
    0x038: "x",
    0x03C: "y",
    0x040: "z",
    0x0A8: "hit records",
    0x0AC: "native state",
    0x0C8: "stage flag",
    0x2B8: "hp max",
    0x324: "control mode",
    0x326: "action state",
    0x32C: "hp",
}


def actor_fields(reader, pointer: int, *, size: int = 0x60, words: int | None = None) -> dict:
    """Dump one actor's first `size` bytes as u32 fields, labelled and classified.

    Each field is `{offset, name, value, kind}` where kind is "class-name" (a pointer to printable text),
    "executable" (a pointer into the executable's 0x8000C000-0x80600000 image - code and data share that range, so a
    caller looks closer), "ram" (another RAM pointer), "small" (a value that could be a count/index) or "raw". This is
    deliberately read-only and bounded.
    """
    count = words if words is not None else max(1, size // 4)
    out = []
    for i in range(count):
        off = i * 4
        try:
            value = reader.u32(pointer + off)
        except RamError:
            break
        kind, text = "raw", None
        if RAM_START <= value < RAM_END:
            try:
                name = reader.cstring(value, 24)
            except RamError:
                name = None
            if name and name.isprintable() and name[:1].isalpha():
                kind, text = "class-name", name
            elif 0x8000C000 <= value < 0x80600000 and (value & 3) == 0:
                kind = "executable"
            else:
                kind = "ram"
        elif value < 0x10000:
            kind = "small"
        out.append({"offset": off, "name": KNOWN_FIELDS.get(off), "value": value, "kind": kind, "text": text})
    return {"pointer": pointer, "fields": out}


def handlers(reader, pointer: int, *, size: int = 0x200) -> list:
    """The fields of an actor that point into the executable image - candidate handler/update slots.

    A candidate still has to be checked (the image holds data as well as code), which is what
    `Ghiddra`/`pso_ram`'s address table or a disassembly of the target settles in one look.
    """
    return [f for f in actor_fields(reader, pointer, size=size)["fields"] if f["kind"] == "executable"]


def actor_dump(reader, items: list[dict], *, cls: str | None = None, index: int = 0, size: int = 0x60) -> dict | None:
    """Dump the first actor of `cls` (or the `index`-th actor) from a `pso_entities.entities()` list."""
    pool = [e for e in items if cls is None or str(e["cls"]).startswith(cls)]
    if not pool:
        return None
    chosen = pool[min(index, len(pool) - 1)]
    out = actor_fields(reader, chosen["pointer"], size=size)
    out.update({"cls": chosen["cls"], "index": chosen["index"], "room": chosen.get("room"),
                "pos": (chosen.get("x"), chosen.get("y"), chosen.get("z"))})
    return out
