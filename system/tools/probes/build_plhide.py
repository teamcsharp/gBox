"""Collapse whole player packs (not shrink them) - a missing player is readable from any camera.

A 10% shrink can be hidden by the camera sitting inside a body, which is exactly what made the `pl07`..`pl0d` quarter
inconclusive. Collapsing every material of a pack onto its centroid removes the body: if the player is gone from the shot the
pack is his, and if he is there it is not - no camera position produces either answer by accident.
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
ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), TITLE, "bio4", "em")
BUILD = sys.argv[1] if len(sys.argv) > 1 else "re4sw-plhide"
PACKS = sys.argv[2].split(",") if len(sys.argv) > 2 else ["pl07", "pl08", "pl09", "pl0a", "pl0b", "pl0c", "pl0d"]


def main() -> int:
    cfg = gconfig.load(os.path.expanduser("~/gBox/system/gbox.toml"))
    changes, totals = {}, {"packs": 0, "slots": 0, "vertices": 0}
    for stem in PACKS:
        path = os.path.join(ROMFS, f"{stem}.udas")
        if not os.path.isfile(path):
            print(f"{stem}: not present")
            continue
        data = open(path, "rb").read()
        try:
            slots = INV.bin_slots(data, endian="<")
        except ValueError:
            continue
        patched, touched, hidden = data, 0, 0
        for index, slot in enumerate(slots):
            body = data[slot["offset"]:slot["offset"] + slot["size"]]
            try:
                mesh = R.bin_read(body)
                if not mesh.mats or mesh.tris is None or mesh.pos is None:
                    continue
                report = H.hide_materials(mesh, list(range(len(mesh.mats))))
                patched = INV.pack_patch(patched, index, R.pad_to(R.bin_write(mesh), slot["size"]), endian="<")
                totals["slots"] += 1
                totals["vertices"] += report["vertices_changed"]
                touched += 1
                hidden += 1
            except (R.BINError, ValueError):
                continue
        if touched:
            changes[f"bio4/em/{stem}.udas"] = {"bytes": patched}
            totals["packs"] += 1
            print(f"{stem}: {hidden} slots collapsed")
    print(f"packs: {totals['packs']} | slots: {totals['slots']} | vertices: {totals['vertices']}")
    out = switch_mods.write_files(cfg, GAME, BUILD, changes,
                                  create={"title_id": TITLE, "game_title": "re4_switch", "base": "", "kind": "files"},
                                  note=f"every material of {','.join(PACKS)} collapsed (a missing player is a clear answer)")
    print("write_files:", json.dumps(out)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
