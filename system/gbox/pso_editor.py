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

import pathlib

from . import pso_class_registry as REG
from . import pso_map_write as W
from . import pso_setdata as P

KINDS = ("object", "enemy", "event")


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
    """The set's placements, in editor form: ``{set, count, records: [{index, kind, class, family, x, y, z}]}``.

    The class name and family come from the executable's own registry (`pso_class_registry`), so a marker reads
    "door"/"warp"/"switch" or a real class name instead of a number.
    """
    data, where = W.read_set(disc, set_name)
    recs = P.records(data)
    rows = []
    for rec in recs:
        cls = P.kind_class(rec["kind"])
        rows.append({"index": int(rec["index"]), "kind": int(rec["kind"]), "class_index": cls,
                     "class": REG.label(cls), "family": REG.family(cls),
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

# --- room-local -> world ---------------------------------------------------------------------------------------
#
# Placement records are stored in a **room-local** space; the entity table reports **world** positions. Measured for the
# Pioneer 2 lobby (`map_city00_00o.dat`, i9-NUC 2026-11-10) by adding a constant to every record and checking which land on
# a live entity: with (+228, +291) **10 of the set's 28 records land exactly (distance 0.0)** on entities the game has --
# all four lobby doors (`TObjCityDoor_Guild/Shop/Warp/Med`), both co-op spawn points, and every `TObject` in the room.
#
# The door class indices fall out of that match, too: 0x46 Shop, 0x47 Guild, 0x48 Warp, 0x49 Med.
AREA_OFFSETS = {
    "map_city00_00o.dat": (228.0, 291.0),
}

DOOR_CLASSES = {0x46: "Shop", 0x47: "Guild", 0x48: "Warp", 0x49: "Med"}


def offset_of(set_name: str) -> tuple[float, float] | None:
    """The room-local -> world offset for a set, when it has been measured."""
    return AREA_OFFSETS.get(set_name.replace("\\", "/").rsplit("/", 1)[-1].lower())


def world_position(record: dict, set_name: str) -> tuple[float, float] | None:
    """A record's position in world coordinates, or None when the set's offset is not known.

    A page should show this next to the local values rather than instead of them: the local value is what the writer
    edits, the world value is what a player would recognise.
    """
    off = offset_of(set_name)
    if off is None:
        return None
    return (round(float(record["x"]) + off[0], 2), round(float(record["z"]) + off[1], 2))


def door_name(kind: int) -> str | None:
    """The door a record's kind value names, if it is one of the lobby's four."""
    return DOOR_CLASSES.get(int(kind) & 0xFF)

# --- a picture of an area --------------------------------------------------------------------------------------
#
# The guild search has cost many rounds of walking. A set rendered as a grid makes the shape of an area obvious at a glance
# -- where the doors are, where the objects cluster, and where nobody has been -- and it costs nothing to produce.

MARK = {"Warp": "W", "Guild": "G", "Shop": "S", "Med": "M"}   # keys must match door_name() exactly


def _mark_for(record: dict) -> str:
    door = door_name(record["kind"])
    if door:
        return MARK[door]          # every name door_name returns has a mark
    cls = CLASS_NAMES.get(record.get("class_index", -1))
    if cls == "player":
        return "*"
    if record.get("class_index") == 87:          # the lobby's teleporter pedestal
        return "T"
    return "o"


def ascii_map(records: list[dict], set_name: str, cols: int = 60, rows: int = 26,
              marks: dict | None = None) -> str:
    """Render a set's placements as a text grid, in **world** coordinates when the offset is known.

    ``marks`` maps a label to a world (x, z) to overlay (the player, a waypoint), shown as its first letter above the
    objects. Cells without anything are blank, so clustering and gaps are both visible.
    """
    pts = []
    for rec in records:
        world = world_position(rec, set_name)
        if world is None:
            world = (float(rec["x"]), float(rec["z"]))
        pts.append((world[0], world[1], _mark_for(rec)))
    for label, (wx, wz) in (marks or {}).items():
        pts.append((wx, wz, label[0].upper()))
    if not pts:
        return f"(no records in {set_name})"
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    span_x = max(x1 - x0, 1.0)
    span_z = max(z1 - z0, 1.0)
    grid = [[" "] * cols for _ in range(rows)]
    for x, z, ch in pts:
        # north (+z) at the top, like every map of a place the player has walked
        cx = int((x - x0) / span_x * (cols - 1))
        cz = rows - 1 - int((z - z0) / span_z * (rows - 1))
        grid[cz][cx] = ch
    head = f"{set_name}: x {x0:.0f}..{x1:.0f}, z {z0:.0f}..{z1:.0f}   ('*' spawn, 'T' pedestal, doors W/M/G/S, 'o' object)"
    return "\n".join([head] + ["".join(row) for row in grid])


# --- command line ----------------------------------------------------------------------------------------------
#
# The editorial layer is usable from a page, and equally from a shell, which is how most of this lane's verification
# happens. `python -m gbox.pso_editor <disc> sets` lists the editable sets; `list <set>` shows its placements with both
# the stored (room-local) and, where measured, the world position; `move`, `delete`, `add` and `build` take the same ops
# the writer does.

def build_parser():
    import argparse

    ap = argparse.ArgumentParser(prog="python -m gbox.pso_editor",
                                 description="List and edit PSO area placement sets.")
    ap.add_argument("disc", help="the disc image (.gcz / .iso / .gcm)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_sets = sub.add_parser("sets", help="list every editable set")
    p_sets.add_argument("--kind", choices=KINDS, default=None, help="only this kind")

    p_list = sub.add_parser("list", help="list one set's placements")
    p_list.add_argument("set")
    p_list.add_argument("--limit", type=int, default=0, help="show at most this many records")
    p_list.add_argument("--world", action="store_true", help="also show the world position when the offset is known")

    p_move = sub.add_parser("move", help="move one placement")
    p_move.add_argument("set")
    p_move.add_argument("index", type=int)
    p_move.add_argument("x", type=float)
    p_move.add_argument("y", type=float)
    p_move.add_argument("z", type=float)

    p_del = sub.add_parser("delete", help="delete one placement")
    p_del.add_argument("set")
    p_del.add_argument("index", type=int)

    p_map = sub.add_parser("map", help="draw one set as a text map")
    p_map.add_argument("set")
    p_map.add_argument("--cols", type=int, default=60)
    p_map.add_argument("--rows", type=int, default=26)

    p_build = sub.add_parser("build", help="build a disc image from ops (JSON on stdin)")
    p_build.add_argument("name")
    p_build.add_argument("--game-id", default="436e0bb84d5337d1")
    return ap


def main(argv=None):
    """Run the editor from the command line. Returns the result dict so a caller can assert on it too."""
    import json
    import sys

    from . import gcdisc

    ap = build_parser()
    args = ap.parse_args(argv)
    disc = gcdisc.GCDisc(args.disc)

    if args.cmd == "sets":
        found = sets(disc)
        if args.kind:
            found = [s for s in found if s["kind"] == args.kind]
        for s in found:
            print(f"{s['kind']:7s} {s['where']:8s} {s['name']}")
        print(f"{len(found)} set(s)")
        return {"sets": found}

    if args.cmd == "list":
        pl = placements(disc, args.set)
        rows = pl["records"][:args.limit] if args.limit else pl["records"]
        for r in rows:
            line = f"{r['index']:4d}  {r['class']:10s} local ({r['x']:8.2f}, {r['y']:7.2f}, {r['z']:8.2f})"
            if args.world:
                world = world_position(r, args.set)
                line += "  world " + (f"({world[0]:8.2f}, {world[1]:8.2f})" if world else "unknown")
            print(line)
        print(f"{pl['count']} record(s) in {args.set} ({pl['where']})")
        return {"set": args.set, "count": pl["count"], "records": rows}

    if args.cmd == "move":
        op = edit("move", args.set, index=args.index, x=args.x, y=args.y, z=args.z)
        out = preview(disc, [op])
        print(json.dumps(out, indent=1)[:2000])
        return out

    if args.cmd == "delete":
        op = edit("delete", args.set, index=args.index)
        out = preview(disc, [op])
        print(json.dumps(out, indent=1)[:2000])
        return out

    if args.cmd == "map":
        pl = placements(disc, args.set)
        text = ascii_map(pl["records"], args.set, cols=args.cols, rows=args.rows)
        print(text)
        return {"set": args.set, "count": pl["count"], "map": text}

    if args.cmd == "build":
        from . import config
        ops = json.load(sys.stdin)
        cfg = config.load(pathlib.Path("gbox.toml"))
        out = build(cfg, args.game_id, pathlib.Path(args.disc), args.name, ops)
        print(json.dumps(out, indent=1))
        return out

    raise EditError(f"unknown command {args.cmd!r}")


if __name__ == "__main__":
    main()
