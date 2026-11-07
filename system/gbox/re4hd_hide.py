"""Hide a material's vertices without touching topology: the operation behind "remove clothes".

The Switch engine draws a slot's own topology and ignores a rebuilt mesh, so a part cannot be deleted - it has to be made
invisible **in place**. Collapsing a part's vertices onto that part's own centroid leaves every index, triangle and count
exactly as it was while the part becomes a point: zero area, drawn as nothing.

Which vertices belong to a material is measured, not assumed. `Mat.start` is a display-list offset, not an index, but the
material records' `triangle_count`s sum **exactly** to the mesh's triangle count (measured on `pl00.udas`: 2,519 = 2,519),
so the triangles are stored in material order and material *i* owns `triangle_count[i]` consecutive triangles starting at the
running total. Its vertices are the indices those triangles use.
"""
from __future__ import annotations

import numpy as np

from .re4hd_models import BINError


def material_triangle_span(mesh, index: int) -> tuple[int, int]:
    """[start, end) of the triangles one material owns, from the running total of the material records."""
    mats = list(getattr(mesh, "mats", None) or [])
    if not mats:
        raise BINError("this BIN has no material records")
    if not 0 <= index < len(mats):
        raise BINError(f"material {index} out of range (0..{len(mats) - 1})")
    start = sum(int(m.triangle_count) for m in mats[:index])
    count = int(mats[index].triangle_count)
    if count <= 0:
        raise BINError(f"material {index} owns no triangles")
    total = 0 if getattr(mesh, "tris", None) is None else len(mesh.tris)
    if start + count > total:
        raise BINError(f"material {index} spans triangles {start}..{start + count} but the mesh has {total}")
    return start, start + count


def material_vertex_indices(mesh, index: int) -> np.ndarray:
    """The unique vertex indices material `index` uses."""
    mesh_check(mesh)
    start, end = material_triangle_span(mesh, index)
    return np.unique(np.asarray(mesh.tris[start:end]).reshape(-1))


def mesh_check(mesh) -> None:
    if getattr(mesh, "tris", None) is None or len(mesh.tris) == 0:
        raise BINError("this BIN has no triangles")
    if getattr(mesh, "pos", None) is None or len(mesh.pos) == 0:
        raise BINError("this BIN has no positions to collapse")


def hide_materials(mesh, indices) -> dict:
    """Collapse each named material's vertices onto that material's centroid; topology is untouched.

    Returns a report {hidden: [{material, start, triangles, vertices, centroid}], vertices_changed,
    triangles_unchanged, n_verts, n_tris} so a caller can show what a build actually did.
    """
    mesh_check(mesh)
    before_tris = np.array(mesh.tris, copy=True)
    hidden, moved = [], 0
    for index in indices:
        start, end = material_triangle_span(mesh, index)
        verts = np.unique(np.asarray(mesh.tris[start:end]).reshape(-1))
        if verts.size == 0:
            raise BINError(f"material {index} references no vertices")
        centroid = mesh.pos[verts].mean(axis=0)
        mesh.pos[verts] = centroid
        hidden.append({"material": int(index), "start": start, "triangles": end - start,
                       "vertices": int(verts.size), "centroid": [round(float(v), 4) for v in centroid]})
        moved += int(verts.size)
    return {"hidden": hidden, "vertices_changed": moved,
            "triangles_unchanged": bool(np.array_equal(before_tris, mesh.tris)),
            "n_verts": len(mesh.pos), "n_tris": len(mesh.tris)}
