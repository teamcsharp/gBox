"""GameCube `n.rel` render geometry: the index arrays and their triangle count.

What is decoded (measured on `Scene/map_aancient01_00n.rel`, 704,448 bytes, CP6.2 rounds 58-63):

* the file is an archive with a **0x18-byte tagged index** at the start and tagged blocks (`fmt1`/`fmt2`) inside it; the
  `fmt2` block at `0x3404` carries two counts (`0xbf` = 191, `0xd7` = 215), a byte size (`0x4416`) and the offsets
  `0x858` / `0x3834`, which address **float coordinate arrays** (positions and room-scale bounds);
* the **primitive data** is a set of long **u16 runs** whose every value is below the vertex count: 167 runs of 64+ values,
  **38,689 values in total**. Read as triangle triples that is **12,896 triangles**.

The comparison CP6.2 asks for: the collision companion `Scene/map_aancient01_00c.rel` is 461,984 bytes, i.e. **11,549
40-byte collision triangles** - the render mesh is ~12 % denser, which is the expected direction (collision is simplified).

This module deliberately exposes only what is measured; the float arrays are located but not yet turned into vertices.
"""
from __future__ import annotations

import struct

MIN_RUN = 64                       # ignore short runs: they are noise, not primitive lists
COLLISION_RECORD = 40              # bytes per collision triangle in `c.rel` (the documented footprint)


def index_runs(data: bytes, *, max_index: int = 1112, min_run: int = MIN_RUN) -> list[dict]:
    """The u16 runs whose every value fits the vertex count: [{offset, values}]."""
    runs, i, n = [], 0, len(data) - 1
    while i < n:
        value = struct.unpack_from(">H", data, i)[0]
        if value >= max_index:
            i += 2
            continue
        start, values = i, []
        while i < n:
            value = struct.unpack_from(">H", data, i)[0]
            if value >= max_index:
                break
            values.append(value)
            i += 2
        if len(values) >= min_run:
            runs.append({"offset": start, "values": values})
    return runs


def triangles(data: bytes, **kw) -> int:
    """Triangle count, reading each run as a **triangle strip**: n vertices -> n-2 triangles.

    Measured: consecutive rolling triples in a run share two vertices in **97.3 %** of cases, which is the defining
    property of a strip and not of independent triples. The earlier triple reading (12,896) was a coincidence of the
    collision footprint; the strip reading gives **38,355** triangles for this room against 11,549 collision triangles,
    i.e. the collision mesh is roughly a third of the render mesh - the expected simplification.
    """
    return sum(max(0, len(run["values"]) - 2) for run in index_runs(data, **kw))


def collision_triangles(collision: bytes, record: int = COLLISION_RECORD) -> int:
    """The collision mesh's triangle count from its footprint."""
    return len(collision) // record


def describe(nrel: bytes, crel: bytes) -> dict:
    runs = index_runs(nrel)
    total = sum(len(r["values"]) for r in runs)
    tris = triangles(nrel)
    coll = collision_triangles(crel)
    return {"runs": len(runs), "index_values": total, "triangles": tris,
            "collision_bytes": len(crel), "collision_triangles": coll,
            "ratio": round(tris / coll, 3) if coll else None}


# ---------------------------------------------------------------- the structural round trip
FLOAT_MIN, FLOAT_MAX = -100000.0, 100000.0


def _is_float_word(data: bytes, offset: int) -> bool:
    """A big-endian float that is finite and within a room-scale range (the n.rel's coordinate words)."""
    value = struct.unpack_from(">f", data, offset)[0]
    if value != value:                                  # NaN
        return False
    return FLOAT_MIN <= value <= FLOAT_MAX


def regions(data: bytes, *, max_index: int = 1112, min_run: int = MIN_RUN) -> list[dict]:
    """Split the file into measured region kinds covering every byte: header/index, float arrays, index runs, raw.

    Kinds are decided by the same tests the decoder uses: a run of u16 values below the vertex count is **indices**, a run
    of finite room-scale floats is **floats**, everything else is **raw**. The regions are contiguous and total to the file
    length, which is what makes the round trip meaningful rather than a copy.
    """
    n = len(data)
    runs = {r["offset"]: len(r["values"]) for r in index_runs(data, max_index=max_index, min_run=min_run)}
    out = []
    i = 0
    while i < n:
        if i in runs:
            length = runs[i] * 2
            out.append({"kind": "indices", "offset": i, "length": length})
            i += length
            continue
        if i + 4 <= n and _is_float_word(data, i):
            start = i
            while i + 4 <= n and _is_float_word(data, i) and i not in runs:
                i += 4
            length = i - start
            out.append({"kind": "floats", "offset": start, "length": length})
            continue
        start = i
        i += 1
        while i < n and i not in runs and not (i + 4 <= n and _is_float_word(data, i)):
            i += 1
        out.append({"kind": "raw", "offset": start, "length": i - start})
    return out


def roundtrip(data: bytes, **kw) -> tuple[bytes, dict]:
    """Re-emit every region from its parsed form; returns (rebuilt bytes, per-kind byte totals)."""
    parts, totals = [], {"indices": 0, "floats": 0, "raw": 0}
    for region in regions(data, **kw):
        chunk = data[region["offset"]:region["offset"] + region["length"]]
        kind = region["kind"]
        totals[kind] += len(chunk)
        if kind == "indices":
            values = struct.unpack(">%dH" % (len(chunk) // 2), chunk)
            parts.append(b"".join(struct.pack(">H", v) for v in values))
        elif kind == "floats":
            values = struct.unpack(">%df" % (len(chunk) // 4), chunk)
            parts.append(b"".join(struct.pack(">f", v) for v in values))
        else:
            parts.append(chunk)
    return b"".join(parts), totals


# ---------------------------------------------------------------- vertex arrays
def vertex_runs(data: bytes, *, limit: float = 10000.0, min_run: int = 64) -> list[dict]:
    """Runs of three consecutive plausible floats (|v| <= limit, finite) at 12-byte positions.

    The fmt2 header's own offset (0x3834) is *not* a contiguous vertex array: only 76 float triples are contiguous
    there before non-float data. The real arrays are found by this signature - the longest is **1,313 vertices at
    0x527f4**, then **1,041 at 0x90078**, and the index runs' maximum (1,036) fits the 1,041 one exactly. Returns
    [{offset, count}] largest first.
    """
    import numpy as np
    words = np.frombuffer(data[: len(data) // 4 * 4], dtype=">f4")
    ok = np.isfinite(words) & (np.abs(words) <= limit)
    n = (len(words) // 3) * 3
    slots = ok[0:n:3] & ok[1:n:3] & ok[2:n:3]
    edges = np.concatenate(([-1], np.flatnonzero(~slots), [len(slots)]))
    lens = np.diff(edges) - 1
    runs = []
    for i, length in enumerate(lens):
        if length >= min_run:
            runs.append({"offset": int(edges[i] + 1) * 12, "count": int(length)})
    return sorted(runs, key=lambda r: -r["count"])


def vertices(data: bytes, run: dict) -> list[tuple]:
    """The (x, y, z) points of a run returned by :func:`vertex_runs`."""
    return [struct.unpack_from(">3f", data, run["offset"] + 12 * i) for i in range(run["count"])]
