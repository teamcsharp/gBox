"""Owned-build manifest for the GameCube multi-title disc that carries
'Legend of Zelda: Ocarina of Time - Master Quest' in the hyperspin library.

Everything reported here is derived from bytes that were actually parsed; nothing
is inferred from a file name.

Findings this module is built on (all re-derived at run time):

* the owned ``.gcz`` is a Dolphin GCZ container around a 28-file GameCube disc,
  game id ``D43E01``, title ``ZELDA OCARINA MULTI PACK``;
* that disc is a multi-title image: eight nested ``.tgc`` disc images plus a
  ``zeldaGraph.arc`` RARC archive and nine GameCube TPL texture archives;
* the nested retail payload ``zlj_f.tgc`` (inner game id ``D43J01``) has a
  well-formed disc header but its FST does **not** decode because it is a
  GameCube wrapper around two raw N64 ``z64`` images, found by magic scan:
  the Master Quest ROM (crc ``f034001a``, sha256 ``2a8d9dff...``) and the
  original OoT v1.2 ROM (crc ``f3dd35ba``, byte-identical to the CE build);
* the multi-title archive ``zeldaGraph.arc`` does decode and holds the character
  assets of the menu: ``zelda30.bmd`` (J3D model) and ``zelda30.bck`` (J3D
  animation) are the native target slot for a character replacement.

The manifest separates counted assets (parsed members) from the one file name
that is only a candidate target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import zlib

from gbox.formats.gcfst import disc_header, parse_fst
from gbox.formats.rarc import parse as rarc_parse
from gbox.gcdisc import GCDisc
from gbox.pzle_inventory import _FlatReader, rom_info, scan_magics

GC_MAGIC = bytes.fromhex("c2339f3d")
TGC_MAGIC = bytes.fromhex("ae0f38a2")
SUB_HEADER_BASE = 0x8000  # nested .tgc images carry the GC disc header at 0x8000

EXPECTED_GAME_ID = "D43E01"
EXPECTED_TITLE = "ZELDA OCARINA MULTI PACK"
EXPECTED_SOURCE_SHA256 = "cf9b6719479aefa6e8877fbab5362f8c4a54e99fc6070fd7b91ee63714d65ce8"

ARCHIVE_NAME = "zeldaGraph.arc"
NATIVE_TARGET_MODEL = "zelda30.bmd"
NATIVE_TARGET_ANIM = "zelda30.bck"

# J3D chunk tags. A file that carries several of them is a real J3D asset, not a
# name that merely looks like one.
J3D_MODEL_TAGS = (b"INF ", b"MSH1", b"MSH2", b"DRW1", b"DRW2", b"SHP1", b"MAT1",
                   b"TEX1", b"PEK1", b"POS1", b"NRM1", b"COL1", b"JNT1", b"AXS1",
                   b"AAM1", b"BTF1", b"KDS1", b"PBT1", b"SPT1", b"STB1", b"VTX1")
J3D_ANIM_TAGS = (b"JB  ", b"KSB3", b"KTB3", b"KTR3", b"FLG3", b"KHP3", b"SCN3")


def sha256_file(path) -> str:
    """SHA-256 of the file's own bytes, streamed."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def j3d_probe(raw: bytes, tags) -> dict:
    """Which J3D chunk tags a candidate asset really contains."""
    hits = {}
    for tag in tags:
        offsets = []
        start = raw.find(tag)
        while start != -1 and len(offsets) < 8:
            offsets.append(start)
            start = raw.find(tag, start + 1)
        if offsets:
            hits[tag.decode("latin-1").strip()] = {
                "offsets": offsets,
                "aligned_hits": sum(1 for o in offsets if o % 4 == 0),
            }
    return {
        "size": len(raw),
        "head_hex": raw[:16].hex(),
        "magic": raw[:4].decode("latin-1", "replace"),
        "j3d_tags": hits,
        "j3d_tag_count": len(hits),
    }


def rarc_paths(table) -> list:
    """[(path, entry)] for every file member of a parsed RARC."""
    nodes = table["nodes"]
    files = table["files"]
    dirpath = {0: ""}
    out = []
    stack = [0]
    while stack:
        i = stack.pop()
        node = nodes[i]
        for fi in range(node["first"], node["first"] + node["nchild"]):
            entry = files[fi]
            if entry["name"] in (".", ".."):
                continue
            if entry["type"] & 2:
                ni = entry["node_index"]
                if ni is None or ni in dirpath or ni >= len(nodes):
                    continue
                dirpath[ni] = f"{dirpath[i]}/{entry['name']}".strip("/")
                stack.append(ni)
            else:
                out.append((f"{dirpath[i]}/{entry['name']}".strip("/"), entry))
    return out


N64_MAGICS = {b"\x80\x37\x12\x40": "z64", b"\x37\x80\x40\x12": "v64", b"\x12\x40\x80\x37": "n32"}
N64_ROM_SIZE = 0x2000000  # OoT US builds are 32 MiB


def n64_roms_in(reader, base: int, size: int) -> list:
    """Locate raw N64 ROMs inside a .tgc blob by magic scan (not the FST).

    The retail payload of ``zlj_f.tgc`` is two raw z64 images, so its disc FST
    never decodes; the ROMs are found by scanning for the N64 magic byte and
    validating the header in place.  Casts (off, kind, info) are mapped to the
    disk offset and the ROM is hashed from its own 32 MiB of bytes.
    """
    out = []
    for off, kind in scan_magics(reader, base, size, N64_MAGICS):
        info = rom_info(reader, base + off)
        if info is None:
            continue
        h = hashlib.sha256()
        pos = 0
        while pos < N64_ROM_SIZE:
            blob = reader.read(base + off + pos, min(1 << 23, N64_ROM_SIZE - pos))
            h.update(blob)
            pos += len(blob)
        out.append({
            "disk_offset": base + off,
            "rel_offset": off,
            "size": N64_ROM_SIZE,
            "sha256": h.hexdigest(),
            "crc_stored": info["crc_stored"],
            "crc_valid": info["crc_valid"],
            "title": info["title"],
        })
    return out


def sub_image(disc, name: str, off: int, size: int) -> dict:
    """Manifest record for one nested .tgc disc image."""
    rec = {"name": name, "offset": off, "size": size}
    rec["tgc_wrapper_magic_ok"] = disc._r(off, 4) == TGC_MAGIC
    words = struct.unpack(">16I", disc._r(off, 0x40))
    rec["wrapper_words"] = {hex(i * 4): words[i] for i in range(16)}
    header = disc._r(off + SUB_HEADER_BASE, 0x440)
    rec["gc_magic_ok"] = header[0x1C:0x20] == GC_MAGIC
    dh = disc_header(header)
    rec["inner_game_id"] = dh["game_id"]
    rec["inner_title"] = dh["title"]
    rec["inner_fst_offset"] = dh["fst_offset"]
    rec["inner_fst_size"] = dh["fst_size"]
    rec["inner_dol_offset"] = dh["dol_offset"]
    rec["header_is_template"] = dh["game_id"].startswith("GAME") and dh["title"].startswith("Long")
    if dh["fst_size"]:
        fst_at = off + SUB_HEADER_BASE + dh["fst_offset"]
        raw = disc._r(fst_at, dh["fst_size"])
        try:
            entries = parse_fst(raw, fst_at)
        except Exception as exc:  # undecodable FST: reported, never guessed
            rec["fst_status"] = "undecoded"
            rec["fst_error"] = f"{type(exc).__name__}: {exc}"
            rec["fst_head_hex"] = raw[:32].hex()
        else:
            rec["fst_status"] = "decoded"
            rec["fst_files"] = [
                {"path": p, "offset": o, "size": s} for p, o, s, _ in entries
            ]
    return rec


def _tpl_dims(im):
    """Image dimensions of a TPL image, whatever the reader names them."""
    def pick(*names):
        for n in names:
            v = getattr(im, n, None)
            if isinstance(v, int):
                return v
        return None
    return [pick("width", "w", "img_width"), pick("height", "h", "img_height")]


def inventory(path, source_sha256: str | None = None) -> dict:
    """Authoritative manifest of the owned build."""
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(str(src))
    actual = sha256_file(src)
    if source_sha256 and actual != source_sha256:
        raise ValueError(f"SHA-256 mismatch: expected {source_sha256}, got {actual}")

    disc = GCDisc(str(src))
    header = disc_header(disc._r(0, 0x440))
    if header["game_id"] != EXPECTED_GAME_ID:
        raise ValueError(f"unexpected game id {header['game_id']!r}, expected {EXPECTED_GAME_ID!r}")

    files = [{"name": n, "offset": o, "size": s}
             for n, (o, s) in sorted(disc.files.items(), key=lambda kv: kv[1][0])]

    subs = [sub_image(disc, n, o, s)
            for n, (o, s) in sorted(disc.files.items(), key=lambda kv: kv[1][0])
            if n.endswith(".tgc")]

    # GameCube TPL texture archives on the outer disc.
    tpl = []
    try:
        from gbox.re4gc_models import tpl_read
    except Exception as exc:
        tpl = [{"error": f"TPL reader unavailable: {type(exc).__name__}: {exc}"}]
    else:
        for n, (o, s) in sorted(disc.files.items()):
            if not n.endswith(".tpl"):
                continue
            try:
                images = tpl_read(disc._r(o, s))
            except Exception as exc:
                tpl.append({"name": n, "size": s, "error": f"{type(exc).__name__}: {exc}"})
            else:
                tpl.append({"name": n, "size": s, "image_count": len(images),
                            "dimensions": [_tpl_dims(im) for im in images]})

    # The multi-title character archive.
    arc_off, arc_size = disc.files[ARCHIVE_NAME]
    arc = disc._r(arc_off, arc_size)
    table = rarc_parse(arc)
    members = rarc_paths(table)

    counts = {}
    models, animations = [], []
    for path_name, entry in members:
        ext = path_name.rsplit(".", 1)[-1].lower()
        counts[ext] = counts.get(ext, 0) + 1
        if ext in ("bmd", "bck"):
            raw = arc[entry["offset"]: entry["offset"] + entry["size"]]
            probe = j3d_probe(raw, J3D_MODEL_TAGS if ext == "bmd" else J3D_ANIM_TAGS)
            record = {"path": path_name, "size": entry["size"],
                      "sha256": hashlib.sha256(raw).hexdigest(), "probe": probe}
            (models if ext == "bmd" else animations).append(record)

    def target(records, name):
        for rec in records:
            if rec["path"] == name:
                return rec
        return None

    native_target = {
        "model": target(models, NATIVE_TARGET_MODEL),
        "animation": target(animations, NATIVE_TARGET_ANIM),
    }

    unresolved = [
        f"{s['name']}: nested retail payload (game id {s['inner_game_id']}) FST "
        f"{s.get('fst_status', 'absent')}"
        for s in subs
        if s.get("fst_status") == "undecoded"
    ]

    # Resolve the retail payload: locate raw N64 ROMs inside the nested .tgc
    # (its FST never decodes because it is a GC wrapper around raw z64 images).
    reader = _FlatReader(str(src))
    retail_roms = {}
    for n, (o, s) in sorted(disc.files.items()):
        if not n.endswith(".tgc"):
            continue
        roms = n64_roms_in(reader, o, s)
        if roms:
            retail_roms[n] = roms

    return {
        "source": {"path": str(src), "size": src.stat().st_size, "sha256": actual},
        "disc": {
            "game_id": header["game_id"],
            "title": header["title"],
            "dol_offset": header["dol_offset"],
            "fst_offset": header["fst_offset"],
            "fst_size": header["fst_size"],
            "file_count": len(files),
            "files": files,
        },
        "outer_tpl": tpl,
        "sub_images": subs,
        "zelda_graph": {
            "offset": arc_off,
            "size": arc_size,
            "sha256": hashlib.sha256(arc).hexdigest(),
            "node_count": len(table["nodes"]),
            "member_count": len(members),
            "asset_counts": counts,
            "models": models,
            "animations": animations,
            "native_target": native_target,
        },
        "retail_roms": retail_roms,
        "unresolved": unresolved,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?",
                    default="/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/"
                            "Legend of Zelda, The - Ocarina of Time - Master Quest (USA).gcz")
    ap.add_argument("--source-sha256", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    result = inventory(args.path, args.source_sha256)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text)
        print(args.out)
    else:
        print(text)


if __name__ == "__main__":
    main()
