"""Swap one of the player's textures through imagepackhd and see whether the mesh changes.

Round 116 left one question: is the TPL descriptor's global image id the same id the loader uses for `imagepackhd/%08x.pack.fen`? `pl08`
names global id **9**, and `00000009.pack.fen` is present. If replacing that archive's surface recolours the player, then "swap clothes /
swap skins" is a **file replacement** - no pack edit, no writer for the pack's descriptor table.

This builds the mod and prints what it did; the run and the frame are the test.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4hd_tex as T
from gbox import switch_mods

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "gBox_alt/switch/romfs/010099A00BC1E000")
ARCHIVES = os.path.join(ROOT, "bio4", "imagepackhd")
GAME_ID = "270a15eb98dab4d7"
TITLE_ID = "010099A00BC1E000"
COLOUR = (222, 168, 140)          # a skin tone, so a recoloured surface is unmistakable


class Config:
    cache = os.path.join(HOME, "gBox_alt", "gbox-cache")


def main() -> int:
    texture_id = int(sys.argv[1], 16) if len(sys.argv) > 1 else 9
    build = sys.argv[2] if len(sys.argv) > 2 else "re4sw-texswap9"
    name = T.archive_name(texture_id)
    path = os.path.join(ARCHIVES, name)
    if not os.path.isfile(path):
        print(f"{name} is not in imagepackhd")
        return 1
    data = open(path, "rb").read()
    print(f"{name}: {len(data)} bytes")
    try:
        textures = T.fen_textures(data, limit=4)
    except T.TexError as exc:
        print("cannot list its surfaces:", exc)
        textures = []
    for row in textures[:4]:
        print("  surface:", {k: row[k] for k in row if k in ("index", "width", "height", "format", "bytes")})
    if not textures:
        print("no surface descriptors: nothing to swap")
        return 1
    first = textures[0]
    width, height = int(first.get("width") or 0), int(first.get("height") or 0)
    if not (width and height):
        print("the first surface has no dimensions")
        return 1
    patched = None
    for fourcc in ("DXT5", "DXT1", "DXT3"):
        dds = T.solid_dds(width, height, COLOUR, fourcc=fourcc)
        try:
            patched = T.fen_replace_texture(data, int(first["index"]), dds)
            print(f"replaced surface {first['index']} with a {width}x{height} {fourcc} solid: {len(dds)} bytes")
            break
        except T.TexError as exc:
            print(f"  {fourcc} refused: {str(exc)[:90]}")
    if patched is None:
        print("no DDS variant fitted")
        return 1
    result = switch_mods.write_files(Config(), GAME_ID, build,
                                     {f"romfs/bio4/imagepackhd/{name}": {"bytes": patched}},
                                     create={"title_id": TITLE_ID, "kind": "file", "game_title": "re4"},
                                     note=f"texture {texture_id:#x} ({name}) surface replaced with a solid colour")
    print("wrote", result.get("mod"), result.get("files"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
