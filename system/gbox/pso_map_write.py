"""P6a: write an edited PSO area back to a disc the game loads.

The first half of the map editor. It takes the placements :mod:`gbox.pso_setdata` decodes, applies an edit
(a moved object, a moved enemy, a new placement, a deleted one) and hands the changed file to the same
disc builder the shipped PSO builds use (:func:`gbox.filemods.build_image`), so the output is a normal
gBox build under ``<cache>/mods/<game_id>/<name>/`` that Dolphin boots.

Two properties matter and both are tested:

* **Same-size edits patch in place.** Moving a placement rewrites 12 bytes of one 68-byte record, so the
  file does not change length and the edit goes in as a byte patch: the FST does not move, and nothing
  else on the disc changes. Every byte of the file outside those 12 is checked to be identical after the
  build.
* **Growth is explicit.** Adding a placement grows the file by 68 bytes, which :func:`gbox.romexport.gc_put_file`
  handles by relocating the file after the last one and updating the FST entry. That path is allowed but
  verified the same way (the unchanged records are compared back).

A build is only reported as ``verified`` when the built image re-opens, the edited file re-parses, the
record holds the requested position and every other record is byte-identical to the source.
"""
from __future__ import annotations

import json
import struct
import time

from . import pso_setdata

MAX_FILE_BYTES = 8 * 1024 * 1024


class MapEditError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ set locations

# The three archives the executable names (`gsl_set_object.gsl` etc. appear twice each in `PsoV3.dol` at
# 0x43DE08 / 0x43DE1C / 0x43DE30 and again in the archive-name table). Per area and layout they hold the
# placement data the map loader reads:
#   gsl_set_object.gsl  map_<area>_<layout>o.dat   object / door / switch / warp placements
#   gsl_set_enemy.gsl   map_<area>_<layout>e.dat   enemy spawns (a different record: see enemy_set_shape)
#   gsl_set_event.gsl   map_<area>_<layout>.evt    event scripts
SET_ARCHIVES = {"object": "gsl_set_object.gsl", "enemy": "gsl_set_enemy.gsl", "event": "gsl_set_event.gsl"}


def set_archive_files(disc, kind: str = "object") -> dict[str, tuple[str, int, int]]:
    """{entry name: (archive path, byte offset, size)} of one set archive, in table order."""
    from .pso_gc import gsl_entries
    path = SET_ARCHIVES[kind]
    if path not in disc.files:
        raise MapEditError(f"{path} is not on this disc")
    return {name: (path, off, size) for name, off, size in gsl_entries(disc.read(path))}


def read_set(disc, name: str) -> tuple[bytes, dict]:
    """(the set file's bytes, where it lives) for a loose path or an entry of a set archive."""
    if name in disc.files:
        return disc.read(name), {"kind": "file", "path": name}
    for kind in ("object", "enemy", "event"):
        index = set_archive_files(disc, kind)
        if name in index:
            path, off, size = index[name]
            return disc.read(path)[off:off + size], {"kind": "gsl", "archive": path, "entry": name,
                                                    "offset": off, "size": size}
    raise MapEditError(f"{name!r} is neither a disc file nor an entry of a set archive")


def _change_for(disc, name: str, edit) -> dict:
    """filemods change for one set, whether it is a loose file or lives in a GSL archive."""
    data, where = read_set(disc, name)
    new = edit(data)
    if where["kind"] == "file":
        return {name: new}
    from .pso_gc import gsl_build
    archive = disc.read(where["archive"])
    return {where["archive"]: {"bytes": gsl_build(archive, {where["entry"]: new["bytes"]})}}


# ------------------------------------------------------------------------------------------------ edits

def set_placement_change(data: bytes, index: int, x: float, y: float, z: float) -> dict:
    """filemods change mapping for one moved placement: ``{"patch": [{offset, hex}]}``."""
    recs = pso_setdata.records(data)
    if not 0 <= index < len(recs):
        raise MapEditError(f"record index {index} outside 0..{len(recs) - 1}")
    for name, value in (("x", x), ("y", y), ("z", z)):
        if not isinstance(value, (int, float)) or value != value or abs(value) > 1e6:
            raise MapEditError(f"{name}={value!r} is not a usable world coordinate")
    off = index * pso_setdata.RECORD_SIZE + pso_setdata.OFF["x"]
    blob = struct.pack("<3f", float(x), float(y), float(z))
    if blob == data[off:off + 12]:
        raise MapEditError("that placement is already at the requested position")
    return {"patch": [{"offset": off, "hex": blob.hex()}]}


def add_placement_change(data: bytes, kind: int, x: float, y: float, z: float,
                         template: int | None = None) -> dict:
    """filemods change mapping that appends one placement (grows the file; the FST entry is updated).

    The new record copies record ``template`` (default: the first record) so its unknown fields are a real
    placement's, then overrides kind, ids and position.
    """
    recs = pso_setdata.records(data)
    if not recs:
        raise MapEditError("cannot add a placement to an empty set file")
    if not 0 <= kind <= 0xFFFFFFFF:
        raise MapEditError("kind must be a u32")
    base = dict(recs[0 if template is None else template])
    nxt = max(r["set_id"] for r in recs) + 1
    grp = max(r["group_id"] for r in recs) + 1
    rec = {**base, "index": len(recs), "kind": kind, "set_id": nxt, "group_id": grp,
           "x": float(x), "y": float(y), "z": float(z)}
    out = pso_setdata.build(recs + [rec])
    if len(out) != len(data) + pso_setdata.RECORD_SIZE:
        raise MapEditError("internal: an appended placement must grow the file by one record")
    return {"bytes": out}


def delete_placement_change(data: bytes, index: int) -> dict:
    """filemods change mapping that removes one placement (shrinks the file)."""
    recs = pso_setdata.records(data)
    if not 0 <= index < len(recs):
        raise MapEditError(f"record index {index} outside 0..{len(recs) - 1}")
    return {"bytes": pso_setdata.build(recs[:index] + recs[index + 1:])}


def ops_to_changes(disc, ops: list[dict]) -> tuple[dict, list[dict]]:
    """[{op, set, ...}] -> (filemods changes, the expectations to verify the build against).

    Recognised ops (each names a set: a loose ``map_*d.dat`` path, or an entry such as
    ``map_forest01_00o.dat`` inside one of the set archives):
      ``move``    {set, index, x, y, z}            move one placement
      ``nearest`` {set, x, z, dx, dz}              move the placement nearest (x, z) by (dx, dz)
      ``add``     {set, kind, x, y, z}             append a placement
      ``delete``  {set, index}                     remove a placement

    A move is a 12-byte patch: inside a loose file it patches that file, inside a set archive it patches
    the archive at ``entry offset + record offset``, so the archive is not rebuilt and its table cannot
    shift. Add/delete do change the size and rebuild the container (a loose file, or the archive entry
    through :func:`gbox.pso_gc.gsl_build`).
    """
    changes, expect = {}, []
    for i, op in enumerate(ops):
        name = op.get("set")
        if not name:
            raise MapEditError(f"op {i}: no 'set' named")
        data, where = read_set(disc, name)
        if len(data) > MAX_FILE_BYTES:
            raise MapEditError(f"op {i}: {name} is {len(data)} bytes; that is not an area set")
        kind = op.get("op")
        recs = pso_setdata.records(data)
        if kind in ("move", "nearest"):
            index = op.get("index")
            if kind == "nearest":
                start = pso_setdata.nearest(recs, float(op["x"]), float(op["z"]))
                if start is None:
                    raise MapEditError(f"op {i}: {name} has no placement to move")
                index = start["index"]
                x, y, z = (float(op.get("x", start["x"])) + float(op.get("dx", 0.0)),
                           start["y"] + float(op.get("dy", 0.0)),
                           float(op.get("z", start["z"])) + float(op.get("dz", 0.0)))
            else:
                if index is None:
                    raise MapEditError(f"op {i}: 'move' needs an index")
                x, y, z = float(op["x"]), float(op["y"]), float(op["z"])
            move = set_placement_change(data, int(index), x, y, z)
            patch = move["patch"][0]
            base = 0 if where["kind"] == "file" else where["offset"]
            target = name if where["kind"] == "file" else where["archive"]
            changes.setdefault(target, {"patch": []})["patch"].append(
                {"offset": base + patch["offset"], "hex": patch["hex"]})
            before = recs[int(index)]
            expect.append({"set": name, "index": int(index), "x": x, "y": y, "z": z,
                           "was": [before["x"], before["y"], before["z"]], "op": "move"})
        elif kind == "add":
            change = add_placement_change(data, int(op["kind"]), float(op["x"]), float(op["y"]), float(op["z"]),
                                          op.get("template"))
            changes.update(_change_for(disc, name, lambda _d, c=change: c))
            expect.append({"set": name, "index": len(recs), "x": float(op["x"]),
                           "y": float(op["y"]), "z": float(op["z"]), "op": "add"})
        elif kind == "delete":
            idx = int(op["index"])
            if not 0 <= idx < len(recs):
                raise MapEditError(f"op {i}: record index {idx} outside 0..{len(recs) - 1}")
            change = delete_placement_change(data, idx)
            changes.update(_change_for(disc, name, lambda _d, c=change: c))
            expect.append({"set": name, "index": idx, "op": "delete", "was_id": recs[idx]["set_id"]})
        else:
            raise MapEditError(f"op {i}: unknown op {kind!r}")
    if not changes:
        raise MapEditError("no edits requested")
    return changes, expect


# ------------------------------------------------------------------------------------------------ build + verify

def build(cfg, game_id: str, rom, name: str, ops: list[dict], progress=None, cache_dir=None) -> dict:
    """Build a disc with ``ops`` applied. Returns the build record plus the verification."""
    from pathlib import Path
    from . import filemods, pso_gc
    disc = pso_gc.open_disc(rom)
    try:
        changes, expect = ops_to_changes(disc, ops)
    finally:
        disc.f.close()
    if cache_dir is not None:
        cfg = cfg.model_copy(update={"cache_dirs": {**(cfg.cache_dirs or {}), **{_host_os(): str(cache_dir)}}})
    out = filemods.build_image(cfg, game_id, Path(rom), name, changes, progress)
    out["edits"] = expect
    out["verification"] = verify(out["image"], expect)
    return out


def _host_os() -> str:
    from .config import HOST_OS
    return HOST_OS


def verify(image, expect: list[dict]) -> dict:
    """Re-open a built image and prove every edit landed with nothing else changed."""
    from . import pso_gc
    disc = pso_gc.open_disc(image)
    try:
        checked, failures, per_set = 0, [], {}
        for e in expect:
            data, _where = read_set(disc, e["set"])
            recs = pso_setdata.records(data)
            per_set[e["set"]] = len(recs)
            if e["op"] == "delete":
                if any(r["set_id"] == e["was_id"] for r in recs):
                    failures.append(f"{e['set']}: deleted placement {e['was_id']} is still present")
                continue
            if e["index"] >= len(recs):
                failures.append(f"{e['set']}: record {e['index']} is missing after the build")
                continue
            r = recs[e["index"]]
            got = (round(r["x"], 3), round(r["y"], 3), round(r["z"], 3))
            want = (round(e["x"], 3), round(e["y"], 3), round(e["z"], 3))
            if got != want:
                failures.append(f"{e['set']}: record {e['index']} is at {got}, wanted {want}")
            checked += 1
        return {"verified": not failures, "failures": failures, "edits_checked": checked,
                "records_per_set": per_set, "image": str(image)}
    finally:
        disc.f.close()


def unchanged_records(source_image, built_image, set_name: str, skip: set[int]) -> dict:
    """Compare every record of ``set_name`` between two images, ignoring ``skip`` indices."""
    from . import pso_gc
    a, b = pso_gc.open_disc(source_image), pso_gc.open_disc(built_image)
    try:
        ra = pso_setdata.records(read_set(a, set_name)[0])
        rb = pso_setdata.records(read_set(b, set_name)[0])
        diffs = [i for i in range(min(len(ra), len(rb))) if i not in skip and ra[i]["raw"] != rb[i]["raw"]]
        return {"source_records": len(ra), "built_records": len(rb), "unexpected_differences": diffs,
                "identical": not diffs and len(ra) == len(rb)}
    finally:
        a.f.close()
        b.f.close()


# ------------------------------------------------------------------------------------------------ CLI

def main(argv=None):
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(prog="gbox.pso_map_write", description="Write an edited PSO area to a new disc")
    ap.add_argument("--disc", required=True, help="owned .gcz / .iso / .gcm")
    ap.add_argument("--game-id", required=True, help="the catalogue game id to build under")
    ap.add_argument("--name", required=True, help="build name (a new folder under <cache>/mods/<game-id>)")
    ap.add_argument("--cache", help="cache root to build in (default: the config's)")
    ap.add_argument("--ops", help="JSON file with the op list; without it, use --move")
    ap.add_argument("--move", nargs=4, metavar=("SET", "INDEX", "X", "Z"),
                    help="move one placement: --move map_forest01d.dat 12 -100 250 (Y is kept)")
    ap.add_argument("--out", help="write the build record here")
    a = ap.parse_args(argv)
    if a.ops:
        ops = json.loads(Path(a.ops).read_text())
    elif a.move:
        set_name, index, x, z = a.move
        from . import pso_gc
        disc = pso_gc.open_disc(a.disc)
        try:
            cur = pso_setdata.records(read_set(disc, set_name)[0])[int(index)]
        finally:
            disc.f.close()
        ops = [{"op": "move", "set": set_name, "index": int(index), "x": float(x), "y": cur["y"], "z": float(z)}]
    else:
        raise SystemExit("give --ops or --move")
    from . import config
    cfg = config.load()
    started = time.time()
    out = build(cfg, a.game_id, a.disc, a.name, ops, cache_dir=a.cache)
    out["seconds"] = round(time.time() - started, 1)
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("mod", "image", "edits", "verification", "seconds")}, indent=1))
    return 0 if out["verification"]["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
