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
    """Triangle count, reading each run as a list of index triples (the reading that matches `c.rel`)."""
    return sum(len(run["values"]) // 3 for run in index_runs(data, **kw))


def collision_triangles(collision: bytes, record: int = COLLISION_RECORD) -> int:
    """The collision mesh's triangle count from its footprint."""
    return len(collision) // record


def describe(nrel: bytes, crel: bytes) -> dict:
    runs = index_runs(nrel)
    total = sum(len(r["values"]) for r in runs)
    tris = total // 3
    coll = collision_triangles(crel)
    return {"runs": len(runs), "index_values": total, "triangles": tris,
            "collision_bytes": len(crel), "collision_triangles": coll,
            "ratio": round(tris / coll, 3) if coll else None}
