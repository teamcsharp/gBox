"""Body roles for characters made outside gBox (Blender "Send to gBox"): recognise the common rigs by their bone names,
or rig an unrigged mesh with a simple humanoid heuristic, so the model becomes a first-class donor every writer can fit.

detect(model) -> {"rig": "mixamo" | "rigify" | "vrm" | "ue_mannequin" | "biped" | "blender" | "tree" | None,
                  "roles": {role: joint name}, "matched", "of", "missing"}
  Roles are the 18 of gbox.retarget_profile.ROLES (hip, chest, neck, head, clavicles, upper / fore / hand, thigh /
  shin / foot per side; l_ = the character's own left). Order of evidence: the VRM humanoid extension (VRoid exports,
  VRM 0.x and 1.0), then bone-name presets, then gbox.characters.tree_roles (joint tree + rest positions) for rigs
  with other names. A preset counts when it maps the hip, the head and at least 10 roles.

auto_rig(src, dst) -> {"rig": "auto", "roles", "pose", ...}
  An unskinned model (+Y up, facing +Z, its left on +X: what Blender's glTF export writes) gets an 18-joint humanoid
  skeleton placed from its own shape (height, where the arms reach: T / A pose, where the legs stand) and a rigid
  skin (every vertex on its nearest bone, left / right never mixed). The joints are named after their roles, so the
  roles map is the identity. Good enough for the rigid-per-limb writers; a model that needs real weights should be
  rigged in Blender (Rigify / Mixamo) and sent again.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from . import attachments
from .retarget_profile import ROLES

SIDES = {"l": ("left", "l", "L"), "r": ("right", "r", "R")}

# preset -> {role: [candidate names after normalize()]}; {S} = side word of that preset, first match wins
PRESETS = {
    "mixamo": {"hip": ["hips"], "chest": ["spine2", "spine1", "spine"], "neck": ["neck"], "head": ["head"],
               "{s}_clav": ["{S}shoulder"], "{s}_upper": ["{S}arm"], "{s}_fore": ["{S}forearm"], "{s}_hand": ["{S}hand"],
               "{s}_thigh": ["{S}upleg"], "{s}_shin": ["{S}leg"], "{s}_foot": ["{S}foot"]},
    "rigify": {"hip": ["def-spine", "def-hips"], "chest": ["def-spine.003", "def-spine.002", "def-chest"],
               "neck": ["def-spine.004", "def-neck"], "head": ["def-spine.006", "def-spine.005", "def-head"],
               "{s}_clav": ["def-shoulder.{S}"], "{s}_upper": ["def-upper_arm.{S}"], "{s}_fore": ["def-forearm.{S}"],
               "{s}_hand": ["def-hand.{S}"], "{s}_thigh": ["def-thigh.{S}"], "{s}_shin": ["def-shin.{S}"],
               "{s}_foot": ["def-foot.{S}"]},
    "blender": {"hip": ["spine", "hips", "pelvis"], "chest": ["spine.003", "spine.002", "chest"], "neck": ["spine.004", "neck"],
                "head": ["spine.006", "spine.005", "head"], "{s}_clav": ["shoulder.{S}"], "{s}_upper": ["upper_arm.{S}"],
                "{s}_fore": ["forearm.{S}"], "{s}_hand": ["hand.{S}"], "{s}_thigh": ["thigh.{S}"], "{s}_shin": ["shin.{S}"],
                "{s}_foot": ["foot.{S}"]},
    "vrm": {"hip": ["j_bip_c_hips"], "chest": ["j_bip_c_upperchest", "j_bip_c_chest", "j_bip_c_spine"],
            "neck": ["j_bip_c_neck"], "head": ["j_bip_c_head"], "{s}_clav": ["j_bip_{S}_shoulder"],
            "{s}_upper": ["j_bip_{S}_upperarm"], "{s}_fore": ["j_bip_{S}_lowerarm"], "{s}_hand": ["j_bip_{S}_hand"],
            "{s}_thigh": ["j_bip_{S}_upperleg"], "{s}_shin": ["j_bip_{S}_lowerleg"], "{s}_foot": ["j_bip_{S}_foot"]},
    "ue_mannequin": {"hip": ["pelvis"], "chest": ["spine_05", "spine_04", "spine_03", "spine_02"], "neck": ["neck_01", "neck_02"],
                     "head": ["head"], "{s}_clav": ["clavicle_{S}"], "{s}_upper": ["upperarm_{S}"], "{s}_fore": ["lowerarm_{S}"],
                     "{s}_hand": ["hand_{S}"], "{s}_thigh": ["thigh_{S}"], "{s}_shin": ["calf_{S}"], "{s}_foot": ["foot_{S}"]},
    "biped": {"hip": ["pelvis"], "chest": ["spine2", "spine1", "spine"], "neck": ["neck"], "head": ["head"],
              "{s}_clav": ["{S} clavicle"], "{s}_upper": ["{S} upperarm"], "{s}_fore": ["{S} forearm"], "{s}_hand": ["{S} hand"],
              "{s}_thigh": ["{S} thigh"], "{s}_shin": ["{S} calf"], "{s}_foot": ["{S} foot"]},
}
SIDE_WORD = {"mixamo": {"l": "left", "r": "right"}, "rigify": {"l": "l", "r": "r"}, "blender": {"l": "l", "r": "r"},
             "vrm": {"l": "l", "r": "r"}, "ue_mannequin": {"l": "l", "r": "r"}, "biped": {"l": "l", "r": "r"}}
PREFIX = {"mixamo": re.compile(r"^mixamorig\d*[:_]?"), "biped": re.compile(r"^bip0*1[ _]")}

# VRM humanoid bone -> role (VRM 0.x humanBones list, VRM 1.0 humanBones dict)
VRM_BONES = {"hips": "hip", "neck": "neck", "head": "head", "leftShoulder": "l_clav", "rightShoulder": "r_clav",
             "leftUpperArm": "l_upper", "leftLowerArm": "l_fore", "leftHand": "l_hand", "rightUpperArm": "r_upper",
             "rightLowerArm": "r_fore", "rightHand": "r_hand", "leftUpperLeg": "l_thigh", "leftLowerLeg": "l_shin",
             "leftFoot": "l_foot", "rightUpperLeg": "r_thigh", "rightLowerLeg": "r_shin", "rightFoot": "r_foot"}
VRM_CHEST = ("upperChest", "chest", "spine")


def normalize(preset: str, name: str) -> str:
    n = name.strip().lower()
    rx = PREFIX.get(preset)
    return rx.sub("", n) if rx else n


def expand(preset: str) -> dict[str, list[str]]:
    out = {}
    for role, cands in PRESETS[preset].items():
        if "{s}" in role:
            for s in ("l", "r"):
                w = SIDE_WORD[preset][s]
                out[role.replace("{s}", s)] = [c.replace("{S}", w) for c in cands]
        else:
            out[role] = list(cands)
    return out


def from_names(names: list[str]) -> list[dict]:
    """Every preset's mapping of these joint names, best first."""
    res = []
    for preset in PRESETS:
        norm = {}
        for n in names:
            norm.setdefault(normalize(preset, n), n)
        roles = {}
        for role, cands in expand(preset).items():
            hit = next((norm[c] for c in cands if c in norm), None)
            if hit and hit not in roles.values():
                roles[role] = hit
        res.append({"rig": preset, "roles": roles})
    return sorted(res, key=lambda r: -len(r["roles"]))


def from_vrm(gl: dict) -> dict:
    """The VRM humanoid extension (authoritative when present) -> {role: node name}."""
    ext = gl.get("extensions") or {}
    hb: dict[str, int] = {}
    if isinstance(ext.get("VRMC_vrm"), dict):                       # VRM 1.0
        for b, v in ((ext["VRMC_vrm"].get("humanoid") or {}).get("humanBones") or {}).items():
            if isinstance(v, dict) and isinstance(v.get("node"), int):
                hb[b] = v["node"]
    elif isinstance(ext.get("VRM"), dict):                          # VRM 0.x
        for v in (ext["VRM"].get("humanoid") or {}).get("humanBones") or []:
            if isinstance(v, dict) and isinstance(v.get("node"), int) and v.get("bone"):
                hb[v["bone"]] = v["node"]
    nodes = gl.get("nodes") or []
    name = lambda i: nodes[i].get("name", f"node{i}") if 0 <= i < len(nodes) else None   # noqa: E731
    roles = {r: name(hb[b]) for b, r in VRM_BONES.items() if b in hb and name(hb[b])}
    ch = next((hb[b] for b in VRM_CHEST if b in hb), None)
    if ch is not None and name(ch):
        roles["chest"] = name(ch)
    return roles


def skin_joint_names(gl: dict) -> list[str]:
    seen, out = set(), []
    for s in gl.get("skins") or []:
        for j in s.get("joints") or []:
            if j not in seen:
                seen.add(j)
                out.append(gl["nodes"][j].get("name", f"node{j}"))
    return out


def usable(roles: dict) -> bool:
    return {"hip", "head"} <= roles.keys() and len(roles) >= 10


def detect(model: Path) -> dict:
    gl, _ = attachments.read_gltf(model)
    names = skin_joint_names(gl)
    base = {"of": len(ROLES), "joints": len(names)}
    if not names:
        return base | {"rig": None, "roles": {}, "matched": 0, "missing": list(ROLES), "why": "no skin (unrigged)"}
    vrm = {r: n for r, n in from_vrm(gl).items() if n in names}
    if usable(vrm):
        return base | {"rig": "vrm", "roles": vrm, "matched": len(vrm), "missing": [r for r in ROLES if r not in vrm],
                       "evidence": "VRM humanoid extension"}
    best = from_names(names)[0]
    if usable(best["roles"]):
        return base | best | {"matched": len(best["roles"]), "missing": [r for r in ROLES if r not in best["roles"]],
                              "evidence": "bone names"}
    why = ""
    try:
        from .characters import tree_roles
        tr = tree_roles(Path(model))                       # arms-down rigs (SA2's hand-picked roles reproduce)
    except Exception as e:                                  # noqa: BLE001 - not that shape: try the T-pose reading
        tr, why = {}, f"{type(e).__name__}: {e}"
    if not {"hip", "head"} <= tr.keys():
        try:
            tr = topology_roles(gl)
        except Exception as e:                              # noqa: BLE001 - not a humanoid tree
            tr, why = {}, f"{why}; {type(e).__name__}: {e}" if why else f"{type(e).__name__}: {e}"
    if {"hip", "head"} <= tr.keys():
        return base | {"rig": "tree", "roles": tr, "matched": len(tr), "missing": [r for r in ROLES if r not in tr],
                       "evidence": "joint tree + rest positions (no known bone names)"}
    return base | {"rig": None, "roles": best["roles"], "matched": len(best["roles"]),
                   "missing": [r for r in ROLES if r not in best["roles"]],
                   "why": "no known rig: name the bones in Blender (gbox_role) or pass rig_roles" + (f" ({why})" if why else "")}


def topology_roles(gl: dict) -> dict[str, str]:
    """Roles of any humanoid joint tree from its shape (+Y up, left = +X), T or A pose, fingers / toes / end bones
    allowed: feet = the lowest leaf each side, hip = their common ancestor, hands = the common ancestor of the
    outermost leaves above the hip each side (the fingers' hand), chest = where the arms meet, head / neck along the
    path to the top leaf; limb joints by position along each chain."""
    from .re4gc_models import _node_world
    W = _node_world(gl)
    sk = max(gl.get("skins") or [{"joints": []}], key=lambda s: len(s["joints"]))["joints"]
    if len(sk) < 8:
        raise ValueError("fewer than 8 joints")
    js = set(sk)
    name = {j: gl["nodes"][j].get("name", f"node{j}") for j in sk}
    pos = {j: np.asarray(W[j])[:3, 3] for j in sk}
    par = {c: i for i, n in enumerate(gl["nodes"]) for c in n.get("children", []) if c in js and i in js}
    kids = {j: [c for c in gl["nodes"][j].get("children", []) if c in js] for j in sk}

    def anc(j):
        out = [j]
        while out[-1] in par:
            out.append(par[out[-1]])
        return out

    def lca(*xs):
        common = set(anc(xs[0]))
        for x in xs[1:]:
            common &= set(anc(x))
        return next(a for a in anc(xs[0]) if a in common)

    def path(a, b):                                        # joints after a, down to b
        A = list(reversed(anc(b)))
        return A[A.index(a) + 1:] if a in A else []

    def under(a):
        return [j for j in sk if a in anc(j)]
    P = np.array([pos[j] for j in sk])
    y0, H = float(P[:, 1].min()), float(np.ptp(P[:, 1]))
    cx = float(np.median(P[:, 0]))
    leaves = [j for j in sk if not kids[j]]
    lf = min([j for j in leaves if pos[j][0] > cx + 0.02 * H], key=lambda j: pos[j][1])
    rf = min([j for j in leaves if pos[j][0] < cx - 0.02 * H], key=lambda j: pos[j][1])
    hip = lca(lf, rf)
    legs = {j for f in (lf, rf) for j in path(hip, f)}
    up = [j for j in leaves if j not in legs and pos[j][1] > pos[hip][1]]
    lh_leaf = max(up, key=lambda j: pos[j][0])
    rh_leaf = min(up, key=lambda j: pos[j][0])
    if pos[lh_leaf][0] - cx < 0.1 * H or cx - pos[rh_leaf][0] < 0.1 * H:
        raise ValueError("no arms reaching out on both sides")
    chest = lca(lh_leaf, rh_leaf)
    roles = {"hip": name[hip], "chest": name[chest]}
    top = max([j for j in up if j not in (lh_leaf, rh_leaf)], key=lambda j: pos[j][1])
    hp = path(chest, top)
    if hp:
        head = hp[-2] if len(hp) >= 3 and not kids[hp[-1]] else hp[-1]
        roles["head"] = name[head]
        if hp[0] != head:
            roles["neck"] = name[hp[0]]
    for s, leaf in (("l", lh_leaf), ("r", rh_leaf)):
        arm = path(chest, leaf)
        root = arm[0]
        tips = [j for j in under(root) if not kids[j]]
        hand = lca(*tips) if len(tips) > 1 else leaf
        chain = path(chest, hand)
        if len(chain) >= 4:
            roles[f"{s}_clav"], roles[f"{s}_upper"], roles[f"{s}_fore"] = name[chain[-4]], name[chain[-3]], name[chain[-2]]
        elif len(chain) == 3:
            roles[f"{s}_upper"], roles[f"{s}_fore"] = name[chain[0]], name[chain[1]]
        roles[f"{s}_hand"] = name[hand]
    for s, foot_leaf in (("l", lf), ("r", rf)):
        leg = path(hip, foot_leaf)
        if len(leg) < 3:
            continue
        roles[f"{s}_thigh"] = name[leg[0]]
        ankle = next((j for j in leg[1:] if pos[j][1] - y0 < 0.15 * H), leg[-1])
        roles[f"{s}_foot"] = name[ankle]
        mid = [j for j in leg[1:leg.index(ankle)]]
        if mid:
            want = (pos[leg[0]][1] + pos[ankle][1]) / 2
            roles[f"{s}_shin"] = name[min(mid, key=lambda j: abs(pos[j][1] - want))]
    return roles


# ---------------------------------------------------------------- auto rig (unskinned models)

PARENT = {"hip": None, "chest": "hip", "neck": "chest", "head": "neck", "l_clav": "chest", "r_clav": "chest",
          "l_upper": "l_clav", "l_fore": "l_upper", "l_hand": "l_fore", "r_upper": "r_clav", "r_fore": "r_upper",
          "r_hand": "r_fore", "l_thigh": "hip", "l_shin": "l_thigh", "l_foot": "l_shin", "r_thigh": "hip",
          "r_shin": "r_thigh", "r_foot": "r_shin"}
ORDER = list(PARENT)                                        # parents first


def _mesh_points(gl: dict, acc, W) -> np.ndarray:
    pts = []
    for ni, nd in enumerate(gl.get("nodes") or []):
        if "mesh" not in nd:
            continue
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            P = acc(pr["attributes"]["POSITION"]).astype(float)
            pts.append(P @ W[ni][:3, :3].T + W[ni][:3, 3])
    if not pts:
        raise ValueError("no meshes to rig")
    return np.concatenate(pts)


def place_joints(P: np.ndarray) -> tuple[dict, dict]:
    """World joint positions for a standing humanoid point cloud (+Y up, facing +Z, its left = +X)."""
    lo, hi = P.min(0), P.max(0)
    H = float(hi[1] - lo[1])
    if H <= 0:
        raise ValueError("the model is flat")
    y = lambda f: lo[1] + f * H                             # noqa: E731
    cx, cz = float(np.median(P[:, 0])), float(np.median(P[:, 2]))
    band = P[(P[:, 1] > y(0.62)) & (P[:, 1] < y(0.9))]
    left, right = band[band[:, 0] > cx], band[band[:, 0] < cx]
    reach_l = float(left[:, 0].max() - cx) if len(left) else 0.2 * H
    reach_r = float(cx - right[:, 0].min()) if len(right) else 0.2 * H
    tpose = min(reach_l, reach_r) > 0.3 * H
    legs = P[P[:, 1] < y(0.25)]
    lx = float(np.median(legs[legs[:, 0] > cx][:, 0]) - cx) if (legs[:, 0] > cx).any() else 0.08 * H
    rx = float(cx - np.median(legs[legs[:, 0] < cx][:, 0])) if (legs[:, 0] < cx).any() else 0.08 * H
    lx, rx = float(np.clip(lx, 0.04 * H, 0.2 * H)), float(np.clip(rx, 0.04 * H, 0.2 * H))
    J = {"hip": (cx, y(0.53), cz), "chest": (cx, y(0.72), cz), "neck": (cx, y(0.84), cz), "head": (cx, y(0.88), cz)}
    for s, sg, reach, lg in (("l", 1, reach_l, lx), ("r", -1, reach_r, rx)):
        sh = np.array([cx + sg * 0.1 * H, y(0.81), cz])
        J[f"{s}_clav"] = (cx + sg * 0.03 * H, y(0.81), cz)
        J[f"{s}_upper"] = tuple(sh)
        if tpose:                                           # arms out: hand near the reach, elbow half way
            hand = np.array([cx + sg * max(reach - 0.08 * H, 0.25 * H), y(0.81), cz])
        else:                                               # arms down / A pose: the farthest point of each side's arm
            side = band[(sg * (band[:, 0] - cx)) > 0.12 * H]
            tip = side[np.argmax(sg * (side[:, 0] - cx) - (side[:, 1] - y(0.81)))] if len(side) else \
                np.array([cx + sg * 0.22 * H, y(0.48), cz])
            hand = sh + 0.85 * (np.asarray(tip, float) - sh)
            if not tpose and hand[1] > y(0.7):              # only the shoulders stick out: arms hang by the sides
                hand = np.array([cx + sg * 0.2 * H, y(0.48), cz])
        J[f"{s}_fore"] = tuple(sh + 0.5 * (hand - sh))
        J[f"{s}_hand"] = tuple(hand)
        J[f"{s}_thigh"] = (cx + sg * lg, y(0.5), cz)
        J[f"{s}_shin"] = (cx + sg * lg, y(0.28), cz)
        J[f"{s}_foot"] = (cx + sg * lg, y(0.05), cz)
    tips = {"head": (cx, y(1.0), cz), "l_hand": None, "r_hand": None, "l_foot": None, "r_foot": None}
    for s, sg in (("l", 1), ("r", -1)):
        h, f = np.array(J[f"{s}_hand"]), np.array(J[f"{s}_fore"])
        tips[f"{s}_hand"] = tuple(h + 0.35 * (h - f))
        tips[f"{s}_foot"] = (J[f"{s}_foot"][0], lo[1], cz + 0.1 * H)
    return {k: np.asarray(v, float) for k, v in J.items()}, {"height": H, "pose": "T" if tpose else "A / arms down",
                                                            "tips": {k: np.asarray(v, float) for k, v in tips.items()}}


def _segments(J: dict, tips: dict) -> list[tuple[str, np.ndarray, np.ndarray]]:
    """(owner role, start, end) bone segments: each joint toward its child (or its tip), + hip -> thighs."""
    kids = {}
    for r, p in PARENT.items():
        if p:
            kids.setdefault(p, []).append(r)
    segs = []
    for r in ORDER:
        ends = [J[c] for c in kids.get(r, []) if not c.endswith(("_clav", "_thigh"))] or \
               ([tips[r]] if tips.get(r) is not None else [J[r]])
        for e in ends:
            segs.append((r, J[r], e))
    for s in ("l", "r"):
        segs.append(("hip", J["hip"], J[f"{s}_thigh"]))
        segs.append((f"{s}_clav", J[f"{s}_clav"], J[f"{s}_upper"]))
    return segs


def assign(P: np.ndarray, J: dict, tips: dict, H: float) -> np.ndarray:
    """Role index (ORDER) per point: the nearest bone segment; a point clearly on one side never takes the other side's
    limbs."""
    segs = _segments(J, tips)
    cx = J["hip"][0]
    D = np.empty((len(P), len(segs)))
    for k, (r, a, b) in enumerate(segs):
        ab = b - a
        t = np.clip(((P - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1) if float(ab @ ab) > 1e-12 else np.zeros(len(P))
        D[:, k] = np.linalg.norm(a + t[:, None] * ab - P, axis=1)
        side = r[:2]
        if side in ("l_", "r_"):
            wrong = (P[:, 0] - cx) * (1 if side == "l_" else -1) < -0.02 * H
            D[wrong, k] += 10 * H
    owner = np.array([ORDER.index(r) for r, _a, _b in segs])
    return owner[D.argmin(1)]


def auto_rig(src: Path, dst: Path) -> dict:
    """An unskinned model -> a skinned GLB with an 18-joint humanoid skeleton (joints named after their roles)."""
    from .re4gc_models import _gltf_load, _node_world
    gl0, acc, _img = _gltf_load(src)
    W = _node_world(gl0)
    if gl0.get("skins"):
        raise ValueError("the model already has a skeleton: detect() maps it")
    P = _mesh_points(gl0, acc, W)
    J, info = place_joints(P)
    H = info["height"]
    gl, blob = attachments.pack(Path(src))
    blob = bytearray(blob)

    def add(arr, comp, typ, target=None):
        arr = np.ascontiguousarray(arr)
        blob.extend(bytes(-len(blob) % 4))
        gl.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes,
                                                 **({"target": target} if target else {})})
        blob.extend(arr.tobytes())
        gl.setdefault("accessors", []).append({"bufferView": len(gl["bufferViews"]) - 1, "componentType": comp,
                                               "count": int(len(arr)), "type": typ})
        return len(gl["accessors"]) - 1
    nodes = gl.setdefault("nodes", [])
    base = len(nodes)
    idx = {r: base + k for k, r in enumerate(ORDER)}
    for r in ORDER:
        p = PARENT[r]
        t = J[r] - (J[p] if p else 0)
        nodes.append({"name": r, "translation": [float(v) for v in t], "extras": {"gbox_role": r}})
    for r in ORDER:
        if PARENT[r]:
            nodes[idx[PARENT[r]]].setdefault("children", []).append(idx[r])
    joints = [idx[r] for r in ORDER]
    jw = {r: np.eye(4) for r in ORDER}
    for r in ORDER:
        jw[r][:3, 3] = J[r]
    done_mesh, skins = set(), gl.setdefault("skins", [])
    for ni, nd in enumerate(nodes[:base]):
        if "mesh" not in nd or nd["mesh"] in done_mesh:
            continue
        done_mesh.add(nd["mesh"])
        ibm = np.array([(np.linalg.inv(jw[r]) @ W[ni]).T.reshape(16) for r in ORDER], np.float32)
        skins.append({"joints": joints, "inverseBindMatrices": add(ibm, 5126, "MAT4"), "skeleton": idx["hip"],
                      "name": "gbox_auto_rig"})
        nd["skin"] = len(skins) - 1
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            Pl = acc(pr["attributes"]["POSITION"]).astype(float)
            Pw = Pl @ W[ni][:3, :3].T + W[ni][:3, 3]
            own = assign(Pw, J, info["tips"], H)
            Jv = np.zeros((len(Pw), 4), np.uint16)
            Jv[:, 0] = own
            Wv = np.zeros((len(Pw), 4), np.float32)
            Wv[:, 0] = 1
            pr["attributes"]["JOINTS_0"] = add(Jv, 5123, "VEC4", 34962)
            pr["attributes"]["WEIGHTS_0"] = add(Wv, 5126, "VEC4", 34962)
    sc = gl.setdefault("scenes", [{"nodes": []}])[gl.get("scene", 0)]
    sc.setdefault("nodes", []).append(idx["hip"])
    Path(dst).write_bytes(attachments.glb_bytes(gl, bytes(blob)))
    return {"rig": "auto", "roles": {r: r for r in ROLES}, "pose": info["pose"], "height": round(H, 4),
            "joints": len(ORDER), "weights": "rigid (one bone per vertex)",
            "joint_positions": {r: [round(float(v), 4) for v in J[r]] for r in ORDER}}
