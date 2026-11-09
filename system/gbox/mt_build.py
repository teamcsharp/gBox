"""Build a modified MT Framework archive: decode a model, change one part's geometry, repack, verify.

This is the end-to-end writer as a library call, so the same path serves a script, a test, the lab and a future panel:

    build_modified_arc(source_arc_bytes, entry_name, part_index, transform) -> bytes

`transform` maps a list of model-space points to new points, which keeps the geometry change explicit and testable. The
result is re-parsed and its part count, validity and per-part sizes are checked before it is returned - a caller should
never receive a container that does not describe itself.

Measured on `uEm6c.arc`: a 14-part majini model with part 0 at 55 vertices in format 0x1580b60c; shrinking that part to
half size produced a model of the same byte length that still validates, whose part 0 width went 0.52 -> 0.26 cm, and an
archive that re-reads with all 68 entries intact.
"""
from __future__ import annotations

import zlib

from . import mt_arc, mt_model, mtf_author


class BuildError(ValueError):
    """The archive or model cannot be rebuilt as asked."""


def find_model(arc: mt_arc.Arc, entry_name: str | None = None) -> tuple[int, str, bytes]:
    """The first entry whose decompressed payload is a MOD container: (index, name, raw model bytes)."""
    for index, entry in enumerate(arc.entries):
        if entry_name and entry.name.rsplit("\\", 1)[-1] != entry_name:
            continue
        raw = b""
        for window in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                raw = zlib.decompress(entry.data, window)
                break
            except zlib.error:
                continue
        if raw[:4] == mt_model.MOD_MAGIC:
            return index, entry.name, raw
    raise BuildError("no MOD model found in this archive")


def build_modified_arc(source: bytes, entry_name: str | None, part_index: int, transform) -> tuple[bytes, dict]:
    """Replace one part's geometry with `transform(points)` and return a whole new archive plus a receipt."""
    arc = mt_arc.parse(source)
    index, name, raw = find_model(arc, entry_name)
    model = mt_model.parse_mod(raw)
    if model.variant != "model":
        raise BuildError(f"{name} is the {model.variant} variant, which cannot be rebuilt yet")
    bounds = model.bounds()
    if not bounds:
        raise BuildError(f"{name} carries no bounding box to quantise against")
    record = model.meshes()[part_index]
    points = model.positions(part_index)
    if len(points) != record["vertex_count"]:
        raise BuildError(f"part {part_index}'s positions do not decode ({len(points)} of {record['vertex_count']})")
    moved = list(transform(list(points)))
    if len(moved) != len(points):
        raise BuildError("the transform changed the vertex count")
    data, _ = model.mesh_bytes(part_index)
    normals = model.normals(part_index)
    uvs = model.uvs(part_index)
    bones = model.bone_ids(part_index)
    weights = mt_model.decode_weights(data, record["vertex_format"], record["vertex_count"], record["vertex_stride"])
    vertices = [{"position": moved[i], "bounds": bounds,
                 **({"normal": normals[i]} if normals else {}),
                 **({"uv": uvs[i]} if uvs else {}),
                 **({"bones": bones[i]} if bones else {}),
                 **({"weights": weights[i]} if weights else {})} for i in range(len(moved))]
    packed = model.pack_part(part_index, vertices)
    rebuilt = mt_model.replace_part(raw, part_index, packed, len(moved), record["vertex_format"],
                                    record["vertex_stride"])
    check = mt_model.parse_mod(rebuilt)
    if not check.split_valid() or len(check.meshes()) != len(model.meshes()):
        raise BuildError("the rebuilt model does not describe itself")
    # MRL and MOD entries can have the same name. Replace the exact MOD index, and use the measured level-6 stream.
    new_arc = mtf_author.replace_archive_model(source, index, rebuilt)
    again = mt_arc.parse(new_arc)
    if len(again.entries) != len(arc.entries):
        raise BuildError("the rebuilt archive lost entries")
    return new_arc, {"entry": name, "part": part_index, "vertex_format": record["vertex_format"],
                     "stride": record["vertex_stride"], "vertices": len(moved),
                     "model_bytes": len(rebuilt), "arc_bytes": len(new_arc),
                     "entries": len(again.entries), "parts": len(check.meshes())}
