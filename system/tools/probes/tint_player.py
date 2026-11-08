"""Recolour the player by editing its material tint, no texture involved.

The material header carries three bytes at +16 that hold a real colour in the materials that use one (`3f 3f 3f`, `66 66 66`) and zeros in
the others. If the engine multiplies that into the surface, setting it to a strong colour recolours the character - a skin swap that needs
neither the missing texture store nor a TPL writer.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R
from gbox import switch_mods

HOME = os.path.expanduser("~")
ROMFS = os.path.join(HOME, "gBox_alt/switch/romfs/010099A00BC1E000", "bio4", "em")
GAME_ID = "270a15eb98dab4d7"
TITLE_ID = "010099A00BC1E000"
TINT_OFFSET = 16
COLOUR = (0xFF, 0x20, 0x20)          # red, unmistakable against the game's palette


class Config:
    cache = os.path.join(HOME, "gBox_alt", "gbox-cache")


def main() -> int:
    pack = sys.argv[1] if len(sys.argv) > 1 else "pl08.udas"
    build = sys.argv[2] if len(sys.argv) > 2 else "re4sw-tint"
    data = open(os.path.join(ROMFS, pack), "rb").read()
    slots = INV.bin_slots(data, endian="<")
    patched, touched = data, []
    for index, entry in enumerate(slots):
        body = patched[entry["offset"]:entry["offset"] + entry["size"]]
        try:
            mesh = R.bin_read(body)
        except (R.BINError, ValueError):
            continue
        if mesh.pos is None or len(mesh.pos) < 800 or not mesh.mats:
            continue
        changed = 0
        for mat in mesh.mats:
            header = bytearray(mat.header or b"")
            if len(header) < TINT_OFFSET + 4:
                continue
            for i, value in enumerate(COLOUR):
                header[TINT_OFFSET + i] = value
            header[TINT_OFFSET + 3] = 0xFF
            mat.header = bytes(header)
            changed += 1
        if not changed:
            continue
        replacement = R.pad_to(R.bin_write(mesh, verify=True), entry["size"])
        patched = patched[:entry["offset"]] + replacement + patched[entry["offset"] + entry["size"]:]
        touched.append({"slot": index, "materials": changed})
    if not touched:
        print("no slot to tint")
        return 1
    result = switch_mods.write_files(Config(), GAME_ID, build, {f"romfs/bio4/em/{pack}": {"bytes": patched}},
                                     create={"title_id": TITLE_ID, "kind": "file", "game_title": "re4"},
                                     note=f"material tint on {pack}")
    print("touched:", touched)
    print("wrote", result.get("mod"), result.get("files"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
