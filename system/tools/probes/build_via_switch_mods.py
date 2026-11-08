"""Write the shrunken pack through `switch_mods.write_files` instead of by hand.

The hand-written overlay in the previous round was never read - Leon was untouched with **every** material of `pl00` shrunk to
10% - so the folder layout a marker alone produces is not what the launcher links into the emulator. `write_files` is the
writer the working morph builds used: it stages the edit, records it, and its `create` argument makes the build when it does
not exist yet.
"""
import json
import os
import sys

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import config as gconfig
from gbox import re4gc_inventory as INV
from gbox import re4hd_hide as H
from gbox import re4hd_models as R
from gbox import switch_mods

TITLE = "010099A00BC1E000"
GAME = "270a15eb98dab4d7"
PACK = "pl00.udas"
BUILD = sys.argv[1] if len(sys.argv) > 1 else "re4sw-shrinkall2"
FACTOR = float(sys.argv[2]) if len(sys.argv) > 2 else 0.1
ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), TITLE)


def main() -> int:
    cfg = gconfig.load(os.path.expanduser("~/gBox/system/gbox.toml"))
    source = os.path.join(ROMFS, "bio4", "em", PACK)
    data = open(source, "rb").read()
    slot = INV.bin_slots(data, endian="<")[0]
    mesh = R.bin_read(data[slot["offset"]:slot["offset"] + slot["size"]])
    report = H.scale_materials(mesh, list(range(len(mesh.mats))), factor=FACTOR)
    print(f"scaled {len(report['scaled'])} materials to {FACTOR} | vertices {report['vertices_changed']} | "
          f"topology unchanged {report['triangles_unchanged']}")
    patched = INV.pack_patch(data, 0, R.pad_to(R.bin_write(mesh), slot["size"]), endian="<")
    print(f"pack {len(data)} -> {len(patched)} bytes | same size: {len(data) == len(patched)}")
    out = switch_mods.write_files(cfg, GAME, BUILD, {f"bio4/em/{PACK}": {"bytes": patched}},
                                  create={"title_id": TITLE, "game_title": "re4_switch", "base": "", "kind": "files"},
                                  note=f"every material of {PACK} slot 0 shrunk to {FACTOR} about its centroid")
    print("write_files:", json.dumps(out)[:400])
    meta = switch_mods.read_meta(switch_mods.build_dir(cfg, GAME, BUILD))
    print("meta layeredfs:", json.dumps((meta or {}).get("layeredfs"))[:300])
    files = []
    for root, _dirs, names in os.walk(switch_mods.build_dir(cfg, GAME, BUILD)):
        for name in names:
            files.append(os.path.relpath(os.path.join(root, name), switch_mods.build_dir(cfg, GAME, BUILD)))
    print("build files:", files[:8], f"({len(files)} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
