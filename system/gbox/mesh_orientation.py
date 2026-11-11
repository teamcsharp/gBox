"""Outward orientation of a donor surface: winding and normals measured against the geometry, then repaired.

The RE4 / RE5 / RE6 Switch writers author a donor in the game's own convention - counter-clockwise fronts seen from
outside, stored normals that agree with the winding (measured on the native RE6 body records: winding vs normals
0.99-1.0, 70-100% of the area facing away from its part's centre). The game culls back faces and lights with the
stored normals, so a donor that reaches the writer inside-out is drawn inside-out: the lit side dark, the far side
and the inside of the body showing through, faces and hair inverted.

Several of the library's exporters do write inside-out surfaces, and their materials say ``doubleSided`` so a glTF
viewer (and the collection previews) never shows it. Measured 2026-11-10 on the library entries the live builds
used (`mtf_materials.source_mesh` output; outward = area share of triangles facing away from their part's centre):

* ``gbox ff7_models`` (every FF7 battle and field model): winding against the outside, and the stored normals - face
  normals of that same winding - agree with it: outward 3-6%, every part a negative volume. Aerith (``ff7_earith``,
  RE4 Wesker / pl0d; ``ff7_earith_field``; RE5 uEm92) is one.
* ``gbox.stranglehold_models``: the same, normals included (outward 13-24%).
* ``gbox melee_models`` Smash Melee fighters and ``gbox soulcalibur2``: the winding is inside-out but the stored
  normals point outward (winding vs normals 0-3%: the RE5 survey's "cw" donors). A Melee model without normals (the
  Fighting Wire Frames) gets its normals from the winding, so it is fully inside-out.

A winding check against the stored normals cannot see the first two (they agree, both wrong), which is why nothing
caught them. `orient` decides from the geometry: each welded part's signed volume about its own centre and its
outward area share, summed over the model. One exporter writes one convention, so the decision is made for the
whole model (a mouth or eye cavity, a coat lining, is legitimately inward on a correct model and is never flipped
alone); a model the geometry cannot settle (open cards, a single quad) is left as it came. Then the stored normals
are made to agree with the oriented winding: they are negated when most of them point against it.
"""
from __future__ import annotations

import numpy as np

#: Area / volume share facing outward at or under which a model is inside-out, and at or over which it is outward.
#: Measured: inside-out exporters 0.0-0.27, every correct donor of the live builds 0.73-0.99.
INSIDE_OUT_SHARE = 0.4
OUTWARD_SHARE = 0.6
#: A part's centre test counts a triangle only when its facing is clear of the centre by this share of its own size.
_EPS = 1e-9


def _components(corners: np.ndarray, count: int) -> np.ndarray:
    """Component id per welded vertex (hooking + pointer jumping over the triangle edges, numpy only)."""
    parent = np.arange(count)
    edges = np.concatenate([corners[:, [0, 1]], corners[:, [1, 2]]])
    while True:
        a, b = parent[edges[:, 0]], parent[edges[:, 1]]
        changed = a != b
        if not changed.any():
            return parent
        low, high = np.minimum(a, b)[changed], np.maximum(a, b)[changed]
        np.minimum.at(parent, high, low)
        while True:
            jumped = parent[parent]
            if np.array_equal(jumped, parent):
                break
            parent = jumped


def weld(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Per-triangle part id: triangles that share a corner position (to 1e-6 of the model size) are one part."""
    points = np.asarray(points, float)
    extent = float(np.ptp(points, axis=0).max()) if len(points) else 0.0
    step = max(extent * 1e-6, 1e-12)
    keys = np.round(points / step).astype(np.int64)
    _, welded = np.unique(keys, axis=0, return_inverse=True)
    welded = np.asarray(welded).reshape(-1)
    corners = welded[np.asarray(triangles, np.int64)]
    parent = _components(corners, int(welded.max()) + 1 if len(welded) else 0)
    return parent[corners[:, 0]]


def measure(points, triangles, normals=None) -> dict:
    """How a surface faces: outward area and volume shares over its welded parts, and its normals against its winding.

    ``normals`` (per vertex, NaN rows allowed) adds ``normals_against_winding``: the area share of triangles whose
    summed corner normals point against their geometric normal. ``verdict`` is 'outward', 'inside_out' or 'unclear'.
    """
    P = np.asarray(points, float)
    F = np.asarray(triangles, np.int64).reshape(-1, 3)
    out = {"triangles": int(len(F)), "parts": 0, "outward_area_share": None, "outward_volume_share": None,
           "normals_against_winding": None, "verdict": "unclear"}
    if not len(F):
        return out
    a, b, c = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    geometric = np.cross(b - a, c - a)
    area = np.linalg.norm(geometric, axis=1) / 2
    centre = (a + b + c) / 3
    part = weld(P, F)
    labels, part_index = np.unique(part, return_inverse=True)
    out["parts"] = int(len(labels))
    weight = np.bincount(part_index, area, len(labels))
    part_centre = np.stack([np.bincount(part_index, centre[:, k] * area, len(labels)) for k in range(3)], 1)
    part_centre /= np.maximum(weight, 1e-300)[:, None]
    offset = centre - part_centre[part_index]
    # signed volume of each part about its own centre (translation-free, so an open part still has a sign)
    ra, rb, rc = a - part_centre[part_index], b - part_centre[part_index], c - part_centre[part_index]
    volume = np.bincount(part_index, np.einsum("ij,ij->i", ra, np.cross(rb, rc)) / 6, len(labels))
    facing = np.einsum("ij,ij->i", geometric, offset)
    clear = np.abs(facing) > _EPS * np.linalg.norm(geometric, axis=1) * np.linalg.norm(offset, axis=1) + 1e-300
    outward_area, inward_area = float(area[clear & (facing > 0)].sum()), float(area[clear & (facing < 0)].sum())
    outward_volume, inward_volume = float(volume[volume > 0].sum()), float(-volume[volume < 0].sum())
    if outward_area + inward_area > 0:
        out["outward_area_share"] = round(outward_area / (outward_area + inward_area), 4)
    if outward_volume + inward_volume > 0:
        out["outward_volume_share"] = round(outward_volume / (outward_volume + inward_volume), 4)
    shares = (out["outward_area_share"], out["outward_volume_share"])
    if None not in shares:
        if max(shares) <= INSIDE_OUT_SHARE:
            out["verdict"] = "inside_out"
        elif min(shares) >= OUTWARD_SHARE:
            out["verdict"] = "outward"
    if normals is not None:
        N = np.asarray(normals, float)
        summed = N[F].sum(1)
        valid = np.isfinite(summed).all(1) & (area > 0)
        if valid.any():
            against = np.einsum("ij,ij->i", summed[valid], geometric[valid]) < 0
            out["normals_against_winding"] = round(float(area[valid][against].sum() / area[valid].sum()), 4)
    return out


def orient(points, triangles, normals=None) -> tuple[np.ndarray, np.ndarray | None, dict]:
    """(triangles, normals, report) with the winding facing outward and the normals agreeing with it.

    An inside-out model has every triangle turned (a, b, c) -> (a, c, b); a model the geometry cannot settle keeps
    its winding. Then, when most stored normals point against the (oriented) winding, every stored normal is negated
    (NaN rows stay NaN, so a caller's face-normal fallback still applies). Positions are never changed.
    """
    F = np.asarray(triangles, np.int64).reshape(-1, 3)
    N = None if normals is None else np.asarray(normals, float).copy()
    before = measure(points, F, N)
    turned = before["verdict"] == "inside_out"
    if turned:
        F = F[:, [0, 2, 1]]
    against = before["normals_against_winding"]
    if against is not None and turned:
        against = round(1 - against, 4)
    # normals are judged against the winding only once the winding is known to face outward (or was turned so)
    negated = bool(N is not None and against is not None and against > 0.5 and before["verdict"] != "unclear")
    if negated:
        N = -N
    report = {"before": before, "winding_turned": turned, "normals_negated": negated,
              "verdict": "turned" if turned else ("kept" if before["verdict"] == "outward" else "unclear, kept")}
    return F, N, report


def winding_normals(points, triangles) -> np.ndarray:
    """Area-weighted vertex normals of the winding (for a source without a NORMAL attribute)."""
    P = np.asarray(points, float)
    F = np.asarray(triangles, np.int64).reshape(-1, 3)
    geometric = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    out = np.zeros_like(P)
    for k in range(3):
        np.add.at(out, F[:, k], geometric)
    length = np.linalg.norm(out, axis=1)
    out[length > 1e-300] /= length[length > 1e-300, None]
    out[length <= 1e-300] = (0.0, 1.0, 0.0)
    return out
