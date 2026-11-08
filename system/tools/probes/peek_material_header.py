"""Does a material record carry a colour? If it does, a character can be recoloured without touching any texture.

The texture search is expensive and has failed three ways; a per-material tint would be a direct, cheap route to a visible "skin swap".
This prints the raw header of the first few materials of the player's body slot, with any run of four equal bytes flagged - the shape a
neutral colour takes.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R

ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em")


def main() -> int:
    pack = sys.argv[1] if len(sys.argv) > 1 else "pl08.udas"
    data = open(os.path.join(ROMFS, pack), "rb").read()
    slot = INV.bin_slots(data, endian="<")[0]
    mesh = R.bin_read(data[slot["offset"]:slot["offset"] + slot["size"]])
    print(f"{pack} slot 0: {len(mesh.mats)} materials")
    for mat in mesh.mats[:6]:
        header = getattr(mat, "header", b"") or b""
        print(f"  material {mat.index:2d} tris {mat.triangle_count:>4} header {len(header)} bytes")
        if header:
            print("    ", " ".join(f"{b:02x}" for b in header[:48]))
            for i in range(0, max(1, len(header) - 3)):
                quad = header[i:i + 4]
                if len(quad) == 4 and len(set(quad)) == 1 and quad[0] > 0x40:
                    print(f"     run of {quad[0]:#04x} at +{i}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
