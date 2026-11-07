"""What does a real RE4 Switch Ganado pack look like? Parts, materials and vertex counts, before writing a hide op.

"Remove clothes" needs to know what a part *is* in this format. This prints the structure of `em16.udas` - its DAT
entries, the BIN slots and each slot's materials - so the hide operation can be written against the real thing instead of a
guess about where a clothing piece lives.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R

UDAS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em", "em16.udas")


def main() -> int:
    data = open(UDAS, "rb").read()
    print(f"{os.path.basename(UDAS)}: {len(data)} bytes")
    entries = INV.udas_entries(data, endian="<")  # HD port is little-endian
    print(f"udas entries: {len(entries)}")
    for entry in entries[:6]:
        print("   ", entry)
    # the BIN slots inside the DAT entries: what a hide op would have to address
    total = 0
    for entry in entries[:6]:
        blob = data[entry["offset"]:entry["offset"] + entry["size"]]
        try:
            slots = INV.dat_entries(blob, endian="<")
        except Exception as exc:                                  # noqa: BLE001
            print(f"   entry type {entry['type']}: dat parse failed ({type(exc).__name__}: {exc})")
            continue
        print(f"   entry type {entry['type']}: {len(slots)} DAT slots")
        for slot in slots[:6]:
            body = blob[slot["offset"]:slot["offset"] + slot["size"]]
            try:
                info = R.bin_info(body)
                print(f"      slot {slot['index']}: BIN verts {info.get('n_verts')} tris {info.get('n_tris')}")
                total += 1
            except Exception:                                     # noqa: BLE001
                pass
    print("BIN slots decoded:", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
