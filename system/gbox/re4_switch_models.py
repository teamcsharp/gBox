"""RE4 (Switch) Mercenaries player models: who is in which pack, and two offline writers for a pack overlay.

Nothing in this module has been drawn by the game. It builds LayeredFS overlay files (`romfs/bio4/em/plXX.udas`,
`romfs/bio4/imagepackhd/XXXXXXXX.pack.fen`) and a receipt that says what was replaced and `live_verified: false`.

A player pack is a DAT whose slots mean the same thing in every playable humanoid pack (measured on pl06, pl08,
pl0a, pl0b, pl0d - see docs/research/re4-switch-model-replacement.md): 0 body, 1 the body's texture table, 2 head,
3 the head's texture table, 4 face, 5 hair, 8 a one-bone far head, 14-21 hand poses, 22 effects, 23+ animations.
The parts are skinned to one skeleton by bone id, so a body can only be exchanged for one that keeps the ids the
other parts and the animations use.

* `native_body_swap` puts another pack's body in a pack's body slot, bytes untouched, and rebuilds the container.
* `author_body` writes a donor mesh (a skinned .glb) onto the pack's own skeleton in its own bind pose.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from . import re4_switch_assets as A

TITLE_ID = "010099A00BC1E000"
PACK_DIR = "bio4/em"
IMAGE_DIR = "bio4/imagepackhd"

#: The Mercenaries cast. "art" = the pack's own textures show the character (decoded and looked at), "layout" = the
#: pack has the playable 133+-slot layout; only Leon's pack was ever identified in a running round (an earlier
#: session's scale test), and Ada's is the weakest entry: three packs hold a playable Ada.
CAST = {
    "leon": {"pack": "pl08", "evidence": "art + layout; a scale edit of this pack changed the player in a live round "
                                         "(earlier session, 2026-11-08)"},
    "hunk": {"pack": "pl06", "evidence": "art (gas mask, black fatigues) + layout; same 119-bone count and the same "
                                         "animated bone set as Leon"},
    "krauser": {"pack": "pl0a", "evidence": "art (camouflage, war paint, blade arm) + layout"},
    "wesker": {"pack": "pl0d", "evidence": "art (sunglasses, black leather) + layout"},
    "ada": {"pack": "pl0b", "evidence": "inferred: art (plain red dress) + layout, but pl0c (tactical) and pl16 "
                                        "(butterfly dress) have the same layout - not told apart offline"},
}

BODY, BODY_TPL, HEAD, HEAD_TPL, FACE, HAIR, FAR_HEAD = 0, 1, 2, 3, 4, 5, 8
HANDS = tuple(range(14, 22))

#: Leon-family skeleton ids for the body roles (`gbox.characters.tree_roles` vocabulary). x < 0 is the right side:
#: the model faces +z (toes at +z), y is up.
ROLE_BONES = {"hip": 0, "chest": 2, "head": 4,
              "r_upper": 7, "r_fore": 8, "r_hand": 10, "l_upper": 13, "l_fore": 14, "l_hand": 16,
              "r_thigh": 18, "r_shin": 19, "r_foot": 20, "l_thigh": 22, "l_shin": 23, "l_foot": 24}
SEGMENTS = {"hip": "chest", "chest": "head", "r_upper": "r_fore", "r_fore": "r_hand", "l_upper": "l_fore",
            "l_fore": "l_hand", "r_thigh": "r_shin", "r_shin": "r_foot", "l_thigh": "l_shin", "l_shin": "l_foot"}
#: Cross-section scale (model units per donor unit) by role family; along a limb the length is the skeleton's.
SCALES = {"torso": 150.0, "head": 80.0, "limb": 100.0, "end": 100.0}
ROLE_FAMILY = {"hip": "torso", "chest": "torso", "head": "head", "r_hand": "end", "l_hand": "end",
               "r_foot": "end", "l_foot": "end"}
#: Ends that keep the donor's own orientation (a head stays level, a sole stays flat); a hand follows its forearm.
UPRIGHT = ("head", "r_foot", "l_foot")


class ModelError(ValueError):
    """The pack is not the measured player layout, or the donor cannot be written onto it."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _body(dat: A.Dat) -> tuple[A.HdBin, A.Tpl]:
    if len(dat.slots) < 22 or dat.slots[BODY][0] != "BIN" or dat.slots[BODY_TPL][0] != "TPL":
        raise ModelError("not a playable player pack: slot 0 is not a body BIN followed by its TPL")
    body = A.HdBin.parse(dat.slots[BODY][1])
    if [ident for ident, _p, _t in body.bones()] != list(range(body.bone_count)):
        raise ModelError("the body does not list its skeleton as ids 0..n-1")
    return body, A.Tpl.parse(dat.slots[BODY_TPL][1])


def skeleton_report(target: A.HdBin, donor: A.HdBin) -> dict:
    """Where a donor body's skeleton stops being the target's: the first id whose parent differs, and how far the
    bind joints before it have moved. Animations and the pack's other parts address bones by these ids."""
    a, b = target.bones(), donor.bones()
    shared = min(len(a), len(b))
    first = next((i for i in range(shared) if a[i][1] != b[i][1]), shared)
    shifts = [float(np.linalg.norm(np.subtract(a[i][2], b[i][2]))) for i in range(first)]
    later = [i for i in range(first, shared)
             if a[i][1] != b[i][1] or float(np.linalg.norm(np.subtract(a[i][2], b[i][2]))) > 1.0]
    return {"target_bones": len(a), "donor_bones": len(b), "first_id_with_another_parent": first,
            "largest_bind_shift_before_it": round(max(shifts, default=0.0), 3),
            "ids_that_differ_after_it": len(later), "identical": first == shared == len(a) == len(b) and not later
            and max(shifts, default=0.0) <= 1e-3}


def recompose(model: A.HdBin) -> A.HdBin:
    """The same surface written again by `HdBin.with_geometry`: every strip and quad becomes a triangle list.

    The result draws the same triangles with the same weights and materials but shares no mesh section with the
    original - which makes it the test of the writer itself, apart from any donor.
    """
    materials = model.materials()
    order, runs = A.soup(A.triangles(materials))
    normals = model.normals().astype(np.float64)[order]
    normals[np.linalg.norm(normals, axis=1) < 1e-12] = (0.0, 1.0, 0.0)
    return model.with_geometry(positions=model.positions()[order], normals=normals, uvs=model.uvs()[order],
                               colors=model.colors()[order], weight_sets=model.weights(),
                               weight_index=model.weight_index()[order],
                               materials=[A.Material(m.header, r) for m, r in zip(materials, runs)])


def native_body_swap(target: bytes, donor: bytes, *, rewrite: bool = False) -> tuple[bytes, dict]:
    """`target` pack with `donor` pack's body in slot 0; every other slot is the target's.

    The donor BIN goes in byte for byte (or, with `rewrite`, re-encoded by `recompose`). Its texture table replaces
    slot 1, padded with copies of its first image up to the target table's image count, so any other target model
    bound to slot 1 still finds every index it asks for (it gets the donor's art there). The pixels stay where
    they are: the table names the donor's archive.
    """
    pack, dat = A.pack_slots(target)
    _donor_pack, donor_dat = A.pack_slots(donor)
    body, table = _body(dat)
    donor_body, donor_table = _body(donor_dat)
    images = list(donor_table.images)
    images += [images[0]] * max(0, len(table.images) - len(images))
    before = [sha256(payload) for _ext, payload in dat.slots]
    written = recompose(donor_body) if rewrite else donor_body
    payload = written.build()
    dat.replace(BODY, payload)
    dat.replace(BODY_TPL, A.Tpl(images).slot())
    out = A.pack_build(pack, dat)
    _again_pack, again = A.pack_slots(out)
    after = [sha256(slot) for _ext, slot in again.slots]
    changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    if not set(changed) <= {BODY, BODY_TPL} or again.slots[BODY][1] != payload or (
            not rewrite and payload != donor_dat.slots[BODY][1]):
        raise ModelError(f"the rebuilt pack changed slots {changed}, expected the body and its table only")
    used = sorted({i for m in donor_body.materials() for i in m.textures()})
    triangle_count = sum(m.triangle_count for m in donor_body.materials())
    if sum(m.triangle_count for m in written.materials()) != triangle_count:
        raise ModelError("the rewritten body does not draw the donor's triangle count")
    return out, {"operation": "native body swap" + (", body rewritten by the composer" if rewrite else ""),
                 "slots_replaced": [BODY, BODY_TPL], "other_slots_byte_identical": len(after) - 2,
                 "body": {"stock_bytes": len(body.build()), "bytes": len(payload),
                          "donor_bin_bytes_kept": not rewrite, "vertices": written.vertex_count,
                          "donor_vertices": donor_body.vertex_count, "triangles": triangle_count,
                          "bones": donor_body.bone_count, "materials": donor_body.material_count,
                          "texture_indices_used": used, "donor_bin_sha256": sha256(donor_dat.slots[BODY][1])},
                 "texture_table": {"images": len(images), "donor_images": len(donor_table.images),
                                   "archives": sorted({i.archive() for i in images})},
                 "skeleton": skeleton_report(body, donor_body), "live_verified": False}


def shrink_part(payload: bytes, factor: float, centre=None) -> bytes:
    """A part model with its vertices pulled toward `centre` (default: its own centroid); topology untouched.

    A same-topology position edit is the one model change the earlier live rounds saw drawn, which is why a part
    is hidden this way instead of being emptied or rebuilt.
    """
    model = A.HdBin.parse(payload)
    points = model.positions().astype(np.float64)
    pivot = points.mean(0) if centre is None else np.asarray(centre, float)
    out = model.with_positions(pivot + (points - pivot) * factor).build()
    if len(out) != len(payload):
        raise ModelError("a position edit changed the slot size")
    return out


# ------------------------------------------------------------------------------------------------- donor bodies

def load_donor(source: Path, roles: dict[str, str] | None = None) -> dict:
    """A skinned .glb as the donor record `author_body` takes, through the loaders the RE5/RE6 writers use.

    `vertices` carry position, normal, atlas uv and the glTF node ids that drive them; `joints` are node rest
    positions, `parents` the node tree, `role_nodes` the body roles (given as joint names in `roles`, or derived
    from the joint tree by `characters.tree_roles` when the rig has no names). +y up, facing +z, left at +x.
    """
    from . import characters, mtf_materials

    vertices, faces, atlas, report = mtf_materials.source_mesh(Path(source), atlas_size=(1024, 1024))
    gltf, _acc, _image, world = characters._load(Path(source))
    names = roles or characters.tree_roles(Path(source))
    by_name = {node.get("name"): index for index, node in enumerate(gltf["nodes"])}
    missing = [role for role in ROLE_BONES if role not in names or names[role] not in by_name]
    if missing:
        raise ModelError(f"the donor has no joint for {missing}")
    return {"name": Path(source).name, "vertices": vertices, "faces": faces,
            "atlas": np.asarray(atlas.convert("RGBA"), np.uint8),
            "joints": {index: np.asarray(matrix, float)[:3, 3] for index, matrix in enumerate(world)},
            "parents": {child: index for index, node in enumerate(gltf["nodes"]) for child in node.get("children", [])},
            "role_nodes": {role: by_name[names[role]] for role in ROLE_BONES},
            "report": {k: v for k, v in report.items() if isinstance(v, (int, float, str, bool))}}


def fit(vertices: list[dict], joints: dict, parents: dict, role_nodes: dict[str, int], bones: dict[int, np.ndarray],
        *, scales: dict[str, float] = SCALES) -> tuple[np.ndarray, np.ndarray, list[list[tuple[int, float]]], dict]:
    """Donor vertices placed on the native bind skeleton: (positions, normals, per-vertex (bone, weight), report).

    Every donor joint influence walks up to the nearest role joint. A role's part is rotated so its segment points
    along the native one, stretched along it to the native length and scaled across it by the role family's
    factor, then anchored on the native bone - so each native joint sits where the donor's joint was drawn, and no
    native bind joint moves. A foot is anchored so the donor's sole meets the native floor (y = 0) and still
    weighted to the native foot bone; head and feet keep the donor's orientation. This is the
    `mtf_retarget.transfer` rule with a per-family cross-section.
    """
    from .mtf_retarget import _aim_rotation

    floor = min(float(v["position"][1]) for v in vertices)
    anchor = {role: np.asarray(bones[ROLE_BONES[role]], float) for role in ROLE_BONES}
    cross = {role: float(scales[ROLE_FAMILY.get(role, "limb")]) for role in ROLE_BONES}
    for side in ("r_foot", "l_foot"):
        height = float(joints[role_nodes[side]][1]) - floor
        anchor[side] = np.array([anchor[side][0], height * cross[side], anchor[side][2]])
    transform = {}
    for role in ROLE_BONES:
        start = role if role in SEGMENTS else next(a for a, b in SEGMENTS.items() if b == role)
        end = SEGMENTS[start]
        source = joints[role_nodes[end]] - joints[role_nodes[start]]
        target = anchor[end] - anchor[start]
        rotation = _aim_rotation(source, target)
        if role in SEGMENTS:
            axis = source / np.linalg.norm(source)
            along = float(np.linalg.norm(target) / np.linalg.norm(source))
            transform[role] = rotation @ (np.eye(3) * cross[role] + (along - cross[role]) * np.outer(axis, axis))
        else:
            transform[role] = (np.eye(3) if role in UPRIGHT else rotation) * cross[role]
    by_node = {node: role for role, node in role_nodes.items()}

    def role_of(joint: int) -> str:
        seen = set()
        while joint not in by_node:
            if joint in seen or joint not in parents:
                return "hip"                             # a joint above the hip (scene root) rides the hip
            seen.add(joint)
            joint = parents[joint]
        return by_node[joint]

    positions, normals, influences = [], [], []
    for vertex in vertices:
        point, normal = np.asarray(vertex["position"], float), np.asarray(vertex["normal"], float)
        moved, turned, merged = np.zeros(3), np.zeros(3), {}
        for joint, weight in zip(vertex["source_joints"], vertex["source_weights"]):
            if weight <= 0:
                continue
            role = role_of(int(joint))
            moved += weight * (transform[role] @ (point - joints[role_nodes[role]]) + anchor[role])
            turned += weight * (np.linalg.inv(transform[role]).T @ normal)
            merged[ROLE_BONES[role]] = merged.get(ROLE_BONES[role], 0.0) + float(weight)
        total = sum(merged.values())
        if total <= 0 or not np.isfinite(moved).all():
            raise ModelError("a donor vertex has no usable joint influence")
        length = float(np.linalg.norm(turned))
        positions.append(moved / total)
        normals.append(turned / length if length > 1e-9 else np.array([0.0, 1.0, 0.0]))
        influences.append(sorted(merged.items()))
    report = {"method": "per-role rotate + stretch onto the native bind joints; native bind joints not moved",
              "scales": dict(scales), "donor_floor": floor,
              "foot_anchor_height": {s: float(anchor[s][1]) for s in ("r_foot", "l_foot")},
              "roles": {role: {"donor_node": int(role_nodes[role]), "bone": ROLE_BONES[role]} for role in ROLE_BONES}}
    return np.asarray(positions), np.asarray(normals), influences, report


def author_body(target: bytes, archive: bytes, donor: dict, *, image: int = 5, shrink: float = 0.1,
                scales: dict[str, float] = SCALES) -> tuple[bytes, tuple[str, bytes], dict]:
    """A donor body on `target`'s skeleton: (pack bytes, (archive file name, archive bytes), receipt).

    The donor surface replaces the body mesh (slot 0) as one material drawn with the donor's atlas, which is
    appended to the pack's own archive and named by table image `image` (an image only the body uses). The native
    head, face, hair, far head and hands are shrunk to `shrink` of their size where they stand, because the donor
    brings its own head and hands in the body mesh.
    """
    pack, dat = A.pack_slots(target)
    body, table = _body(dat)
    if not 0 <= image < len(table.images):
        raise ModelError(f"the body table has {len(table.images)} images; {image} is not one of them")
    vertices, faces = donor["vertices"], donor["faces"]
    bones = body.bone_world()
    absent = [role for role, bone in ROLE_BONES.items() if bone not in bones]
    if absent:
        raise ModelError(f"the body skeleton has no bone for {absent}")
    positions, normals, influences, fit_report = fit(vertices, donor["joints"], donor["parents"], donor["role_nodes"],
                                                     bones, scales=scales)
    sets, index, step = A.weight_table(influences)
    order, runs = A.soup([np.asarray(faces, np.int64)])
    native = body.materials()
    plain = next((m for m in native if m.header[11] == 0 and m.textures() == [m.diffuse]), native[0])
    header = bytearray(plain.header)
    header[12], header[13], header[14], header[15], header[23] = image, 0xFF, 0xFF, 0xFF, 0xFF
    uvs = np.asarray([v["uv"] for v in vertices], float)
    built = body.with_geometry(positions=positions[order], normals=normals[order], uvs=uvs[order],
                               weight_sets=sets, weight_index=index[order],
                               materials=[A.Material(bytes(header), runs[0])])
    pixels = np.asarray(donor["atlas"], np.uint8)
    images = A.ImagePack.parse(archive)
    if images.pack_id != table.images[image].pack_id:
        raise ModelError("the archive is not the one the body's texture table names")
    entry = images.append(A.encode_dds(pixels))
    table.images[image] = A.TplImage(pixels.shape[1] // 4, pixels.shape[0] // 4, 0x0E, images.pack_id, entry,
                                     table.images[image].sampler)
    before = [sha256(payload) for _ext, payload in dat.slots]
    dat.replace(BODY, built.build())
    dat.replace(BODY_TPL, A.Tpl(table.images).slot())
    low, high = positions.min(0), positions.max(0)
    head_centre = np.asarray(bones[ROLE_BONES["head"]], float) + [0.0, 0.25 * (high[1] - bones[ROLE_BONES["head"]][1]), 0.0]
    hidden = {}
    for slot in (HEAD, FACE, HAIR, FAR_HEAD) + HANDS:
        ext, payload = dat.slots[slot]
        if ext != "BIN":
            continue
        centre = head_centre if slot in (HEAD, FACE, HAIR) else None
        dat.replace(slot, shrink_part(payload, shrink, centre))
        hidden[slot] = "toward the donor head" if centre is not None else "toward its own centroid"
    out = A.pack_build(pack, dat)
    _again_pack, again = A.pack_slots(out)
    after = [sha256(payload) for _ext, payload in again.slots]
    changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    if changed != sorted({BODY, BODY_TPL, *hidden}):
        raise ModelError(f"the rebuilt pack changed slots {changed}")
    check = A.HdBin.parse(again.slots[BODY][1])
    used_bones = sorted({bone for entry_ in check.weights() for bone, _w in entry_})
    name = f"{images.pack_id:08x}.pack.fen"
    receipt = {"operation": "donor body authored on the native skeleton", "source": donor.get("name"),
               "source_report": donor.get("report", {}),
               "fit": fit_report,
               "body": {"vertices": check.vertex_count, "triangles": len(faces), "materials": check.material_count,
                        "weight_sets": check.weight_count, "weight_percent_step": step, "bones_used": used_bones,
                        "bones": check.bone_count, "bytes": [len(body.build()), len(built.build())],
                        "bbox": [low.round(2).tolist(), high.round(2).tolist()],
                        "skeleton_bytes_identical": check.sections["bones"] == body.sections["bones"]},
               "texture": {"archive": name, "entry": entry, "table_image": image, "width": int(pixels.shape[1]),
                           "height": int(pixels.shape[0]), "format": "DXT5", "entries": len(images.entries)},
               "parts_shrunk": {str(k): v for k, v in sorted(hidden.items())}, "shrink": shrink,
               "slots_replaced": changed, "other_slots_byte_identical": len(after) - len(changed),
               "live_verified": False}
    return out, (name, images.build()), receipt


def write_overlay(root: Path, files: dict[str, bytes], receipt: dict, sources: dict[str, bytes]) -> dict:
    """Write `files` under `root/romfs/` and a `receipt.json` beside it. `sources` are the stock files by the same
    relative name (their hashes go in the receipt); refuses to write over an existing overlay."""
    root = Path(root)
    if (root / "receipt.json").exists():
        raise ModelError(f"{root} already holds an overlay; candidates are never overwritten")
    rows = []
    for name, payload in files.items():
        path = root / "romfs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        stock = sources.get(name)
        rows.append({"path": f"romfs/{name}", "bytes": len(payload), "sha256": sha256(payload),
                     "source_bytes": len(stock) if stock is not None else None,
                     "source_sha256": sha256(stock) if stock is not None else None})
    receipt = {"title_id": TITLE_ID, "files": rows} | receipt | {"live_verified": False}
    (root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="RE4 Switch player model overlays (offline; never booted here)")
    sub = parser.add_subparsers(dest="command", required=True)
    swap = sub.add_parser("native-swap", help="another pack's body in a pack's body slot")
    swap.add_argument("--em", type=Path, required=True, help="a folder holding the stock plXX.udas files")
    swap.add_argument("--target", default="pl08")
    swap.add_argument("--donor", required=True)
    swap.add_argument("--rewrite", action="store_true", help="re-encode the donor body through the composer")
    swap.add_argument("--out", type=Path, required=True)
    author = sub.add_parser("author", help="a skinned .glb written onto a pack's own skeleton")
    author.add_argument("--em", type=Path, required=True)
    author.add_argument("--imagepack", type=Path, required=True, help="a folder holding the stock .pack.fen files")
    author.add_argument("--target", default="pl08")
    author.add_argument("--source", type=Path, required=True)
    author.add_argument("--out", type=Path, required=True)
    for command in (swap, author):
        command.add_argument("--expect", default="", help="what a live round must show; stored in the receipt")
    args = parser.parse_args(argv)
    target = (args.em / f"{args.target}.udas").read_bytes()
    if args.command == "native-swap":
        donor = (args.em / f"{args.donor}.udas").read_bytes()
        out, receipt = native_body_swap(target, donor, rewrite=args.rewrite)
        name = f"{PACK_DIR}/{args.target}.udas"
        receipt |= {"target_pack": args.target, "donor_pack": args.donor, "donor_pack_sha256": sha256(donor),
                    "expect_live": args.expect}
        result = write_overlay(args.out, {name: out}, receipt, {name: target})
    else:
        _pack, dat = A.pack_slots(target)
        archive_name = A.Tpl.parse(dat.slots[BODY_TPL][1]).images[0].archive()
        archive = (args.imagepack / archive_name).read_bytes()
        out, (written_name, written), receipt = author_body(target, archive, load_donor(args.source))
        if written_name != archive_name:
            raise ModelError("the writer grew another archive than the one that was read")
        files = {f"{PACK_DIR}/{args.target}.udas": out, f"{IMAGE_DIR}/{written_name}": written}
        receipt |= {"target_pack": args.target, "source_sha256": sha256(args.source.read_bytes()),
                    "expect_live": args.expect}
        result = write_overlay(args.out, files, receipt, {f"{PACK_DIR}/{args.target}.udas": target,
                                                          f"{IMAGE_DIR}/{archive_name}": archive})
    print(json.dumps({"out": str(args.out), "files": result["files"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
