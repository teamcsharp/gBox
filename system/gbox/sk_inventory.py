"""Inventory for the owned Sonic & Knuckles lock-on build (favorite 286b3fae79e33f17).

The catalog labels this file "Sonic & Knuckles + Sonic the Hedgehog 2 (World)" but
the actual lock-on image is Sonic & Knuckles + Sonic the Hedgehog **1** REV00:
the attached segment header serial is "GM 00001009-00". S&K selects the lock-on
game by reading the serial string of the ROM mapped at 0x200000, so that serial is
the authoritative layout signal, not the catalog title.

Layout of the 0x280000-byte combined image (flat, no interleave):

    0x000000-0x1FFFFF  S&K (World) main program + assets (2 MiB)
    0x200000-0x27FFFF  Sonic 1 REV00 image (512 KiB of the 1 MiB REV00 ROM)

The S&K segment differs from the stock "Sonic & Knuckles (World)" dump in only a
few bytes (header checksum/end-address patched for the combined size, plus two
small patches), see segment_diff().

Character notes (2D sprite-based title, per stage-1 scope):
  * Playable character in this lock-on mode is Sonic in the Blue Sphere special
    stage; the S1 segment only contributes its header for lock-on detection.
  * The full playable roster (Sonic/Tails/Knuckles art, mappings, DPLC) lives in
    the S&K segment; exact table addresses are pinned in the analysis stage via
    the DPLC-loader xref probe (find_dplc_loaders).

CLI: python -m gbox.sk_inventory SRC [--out m.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zipfile
from pathlib import Path

ROM_EXT = (".bin", ".md", ".gen", ".smd")

SERIALS = {
    # serial string (at attached segment +0x180) -> lock-on game
    "GM 00001051-00": "sonic2",
    "GM MK-1079 -00": "sonic3",
    "GM 00001009-00": "sonic1",
}


class InventoryError(ValueError):
    pass


def read_rom(path: str | Path) -> tuple[bytes, dict]:
    """Load a flat Genesis image from a zip member or a raw file."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            names = [i for i in zf.infolist() if not i.is_dir()]
            if not names:
                raise InventoryError(f"zip has no members: {p}")
            name = names[0].filename
            d = zf.read(names[0])
    elif p.suffix.lower() in ROM_EXT:
        name, d = p.name, p.read_bytes()
    else:
        raise InventoryError(f"unsupported source: {p}")
    if len(d) < 0x200:
        raise InventoryError(f"file too small to be a Genesis image: {len(d)}")
    return d, {"member": name, "size": len(d)}


def header(d: bytes, base: int = 0) -> dict:
    h = d[base + 0x100 : base + 0x200]
    if h[:16] not in (b"SEGA GENESIS    ", b"SEGA MEGA DRIVE "):
        raise InventoryError(f"no Genesis header at 0x{base + 0x100:x}")
    return {
        "base": base,
        "console": h[0:16].decode("ascii"),
        "copyright": h[16:32].decode("ascii"),
        "domestic": h[32:80].decode("latin1").strip(),
        "overseas": h[80:128].decode("latin1").strip(),
        "serial": h[128:142].decode("ascii"),
        "checksum": h[142:144].hex(),
        "io_support": h[144:160].decode("ascii"),
        "rom_start": int.from_bytes(h[160:164], "big"),
        "rom_end": int.from_bytes(h[164:168], "big"),
        "region": h[240:243].decode("ascii"),
    }


def genesis_checksum(d: bytes, start: int = 0x200, end: int | None = None) -> int:
    """Big-endian 16-bit sum over the byte range, like the header field."""
    end = len(d) if end is None else end
    s = 0
    for i in range(start, min(end, len(d)) & ~1, 2):
        s = (s + (d[i] << 8 | d[i + 1])) & 0xFFFF
    return s


def lock_on(d: bytes) -> dict:
    """Identify the attached cartridge from its header serial at 0x200180."""
    if len(d) < 0x200200:
        return {"attached": None, "reason": "no attached segment"}
    serial = d[0x200180:0x20018E].decode("ascii")
    game = SERIALS.get(serial)
    return {"attached": game, "serial": serial, "source": "serial@0x200180"}


def segments(d: bytes) -> list[dict]:
    lo = lock_on(d)
    segs = [
        {
            "name": "sonic_and_knuckles",
            "offset": 0x000000,
            "size": 0x200000,
            "sha256": hashlib.sha256(d[0:0x200000]).hexdigest(),
            "header": header(d, 0),
        }
    ]
    if lo["attached"]:
        segs.append(
            {
                "name": lo["attached"],
                "offset": 0x200000,
                "size": len(d) - 0x200000,
                "sha256": hashlib.sha256(d[0x200000:]).hexdigest(),
                "header": header(d, 0x200000),
            }
        )
    return segs


def segment_diff(d: bytes, reference: bytes) -> dict:
    """First differing offsets vs a stock dump, plus the whole change count."""
    n = min(len(d), len(reference))
    diffs = [i for i in range(n) if d[i] != reference[i]]
    extra = abs(len(d) - len(reference))
    return {"diff_bytes": len(diffs) + extra, "first_offsets": [hex(x) for x in diffs[:16]], "len_diff": extra}


# S3K-style player DPLC loader: movea.l #ArtTbl,a2; add.w d0,d0; adda.w (a2,d0.w),a2;
# moveq #0,d5; move.b (a2)+,d5; subq.w #1,d5  -> the d0-indexed table read that picks
# each mapping frame's DMA queue. Search is loose on purpose (a probe, not a proof);
# the analysis stage pins the exact address from Ghidra.
DPLC_LOADER = re.compile(
    rb"\x45\xf9(....)\xd0\x40\xd4\xf2\x00\x00\x7a\x00\x1a\x1a\x53\x45", re.S
)
# move.l #Map,obMap(a0); move.w #ArtTile,obGfx(a0) (S3K object offsets $C/$A)
MAP_GFX = re.compile(rb"\x21\x7c(....)\x00\x0c\x31\x7c(..)\x00\x0a", re.S)


def find_dplc_loaders(d: bytes, lo: int = 0, hi: int | None = None) -> list[dict]:
    hi = len(d) if hi is None else hi
    out = []
    for m in DPLC_LOADER.finditer(d, lo, hi):
        if m.start() < lo:
            continue
        out.append(
            {
                "offset": m.start(),
                "art_table": int.from_bytes(m.group(1), "big"),
                "vram_dest": int.from_bytes(d[m.start() + 22 : m.start() + 24], "big"),
            }
        )
    return out


def find_map_art_pairs(d: bytes, lo: int = 0, hi: int | None = None) -> list[dict]:
    hi = len(d) if hi is None else hi
    out = []
    for m in MAP_GFX.finditer(d, lo, hi):
        map_addr = int.from_bytes(m.group(1), "big")
        art_tile = int.from_bytes(m.group(2), "big")
        # keep plausible player-like hits: ROM-resident map table, sane art tile
        if 0 < map_addr < hi and 0x100 < art_tile <= 0xFFFF:
            out.append({"offset": m.start(), "map_table": map_addr, "art_tile": art_tile})
    return out


def inventory(path: str | Path, source_sha256: str | None = None) -> dict:
    d, meta = read_rom(path)
    lo = lock_on(d)
    return {
        "game": "Sonic & Knuckles + Sonic the Hedgehog 1 (World lock-on)",
        "catalog_label_note": (
            "catalog names this file 'S&K + Sonic the Hedgehog 2' but the attached "
            "segment serial is GM 00001009-00 (Sonic 1 REV00)"
        ),
        "source_sha256": source_sha256,
        "rom_sha256": hashlib.sha256(d).hexdigest(),
        "rom_md5": hashlib.md5(d).hexdigest(),
        "rom_size": len(d),
        **meta,
        "lock_on": lo,
        "segments": segments(d),
        "header_checksum": genesis_checksum(d),
        "playable": {
            "mode": "blue_sphere" if lo["attached"] else None,
            "characters": ["Sonic"] if lo["attached"] else ["Sonic", "Tails", "Knuckles"],
            "sprite_kind": "2D tiles: mappings + DPLC-queued art + palettes",
            "notes": (
                "Attached-cart mode boots the Blue Sphere special stage; the full "
                "player sprite sets (Sonic/Tails/Knuckles) live in the S&K segment."
            ),
        },
        "dplc_loader_probe": find_dplc_loaders(d, 0, 0x200000),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sonic & Knuckles lock-on ROM inventory")
    ap.add_argument("source", help="zip or flat Genesis image")
    ap.add_argument("--out", help="write manifest JSON here")
    ap.add_argument("--source-sha256", help="sha256 of the owned archive, for the manifest")
    args = ap.parse_args(argv)
    m = inventory(args.source, args.source_sha256)
    text = json.dumps(m, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)
    return m


if __name__ == "__main__":
    main()
