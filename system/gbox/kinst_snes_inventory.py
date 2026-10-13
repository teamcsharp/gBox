"""Killer Instinct (USA) (Rev 1) (SNES) owned-source inventory.

Resolves the exact owned build from its HyperSpin zip, verifies the headerless
.sfc against the No-Intro record, parses the SNES header, and records the
container layout and candidate sprite-data regions that the analysis stage will
decode.  The game stores pre-rendered CGI sprites in a custom compressed format
(not standard SNES 2bpp/4bpp tiles), so this module does not attempt to draw
anything; it just bounds where the artwork lives.

CLI:
    python -m gbox.kinst_snes_inventory SRC [--out manifest.json]
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import struct
import zipfile
import zlib
from pathlib import Path

GAME_ID = "86cc5716ca08db6e"
TITLE = "Killer Instinct (USA) (Rev 1)"

# No-Intro / public checksums for the headerless .sfc inside the zip.
KNOWN = {
    "sha1": "d31ae8e41c743c9ad8b6d43bbbbe660151f052df",
    "md5": "c9b698cf98f1aede7a87c1e449384632",
    "crc32": "09e9a04e",
    "size": 4 * 1024 * 1024,
}

ROSTER = [
    "Jago",
    "Sabrewulf",
    "Glacius",
    "Chief Thunder",
    "Black Orchid",
    "Spinal",
    "Fulgore",
    "T.J. Combo",
    "Cinder",
    "Riptor",
    "Eyedol",
]

PLATFORM = {
    "machine": "Super Nintendo Entertainment System",
    "cpu": "Ricoh 5A22 @ 3.58 MHz",
    "mode": "HiROM FastROM (map mode 0x31)",
    "coprocessor": "none (cartridge type 0x00)",
    "video": "pre-rendered 2D sprites, custom compressed; SNES PPU modes vary per screen",
    "audio": "S-SMP",
    "year": 1995,
    "mfg": "Rare / Nintendo (Midway license)",
}


class RomError(ValueError):
    """Raised when the supplied file is not the expected owned build."""


def _read_sfc(src: Path) -> tuple[bytes, str]:
    """Return the ROM bytes and the inner filename.  Accepts a zip or a bare .sfc."""
    src = Path(src)
    if src.suffix.lower() == ".zip":
        data = src.read_bytes()
        with zipfile.ZipFile(src) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if len(names) != 1:
                raise RomError(f"expected one file in zip, got {names}")
            rom = zf.read(names[0])
        return rom, names[0]
    rom = src.read_bytes()
    return rom, src.name


def parse_header(rom: bytes) -> dict:
    """Parse the SNES header at the HiROM location 0xFFB0."""
    base = 0xFFB0
    if len(rom) < base + 0x40:
        raise RomError("ROM too short for SNES header")
    title = rom[base + 0x10 : base + 0x25].rstrip(b"\x00").decode("ascii", "replace").strip()
    map_mode = rom[base + 0x25]
    rom_type = rom[base + 0x26]
    rom_size_code = rom[base + 0x27]
    ram_size_code = rom[base + 0x28]
    version = rom[base + 0x2B]
    checksum_comp, checksum = struct.unpack_from(">HH", rom, base + 0x2C)
    reset = struct.unpack_from("<H", rom, base + 0x3C)[0]
    return {
        "title": title,
        "map_mode": f"0x{map_mode:02x}",
        "cartridge_type": f"0x{rom_type:02x}",
        "rom_size_code": f"0x{rom_size_code:02x}",
        "ram_size_code": f"0x{ram_size_code:02x}",
        "version": version,
        "checksum": f"0x{checksum:04x}",
        "checksum_complement": f"0x{checksum_comp:04x}",
        "checksum_ok": (checksum ^ checksum_comp) == 0xFFFF,
        "native_reset_vector": f"0x{reset:04x}",
        "mirrored": rom[base + 0x24] == 0x33,
    }


def identity(rom: bytes) -> dict:
    """Hashes and known-identity check for the normalized .sfc."""
    sha1 = hashlib.sha1(rom).hexdigest()
    md5 = hashlib.md5(rom).hexdigest()
    crc32 = f"{zlib.crc32(rom) & 0xFFFFFFFF:08x}"
    return {
        "size": len(rom),
        "sha1": sha1,
        "md5": md5,
        "sha256": hashlib.sha256(rom).hexdigest(),
        "crc32": crc32,
        "known": sha1 == KNOWN["sha1"] and md5 == KNOWN["md5"] and crc32 == KNOWN["crc32"] and len(rom) == KNOWN["size"],
    }


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in collections.Counter(data).values())


def entropy_profile(rom: bytes, block: int = 64 * 1024) -> list[dict]:
    rows = []
    for i in range(0, len(rom), block):
        blk = rom[i : i + block]
        if not blk:
            continue
        rows.append({
            "start": hex(i),
            "end": hex(i + len(blk)),
            "entropy": round(entropy(blk), 3),
            "zero_frac": round(blk.count(0) / len(blk), 4),
        })
    return rows


def classify_regions(profile: list[dict], high: float = 7.2, structured_max_zero: float = 0.35) -> list[dict]:
    """Merge consecutive profile blocks into empty / structured / high_entropy regions.

    High-entropy regions are likely compressed sprite/audio data; structured
    regions are code/tables; empty regions are all-zero padding.
    """
    regions: list[dict] = []
    for row in profile:
        if row["zero_frac"] >= 0.999:
            kind = "empty"
        elif row["entropy"] >= high:
            kind = "high_entropy"
        elif row["zero_frac"] >= structured_max_zero:
            kind = "sparse"
        else:
            kind = "structured"
        if regions and regions[-1]["kind"] == kind:
            regions[-1]["end"] = row["end"]
            regions[-1]["blocks"] += 1
        else:
            regions.append({
                "kind": kind,
                "start": row["start"],
                "end": row["end"],
                "blocks": 1,
            })
    return regions


def summarize_regions(regions: list[dict]) -> dict:
    return {
        "by_kind": {
            kind: len([r for r in regions if r["kind"] == kind])
            for kind in ("empty", "sparse", "structured", "high_entropy")
        },
        "largest_high_entropy": max(
            ((r["start"], r["end"]) for r in regions if r["kind"] == "high_entropy"),
            default=(None, None),
            key=lambda x: int(x[1], 16) - int(x[0], 16) if x[0] else 0,
        ),
    }


def inventory(src: Path) -> dict:
    rom, inner_name = _read_sfc(src)
    ident = identity(rom)
    if not ident["known"]:
        raise RomError(
            f"{src} does not match the owned No-Intro build "
            f"(sha1 {ident['sha1']} != {KNOWN['sha1']})"
        )
    header = parse_header(rom)
    profile = entropy_profile(rom)
    regions = classify_regions(profile)
    region_summary = summarize_regions(regions)
    manifest = {
        "game_id": GAME_ID,
        "title": TITLE,
        "source": {
            "path": str(src),
            "inner_file": inner_name,
            "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
            "bytes": src.stat().st_size,
        },
        "rom": ident,
        "header": header,
        "platform": PLATFORM,
        "launch": {
            "core": "retroarch/snes9x",
            "bios_required": False,
            "save": "none",
            "audio": "2% on agent Windows tests",
            "video": "NTSC 60 Hz",
        },
        "container": {
            "kind": "zip",
            "contents": [inner_name],
            "rom_size": ident["size"],
            "map": "HiROM",
        },
        "characters": {
            "playable": ROSTER[:10],
            "boss": ROSTER[10],
            "total_spritesets": None,  # populated by analysis after decoding
        },
        "artwork": {
            "note": "pre-rendered CGI sprites stored in a custom compressed format; not plain SNES tiles",
            "candidate_regions": regions,
            "region_summary": region_summary,
            "entropy_profile": profile,
        },
    }
    return manifest


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    m = inventory(Path(a.src))
    text = json.dumps(m, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    summary = {
        "known": m["rom"]["known"],
        "header": m["header"],
        "regions": m["artwork"]["region_summary"],
        "characters": m["characters"],
    }
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
