"""Shrink every material of every player pack (`pl00`..`pl21`) into one overlay.

The overlay mechanism is verified (the launched build is enabled, nothing else is, and the emulator's `pl00.udas` md5 equals
the build's). `pl00` alone changed nothing, so this covers all 27 player packs at once: whatever the game draws a character
from, its vertices move. If no character changes, the models do not come from `bio4/em/pl*.udas` at all and that is the
finding.

Every BIN slot of every pack is scaled - slots that are not meshes are skipped rather than forced - and each pack is patched
in place at its slot's own size, which keeps the container byte-for-byte elsewhere.
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
BUILD = sys.argv[1] if len(sys.argv) > 1 else "re4sw-allplayers"
FACTOR = float(sys.argv[2]) if len(sys.argv) > 2 else 0.1


def main() -> int:
    cfg = gconfig.load(os.path.expanduser("~/gBox/system/gbox.toml"))
    packs = sorted(n for n in os.listdir(ROMFS) if n.lower().startswith("pl") and n.lower().endswith(".udas"))
    changes, totals = {}, {"packs": 0, "slots": 0, "vertices": 0}
    for name in packs:
        data = open(os.path.join(ROMFS, name), "rb").read()
        try:
            slots = INV.bin_slots(data, endian="<")
        except ValueError:
            continue
        patched = data
        touched = 0
        for index, slot in enumerate(slots):
            body = data[slot["offset"]:slot["offset"] + slot["size"]]
            try:
                mesh = R.bin_read(body)
                if not mesh.mats or mesh.tris is None or mesh.pos is None:
                    continue
                report = H.scale_materials(mesh, list(range(len(mesh.mats))), factor=FACTOR)
                replacement = R.pad_to(R.bin_write(mesh), slot["size"])
                patched = INV.pack_patch(patched, index, replacement, endian="<")
                totals["slots"] += 1
                totals["vertices"] += report["vertices_changed"]
                touched += 1
            except (R.BINError, ValueError):
                continue
        if touched:
            changes[f"bio4/em/{name}"] = {"bytes": patched}
            totals["packs"] += 1
    print(f"packs rewritten: {totals['packs']} of {len(packs)} | slots: {totals['slots']} | vertices moved: {totals['vertices']}")
    out = switch_mods.write_files(cfg, GAME, BUILD, changes,
                                  create={"title_id": TITLE, "game_title": "re4_switch", "base": "", "kind": "files"},
                                  note=f"every material of every player pack scaled to {FACTOR}")
    print("write_files:", json.dumps(out)[:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
