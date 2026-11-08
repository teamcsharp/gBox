"""What does the player pack's TPL really look like? Print the container, not a guess about it.

The payload field in the 40-byte record is not a byte count (it claims more than the slot holds), so this walks the container and prints
where each record is, where the first `DDS ` magic after it is, and how the slot is laid out.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV

ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em")


def main() -> int:
    pack = sys.argv[1] if len(sys.argv) > 1 else "pl08.udas"
    data = open(os.path.join(ROMFS, pack), "rb").read()
    dat = next(e for e in INV.udas_entries(data, endian="<") if e["type"] == 0)
    blob = data[dat["offset"]:dat["offset"] + dat["size"]]
    for slot, (ext, off, size) in enumerate(INV.dat_entries(blob, endian="<")):
        if ext != "TPL":
            continue
        tpl = blob[off:off + size]
        magic = struct.unpack_from("<I", tpl, 0)[0]
        count = struct.unpack_from("<I", tpl, 4)[0] if len(tpl) > 8 else 0
        print(f"slot {slot}: {size} bytes, magic {magic:#x}, count {count}")
        if magic != 0x12345678:
            print("  (not a TPL container)")
            continue
        print(f"  header size field: {struct.unpack_from('<I', tpl, 8)[0]}")
        for i in range(min(count, 8)):
            record = struct.unpack_from("<Q", tpl, 0x10 + 0x10 * i)[0]
            if record + 0x28 > len(tpl):
                print(f"  image {i}: record {record:#x} is past the slot")
                continue
            w, h, fmt, payload = struct.unpack_from("<HHII", tpl, record)
            found = tpl.find(b"DDS ", record + 0x28)
            print(f"  image {i}: record {record:#x}  {w}x{h} fmt {fmt:#x} field {payload}  "
                  f"first DDS magic at {found:#x}  slot end {len(tpl):#x}")
        print(f"  DDS magics in the slot: {tpl.count(b'DDS ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
