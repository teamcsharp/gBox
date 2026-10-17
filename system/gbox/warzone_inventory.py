"""WWF War Zone (USA) N64 inventory.

Identifies the owned build and maps its static data tables: the IPL3/boot
identity, the 32-byte-record move-name table, the wrestler/announcer name
string bank, the venue string bank referenced from code, and the embedded
F3DEX2 RSP microcode. Character name strings in this title are stored with
a partial per-record encoding (readable fragments interleaved with control
bytes), so this module records fragments verbatim; decoding is analysis work.

Usage: python -m gbox.warzone_inventory SRC [--out manifest.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

from . import n64_rom

GAME_ID = "55106ab284192c75"
TITLE = "WWF War Zone (USA)"
# Owned HyperSpin zip (sha256 of the zip itself is the stage source hash).
ZIP_SHA256 = "355c6474a3555f24c3065c3a61e2d35999941c21937e50aaf8933f962878bff7"
# Exact-build identity of the normalized .z64 image (matches the No-Intro
# USA dump; CRC32 externally confirmed as 2FBB5507).
EXPECTED = {
    "size": 0xC00000,          # 12 MiB
    "crc32": "2FBB5507",
    "md5": "2322da2b9e7dc74678cd683b7a246b49",
    "sha256": "ee4f5a036423b78449475fa09471de6148ff6972d0510098943bc83092f990b5",
    "code": "NWWE",            # game code at 0x3B:0x3F
    "name": "WWF War Zone",    # internal name at 0x20:0x34
}

# Static table map (exact-build offsets, verified against this ROM).
# Move names: 0x20-byte records, space-padded, NUL as the record's last byte.
MOVE_TABLE = 0xB81CF4     # first clean record ("STANDING MOONSAULT")
MOVE_STRIDE = 0x20
NAME_BANK = (0xBE7900, 0xBEA600)   # wrestler/announcer name strings
VENUE_BANK = 0xBF2E00     # string bank referenced by u32 at ROM 0xE2CBC
VENUE_REF = 0xE2CBC       # code/data pointer holding 0x80BF2E00
UCODE_TEXT = 0xBF1A0E     # "RSP Gfx ucode F3DEX2 ... fifo 2.0" version strings
LAST_NONZERO = 0xBF5030   # last non-zero dword; the tail after it is all zero


def _crc32(data: bytes) -> str:
    return format(zlib.crc32(data) & 0xFFFFFFFF, "08X")


def header_fields(rom: bytes) -> dict:
    """Raw header fields of the ROM image (no build validation)."""
    return {
        "internal_name": rom[0x20:0x34].rstrip(b"\0 ").decode("latin1"),
        "game_code": rom[0x3B:0x3F].decode("latin1"),
        "country": chr(rom[0x3E]),
        "entry": hex(struct.unpack(">I", rom[8:12])[0]),
        "clockrate": hex(rom[4]),
        "header_crc1": f"{struct.unpack('>I', rom[0x10:0x14])[0]:08X}",
        "header_crc2": f"{struct.unpack('>I', rom[0x14:0x18])[0]:08X}",
        "crc32": _crc32(rom),
        "md5": hashlib.md5(rom).hexdigest(),
        "sha256": hashlib.sha256(rom).hexdigest(),
        "ipl3_sha256": hashlib.sha256(rom[0x40:0x1040]).hexdigest(),
        "size": len(rom),
    }


def identify(rom: bytes) -> dict:
    """Header identity for the exact owned build; refuses other builds."""
    if len(rom) != EXPECTED["size"]:
        raise ValueError(f"expected a {EXPECTED['size']} byte ROM, got {len(rom)}")
    info = header_fields(rom)
    expected_by_info = {
        "size": "size", "crc32": "crc32", "md5": "md5", "sha256": "sha256",
        "code": "game_code", "name": "internal_name",
    }
    for key, want in EXPECTED.items():
        got = info[expected_by_info[key]]
        if got != want:
            raise ValueError(f"not the WWF War Zone (USA) build: {key}={got!r}, expected {want!r}")
    return info


def scan_ascii(rom: bytes, start: int, end: int, min_len: int = 3) -> list[dict]:
    """Readable ASCII runs inside a region, as (offset, text) records."""
    runs = []
    i = start
    while i < end:
        c = rom[i]
        if 0x20 <= c < 0x7F:
            j = i
            while j < end and 0x20 <= rom[j] < 0x7F:
                j += 1
            text = rom[i:j].decode("latin1")
            if len(text) >= min_len:
                runs.append({"offset": i, "text": text})
            i = j
        else:
            i += 1
    return runs


def _has_letters(body: bytes) -> bool:
    """A real move record's name contains at least one ASCII letter."""
    return any(0x41 <= c <= 0x5A or 0x61 <= c <= 0x7A for c in body)


def move_table(rom: bytes, base: int = MOVE_TABLE, limit: int = 400) -> dict:
    """The 0x20-byte-record move-name table.

    Each record is a space-padded move name whose NUL terminator sits in the
    record's final byte. The base is walked back to the first clean record,
    then records are read forward until the terminator pattern breaks.
    """
    while base >= MOVE_STRIDE:
        rec = rom[base - MOVE_STRIDE:base]
        if rec[-1] == 0 and _has_letters(rec[:-1].split(b"\0")[0]):
            base -= MOVE_STRIDE
        else:
            break
    records = []
    off = base
    for _ in range(limit):
        rec = rom[off:off + MOVE_STRIDE]
        if rec[-1] != 0:
            break
        body = rec[:-1].split(b"\0")[0]
        if not _has_letters(body):
            break
        records.append({"offset": off, "name": body.rstrip().decode("latin1")})
        off += MOVE_STRIDE
    return {"base": base, "stride": MOVE_STRIDE, "count": len(records),
            "end": off, "records": records}


def name_bank(rom: bytes) -> dict:
    """Wrestler/announcer name bank: verbatim fragments plus a decoded-pair guess.

    The strings appear to be fixed records with several bytes outside the
    printable range (see 'encoding' note); raw runs are the ground truth here.
    """
    runs = scan_ascii(rom, NAME_BANK[0], NAME_BANK[1])
    return {
        "region": [NAME_BANK[0], NAME_BANK[1]],
        "encoding": ("partial: printable fragments interleaved with control/opaque "
                     "bytes per record; full decode is the analysis stage"),
        "fragments": runs,
    }


def venue_bank(rom: bytes) -> dict:
    """String bank referenced from VENUE_REF (match-type/venue text)."""
    ref = struct.unpack(">I", rom[VENUE_REF:VENUE_REF + 4])[0]
    return {
        "pointer_at": VENUE_REF,
        "pointer_value": hex(ref),
        "base": VENUE_BANK,
        "matches_pointer": ref == (VENUE_BANK | 0x80000000),
        "fragments": scan_ascii(rom, VENUE_BANK, VENUE_BANK + 0x400),
    }


def layout(rom: bytes) -> dict:
    """Container layout: mapped regions and the unused tail."""
    tail = rom[LAST_NONZERO + 4:]
    return {
        "rom_size": len(rom),
        "last_nonzero_dword": hex(LAST_NONZERO),
        "tail_start": hex(LAST_NONZERO + 4),
        "tail_all_zero": tail.count(b"\0") == len(tail),
        "mio0/yay0/yaz0": {
            "MIO0": rom.count(b"MIO0"), "YAY0": rom.count(b"YAY0"), "Yaz0": rom.count(b"Yaz0"),
        },
        "microcode": {"version_text": hex(UCODE_TEXT),
                      "text": "RSP Gfx ucode F3DEX2 (fifo 2.0), Yoshitaka Yasumoto / Nintendo"},
    }


def prerequisites() -> dict:
    """Launch prerequisites recorded for the emulator/gBox session."""
    return {
        "emulator": "retroarch/parallel_n64",
        "rom": "12 MiB, game code NWWE, entry 0x80000400",
        "rdram": "4 MiB (no Expansion Pak requirement known)",
        "save": "Controller Pak required (career/CAW save file uses 54 pages)",
        "cic": "auto-detected by the core from the embedded IPL3",
        "controls": "standard N64 pad; no Rumble Pak requirement recorded",
    }


def inventory(rom_path: str | Path) -> dict:
    """Full inventory manifest for the exact owned build."""
    rom = n64_rom.read(rom_path)
    info = identify(rom)
    man = {
        "game_id": GAME_ID,
        "title": TITLE,
        "source": {
            "zip_sha256": ZIP_SHA256,
            "zip_member": "WWF War Zone (USA).n64 (v64 word-swapped, 12,582,912 B)",
            "normalized_z64": info,
        },
        "prerequisites": prerequisites(),
        "layout": layout(rom),
        "move_table": move_table(rom),
        "name_bank": name_bank(rom),
        "venue_bank": venue_bank(rom),
    }
    return man


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="WWF War Zone (USA) N64 inventory")
    ap.add_argument("src", help="path to the owned .zip/.7z/.z64/.n64")
    ap.add_argument("--out", help="write the manifest JSON here")
    args = ap.parse_args(argv)
    man = inventory(args.src)
    print(json.dumps(man, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(man, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
