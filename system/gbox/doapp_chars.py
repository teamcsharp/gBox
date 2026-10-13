"""Dead Or Alive ++ (arcade, Tecmo TPS, MAME doapp / doappk): fighters -> rigged, textured GLBs with body roles (#1340).

Everything comes from the owned ROMs and the game's own code (docs/doapp_pipeline.md):

* the program is decoded by the TPS BIOS's code on gbox.zn_tps_boot's interpreter (doapp_inventory.decode_owned);
* gbox.doapp_motion.Rig loads both players the way the fight loader does and runs the fight init, the motion player
  and the skeleton build (0x800a4848: FK, two-bone IK, head look, accessory chain physics) with a GTE model;
* the rest pose is frame 0 of the stance loop (move 0 -> motion 0) after one full loop, so the chains have settled;
  the bind matrices are the game's bone matrices for that frame (0x8011ca60, 15 body bones + accessory bones);
* the model's 8 mesh slots (expanded by the game's own 0x8006c718) give vertex batches per bone (rigid skinning, one
  joint per vertex), the chunk records give the primitives (doapp_models.primitives) and the TIMs give the textures
  (256 x 256 PS1 texture pages decoded with each primitive's CLUT, cropped to what the primitives sample).

Skinned at the bind pose the mesh is exactly what the game transforms for that frame. Verification per costume:
every vertex has a bone, every textured primitive samples the model's own TIMs, the seam triangles (chunk 0x805a,
the only primitives joining two bones) stay short, the feet touch the ground and the height is a fighter's.

glTF frame: game (x, y down, z) -> (x, -y, -z), the fighter faces +Z with its left at +X; metres = game units x 0.001.
Clips (optional): the game's matrices per frame of a motion (60 fps), as joint TRS animations.

  python -m gbox.doapp_chars <dir with doapp.zip + coh1002m.zip> <out dir> [fighter ...] [--costumes 0,1,2,3]
"""
from __future__ import annotations

import hashlib
import json

import struct
import zlib
from pathlib import Path

import numpy as np

from . import doapp_inventory as D
from . import doapp_models as M
from . import doapp_motion as DM

SCALE = 0.001
FLIP = np.diag([1.0, -1.0, -1.0])
# game bone index -> (joint name, parent bone, collection role); order = joint order in the GLB
BODY = ((2, "pelvis", None, "hip"), (0, "torso", 2, "chest"), (1, "head", 0, "head"),
        (8, "l_upper_arm", 0, "l_upper"), (4, "l_forearm", 8, "l_fore"), (5, "l_hand", 4, "l_hand"),
        (14, "r_upper_arm", 0, "r_upper"), (10, "r_forearm", 14, "r_fore"), (11, "r_hand", 10, "r_hand"),
        (6, "l_thigh", 2, "l_thigh"), (7, "l_shin", 6, "l_shin"), (3, "l_foot", 7, "l_foot"),
        (12, "r_thigh", 2, "r_thigh"), (13, "r_shin", 12, "r_shin"), (9, "r_foot", 13, "r_foot"))
BODY_BONES = 15
CHAIN_TABLE = 0x80103AB8         # u32 per (fighter * 17 + costume): {entries, ...}; entry 10 bytes {links, anchor, ...}
CLIPS = {"stance": 0}
SEAM_LIMIT = 400                 # game units: longest seam-triangle edge accepted at the bind pose
HEIGHT = (1300, 2000)
GROUND = 60


class ReaderError(ValueError):
    pass


def _title(name: str) -> str:
    return " ".join(w.capitalize() for w in name.split())


def roster() -> list[dict]:
    """11 fighters x 4 costumes (doapp_inventory.FIGHTERS)."""
    out = []
    for f in D.FIGHTERS:
        nice = _title(f["name"])
        base = "doapp_" + f["name"].lower().replace(" ", "_")
        for c in range(D.COSTUMES):
            out.append({"key": f"{f['name'].lower().replace(' ', '_')}_c{c + 1}", "slug": f"{base}_{c + 1}",
                        "fighter": f["id"], "costume": c, "kind": "character",
                        "name": f"{nice} (costume {c + 1}, Dead Or Alive ++)",
                        "aliases": [f"{nice} {c + 1}", f"{nice} costume {c + 1}", f"DOA++ {nice} {c + 1}"]
                                   + ([nice, f"DOA++ {nice}", f"Dead Or Alive {nice}"] if c == 0 else [])})
    return out


# ---- skeleton --------------------------------------------------------------------------------------------------------
def game_matrix(m) -> np.ndarray:
    """((9 s16 4.12 row-major), (3 s32)) -> 4x4 game-space matrix (column vectors)."""
    rot, t = m
    G = np.eye(4)
    G[:3, :3] = np.array(rot, float).reshape(3, 3) / 4096.0
    G[:3, 3] = t
    return G


def to_gltf(G: np.ndarray, scale: float = SCALE, orthonormal: bool = True) -> np.ndarray:
    W = np.eye(4)
    R = FLIP @ G[:3, :3] @ FLIP
    if orthonormal:
        u, _, vt = np.linalg.svd(R)
        R = u @ vt
    W[:3, :3] = R
    W[:3, 3] = FLIP @ G[:3, 3] * scale
    return W


def chains(ram: bytes, fighter_id: int, costume: int) -> list[tuple[int, int]]:
    """Accessory chains of a costume from the game's table: [(links, anchor bone)], bones 15.. in this order."""
    o = (CHAIN_TABLE & 0x1FFFFF) + 4 * (fighter_id * 17 + costume)
    p = struct.unpack_from("<I", ram, o)[0]
    if not p:
        return []
    q = struct.unpack_from("<I", ram, p & 0x1FFFFF)[0] & 0x1FFFFF
    out = []
    while ram[q] and len(out) < 16:
        out.append((ram[q], ram[q + 1]))
        q += 10
    return out


def skeleton(pose: list, used: set[int], chain_defs: list[tuple[int, int]]) -> list[dict]:
    """Joints for the body bones plus every used accessory bone. Chain links hang off their anchor / previous link
    (the game's chain table); other accessory bones (secondary motion the game attaches separately) hang off the body
    bone nearest to them at the bind pose. world = the game's bind matrix."""
    joints = [{"bone": b, "name": n, "parent_bone": p, "role": r} for b, n, p, r in BODY]
    parent_of, b = {}, BODY_BONES
    for links, anchor in chain_defs:
        for k in range(links):
            parent_of[b] = anchor if k == 0 else b - 1
            b += 1
    for bone in sorted(x for x in used if x >= BODY_BONES):
        G = game_matrix(pose[bone])
        if not np.any(G[:3, :3]):
            raise ReaderError(f"accessory bone {bone} is used by the mesh but the game left it unset")
        par = parent_of.get(bone)
        if par is None or (par >= BODY_BONES and par not in used):
            d = [np.linalg.norm(game_matrix(pose[k])[:3, 3] - G[:3, 3]) for k in range(BODY_BONES)]
            par = int(np.argmin(d))
        joints.append({"bone": bone, "name": f"acc_{bone - BODY_BONES:02d}", "parent_bone": par, "role": None})
    index = {j["bone"]: i for i, j in enumerate(joints)}
    for j in joints:
        j["parent"] = index.get(j["parent_bone"], -1) if j["parent_bone"] is not None else -1
    order, done = [], set()
    while len(order) < len(joints):                        # parents before children
        for i, j in enumerate(joints):
            if i not in done and (j["parent"] < 0 or j["parent"] in done):
                order.append(i)
                done.add(i)
    remap = {old: new for new, old in enumerate(order)}
    out = []
    for old in order:
        j = dict(joints[old])
        j["parent"] = remap[j["parent"]] if j["parent"] >= 0 else -1
        out.append(j)
    return out


def local_matrices(joints: list[dict], pose: list) -> list[np.ndarray]:
    W = [to_gltf(game_matrix(pose[j["bone"]])) for j in joints]
    return [W[i] if j["parent"] < 0 else np.linalg.inv(W[j["parent"]]) @ W[i] for i, j in enumerate(joints)], W


# ---- mesh ------------------------------------------------------------------------------------------------------------
def assemble(sections: dict[int, bytes], model: bytes, pose: list, hand_shapes: dict[int, int],
             chain_defs: list[tuple[int, int]]) -> dict:
    """Expanded sections + the model file (TIMs) + bind pose -> {joints, prims, textures, roles, report}."""
    counts, starts = sections.get(1, b""), sections.get(2, b"")
    tims = M.tims(model)
    vram, _ = M.vram(model)
    world = [game_matrix(m) for m in pose]
    tris = []                    # (bone per corner, game positions 3x3, normals game 3x3 or None, uv 3x2, material key)
    report = {"slots": {}, "untextured_prims": 0, "inexact_texture": 0, "skipped": []}
    used = set()
    for slot in range(M.MESH_SLOTS):
        sec = sections.get(3 + slot)
        if sec is None:
            continue
        mesh = M.parse_mesh(sec)
        V = np.array(mesh["vertices"], float)
        bs = M.batches(counts, starts, slot, len(V), len(mesh["groups"]))
        bone_of = np.full(len(V), -1)
        part_bone = {}
        for b in bs:
            bone_of[b["first"]:b["first"] + b["count"]] = -2 if b["bone"] is None else b["bone"]
            part_bone[b["part"]] = b["bone"]
        if (bone_of == -1).any():
            raise ReaderError(f"slot {slot}: {int((bone_of == -1).sum())} vertices outside every batch")
        drawn = [g for g in range(len(mesh["groups"]))]
        if slot in hand_shapes:                            # one of the three hand shapes is drawn
            drawn = [hand_shapes[slot]]
        skipped_parts = []
        if slot == 7:                                      # accessory parts whose bone the game did not set
            for g in list(drawn):
                bone = part_bone.get(g)
                if bone is None or not np.any(world[bone][:3, :3]):
                    drawn.remove(g)
                    skipped_parts.append(g)
        pos = np.einsum("nij,nj->ni", np.array([world[max(b, 0)][:3, :3] for b in bone_of]), V) + \
            np.array([world[max(b, 0)][:3, 3] for b in bone_of])
        n_tri = 0
        for g in drawn:
            for co in mesh["groups"][g]:
                for pr in M.primitives(sec, co):
                    if pr["verts"] is None:
                        continue
                    if any(bone_of[v] < 0 for v in pr["verts"]):
                        raise ReaderError(f"slot {slot}: primitive at {pr['offset']:#x} uses a vertex without a bone")
                    src = textures_key(pr, tims, report)
                    nrm = pr["normals"]
                    for t in M.corner_triangles(len(pr["uv"])):
                        vs = [pr["verts"][c] for c in t]
                        bones = [int(bone_of[v]) for v in vs]
                        used.update(bones)
                        if len(nrm) == len(pr["uv"]):
                            nn = [world[bones[k]][:3, :3] @ np.array(nrm[c], float) for k, c in enumerate(t)]
                        elif len(nrm) == 1:
                            nn = [world[bones[k]][:3, :3] @ np.array(nrm[0], float) for k in range(3)]
                        else:
                            nn = None
                        tris.append({"bones": bones, "pos": pos[vs], "nrm": nn, "uv": [pr["uv"][c] for c in t],
                                     "mat": src, "seam": pr["kind"] == M.SEAM_KIND, "slot": slot})
                        n_tri += 1
        report["slots"][slot] = {"vertices": len(V), "groups": len(mesh["groups"]), "drawn": drawn,
                                 "skipped": skipped_parts, "triangles": n_tri}
    if 12 in sections:
        report["skipped"].append("section 12 (effect quads with inline vertices, drawn only on a player flag)")
    joints = skeleton(pose, used, chain_defs)
    # textures: one cropped page per (tpage, clut, double-sided)
    mats = {}
    for t in tris:
        mats.setdefault(t["mat"], []).append(t)
    textures = []
    for key, ts in mats.items():
        tp, clut, two = key
        page = M.texture_page(vram, M.tpage_fields(tp), clut)
        uv = np.array([c for t in ts for c in t["uv"]])
        x0, y0 = uv.min(0)
        x1, y1 = uv.max(0) + 1
        crop = page[y0:y1, x0:x1]
        textures.append({"key": key, "rgba": crop, "origin": (int(x0), int(y0)), "size": (int(x1 - x0), int(y1 - y0)),
                         "mask": bool((crop[..., 3] == 0).any()), "double_sided": two})
    ys = np.concatenate([t["pos"][:, 1] for t in tris])
    seam = [max(np.linalg.norm(t["pos"][i] - t["pos"][(i + 1) % 3]) for i in range(3)) for t in tris if t["seam"]]
    report.update(triangles=len(tris), seam_triangles=len(seam), seam_max_edge=round(float(max(seam, default=0)), 1),
                  ground=round(float(ys.max()), 1), height=round(float(ys.max() - ys.min()), 1),
                  joints=len(joints), textures=len(textures))
    report["verified"] = (report["seam_max_edge"] <= SEAM_LIMIT and abs(report["ground"]) <= GROUND
                          and HEIGHT[0] <= report["height"] <= HEIGHT[1] and report["untextured_prims"] == 0
                          and len(seam) > 0)
    roles = {j["role"]: j["name"] for j in joints if j["role"]}
    return {"joints": joints, "tris": tris, "textures": textures, "roles": roles, "report": report, "pose": pose}


def textures_key(pr: dict, tims: list[dict], report: dict):
    """Material key (tpage raw, clut xy, double-sided); checks that the texels and palette are the model's own."""
    tp = pr["tpage"]
    x0, y0, x1, y1 = M.texture_rect(pr)
    cx, cy = pr["clut"]

    def texels(t):
        im = t["image"]
        return t["bpp"] == tp["bpp"] and im["x"] <= x0 and x1 < im["x"] + im["w"] and im["y"] <= y0 and y1 < im["y"] + im["h"]

    def palette(t):
        c = t["clut"]
        return c is not None and c["x"] <= cx and cx + (1 << tp["bpp"]) <= c["x"] + c["w"] and c["y"] <= cy < c["y"] + c["h"]
    if not any(texels(t) and palette(t) for t in tims):
        if any(texels(t) for t in tims) or any(palette(t) for t in tims):
            report["inexact_texture"] += 1      # texels spill past their TIM (Lei Fang costume 3 hands: 4 triangles)
        else:
            report["untextured_prims"] += 1
    return tp["raw"], pr["clut"], bool(pr["double_sided"])


# ---- GLB -------------------------------------------------------------------------------------------------------------
def _png(rgba: np.ndarray) -> bytes:
    h, w = rgba.shape[:2]
    raw = b"".join(b"\0" + rgba[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _quat(R: np.ndarray) -> list[float]:
    tr = np.trace(R)
    if tr > 0:
        k = np.sqrt(tr + 1.0) * 2
        q = [(R[2, 1] - R[1, 2]) / k, (R[0, 2] - R[2, 0]) / k, (R[1, 0] - R[0, 1]) / k, 0.25 * k]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        k = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [0.25 * k, (R[0, 1] + R[1, 0]) / k, (R[0, 2] + R[2, 0]) / k, (R[2, 1] - R[1, 2]) / k]
    elif R[1, 1] > R[2, 2]:
        k = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 1] + R[1, 0]) / k, 0.25 * k, (R[1, 2] + R[2, 1]) / k, (R[0, 2] - R[2, 0]) / k]
    else:
        k = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[0, 2] + R[2, 0]) / k, (R[1, 2] + R[2, 1]) / k, 0.25 * k, (R[1, 0] - R[0, 1]) / k]
    q = np.array(q)
    return (q / np.linalg.norm(q)).tolist()


def write_glb(path, a: dict, name: str, clips: dict | None = None, extras: dict | None = None) -> Path:
    """Assembled fighter -> skinned GLB: joint nodes (TRS from the bind matrices), one joint per vertex, one material
    per texture page; clips = {name: [pose per frame]} -> animations at 60 fps."""
    bin_, views, accs = bytearray(), [], []

    def view(data: bytes, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), **({"target": target} if target else {})})
        bin_.extend(data)
        return len(views) - 1

    def acc(arr, typ, ctype=5126, target=34962, minmax=False):
        arr = np.ascontiguousarray(arr)
        x = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            x["min"], x["max"] = arr.reshape(len(arr), -1).min(0).tolist(), arr.reshape(len(arr), -1).max(0).tolist()
        accs.append(x)
        return len(accs) - 1

    J = a["joints"]
    local, world = local_matrices(J, a["pose"])
    nodes = []
    for j, L in zip(J, local):
        nodes.append({"name": j["name"], "translation": L[:3, 3].tolist(), "rotation": _quat(L[:3, :3])})
    for i, j in enumerate(J):
        if j["parent"] >= 0:
            nodes[j["parent"]].setdefault("children", []).append(i)
    roots = [i for i, j in enumerate(J) if j["parent"] < 0]
    joint_of = {j["bone"]: i for i, j in enumerate(J)}
    images, textures, materials, prims = [], [], [], []
    for k, tex in enumerate(a["textures"]):
        images.append({"bufferView": view(_png(tex["rgba"])), "mimeType": "image/png", "name": f"{name}_tex{k}"})
        textures.append({"source": k, "sampler": 0})
        m = {"name": f"{name}_mat{k}", "pbrMetallicRoughness": {"baseColorTexture": {"index": k}, "metallicFactor": 0.0,
                                                                 "roughnessFactor": 0.9},
             "doubleSided": tex["double_sided"]}
        if tex["mask"]:
            m.update(alphaMode="MASK", alphaCutoff=0.5)
        materials.append(m)
        ts = [t for t in a["tris"] if t["mat"] == tex["key"]]
        P = np.array([to_gltf_points(t["pos"]) for t in ts], np.float32).reshape(-1, 3)
        N = []
        for t in ts:
            if t["nrm"] is None:
                n = np.cross(t["pos"][1] - t["pos"][0], t["pos"][2] - t["pos"][0])
                nn = [n] * 3
            else:
                nn = t["nrm"]
            for n in nn:
                n = FLIP @ np.asarray(n, float)
                N.append(n / (np.linalg.norm(n) or 1))
        ox, oy = tex["origin"]
        w, h = tex["size"]
        UV = np.array([((u - ox) / w, (v - oy) / h) for t in ts for u, v in t["uv"]], np.float32)
        JN = np.zeros((len(P), 4), np.uint16)
        JN[:, 0] = [joint_of[b] for t in ts for b in t["bones"]]
        WT = np.zeros((len(P), 4), np.float32)
        WT[:, 0] = 1
        prims.append({"attributes": {"POSITION": acc(P, "VEC3", minmax=True), "NORMAL": acc(np.array(N, np.float32), "VEC3"),
                                     "TEXCOORD_0": acc(UV, "VEC2"), "JOINTS_0": acc(JN, "VEC4", 5123),
                                     "WEIGHTS_0": acc(WT, "VEC4")},
                      "indices": acc(np.arange(len(P), dtype=np.uint32), "SCALAR", 5125, 34963), "material": k})
    ibm = np.array([np.linalg.inv(W).T.reshape(16) for W in world], np.float32)   # column-major
    skin = {"name": f"{name}_rig", "joints": list(range(len(J))), "skeleton": roots[0],
            "inverseBindMatrices": acc(ibm, "MAT4", target=None)}
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox.doapp_chars", **({"extras": extras} if extras else {})},
          "scene": 0, "scenes": [{"name": name, "nodes": roots + [len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": name, "primitives": prims}], "skins": [skin], "materials": materials,
          "images": images, "textures": textures,
          "samplers": [{"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}],
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": 0}]}
    anims = []
    for cname, frames in (clips or {}).items():
        times = acc(np.arange(len(frames), dtype=np.float32) / 60.0, "SCALAR", target=None, minmax=True)
        samplers, channels = [], []
        per = [local_matrices(J, f)[0] for f in frames]
        for i in range(len(J)):
            T = np.array([L[i][:3, 3] for L in per], np.float32)
            Q = np.array([_quat(L[i][:3, :3]) for L in per], np.float32)
            for k in range(1, len(Q)):                         # keep quaternions on one hemisphere for slerp
                if float(Q[k] @ Q[k - 1]) < 0:
                    Q[k] = -Q[k]
            samplers.append({"input": times, "output": acc(T, "VEC3", target=None), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": i, "path": "translation"}})
            samplers.append({"input": times, "output": acc(Q, "VEC4", target=None), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": i, "path": "rotation"}})
        anims.append({"name": cname, "samplers": samplers, "channels": channels})
    if anims:
        gl["animations"] = anims
    while len(bin_) % 4:
        bin_.append(0)
    gl["buffers"][0]["byteLength"] = len(bin_)
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


def to_gltf_points(p: np.ndarray, scale: float = SCALE) -> np.ndarray:
    return (np.asarray(p, float) @ FLIP.T) * scale


# ---- extraction -----------------------------------------------------------------------------------------------------
def extract(program_ram: bytes, banked: bytes, fighter: dict, costume: int, out: Path,
            clips: dict[str, int] | None = None, rig=None) -> dict:
    """One fighter costume -> GLB + verification report. clips: {name: motion index} (default: the stance loop)."""
    rig = rig or DM.Rig(program_ram, banked, fighter, costume)
    pose = rig.rest_pose()
    a = assemble(rig.sections(), rig.model, pose, rig.hand_shapes(), chains(program_ram, fighter["id"], costume))
    clip_poses = {n: rig.clip(m) for n, m in (CLIPS if clips is None else clips).items()}
    name = Path(out).stem
    glb = write_glb(out, a, name, clip_poses, extras={
        "source": "Dead Or Alive ++ (MAME doapp), data ROMs doapp-0..5, program decoded by the TPS BIOS",
        "fighter": fighter["name"], "costume": costume, "model_file": fighter["models"][costume],
        "motion_file": fighter["motion"], "bind_pose": "frame 0 of motion 0 (stance loop), game matrices 0x8011ca60",
        "units": f"metres (game units x {SCALE})", "clips": {n: m for n, m in (CLIPS if clips is None else clips).items()}})
    r = dict(a["report"])
    r.update(glb=str(glb), roles=a["roles"], fighter=fighter["name"], costume=costume,
             model_file=fighter["models"][costume],
             model_sha256=hashlib.sha256(rig.model).hexdigest())
    return r


def _program(ctx, src_dir: Path) -> tuple[bytes, bytes]:
    """(decoded program RAM, bankedroms) for the owned zips, the ~40 s decode cached per program-ROM hash."""
    import zipfile
    parent = src_dir / "doapp.zip"
    with zipfile.ZipFile(parent) as z:
        key = hashlib.sha1(z.read("doapp119.bin") + z.read("doapp120.bin")).hexdigest()[:16]
    cache = Path(getattr(getattr(ctx, "config", None), "cache", "") or Path.home() / "gbox-cache") / "doapp" / f"{key}.ram"
    banked = D.merge_parent(str(parent))
    if cache.is_file() and cache.stat().st_size == 0x200000:
        return cache.read_bytes(), banked
    _, ram, _ = D.decode_owned(str(src_dir))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(ram)
    return ram, banked


def source_dir(ctx, game: dict) -> Path:
    from . import characters as C
    rom = Path(C._rom(ctx, game))
    d = rom if rom.is_dir() else rom.parent
    if not (d / "doapp.zip").is_file() or not (d / "coh1002m.zip").is_file():
        raise ReaderError(f"{d}: needs doapp.zip (the parent set: data ROMs) and coh1002m.zip (TPS BIOS) side by side")
    return d


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED hook: one fighter costume -> verified rigged, textured GLB with body roles."""
    d = source_dir(ctx, game)
    ram, banked = _program(ctx, d)
    f = next(x for x in D.FIGHTERS if x["id"] == e["fighter"])
    r = extract(ram, banked, f, e["costume"], Path(work) / f"{e['slug']}.glb")
    if not r["verified"]:
        raise ReaderError(f"{e['key']}: failed verification: {json.dumps({k: r[k] for k in ('seam_max_edge', 'ground', 'height', 'untextured_prims')})}")
    return {"files": [Path(r["glb"])], "roles": r["roles"], "tool": "gbox.doapp_chars",
            "source_files": [f"doapp.zip#file{f['models'][e['costume']]} (model, sha256 {r['model_sha256'][:16]})",
                             f"doapp.zip#file{f['motion']} (motion bank)", f"doapp.zip#file{f['small_a']} (fighter data)",
                             "coh1002m.zip (TPS BIOS, program decode)"],
            "notes": (f"Native DOA++ arcade model: {r['joints']} joints (15 body + accessory chains), rigid one-joint "
                      f"skinning, {r['triangles']} triangles, {r['textures']} texture pages. Bind pose = the game's own "
                      "bone matrices for frame 0 of the stance loop (motion player + skeleton build run on the decoded "
                      "program); 'stance' clip included.")}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m gbox.doapp_chars", description="DOA++ fighters -> rigged GLBs")
    ap.add_argument("src", help="directory with doapp.zip + coh1002m.zip")
    ap.add_argument("out", help="output directory")
    ap.add_argument("fighters", nargs="*", help="fighter names / ids (default: all 11)")
    ap.add_argument("--costumes", default="0,1,2,3")
    ap.add_argument("--clips", default="stance=0", help="name=motion,... ('' for none)")
    a = ap.parse_args(argv)
    ram, banked = _program(None, Path(a.src))
    fs = [D.fighter(x) for x in a.fighters] if a.fighters else list(D.FIGHTERS)
    clips = dict((kv.split("=")[0], int(kv.split("=")[1])) for kv in a.clips.split(",") if kv)
    rows = []
    for f in fs:
        for c in (int(x) for x in a.costumes.split(",")):
            slug = f"doapp_{f['name'].lower().replace(' ', '_')}_{c + 1}"
            r = extract(ram, banked, f, c, Path(a.out) / f"{slug}.glb", clips)
            rows.append({k: r[k] for k in ("fighter", "costume", "verified", "triangles", "joints", "textures",
                                           "seam_max_edge", "ground", "height", "inexact_texture", "glb")})
            print(json.dumps(rows[-1]), flush=True)
    return 0 if all(r["verified"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
