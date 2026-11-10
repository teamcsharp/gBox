"""P6a proof: the room-local -> world offset of PSO's city placement records.

The map writer (`pso_map_write`) can move any placement record at the byte level and the
edited disc boots, but the moved object has never been *seen* to move. The reason is in
`docs/research/pso-gc-pioneer2-rooms.md`: placement records are **room-local** while live
entities report **world** positions, and no record sits at any entity's world position.

This module closes that gap with the hand-off's six-pairwise-distances method
(`docs/PSO-HANDOFF-2026-11-10.md`): take entities whose world positions are known from live
reads, compute the six pairwise distances of the quadruple (a translation preserves them),
find the four placement records with the same distance multiset, solve which record is which
entity, and read the offset off the pair differences. The offset is only accepted when one
constant translation explains every pair to within a tolerance.

Verified on the owned GPOE8P image: the four room-10 doors (world positions from live
sessions, `docs/research/pso-gc-pioneer2-rooms.md`) match records 17/18/20/21 of
``map_city00_00o.dat`` with a best-subset error of 0.67 units (next candidate 14.0) and a
single constant offset of (228.13, 291.25) with max per-pair deviation 0.45. The same
records appear in the ``_c1`` and ``_d`` layout variants with identical kinds
(0x2000046..0x2000049), which identifies the door kind range for future edits.
"""
from __future__ import annotations

import itertools
import math

from . import pso_setdata

# The four room-10 TObjCityDoor_* entities, world (x, z) as read live and recorded in
# docs/research/pso-gc-pioneer2-rooms.md (rounds 22-29).
ROOM10_DOORS = {
    "Guild": (185.0, 173.0),
    "Warp": (254.0, 25.0),
    "Med": (194.0, -93.0),
    "Shop": (-165.0, 148.0),
}

# The matching record indices/kinds on the owned image (map_city00_00o.dat), for reference.
ROOM10_DOOR_RECORDS = {17: 0x2000049, 18: 0x2000046, 20: 0x2000047, 21: 0x2000048}


def _pair_distances(points: list[tuple[float, float]]) -> list[float]:
    out = []
    for a, b in itertools.combinations(range(len(points)), 2):
        out.append(math.hypot(points[a][0] - points[b][0], points[a][1] - points[b][1]))
    return sorted(out)


def match_anchor_subset(
    recs: list[dict],
    observed: dict[str, tuple[float, float]],
    max_subset_error: float = 3.0,
) -> list[dict]:
    """Rank every record subset of the anchor size by pairwise-distance fit.

    Only subsets whose sorted pairwise distance vector matches the observed one to within
    ``max_subset_error`` are returned (best first). Each hit is
    ``{"indices", "subset_error", "kinds"}``.
    """
    obs_pts = list(observed.values())
    n = len(obs_pts)
    target = _pair_distances(obs_pts)
    hits = []
    for combo in itertools.combinations(range(len(recs)), n):
        pts = [(recs[i]["x"], recs[i]["z"]) for i in combo]
        err = max(abs(a - b) for a, b in zip(_pair_distances(pts), target))
        if err <= max_subset_error:
            hits.append({
                "indices": combo,
                "subset_error": round(err, 3),
                "kinds": [recs[i]["kind"] for i in combo],
            })
    hits.sort(key=lambda h: h["subset_error"])
    return hits


def solve_offset(
    recs: list[dict],
    indices: tuple[int, ...],
    observed: dict[str, tuple[float, float]],
    max_deviation: float = 2.0,
) -> dict | None:
    """Solve which record is which observed entity, and the single translation between them.

    Returns ``{"names": {entity: record index}, "offset": (dx, dz), "max_deviation"}``
    when one constant translation explains the whole assignment within
    ``max_deviation`` world units, else ``None``.
    """
    names = list(observed)
    obs_pts = [observed[n] for n in names]
    best: tuple[float, tuple[int, ...], float, float] | None = None
    for perm in itertools.permutations(indices):
        offs = [
            (obs_pts[i][0] - recs[ri]["x"], obs_pts[i][1] - recs[ri]["z"])
            for i, ri in enumerate(perm)
        ]
        ox = sum(o[0] for o in offs) / len(offs)
        oz = sum(o[1] for o in offs) / len(offs)
        dev = max(math.hypot(o[0] - ox, o[1] - oz) for o in offs)
        if best is None or dev < best[0]:
            best = (dev, perm, ox, oz)
    if best is None:  # empty indices: nothing to solve
        return None
    dev, perm, ox, oz = best
    if dev > max_deviation:
        return None
    return {
        "names": {name: ri for name, ri in zip(names, perm)},
        "offset": (round(ox, 2), round(oz, 2)),
        "max_deviation": round(dev, 3),
    }


def room_offset(disc, set_name: str, observed: dict[str, tuple[float, float]] | None = None,
                max_subset_error: float = 3.0, max_deviation: float = 2.0) -> dict:
    """The room-local -> world offset of one placement set from live-observed anchors.

    Reads the set off the disc, finds the anchor subset, solves the assignment and returns
    ``{"set", "indices", "kinds", "names", "offset", "max_deviation", "subset_error"}``.
    Raises ``ValueError`` when no subset fits (the anchors are not from this set) or no
    single translation explains the best subset.
    """
    from . import pso_map_write as W

    observed = observed or ROOM10_DOORS
    b, _ = W.read_set(disc, set_name)
    recs = pso_setdata.records(b)
    hits = match_anchor_subset(recs, observed, max_subset_error)
    if not hits:
        raise ValueError(f"no record subset of {set_name} matches the anchors")
    hit = hits[0]
    solved = solve_offset(recs, hit["indices"], observed, max_deviation)
    if solved is None:
        raise ValueError(f"best subset of {set_name} fits but no single translation explains it")
    return {
        "set": set_name,
        "indices": list(hit["indices"]),
        "kinds": hit["kinds"],
        "subset_error": hit["subset_error"],
        **solved,
    }


def world_of(rec: dict, offset: tuple[float, float]) -> tuple[float, float]:
    """A record's world (x, z) after applying a solved offset."""
    return (rec["x"] + offset[0], rec["z"] + offset[1])


def record_at(recs: list[dict], x: float, z: float, offset: tuple[float, float],
              tolerance: float = 5.0) -> dict | None:
    """The record whose offset position is nearest a world point, within tolerance."""
    best, best_d = None, tolerance
    for rec in recs:
        wx, wz = world_of(rec, offset)
        d = math.hypot(wx - x, wz - z)
        if d <= best_d:
            best, best_d = rec, d
    return best
