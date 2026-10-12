"""Mario Kart 64 (N64): owned-source inventory for the favorite-queue character replacement.

The favorite is "Mario Kart 64 (USA)" (game 7f5c674909d63b5f): a hyperspin zip holding one
byteswapped .n64 (v64 halfword order) ROM whose z64-normalized sha1 579c48e2... is No-Intro
"Mario Kart 64 (USA)" and the n64decomp/mk64 `mk64.us.z64` (the single US revision).
Header: image "MARIOKART64", manufacturer 'N', cart id "KT", country 'E' (USA), revision 0.
The stored boot CRC pair is (0x00001446, 0x3E5055B6); the CIC-6102 algorithm over
0x1000..0x101000 reproduces the stored CRC2, so CIC = 6102.

Container layout: zip -> one 12 MiB .n64 ROM; there is no inner filesystem. Assets are
sixteen link-time segments 0x0..0xF (mk64 wiki: seg 0 code, seg 1 gfx pool, seg 2 fonts/UI/
animations/vertices/displaylists, seg 3 common+course textures, seg 4/7 course geography
vertices/displaylists, seg 5 course textures, seg 6 startup logo + course models/actors,
seg 9 course texture-list offsets, seg B trophy/podium, seg D common course data, seg F
temporary MIO0 buffer + course collisions). Thousands of payloads are MIO0 streams (probed:
all structurally valid headers). Drivers are 3D F3DEX display-list models with per-driver
texture/animation banks - not 2D sprites. Per-driver segment/offset mapping is the analysis
stage; this module only proves the owned build, its launch facts and the compression/container
shape.

Roster (8): Mario, Luigi, Peach, Toad, Yoshi, Donkey Kong, Wario, Bowser - the exact set named
by n64decomp/mk64 `assets/character_select/*.json`, which builds from this same sha1.

CLI: python -m gbox.mk64_inventory SRC [--out manifest.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from . import n64_rom

GAME_ID = "7f5c674909d63b5f"
# sha1 of the z64-normalized ROM -> build (owned file hashed on the Spark, #1409).
KNOWN = {
    "579c48e211ae952530ffc8738709f078d5dd215e": {
        "code": "NKT", "region": "US", "version": 0,
        "name": "Mario Kart 64 (USA)", "decomp": "mk64.us.z64",
    },
}
COUNTRY = {"J": "JP", "E": "US", "P": "EU"}
# n64decomp/mk64 assets/character_select/*.json names for this build.
DRIVERS = ["mario", "luigi", "peach", "toad", "yoshi", "donkeykong", "wario", "bowser"]
SEGMENTS = {
    0: "game code", 1: "gfx pool", 2: "fonts/UI/animations/vertices/displaylists",
    3: "common + course textures", 4: "course geography vertices", 5: "course textures",
    6: "startup logo + course models/actors/paths", 7: "course displaylists", 8: "unused",
    9: "course texture-list offsets", 0xA: "unused", 0xB: "trophy/podium",
    0xC: "unused", 0xD: "common course data", 0xE: "unused", 0xF: "temp MIO0 buffer + collisions",
}


def identify(rom: bytes) -> dict:
    """Header identity on big-endian ROM bytes."""
    from .sm64_writer import crc6102
    crc = struct.unpack_from(">II", rom, 0x0C)
    country = rom[0x3E:0x3F].decode("ascii", "replace")
    cic = "unknown"
    # MK64 stores CRC2 = crc6102 over 0x1000..0x101000; CRC1 (0x1446) is the boot block sum.
    if len(rom) >= 0x101004 and crc6102(rom)[0] == crc[1]:
        cic = "6102"
    return {
        "size": len(rom),
        "title": rom[0x20:0x34].decode("ascii", "replace").strip(),
        "manufacturer": rom[0x3B:0x3C].decode("ascii", "replace"),
        "cart_id": rom[0x3C:0x3E].decode("ascii", "replace"),
        "country": COUNTRY.get(country, country),
        "version": rom[0x3F],
        "entry": hex(struct.unpack_from(">I", rom, 8)[0]),
        "header_crc": [hex(crc[0]), hex(crc[1])],
        "cic": cic,
        "md5": hashlib.md5(rom).hexdigest(),
        "sha1": hashlib.sha1(rom).hexdigest(),
        "sha256": hashlib.sha256(rom).hexdigest(),
        "known": KNOWN.get(hashlib.sha1(rom).hexdigest()),
    }


def mio0_streams(rom: bytes) -> dict:
    """Scan 4-aligned MIO0 headers and validate their {sizes, comp_off, uncomp_off} triple."""
    stats = {"count": 0, "valid": 0, "invalid": 0, "max_uncompressed": 0, "per_mb": {}}
    i = 0
    while True:
        j = rom.find(b"MIO0", i)
        if j == -1:
            break
        i = j + 1
        if j % 4 or j + 16 > len(rom):
            continue
        stats["count"] += 1
        size, comp_off, uncomp_off = struct.unpack_from(">III", rom, j + 4)
        if 0 < size <= 0x400000 and 0 < comp_off <= 0x400000 and 0 < uncomp_off <= 0x400000 \
                and comp_off % 4 == 0:
            stats["valid"] += 1
            stats["max_uncompressed"] = max(stats["max_uncompressed"], size)
        else:
            stats["invalid"] += 1
            continue
        mb = j // 0x100000
        stats["per_mb"][mb] = stats["per_mb"].get(mb, 0) + 1
    return stats


def markers(rom: bytes) -> dict:
    """Observed driver-ish ASCII markers; interpretation is the analysis stage."""
    out = {}
    for magic in (b"TKMK0000", b"MARIO", b"LUIGI", b"PEACH", b"TOAD", b"YOSHI", b"DONKEY",
                  b"WARIO", b"BOWSER"):
        out[magic.decode()] = rom.count(magic)
    return out


def inventory(src: Path) -> dict:
    src = Path(src)
    rom = n64_rom.read(src)
    ident = identify(rom)
    return {
        "game_id": GAME_ID,
        "source": {"path": str(src), "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                   "bytes": src.stat().st_size},
        "rom": ident,
        "launch": {
            "core": "retroarch/parallel_n64",
            "cic": ident["cic"],
            "video": "PAL 50 Hz" if ident["country"] == "EU" else "NTSC 60 Hz",
            "byte_order_source": "v64 (halfword-swapped .n64 in the zip)",
            "byte_order_working": "z64 (big-endian, normalized in memory)",
            "save": "not asserted this run (EEPROM/SRAM probe lives in boot code)",
        },
        "layout": {
            "container": "zip -> single .n64 ROM; no inner filesystem",
            "segments": SEGMENTS,
            "mio0": mio0_streams(rom),
            "markers": markers(rom),
        },
        "characters": {
            "kind": "3D F3DEX display-list models + per-driver texture/animation banks (not sprites)",
            "roster": DRIVERS,
            "roster_source": "n64decomp/mk64 assets/character_select (builds from this sha1)",
            "per_driver_mapping": "deferred to analysis stage",
        },
        "analysis_next": "map driver model/texture/animation banks to MIO0 streams per segment "
                         "(mk64 decomp symbol tables apply to this exact build)",
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = inventory(Path(a.src))
    text = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(json.dumps({k: m[k] for k in ("rom", "launch")} |
                     {"mio0": m["layout"]["mio0"], "roster": m["characters"]["roster"]},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
