"""A Ganado with Sonic's proportions: transfer the donor rig's skeleton onto the template's bones, keep topology.

Why this shape of edit: the Switch engine draws a slot's own topology and ignores a rebuilt mesh (measured: scaled positions are
drawn, a rebuilt mesh is not), so a character cannot be replaced - only *reshaped*. `morph_bones_to` is built for exactly that:
it moves the template so its skeleton takes the donor's shape and carries every vertex with its own bone, so the donor's
proportions come through without neighbouring vertices landing on opposite sides of it.

The donor is a `Bin` with a bone table, so the Sonic rig becomes one by writing its joint offsets into a copy of the template's
bone table, matched bone-for-bone by hierarchy depth, and scaled to the template's own height. The vertex count, primitive
table, weights and materials are the template's - nothing the engine refuses to draw is touched.
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
PACK = sys.argv[1] if len(sys.argv) > 1 else "em16.udas"
DONOR = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/agent-work/re4chars/sonic_src.glb")
BUILD = sys.argv[3] if len(sys.argv) > 3 else "re4sw-sonicganado"


def donor_rig(path: str):
    """Sonic's joints as parent-relative offsets, in hierarchy order, plus each joint's depth."""
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
    positions = {j: np.asarray(world[j])[:3, 3].astype(float) for j in joints}
    return ordered, positions, parent


def scaled_to_height(points: dict[int, np.ndarray], height: float) -> dict[int, np.ndarray]:
    """The donor's joints scaled so its tall axis matches the template's - proportions kept, units matched."""
    stacked = np.stack(list(points.values()))
    span = float(stacked.max(0)[2] - stacked.min(0)[2]) if len(stacked) else 0.0
    if span <= 0:
        return points
    factor = height / span
    low = float(stacked.min(0)[2])
    return {key: np.array([p[0] * factor, p[1] * factor, (p[2] - low) * factor]) for key, p in points.items()}


def donor_bin(template: R.Bin, donor_path: str) -> R.Bin:
    """The template's bone table rewritten with the donor's joint positions, as parent-relative offsets.

    Every offset is computed from the *donor's* absolute joint positions, never from the template's accumulated ones, so a
    parent's replacement does not need the child's to be recomputed twice.
    """
    ordered, positions, _parent = donor_rig(donor_path)
    box = template.bbox()
    height = float(box[1][2] - box[0][2])
    scaled = scaled_to_height(positions, height or 1.0)
    donor_order = [np.asarray(scaled[j], float) for j in ordered]
    if not donor_order:
        raise R.BINError("the donor produced no joints")
    absolute = [donor_order[min(index, len(donor_order) - 1)] for index in range(len(template.bones))]
    parent_absolute = {}
    for index, bone in enumerate(template.bones):
        parent_absolute[bone["id"]] = np.zeros(3) if bone["parent"] == 0xFF else np.asarray(absolute[bone["parent"]])
    out = copy.copy(template)
    out.bones = []
    for index, bone in enumerate(template.bones):
        local = absolute[index] - parent_absolute[bone["id"]]
        out.bones.append(dict(bone, x=float(local[0]), y=float(local[1]), z=float(local[2])))
    return out


def main() -> int:
    cfg = gconfig.load(os.path.expanduser("~/gBox/system/gbox.toml"))
    data = open(os.path.join(ROMFS, PACK), "rb").read()
    slots = INV.bin_slots(data, endian="<")
    print(f"{PACK}: {len(data)} bytes | {len(slots)} BIN slots")
    patched, done, total = data, 0, 0
    for index, slot in enumerate(slots):
        body = data[slot["offset"]:slot["offset"] + slot["size"]]
        try:
            mesh = R.bin_read(body)
            if not mesh.bones or mesh.pos is None or mesh.tris is None or not mesh.mats:
                continue
            donor = donor_bin(mesh, DONOR)
            replacement = R.pad_to(R.morph_bones_bin(mesh, donor), slot["size"])
            report = R.bin_read(replacement)
            if report.pos is None or len(report.pos) != len(mesh.pos):
                print(f"  slot {index}: refused (vertex count changed)")
                continue
            patched = INV.pack_patch(patched, index, replacement, endian="<")
            done += 1
            total += len(mesh.pos)
            print(f"  slot {index}: {len(mesh.pos)} vertices reshaped | bones {len(mesh.bones)}")
        except (R.BINError, ValueError, IndexError) as exc:
            continue
    print(f"slots reshaped: {done} | vertices: {total}")
    if not done:
        return 1
    out = switch_mods.write_files(cfg, GAME, BUILD, {f"bio4/em/{PACK}": {"bytes": patched}},
                                  create={"title_id": TITLE, "game_title": "re4_switch", "base": "", "kind": "files"},
                                  note=f"{PACK} reshaped toward the donor rig's proportions (topology untouched)")
    print("write_files:", json.dumps(out)[:220])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
