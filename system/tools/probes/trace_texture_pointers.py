"""Where are the surfaces? Follow the descriptor's pointer and scan the pack for DDS magics.

The 40-byte records end with a value that strides by 8 and stays inside the slot (520, 528, 536...) - which is the shape of a pointer to
an 8-byte entry near the slot's end, not a byte count. This reads those entries, scans the whole pack for `DDS ` magics, and prints both
so the relationship can be seen instead of guessed.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV

ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em")


def main() -> int:
    pack = sys.argv[1] if len(sys.argv) > 1 else "pl08.udas"
    path = os.path.join(ROMFS, pack)
    data = open(path, "rb").read()
    print(f"{pack}: {len(data)} bytes")

    hits = []
    at = data.find(b"DDS ")
    while at >= 0:
        hits.append(at)
        at = data.find(b"DDS ", at + 4)
    print(f"DDS magics in the whole pack: {len(hits)}  first few: {[hex(h) for h in hits[:6]]}")

    print("\nUDAS entries:")
    for entry in INV.udas_entries(data, endian="<"):
        print(f"  type {entry['type']} offset {entry['offset']:#x} size {entry['size']:#x}")
    dat = next(e for e in INV.udas_entries(data, endian="<") if e["type"] == 0)
    print("\nDAT slots:")
    blob_all = data[dat["offset"]:dat["offset"] + dat["size"]]
    for slot, (ext, off, size) in enumerate(INV.dat_entries(blob_all, endian="<")):
        print(f"  slot {slot:>2} {str(ext):4s} offset {off:#08x} size {size:#08x}")
    print(f"DAT slot: offset {dat['offset']:#x} size {dat['size']:#x}")
    blob = data[dat["offset"]:dat["offset"] + dat["size"]]
    for slot, (ext, off, size) in enumerate(INV.dat_entries(blob, endian="<")):
        if ext != "TPL":
            continue
        tpl = blob[off:off + size]
        count = struct.unpack_from("<I", tpl, 4)[0]
        print(f"\nTP L slot {slot} at {off:#x} ({size} bytes, {count} images)")
        for i in range(count):
            record = struct.unpack_from("<Q", tpl, 0x10 + 0x10 * i)[0]
            if record + 0x28 > len(tpl):
                continue
            w, h, fmt, field = struct.unpack_from("<HHII", tpl, record)
            entry = ""
            if 0 <= field <= len(tpl) - 8:
                a, b = struct.unpack_from("<II", tpl, field)
                entry = f"entry@slot+{field:#x} = u32 {a} ({a:#x}), u32 {b} ({b:#x})"
            else:
                entry = f"field {field} is outside the slot"
            print(f"  image {i}: {w}x{h} fmt {fmt:#x} field {field:#x}  {entry}")
        print(f"  tail of the slot (last 0x40): {tpl[-0x40:].hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
