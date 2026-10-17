"""Burnout Revenge (Xbox 360, title 454107DC) inventory manifest.

Identify the exact owned build (XDVDFS disc image, default.xex) and enumerate its
vehicle ("character") assets: the per-car model/rig/geometry files under pveh/, the
RenderWare texture dictionary, the Criterion container layout and the format magics
(.bgv = zlib-wrapped geometry, .hwb = DNBW rig buffer, .gin = Gnsu2.0 geometry info).

CLI:  python -m gbox.burnout_revenge_inventory ISO [--out m.json] [--source-sha256 HEX]

Pure stdlib plus gbox.re6 (the shared XDVDFS/XEX reader); no numpy/PIL, so it runs on
the runtime venv and in CI without the analysis stack.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zlib
from collections import Counter, defaultdict
from pathlib import Path

from . import re6

TITLE_ID = 0x454107DC                 # Burnout Revenge (all regions)
XEX_MAGIC = b"XEX2"
BUILD_PAT = re.compile(rb"Burnout\d?_External\.pe")

# pveh/<quality>/<region>/<Car><variant>.<ext>  e.g. pveh/high/us/Car2S1d.gin
# (XDVD paths carry a leading slash: "/pveh/high/us/Car1A.bgv")
CAR_RE = re.compile(r"^/?pveh/(?P<quality>high|low)/(?P<region>as|eu|us)/(?P<car>Car\d+[A-Z]*\d*)(?P<sub>[a-z]?)\.(?P<ext>bgv|hwb|gin)$")
# pveh/traf/<region>/CarNN.btv  (civilian traffic vehicles)
TRAF_RE = re.compile(r"^/?pveh/traf/(?P<region>as|eu|us)/(?P<car>Car\d+)\.btv$")
# tracks/<region>/<track>_vN/Gamedata.bgd  (per-track game data)
BGD_RE = re.compile(r"^/?tracks/(?P<region>as|eu|us)/(?P<track>\w+)/Gamedata\.bgd$")

# format magics observed on the owned build
FORMAT_MAGICS = {
    "bgv": "zlib-wrapped geometry (0x78 0xda)",     # decompresses to vertex/index soup
    "hwb": "DNBW rig buffer",                        # rig/weight buffer
    "gin": "Gnsu20 geometry info v2.0 (a=anim, d=damage)",
}


def xex_info(data: bytes) -> dict:
    """Identity fields of default.xex (XEX2 header; title id + build string)."""
    if data[:4] != XEX_MAGIC:
        raise ValueError("not an XEX2 executable")
    mod_flags, header_size = struct.unpack_from(">II", data, 4)
    sec_off = struct.unpack_from(">I", data, 16)[0]
    pat = struct.pack(">I", TITLE_ID)
    off = data.find(pat)
    if off < 0:
        pat = struct.pack("<I", TITLE_ID)
        off = data.find(pat)
    if off < 0:
        raise ValueError(f"title id {TITLE_ID:#x} not found in XEX header")
    build = None
    m = BUILD_PAT.search(data[:0x4000])
    if m:
        build = m.group().decode("ascii", "replace")
    return {"magic": "XEX2", "module_flags": f"{mod_flags:#x}", "header_size": f"{header_size:#x}",
            "security_offset": f"{sec_off:#x}", "title_id": f"{TITLE_ID:#x}",
            "title_id_offset": off, "build_string": build, "size": len(data)}


def classify_vehicles(files: dict) -> dict:
    """Group the pveh/ files into playable cars, traffic cars and track game data."""
    roster: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    traffic: dict[str, list[str]] = defaultdict(list)
    tracks: set[str] = set()
    for p in files:
        m = CAR_RE.match(p)
        if m:
            roster[m.group("car")][m.group("ext")].append(f"{m.group('quality')}/{m.group('region')}{m.group('sub')}")
            continue
        m = TRAF_RE.match(p)
        if m:
            traffic[m.group("car")].append(m.group("region"))
            continue
        m = BGD_RE.match(p)
        if m:
            tracks.add(m.group("track"))
    return {
        "cars": {car: {ext: sorted(v) for ext, v in exts.items()} for car, exts in sorted(roster.items())},
        "traffic": {car: sorted(v) for car, v in sorted(traffic.items())},
        "tracks": sorted(tracks),
    }


def detect_formats(xdvd, paths: list[str]) -> list:
    """Read the first bytes of sample files to confirm the container/model magics."""
    out = []
    for p in paths:
        if p not in xdvd.files:
            out.append({"path": p, "error": "not on disc"})
            continue
        off, size = xdvd.files[p]
        xdvd.f.seek(off)
        h = xdvd.f.read(64)
        kind = None
        if h[:2] in (b"\x78\x9c", b"\x78\xda", b"\x78\x01"):
            kind = "zlib"
            try:
                xdvd.f.seek(off)
                d = zlib.decompress(xdvd.f.read(size))
                kind = f"zlib (decompressed {size} -> {len(d)} B, head {d[:8].hex()})"
            except zlib.error:
                kind = "zlib (stream continues past sample)"
        elif h[:4] == b"DNBW":
            kind = "DNBW rig buffer"
        elif h[:4] == b"Gnsu":
            kind = f"Gnsu geometry info ({h[:8].decode('latin-1')})"
        elif h[:4] == b"\xbc\xde\xed\x81":
            kind = "RenderWare TXD texture dictionary"
        out.append({"path": p.rsplit("/", 1)[-1], "size": size, "magic": h[:8].hex(), "kind": kind})
    return out


def inventory(iso, source_sha256: str | None = None) -> dict:
    """Full manifest of the owned disc image: build identity, container layout, vehicle census."""
    iso = str(iso)
    disc = re6.XDVD(iso)
    try:
        files = disc.files
        xex = disc.read("/default.xex")
        top = Counter(p.split("/", 2)[1] if p.count("/") >= 1 else "(root)" for p in files)
        exts = Counter(p.rsplit(".", 1)[-1].lower() if "." in p else "(none)" for p in files)
        roster = classify_vehicles(files)
        samples = detect_formats(disc, [
            "/pveh/high/us/Car1A.bgv", "/pveh/high/us/Car1A.hwb",
            "/pveh/high/us/Car1Aa.gin", "/pveh/high/us/Car1Ad.gin",
            "/data/Global.txd", "/tracks/tlist.bin",
        ])
        man = {
            "game": "Burnout Revenge",
            "platform": "xbox360",
            "title_id": f"{TITLE_ID:#x}",
            "source": {"path": iso, "size": Path(iso).stat().st_size, "sha256": source_sha256},
            "executable": {"path": "/default.xex", "sha256": hashlib.sha256(xex).hexdigest(), **xex_info(xex)},
            "disc": {"partition": disc.part, "files": len(files), "bytes": sum(n for _, n in files.values()),
                     "top_dirs": dict(top), "extensions": dict(exts)},
            "vehicles": {"cars": len(roster["cars"]), "traffic": len(roster["traffic"]),
                         "track_game_data": len(roster["tracks"]), **roster,
                         "format_magics": FORMAT_MAGICS, "samples": samples},
            "launch": {
                "emulator": "Xenia (canary)", "boot": "extracted folder with default.xex at root",
                "base_extraction": "gbox.re6.extract (XDVD extract, resumable)",
                "mod_mechanism": "hard-link copies of the extracted base in ~/gbox-cache/mods/<game_id>/<mod> with only changed pveh files real; launch_game(mod=...)",
                "note": "core is currently unset in the catalog (xbox360); launch acceptance needs a Xenia worker",
            },
        }
        return man
    finally:
        disc.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Burnout Revenge (Xbox 360) inventory manifest")
    ap.add_argument("iso", help="owned disc image (.iso)")
    ap.add_argument("--out", default="burnout_revenge_inventory.json", help="manifest output path")
    ap.add_argument("--source-sha256", default=None, help="sha256 of the source image, if precomputed")
    args = ap.parse_args(argv)
    man = inventory(args.iso, args.source_sha256)
    Path(args.out).write_text(json.dumps(man, indent=1))
    print(json.dumps({k: man[k] for k in ("game", "title_id", "source", "executable", "disc", "vehicles")}, indent=1))
    print(f"manifest -> {args.out}")


if __name__ == "__main__":
    main()
