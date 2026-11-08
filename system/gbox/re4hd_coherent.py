"""A coherent surface morph: each vertex snaps to the donor's surface *near its own bone*.

Two earlier results fix the design. Bone transfer keeps every vertex with its own bone but preserves the silhouette (measured
across 22 player packs: no visible change). Surface transfer changes the shape but lets a left-arm vertex land on the right leg,
which is drawn as shards (measured on the player). This combines them: the bone decides *where* the vertex may land, so the arm
lands on the arm and the head on the head, and the surface decides the shape within that region.

A vertex with no usable bone region falls back to the global nearest surface, so no vertex is ever left unmoved.
"""
from __future__ import annotations

import numpy as np

from .re4hd_models import BINError, Bin, _closest_on_triangles, _dominant_bone, bin_read


def _bone_by_rank(mesh: Bin) -> np.ndarray:
    """Each vertex's bone expressed as a *rank* in hierarchy order, so two different skeletons can be compared."""
    dominant = _dominant_bone(mesh)
    if dominant is None:
        return None
    order = {bone["id"]: index for index, bone in enumerate(mesh.bones or [])}
    ranks = np.full(len(dominant), -1, np.int64)
    for vertex, bone_id in enumerate(dominant):
        ranks[vertex] = order.get(int(bone_id), -1)
    return ranks


def _region_of(ranks: np.ndarray, count: int, bands: int) -> np.ndarray:
    """Collapse bone ranks into a few body bands.

    Exact bone ids do not correspond between two rigs, but *position in the hierarchy* does approximately: the first bones are
    the root and spine, the middle ones limbs, the last ones extremities. Bands make that robust to different joint counts.
    """
    out = np.full(len(ranks), 0, np.int64)
    valid = ranks >= 0
    if count <= 0 or not valid.any():
        return out
    # The span is the ranks actually present, not the bone-table length: a donor whose joints were bucketed into a few weight
    # records (a converted .glb, say) has ranks 0..3 over a 62-bone table, and using the table length would put every vertex in
    # band 0 and make the transfer a no-op.
    span = int(ranks[valid].max()) + 1
    out[valid] = np.minimum((ranks[valid] * bands) // max(span, 1), bands - 1)
    return out


def coherent_surface(template, donor, *, bands: int = 6, align: bool = True) -> np.ndarray:
    """The template's vertices moved onto the donor's surface, restricted to each vertex's own body band."""
    tmpl = template if isinstance(template, Bin) else bin_read(template)
    src = donor if isinstance(donor, Bin) else bin_read(donor)
    if tmpl.pos is None or src.pos is None or src.tris is None:
        raise BINError("coherent_surface needs positions on both sides and triangles on the donor")
    target = np.asarray(tmpl.pos, np.float64).copy()
    donor_pos = np.asarray(src.pos, np.float64).copy()
    if align:
        d_lo, d_hi = donor_pos.min(0), donor_pos.max(0)
        t_lo, t_hi = target.min(0), target.max(0)
        d_ext = np.where((d_hi - d_lo) < 1e-9, 1.0, d_hi - d_lo)
        t_ext = np.where((t_hi - t_lo) < 1e-9, 1.0, t_hi - t_lo)
        scale = float(np.mean(t_ext / d_ext))
        donor_pos = (donor_pos - (d_lo + d_hi) / 2.0) * scale + (t_lo + t_hi) / 2.0
    tri = np.asarray(src.tris, np.int64)

    t_ranks, s_ranks = _bone_by_rank(tmpl), _bone_by_rank(src)
    if t_ranks is None or s_ranks is None:
        moved, _ = _closest_on_triangles(target, donor_pos[tri[:, 0]], donor_pos[tri[:, 1]], donor_pos[tri[:, 2]])
        return moved
    t_band = _region_of(t_ranks, len(tmpl.bones or []), bands)
    s_band = _region_of(s_ranks, len(src.bones or []), bands)
    # a triangle belongs to the band most of its corners are in
    tri_band = np.stack([s_band[tri[:, 0]], s_band[tri[:, 1]], s_band[tri[:, 2]]])
    taken = np.array([np.bincount(col, minlength=bands).argmax() for col in tri_band.T], np.int64)

    moved = np.empty_like(target)
    fallback = []
    for band in range(bands):
        index = np.where(t_band == band)[0]
        if index.size == 0:
            continue
        faces = np.where(taken == band)[0]
        if faces.size == 0:                      # this band has no faces of its own: fall back to the whole donor
            fallback.append(band)
            continue
        sub = tri[faces]
        part, _ = _closest_on_triangles(target[index], donor_pos[sub[:, 0]], donor_pos[sub[:, 1]], donor_pos[sub[:, 2]])
        moved[index] = part
    if fallback:
        index = np.where(np.isin(t_band, fallback))[0]
        part, _ = _closest_on_triangles(target[index], donor_pos[tri[:, 0]], donor_pos[tri[:, 1]], donor_pos[tri[:, 2]])
        moved[index] = part
    missing = ~np.isfinite(moved).all(axis=1)
    if missing.any():
        part, _ = _closest_on_triangles(target[missing], donor_pos[tri[:, 0]], donor_pos[tri[:, 1]], donor_pos[tri[:, 2]])
        moved[missing] = part
    return moved


def coherent_surface_bin(template, donor, *, bands: int = 6, align: bool = True) -> bytes:
    """`coherent_surface` written back with the template's own layout (counts, primitive table, bones untouched)."""
    import copy
    tmpl = template if isinstance(template, Bin) else bin_read(template)
    out = copy.copy(tmpl)
    out.pos = coherent_surface(tmpl, donor, bands=bands, align=align)
    from .re4hd_models import bin_write
    return bin_write(out, verify=True)
