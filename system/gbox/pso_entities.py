"""P2b/P3: PSO's live entity list from RAM.

`ENTITY_TABLE` (``0x8050D460``) **is the object table**: the address holds the first of a run of ``u32`` object
pointers (it is not a pointer to the table -- reading the word there gives the first object, the player, which is what
made a first version of this module walk one level too deep and find nothing). Each entry points at a live actor whose
``+0x00`` is a ``char*`` to its class name, ``+0x28`` a ``u16`` room and ``+0x38/+0x3C/+0x40`` its world position. Proven live on the owned build in Pioneer 2, 2026-11-10 (session
``dbc5ff9be4ca416c-c91e5802a9844b37``): 29 objects, including

    TObjPlayer            room 41  ( 52.7,  -2008.1)   the character
    TObjNpcSecretaryBase  room 41  ( 47.0,  -2000.0)   Irene, the Principal's secretary
    TObjNpcGovernorBase   room 41  (  0.0,  -2031.0)   Principal Tyrell
    TObjCityDoor_Guild    room 10  (185.0,    173.0)   the Hunter's Guild door
    TObjCityDoor_Warp     room 10  (254.0,     25.0)   the teleporter room
    TObjCityDoor_Med      room 10  (193.5,    -93.5)
    TObjCityDoor_Shop     room 10  (-165.0,   147.5)

That is what P3 needs to route room to room, and what P1 needs to find the guild. The table is a flat run of
pointers terminated by the first word that is not a live actor, so :func:`entities` stops there rather than reading
off into unrelated memory.
"""
from __future__ import annotations

from .pso_ram import ENTITY_TABLE, RAM_END, RAM_START, Reader, RamError

MAX_OBJECTS = 512          # a sane bound; the retail town holds ~30 and a busy field a few hundred


def _class_of(reader: Reader, ptr: int) -> str | None:
    """The actor's class name, or None when ``ptr`` is not a live actor (wrong shape or unreadable)."""
    if not RAM_START <= ptr < RAM_END:
        return None
    try:
        name_ptr = reader.u32(ptr)
        if not RAM_START <= name_ptr < RAM_END:
            return None
        text = reader.cstring(name_ptr, 24)
    except RamError:
        return None
    if text.startswith("TObj") and text.isprintable():
        return text
    return None


def entities(reader: Reader, limit: int = MAX_OBJECTS) -> list[dict]:
    """Every live actor, in table order: {index, pointer, cls, room, x, y, z}.

    Stops at the first word that is not a live actor. A table with nothing in it returns ``[]``, which is the
    correct answer for a title screen or a loading area -- callers must not treat it as an error.
    """
    base = ENTITY_TABLE                      # the TABLE IS the array: 0x8050D460 holds object pointers directly
    out = []
    for i in range(min(limit, 4096)):
        try:
            ptr = reader.u32(base + i * 4)
        except RamError:
            break
        cls = _class_of(reader, ptr)
        if cls is None:
            break
        try:
            room = reader.u16(ptr + 0x28)
            x, y, z = reader.position(ptr)
        except RamError:
            room, x, y, z = None, None, None, None
        out.append({"index": i, "pointer": ptr, "cls": cls, "room": room, "x": x, "y": y, "z": z})
    return out


def by_class(items: list[dict], prefix: str) -> list[dict]:
    """The entities whose class name starts with ``prefix`` (``"TObjCityDoor_"``, ``"TObjNpc"``, ...)."""
    return [e for e in items if str(e["cls"]).startswith(prefix)]


def nearest(items: list[dict], x: float, z: float, prefix: str | None = None) -> dict | None:
    """The entity nearest (x, z) in the XZ plane, optionally restricted to a class prefix."""
    pool = by_class(items, prefix) if prefix else items
    best, best_d = None, None
    for e in pool:
        if e["x"] is None:
            continue
        d = (e["x"] - x) ** 2 + (e["z"] - z) ** 2
        if best_d is None or d < best_d:
            best, best_d = e, d
    return best


def player(items: list[dict]) -> dict | None:
    """The first TObjPlayer in the list."""
    hits = by_class(items, "TObjPlayer")
    return hits[0] if hits else None
