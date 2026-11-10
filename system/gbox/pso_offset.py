"""Solve a placement set's local -> world offset from live entity positions.

Every room's set lives in its own local space (round 59), so the offset has to be found per room rather than reused. The
method that solved `city00` was manual -- two co-op spawn points implied the constant and the rest confirmed it. This module
does it the general way: try every (record, entity) pair as a candidate translation, count how many records land on an
entity under it, and return the best. With `city00` and the lobby's live entities it returns the offset round 49 proved,
which is the check that makes the tool trustworthy.
"""
from __future__ import annotations

import math


class OffsetError(ValueError):
    """No translation explains the data well enough to trust."""


def _points(records, entities):
    recs = [(float(r["x"]), float(r["z"])) for r in records]
    ents = [(float(e["x"]), float(e["z"])) for e in entities]
    return recs, ents


def score(records, entities, offset, tolerance: float = 6.0) -> int:
    """How many records land within ``tolerance`` of some entity under this translation."""
    recs, ents = _points(records, entities)
    dx, dz = offset
    hits = 0
    for rx, rz in recs:
        wx, wz = rx + dx, rz + dz
        if any(math.hypot(ex - wx, ez - wz) <= tolerance for ex, ez in ents):
            hits += 1
    return hits


def solve(records, entities, *, tolerance: float = 6.0, min_fraction: float = 0.25) -> dict:
    """The translation matching the most records to entities.

    Returns ``{offset, matched, total, fraction}``. Raises when the best candidate explains less than ``min_fraction`` of
    the records -- a wrong answer is worse than an error, because it makes every later coordinate meaningless.
    """
    recs, ents = _points(records, entities)
    if not recs or not ents:
        raise OffsetError("need at least one record and one entity")
    best = None
    for rx, rz in recs:
        for ex, ez in ents:
            cand = (ex - rx, ez - rz)
            hits = score(records, entities, cand, tolerance)
            if best is None or hits > best["matched"]:
                best = {"offset": (round(cand[0], 3), round(cand[1], 3)), "matched": hits,
                        "total": len(recs), "fraction": hits / len(recs)}
                if hits == len(recs):
                    return best
    if best is None or best["fraction"] < min_fraction:
        raise OffsetError(f"best translation matched only {best['matched'] if best else 0} of {len(recs)} records")
    return best
