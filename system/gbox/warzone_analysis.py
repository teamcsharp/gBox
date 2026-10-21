"""WWF War Zone (USA) N64 analysis.

Static analysis of the exact owned build (zip sha256
355c6474a3555f24c3065c3a61e2d35999941c21937e50aaf8933f962878bff7) that:

* confirms the ROM is mapped at virtual 0x80000000, so a data pointer
  ``0x80XXXXXX`` in code addresses ROM offset ``0xXXXXXX``;
* locates the code/data references into the wrestler name bank and the move
  table (the call sites a Ghidra pass must follow to reach the name-bank
  decoder and the character/asset loader);
* extracts the wrestler roster from the partially-encoded name bank;
* documents the name-bank record encoding and the debug-string table.

The wrestler name strings use a partial per-record encoding: printable ASCII
runs interleaved with opaque per-record bytes.  Most characters store as their
ASCII value, but characters adjacent to a space (and the space itself) are
replaced by 1-3 opaque bytes, so records are variable-length.  Goldust has no
clean ASCII run at all.  A full decode therefore needs the name-bank loader
disassembly (a Ghidra RDRAM image at base 0x80000000, entry 0x80000400).

Usage: python -m gbox.warzone_analysis SRC
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

from . import n64_rom

GAME_ID = "55106ab284192c75"
TITLE = "WWF War Zone (USA)"

# The game maps the ROM image at virtual 0x80000000: ROM offset X is addressed
# as 0x80XXXXXX (verified against the venue pointer 0x80BF2E00 held at ROM
# 0xE2CBC, which addresses the venue bank at ROM 0xBF2E00).
VIRTUAL_BASE = 0x80000000

NAME_BANK = (0xBE7900, 0xBEA600)      # wrestler/announcer name strings
MOVE_TABLE = (0xB80BF4, 0xB82B34)     # 0x20-byte move-name records
VENUE_BANK = 0xBF2E00                 # string bank referenced by u32 at VENUE_REF
VENUE_REF = 0xE2CBC                   # code/data word holding 0x80BF2E00
DEBUG_STRINGS = 0x521000              # "z202"/"z203"... 0x20-byte records
CODE_LO = 0x1000                      # first scanned word of the code region

# Clean ASCII fragments that pin each wrestler's name record in the name bank.
# A wrestler may have several fragments (first/last name, nickname) or none
# clean (Goldust).  Fragments are ground truth, not a decode.
ROSTER_FRAGMENTS: list[tuple[str, tuple[str, ...]]] = [
    ("BRITISH BULLDOG", ("BRITIS", "BULLDOG")),
    ("SHAWN MICHAELS", ("AWN", "MIC", "ZELS")),
    ("OWEN HART", ("OWEN",)),
    ("STONE COLD", ("ONE COLD", "TEVE", "AU")),
    ("FAAROOQ", ("FAAROOQ",)),
    ("MANKIND", ("KIND",)),
    ("AHMED JOHNSON", ("AHME", "JOHNSON")),
    ("ROCKY MAIVIA", ("ROCKY", "IVIA")),
    ("THE ROCK", ("_THE",)),
    ("HUNTER HEARST HELMSLEY", ("HUNTE", "HELMSLE")),
    ("UNDERTAKER", ("TAK",)),
    ("KANE", ("KANE",)),
    ("DUDE LOVE", ("DUDE LO",)),
    ("CACTUS JACK", ("CACTUS JA",)),
    ("CAW PLAYER1", ("PLAYER1",)),
]


def virtual(rom_offset: int) -> int:
    """ROM offset to the virtual address the code uses (0x80XXXXXX)."""
    return VIRTUAL_BASE + rom_offset


def rom_offset(vaddr: int) -> int:
    """Virtual 0x80XXXXXX address back to its ROM offset."""
    return vaddr & 0xFFFFFF


def find_pointers_into(rom: bytes, lo: int, hi: int, start: int = CODE_LO) -> list[tuple[int, int]]:
    """(src_off, value) for every 4-aligned u32 in [start, end) whose value lies
    in the virtual address range [lo, hi] (inclusive)."""
    hits: list[tuple[int, int]] = []
    for off in range(start, len(rom) - 3, 4):
        v = struct.unpack(">I", rom[off:off + 4])[0]
        if lo <= v <= hi:
            hits.append((off, v))
    return hits


def name_bank_refs(rom: bytes) -> list[tuple[int, int]]:
    """Code/data words that address a string inside the wrestler name bank."""
    return find_pointers_into(rom, virtual(NAME_BANK[0]), virtual(NAME_BANK[1]))


def move_table_refs(rom: bytes) -> list[tuple[int, int]]:
    """Code/data words that address a string inside the move-name table."""
    return find_pointers_into(rom, virtual(MOVE_TABLE[0]), virtual(MOVE_TABLE[1]))


def venue_pointer(rom: bytes) -> dict:
    """The venue-bank pointer word and whether it matches the mapping model."""
    ref = struct.unpack(">I", rom[VENUE_REF:VENUE_REF + 4])[0]
    return {
        "pointer_at": VENUE_REF,
        "pointer_value": hex(ref),
        "bank": VENUE_BANK,
        "matches_virtual_mapping": ref == virtual(VENUE_BANK),
    }


def roster_locations(rom: bytes) -> dict[str, list[int]]:
    """Wrestler name -> ROM offsets of each clean fragment in the name bank."""
    out: dict[str, list[int]] = {}
    for name, frags in ROSTER_FRAGMENTS:
        locs: list[int] = []
        for frag in frags:
            off = rom.find(frag.encode(), NAME_BANK[0], NAME_BANK[1])
            if off >= 0:
                locs.append(off)
        out[name] = locs
    return out


def debug_string_table(rom: bytes, base: int = DEBUG_STRINGS) -> dict:
    """The "zNNN" debug/stage-id table: 0x20-byte records, ``z<digits>\\r\\n`` +
    zero padding.  Returns the parsed ids and the last clean offset."""
    ids: list[dict] = []
    off = base
    while off < base + 0x2000:
        rec = rom[off:off + 0x20]
        if rec[0] != 0x7A:  # records start with 'z'
            break
        end = rec.find(b"\r\n")
        if end < 0:
            break
        ids.append({"offset": off, "id": rec[:end].decode("latin1")})
        off += 0x20
    return {"base": base, "stride": 0x20, "count": len(ids), "ids": ids}


def analysis(rom_path: str | Path) -> dict:
    """Full analysis report for the exact owned build."""
    rom = n64_rom.read(rom_path)
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "mapping": {
            "virtual_base": hex(VIRTUAL_BASE),
            "model": "ROM offset X is addressed as 0x80XXXXXX",
            "venue_pointer": venue_pointer(rom),
        },
        "name_bank": {
            "region": [NAME_BANK[0], NAME_BANK[1]],
            "refs": name_bank_refs(rom),
            "roster": roster_locations(rom),
            "encoding": (
                "partial per-record: printable ASCII runs interleaved with "
                "opaque bytes; space and adjacent letters may be replaced by "
                "1-3 opaque bytes, so records are variable-length; Goldust has "
                "no clean run.  Full decode requires the loader disassembly."
            ),
        },
        "move_table": {"region": [MOVE_TABLE[0], MOVE_TABLE[1]],
                       "refs": move_table_refs(rom)},
        "debug_strings": debug_string_table(rom),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="WWF War Zone (USA) N64 analysis")
    ap.add_argument("src", help="path to the owned .zip/.7z/.z64/.n64")
    ap.add_argument("--out", help="write the analysis JSON here")
    args = ap.parse_args(argv)
    rep = analysis(args.src)
    print(json.dumps(rep, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(rep, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
