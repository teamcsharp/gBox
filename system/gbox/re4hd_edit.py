"""`hide_materials` as a route-level operation: the software half of "remove clothes".

The MercMode sidebar asks for four things - remove clothes, swap clothes, character↔zombie, zombies→cast. All four reduce to
editing a model pack in place with the topology kept, so the reusable piece is one operation with a target: a pack, a slot and
a set of materials (or a donor rig to morph toward). This module holds the operation itself, independent of the HTTP layer and of
the emulator, so it can be tested against a real pack and reused by a route, a job or an agent.

Nothing here guesses: a material index out of range is refused, a mesh without materials is refused, and the report says what it
did - which materials, how many vertices, whether the triangle table moved.
"""
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

from . import re4gc_inventory as INV
from . import re4hd_hide as HIDE
from . import re4hd_models as MODELS


class EditError(ValueError):
    """The pack cannot take the edit the caller asked for; the message says which part and why."""


@dataclasses.dataclass
class EditReport:
    pack: str
    slot: int
    operation: str
    vertices: int
    triangles: int
    before_sha256: str
    after_sha256: str
    detail: dict

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def material_census(pack_bytes: bytes, slot: int) -> list[dict]:
    """Every material of one slot, with the vertex and triangle span it owns - the list a picker shows."""
    mesh, _info = _slot_mesh(pack_bytes, slot)
    materials = []
    start = 0
    for mat in mesh.mats:
        end = start + int(mat.triangle_count)
        materials.append({"material": int(mat.index), "triangles": int(mat.triangle_count),
                          "triangle_start": start, "triangle_end": end})
        start = end
    return materials


def _slot_mesh(pack_bytes: bytes, slot: int):
    try:
        slots = INV.bin_slots(pack_bytes, endian="<")
    except (ValueError, TypeError) as exc:
        raise EditError(f"this is not a pack with a BIN table: {exc}") from exc
    if not slots:
        raise EditError("this pack holds no BIN slot")
    if not 0 <= slot < len(slots):
        raise EditError(f"slot {slot} is out of range (this pack holds {len(slots)})")
    entry = slots[slot]
    body = pack_bytes[entry["offset"]:entry["offset"] + entry["size"]]
    try:
        mesh = MODELS.bin_read(body)
    except MODELS.BINError as exc:
        raise EditError(f"slot {slot} is not a decodable BIN: {exc}") from exc
    return mesh, entry


def edit_pack(pack_bytes: bytes, slot: int, *, hide: list[int] | None = None,
              scale: tuple[list[int], float] | None = None, donor: bytes | None = None,
              pack_name: str = "", hide_mode: str = "collapse") -> tuple[bytes, EditReport]:
    """One in-place edit of one slot: hide materials, scale materials, or morph the mesh toward a donor rig.

    Exactly one operation per call, so the report is unambiguous and a build can name what it did. The slot's own size is
    preserved - the rule that this engine draws in place and ignores rebuilt meshes.
    """
    if not hide and not scale and donor is None:
        raise EditError("one of hide, scale or donor is required")
    mesh, entry = _slot_mesh(pack_bytes, slot)
    before = _sha(pack_bytes)
    if mesh.mats is None or not mesh.mats:
        raise EditError(f"slot {slot} carries no material records, so there is nothing to name")
    chosen = 0
    if hide:
        report = HIDE.hide_materials(mesh, list(hide), mode=hide_mode)
        chosen, operation, detail = report["vertices_changed"], "hide", report
    elif scale:
        indices, factor = scale
        report = HIDE.scale_materials(mesh, list(indices), factor=factor)
        chosen, operation, detail = report["vertices_changed"], "scale", report
    elif donor is not None:
        donor_mesh = MODELS.bin_read(donor) if isinstance(donor, (bytes, bytearray)) else donor
        if not donor_mesh.bones:
            raise EditError("the donor BIN has no bone table, so proportions cannot be transferred")
        moved = MODELS.morph_bones_to(mesh, donor_mesh)
        mesh.pos = moved
        chosen, operation, detail = len(moved), "morph_bones", {"vertices": len(moved)}
    if not chosen:
        raise EditError(f"the {operation} touched no vertices")
    replacement = MODELS.pad_to(MODELS.bin_write(mesh), entry["size"])
    if len(replacement) != entry["size"]:
        raise EditError(f"the rewritten slot is {len(replacement)} bytes, not the slot's {entry['size']}")
    out = INV.pack_patch(pack_bytes, slot, replacement, endian="<")
    report = EditReport(pack=pack_name or "", slot=slot, operation=operation, vertices=chosen,
                        triangles=len(mesh.tris) if mesh.tris is not None else 0,
                        before_sha256=before, after_sha256=_sha(out), detail=detail)
    return out, report


def edit_pack_file(path: Path, slot: int, *, pack_name: str = "", **kwargs) -> tuple[bytes, EditReport]:
    data = Path(path).read_bytes()
    return edit_pack(data, slot, pack_name=pack_name or Path(path).name, **kwargs)
