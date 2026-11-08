"""Where does the player's body texture actually live: inside the pack, or in an external .fen archive?

`remove clothes` is a texture edit now, so this decides the operation: replacing a `.fen` archive under ImagePackHD is a RomFS file
swap the mod writer already does, while replacing a texture inside the pack needs a TPL writer that may not exist.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R
from gbox import re4hd_tex as T

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "gBox_alt/switch/romfs/010099A00BC1E000")
ROMFS = os.path.join(ROOT, "bio4", "em")


def main() -> int:
    pack = sys.argv[1] if len(sys.argv) > 1 else "pl08.udas"
    data = open(os.path.join(ROMFS, pack), "rb").read()
    slot = INV.bin_slots(data, endian="<")[0]
    mesh = R.bin_read(data[slot["offset"]:slot["offset"] + slot["size"]])
    print(f"{pack} slot 0: {len(mesh.mats)} materials")
    seen = set()
    for mat in mesh.mats:
        tid = int(getattr(mat, "material_id", 0) or 0)
        if tid in seen:
            continue
        seen.add(tid)
        name = T.archive_name(tid)
        found = T.archive_for(ROOT, tid)
        print(f"  tex {tid:>3} -> {name:28s} archive exists: {bool(found)} {str(found)[-60:] if found else ''}")
    images = T.pack_images(data, endian="<")
    print(f"images inside the pack: {len(images)}")
    for image in images[:6]:
        keys = ", ".join(f"{k}={image[k]}" for k in ("id", "width", "height", "format") if k in image)
        print("   ", keys)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
