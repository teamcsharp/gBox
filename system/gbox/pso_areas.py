"""PSO Episode I & II area catalogue: every field area's disc files, collision and placement sets.

This is the "breaking down" half of P2: for each area the game can load it collects

* the collision file (``Scene/map_<area>c.rel``, or ``Scene/map_<area>_<variant>c.rel`` for a
  multi-layout area) and the triangles :mod:`gbox.psomap` extracts from it,
* the render geometry (``n.rel``), the object/render sections (``r.rel``) and the area textures
  (``.GVM`` / ``s.GVM`` / ``s.gj``),
* the placement set (``map_<area>d.dat`` / ``map_<area>_<variant>d.dat`` and the ``ad`` variant)
  decoded by :mod:`gbox.pso_setdata`,
* the event scripts (``*.evt``) and the effect tables (``*e.dat`` / ``*o.dat``) where the area has
  them,

with each file's size and sha256, so a rebuild can prove it started from the right bytes.

Area order comes from the executable, not from a guess: ``PsoV3.dol`` (not ``main.dol``, which is
only the AppSwitcher stub) carries the area-archive name table at ``0x431C04`` in load order
(``gsl_city.gsl``, ``gsl_forest01.gsl``, ``gsl_forest02.gsl``, ...).  ``LIST_AREA_TABLE`` below is
that table, verbatim, and the area prefix of each entry (``gsl_forest01.gsl`` -> ``forest01``) is
the ``Scene/map_<area>*`` stem the catalogue groups on.  Do not re-number it.

Variant suffixes: ``map_cave01_00..05`` and friends are the area's *layout variants* -- one floor of
Cave 1 is built from one of six layouts.  ``map_aforest02``-style ``a`` prefixes are a second
layout of the same floor; :data:`FLOOR_LAYOUTS` records the two the bot already pins by sha256 in
:mod:`gbox.pso_coop_geometry` (floor 2 = ``forest02`` or ``aforest02``).
"""
from __future__ import annotations

import hashlib
import json
import re

from . import psomap
from . import pso_setdata

# ------------------------------------------------------------------------------------------------- authoring facts

# `PsoV3.dol` + 0x431C04, in table order: the archive the map loader opens per area. The order is
# the game's own area-index order (city first, then Episode I, then the `a` layouts, then Episode II).
LIST_AREA_TABLE = (
    "city", "forest01", "forest02", "cave01", "cave02", "cave03", "machine01", "machine02",
    "ancient01", "ancient02", "ancient03", "versus01", "versus02", "labo", "ruins01", "space01",
    "aforest01", "aforest02", "acave01", "acave02", "acave03", "amachine01", "amachine02",
    "aancient01", "aancient02", "aancient03", "aversus01", "aversus02", "aruins01", "aspace01",
    "jungle01", "jungle02", "jungle03", "jungle04", "jungle05", "seabed01", "seabed02",
    "jungle06", "jungle07",
)
LIST_AREA_MULTI = ("jungle01", "jungle02", "jungle03", "jungle04", "jungle05", "seabed01", "seabed02")

DOL_AREA_TABLE_OFFSET = 0x431C04

# Floor -> the layouts the bot pins by collision sha256 (gbox.pso_coop_geometry.KNOWN). Only these
# are proven; everything else needs a live area load to attribute.
FLOOR_LAYOUTS = {
    (1, 0): ("city00",),
    (1, 1): ("forest01",),
    (1, 2): ("forest02", "aforest02"),
}

# area -> (episode, zone family, floor within that zone). Derived, in order of authority:
#  * floors 0..7 from the proven Ep1 floor ids in gbox.pso_fence.FLOOR_NAMES_EP1 (town, Forest 1-2,
#    Cave 1-3, Mine 1-2);
#  * Ruins 1-3 = the three `ancient` areas, because `gsl_ancient01.gsl`'s own zone text
#    (`map_ancient_e.bin`) is the Episode I Ruins narration ("these weapons are from Pioneer 1 ...
#    they must have already entered the ruins");
#  * `ruins01/02` are NOT Episode I: `map_ruin_e.bin` is the Episode II VR Temple ("VR test field",
#    "final Temple area cleared"), so those two are VR Temple Alpha/Beta;
#  * `space01/02` likewise carry the VR Spaceship narration in `map_space_e.bin`;
#  * the `a`-prefixed areas are the alternate/Battle layouts of an Episode I area: every one of them
#    has zero placement sets (see `a` rows below), so they are not campaign areas;
#  * `jungle01..07` / `seabed01/02` / `labo00` are Episode II (Central Control Area, Seabed, Lab).
# Anything not listed here has no established episode and reports None.
ZONES = {
    "city00": (1, "Pioneer 2", 0), "lobby": (2, "Lobby", 0),
    "forest01": (1, "Forest", 1), "forest02": (1, "Forest", 2),
    "cave01": (1, "Cave", 1), "cave02": (1, "Cave", 2), "cave03": (1, "Cave", 3),
    "machine01": (1, "Mine", 1), "machine02": (1, "Mine", 2),
    "ancient01": (1, "Ruins", 1), "ancient02": (1, "Ruins", 2), "ancient03": (1, "Ruins", 3),
    "ruins01": (2, "VR Temple", 1), "ruins02": (2, "VR Temple", 2),
    "space01": (2, "VR Spaceship", 1), "space02": (2, "VR Spaceship", 2),
    "jungle01": (2, "Central Control Area", 1), "jungle02": (2, "Central Control Area", 2),
    "jungle03": (2, "Central Control Area", 3), "jungle04": (2, "Central Control Area", 4),
    "jungle05": (2, "Central Control Area", 5), "jungle06": (2, "Central Control Area", 6),
    "jungle07": (2, "Central Control Area", 7),
    "seabed01": (2, "Seabed", 1), "seabed02": (2, "Seabed", 2),
    "labo00": (2, "Lab", 0),
    "boss01": (1, "Boss arena", 1), "boss02": (1, "Boss arena", 2),
    "boss03": (1, "Boss arena", 3), "boss04": (1, "Boss arena", 4),
    "boss05": (2, "Boss arena", 5), "boss06": (2, "Boss arena", 6),
    "boss07": (2, "Boss arena", 7), "boss08": (2, "Boss arena", 8),
    "darkfalz00": (1, "Boss arena", 14),
    "versus01": (None, "Battle mode", 0), "versus02": (None, "Battle mode", 0),
    "soccer11": (None, "Soccer minigame", 0), "soccer12": (None, "Soccer minigame", 0),
    "lobby_green_be00": (None, "Lobby event", 0), "lobby_red_be00": (None, "Lobby event", 0),
    "lobby_yellow_be00": (None, "Lobby event", 0),
}

EPISODE1 = tuple(a for a, (e, _z, _f) in ZONES.items() if e == 1)
EPISODE2 = tuple(a for a, (e, _z, _f) in ZONES.items() if e == 2)

# Scene file kinds, by the suffix the disc uses.



def _alternate(area: str):
    """`aforest02` -> the ZONES row of `forest02`, for the alternate-layout copies of an area.

    The `a` copies keep the base area's collision (same triangle count, e.g. `aforest01` 1,455 and
    `forest01` 1,455; `acave01` 43,266 and `cave01` 43,266) but carry **no** placement sets, so they
    are the alternate/Battle layouts of the same zone, not separate areas.
    """
    if len(area) > 1 and area[0] == "a":
        return ZONES.get(area[1:])
    return None


def episode_of(area: str) -> int | None:
    """1 for a known Episode I area, 2 for a known Episode II area, None when the name is not one."""
    row = ZONES.get(area) or _alternate(area)
    return row[0] if row else None


def zone_of(area: str) -> str | None:
    """The zone family of an area ('Forest', 'Cave', 'VR Temple', 'Boss arena', ...) or None."""
    row = ZONES.get(area)
    if row:
        return row[1]
    alt = _alternate(area)
    return f"{alt[1]} (alternate layout)" if alt else None


_AREA_RE = re.compile(r"^(?P<area>[a-z][a-z0-9_]*?)(?:_(?P<variant>\d{2}))?$")


# ------------------------------------------------------------------------------------------------- disc walking

def scene_index(files) -> dict[str, dict]:
    """{area: {role: [file names]}} for every ``Scene/map_*`` file in an FST listing.

    ``files`` is ``GCDisc.files`` (``{name: (offset, size)}``) or any mapping with the same keys.
    Roles: ``c`` collision, ``n`` geometry, ``r`` object/render sections, ``t`` texture block,
    ``s.GVM`` / ``s.gj`` the area texture archive and its list, ``.GVM`` the big texture archive,
    ``tam`` / ``bm.bin`` / ``i.bin`` the area tables.
    """
    out: dict[str, dict] = {}
    for name in files:
        if not name.startswith("Scene/"):
            continue
        rest = name[len("Scene/"):]
        if not rest.startswith("map_"):
            continue
        body = rest[len("map_"):]
        role = None
        for suffix, tag in (("c.rel", "c"), ("n.rel", "n"), ("r.rel", "r"), ("t.rel", "t")):
            if body.endswith(suffix):
                body, role = body[:-len(suffix)], tag
                break
        if role is None:
            for suffix, tag in (("s.GVM", "s.GVM"), ("s.gvm", "s.GVM"), ("s.gj", "s.gj"),
                                (".GVM", "GVM"), (".gvm", "GVM"), (".tam", "tam"),
                                ("bm.bin", "bm.bin"), ("i.bin", "i.bin")):
                if body.endswith(suffix):
                    body, role = body[:-len(suffix)], tag
                    break
        if role is None:
            continue
        m = _AREA_RE.match(body)
        if not m:
            continue
        area = m.group("area")
        variant = m.group("variant")
        bucket = out.setdefault(area, {})
        entry = bucket.setdefault(role, [])
        entry.append((int(variant) if variant else 0, name))
    for area, roles in out.items():
        for role in roles:
            roles[role] = [n for _v, n in sorted(roles[role])]
    return dict(sorted(out.items()))


def set_files(files) -> dict[str, dict]:
    """{area: {"d": [...], "ad": [...]}} of the placement sets ``map_<area>d.dat`` / ``...ad.dat``.

    Empty for the ``e``/``o`` event tables, which are their own formats (see ``event_files``).
    """
    out: dict[str, dict] = {}
    for name in files:
        if not name.startswith("map_") or not name.endswith(".dat"):
            continue
        body = name[len("map_"):-len(".dat")]
        if body.endswith("ad"):
            area, kind = body[:-2], "ad"
        elif body.endswith("d"):
            area, kind = body[:-1], "d"
        else:
            continue
        m = _AREA_RE.match(area)
        if not m:
            continue
        out.setdefault(m.group("area"), {}).setdefault(kind, []).append(name)
    return {a: {k: sorted(v) for k, v in d.items()} for a, d in sorted(out.items())}


def event_files(files) -> dict[str, list]:
    """{area: [names]} of the ``*.evt`` scripts and their ``*e.dat`` / ``*o.dat`` companions."""
    out: dict[str, list] = {}
    for name in files:
        if not name.startswith("map_") or "/" in name:
            continue
        m = re.match(r"^map_(?P<area>[a-z][a-z0-9_]*?)((?:_\d{2})?)_?(?P<k>jm|off)?(?P<suffix>e|o)?\.(?:evt|dat)$", name)
        if not m:
            continue
        area = m.group("area")
        if not (name.endswith(".evt") or (m.group("suffix") and m.group("k"))):
            continue
        out.setdefault(area, []).append(name)
    return {a: sorted(v) for a, v in sorted(out.items())}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------------------------------------- the catalogue

def collision_summary(data: bytes, be: bool = True) -> dict:
    """Triangle/bbox/identity summary of one ``c.rel`` collision file."""
    tris = psomap.collision(data, be)
    xs = [v[0] for t in tris for v in t[:3]]
    ys = [v[1] for t in tris for v in t[:3]]
    zs = [v[2] for t in tris for v in t[:3]]
    triggers = sum(1 for t in tris if t[3] & psomap.TRIGGER_FLAG)
    return {
        "triangles": len(tris), "trigger_triangles": triggers,
        "sha256": sha256(data), "bytes": len(data),
        "bounds": ({k: round(v, 3) for k, v in zip(
            ("min_x", "max_x", "min_y", "max_y", "min_z", "max_z"),
            (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))} if tris else {}),
    }


def set_summary(data: bytes) -> dict:
    """Placement census of one set file."""
    recs = pso_setdata.records(data)
    return {"records": len(recs), "kinds": pso_setdata.kinds(recs),
            "bounds": {k: round(v, 3) for k, v in pso_setdata.bounds(recs).items()},
            "sha256": sha256(data), "bytes": len(data)}


def catalogue(reader, files=None, *, hash_all=True) -> dict:
    """The whole disc's area catalogue.

    ``reader`` needs ``.read(name) -> bytes``; ``files`` defaults to ``reader.files``.  Collects, per
    area, every Scene file, the collision triangles, the placement records and the event scripts.
    ``decode_failures`` lists anything a decoder rejected instead of aborting the walk.
    """
    files = reader.files if files is None else files
    scenes, sets, events = scene_index(files), set_files(files), event_files(files)
    failures = []
    areas = {}
    for area in sorted(set(scenes) | set(sets) | set(events)):
        entry = {"area": area, "episode": episode_of(area), "zone": zone_of(area),
                 "in_area_table": area in LIST_AREA_TABLE,
                 "multiplayer_archive": area in LIST_AREA_MULTI,
                 "files": {}, "collision": [], "sets": [], "events": events.get(area, [])}
        for role, names in scenes.get(area, {}).items():
            for name in names:
                entry["files"][name] = {"role": role, "size": files[name][1],
                                        "sha256": sha256(reader.read(name)) if hash_all else None}
        for name in scenes.get(area, {}).get("c", []):
            try:
                entry["collision"].append({"file": name, **collision_summary(reader.read(name))})
            except Exception as exc:                            # a decoder that does not fit: report it
                failures.append({"file": name, "error": f"{type(exc).__name__}: {exc}"})
        for kind in ("d", "ad"):
            for name in sets.get(area, {}).get(kind, []):
                try:
                    entry["sets"].append({"file": name, "variant": kind, **set_summary(reader.read(name))})
                except pso_setdata.SetDataError as exc:
                    failures.append({"file": name, "error": str(exc)})
        entry["totals"] = {
            "triangles": sum(c["triangles"] for c in entry["collision"]),
            "trigger_triangles": sum(c["trigger_triangles"] for c in entry["collision"]),
            "placements": sum(s["records"] for s in entry["sets"]),
            "layouts": sum(1 for n in entry["files"] if n.endswith("c.rel")),
            "files": len(entry["files"]),
            "bytes": sum(f["size"] for f in entry["files"].values()),
        }
        areas[area] = entry
    return {
        "source": {"game_id": getattr(reader, "game_id", None), "title": getattr(reader, "title", None)},
        "area_table": list(LIST_AREA_TABLE), "area_table_dol_offset": DOL_AREA_TABLE_OFFSET,
        "areas": areas, "decode_failures": failures,
        "totals": {
            "areas": len(areas),
            "triangles": sum(a["totals"]["triangles"] for a in areas.values()),
            "placements": sum(a["totals"]["placements"] for a in areas.values()),
            "files": sum(a["totals"]["files"] for a in areas.values()),
        },
    }


# ------------------------------------------------------------------------------------------------- markdown

def to_markdown(cat: dict) -> str:
    """The catalogue as the research doc ``docs/research/pso-gc-areas.md``."""
    src = cat["source"]
    out = [
        "# PSO Episode I & II: every area's files, collision and placements",
        "",
        f"Generated by `python -m gbox.pso_areas --disc <image> --doc`. Source image "
        f"`{src.get('title') or '?'}` (`{src.get('game_id') or '?'}`).",
        "",
        f"Totals: **{cat['totals']['areas']} areas**, {cat['totals']['files']} area files, "
        f"{cat['totals']['triangles']:,} collision triangles, {cat['totals']['placements']:,} placements.",
        "",
        "Area order is the game's own: the archive-name table at `PsoV3.dol`+"
        f"`0x{cat['area_table_dol_offset']:X}`, listed in :mod:`gbox.pso_areas`. Collision triangles "
        "come from `gbox.psomap.collision` on `Scene/map_*c.rel`; placements come from "
        "`gbox.pso_setdata.records` on `map_*d.dat` / `map_*ad.dat` (68-byte little-endian records).",
        "",
        "`episode` is filled only for area names the repo already attributes; `-` means the zone "
        "family is known from the name but the episode/floor binding is not established here.",
        "`layouts` counts the layout variants the disc carries for that area (the `_00`, `_01`, ... "
        "and `a`-prefixed files).",
        "",
        "| area | ep | zone | layouts | collision tris | trigger tris | placements | set files | area files | bytes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for area, a in cat["areas"].items():
        layouts = sum(1 for n in a["files"] if n.endswith("c.rel"))
        out.append(
            f"| `{area}` | {a['episode'] if a['episode'] else '-'} | {a['zone'] or '-'} | {layouts} | "
            f"{a['totals']['triangles']:,} | {a['totals']['trigger_triangles']:,} | "
            f"{a['totals']['placements']:,} | {len(a['sets'])} | {a['totals']['files']} | "
            f"{a['totals']['bytes']:,} |")
    out.append("")
    out.append("## Per-area detail")
    out.append("")
    for area, a in cat["areas"].items():
        out.append(f"### `{area}`")
        out.append("")
        if a["episode"]:
            out.append(f"Episode {a['episode']}." + (f" {a['zone']}." if a["zone"] else ""))
        elif a["zone"]:
            out.append(f"{a['zone']}.")
        if a["multiplayer_archive"]:
            out.append("Has a `_multi` archive for multiplayer.")
        if a["area"] not in ZONES:
            # The alternate/Battle copies and the event lobbies have no placement sets and are not on
            # the campaign path; the summary table above carries their totals and the JSON has their
            # per-file hashes. Listing 40 texture files each here would bury the areas that matter.
            out.append("")
            out.append(f"Not a campaign area: {a['totals']['files']} files, "
                       f"{a['totals']['triangles']:,} collision triangles, no placement sets. "
                       "Per-file hashes: the JSON catalogue.")
            out.append("")
            continue
        out.append("")
        if a["collision"]:
            out.append("| collision file | triangles | trigger | bounds x / y / z | sha256 |")
            out.append("| --- | --- | --- | --- | --- |")
            for c in a["collision"]:
                b = c.get("bounds") or {}
                rng = (f"x {b.get('min_x', 0):.0f}..{b.get('max_x', 0):.0f}, "
                       f"y {b.get('min_y', 0):.0f}..{b.get('max_y', 0):.0f}, "
                       f"z {b.get('min_z', 0):.0f}..{b.get('max_z', 0):.0f}") if b else "-"
                out.append(f"| `{c['file']}` | {c['triangles']:,} | {c['trigger_triangles']:,} | {rng} | "
                           f"`{c['sha256'][:16]}` |")
            out.append("")
        if a["sets"]:
            out.append("| set file | variant | records | kinds | sha256 |")
            out.append("| --- | --- | --- | --- | --- |")
            for s in a["sets"]:
                kinds = ", ".join(f"{k}x{v}" for k, v in s["kinds"].items())
                out.append(f"| `{s['file']}` | {s['variant']} | {s['records']} | {kinds} | `{s['sha256'][:16]}` |")
            out.append("")
        if a["events"]:
            out.append("Events: " + ", ".join(f"`{e}`" for e in a["events"]))
            out.append("")
        other = {n: f for n, f in a["files"].items() if not n.endswith("c.rel")}
        if other:
            out.append("Other area files (bytes, sha256 prefix):")
            out.append("")
            for n, f in other.items():
                out.append(f"- `{n}` {f['size']:,} `{(f['sha256'] or '')[:16]}`")
            out.append("")
    if cat["decode_failures"]:
        out.append("## Decode failures")
        out.append("")
        for f in cat["decode_failures"]:
            out.append(f"- `{f['file']}`: {f['error']}")
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------- CLI

def main(argv=None):
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(prog="gbox.pso_areas", description=__doc__.splitlines()[0])
    ap.add_argument("--disc", required=True, help="owned .gcz / .iso / .gcm of PSO Episode I & II")
    ap.add_argument("--out", help="write the JSON catalogue here")
    ap.add_argument("--doc", help="write the markdown catalogue here")
    ap.add_argument("--area", action="append", help="restrict to these areas (repeatable)")
    ap.add_argument("--no-hash", action="store_true", help="skip per-file sha256 (much faster)")
    a = ap.parse_args(argv)
    from .pso_gc import open_disc
    disc = open_disc(a.disc)
    cat = catalogue(disc, hash_all=not a.no_hash)
    if a.area:
        keep = set(a.area)
        cat["areas"] = {k: v for k, v in cat["areas"].items() if k in keep}
    tot = cat["totals"]
    print(f"{tot['areas']} areas, {tot['triangles']:,} collision triangles, "
          f"{tot['placements']:,} placements, {tot['files']} files", file=__import__("sys").stderr)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(cat, indent=1))
        print(f"catalogue -> {a.out}", file=__import__("sys").stderr)
    if a.doc:
        Path(a.doc).parent.mkdir(parents=True, exist_ok=True)
        Path(a.doc).write_text(to_markdown(cat))
        print(f"doc -> {a.doc}", file=__import__("sys").stderr)
    if not a.out and not a.doc:
        print(json.dumps(cat["totals"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
