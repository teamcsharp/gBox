"""Which packs' materials reference a texture archive that actually exists in imagepackhd?

The question round 116 left open: is `Mat.material_id` the same global id the loader uses for `%08x.pack.fen`? This answers the cheap
half - for every `em` pack, which material ids are present in the archive directory - so the expensive half (a live swap) can be aimed at a
mesh whose texture is certain to be found.
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "gBox_alt/switch/romfs/010099A00BC1E000")
EM = os.path.join(ROOT, "bio4", "em")
PACKS = os.path.join(ROOT, "bio4", "imagepackhd")


def present_ids() -> set[int]:
    ids = set()
    for name in os.listdir(PACKS):
        if name.endswith(".pack.fen") and len(name) == 17:
            try:
                ids.add(int(name[:8], 16))
            except ValueError:
                continue
    return ids


def global_ids(pack_bytes: bytes) -> list[int]:
    """The global image ids this pack names: the second u32 of every TPL descriptor's 8-byte entry."""
    import struct
    out = []
    try:
        dat = next(e for e in INV.udas_entries(pack_bytes, endian="<") if e["type"] == 0)
    except (ValueError, StopIteration):
        return out
    blob = pack_bytes[dat["offset"]:dat["offset"] + dat["size"]]
    for ext, off, size in INV.dat_entries(blob, endian="<"):
        if ext != "TPL":
            continue
        tpl = blob[off:off + size]
        if len(tpl) < 8 or struct.unpack_from("<I", tpl, 0)[0] != 0x12345678:
            continue
        count = struct.unpack_from("<I", tpl, 4)[0]
        for i in range(min(count, 64)):
            record = struct.unpack_from("<Q", tpl, 0x10 + 0x10 * i)[0]
            if record + 0x28 > len(tpl):
                continue
            field = struct.unpack_from("<I", tpl, record + 12)[0]
            if 0 <= field <= len(tpl) - 8:
                _const, image_id = struct.unpack_from("<II", tpl, field)
                out.append(int(image_id))
    return sorted(set(out))


def main() -> int:
    have = present_ids()
    print(f"archives present: {len(have)} (lowest ids: {sorted(have)[:12]})")
    rows = []
    for name in sorted(os.listdir(EM)):
        if not name.endswith(".udas"):
            continue
        data = open(os.path.join(EM, name), "rb").read()
        try:
            slots = INV.bin_slots(data, endian="<")
        except ValueError:
            continue
        for index, slot in enumerate(slots):
            try:
                mesh = R.bin_read(data[slot["offset"]:slot["offset"] + slot["size"]])
            except (R.BINError, ValueError):
                continue
            if mesh.pos is None or len(mesh.pos) < 800 or not mesh.mats:
                continue
            local = sorted({int(getattr(m, "material_id", 0) or 0) for m in mesh.mats})
            hit = [i for i in local if i in have]
            rows.append({"pack": name, "slot": index, "verts": len(mesh.pos), "mats": len(mesh.mats),
                         "ids": local[:6], "present": sorted(set(hit))[:6], "global": global_ids(data)[:6]})
            break
    rows.sort(key=lambda r: (-len(r["present"]), -r["verts"]))
    print(f"{'pack':16s} {'slot':>4} {'verts':>6} {'mats':>4}  local ids                    global ids")
    for row in rows[:14]:
        glob = [i for i in row.get("global", []) if i in have]
        print(f"{row['pack']:16s} {row['slot']:>4} {row['verts']:>6} {row['mats']:>4}  "
              f"{str(row['ids']):26s} {str(row.get('global'))[:28]} present {len(glob)}")
    with_present = [r for r in rows if r["present"]]
    print(f"\npacks with at least one texture archive present: {len(with_present)} of {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
