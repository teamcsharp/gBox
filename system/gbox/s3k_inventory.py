"""Owned-build inventory manifest for Sonic & Knuckles + Sonic the Hedgehog 3 (World), game_id ed2bef5be2826deb.

Platform: Sega Mega Drive / Genesis, Motorola 68000, big-endian, offsets are absolute file offsets == ROM
addresses (no header/base shift; the .md member is a flat 4 MiB image).  This is the Sonic 1/2/3 object engine
(uncompressed 4bpp art + DPLC + sprite mappings + palette lines), NOT Sega Ninja/NJ (Dreamcast); the reader is
gbox.sonic2d_sprites ('sonic2d_s3k').  The hash is STREAMED from the owned bytes; no reference value is copied.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

from . import sonic2d_sprites as s2d

GAME_ID = "ed2bef5be2826deb"
DEFAULT_SRC = Path("/mnt/gbox/hyperspin/Arcade/collections/Sega Genesis/roms/"
                   "Sonic & Knuckles + Sonic the Hedgehog 3 (World).zip")


def stream_hashes(src) -> dict:
    """sha256/sha1/size of the single ROM member, streamed in 1 MiB chunks (no whole-file read)."""
    p = Path(src)
    h2, h1, n = hashlib.sha256(), hashlib.sha1(), 0
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as zf:
            ms = [i for i in zf.infolist() if not i.is_dir() and Path(i.filename).suffix.lower() in (".md", ".bin", ".gen")]
            if len(ms) != 1:
                raise s2d.Sonic2DError(f"expected one ROM member, found {len(ms)}")
            name, f = ms[0].filename, zf.open(ms[0])
            container = {"kind": "zip", "path": str(p), "member": name, "zip_size": p.stat().st_size}
            with f:
                for c in iter(lambda: f.read(1 << 20), b""):
                    h2.update(c); h1.update(c); n += len(c)
    else:
        container = {"kind": "flat", "path": str(p), "member": p.name}
        with p.open("rb") as f:
            for c in iter(lambda: f.read(1 << 20), b""):
                h2.update(c); h1.update(c); n += len(c)
    return {"sha256": h2.hexdigest(), "sha1": h1.hexdigest(), "size": n, "container": container}


def build_manifest(src=DEFAULT_SRC) -> dict:
    ident = stream_hashes(src)
    d, _ = s2d.read_rom(src)
    assert hashlib.sha256(d).hexdigest() == ident["sha256"], "streamed and loaded bytes disagree"
    game = s2d.identify(d)
    ex = s2d.Extractor(d, {"member": ident["container"]["member"], "size": len(d)})
    chars = {}
    for name, ch in ex.chars.items():
        tiles = [first + n for fr in ch.dplc for first, n in fr]
        pieces = sum(len(m) for m in ch.maps)
        chars[name] = {
            "art_main": ch.art, "art_extra": ch.extra_art, "art_bank_switch_frame": ch.extra_from,
            "dplc_table": ch.plc, "mappings_table": ch.maps_off, "anim_table": ch.anim,
            "palette_table_entry": ch.pal_entry, "palette_line_hex": ch.palette.hex(),
            "loader_routine": ch.loader,
            "dplc_frames": len(ch.dplc), "mapping_frames": len(ch.maps), "mapping_pieces": pieces,
            "max_art_tile_index": max(tiles) if tiles else 0,
            "animations": s2d.anim_count(d, ch.anim),
            "tails_overlay": ch.tails and {k: (v if isinstance(v, (int, str, bool, type(None))) else repr(type(v).__name__))
                                           for k, v in ch.tails.items()} or None,
            "clips": [p["name"] for p in ex.plans(name)],
        }
    return {
        "game_id": GAME_ID, "platform": "genesis (Sega Mega Drive, 68000)", "byte_order": "big-endian",
        "offset_base": "absolute ROM file offset == 68k address (flat .md image)",
        "engine": "Sonic 1/2/3 object engine: uncompressed 4bpp 8x8 tiles + DPLC + mappings + palette lines",
        "reader": "gbox.sonic2d_sprites (sonic2d_s3k)", "game": game.key, "layout": ex.lay.name,
        "source": ident, "header": s2d.header(d), "palette_table": ex.pal_table,
        "target_slot_candidate": {"character": "tails", "why": "smallest coupled set; art+extra bank, 251 frames, overlay sub-object"},
        "characters": chars,
        "counted": "all counts come from parsing pointer tables in the ROM, not filenames",
    }


if __name__ == "__main__":
    out = build_manifest(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC)
    print(json.dumps(out, indent=1, sort_keys=True, default=str))
