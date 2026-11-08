"""Which enemy pack has the most different body plan from a Ganado? Vertex counts per slot, sorted.

The coherent morph is conservative when the donor is another humanoid, so the experiment that can validate it needs a donor whose
silhouette is genuinely different. This lists every `em*` pack's decodable slots with their numbers, so the choice is made from
data rather than from a name.
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
        if not (name.lower().startswith("em") and name.lower().endswith(".udas")):
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
            if mesh.pos is None or mesh.tris is None or len(mesh.pos) < 200:
                continue
            box = mesh.bbox()
            rows.append({"pack": name, "slot": index, "verts": len(mesh.pos), "tris": len(mesh.tris),
                         "extent": [round(float(v), 1) for v in (box[1] - box[0])],
                         "aspect": round(float(max(box[1] - box[0]) / max(1e-6, min(box[1] - box[0]))), 2)})
            break                      # the first real mesh per pack is its body
    rows.sort(key=lambda r: r["verts"])
    print(f"{'pack':14s} {'slot':>4} {'verts':>6} {'tris':>6}  extent (x,y,z)          aspect")
    for row in rows:
        print(f"{row['pack']:14s} {row['slot']:>4} {row['verts']:>6} {row['tris']:>6}  {str(row['extent']):24s} {row['aspect']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
