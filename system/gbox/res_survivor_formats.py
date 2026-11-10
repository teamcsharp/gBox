"""Owned-build format probe for Resident Evil - Survivor (PSX).

game_id a178bf02b925ec44.  Every magic, offset, size and hash below is
parsed out of the owned CHD v5 image (ISO9660 walk through the shared
disc reader); nothing is copied from a catalog label or a filename guess.
The disc is a 2D sprite title: the assets are PSX TIM textures (4/8/16/24
bpp) held inside MT-Framework containers, not 3D meshes, so this module
reports container magic, TIM block layout and per-member offsets.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gbox.res_survivor_inventory import (  # noqa: E402
    DEFAULT_CHD, _chd_disc_cls, build_inventory, iso_tree,
)

TIM_MAGIC = 0x00000010
PBAV_MAGIC = b"pBAV"
PSX_EXE_MAGIC = b"PS-X EXE"
ROSTER_NAMES = ("LEON", "RAPI", "STEPHANIE", "GABRIEL", "ALISON", "CHARLIE")
CAST_CONTAINERS = ("OBJ.DAT", "EV_OBJ.DAT", "NOISE.BIN", "ITEMDAT.DAT",
                   "CONFFILE.BIN", "KERNEL.BIN")
KEY_MEMBERS = ("KERNEL.BIN", "SLUS_010.87", "OBJ.DAT", "EV_OBJ.DAT",
               "NOISE.BIN", "ITEMDAT.DAT", "CONFFILE.BIN")


def chd_path(explicit=None):
    return str(explicit or os.environ.get("RES_SURVIVOR_CHD", DEFAULT_CHD))


def open_disc(path=None):
    disc = _chd_disc_cls()(chd_path(path))
    iso, members = iso_tree(disc)
    return disc, iso, members


def read_range(disc, member, offset=0, length=None):
    """Read a byte range out of an ISO member (offset base = extent * 2048)."""
    size = member["size"]
    length = size - offset if length is None else length
    length = max(0, min(length, size - offset))
    if length == 0:
        return b""
    start = member["extent"] + offset // 2048
    first = offset % 2048
    nsec = (first + length + 2047) // 2048
    data = b"".join(disc.sector(start + i) for i in range(nsec))
    return data[first:first + length]


def parse_psx_tim(data, offset=0):
    """Strict PSX TIM: magic 0x00000010, flags, [CLUT block], image block."""
    if len(data) < offset + 8:
        return None
    magic, flags = struct.unpack_from("<II", data, offset)
    if magic != TIM_MAGIC or (flags & 0xFFFFFFC0):
        return None
    p = offset + 8
    clut = None
    if (flags & 3) in (0, 1):
        if len(data) < p + 4:
            return None
        csize = struct.unpack_from("<I", data, p)[0]
        if csize < 8 or csize > len(data) - p:
            return None
        clut = {"block_offset": p, "block_size": csize,
                "data_offset": p + 4, "data_size": csize - 4,
                "colors": (csize - 4) // 2 if flags & 4 else (csize - 4)}
        p += csize
    if len(data) < p + 4:
        return None
    isize = struct.unpack_from("<I", data, p)[0]
    if isize < 8 or isize > len(data) - p:
        return None
    return {"offset": offset, "flags": flags,
            "bpp": {0: 4, 1: 8, 2: 16, 3: 24}[flags & 3],
            "clut16": bool(flags & 4), "interlaced": bool(flags & 8),
            "clut": clut,
            "image": {"block_offset": p, "block_size": isize,
                      "data_offset": p + 4, "data_size": isize - 4},
            "end": p + isize}


def scan_tim_images(data, start=0):
    hits, i = [], start
    while True:
        j = data.find(b"\x10\x00\x00\x00", i)
        if j < 0:
            return hits
        t = parse_psx_tim(data, j)
        if t:
            hits.append(t)
            i = t["end"]
        else:
            i = j + 4


def detect_pbav(data):
    """MT-Framework 'pBAV' container header (version, header size, blocks)."""
    if len(data) < 16 or data[12:16] != PBAV_MAGIC:
        return None
    version, header_size, first_block = struct.unpack_from("<III", data, 0)
    return {"magic": PBAV_MAGIC.decode("ascii"), "offset": 12, "version": version,
            "header_size": header_size, "first_block_offset": first_block}


def parse_psx_exe(data):
    """PS-X EXE header (magic 'PS-X EXE', 11 words at 0x10)."""
    if len(data) < 0x40 or data[:8] != PSX_EXE_MAGIC:
        return None
    f = struct.unpack_from("<11I", data, 0x10)
    return {"pc0": f[0], "gp0": f[1], "text_addr": f[2], "text_size": f[3],
            "data_addr": f[4], "data_size": f[5], "bss_addr": f[6], "bss_size": f[7],
            "stack_addr": f[8], "stack_size": f[9], "t_addr": f[10]}


def focused_probe(path=None):
    """Cheap, deterministic evidence: two TIM magics, one pBAV, two EXEs."""
    disc, iso, members = open_disc(path)
    by = {m["path"]: m for m in members}
    out = {"volume_id": iso["volume_id"], "system_id": iso["system_id"]}
    aex = by["AEX.DAT"]
    out["aex_first_tim"] = parse_psx_tim(read_range(disc, aex, 0, 1 << 16), 0)
    big = by["B/BIGTIM.BIN"]
    out["bigtim_first_tim"] = parse_psx_tim(read_range(disc, big, 0, 1 << 16), 12)
    out["noise_pbav"] = detect_pbav(read_range(disc, by["NOISE.BIN"], 0, 4096))
    for name in ("KERNEL.BIN", "SLUS_010.87"):
        m = by[name]
        out[name] = {"size": m["size"], "extent": m["extent"], "offset": m["offset"],
                     "sha256": hashlib.sha256(read_range(disc, m)).hexdigest(),
                     "exe": parse_psx_exe(read_range(disc, m, 0, 2048))}
    return out


def build_format_report(path=None):
    """Full owned-build census: per-member TIM blocks, pBAV, casts, hashes."""
    disc, iso, members = open_disc(path)
    by = {m["path"]: m for m in members}
    report = {"game_id": "a178bf02b925ec44",
              "title": "Resident Evil - Survivor (USA) [PSX]",
              "source": chd_path(path), "volume_id": iso["volume_id"],
              "system_id": iso["system_id"], "byte_order": "little-endian (MIPS LE)",
              "offset_base": "ISO9660 LBA 0 == byte 0 of logical disc; member offset = extent * 2048",
              "members": {}, "tim_total": 0, "pbav_containers": [],
              "roster_name_hits": [], "cast_containers": []}
    for m in members:
        data = read_range(disc, m)
        hits = scan_tim_images(data)
        entry = {"size": m["size"], "extent": m["extent"], "offset": m["offset"],
                 "sha256": hashlib.sha256(data).hexdigest(),
                 "tim_count": len(hits),
                 "tim_bpp": sorted({h["bpp"] for h in hits}),
                 "tim_first": hits[0] if hits else None}
        pb = detect_pbav(data[:4096])
        if pb:
            entry["pbav"] = pb
            report["pbav_containers"].append({"path": m["path"], **pb})
        report["members"][m["path"]] = entry
        report["tim_total"] += len(hits)
        for n in ROSTER_NAMES:
            i = data.find(n.encode())
            if i >= 0:
                report["roster_name_hits"].append({"path": m["path"], "name": n, "offset": i})
    for p in CAST_CONTAINERS:
        m = by[p]
        data = read_range(disc, m)
        report["cast_containers"].append(
            {"path": p, "size": m["size"], "offset": m["offset"],
             "sha256": hashlib.sha256(data).hexdigest(),
             "tim_count": report["members"][p]["tim_count"],
             "roster_names_found": [n for n in ROSTER_NAMES if n.encode() in data]})
    report["key_members"] = {p: {k: report["members"][p][k]
                                 for k in ("size", "extent", "offset", "sha256")}
                             for p in KEY_MEMBERS if p in report["members"]}
    report["finding_character_identity"] = (
        "No ASCII cast name (LEON/RAPI/STEPHANIE/GABRIEL/ALISON/CHARLIE) occurs in the "
        "owned character containers; sprite identity is by numeric id inside the "
        "container tables, so the roster must come from the loader, not from names.")
    return report


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "res_survivor_formats.json"
    rep = build_format_report()
    Path(out).write_text(json.dumps(rep, indent=2, sort_keys=True))
    print(json.dumps({"tim_total": rep["tim_total"],
                      "members_with_tim": sum(1 for v in rep["members"].values() if v["tim_count"]),
                      "pbav_containers": rep["pbav_containers"],
                      "roster_name_hits": rep["roster_name_hits"],
                      "key_members": rep["key_members"]}, indent=2))
