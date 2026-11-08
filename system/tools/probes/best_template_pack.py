"""Which pack is the best container for a big donor? Its weight table decides how many joint groups a donor can keep.

`bin_from` builds the donor on the template's weight table, and a 62-joint donor does not fit an 8-record one. This prints, for every
pack, its slot 0 bone count and weight-record count, so the container is chosen from data.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R

ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em")


def main() -> int:
    rows = []
    for name in sorted(os.listdir(ROMFS)):
        if not name.lower().endswith(".udas"):
            continue
        data = open(os.path.join(ROMFS, name), "rb").read()
        try:
            slots = INV.bin_slots(data, endian="<")
        except ValueError:
            continue
        for index, slot in enumerate(slots):
            body = data[slot["offset"]:slot["offset"] + slot["size"]]
            try:
                mesh = R.bin_read(body)
            except (R.BINError, ValueError):
                continue
            if not mesh.bones:
                continue
            verts = 0 if mesh.pos is None else len(mesh.pos)
            rows.append({"pack": name, "slot": index, "bones": len(mesh.bones),
                         "weight_records": len(mesh.weights or []), "verts": verts})
            break
    rows.sort(key=lambda row: (row["weight_records"], row["bones"]), reverse=True)
    print(f"{'pack':16s} {'slot':>4} {'bones':>6} {'weights':>8} {'verts':>6}")
    for row in rows[:12]:
        print(f"{row['pack']:16s} {row['slot']:>4} {row['bones']:>6} {row['weight_records']:>8} {row['verts']:>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
