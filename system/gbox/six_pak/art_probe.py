#!/usr/bin/env python3
"""6-Pak (game_id=73c0f182facee148) analysis probe: decode the Sonic-bank Nemesis art streams.

Streams the owned ROM zip, Nemesis-decodes each target asset from inventory_probe.SONIC_TARGET_ASSETS with the shared
gbox.formats.sega_md codec, checks tile counts against the documented values, proves re-encode -> decode round trip and
exports a grayscale-indexed PNG tile sheet.  Run from system/:  python3 gbox/six_pak/art_probe.py [--png-dir DIR]
"""
from __future__ import annotations

import hashlib
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from gbox.formats import sega_md as md  # noqa: E402
from gbox.six_pak.inventory_probe import ROM_ZIP, SONIC_TARGET_ASSETS  # noqa: E402

SONIC_BANK = 0x280000
# stars: header in this build says 36 tiles (inventory note of 35 was a documentation off-by-one)
DOC_TILES = {"sonic_intro_patterns": 525, "sega_screen_patterns": 123, "hud_patterns": 24, "smoke_dust": 16,
             "shield": 27, "stars": 36, "sonic_ending": 323}


def load_rom(zip_path: str = ROM_ZIP) -> bytes:
    with zipfile.ZipFile(zip_path) as z:
        (m,) = z.infolist()
        return z.read(m.filename)


def decode_assets(rom: bytes) -> dict:
    out = {}
    for name, off in SONIC_TARGET_ASSETS.items():
        pos = SONIC_BANK + off
        art, end = md.nemesis_decompress(rom, pos, with_end=True)
        out[name] = {"cart_offset": pos, "end": end, "packed": end - pos, "tiles": len(art) // 32, "art": art,
                     "sha256": hashlib.sha256(art).hexdigest()}
    return out


def export_png(art: bytes, path: str, cols: int = 16) -> None:
    from PIL import Image
    idx = md.tiles_to_indices(art)
    rows = (len(idx) + cols - 1) // cols
    img = Image.new("P", (cols * 8, rows * 8))
    img.putpalette([c for i in range(16) for c in (i * 17,) * 3] + [0] * (768 - 48))
    for t, tile in enumerate(idx):
        x, y = (t % cols) * 8, (t // cols) * 8
        img.paste(Image.frombytes("P", (8, 8), tile.tobytes()), (x, y))
    img.save(path)


def main(png_dir: str | None = None) -> int:
    rom = load_rom()
    fails = []
    for name, a in decode_assets(rom).items():
        ok = a["tiles"] == DOC_TILES[name]
        rt = md.nemesis_decompress(md.nemesis_compress(a["art"]))
        rt_ok = rt == a["art"]
        print(f"{name:22s} cart={a['cart_offset']:#08x} packed={a['packed']:5d}B tiles={a['tiles']:4d} "
              f"{'OK' if ok else 'TILE-MISMATCH'} roundtrip={'OK' if rt_ok else 'FAIL'} sha256={a['sha256'][:16]}")
        if not ok:
            fails.append(name)
        if not rt_ok:
            fails.append(name + ":roundtrip")
        if png_dir:
            os.makedirs(png_dir, exist_ok=True)
            export_png(a["art"], os.path.join(png_dir, f"{name}.png"))
    print("RESULT:", "PASS" if not fails else f"FAIL {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    d = sys.argv[sys.argv.index("--png-dir") + 1] if "--png-dir" in sys.argv else None
    sys.exit(main(d))
