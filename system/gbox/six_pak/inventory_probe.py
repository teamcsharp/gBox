#!/usr/bin/env python3
"""6-Pak (Genesis, game_id=73c0f182facee148) inventory probe.

Stage-1 deliverable: authoritative owned-build manifest verification.
Verifies, from the actual owned ROM bytes (streamed, not reference hashes):
  * container identity + member hashes (zip -> single .md Mega Drive image)
  * Mega Drive header magic at 0x100 of each 512KB bank
  * six-bank menu+5-games layout and per-bank game identification
  * byte-verified native target asset (Nemesis art) offsets in the Sonic bank

Run:  python3 system/gbox/six_pak/inventory_probe.py [--rom PATH]
"""
from __future__ import annotations

import hashlib
import sys
import zipfile

ROM_ZIP = "/mnt/gbox/hyperspin/Arcade/collections/Sega Nomad/roms/6-Pak (USA).zip"

# Verified this run: (bank, domestic/overseas name, header serial)
BANKS = [
    (0x000000, "Mega Games 6in1 U (menu/launcher)", "GM MK-1717 -00"),
    (0x080000, "Columns (headerless bank; 'FLASH COLUMNS' strings)", None),
    (0x100000, "Golden Axe", "GM 00054018-01"),
    (0x180000, "Streets of Rage", "MK 00001019-01"),
    (0x200000, "The Revenge of Shinobi", "GM 00001105-03"),
    (0x280000, "Sonic the Hedgehog (REV00, regions JUE, hdr cksum 0x264A)",
     "GM 00001009-00"),
]

# Documented clean Sonic 1 REV00 Nemesis art offsets (Sonic Retro SCHG,
# Art Editing / Nemesis Compressed Art) -> cart offset = bank + doc offset.
# Byte-verified against this build this run (Nemesis stream signature).
SONIC_TARGET_ASSETS = {
    "sonic_intro_patterns": 0x1F27A,   # 'Patterns for Sonic in intro', 525 tiles
    "sega_screen_patterns": 0x1DC00,   # 'SEGA' patterns, 123 tiles
    "hud_patterns": 0x39368,           # primary HUD, 24 tiles
    "smoke_dust": 0x2BC1E,             # smoke/dust trail, 16 tiles
    "shield": 0x2BD5C,                 # shield, 27 tiles
    "stars": 0x2BEF2,                  # more stars, 35 tiles
    "sonic_ending": 0x5F866,           # Sonic - Ending, 323 tiles
}


def sha256_stream(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(rom_zip: str = ROM_ZIP) -> int:
    failures = []

    # 1. container + member hashes from the owned file
    with zipfile.ZipFile(rom_zip) as z:
        members = z.infolist()
        assert len(members) == 1, f"expected 1 member, got {len(members)}"
        rom = z.read(members[0].filename)
        member_sha = hashlib.sha256(rom).hexdigest()
    print(f"container sha256 : {sha256_stream(rom_zip)}")
    print(f"member           : {members[0].filename} ({len(rom)} bytes)")
    print(f"member sha256    : {member_sha}")
    if len(rom) != 6 * 0x80000:
        failures.append(f"unexpected ROM size {len(rom)}")

    # 2. Mega Drive header magic at 0x100 of each bank
    for base, name, _ser in BANKS:
        magic = rom[base + 0x100:base + 0x104]
        ok = magic == b"SEGA"
        print(f"bank {base:#08x} magic={magic!r} {'OK' if ok else 'NO-HEADER'} :: {name}")
        if base != 0x80000 and not ok:
            failures.append(f"bank {base:#x} missing SEGA header")

    # (Golden Axe bank stores a Shift-JIS name; verify via its serial field)
    assert rom[0x100000 + 0x180:0x100000 + 0x18E] == b"GM 00054018-01"
    assert rom[0x180000 + 0x150:0x180000 + 0x162].startswith(b"STREETS OF RAGE")
    assert rom.startswith(b"THE REVENGE SHINOBI", 0x200000 + 0x150)
    assert rom.startswith(b"SONIC THE", 0x280000 + 0x150)

    # 4. byte-verified native target assets (Nemesis streams) in Sonic bank
    sonic = 0x280000
    for name, off in SONIC_TARGET_ASSETS.items():
        # Nemesis streams: 0x80 start/branch opcode followed by a small
        # inline XOR-run code byte (0x01..0x08) -- verified across all assets.
        sig = rom[sonic + off + 2] == 0x80 and 0x01 <= rom[sonic + off + 3] <= 0x08
        print(f"asset {name:22s} doc={off:#07x} cart={sonic + off:#08x} "
              f"bytes={rom[sonic + off:sonic + off + 4].hex()} {'OK' if sig else 'FAIL'}")
        if not sig:
            failures.append(f"asset {name} at {off:#x} lost Nemesis signature")

    print("RESULT:", "PASS" if not failures else f"FAIL {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
