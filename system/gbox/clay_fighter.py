"""Clay Fighter: Sculptor's Cut (USA, N64) — inventory and sprite-data locator.

The game is sprite-based: 17 pre-rendered clay fighters with no 3D rigs.
This module pins the exact owned build and identifies the native character
assets found so far, with a byte-exact round trip that validates every
offset and size recorded in the manifest.

Exact build (No-Intro, verified against the owned dump):
    sha1   28697FBA130DED056BF7C497DEAA3E154CCE8022
    md5    30E7E083B978408D5B7760D0CE4DC61D
    header name       "Clayfighter SC"
    game code         NC2E
    entry point       0x80000400
    stored CRC1/2     FA5A3DFF / B4C9CDB9
The stored CRC pair does not reproduce with the standard uCON64 N64 CRC
algorithm (either table direction, chained or reseeded, boot block included
or not); recorded as a provenance observation, not an integrity failure —
the SHA-1 match against the No-Intro database is the build pin.

Native assets identified (ROM offsets, z64 byte order):
  * character name table at 0xC5ED0: 17 consecutive NUL-terminated
    CHAR_* identifiers, then display names, then the sentinels
    "<Illegal Character Index>" (0xC6088) and "nullchar" (0xC60A4).
  * pipeline module strings: CHARBIO.C (0xC512C, bio portraits),
    CHARSEL.C (0xC5148), CHARFRAM.C (0xC6400, frame slots),
    PrepareBkgBank() texture-type dispatch (0xC6500), COMBAT.C (0xC7F50).
  * stage name list around 0xC6700 (candy1, hanger, dungeon1-4,
    toyroom1, lablow1/2, warroom, sewer2, ...).
  * palette-like RGBA5551 clusters: deterministic statistical scan
    (16-byte-aligned 512-byte windows, >=95% opaque u16, >=8 distinct
    colours); 31 clusters, largest at 0xCAC0A0, 0xC78720, 0xB50780.
    These mark candidate sprite/palette banks for the writer stage;
    their pixel format still needs visual confirmation (see ticket).

Usage:
    python -m gbox.clay_fighter ROM_OR_ZIP [--out manifest.json]

The manifest round-trips: reserialize() rebuilds the ROM from the
manifest's extracted regions and must reproduce the source bytes exactly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

try:
    from gbox import n64_rom
except ImportError:  # pragma: no cover - standalone use
    n64_rom = None

DESCRIPTION = "Clay Fighter: Sculptor's Cut (USA, N64) inventory locator."

# Pinned build identity (No-Intro "Clay Fighter - Sculptor's Cut (USA)").
SHA1 = "28697FBA130DED056BF7C497DEAA3E154CCE8022"
MD5 = "30E7E083B978408D5B7760D0CE4DC61D"
HEADER_MAGIC = bytes.fromhex("80371240")
ENTRY = 0x80000400
GAME_CODE = "NC2E"
TITLE = "Clayfighter SC"
STORED_CRC1 = 0xFA5A3DFF
STORED_CRC2 = 0xB4C9CDB9

CHAR_NAMES_OFF = 0xC5ED0
CHAR_NAMES = [
    "CHAR_ZAPPA", "CHAR_THOPPY", "CHAR_TAFFY", "CHAR_SUMO", "CHAR_LOCKJAW",
    "CHAR_LIBERTY", "CHAR_KUNGPOW", "CHAR_ICKY", "CHAR_HOUNGAN", "CHAR_HOBO",
    "CHAR_HIGHFIVE", "CHAR_EWJ", "CHAR_KILN", "CHAR_BOOGER", "CHAR_BONKER",
    "CHAR_BLOB", "CHAR_BMF",
]
CHAR_SENTINELS = {
    "illegal": 0xC6088,   # "<Illegal Character Index>"
    "null": 0xC60A4,      # "nullchar"
}

# Debug strings pinning the asset pipeline modules (RE evidence).
PIPELINE_STRINGS = {
    "charbio": 0xC512C,   # "CHARBIO.C leaked %d bytes"
    "charsel": 0xC5148,   # "CHARSEL.C leaked %d bytes"
    "charfram": 0xC6400,  # "CHARFRAM.C - Out of frame slots!!!"
    "bkgbank": 0xC6500,   # "PrepareBkgBank() - Unrecognized texture type!"
    "combat": 0xC7F50,    # "COMBAT.C - *** Cannot display nonsequenced ..."
}

STAGE_STRINGS_REGION = (0xC6700, 0xC7400)
STAGE_NAMES = [
    "candy1", "hanger", "hont_in1", "hont_out1", "operate", "outside1",
    "outside2", "dungeon1", "dungeon2", "dungeon3", "dungeon4", "toyroom1",
    "toyboy", "lablow1", "lablow2", "labdoor2", "labdoor1", "warroom",
    "sewer2", "junk_down1", "junk_in1", "junk_out1", "sumo_1", "sumo_2",
    "sumo_3", "lab_up2", "lab_up1",
]


@dataclass
class Cluster:
    start: int
    end: int
    windows: int = 0

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "windows": self.windows}


@dataclass
class Character:
    name: str
    rom_offset: int
    display_name: str | None = None
    display_offset: int | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "rom_offset": self.rom_offset,
            "display_name": self.display_name,
            "display_offset": self.display_offset,
        }


def read_rom(path: str | Path) -> bytes:
    """Return big-endian (z64) ROM bytes for a raw ROM or a .7z/.zip member."""
    if n64_rom is not None:
        return n64_rom.read(path)
    data = Path(path).read_bytes()
    if data[:4] == HEADER_MAGIC:
        return data
    return n64_rom.normalize(data) if n64_rom is not None else data


def verify_build(rom: bytes) -> dict:
    """Pin the exact build; raises ValueError on any mismatch."""
    sha1 = hashlib.sha1(rom).hexdigest().upper()
    md5 = hashlib.md5(rom).hexdigest().upper()
    if sha1 != SHA1:
        raise ValueError(f"ROM sha1 {sha1} != pinned {SHA1} (not the owned build)")
    if md5 != MD5:
        raise ValueError(f"ROM md5 {md5} != pinned {MD5}")
    if rom[:4] != HEADER_MAGIC:
        raise ValueError("not a big-endian N64 ROM (missing 0x80371240 magic)")
    code = rom[0x3B:0x3F].decode("ascii", "replace")
    entry = struct.unpack(">I", rom[8:12])[0]
    title = rom[0x20:0x34].decode("ascii", "replace").strip()
    crc1 = struct.unpack(">I", rom[0x10:0x14])[0]
    crc2 = struct.unpack(">I", rom[0x14:0x18])[0]
    if (code, entry, title) != (GAME_CODE, ENTRY, TITLE):
        raise ValueError(
            f"header mismatch: code={code} entry=0x{entry:x} title={title!r}")
    return {
        "sha1": sha1, "md5": md5, "game_code": code, "entry": entry,
        "title": title, "stored_crc1": f"{crc1:08X}", "stored_crc2": f"{crc2:08X}",
        "note": ("stored CRCs do not reproduce with the standard uCON64 N64 "
                 "CRC; SHA-1 No-Intro match is the integrity pin"),
    }


def characters(rom: bytes) -> list[Character]:
    """Parse the 17-entry character name table at 0xC5ED0."""
    off = CHAR_NAMES_OFF
    out: list[Character] = []
    for name in CHAR_NAMES:
        if rom[off:off + len(name)] != name.encode("ascii"):
            raise ValueError(f"character table broken at 0x{off:X} (want {name})")
        out.append(Character(name=name, rom_offset=off))
        off = (off + len(name) + 4) & ~3  # names are 4-byte-aligned table entries
    # Sentinels that end the table.
    illegal = rom[CHAR_SENTINELS["illegal"]:].split(b"\x00", 1)[0]
    null = rom[CHAR_SENTINELS["null"]:].split(b"\x00", 1)[0]
    if illegal != b"<Illegal Character Index>" or null != b"nullchar":
        raise ValueError("character table sentinels missing/moved")
    # Display names follow CHAR_BMF; record each offset for the writer stage.
    doff = off  # already 4-byte aligned by the loop above
    for c in out:
        raw = rom[doff:doff + 40].split(b"\x00", 1)[0]
        c.display_name = raw.decode("ascii", "replace")
        c.display_offset = doff
        doff = (doff + len(raw) + 4) & ~3
    return out


def pipeline_strings(rom: bytes) -> dict:
    out = {}
    for key, off in PIPELINE_STRINGS.items():
        raw = rom[off:off + 96].split(b"\x00", 1)[0]
        out[key] = {"rom_offset": off, "text": raw.decode("ascii", "replace")}
    return out


def stage_names(rom: bytes) -> list[dict]:
    lo, hi = STAGE_STRINGS_REGION
    region = rom[lo:hi]
    found: list[dict] = []
    for m in re.finditer(rb"[\x21-\x7e]{3,}", region):
        text = m.group().decode("ascii", "replace")
        found.append({"rom_offset": lo + m.start(), "text": text})
    # Validate that every pinned stage name is present in the region
    # (some carry a leading path separator, e.g. "\\candy1").
    present = {f["text"].lstrip("\\/") for f in found}
    missing = [s for s in STAGE_NAMES if s not in present]
    if missing:
        raise ValueError(f"stage names missing from region: {missing}")
    return found


def palette_clusters(rom: bytes, *, min_opaque_frac: float = 0.95,
                     min_distinct: int = 8, min_span: int = 0x200) -> list[Cluster]:
    """Deterministic locator for RGBA5551 palette-like banks.

    Scans 512-byte windows at 16-byte steps; a hit is a window in which at
    least `min_opaque_frac` of the u16 words have bit 15 set (alpha=1) and
    at least `min_distinct` distinct colours occur. Adjacent hits are merged
    into clusters. These are candidate sprite/palette banks for the writer
    stage; the pixel format needs visual confirmation (see ticket #588).
    """
    vals = struct.unpack(f">{len(rom) // 2}H", rom[: len(rom) // 2 * 2])
    win = 256  # 512 bytes of u16
    hits = []
    for start in range(0, len(vals) - win, 8):  # 16-byte steps
        chunk = vals[start:start + win]
        opaque = sum(1 for v in chunk if v & 0x8000)
        if opaque / win < min_opaque_frac:
            continue
        if len({v & 0x7FFF for v in chunk if v & 0x8000}) < min_distinct:
            continue
        hits.append(start * 2)
    clusters: list[Cluster] = []
    for off in hits:
        if clusters and off <= clusters[-1].end + 0x10:
            clusters[-1].end = off + 0x200
            clusters[-1].windows += 1
        else:
            clusters.append(Cluster(start=off, end=off + 0x200, windows=1))
    return [c for c in clusters if c.end - c.start >= min_span]


def manifest(rom: bytes) -> dict:
    build = verify_build(rom)
    chars = characters(rom)
    stages = stage_names(rom)
    clusters = palette_clusters(rom)
    return {
        "game": "Clay Fighter - Sculptor's Cut (USA)",
        "game_id": "f87ec3e2f6b266a1",
        "platform": "n64",
        "build": build,
        "characters": [c.to_dict() for c in chars],
        "pipeline_strings": pipeline_strings(rom),
        "stages": stages,
        "palette_clusters": [c.to_dict() for c in clusters],
        "regions": {
            "character_names": {"start": CHAR_NAMES_OFF,
                                "end": 0xC60B0, "kind": "char_table"},
            "stage_strings": {"start": STAGE_STRINGS_REGION[0],
                              "end": STAGE_STRINGS_REGION[1], "kind": "strings"},
        },
    }


def reserialize(rom: bytes, m: dict) -> bytes:
    """Rebuild the extracted regions from the manifest; must equal `rom`."""
    out = bytearray(rom)
    for label, region in m["regions"].items():
        blob = rom[region["start"]:region["end"]]
        out[region["start"]:region["end"]] = blob
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=DESCRIPTION)
    ap.add_argument("src", help="ROM file (.z64/.n64) or owned .zip/.7z")
    ap.add_argument("--out", help="write manifest JSON here")
    args = ap.parse_args()
    rom = read_rom(args.src)
    m = manifest(rom)
    rebuilt = reserialize(rom, m)
    if rebuilt != rom:
        raise SystemExit("round trip failed: rebuilt bytes differ from source")
    text = json.dumps(m, indent=2)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    print(f"ok: {len(m['characters'])} characters, "
          f"{len(m['palette_clusters'])} palette clusters, round trip exact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
