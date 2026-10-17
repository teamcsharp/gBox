"""Owned-build inventory for WCW vs. nWo: World Tour (USA, NWNE rev 1) on N64 (#1354).

    python -m gbox.wcw_worldtour_inventory ROM [--out manifest.json]

Identifies the exact owned build, verifies the gbox.aki_wcw writer profile it uses, and writes a manifest with the
container layout, AkiFileTable statistics, wrestler/costume roster and the part-model/texture/palette inventory.
PR #45 (#1317, gbox.aki_wcw_inventory) covers the Revenge regional builds and the profile-derivation tooling; this
module is the World Tour manifest built only from main-branch readers (gbox.aki_wcw, gbox.aki_wrestling).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from . import aki_wcw as W
from . import n64_rom

BYTE_ORDER = {b"\x80\x37\x12\x40": "z64 (big-endian)", b"\x37\x80\x40\x12": "v64 (byte-swapped)",
              b"\x40\x12\x37\x80": "n64 (word-swapped)"}


def container(path: Path) -> dict:
    """The owned file as stored: hash, archive members, and each member's actual byte order vs. its extension."""
    raw = path.read_bytes()
    out = {"path": str(path), "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            ms = []
            for m in z.infolist():
                with z.open(m) as f:
                    order = BYTE_ORDER.get(f.read(4), "unknown")
                ext = Path(m.filename).suffix.lower().lstrip(".")
                ms.append({"name": m.filename, "size": m.file_size, "crc32": f"{m.CRC:08x}", "byte_order": order,
                           "extension_matches": order.startswith(ext)})
            out["members"] = ms
    else:
        out["byte_order"] = BYTE_ORDER.get(raw[:4], "unknown")
    return out


def header(rom: bytes) -> dict:
    import struct
    import zlib
    u32 = lambda o: struct.unpack_from(">I", rom, o)[0]                       # noqa: E731
    region = chr(rom[0x3E])
    cic = {0x90BB6CB5: "6102/7101", 0x6170A4A1: "6101", 0x0B050EE0: "6103/7103", 0x98BC2C86: "6105/7105",
           0xACC8580A: "6106/7106"}.get(zlib.crc32(rom[0x40:0x1000]), "unknown")
    return {"name": rom[0x20:0x34].decode("ascii", "replace").strip(), "code": rom[0x3B:0x3F].decode("ascii", "replace"),
            "rev": rom[0x3F], "region": {"E": "USA", "P": "Europe", "J": "Japan"}.get(region, region),
            "crc1": f"{u32(0x10):08x}", "crc2": f"{u32(0x14):08x}", "entry": f"{u32(0x08):08x}", "cic": cic,
            "size": len(rom), "sha256_z64": hashlib.sha256(rom).hexdigest(), "md5_z64": hashlib.md5(rom).hexdigest()}


def wrestlers(rom: bytes) -> list[dict]:
    """Per wrestler: code, name, costumes with their body/head definitions and part model/texture/palette ids."""
    R = W.Rom(rom)
    out = []
    for w in W.roster(rom):
        cost = []
        for ci in range(len(w["costumes"])):
            parts = W.rest_parts(R, w, ci)
            cost.append({"body": parts["_costume"]["body"], "head": list(parts.get("_head", ())),
                         "parts": {str(k): [v["mid"], v["tex"], v["pal"]] for k, v in parts.items()
                                   if not str(k).startswith("_")}})
        out.append({"code": f"{w['code']:#05x}", "group": w["group"], "member": w["member"], "name": w["name"],
                    "heads": len(w["heads"]), "costumes": cost})
    return out


def inventory(rom: bytes, source: Path | None = None) -> dict:
    """Manifest of the owned World Tour build: layout, file table, roster, and the asset id inventory."""
    R = W.Rom(rom)
    p = R.p
    raw = R.ft.raw
    ws = wrestlers(rom)
    ids = lambda i: {v[i] for w in ws for c in w["costumes"] for v in c["parts"].values()}  # noqa: E731
    asset_end = p["first"] + max(x & ~1 for x in raw)
    m = {"build": header(rom), "source": container(source) if source else None,
         "profile": {"code": rom[0x3B:0x3F].decode("ascii", "replace"), "rev": rom[0x3F]},
         "layout": {"boot": [0x40, 0x1000], "code_rom": [0x1000, p["first"]], "code_ram": 0x80000400,
                    "assets_rom": [p["first"], asset_end],
                    "file_table_rom": [p["ft"], p["ft"] + 4 * len(raw)],
                    "free_tail": [p["ft"], len(rom) - p["ft"]]},
         "file_table": {"files": p["nfiles"], "lzss": sum(1 for x in raw[:-1] if x & 1)},
         "roster": {"wrestlers": len(ws), "costumes": sum(len(w["costumes"]) for w in ws),
                    "unnamed": [w["code"] for w in ws if w["name"].startswith("Wrestler ")],
                    "part_models": len(ids(0)), "textures": len(ids(1)), "palettes": len(ids(2)),
                    "parts_per_body": p["nmodels"], "bodies": p["bodies"]},
         "formats": {"models": "AkiModel (<=127 vertices / faces, int8 xyz + 16 * offset, rest pose)",
                     "textures": "CI4 bodies (16-colour banks) / CI8 heads, RGBA5551 palettes",
                     "animations": "not parsed: a part-model swap keeps the game's own skeleton and animations"},
         "launch": {"emulator": "retroarch", "core": "parallel_n64", "rsp": "cxd4 (LLE; HLE RSP renders black)",
                    "ram": "no expansion pak required (the writer moves the file table to 0x80700000)"},
         "wrestlers": ws}
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.wcw_worldtour_inventory",
                                 description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("rom", type=Path)
    ap.add_argument("--out", type=Path, help="write the JSON manifest here")
    a = ap.parse_args(argv)
    rom = n64_rom.read(a.rom)
    m = inventory(rom, a.rom)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    print(json.dumps({k: m[k] for k in ("build", "profile", "layout", "file_table", "roster")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
