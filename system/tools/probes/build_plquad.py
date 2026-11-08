"""Which player pack does Mercenaries draw Leon from? One boot, four visually distinct answers.

Twenty-seven player packs is too many to test one at a time. They are split into four groups, each scaled by a *different*
factor, so the appearance of the player in a single live round says which group his model comes from:

    pl00..pl06   x3.0   -> a giant
    pl07..pl0d   x0.1   -> a fragment
    pl0e..pl15   x0.5   -> noticeably smaller
    pl16..pl21   untouched -> unchanged (so "no change" names the last group)

Every slot is scaled about its own material centroid and patched at its own size, exactly as `re4sw-allplayers` was - which
is the build that first drew a character change, so the mechanism is not in question here.
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
BUILD = sys.argv[1] if len(sys.argv) > 1 else "re4sw-plquad"
GROUPS = {"pl00": 3.0, "pl01": 3.0, "pl02": 3.0, "pl03": 3.0, "pl04": 3.0, "pl05": 3.0, "pl06": 3.0,
          "pl07": 0.1, "pl08": 0.1, "pl09": 0.1, "pl0a": 0.1, "pl0b": 0.1, "pl0c": 0.1, "pl0d": 0.1,
          "pl0e": 0.5, "pl0f": 0.5, "pl10": 0.5, "pl11": 0.5, "pl12": 0.5, "pl14": 0.5, "pl15": 0.5}


def main() -> int:
    cfg = gconfig.load(os.path.expanduser("~/gBox/system/gbox.toml"))
    changes, totals = {}, {"packs": 0, "slots": 0, "vertices": 0}
    for stem, factor in GROUPS.items():
        name = f"{stem}.udas"
        path = os.path.join(ROMFS, name)
        if not os.path.isfile(path):
            continue
        data = open(path, "rb").read()
        try:
            slots = INV.bin_slots(data, endian="<")
        except ValueError:
            continue
        patched, touched = data, 0
        for index, slot in enumerate(slots):
            body = data[slot["offset"]:slot["offset"] + slot["size"]]
            try:
                mesh = R.bin_read(body)
                if not mesh.mats or mesh.tris is None or mesh.pos is None:
                    continue
                report = H.scale_materials(mesh, list(range(len(mesh.mats))), factor=factor)
                patched = INV.pack_patch(patched, index, R.pad_to(R.bin_write(mesh), slot["size"]), endian="<")
                totals["slots"] += 1
                totals["vertices"] += report["vertices_changed"]
                touched += 1
            except (R.BINError, ValueError):
                continue
        if touched:
            changes[f"bio4/em/{name}"] = {"bytes": patched}
            totals["packs"] += 1
    print(f"packs: {totals['packs']} | slots: {totals['slots']} | vertices: {totals['vertices']}")
    out = switch_mods.write_files(cfg, GAME, BUILD, changes,
                                  create={"title_id": TITLE, "game_title": "re4_switch", "base": "", "kind": "files"},
                                  note="player-pack groups scaled x3.0 / x0.1 / x0.5 to identify Mercenaries' Leon")
    print("write_files:", json.dumps(out)[:240])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
