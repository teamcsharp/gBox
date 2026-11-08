"""Does the loader fall back to `imagepack/<id>.pack.fen` when the HD archive is absent?

Round 118's measured facts: the player's body names global texture ids 1, 2 and 5; `imagepackhd` has nothing below id 6; and the loader's
own format string switches between `ImagePack` and `ImagePackHD` by a flag. So the low ids belong to the SD store, which this RomFS does not
contain - and a LayeredFS overlay can supply a file the base tree lacks.

This writes a real archive (the wrapper and surface layout of a known-good one) under `bio4/imagepack/<id>.pack.fen` with its first surface
replaced by a solid skin tone. If the player changes colour, the fallback is real and every texture in the low id range becomes
replaceable by a plain file swap.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4hd_tex as T
from gbox import switch_mods

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "gBox_alt/switch/romfs/010099A00BC1E000")
HD = os.path.join(ROOT, "bio4", "imagepackhd")
GAME_ID = "270a15eb98dab4d7"
TITLE_ID = "010099A00BC1E000"
COLOUR = (222, 168, 140)


class Config:
    cache = os.path.join(HOME, "gBox_alt", "gbox-cache")


def main() -> int:
    target_id = int(sys.argv[1], 16) if len(sys.argv) > 1 else 1
    build = sys.argv[2] if len(sys.argv) > 2 else "re4sw-imagepack1"
    donor = os.path.join(HD, T.archive_name(9))
    if not os.path.isfile(donor):
        print("the donor archive 00000009.pack.fen is missing")
        return 1
    data = open(donor, "rb").read()
    textures = T.fen_textures(data, limit=2)
    if not textures:
        print("the donor has no surfaces")
        return 1
    first = textures[0]
    width, height = int(first["width"]), int(first["height"])
    patched = None
    for fourcc in ("DXT5", "DXT1", "DXT3"):
        try:
            patched = T.fen_replace_texture(data, int(first["index"]),
                                            T.solid_dds(width, height, COLOUR, fourcc=fourcc))
            print(f"donor surface {first['index']} ({width}x{height}) replaced with {fourcc}")
            break
        except T.TexError as exc:
            print(f"  {fourcc} refused: {str(exc)[:80]}")
    if patched is None:
        return 1
    name = T.archive_name(target_id)
    result = switch_mods.write_files(Config(), GAME_ID, build,
                                     {f"romfs/bio4/imagepack/{name}": {"bytes": patched}},
                                     create={"title_id": TITLE_ID, "kind": "file", "game_title": "re4"},
                                     note=f"SD texture archive {name} supplied from the overlay (fallback test)")
    print("wrote", result.get("mod"), result.get("files"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
