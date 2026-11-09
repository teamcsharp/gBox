"""Resident Evil 6 (Switch, No Mercy edition) model replacement: MTF body MOD authoring.

RE6 keeps each player body in an MTF `.arc` under `nativeNXx64/arc/NX` (`uPl00LeonUsa.arc`, ...), one archive per
native character and costume; the body's `data\\chara\\pl\\plNNNN\\model\\plNNNN` entry holds an `MRL` (materials) and a
`MOD` (geometry + skeleton). The skeleton's 24-byte bone headers carry a Smash-style animation id at +0; measured on
`uPl00LeonUsa.arc`, those ids are the **RE6 global bone ids** also used by the Xbox 360 edition (1 hip, 2 chest, 3 neck,
4 head, 5/6/7/8 right clav/upper/fore/hand, 10..13 left, 15 pelvis, 16/17/18 right thigh/shin/foot, 20/21/22 left), so a
role maps to a bone index by looking up the anim id. The body skeleton is 54 bones with the root at the hip height.

The writer preserves the native skeleton, groups, materials and compression transform and replaces the geometry (the
same rule as the Xbox 360 `fit_source_proportions`: the donor surface is fit uniformly, the native bind joints move to
the donor's joints, every vertex binds to its nearest named ancestor). It does not yet retarget the donor's textures:
RE6 keeps player textures in separate `uPlTex####_*.arc` archives, so the first port replaces geometry only (the native
material still samples its own textures). A separate texture step is required for a fully retextured donor.

This module is the Switch counterpart of the Xbox 360 `re6_models` writer; it produces bytes for `switch_mods` LayeredFS
overlays (`romfs/nativeNXx64/arc/NX/...`), never a disc edit.
"""
from __future__ import annotations

import math
import re
import zlib
from pathlib import Path

import numpy as np

from . import mt_arc, mt_model, mtf_author, mtf_materials, mtf_retarget

ARCHIVE_DIR = Path("nativeNXx64") / "arc" / "NX"
TITLE_ID = "01002A000CD48000"
GAME_ID = "115f9cdbba115432"
BODY_RE = re.compile(r"^uPl([0-9A-Fa-f]{2})(?P<name>[A-Za-z]+)(?P<costume>[A-Za-z0-9]+)\.arc$",
                     re.IGNORECASE)
PART_MARKERS = ("achead", "head", "hand", "tex")


def _is_part_archive(stem: str) -> bool:
    """Head / hand / accessory-head / texture archives are not body arcs (whatever the character's number)."""
    lower = stem.lower()
    return any(marker in lower for marker in PART_MARKERS)

#: RE6 global bone ids (the anim id in the MTF bone header). Identical ids on the Xbox 360 edition (re6_models).
ROLE_IDS = {"hip": 1, "chest": 2, "neck": 3, "head": 4,
            "r_clav": 5, "r_upper": 6, "r_fore": 7, "r_hand": 8,
            "l_clav": 10, "l_upper": 11, "l_fore": 12, "l_hand": 13,
            "r_thigh": 16, "r_shin": 17, "r_foot": 18,
            "l_thigh": 20, "l_shin": 21, "l_foot": 22}
ROOT_ROLE = "hip"                     # the hip is the MTF root bone (id 1, index 0 in the measured body)
REQUIRED = ("hip", "chest", "neck", "head", "r_upper", "r_fore", "r_hand", "l_upper", "l_fore", "l_hand",
            "r_thigh", "r_shin", "r_foot", "l_thigh", "l_shin", "l_foot")


class SwitchModelError(ValueError):
    """The archive/skeleton is not the measured RE6 Switch player body, or the donor cannot be fitted."""


def archive_root(romfs: Path) -> Path:
    root = Path(romfs) / ARCHIVE_DIR
    if not root.is_dir():
        raise SwitchModelError(f"{root} is not a directory: is this the RE6 RomFS with nativeNXx64/arc/NX?")
    return root


def body_arcs(root: Path) -> dict[tuple[str, str], Path]:
    """{(character, costume): body archive path} for every native body arc in the extracted tree.

    The canonical slot -> default archive mapping is `gbox.skin_swap.CHARACTER_ARCS` (the same table the archive-swap
    route uses); every other `uPlXX<Name><costume>.arc` with the same prefix is that character's costume body. Head,
    hand, accessory-head and texture archives are excluded (they are separate resources).
    """
    from . import skin_swap
    from .re6_models import CHARACTERS

    known = skin_swap.CHARACTER_ARCS[TITLE_ID]
    out: dict[tuple[str, str], Path] = {}
    for character, rel in known.items():
        default = Path(rel).name
        match = re.match(r"^uPl([0-9A-Fa-f]{2})", default)
        if not match or character not in CHARACTERS:
            continue
        prefix = match.group(1)
        costumes = sorted(list(CHARACTERS[character]["costumes"]) + ["DebugId"], key=len, reverse=True)
        for path in sorted(archive_root(root).glob(f"uPl{prefix}*.arc")):
            stem = path.stem
            if _is_part_archive(stem):
                continue
            suffix = stem[6:]                      # after "uPlXX"
            costume = next((c for c in costumes if suffix.lower().endswith(c.lower())), None)
            if costume is None:
                continue
            out.setdefault((character, costume), path)
    if not out:
        raise SwitchModelError(f"no player body archives under {archive_root(root)}")
    return out


def part_arc(root: Path, stem: str) -> Path | None:
    path = archive_root(root) / f"{stem}.arc"
    return path if path.is_file() else None


def roles_for(model) -> dict[str, int]:
    """{role: bone index} from the bone headers' anim ids; the measured body skeleton must match its own ids."""
    table = model.bone_table()
    if not table.get("consistent"):
        raise SwitchModelError("the body MOD skeleton is incomplete")
    by_anim: dict[int, int] = {}
    for index, anim in enumerate(table["anim_map"]):
        by_anim.setdefault(int(anim), index)
    roles = {role: by_anim[role_id] for role, role_id in ROLE_IDS.items() if role_id in by_anim}
    missing = [role for role in REQUIRED if role not in roles]
    if missing:
        raise SwitchModelError(f"the body skeleton lacks {missing} (bone ids {sorted(by_anim)})")
    return roles


def _find_model(arc) -> tuple[int, int, bytes]:
    matches = {}
    for index, entry in enumerate(arc.entries):
        try:
            raw = zlib.decompress(entry.data)
        except zlib.error:
            raw = entry.data
        if raw[:4] in (b"MOD\0", b"MRL\0"):
            matches.setdefault(raw[:4], (index, raw))
    if b"MOD\0" not in matches:
        raise SwitchModelError("the body archive holds no MOD")
    mod_index, mod_raw = matches[b"MOD\0"]
    return mod_index, matches.get(b"MRL\0", (-1, b""))[0], mod_raw


def _source_rig(source: Path, roles: dict[str, str]):
    """The donor's joints, per-vertex influences and world matrices from gbox.characters (same loader as RE5)."""
    from . import characters

    gltf, _, _, world = characters._load(Path(source))
    names = {}
    for index, node in enumerate(gltf["nodes"]):
        if node.get("name") in roles.values():
            if node["name"] in names:
                raise SwitchModelError("donor role node names must be unique")
            names[node["name"]] = index
    absent = [name for name in roles.values() if name not in names]
    if absent:
        raise SwitchModelError(f"the donor lacks named role joints: {absent}")
    parents = {child: i for i, node in enumerate(gltf["nodes"]) for child in node.get("children", [])}
    joints = {i: tuple(map(float, matrix[:3, 3])) for i, matrix in enumerate(world)}
    return gltf, names, parents, joints


def _source_geometry(source: Path):
    """The donor's body surface: merged vertices (position, normal, uv, source influences) and triangles.

    Unlike `mtf_materials.source_mesh` this does not pack textures: an RE6 body MOD has no texture table (the
    player's textures live in `uPlTex####_*.arc`), so only geometry and UVs are needed here. Source joint indices are
    the glTF node indices, the same space `mtf_retarget.map_weights` walks with `parents`.
    """
    from . import characters

    gltf, acc, _image, world = characters._load(Path(source))
    vertices, triangles = [], []
    for node_index, node in enumerate(gltf.get("nodes", [])):
        if "mesh" not in node:
            continue
        skin = gltf["skins"][node["skin"]] if "skin" in node and "skins" in gltf else None
        joint_nodes = skin["joints"] if skin else None
        # a rigid prop node (sword, tome) carries its own place in the model; a skinned node's POSITION is already
        # model-space in the collection GLBs
        transform = np.asarray(world[node_index], float) if skin is None else None
        for prim in gltf["meshes"][node["mesh"]].get("primitives", []):
            attributes = prim["attributes"]
            positions = acc(attributes["POSITION"]).astype(float)
            if transform is not None and len(positions):
                positions = positions @ transform[:3, :3].T + transform[:3, 3]
            normals = acc(attributes["NORMAL"]).astype(float) if "NORMAL" in attributes else np.tile([0, 1.0, 0],
                                                                                                   (len(positions), 1))
            uvs = acc(attributes["TEXCOORD_0"]).astype(float) if "TEXCOORD_0" in attributes else np.zeros((len(positions), 2))
            joints = acc(attributes["JOINTS_0"]).astype(int) if "JOINTS_0" in attributes else None
            weights = acc(attributes["WEIGHTS_0"]).astype(float) if "WEIGHTS_0" in attributes else None
            base = len(vertices)
            for index in range(len(positions)):
                influences = []
                if joints is not None and weights is not None:
                    for slot, weight in zip(joints[index], weights[index]):
                        if weight <= 0 or not np.isfinite(weight):
                            continue
                        joint = int(joint_nodes[int(slot)]) if joint_nodes is not None else int(slot)
                        influences.append((joint, float(weight)))
                total = sum(weight for _joint, weight in influences)
                if total > 0:
                    influences = [(joint, weight / total) for joint, weight in influences]
                normal = np.asarray(normals[index], float)
                length = float(np.linalg.norm(normal))
                if not np.all(np.isfinite(normal)) or length < 1e-8:
                    normal = np.array([0.0, 1.0, 0.0])       # a degenerate donor normal must not abort the author
                else:
                    normal = normal / length
                position = np.asarray(positions[index], float)
                if not np.all(np.isfinite(position)):
                    position = np.zeros(3)
                uv = np.asarray(uvs[index], float)
                if not np.all(np.isfinite(uv)):
                    uv = np.zeros(2)
                vertices.append({"position": tuple(position), "normal": tuple(normal),
                                 "uv": tuple(uv), "source_joints": [j for j, _ in influences],
                                 "source_weights": [w for _, w in influences]})
            for triangle in acc(prim["indices"]).reshape(-1, 3):
                triangles.append(tuple(int(i) + base for i in triangle))
    if not vertices or not triangles:
        raise SwitchModelError(f"{source} has no body geometry")
    return vertices, triangles


def build_body(archive: bytes, source: Path, *, source_roles: dict[str, str], height: float = 180.0,
               material_index: int = 0, template_index: int = 0, margin: float = 0.01,
               atlas_size=(512, 512)) -> tuple[bytes, dict]:
    """Return (new archive, receipt) with the donor's surface authored onto the native body skeleton.

    ``source_roles`` maps a collection role ('hip', 'chest', ...) to the donor's joint name; ``material_index`` picks
    the native material the new mesh is drawn with (the MRL is kept untouched). The donor geometry is scaled
    uniformly to ``height`` (cm), its feet on the native floor and its hip above the native root; the native bind
    joints are moved to the donor's joint positions, never the donor stretched. Raises when the fitted surface cannot
    be represented by the native position transform.
    """
    arc = mt_arc.parse(bytes(archive))
    model_index, mrl_index, mod_raw = _find_model(arc)
    model = mt_model.parse_mod(mod_raw)
    roles = roles_for(model)
    if ROOT_ROLE not in source_roles:
        raise SwitchModelError(f"the donor needs a '{ROOT_ROLE}' joint (the native root bone is the hip)")
    from . import characters

    vertices, triangles = _source_geometry(Path(source))
    gltf, names, parents, joints = _source_rig(Path(source), source_roles)
    roles_map = {role: (names[name], roles[role]) for role, name in source_roles.items() if role in roles}
    missing = [role for role in REQUIRED if role not in roles_map]
    if missing:
        raise SwitchModelError(f"the donor cannot supply target roles {missing}")
    # the native root stays fixed; the hip bone is index 1 and is moved to the fitted donor hip
    # uniform fit into the native quantisation box (same rule as the Xbox 360 writer)
    positions = np.asarray([v["position"] for v in vertices], float)
    low, high = positions.min(0), positions.max(0)
    source_height = float(high[1] - low[1])
    if not math.isfinite(source_height) or source_height <= 1e-6:
        raise SwitchModelError("the donor has no measurable height")
    bounds = model.bounds()
    native_lo = np.asarray([bounds["min"][axis] for axis in "xyz"], float)
    native_hi = np.asarray([bounds["max"][axis] for axis in "xyz"], float)
    transform = np.asarray(model.position_transform(), float).reshape(4, 4)
    scale_axis = float(transform[0, 0])
    if not np.allclose(transform[:3, :3], np.eye(3) * scale_axis, atol=1e-6 * max(1.0, abs(scale_axis))):
        raise SwitchModelError("the native position transform is not a uniform scale")
    offset = np.asarray(transform[3, :3], float)
    box_lo, box_hi = offset, offset + scale_axis
    inner_lo, inner_hi = box_lo + scale_axis * margin, box_hi - scale_axis * margin
    hip = np.asarray(joints[roles_map[ROOT_ROLE][0]], float)
    origin = np.array([hip[0], low[1], hip[2]], float)
    root_world = model.bone_world()[0]
    root = np.asarray(root_world[1:], float)                  # (index, x, y, z) -> the root's rest position
    floor = max(float(native_lo[1]), float(inner_lo[1]))
    extent = np.maximum(high - low, 1e-6)
    available = np.array([inner_hi[0] - inner_lo[0], inner_hi[1] - floor, inner_hi[2] - inner_lo[2]], float)
    scale = min(float(height) / source_height, *(float(available[i] / extent[i]) for i in range(3)))
    if scale <= 1e-6:
        raise SwitchModelError("the native box cannot hold the donor")
    translate = np.array([float(root[0]), floor, float(root[2])], float)
    scaled = (positions - origin) * scale
    slo, shi = scaled.min(0), scaled.max(0)
    for axis in (0, 2):
        low_violation = inner_lo[axis] - (slo[axis] + translate[axis])
        high_violation = (shi[axis] + translate[axis]) - inner_hi[axis]
        if low_violation > 0:
            translate[axis] += low_violation
        elif high_violation > 0:
            translate[axis] -= high_violation
    fitted = [v | {"position": tuple((np.asarray(v["position"], float) - origin) * scale + translate)}
              for v in vertices]
    fitted_low = np.asarray([v["position"] for v in fitted]).min(0)
    fitted_high = np.asarray([v["position"] for v in fitted]).max(0)
    outside = float(max(np.max(box_lo - fitted_low), np.max(fitted_high - box_hi), 0.0))
    if outside > 1e-4:
        raise SwitchModelError(f"the fitted model leaves the native quantisation box by {outside:.3f} units")
    anchors = {target: tuple((np.asarray(joints[source_joint], float) - origin) * scale + translate)
               for source_joint, target in roles_map.values() if target != 0}
    fallback = None
    try:
        model, bind = mtf_retarget.reposition_bind_pose(model, anchors)
    except ValueError as exc:
        # A native skeleton with more than one root (or anchor branches that cannot hold the donor's proportions)
        # cannot have its joints moved by the measured rule. Keep the native skeleton as it is: the donor surface
        # still rests at its own proportions and binds rigidly to the nearest native bone, so the slot is filled
        # instead of skipped; only animation deformation is approximate.
        bind, fallback = {"skipped": str(exc)}, str(exc)
    # Every source influence must walk to a named role; unmapped root/finger influences fall back to the hip role.
    source_anchors = {source_joint for source_joint, _target in roles_map.values()}

    def reaches_anchor(joint: int) -> bool:
        current, seen = joint, set()
        while current not in source_anchors:
            if current in seen or current not in parents:
                return False
            seen.add(current)
            current = parents[current]
        return True

    for vertex in fitted:
        keep = [(joint, weight) for joint, weight in zip(vertex.get("source_joints", ()),
                                                        vertex.get("source_weights", ())) if reaches_anchor(joint)]
        if not keep:
            keep = [(roles_map[ROOT_ROLE][0], 1.0)]
        total = sum(weight for _joint, weight in keep)
        vertex["source_joints"] = [joint for joint, _weight in keep]
        vertex["source_weights"] = [weight / total for _joint, weight in keep]
    fitted, skin = mtf_retarget.map_weights(fitted, parents, roles_map)
    authored = mtf_author.build_one_mesh(model, fitted, triangles, material_index=material_index,
                                        template_index=template_index, four_weights=True)
    bounds_new = {"min": dict(zip("xyz", fitted_low)), "max": dict(zip("xyz", fitted_high)),
                  "sphere": dict(zip("xyz", (fitted_low + fitted_high) / 2)) |
                             {"r": float(np.linalg.norm(fitted_high - fitted_low) / 2)}}
    authored = mt_model.rebuild_mod(mt_model.parse_mod(authored), bounds=bounds_new)
    payload = mtf_author.replace_archive_model(bytes(archive), model_index, authored)
    receipt = {"pose_mode": "native_skeleton" if fallback else "source_proportions",
               "skeleton_fallback": fallback, "source_height": source_height,
               "fitted_height": float(fitted_high[1] - fitted_low[1]), "uniform_scale": scale,
               "height_clamped": bool(abs(scale * source_height - height) > 1e-4),
               "box_usage": float(np.max(fitted_high - fitted_low) / scale_axis),
               "roles": {role: index for role, (joint, index) in roles_map.items()},
               "root_index": roles_map[ROOT_ROLE][1], "bind": bind, "skin": skin,
               "material_index": material_index, "triangle_count": len(triangles), "vertex_count": len(fitted),
               "model_entry": model_index, "mrl_entry": mrl_index,
               "textures": "native material kept: the donor's textures are not yet written (uPlTex####_*.arc step)",
               "archive_sha256": None, "live_verified": False}
    import hashlib
    receipt["archive_sha256"] = hashlib.sha256(payload).hexdigest()
    return payload, receipt


def buildable_slots(romfs: Path) -> dict[tuple[str, str], Path]:
    """Only the body slots whose skeleton carries the measured 18-role humanoid layout.

    The extracted tree also contains non-humanoid bodies (the helper/creature slots and some debug costumes) whose
    bone ids are a different family; they are skipped instead of failing the roster.
    """
    out: dict[tuple[str, str], Path] = {}
    for slot, path in body_arcs(romfs).items():
        try:
            _, _, mod_raw = _find_model(mt_arc.parse(path.read_bytes()))
            roles_for(mt_model.parse_mod(mod_raw))
        except (SwitchModelError, mt_model.ModelError, mt_arc.ArcError):
            continue
        out[slot] = path
    return out


def part_stems(body: Path) -> list[str]:
    """The head/hand/accessory-head stems that belong to a body archive stem (`uPl00LeonUsa` -> 4 stems)."""
    stem = Path(body).stem
    prefix, rest = stem[:5], stem[5:]
    return [f"{prefix}Head{rest}", f"{prefix}HandLeft{rest}", f"{prefix}HandRight{rest}", f"{prefix}AcHead{rest}"]


def blank_arc(archive: bytes) -> bytes:
    """A part archive whose model is one degenerate triangle at the root: the native part disappears in place.

    The material/MRL and the rest of the archive are kept, so the game still loads the resource and the part simply
    draws nothing visible; this is the Switch counterpart of the Xbox 360 writer's blanked head/hands.
    """
    arc = mt_arc.parse(bytes(archive))
    model_index, _mrl, mod_raw = _find_model(arc)
    model = mt_model.parse_mod(mod_raw)
    root = model.bone_world()[0]
    x, y, z = float(root[1]), float(root[2]), float(root[3])
    vertices = [{"position": (x + dx, y + dy, z + dz), "normal": (0.0, 1.0, 0.0), "uv": (0.0, 0.0),
                 "bones": [0], "weights": [1.0]} for dx, dy, dz in ((0, 0, 0), (0.01, 0, 0), (0, 0.01, 0))]
    authored = mtf_author.build_one_mesh(model, vertices, [(0, 1, 2)], material_index=0, template_index=0,
                                        four_weights=False)
    authored = mt_model.rebuild_mod(mt_model.parse_mod(authored),
                                    bounds={"min": {"x": x, "y": y, "z": z}, "max": {"x": x + 0.01, "y": y + 0.01,
                                                                                      "z": z},
                                            "sphere": {"x": x, "y": y, "z": z, "r": 0.02}})
    return mtf_author.replace_archive_model(bytes(archive), model_index, authored)


def character_changes(root: Path, character: str, source: Path, *, source_roles: dict[str, str],
                      costumes: list[str] | None = None, height: float = 180.0, blank: bool = True,
                      progress=None) -> tuple[dict, list[dict]]:
    """LayeredFS changes (romfs-relative path -> {"bytes"}) that put ``source`` on every costume of ``character``.

    Every body arc is authored and, when ``blank`` is true, its head/hand/accessory-head parts are replaced by a
    degenerate triangle so the donor is the whole visible body. Returns ``(changes, receipts)``; nothing is written.
    """
    root = Path(root)
    bodies = {(char, costume): path for (char, costume), path in body_arcs(root).items() if char == character}
    if costumes:
        wanted = {costume.lower() for costume in costumes}
        bodies = {(c, k): p for (c, k), p in bodies.items() if k.lower() in wanted}
    if not bodies:
        raise SwitchModelError(f"{character} has no body archive in this RomFS")
    changes: dict[str, dict] = {}
    receipts = []
    for (char, costume), path in sorted(bodies.items()):
        if progress:
            progress(f"{char}/{costume}: authoring body")
        payload, receipt = build_body(path.read_bytes(), source, source_roles=source_roles, height=height)
        key = f"romfs/{ARCHIVE_DIR.as_posix()}/{path.name}"
        changes[key] = {"bytes": payload}
        receipt = {"character": char, "costume": costume, "archive": path.name, **receipt}
        if blank:
            for stem in part_stems(path):
                part = archive_root(root) / f"{stem}.arc"
                if not part.is_file():
                    continue
                changes[f"romfs/{ARCHIVE_DIR.as_posix()}/{part.name}"] = {"bytes": blank_arc(part.read_bytes())}
                receipt.setdefault("blanked_parts", []).append(part.name)
        receipts.append(receipt)
    return changes, receipts


def export_preview(archive: bytes, gltf_path: Path, png_path: Path | None = None, *, size: int = 384) -> dict:
    """Write the authored body's geometry as a skinned glTF (and a z-buffered PNG) for evidence.

    The authored vertices are model-space (the writer packs them with the native quantisation transform), so the
    preview is what the engine will place in the world; materials/textures are the native ones and are not shown.
    """
    from . import characters, melee_models

    arc = mt_arc.parse(bytes(archive))
    _, _, mod_raw = _find_model(arc)
    model = mt_model.parse_mod(mod_raw)
    table = model.bone_table()
    world = model.bone_world()
    positions = model.positions(0)
    normals = model.normals(0)
    uvs = model.uvs(0)
    triangles = model.triangles()
    if not positions or not triangles:
        raise SwitchModelError("the authored model has no geometry to preview")
    joints = []
    for index, _x, _y, _z in world:
        parent = int(table["parents"][index])
        matrix = np.eye(4)
        matrix[:3, 3] = (world[index][1], world[index][2], world[index][3])
        joints.append({"parent": parent if 0 <= parent < len(world) else -1, "world": matrix})
    count = len(positions)
    prim = {"pos": np.asarray(positions, np.float32), "nrm": np.asarray(normals or [(0, 1, 0)] * count, np.float32),
            "uv": np.asarray(uvs or [(0, 0)] * count, np.float32), "tris": np.asarray(triangles, np.int64),
            "J": np.zeros((count, 4), np.int64), "W": np.zeros((count, 4), np.float32), "color": (200, 200, 200, 255)}
    prim["W"][:, 0] = 1.0
    melee_models.write_gltf(Path(gltf_path), joints, [prim], 1.0, "re6_switch", [f"j{i:03d}" for i in range(len(joints))])
    out = {"gltf": str(gltf_path), "vertices": count, "triangles": len(triangles), "joints": len(joints)}
    if png_path is not None:
        characters.render_preview(Path(gltf_path), Path(png_path), size=size, depth=True)
        out["preview"] = str(png_path)
    return out
