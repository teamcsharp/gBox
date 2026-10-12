"""Time Stalkers (USA, Dreamcast): owned GD-ROM inventory and Climax "LANDERS" character containers.

The exact build is Time Stalkers (USA), product MK-51011, IP.BIN version V1.002 dated 2000-03-05. The owned CHD
(sha256 9bf9e7b6...a5b2) unpacks with chdman into three GD-ROM tracks. IP.BIN boots 1ST_READ.BIN, and MAIN.BIN holds
the game's loader format strings:

* ``%s\\man%03d%02d.BIN``: the skeleton and one motion bank per character id (``MANcccbb.BIN``, ccc = id, bb = bank)
* ``%s\\obj%03d.BIN`` + ``%s\\obj%03d.pvm``: the mesh and its PVM textures (``LANDERS/MANDATA/OBJnnn.*``)
* ``%s\\Map%03d.BIN/.pvm`` and ``%s\\BG%02d.BIN``: maps and backgrounds

Both MAN and OBJ containers carry the float triple 640.0, 480.0, 1024.0 near the start. In a MAN file the first u32 is
always ``size - 512`` and points at a 128-slot table of motion offsets (each bank fills its own slots). The node
records that follow the header are 0x30 bytes: two u32 offsets, position[3] float, angle[3] int (BAMS), scale[3]
float and a packed u32 link field. An OBJ file starts with a trailer offset, then 0, the float triple and the 4-byte
aligned texture names, which match its PVM's texture names in order.

``python -m gbox.time_stalkers disc.gdi --json manifest.json`` writes the inventory. Nothing on the disc is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAME_ID = "03927f87b167f81c"
TITLE = "Time Stalkers (USA)"
SOURCE_CHD_SHA256 = "9bf9e7b6699dbaa8223ec5f793b28f0e059a66812d2000cd7ce7c816059fa5b2"
SIG = struct.pack("<3f", 640.0, 480.0, 1024.0)
NODE_SIZE = 0x30
SLOTS = 128
MAN_RE = re.compile(r"^LANDERS/MANDATA/MAN(\d{3})(\d{2})\.BIN$")
OBJ_RE = re.compile(r"^LANDERS/MANDATA/OBJ(\d{3})\.(BIN|PVM|TEX)$")
LOADER_RE = re.compile(rb"%s\\[A-Za-z]+%0\dd(?:%0\dd)?\.[A-Za-z]{3}")


def ip_meta(ip: bytes) -> dict:
    """The Dreamcast IP.BIN header fields that name the exact build."""
    txt = lambda a, b: ip[a:b].decode("latin-1").strip()
    if ip[:16] != b"SEGA SEGAKATANA ":
        raise ValueError("not a Dreamcast IP.BIN")
    return {"maker": txt(0x10, 0x20), "device": txt(0x20, 0x30), "area": txt(0x30, 0x38),
            "product": txt(0x40, 0x4a), "version": txt(0x4a, 0x50), "date": txt(0x50, 0x58),
            "boot": txt(0x60, 0x70), "company": txt(0x70, 0x80), "title": txt(0x80, 0x100)}


def _finite(*v) -> bool:
    return all(math.isfinite(x) and abs(x) < 1e5 for x in v)


def parse_man(data: bytes) -> dict:
    """A MANcccbb.BIN header: motion slot table, header variant and (when it checks out) the node records."""
    if len(data) < 512 + 16:
        raise ValueError("MAN container too small")
    table = struct.unpack_from("<I", data, 0)[0]
    if table != len(data) - 512:
        raise ValueError(f"MAN slot table at {table:#x}, expected size-512 = {len(data) - 512:#x}")
    sig = data.find(SIG, 4, 40)
    if sig < 0:
        raise ValueError("MAN header lacks the 640/480/1024 constants")
    o = sig + 12
    variant = "plain"
    if data[o:o + 4] == b"\xff" * 4:
        variant, o = "ff", o + 4
    field = struct.unpack_from("<I", data, o)[0]
    slots = {i: v for i, v in enumerate(struct.unpack_from(f"<{SLOTS}I", data, table)) if v}
    bad_slot = [i for i, v in slots.items() if v >= table]
    first = min(slots.values(), default=table)
    nodes = None
    if 0 < field <= (first - o - 4) // NODE_SIZE:
        recs = []
        for i in range(field):
            r = o + 4 + i * NODE_SIZE
            a, b = struct.unpack_from("<2I", data, r)
            pos = struct.unpack_from("<3f", data, r + 8)
            ang = struct.unpack_from("<3i", data, r + 0x14)
            scl = struct.unpack_from("<3f", data, r + 0x20)
            link = struct.unpack_from("<I", data, r + 0x2c)[0]
            if not (_finite(*pos, *scl) and all(abs(s) > 1e-4 for s in scl)):
                recs = None
                break
            recs.append({"offsets": [a, b], "pos": [round(x, 4) for x in pos], "ang": list(ang),
                         "scl": [round(x, 4) for x in scl], "link": link})
        nodes = recs
    return {"size": len(data), "table": table, "variant": variant, "node_field": field,
            "nodes": nodes, "slots": slots, "bad_slots": bad_slot}


def parse_obj(data: bytes) -> dict:
    """An OBJnnn.BIN mesh header: trailer offset, texture names and the raw 28-byte trailer."""
    if len(data) < 48:
        raise ValueError("OBJ container too small")
    trailer, zero = struct.unpack_from("<2I", data, 0)
    if data[8:20] != SIG:
        raise ValueError("OBJ header lacks the 640/480/1024 constants at +8")
    if trailer + 28 > len(data):
        raise ValueError(f"OBJ trailer {trailer:#x} past the end ({len(data):#x})")
    names, o = [], 20
    while o < trailer and 0x20 < data[o] < 0x7f:
        e = data.index(b"\0", o)
        names.append(data[o:e].decode("latin-1"))
        o = (e + 4) & ~3
    t = data[trailer:trailer + 28]
    words = list(struct.unpack("<7I", t))
    floats = [round(x, 4) for x in struct.unpack_from("<2f", t, 4)]
    # trailer word 3 -> NJS_TEXLIST {NJS_TEXNAME *textures (12-byte records at names_end), count}; words 4 and 5 ->
    # two equal-length arrays of NJS_CNK_MODEL pointers (full parts with normals, and vertex-only twins), file-relative
    texlist = None
    if words[3] + 8 <= len(data):
        texlist = dict(zip(("textures", "count"), struct.unpack_from("<2I", data, words[3])))
    parts = []
    if words[4] < words[5] <= trailer and (words[5] - words[4]) == (trailer - words[5]):
        k = (words[5] - words[4]) // 4
        full = struct.unpack_from(f"<{k}I", data, words[4])
        twin = struct.unpack_from(f"<{k}I", data, words[5])
        parts = [{"model": cnk_model(data, a) if a else None, "twin": cnk_model(data, b) if b else None}
                 for a, b in zip(full, twin)]
    return {"size": len(data), "trailer": trailer, "word4": zero, "textures": names, "names_end": o,
            "trailer_words": words, "trailer_floats": floats, "texlist": texlist, "parts": parts}


def cnk_model(data: bytes, off: int) -> dict | None:
    """An NJS_CNK_MODEL {vlist*, plist*, center[3], r} with file-relative pointers and its first vertex chunk header
    (type 0x20-0x32, flags, size in 4-byte words, index offset, vertex count). None when it doesn't check out."""
    if off + 24 > len(data):
        return None
    vlist, plist = struct.unpack_from("<2I", data, off)
    center = struct.unpack_from("<4f", data, off + 8)
    if not (vlist + 8 <= len(data) and plist < len(data) and _finite(*center)):
        return None
    vtype, _flags, words, base, count = struct.unpack_from("<BBHHH", data, vlist)
    if not 0x20 <= vtype <= 0x32 or vlist + 4 + words * 4 > len(data):
        return None
    return {"offset": off, "vlist": vlist, "plist": plist, "center": [round(x, 4) for x in center[:3]],
            "radius": round(center[3], 4), "vtype": vtype, "vbase": base, "verts": count}


def pvm_names(data: bytes) -> list[str]:
    """Texture names of a PVMH archive (flags: 8 = names, 4 = format, 2 = dimensions, 1 = global index)."""
    if data[:4] != b"PVMH":
        raise ValueError("not a PVM archive")
    flags, count = struct.unpack_from("<2H", data, 8)
    step = 2 + (28 if flags & 8 else 0) + (2 if flags & 4 else 0) + (2 if flags & 2 else 0) + (4 if flags & 1 else 0)
    if not flags & 8:
        return [f"#{i}" for i in range(count)]
    return [data[0x0e + i * step:0x0e + i * step + 28].split(b"\0")[0].decode("latin-1") for i in range(count)]


def classify(path: str) -> str:
    """The asset role of one disc file, from the loader format strings and directory names."""
    p = path.upper()
    if MAN_RE.match(p):
        return "character_skeleton_motion"
    m = OBJ_RE.match(p)
    if m:
        return {"BIN": "object_mesh", "PVM": "object_textures", "TEX": "object_texture"}[m.group(2)]
    d = p.rsplit("/", 1)[0] if "/" in p else ""
    ext = p.rsplit(".", 1)[-1]
    if not d:
        return "boot_texture" if ext == "PVR" else "executable"
    return {"LANDERS/SAYMANDATA": "portrait", "LANDERS/MAPDATA": "map", "LANDERS/PIECEMAP": "map",
            "LANDERS/BGDATA": "map", "LANDERS/EFCTDATA": "effect", "LANDERS/EFCTCAMERA": "effect_camera_motion",
            "LANDERS/WAVEDATA": "audio", "LANDERS/MUSICDATA": "audio", "LANDERS/OPENINGDATA": "movie",
            "LANDERS/DEMODATA": "demo_script", "LANDERS/FONTDATA": "font", "LANDERS/WINDOW": "ui",
            "LANDERS/SYSTEM": "system"}.get(d, "unclassified")


def _label(names: list[str]) -> str:
    """The most common texture-name prefix (before the first '_'), e.g. 'swd' for Sword's mesh."""
    c = Counter(n.split("_")[0].lower() for n in names if n)
    return c.most_common(1)[0][0] if c else ""


def inventory(gdi: str | Path, source_sha256: str | None = None) -> dict:
    from .gdrom import GDRom

    g = GDRom(gdi)
    files = g.files
    by_lba = sorted((lba, n) for n, (lba, _) in files.items())
    room = {n: (by_lba[i + 1][0] - lba) * 2048 if i + 1 < len(by_lba) else None for i, (lba, n) in enumerate(by_lba)}
    meta = ip_meta(_ip(g))
    exe = {}
    loaders = set()
    for n in sorted(files):
        if "/" not in n and n.upper().endswith(".BIN"):
            b = g.read(n)
            exe[n] = {"size": len(b), "sha256": hashlib.sha256(b).hexdigest(), "lba": files[n][0]}
            loaders.update(x.decode("latin-1") for x in LOADER_RE.findall(b))
    layout = defaultdict(lambda: {"files": 0, "bytes": 0, "roles": Counter()})
    for n, (_, size) in files.items():
        d = n.rsplit("/", 1)[0] if "/" in n else "."
        layout[d]["files"] += 1
        layout[d]["bytes"] += size
        layout[d]["roles"][classify(n)] += 1
    chars, errors, unmatched = defaultdict(dict), [], []
    for n in sorted(files):
        m = MAN_RE.match(n)
        if not m:
            if n.startswith("LANDERS/MANDATA/MAN"):
                unmatched.append(n)
            continue
        try:
            h = parse_man(g.read(n))
        except ValueError as e:
            errors.append({"file": n, "error": str(e)})
            continue
        sl = sorted(h["slots"])
        chars[int(m.group(1))][m.group(2)] = {
            "file": n, "lba": files[n][0], "size": h["size"], "room": room[n], "variant": h["variant"],
            "node_field": h["node_field"], "nodes": len(h["nodes"]) if h["nodes"] else None,
            "slots": len(sl), "slot_range": [sl[0], sl[-1]] if sl else None, "bad_slots": h["bad_slots"]}
    objs = {}
    for n in sorted(files):
        m = OBJ_RE.match(n)
        if not m:
            continue
        o = objs.setdefault(int(m.group(1)), {})
        rec = {"file": n, "lba": files[n][0], "size": files[n][1], "room": room[n]}
        try:
            if m.group(2) == "BIN":
                h = parse_obj(g.read(n))
                models = [p["model"] for p in h["parts"] if p["model"]]
                rec.update(textures=h["textures"], trailer_words=h["trailer_words"],
                           trailer_floats=h["trailer_floats"], texlist=h["texlist"], parts=len(h["parts"]),
                           models=len(models), verts=sum(m["verts"] for m in models),
                           vertex_types=sorted({m["vtype"] for m in models}))
            elif m.group(2) == "PVM":
                rec["textures"] = pvm_names(g.read(n))
        except ValueError as e:
            errors.append({"file": n, "error": str(e)})
        o[m.group(2).lower()] = rec
    for i, o in objs.items():
        mesh, pvm = o.get("bin", {}).get("textures"), o.get("pvm", {}).get("textures")
        o["label"] = _label(mesh or pvm or [])
        o["pvm_matches_mesh"] = None if mesh is None or pvm is None else [x.lower() for x in mesh] == [x.lower() for x in pvm]
    roles = Counter(classify(n) for n in files)
    njm = sum(1 for n in files if n.upper().endswith(".NJM"))
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": "dreamcast",
        "source": {"kind": "chd", "sha256": source_sha256, "expected_sha256": SOURCE_CHD_SHA256,
                   "matches_expected": source_sha256 == SOURCE_CHD_SHA256 if source_sha256 else None,
                   "gdi": str(gdi), "data_tracks": [[t[0], t[1], Path(t[2]).name] for t in g.tracks]},
        "ip_bin": meta,
        "executables": exe,
        "loader_formats": sorted(loaders),
        "layout": {d: {"files": v["files"], "bytes": v["bytes"], "roles": dict(v["roles"])} for d, v in sorted(layout.items())},
        "roles": dict(roles),
        "characters": {f"{k:03d}": v for k, v in sorted(chars.items())},
        "objects": {f"{k:03d}": v for k, v in sorted(objs.items())},
        "portraits": sorted(n.split("/")[-1] for n in files if classify(n) == "portrait"),
        "summary": {"files": len(files), "man_files": sum(len(v) for v in chars.values()), "character_ids": len(chars),
                    "object_meshes": sum(1 for o in objs.values() if "bin" in o),
                    "object_pvms": sum(1 for o in objs.values() if "pvm" in o),
                    "object_tex": sum(1 for o in objs.values() if "tex" in o),
                    "pvm_name_matches": sum(1 for o in objs.values() if o["pvm_matches_mesh"]),
                    "motion_slots": sum(b["slots"] for v in chars.values() for b in v.values()),
                    "njm_motions": njm, "portraits": roles.get("portrait", 0),
                    "unmatched_man": unmatched, "errors": errors},
    }


def _ip(g) -> bytes:
    """IP.BIN is the first sector of the high-density data track."""
    hd = min((t for t in g.tracks if t[0] >= 45000), default=max(g.tracks))
    return g.sector(hd[0])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--json", help="write the manifest here")
    ap.add_argument("--source-sha256", help="sha256 of the owned CHD the GDI was unpacked from")
    a = ap.parse_args(argv)
    inv = inventory(a.gdi, a.source_sha256)
    text = json.dumps(inv, indent=1, sort_keys=True)
    if a.json:
        Path(a.json).write_text(text)
    print(json.dumps({"ip_bin": inv["ip_bin"], "summary": inv["summary"]}, indent=1))
    return 1 if inv["summary"]["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
