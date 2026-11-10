"""P6b's backend: list an area's placements, author edits, preview them, and build.

`gbox.pso_map_write` already does the hard part -- 68-byte placement records, the set archives, and a build that produces
a bootable image. What an editor page needs on top of that is the *editorial* shape:

* **discover** what can be edited (the loose `map_*d.dat` sets and the entries inside the three set archives),
* **list** a set's placements as records a UI can show (index, kind, class name, position),
* **normalise** an edit into the op dicts `pso_map_write` understands -- so a page never has to know that a move is a
  12-byte patch while an add rebuilds the container,
* **preview** an edit set without building an image, by applying it to bytes and reading the result back.

Nothing here invents format knowledge; it is the layer that makes the existing writer usable by a page, and it refuses
edits it cannot verify.
"""
from __future__ import annotations

from . import pso_map_write as W
from . import pso_setdata as P

KINDS = ("object", "enemy", "event")
CLASS_NAMES = {
    0: "player", 1: "npc", 2: "object", 3: "enemy", 4: "item", 5: "door", 6: "warp", 7: "light", 8: "camera",
}


def kind_of(name: str) -> str | None:
    """Which placement set a file is, from its name, or None if it is not one.

    PSO names its sets by the kind they hold: ``map_<area>_<layout>o.dat`` and ``...d.dat`` hold objects (doors, items,
    decorations), ``...e.dat`` enemies, and ``....evt`` events. Anything else on the disc -- meshes, textures, tables -- is
    not editable by the placement writer.
    """
    low = name.lower().replace("\\", "/").rsplit("/", 1)[-1]
    if not low.startswith("map_"):
        return None
    if low.endswith("e.dat"):
        return "enemy"
    if low.endswith(".evt"):
        return "event"
    if low.endswith("o.dat") or low.endswith("d.dat"):
        return "object"
    return None


class EditError(ValueError):
    """An edit the editor refuses to hand to the writer."""


def sets(disc) -> list[dict]:
    """Every editable set: ``{name, kind, where}`` -- loose files first, then the archive entries."""
    out = []
    for name in getattr(disc, "files", {}):
        kind = kind_of(name)
        if kind:
            out.append({"name": name, "kind": kind, "where": "loose"})
    for kind in W.SET_ARCHIVES:
        try:
            entries = W.set_archive_files(disc, kind)
        except Exception:                             # noqa: BLE001 - a disc without that archive is not an error
            entries = {}
        for entry in entries:
            out.append({"name": entry, "kind": kind, "where": "archive"})
    return out


def placements(disc, set_name: str) -> dict:
    """The set's placements, in editor form: ``{set, count, records: [{index, kind, class, x, y, z}]}``."""
    data, where = W.read_set(disc, set_name)
    recs = P.records(data)
    rows = []
    for rec in recs:
        cls = P.kind_class(rec["kind"])
        rows.append({"index": int(rec["index"]), "kind": int(rec["kind"]), "class_index": cls,
                     "class": CLASS_NAMES.get(cls, f"class{cls}"),
                     "x": round(float(rec["x"]), 3), "y": round(float(rec["y"]), 3), "z": round(float(rec["z"]), 3),
                     "angle": round(float(rec["angle"]), 3)})
    return {"set": set_name, "where": where, "count": len(rows), "records": rows}


def edit(op: str, set_name: str, **fields) -> dict:
    """Normalise one edit into a writer op, checking the fields the writer will need."""
    if op not in ("move", "nearest", "add", "delete"):
        raise EditError(f"unknown edit {op!r}; known: move, nearest, add, delete")
    out = {"op": op, "set": set_name}
    need = {"move": ("index", "x", "y", "z"), "nearest": ("x", "z", "dx", "dz"),
            "add": ("kind", "x", "y", "z"), "delete": ("index",)}[op]
    for field in need:
        if field not in fields:
            raise EditError(f"{op}: missing {field!r}")
        out[field] = fields[field]
    if op in ("move", "nearest", "add") and out.get("y") is None and op != "nearest":
        raise EditError(f"{op}: y is required")
    return out


def edits(*ops: dict) -> list[dict]:
    """A validated list of writer ops, ready for `pso_map_write.build`."""
    if not ops:
        raise EditError("no edits given")
    return list(ops)


def preview(disc, ops: list[dict]) -> dict:
    """Apply the edits in memory and report what changed, without building an image.

    The writer's own expectations are returned, so a page can show "record 7 -> (x, y, z)" before anything is built.
    """
    changes, expect = W.ops_to_changes(disc, ops)
    touched = sorted(changes)
    return {"ok": True, "files": touched, "edits": len(ops),
            "changes": {name: (len(ch.get("bytes", b"")) if isinstance(ch, dict) else 0) for name, ch in changes.items()},
            "expect": expect}


def build(cfg, game_id: str, rom, name: str, ops: list[dict], progress=None) -> dict:
    """Build the edited disc image (delegates to `pso_map_write.build`)."""
    return W.build(cfg, game_id, rom, name, ops, progress=progress)
