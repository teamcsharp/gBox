"""Pin the TEX payload: mip-chain offsets in the header give the surface size and the header length."""
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import mt_arc, skin_swap

ROOT = os.path.join(os.path.expanduser("~"), "gBox_alt/switch/romfs/010018100CD46000",
                    "nativeNXx64/ImgNX/Archive")


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "uPl07RebeccaNormal.arc"
    data = open(os.path.join(ROOT, name), "rb").read()
    groups = skin_swap.material_groups(mt_arc.parse(data))
    entry = (groups.get(skin_swap.body_group(groups)) or {}).get("BM")
    raw = zlib.decompress(entry.data)
    print(f"raw={len(raw)} tag={entry.tag:#010x}")
    # the run of ascending u32s that starts after the fixed fields looks like a mip offset table
    start = 0x18
    offsets = []
    for off in range(start, min(start + 0x80, len(raw) - 3), 4):
        v = struct.unpack_from("<I", raw, off)[0]
        if v > 1 and (not offsets or v > offsets[-1]):
            offsets.append(v)
        elif offsets:
            break
    print(f"ascending offsets from {start:#x}: {[hex(v) for v in offsets]}")
    if offsets:
        base = offsets[0]
        last = offsets[-1]
        print(f"base surface = {base} bytes (2048x1024 BC1 = {2048 * 1024 // 2})")
        print(f"mip chain ends at {last}; header length implied = {len(raw) - last}")
        # what dimensions does the base surface allow?
        for w, h in ((2048, 1024), (1024, 1024), (1024, 2048), (2048, 2048)):
            if w * h // 2 == base:
                print(f"  base fits {w}x{h} BC1/DXT1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
