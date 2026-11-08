"""Name the materials: each one carries a texture id, and the texture has an archive name.

`re4hd_hide` needed a material *index* and round 107 showed why that is not enough - material 7 is not the jacket, and nothing in the
census says what any of the 14 are. The pack's `Mat` records carry a texture id, and `re4hd_tex.archive_name` maps a texture id to the
archive it lives in. That name is what a person can recognise.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R
from gbox import re4hd_tex as T

ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em")


def main() -> int:
    pack = sys.argv[1] if len(sys.argv) > 1 else "pl00.udas"
    slot_index = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    data = open(os.path.join(ROMFS, pack), "rb").read()
    entry = INV.bin_slots(data, endian="<")[slot_index]
    mesh = R.bin_read(data[entry["offset"]:entry["offset"] + entry["size"]])
    print(f"{pack} slot {slot_index}: {len(mesh.mats)} materials")
    for mat in mesh.mats:
        tid = getattr(mat, "material_id", None)
        try:
            name = T.archive_name(int(tid)) if tid is not None else "?"
        except Exception as exc:                             # noqa: BLE001
            name = f"<{type(exc).__name__}: {exc}>"
        print(f"  material {mat.index:2d}  tex {tid!s:>10}  tris {mat.triangle_count:>4}  {name}")
    images = T.pack_images(data, endian="<")
    print(f"pack images: {len(images)}, first: {[hex(i.get('id', 0)) for i in images[:6]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
