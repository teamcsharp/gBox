"""Per-band affine transfer: scale each bone's region to the donor's proportions.

The measured rule from rounds 86-99: **only edits that stay self-consistent AND move parts relative to each other are drawn**. A
coherent projection preserves the silhouette (invisible), a global projection scatters it (drawn as shards), a material scale moves a
part away from the rest (drawn). This is the fourth variant and the first that is both: each band - the vertices a bone owns - is scaled
about its own centroid to match the donor band's per-axis extent, so a limb gets the donor's limb proportions and a body the donor's
body proportions, with no vertex ever leaving its own region.

Per-axis scale, not a uniform one, because that is what carries a *shape*: a slab donor is thin on one axis and wide on two, and the
transfer has to flatten the same axis or it changes nothing - which is exactly what the previous three variants did.
"""
from __future__ import annotations

import numpy as np

from .re4hd_coherent import _bone_by_rank, _region_of
from .re4hd_models import BINError, Bin, bin_read, bin_write

MIN_SCALE, MAX_SCALE = 0.15, 6.0      # a band may not collapse to a point or explode; beyond this the donor is not a body


def _height_band(points: np.ndarray, bands: int) -> np.ndarray:
    """Band by the up axis (z): the lowest quarter of the model is band 0, the top the last band."""
    if len(points) == 0:
        return np.zeros(0, np.int64)
    z = points[:, 2]
    low, high = np.percentile(z, [1, 99])
    span = max(float(high - low), 1e-6)
    return np.clip(((z - low) / span * bands).astype(np.int64), 0, bands - 1)


def _extent(points: np.ndarray) -> np.ndarray:
    """Robust per-axis extent: the 5th..95th percentile, so one stray vertex cannot set a band's scale."""
    if len(points) < 2:
        return np.zeros(points.shape[1] if points.ndim == 2 else 3)
    low, high = np.percentile(points, [5, 95], axis=0)
    return np.maximum(high - low, 1e-6)


def auto_blend(template, donor, *, bands: int = 6, align: bool = True,
               limits: tuple[float, float] = (1.0 / 3.0, 3.0)) -> float:
    """The largest blend whose every band's effective scale stays inside `limits`.

    Measured across rounds 100-105: one blend loads on one target and hangs the stage on another, because a band's factor depends on
    how small that band is. Choosing the strength from the data removes a variable from every experiment, and a factor outside
    [1/3, 3] is the class of edit that stops a stage loading.
    """
    low_limit, high_limit = limits
    tmpl = template if isinstance(template, Bin) else bin_read(template)
    src = donor if isinstance(donor, Bin) else bin_read(donor)
    if tmpl.pos is None or src.pos is None:
        raise BINError("auto_blend needs positions on both sides")
    target = np.asarray(tmpl.pos, np.float64)
    donor_pos = np.asarray(src.pos, np.float64).copy()
    if align:
        d_lo, d_hi = donor_pos.min(0), donor_pos.max(0)
        t_lo, t_hi = target.min(0), target.max(0)
        d_ext = np.where((d_hi - d_lo) < 1e-9, 1.0, d_hi - d_lo)
        t_ext = np.where((t_hi - t_lo) < 1e-9, 1.0, t_hi - t_lo)
        scale = float(np.mean(t_ext / d_ext))
        donor_pos = (donor_pos - (d_lo + d_hi) / 2.0) * scale + (t_lo + t_hi) / 2.0
    t_ranks, d_ranks = _bone_by_rank(tmpl), _bone_by_rank(src)
    t_band = _region_of(t_ranks, len(tmpl.bones or []), bands) if t_ranks is not None else _height_band(target, bands)
    d_band = _region_of(d_ranks, len(src.bones or []), bands) if d_ranks is not None else _height_band(donor_pos, bands)
    best = 1.0
    for band in range(bands):
        mine = np.where(t_band == band)[0]
        theirs = np.where(d_band == band)[0]
        if mine.size < 4 or theirs.size < 4:
            continue
        ratio = np.clip(_extent(donor_pos[theirs]) / _extent(target[mine]), MIN_SCALE, MAX_SCALE)
        for value in ratio:
            if value >= 1.0 + 1e-9:
                best = min(best, (high_limit - 1.0) / (value - 1.0))
            elif value <= 1.0 - 1e-9:
                best = min(best, (low_limit - 1.0) / (value - 1.0))
    return float(np.clip(best, 0.0, 1.0))


def band_affine(template, donor, *, bands: int = 6, align: bool = True, blend: float = 1.0) -> np.ndarray:
    """Each template band scaled about its centroid to the donor band's proportions. Returns (positions, report).

    `blend` mixes between the template (0) and the donor's proportions (1), so a caller can ask for a gentler result without a new
    function. A band with no donor geometry keeps the template's own proportions rather than being dropped.
    """
    tmpl = template if isinstance(template, Bin) else bin_read(template)
    src = donor if isinstance(donor, Bin) else bin_read(donor)
    if tmpl.pos is None or src.pos is None:
        raise BINError("band_affine needs positions on both sides")
    target = np.asarray(tmpl.pos, np.float64).copy()
    donor_pos = np.asarray(src.pos, np.float64).copy()
    if align:
        d_lo, d_hi = donor_pos.min(0), donor_pos.max(0)
        t_lo, t_hi = target.min(0), target.max(0)
        d_ext = np.where((d_hi - d_lo) < 1e-9, 1.0, d_hi - d_lo)
        t_ext = np.where((t_hi - t_lo) < 1e-9, 1.0, t_hi - t_lo)
        scale = float(np.mean(t_ext / d_ext))
        donor_pos = (donor_pos - (d_lo + d_hi) / 2.0) * scale + (t_lo + t_hi) / 2.0

    t_ranks, d_ranks = _bone_by_rank(tmpl), _bone_by_rank(src)
    if t_ranks is not None and d_ranks is not None:
        t_band = _region_of(t_ranks, len(tmpl.bones or []), bands)
        d_band = _region_of(d_ranks, len(src.bones or []), bands)
    else:
        # A donor that is only a mesh - a triangle soup from a .glb, say - has no weights to band by. Band both sides by
        # HEIGHT instead: feet at band 0, head at the last band. It is coarse, but it makes any extracted model a usable
        # donor, which is the whole point of the collection.
        t_band = _height_band(target, bands)
        d_band = _height_band(donor_pos, bands)

    if blend is None:                      # choose a strength the target's own bands can take (see auto_blend)
        blend = auto_blend(tmpl, src, bands=bands, align=False)
    out = target.copy()
    moved = []
    for band in range(bands):
        mine = np.where(t_band == band)[0]
        theirs = np.where(d_band == band)[0]
        if mine.size < 4 or theirs.size < 4:
            continue
        c_mine = target[mine].mean(axis=0)
        c_theirs = donor_pos[theirs].mean(axis=0)
        e_mine = _extent(target[mine])
        e_theirs = _extent(donor_pos[theirs])
        ratio = np.clip(e_theirs / e_mine, MIN_SCALE, MAX_SCALE)
        if not np.isfinite(ratio).all():
            continue
        factor = 1.0 + (ratio - 1.0) * float(blend)
        out[mine] = c_mine + (target[mine] - c_mine) * factor + (c_theirs - c_mine) * float(blend) * 0.5
        moved.append({"band": band, "vertices": int(mine.size), "donor_vertices": int(theirs.size),
                      "extent_ratio": [round(float(v), 3) for v in ratio]})
    if not moved:
        raise BINError("no band had geometry on both sides, so nothing was transferred")
    return out, moved


def band_affine_bin(template, donor, *, bands: int = 6, align: bool = True, blend: float = 1.0) -> tuple[bytes, list]:
    """`band_affine` written back with the template's own layout, plus the per-band report."""
    import copy
    tmpl = template if isinstance(template, Bin) else bin_read(template)
    moved, report = band_affine(tmpl, donor, bands=bands, align=align, blend=blend)
    out = copy.copy(tmpl)
    out.pos = moved
    return bin_write(out, verify=True), report
