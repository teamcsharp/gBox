"""Give every player pack the donor rig's proportions - the character that is always in frame.

The enemy framing is a lottery: a capture either catches a Ganado at distance or catches an explosion, a wall or a mob against the
lens. The **player** is in every frame, so the same `morph_bones_to` transfer pointed at the player packs settles "does the
reshaped model draw" in one run, and it is also the direction the operator actually asked for - the character you play as, wearing
another character's proportions.

The donor is a `Bin` with a bone table: Sonic's joints are written into a copy of each template's own bone table, ordered by
hierarchy depth and scaled to the template's height, so no semantic name matching is needed on either side.
"""
import copy
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox import characters
from gbox import config as gconfig
from gbox import re4gc_inventory as INV
from gbox import re4hd_models as R
from gbox import switch_mods

TITLE = "010099A00BC1E000"
GAME = "270a15eb98dab4d7"
ROMFS = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), TITLE, "bio4", "em")
DONOR = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/agent-work/re4chars/sonic_src.glb")
BUILD = sys.argv[2] if len(sys.argv) > 2 else "re4sw-sonicplayers"
BOOST = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0


def rig(path: str):
    gl, _acc, _image, world = characters._load(path)
    nodes = gl.get("nodes") or []
    parent = [-1] * len(nodes)
    for i, node in enumerate(nodes):
        for child in node.get("children") or []:
            parent[child] = i
    joints = sorted({j for skin in gl.get("skins", []) for j in skin.get("joints", [])})
    if not joints:
        raise SystemExit("the donor has no skin joints")

    def depth(i: int) -> int:
        d = 0
        while parent[i] >= 0:
            i = parent[i]
            d += 1
        return d

    ordered = sorted(joints, key=lambda j: (depth(j), j))
    return ordered, {j: np.asarray(world[j])[:3, 3].astype(float) for j in joints}


def donor_bin(template: R.Bin, donor_path: str) -> R.Bin:
    ordered, positions = rig(donor_path)
    box = template.bbox()
    height = float(box[1][2] - box[0][2]) * BOOST
    stacked = np.stack(list(positions.values()))
    span = float(stacked.max(0)[2] - stacked.min(0)[2])
    if span <= 0:
        raise R.BINError("the donor has no vertical extent")
    factor = (height or 1.0) / span
    low = float(stacked.min(0)[2])
    scaled = {k: np.array([p[0] * factor, p[1] * factor, (p[2] - low) * factor]) for k, p in positions.items()}
    absolute = [np.asarray(scaled[j], float) for j in ordered]
    out = copy.copy(template)
    parent_absolute = {}
    for index, bone in enumerate(template.bones):
        parent_absolute[bone["id"]] = (np.zeros(3) if bone["parent"] == 0xFF
                                       else np.asarray(absolute[bone["parent"]]))
    out.bones = [dict(bone, x=float((absolute[min(index, len(absolute) - 1)] - parent_absolute[bone["id"]])[0]),
                      y=float((absolute[min(index, len(absolute) - 1)] - parent_absolute[bone["id"]])[1]),
                      z=float((absolute[min(index, len(absolute) - 1)] - parent_absolute[bone["id"]])[2]))
                 for index, bone in enumerate(template.bones)]
    return out


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
        patched, touched, moved = data, 0, 0
        for index, slot in enumerate(slots):
            body = data[slot["offset"]:slot["offset"] + slot["size"]]
            try:
                mesh = R.bin_read(body)
                if not mesh.bones or mesh.pos is None or mesh.tris is None or not mesh.mats:
                    continue
                replacement = R.pad_to(R.morph_bones_bin(mesh, donor_bin(mesh, DONOR)), slot["size"])
                patched = INV.pack_patch(patched, index, replacement, endian="<")
                touched += 1
                moved += len(mesh.pos)
            except (R.BINError, ValueError, IndexError):
                continue
        if touched:
            changes[f"bio4/em/{name}"] = {"bytes": patched}
            totals["packs"] += 1
            totals["slots"] += touched
            totals["vertices"] += moved
    print(f"packs: {totals['packs']} | slots: {totals['slots']} | vertices: {totals['vertices']}")
    if not changes:
        return 1
    out = switch_mods.write_files(cfg, GAME, BUILD, changes,
                                  create={"title_id": TITLE, "game_title": "re4_switch", "base": "", "kind": "files"},
                                  note=f"player packs morphed toward {os.path.basename(DONOR)} (boost {BOOST})")
    print("write_files:", json.dumps(out)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
