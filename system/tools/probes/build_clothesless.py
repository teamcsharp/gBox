"""Build a LayeredFS mod that hides one material of the player model, then launch it and look.

The operation is `gbox.re4hd_hide`: collapse a material's vertices onto their own centroid, which leaves topology intact and
is the only kind of edit this engine draws. `pack_patch` takes the **whole UDAS** and the index of the Nth BIN slot in it,
and requires the replacement to be exactly that slot's size, so the result is padded with `pad_to` before it goes in.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import re4gc_inventory as INV
from gbox import re4hd_hide as H
from gbox import re4hd_models as R

TITLE = "010099A00BC1E000"
ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), TITLE)
CACHE = os.path.expanduser("~/gBox_alt/gbox-cache/mods")
PACK = "pl00.udas"
BUILD = sys.argv[1] if len(sys.argv) > 1 else "re4sw-clothesless"
MATERIAL = int(sys.argv[2]) if len(sys.argv) > 2 else 1
SLOT = int(sys.argv[3]) if len(sys.argv) > 3 else 0


def main() -> int:
    source = os.path.join(ROMFS, "bio4", "em", PACK)
    data = open(source, "rb").read()
    slots = INV.bin_slots(data, endian="<")
    print(f"{PACK}: {len(data)} bytes | BIN slots {len(slots)}")
    slot = slots[SLOT]
    print(f"slot #{SLOT}: offset {slot['offset']} size {slot['size']}")
    body = data[slot["offset"]:slot["offset"] + slot["size"]]
    mesh = R.bin_read(body)
    print(f"verts {len(mesh.pos)} tris {len(mesh.tris)} mats {len(mesh.mats)}")
    report = H.hide_materials(mesh, [MATERIAL])
    print("hide report:", json.dumps(report)[:360])
    replacement = R.pad_to(R.bin_write(mesh), slot["size"])
    print(f"replacement {len(replacement)} bytes | slot {slot['size']} | same: {len(replacement) == slot['size']}")
    patched = INV.pack_patch(data, SLOT, replacement, endian="<")
    print(f"pack {len(data)} -> {len(patched)} | same size: {len(data) == len(patched)}")

    out = os.path.join(CACHE, "270a15eb98dab4d7", BUILD, "romfs", "bio4", "em")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, PACK), "wb") as handle:
        handle.write(patched)
    marker = os.path.join(CACHE, "270a15eb98dab4d7", BUILD, ".gbox-mod.json")
    with open(marker, "w", encoding="utf-8") as handle:
        json.dump({"name": BUILD, "game_id": "270a15eb98dab4d7", "game_title": "re4_switch", "title": BUILD,
                   "writer": "gbox.switch_mods", "built": time.time(), "created": time.time(), "platform": "switch",
                   "layeredfs": {"format": 1, "title_id": TITLE, "base": "",
                                 "load": f"load/{TITLE}/{BUILD}",
                                 "note": "only the changed RomFS files; the base NSP is never copied"},
                   "files": [f"/{PACK}"], "file_changes": [f"bio4/em/{PACK}"], "history": [],
                   "kind": "files", "launchable": True,
                   "note": f"{PACK} slot {SLOT} material {MATERIAL} collapsed to a point (clothes removal)"},
                  handle, indent=1)
    print("build:", os.path.dirname(os.path.dirname(os.path.dirname(marker))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
