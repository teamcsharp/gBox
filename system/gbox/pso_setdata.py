"""PSO Episode I & II area set data (``map_*d.dat`` / ``map_*ad.dat``): the object, enemy, door,
switch and warp placements of one area (or one room of a multi-room area).

These are the files the map loader reads next to the geometry (``Scene/map_*_n.rel``) and the
collision (``Scene/map_*c.rel``), and they are what a level editor has to move markers in and
write back.

Format, verified on the owned disc ``GPOE8P`` (Phantasy Star Online Episode I & II Plus (USA)):

* the file is a bare array of **68-byte (0x44) records**, little-endian. 141 of the 146
  ``map_*.dat`` files are an exact multiple of 68; the 5 that are not are the ``*e.dat`` event
  tables (``map_boss02jme.dat`` ..), a different format that sits next to the ``*.evt`` files.
* every multibyte field is little-endian, like the rest of PSO's Dreamcast-era data (PRS, AFS,
  BML, PR2). The GameCube payloads that PSO wrote new for this port (NJCM node trees, GSL
  tables) are big-endian; the ``.dat`` sets are not.

Record layout::

    +0x00 u32   kind          ``flags | class_index``: the low byte is the object class index
                              (:func:`kind_class`), the rest are flags (:func:`kind_flags`). Proven over
                              the 22,521 placements of the 144 object-set files: the high bits take only
                              12 values (0x0, 0x100, 0x200, 0x20000, 0x20100, 0x80000, 0x2000000,
                              0x2000100, 0x2000200, 0x8000000, 0x8000100, 0x8000200 -- all sparse bit
                              sets) while the low byte spans 108 distinct class indices 0..220, and
                              ``PsoV3.dol`` carries 315 ``TObj*`` class-name strings for the registry
    +0x04 u32   set_id        unique within the file; consecutive in table order
    +0x08 u32   group_id      also consecutive within the file, offset from set_id
    +0x0C u32   amount        usually 1; 1..16 on Forest 1 (stack / count per placement)
    +0x10 f32   x             world position                     PROVEN, see position_proof
    +0x14 f32   y
    +0x18 f32   z
    +0x1C u32   flags_a       small values; 0 on most records
    +0x20 u32   flags_b
    +0x24 u32   flags_c
    +0x28 f32   angle         degrees-like (30 / 41 / 51 / 101 on Forest 1)  unproven
    +0x2C f32   scale_x      1.0 on most records                          unproven
    +0x30 f32   scale_y      1.0 on most records                          unproven
    +0x34 u32   link          small ids (9, 0x35, ...)                     unproven
    +0x38 u32   extra_a
    +0x3C u32   extra_b
    +0x40 u32   stamp         monotonically increasing within a file, 0x8CFA____ .. 0x8CFB____
                              on every disc file; looks like a per-record serial, not a pointer
                              (it is outside the GameCube's 0x80000000..0x81800000 RAM window)

``position_proof`` is the load-bearing evidence for the position fields: the record's
``(x, y, z)`` agrees with the area's own collision surface height at ``(x, z)`` for
70/71 Cave 1, 72/74 Ruins 1 and 48/62 Pioneer 2 placements within 25 world units, median error
0.00 on Cave 1 and Ruins 1. Two independent decoders (this one and :mod:`gbox.psomap`) agreeing
is what makes the position triple proof rather than a guess.

The 68-byte record is written back verbatim by :func:`build`, so ``build(records(x)) == x`` for
every file on the disc: the decoder is lossless and safe to use as a rewriter.
"""
from __future__ import annotations

import struct

RECORD_SIZE = 0x44
_FMT = "<17I"
_FAMS = struct.Struct(_FMT)

# Field offsets, by name, for callers that patch one field (the editor does).
OFF = {name: i * 4 for i, name in enumerate((
    "kind", "set_id", "group_id", "amount",
    "x", "y", "z",
    "flags_a", "flags_b", "flags_c",
    "angle", "scale_x", "scale_y",
    "link", "extra_a", "extra_b", "stamp"))}

# The four fields that are floats; everything else is a u32.
FLOAT_FIELDS = ("x", "y", "z", "angle", "scale_x", "scale_y")

# `kind` = flags | class_index. The class index is a byte; everything above it is flags (see the module
# docstring for the census that proves it).
KIND_CLASS_MASK = 0xFF


def kind_class(kind: int) -> int:
    """The object class index of a placement's ``kind`` (low byte)."""
    return int(kind) & KIND_CLASS_MASK


def kind_flags(kind: int) -> int:
    """The placement's flags word (``kind`` with the class index removed)."""
    return int(kind) & ~KIND_CLASS_MASK & 0xFFFFFFFF


def kind_report(recs: list[dict]) -> dict:
    """{"flags": {word: count}, "classes": {index: count}} over a set's placements."""
    flags: dict[int, int] = {}
    classes: dict[int, int] = {}
    for r in recs:
        k = r["kind"]
        f, c = kind_flags(k), kind_class(k)
        flags[f] = flags.get(f, 0) + 1
        classes[c] = classes.get(c, 0) + 1
    return {"flags": dict(sorted(flags.items())), "classes": dict(sorted(classes.items()))}


class SetDataError(ValueError):
    pass


def record_count(data: bytes) -> int:
    """Number of 68-byte records in a set file; raises when the file is not whole records."""
    if len(data) % RECORD_SIZE:
        raise SetDataError(f"{len(data)} bytes is not a multiple of {RECORD_SIZE} (an *e.dat enemy spawn "
                           f"table, an *.evt event script or a corrupt file -- not an area placement set)")
    return len(data) // RECORD_SIZE


def records(data: bytes) -> list[dict]:
    """Every placement of one set file, in table order.

    Each dict carries ``raw`` (the 17 little-endian u32 words, so a rewriter can put back a
    record it did not touch byte for byte) plus the decoded fields named in :data:`OFF`.
    """
    n = record_count(data)
    out = []
    for i in range(n):
        raw = _FAMS.unpack_from(data, i * RECORD_SIZE)
        rec = {"index": i, "raw": raw}
        for name, off in OFF.items():
            v = raw[off // 4]
            rec[name] = struct.unpack("<f", struct.pack("<I", v))[0] if name in FLOAT_FIELDS else v
        out.append(rec)
    return out


def build(recs: list[dict]) -> bytes:
    """The set file for ``recs``; with unmodified records this is byte-identical to the source."""
    out = bytearray()
    for r in recs:
        raw = list(r["raw"])
        for name, off in OFF.items():
            if name not in r:
                continue
            idx = off // 4
            v = r[name]
            if name in FLOAT_FIELDS:
                raw[idx] = struct.unpack("<I", struct.pack("<f", float(v)))[0]
            else:
                if type(v) is not int or not 0 <= v <= 0xFFFFFFFF:
                    raise SetDataError(f"record {r.get('index')}: {name} must be a u32, got {v!r}")
                raw[idx] = v
        out += _FAMS.pack(*raw)
    return bytes(out)


def move(rec: dict, x: float, y: float, z: float) -> dict:
    """The same record with its world position replaced (the editor's drag)."""
    out = dict(rec)
    out["x"], out["y"], out["z"] = float(x), float(y), float(z)
    return out


def patch(data: bytes, changes: dict[int, dict]) -> bytes:
    """``data`` with ``{record index: {field: value}}`` applied; every other byte preserved."""
    recs = records(data)
    for i, fields in changes.items():
        if not 0 <= i < len(recs):
            raise SetDataError(f"record index {i} outside 0..{len(recs) - 1}")
        recs[i] = {**recs[i], **fields}
    return build(recs)


def kinds(recs: list[dict]) -> dict[int, int]:
    """{kind: count}, the placement class census of one set file."""
    out: dict[int, int] = {}
    for r in recs:
        out[r["kind"]] = out.get(r["kind"], 0) + 1
    return dict(sorted(out.items()))


def bounds(recs: list[dict]) -> dict:
    """World-space bounding box of the placements (min/max over x, y, z)."""
    if not recs:
        return {}
    xs = [r["x"] for r in recs]
    ys = [r["y"] for r in recs]
    zs = [r["z"] for r in recs]
    return {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys),
            "min_z": min(zs), "max_z": max(zs)}


def nearest(recs: list[dict], x: float, z: float, kinds_ok=None) -> dict | None:
    """The placement closest to (x, z) in the XZ plane, optionally restricted to some kinds."""
    best, best_d = None, None
    for r in recs:
        if kinds_ok is not None and r["kind"] not in kinds_ok:
            continue
        d = (r["x"] - x) ** 2 + (r["z"] - z) ** 2
        if best_d is None or d < best_d:
            best, best_d = r, d
    return best


# -------------------------------------------------------------------------------------------------- self-test

def _selftest():
    """A synthetic two-record file proves the layout, the round trip and the field patch."""
    words = [0x17, 0x000107AF, 0x00004874, 1,
             0x43F18F9C, 0x41818F5D, 0x444B64E8,
             0, 0x1700, 0,
             0x42240005, 0x3F800001, 0x3F800002,
             9, 0, 0, 0x8CFABA20]
    blob = _FAMS.pack(*words) + _FAMS.pack(*words)
    recs = records(blob)
    assert len(recs) == 2 and recs[0]["kind"] == 0x17 and recs[0]["set_id"] == 0x107AF
    assert abs(recs[0]["x"] - 483.12198) < 0.01 and abs(recs[0]["z"] - 813.5771) < 0.01, recs[0]
    assert build(recs) == blob                                        # lossless round trip
    moved = [move(recs[0], 0.0, 1.0, 2.0), recs[1]]
    out = build(moved)
    assert out[:12] == blob[:12] and out[0x10:0x1C] == struct.pack("<3f", 0.0, 1.0, 2.0)
    assert out[0x1C:] == blob[0x1C:]                                  # nothing else touched
    assert patch(blob, {1: {"kind": 0x1E}})[RECORD_SIZE] == 0x1E
    assert record_count(b"x" * 68) == 1
    try:
        record_count(b"x" * 69)
    except SetDataError:
        pass
    else:
        raise AssertionError("a non-multiple should raise")
    print("pso_setdata selftest ok")


if __name__ == "__main__":
    _selftest()
