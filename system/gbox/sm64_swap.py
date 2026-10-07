"""Super Mario 64 (N64, USA): any character from gBox's collection in Mario's place ("replace me with Cloud").

`characters op=use` routes SM64 here. Pipeline (all from the operator's own ROM and collection, nothing downloaded):
  1. the library model + its body roles (meta rig.roles: hip/chest/neck/head, clavicles, upper/fore/hand, thigh/shin/foot)
     -> a generic rig: joint positions, parents, per-vertex owner joint (largest weight; extra skins matched by name)
  2. facing normalised (left -> +X, up -> +Y, front -> +Z, snapped to axes) and a rigid retarget onto Mario's 20 joints in
     his standing idle pose (anim 197), the rules of scripts/retarget_rigid.py / re4gc_enemies.retarget made automatic:
     torso on Mario's pelvis (uniform scale = head joint to ground fitted to Mario's, vertical fit above / below the hip,
     widened toward Mario's shoulders), head on j03 (scaled about its base, enlarged toward Mario's big head), limbs
     rotated onto Mario's segments from the torso's shoulder / hip and stretched (clamped), hands / feet riding the
     forearm / shin rotation on Mario's wrist / ankle. Every vertex follows its owner joint's nearest ancestor with a role.
     Mario's joint count and order never change (the writer only swaps display lists), so all his animations play.
  3. the Mario-rigged model as a glTF (library <slug>/targets/sm64_mario.gltf + sm64_preview.png); Blender edge-collapse
     decimate when it has more than MAX_TRIS triangles
  4. joint-local triangles + materials fitted into the 0x1CD20 bytes of Mario's own segment-04 data (gbox.sm64_writer):
     textures RGBA16 <= 64x32 (transparent texels filled), then smaller, then the least used ones become plain colours,
     then fewer triangles
  5. gbox.sm64_writer.inject into a copy of the ROM -> file mod cache/mods/<game_id>/sm64_<slug> (launch_game mod=...)

  python -m gbox.sm64_swap build <rom.z64|.zip> <character dir (with meta.json)> <out dir> [--max-tris N]
"""
from __future__ import annotations

import json
import re
import shutil
import time
import zipfile
from pathlib import Path

import numpy as np

from . import sm64_mario as sm
from . import sm64_writer as W

# Both catalog entries hold the same ROM (NSMP, md5 45676429...: the "(USA)" zip is really the European ROM); the
# offsets in gbox.sm64_mario / sm64_writer are this ROM's, and check_rom() refuses any other layout.
GAME_IDS = {W.GAME_ID: "Super Mario 64 (USA)", "66062703301f4969": "Super Mario 64 (Europe) (En,Fr,De)"}
ANIM = 197                                              # standing idle: the pose the model is fitted in
MARIO = {"hip": 1, "chest": 2, "head": 3, "l_upper": 5, "l_fore": 6, "l_hand": 7, "r_upper": 9, "r_fore": 10,
         "r_hand": 11, "l_thigh": 13, "l_shin": 14, "l_foot": 15, "r_thigh": 17, "r_shin": 18, "r_foot": 19}
ORDER = ["hip", "chest", "neck", "head", "l_clav", "r_clav", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore",
         "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"]   # a joint keeps its first role
LIMBS = [("l_upper", "l_fore", "l_hand"), ("r_upper", "r_fore", "r_hand"),
         ("l_thigh", "l_shin", "l_foot"), ("r_thigh", "r_shin", "r_foot")]
MAX_TRIS = 1600
PROP_MAX_TRIS = 400                                     # a prop (hat, sword) keeps its triangles up to this, else decimated


def rom_bytes(path) -> bytes:
    """.z64 / .v64 / .n64, or a .zip holding one -> big-endian .z64 bytes."""
    p = Path(path)
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            data = z.read(next(n for n in z.namelist() if n.lower().endswith((".z64", ".n64", ".v64"))))
    else:
        data = p.read_bytes()
    if data[:4] == b"\x37\x80\x40\x12":
        data = np.frombuffer(data, ">u2").astype("<u2").tobytes()
    elif data[:4] == b"\x40\x12\x37\x80":
        data = np.frombuffer(data, ">u4").astype("<u4").tobytes()
    return data


def check_rom(rom: bytes) -> None:
    """The writer patches fixed offsets: the ROM must have Mario's MIO0 block and the level-script load where they are."""
    import struct
    cmd, _ln, seg, start, end = struct.unpack_from(">BBHII", rom, sm.LOAD_SEG04)
    if rom[:4] != b"\x80\x37\x12\x40" or rom[sm.SEG04[0]:sm.SEG04[0] + 4] != b"MIO0" or \
            (cmd, seg, start, end) != (0x18, 4, sm.SEG04[0], sm.SEG04[1]):
        raise ValueError(f"this SM64 ROM ({rom[0x3B:0x3F].decode(errors='replace')}) doesn't have the layout gbox.sm64_writer "
                         "knows (Mario's data at 0x0F5330, level-script load at 0x28CEE0)")


# ---------------------------------------------------------------- source rig

def load_rig(path: Path, roles: dict[str, str], props=()) -> dict:
    """A skinned glTF + {role: joint name} -> {joints (J,3), parent, roles {role: index}, prims [{pos, nrm, uv, tris,
    owner, tex, color, prop}]}, every vertex in the pose its joint nodes are in (skin applied with the strongest joint).
    props: node names of extra meshes (a hat bound to the head bone): rigid on their nearest joint ancestor, flagged so
    the fit ignores them (head size, ground) and the budget keeps them whole when it can."""
    props = set(props or ())
    from .re4gc_models import _gltf_load, _node_world
    gl, acc, image = _gltf_load(path)
    Wn = _node_world(gl)
    skins = gl.get("skins") or []
    if not skins:
        raise ValueError(f"{Path(path).name} has no skeleton (skin): can't put it on Mario's joints")
    main = max(skins, key=lambda s: len(s["joints"]))
    jn = list(main["joints"])
    names = [gl["nodes"][j].get("name", f"node{j}") for j in jn]
    pos_of = {j: k for k, j in enumerate(jn)}
    by_name = {n: k for k, n in reversed(list(enumerate(names)))}
    par_node = {c: i for i, nd in enumerate(gl["nodes"]) for c in nd.get("children", [])}
    parent = []
    for j in jn:
        p = par_node.get(j)
        while p is not None and p not in pos_of:
            p = par_node.get(p)
        parent.append(pos_of[p] if p is not None else -1)
    ri = {}
    for r in ORDER:
        k = by_name.get(roles.get(r))
        if k is not None and k not in ri.values():
            ri[r] = k

    def to_main(n):                                       # a node -> its joint in the main skin (by node, name, ancestor)
        while n is not None:
            if n in pos_of:
                return pos_of[n]
            k = by_name.get(gl["nodes"][n].get("name"))
            if k is not None:
                return k
            n = par_node.get(n)
        return ri.get("hip", 0)
    texcache, prims = {}, []
    for ni, nd in enumerate(gl["nodes"]):
        if "mesh" not in nd:
            continue
        sk = gl["skins"][nd["skin"]] if "skin" in nd else None
        if sk:
            ibm = (acc(sk["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1) if "inverseBindMatrices" in sk
                   else np.tile(np.eye(4), (len(sk["joints"]), 1, 1)))
            skm = np.array([Wn[j] @ ibm[k] for k, j in enumerate(sk["joints"])])
            loc = np.array([to_main(j) for j in sk["joints"]])
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            if pr.get("mode", 4) != 4:
                continue
            a = pr["attributes"]
            P = acc(a["POSITION"]).astype(float)
            N = acc(a["NORMAL"]).astype(float) if "NORMAL" in a else np.tile([0, 1.0, 0], (len(P), 1))
            UV = acc(a["TEXCOORD_0"]).astype(float) if "TEXCOORD_0" in a else np.zeros((len(P), 2))
            if sk is not None and "JOINTS_0" in a:
                J, Wt = acc(a["JOINTS_0"]).astype(int), acc(a["WEIGHTS_0"]).astype(float)
                k = J[np.arange(len(P)), Wt.argmax(1)]
                M = skm[k]
                owner = loc[k]
            else:
                M = np.repeat(Wn[ni][None], len(P), 0)
                owner = np.full(len(P), to_main(ni))
            P = np.einsum("nij,nj->ni", M[:, :3, :3], P) + M[:, :3, 3]
            N = np.einsum("nij,nj->ni", M[:, :3, :3], N)
            N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
            tris = acc(pr["indices"]).reshape(-1, 3).astype(int) if "indices" in pr else np.arange(len(P) // 3 * 3).reshape(-1, 3)
            tex, color = None, (255, 255, 255, 255)
            if (mi := pr.get("material")) is not None:
                pbr = gl["materials"][mi].get("pbrMetallicRoughness", {})
                color = tuple(int(round(c * 255)) for c in pbr.get("baseColorFactor", [1, 1, 1, 1]))
                if (bct := pbr.get("baseColorTexture")) is not None:
                    if bct["index"] not in texcache:
                        try:
                            texcache[bct["index"]] = image(bct["index"])
                        except Exception:                  # noqa: BLE001 - a missing image: plain colour
                            texcache[bct["index"]] = None
                    tex = texcache[bct["index"]]
            prims.append({"pos": P, "nrm": N, "uv": UV, "tris": tris, "owner": owner, "tex": tex, "color": color,
                          "prop": nd.get("name") in props})
    if not prims:
        raise ValueError(f"{Path(path).name}: no triangles")
    return {"joints": np.array([Wn[j][:3, 3] for j in jn]), "parent": parent, "roles": ri, "prims": prims, "names": names}


def _snap(v, skip=-1) -> np.ndarray:
    a = np.abs(np.asarray(v, float))
    if skip >= 0:
        a[skip] = -1
    i = int(a.argmax())
    out = np.zeros(3)
    out[i] = np.sign(v[i]) or 1.0
    return out


def facing(rig: dict) -> np.ndarray:
    """Rotation (rows) that turns the character to Mario's frame: its left -> +X, up -> +Y, front -> +Z."""
    S, ri = rig["joints"], rig["roles"]
    top = next((r for r in ("head", "neck", "chest") if r in ri), None)
    up = S[ri[top]] - S[ri["hip"]] if top and "hip" in ri else np.array([0, 1.0, 0])
    lefts = [S[ri["l_" + p]] - S[ri["r_" + p]] for p in ("thigh", "upper", "shin", "fore", "clav")
             if "l_" + p in ri and "r_" + p in ri]
    left = np.mean(lefts, 0) if lefts else np.array([1.0, 0, 0])
    ext = float(np.ptp(np.concatenate([p["pos"] for p in rig["prims"]]), 0).max())
    if np.linalg.norm(up) < 0.1 * ext:                     # hip and chest on top of each other (Kirby): trust +Y
        up = np.array([0, 1.0, 0])
    if np.linalg.norm(left) < 0.05 * ext:
        left = np.array([1.0, 0, 0])
    u = _snap(up)
    lf = _snap(left, int(np.abs(u).argmax()))
    return np.stack([lf, u, np.cross(lf, u)])


# ---------------------------------------------------------------- Mario (target)

def mario_target(rom: bytes) -> dict:
    model = sm.extract(rom, ANIM)
    js = model["joints"]
    Wp = [jt["world"] for jt in js]
    T = np.array([w[3, :3] for w in Wp])
    allv, head = [], []
    for k, jt in enumerate(js):
        for _key, tri in jt["tris"]:
            for p, _c, _uv in tri:
                v = (np.r_[np.asarray(p, float), 1.0] @ Wp[k])[:3]
                allv.append(v)
                if k == MARIO["head"]:
                    head.append(v)
    allv, head = np.array(allv), np.array(head)
    return {"T": T, "W": Wp, "parent": [-1 if jt["parent"] is None else jt["parent"] for jt in js],
            "ground": float(allv[:, 1].min()), "head_h": float(np.ptp(head[:, 1])), "joints": len(js)}


def _rot_between(a, b):
    from .re4gc_enemies import _rot_between as rb
    return rb(np.asarray(a, float), np.asarray(b, float))


def retarget(rig: dict, tgt: dict, scale: dict | None = None, jmap: dict | None = None) -> tuple[list[dict], dict]:
    """-> (prims with pos/nrm in Mario's pose-197 world space and J = Mario joint per vertex, fit report).
    scale: {"head": k} = the character's own head-bone scale (Blender Live Link / the sidebar's head size), applied on
    top of the automatic head fit, about the head's base (the neck stays where it is). jmap: {role: target joint} for
    another skeleton (default Mario's; gbox.oot_swap passes Link's or an NPC's limbs)."""
    from .re4gc_enemies import _role_of_joint
    MARIO = jmap or globals()["MARIO"]
    hipj, chestj = MARIO["hip"], MARIO.get("chest", MARIO["hip"])
    B = facing(rig)
    S = rig["joints"] @ B.T
    ri, T = rig["roles"], tgt["T"]
    jrole = np.array(_role_of_joint({"roles": ri, "parent": rig["parent"]}))
    prims = [{**p, "pos": p["pos"] @ B.T, "nrm": p["nrm"] @ B.T, "role": jrole[p["owner"]]} for p in rig["prims"]]
    allp = np.concatenate([p["pos"] for p in prims])
    allr = np.concatenate([p["role"] for p in prims])
    isprop = np.concatenate([np.full(len(p["pos"]), bool(p.get("prop"))) for p in prims])
    arms = np.isin(allr, ["l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand"]) | isprop
    body = allp[~arms] if (~arms).sum() > 10 else allp
    ground_s = float(body[:, 1].min())
    hip = S[ri["hip"]] if "hip" in ri else body.mean(0)
    headp = allp[(allr == "head") & ~isprop]          # a hat doesn't make the head bigger
    head_y = S[ri["head"]][1] if "head" in ri else float(body[:, 1].max())
    th = T[MARIO.get("head", chestj)]
    s = (th[1] - tgt["ground"]) / max(head_y - ground_s, 1e-9)
    if tgt.get("fit_height"):                              # tall targets (gbox.pe_swap): whole figure height, not head joint
        s = tgt["fit_height"] / max(float(allp[~isprop][:, 1].max() if (~isprop).any() else allp[:, 1].max()) - ground_s, 1e-9)
    sy_up = float(np.clip((th[1] - T[hipj][1]) / max(head_y - hip[1], 1e-9), 0.6 * s, 1.8 * s))
    sy_dn = float(np.clip((T[hipj][1] - tgt["ground"]) / max(hip[1] - ground_s, 1e-9), 0.6 * s, 1.8 * s))
    if "head" not in ri:                                   # round bodies (Kirby, Jigglypuff): no torso stretch at all
        s = sy_up = sy_dn = (T[hipj][1] - tgt["ground"]) / max(hip[1] - ground_s, 1e-9)
    sx = 1.0
    if "l_upper" in ri and "r_upper" in ri:                # thin characters grow toward Mario's round shoulders
        half_s = abs(S[ri["l_upper"]][0] - S[ri["r_upper"]][0]) / 2 * s
        half_t = abs(T[MARIO["l_upper"]][0] - T[MARIO["r_upper"]][0]) / 2
        sx = float(np.clip(half_t / max(half_s, 1e-9), 1.0, 1.5))

    def torso(p):
        p = np.atleast_2d(p)
        d = p - hip
        return T[hipj] + np.stack([d[:, 0] * s * sx, np.where(d[:, 1] > 0, d[:, 1] * sy_up, d[:, 1] * sy_dn), d[:, 2] * s], 1)
    rules = {}                                             # role -> (M (3x3), source pivot, target point, rotation, joint)
    head_k = 1.0
    if len(headp) and "head" in MARIO:
        base = np.array([S[ri["head"]][0], headp[:, 1].min(), S[ri["head"]][2]])
        head_k = float(np.clip(tgt["head_h"] / max(np.ptp(headp[:, 1]) * s, 1e-9), 1.0, 1.5))
        head_k *= float((scale or {}).get("head", 1.0))
        rules["head"] = (np.eye(3) * s * head_k, base, torso(base)[0], np.eye(3), MARIO["head"])

    def centroid(r):
        m = allr == r
        return allp[m].mean(0) if m.any() else None
    stretch = {}
    for a, b, c in LIMBS:
        rot = None
        for seg, (r, nxt, nxt2) in enumerate(((a, b, c), (b, c, None))):
            if r not in ri or r not in MARIO or nxt not in MARIO:
                continue
            start = torso(S[ri[r]])[0] if seg == 0 else T[MARIO[r]]
            if nxt in ri:
                end_s, end_t, free = S[ri[nxt]], T[MARIO[nxt]], True
            elif nxt2 and nxt2 in ri and nxt2 in MARIO:
                end_s, end_t, free = S[ri[nxt2]], T[MARIO[nxt2]], True
            else:
                end_s, end_t, free = centroid(r), T[MARIO[nxt]], False
            if end_s is None:
                continue
            ds, dt = end_s - S[ri[r]], end_t - start
            if np.linalg.norm(ds) < 1e-6 * np.ptp(allp[:, 1]) or np.linalg.norm(dt) < 1e-6:
                continue
            rot = _rot_between(ds, dt)
            k = float(np.clip(np.linalg.norm(dt) / (np.linalg.norm(ds) * s), 0.5, 2.0)) if free else 1.0
            d = dt / np.linalg.norm(dt)
            rules[r] = (s * (np.eye(3) + (k - 1) * np.outer(d, d)) @ rot, S[ri[r]], start, rot, MARIO[r])
            stretch[r] = round(k, 2)
        if c in ri and c in MARIO and rot is not None:                    # hand / foot: the forearm's / shin's rotation, on the wrist / ankle
            rules[c] = (s * rot, S[ri[c]], T[MARIO[c]], rot, MARIO[c])
    split = T[hipj][1] + 0.5 * (T[chestj][1] - T[hipj][1])            # torso family: below -> Mario's pelvis, above -> his chest
    out = []
    for p in prims:
        P, N = np.zeros_like(p["pos"]), p["nrm"].copy()
        J = np.zeros(len(P), int)
        for r in set(p["role"].tolist()):
            m = p["role"] == r
            if r in rules:
                M, piv, at, rot, j = rules[r]
                P[m] = (p["pos"][m] - piv) @ M.T + at
                N[m] = p["nrm"][m] @ rot.T
                J[m] = j
            else:                                          # hip, chest, neck, clavicles, anything unmapped
                P[m] = torso(p["pos"][m])
                J[m] = np.where(P[m][:, 1] >= split, chestj, hipj)
        Jv = np.zeros((len(P), 4), np.int64)
        Jv[:, 0] = J
        Wv = np.zeros((len(P), 4))
        Wv[:, 0] = 1
        out.append({"pos": P, "nrm": N, "uv": p["uv"], "tris": p["tris"], "J": Jv, "W": Wv, "tex": p["tex"],
                    "color": p["color"], "name": f"m{len(out)}", "prop": bool(p.get("prop"))})
    rep_flip = _orient(out)
    rep = {"normals_flipped": rep_flip, "scale": round(float(s), 4), "torso_up": round(sy_up / s, 2), "torso_down": round(sy_dn / s, 2),
           "shoulder_widen": round(sx, 2), "head_scale": round(head_k, 2), "head_scale_user": float((scale or {}).get("head", 1.0)),
           "limb_stretch": stretch,
           "roles_used": sorted(ri), "facing": B.astype(int).tolist()}
    return out, rep


def _orient(prims: list[dict]) -> int:
    """Some extractions have inward normals / reversed winding (FF7): SM64 lights by vertex normal, so a part lit from
    inside looks black. Per material: if most normals point into their joint's part, flip normals and winding."""
    allp = np.concatenate([p["pos"][p["tris"]].reshape(-1, 3) for p in prims])
    allj = np.concatenate([p["J"][:, 0][p["tris"]].reshape(-1) for p in prims])
    cen = {j: allp[allj == j].mean(0) for j in set(allj.tolist())}
    flipped = 0
    for p in prims:
        T = p["tris"]
        if not len(T):
            continue
        c = p["pos"][T].mean(1) - np.array([cen[j] for j in p["J"][:, 0][T[:, 0]]])
        if ((c * p["nrm"][T].mean(1)).sum(1) > 0).mean() < 0.35:
            p["nrm"] = -p["nrm"]
            p["tris"] = T[:, ::-1].copy()
            flipped += 1
    return flipped


def write_rigged(prims: list[dict], tgt: dict, path: Path, name: str) -> Path:
    """The retargeted model on Mario's skeleton (joints j00..j19 at their pose-197 positions) as a skinned glTF."""
    from .melee_models import write_gltf
    joints = []
    for k in range(tgt["joints"]):
        w = np.eye(4)
        w[:3, 3] = tgt["T"][k]
        joints.append({"parent": tgt["parent"][k], "world": w})
    return write_gltf(Path(path), joints, prims, 1.0, name, [f"j{k:02d}" for k in range(tgt["joints"])])


def read_rigged(path: Path) -> list[dict]:
    """A Mario-rigged glTF / GLB (joints named jNN; ours or Blender's decimated export) -> prims with world positions
    and the Mario joint per vertex."""
    from .re4gc_models import _gltf_load, _node_world
    gl, acc, image = _gltf_load(path)
    Wn = _node_world(gl)
    out, texcache = [], {}
    for nd in gl["nodes"]:
        if "mesh" not in nd or "skin" not in nd:
            continue
        sk = gl["skins"][nd["skin"]]
        ibm = acc(sk["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
        skm = np.array([Wn[j] @ ibm[k] for k, j in enumerate(sk["joints"])])
        jid = np.array([int(re.sub(r"\D", "", gl["nodes"][j]["name"])) for j in sk["joints"]])
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            a = pr["attributes"]
            P = acc(a["POSITION"]).astype(float)
            N = acc(a["NORMAL"]).astype(float) if "NORMAL" in a else np.tile([0, 1.0, 0], (len(P), 1))
            UV = acc(a["TEXCOORD_0"]).astype(float) if "TEXCOORD_0" in a else np.zeros((len(P), 2))
            J, Wt = acc(a["JOINTS_0"]).astype(int), acc(a["WEIGHTS_0"]).astype(float)
            k = J[np.arange(len(P)), Wt.argmax(1)]
            M = skm[k]
            P = np.einsum("nij,nj->ni", M[:, :3, :3], P) + M[:, :3, 3]
            N = np.einsum("nij,nj->ni", M[:, :3, :3], N)
            tris = acc(pr["indices"]).reshape(-1, 3).astype(int) if "indices" in pr else np.arange(len(P)).reshape(-1, 3)
            tex, color = None, (255, 255, 255, 255)
            if (mi := pr.get("material")) is not None:
                pbr = gl["materials"][mi].get("pbrMetallicRoughness", {})
                color = tuple(int(round(c * 255)) for c in pbr.get("baseColorFactor", [1, 1, 1, 1]))
                if (bct := pbr.get("baseColorTexture")) is not None:
                    if bct["index"] not in texcache:
                        texcache[bct["index"]] = image(bct["index"])
                    tex = texcache[bct["index"]]
            out.append({"pos": P, "nrm": N, "uv": UV, "tris": tris, "jid": jid[k], "tex": tex, "color": color})
    return out


# ---------------------------------------------------------------- writer input + budget

def _fill_alpha(img: np.ndarray) -> np.ndarray:
    """SM64 draws these opaque: transparent texels take the mean colour of the opaque ones (no black fringes)."""
    a = img[..., 3] >= 128
    if a.all() or not a.any():
        return img
    img = img.copy()
    img[~a, :3] = img[a, :3].mean(0).astype(np.uint8)
    img[..., 3] = 255
    return img


def to_writer(prims: list[dict], tgt: dict) -> tuple[dict, list, list]:
    """-> (parts {joint: [(material, ((pos, nrm, uv) x3))]} joint-local, materials, triangles per material)."""
    inv = [np.linalg.inv(w) for w in tgt["W"]]
    mats, key_ix, parts, uses = [], {}, {}, []
    for p in prims:
        tex = p["tex"]
        key = (hash(np.ascontiguousarray(tex).tobytes()) if tex is not None else None, tuple(p["color"][:3]))   # same image = one material
        if key not in key_ix:
            col = np.array(p["color"][:3], float) / 255
            if tex is not None:
                t = _fill_alpha(np.asarray(tex, np.uint8))
                if (col < 0.999).any():
                    t = t.copy()
                    t[..., :3] = (t[..., :3] * col).astype(np.uint8)
                m = {"diffuse": (0xFF, 0xFF, 0xFF), "ambient": (0x80, 0x80, 0x80), "tex": t}
            else:
                c = (col * 255).astype(int)
                m = {"diffuse": tuple(int(v) for v in c), "ambient": tuple(int(v) // 2 for v in c), "tex": None}
            key_ix[key] = len(mats)
            mats.append(m)
            uses.append(0)
        mi = key_ix[key]
        for t in p["tris"]:
            j = int(np.bincount(p["jid"][t]).argmax())      # a triangle is rigid on one joint
            vs = []
            for i in t:
                q = (np.r_[p["pos"][i], 1.0] @ inv[j])[:3]
                n = p["nrm"][i] @ inv[j][:3, :3]
                vs.append((q, n / (np.linalg.norm(n) or 1), tuple(p["uv"][i])))
            parts.setdefault(j, []).append((mi, tuple(vs)))
            uses[mi] += 1
    return parts, mats, uses


def fit_budget(parts: dict, mats: list, uses: list) -> tuple[list, dict]:
    """Fit the model data into the 0x1CD20 bytes of Mario's own data: textures 64x32 -> 16x32 with the least used ones
    flattened to their mean colour first (up to 3/4 of them), then 16x16 / 8x8 and more flattening.
    -> (materials, report); ValueError if even untextured it doesn't fit."""
    order = sorted((i for i, m in enumerate(mats) if m["tex"] is not None), key=lambda i: uses[i])
    step = max(1, len(order) // 8)
    tries = [(mt, f) for mt in (2048, 1024, 512) for f in range(0, len(order) * 3 // 4 + 1, step)]
    tries += [(mt, min(f, len(order))) for f in range(0, len(order) + step, step) for mt in (256, 64)]
    for mt, flat in tries:
        cur = []
        for i, m in enumerate(mats):
            if m["tex"] is None:
                cur.append(m)
            elif i in order[:flat]:
                c = m["tex"][..., :3].reshape(-1, 3).mean(0).astype(int)
                cur.append({"diffuse": tuple(int(v) for v in c), "ambient": tuple(int(v) // 2 for v in c), "tex": None})
            else:
                cur.append({**m, "tex": W.fit_tmem(m["tex"], mt)})
        blob, _ = W.build(parts, cur, 0x04000000)
        if len(blob) <= W.MARIO_END:
            return cur, {"bytes": len(blob), "budget": W.MARIO_END, "max_texels": mt, "textures": len(order) - flat,
                         "flattened": flat}
    blob, _ = W.build(parts, [{**m, "tex": None} for m in mats], 0x04000000)
    raise ValueError(f"{sum(len(v) for v in parts.values())} triangles need {len(blob)} bytes even untextured "
                     f"(budget {W.MARIO_END})")


def _blender(cfg=None) -> str | None:
    from .characters import _blender as find
    from .re4gc_enemies import blender_exe
    if cfg is not None:
        return find(cfg)
    b = blender_exe()
    return b if b and Path(b).exists() else None


def _as_read(p: dict) -> dict:
    """A retargeted prim (write_rigged input) -> the read_rigged form (world positions + Mario joint per vertex)."""
    return {"pos": p["pos"], "nrm": p["nrm"], "uv": p["uv"], "tris": p["tris"], "jid": p["J"][:, 0], "tex": p["tex"],
            "color": p["color"], "prop": True}


def _mat_keys(prims: list[dict]) -> list:
    """Material keys in to_writer's order (to tell which materials belong to props)."""
    keys = []
    for p in prims:
        k = (id(p["tex"]) if p["tex"] is not None else None, tuple(p["color"][:3]))
        if k not in keys:
            keys.append(k)
    return keys


def build(rom: bytes, model: Path, roles: dict, work: Path, name: str, max_tris: int = MAX_TRIS, blender: str | None = None,
          progress=lambda p, m: None, scale: dict | None = None, props=()) -> dict:
    """Library model -> {rom: the patched ROM bytes, rigged: the Mario-rigged glTF, report}. Props (node names) ride their
    bone; they're kept whole while the body is decimated, and simplified only above PROP_MAX_TRIS (reported)."""
    from .re4gc_enemies import decimate
    check_rom(rom)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    progress(15, "Reading Mario's skeleton (idle pose) from the ROM")
    tgt = mario_target(rom)
    progress(25, f"Retargeting {name} onto Mario's 20 joints")
    rig = load_rig(Path(model), roles, props)
    prims, rep = retarget(rig, tgt, scale)
    rigged = write_rigged(prims, tgt, work / "sm64_mario.gltf", name)
    pprims = [p for p in prims if p.get("prop")]
    bprims = [p for p in prims if not p.get("prop")]
    ptris = sum(len(p["tris"]) for p in pprims)
    prop_rep = {"triangles": ptris, "meshes": len(pprims), "simplified": False} if pprims else None
    body_rigged = write_rigged(bprims, tgt, work / "sm64_body.gltf", name) if pprims else rigged
    prop_read = [_as_read(p) for p in pprims]
    if ptris > PROP_MAX_TRIS:                              # a heavy prop: decimated on its own, reported
        if not blender:
            raise ValueError(f"the props have {ptris} triangles (limit {PROP_MAX_TRIS}) and there's no Blender here to simplify them")
        progress(40, f"Simplifying the props {ptris} -> {PROP_MAX_TRIS} triangles (Blender)")
        pr = write_rigged(pprims, tgt, work / "sm64_props.gltf", name + " props")
        prop_read = [dict(q, prop=True) for q in read_rigged(decimate(pr, work / "props_dec.glb", float(PROP_MAX_TRIS), blender))]
        prop_rep |= {"simplified": True, "simplified_to": sum(len(q["tris"]) for q in prop_read),
                     "why": f"over the {PROP_MAX_TRIS}-triangle prop limit of Mario's model data"}
    ptris = sum(len(q["tris"]) for q in prop_read)
    src = body_rigged
    tris = sum(len(p["tris"]) for p in prims)
    rep["source_triangles"] = tris
    for target in (max_tris, int(max_tris * 0.75), int(max_tris * 0.55), int(max_tris * 0.4)):
        btarget = max(200, target - ptris)
        if tris - (ptris if pprims else 0) > btarget:
            if not blender:
                raise ValueError(f"{tris} triangles (budget ~{max_tris}) and no Blender on this node to decimate")
            progress(45, f"Decimating the body -> {btarget} triangles (Blender)")
            src = decimate(body_rigged, work / f"dec_{target}.glb", float(btarget), blender)
        progress(60, "Fitting textures and triangles into Mario's data (64x32 RGBA16 max)")
        rprims = read_rigged(src) + prop_read
        parts, mats, uses = to_writer(rprims, tgt)
        tris = sum(len(v) for v in parts.values())
        try:
            fitted, frep = fit_budget(parts, mats, uses)
            break
        except ValueError as e:
            last = e
    else:
        raise last
    if prop_rep:                                           # did the texture budget flatten a prop's texture?
        keys = _mat_keys(rprims)
        pkeys = set(_mat_keys([q for q in rprims if q.get("prop")]))
        flat = [i for i, k in enumerate(keys) if k in pkeys and mats[i]["tex"] is not None and fitted[i]["tex"] is None]
        if flat:
            prop_rep |= {"simplified": True, "textures_flattened": len(flat),
                         "why": (prop_rep.get("why", "") + "; " if prop_rep.get("why") else "") +
                                "Mario's model data budget: the prop's texture became its average colour"}
        prop_rep["final_triangles"] = ptris
        rep["props"] = prop_rep
    progress(75, "Writing the display lists into a copy of the ROM")
    out = W.inject(rom, parts, fitted)
    return {"rom": out, "rigged": rigged, "report": rep | frep | {"triangles": tris, "materials": len(fitted),
                                                                 "joints": sorted(int(j) for j in parts)}}


def image_name(meta: dict) -> str:
    return "Super Mario 64 - " + re.sub(r"[^\w .()'-]+", "", meta["name"]).strip() + " (USA).z64"


def build_mod(cfg, meta: dict, game: dict, progress=lambda p, m: None, root: Path | None = None) -> dict:
    """On the control-plane node: build the file mod sm64_<slug> from the operator's ROM; copies the Mario-rigged
    model and a preview of it into the library entry (targets/)."""
    from . import characters as C, filemods
    from .models import CatalogEntry
    from .tools import rom_path
    root = root or C.library_root(cfg)
    gid, name = game["game_id"], f"sm64_{meta['slug']}"
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json): can't map it onto Mario's joints")
    rom_file = rom_path(CatalogEntry.model_validate(game), cfg)
    progress(5, f"Reading {rom_file.name}")
    rom = rom_bytes(rom_file)
    work = Path(cfg.cache) / "characters_build" / meta["slug"] / "sm64"
    shutil.rmtree(work, ignore_errors=True)
    b = build(rom, root / meta["slug"] / meta["model"], roles, work, meta["name"], blender=_blender(cfg), progress=progress,
              scale=(meta.get("rig") or {}).get("scale"), props=[p["node"] for p in meta.get("props") or []])
    progress(85, "Rendering a preview of the model on Mario's skeleton")
    tdir = root / meta["slug"] / "targets"
    tdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(b["rigged"], tdir / "sm64_mario.gltf")
    prev = C.render_preview(tdir / "sm64_mario.gltf", tdir / "sm64_preview.png")
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    img = image_name(meta)
    (d / img).write_bytes(b["rom"])
    mj = {"name": name, "game_id": gid, "image": img, "files": ["@image: Mario model (gbox.sm64_swap)"], "built": time.time(),
          "character": meta["slug"], "source": meta["model"], **{k: b["report"][k] for k in ("triangles", "materials", "bytes")}}
    (d / ".gbox-mod.json").write_text(json.dumps(mj))
    stale = Path(cfg.cache) / gid / img                    # a staged copy of an older build
    if stale.exists():
        stale.unlink()
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": img, "preview": str(prev), "rigged": str(tdir / "sm64_mario.gltf"), "report": b["report"]}


# ---------------------------------------------------------------- characters op=use

def _have_mod(ctx, gid: str, name: str) -> bool:
    from . import characters as C, filemods
    if (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists():
        return True
    try:
        return bool(C._api(ctx, "GET", f"/api/modfiles/{gid}/{name}").get("files"))
    except Exception:                                      # noqa: BLE001 - 404: not built anywhere
        return False


def _wait(ctx, job: dict, limit: float) -> dict:
    from . import characters as C
    t0 = time.time()
    while job.get("state") in ("queued", "running") and time.time() - t0 < limit:
        time.sleep(1)
        job = C._api(ctx, "GET", f"/api/jobs/{job['id']}")
    return job


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """Build sm64_<slug> if missing (on the control plane, where the collection is), record it in the character's
    targets, launch it on the node of the requesting session (the operator's PC for a PC session)."""
    from . import characters as C
    gid, name = game["game_id"], f"sm64_{meta['slug']}"
    if meta.get("source", {}).get("game_id") in GAME_IDS and not meta.get("variant_of"):
        return {"status": "native", "message": f"{meta['name']} is Super Mario 64's own player: launch the game without a mod."}
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    built = None
    stale = any(t.get("needs_rebuild") for t in meta.get("targets", {}).get(gid, []) if t.get("mod") == name)
    if inp.rebuild or stale or not _have_mod(ctx, gid, name):
        if C.library_root(ctx.config).is_dir():
            built = build_mod(ctx.config, meta, game, ctx.progress)
            C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                   json={"game_id": gid, "slot": "player", "mod": name, "nodes": [C.HOST_OS],
                         "notes": f"replaces Mario (all his animations); {built['report']['triangles']} triangles, "
                                  f"{built['report']['textures']} textures <= {built['report']['max_texels']} texels; "
                                  "preview targets/sm64_preview.png"})
        else:                                              # not the control plane: build there, launch here
            cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
            ctx.progress(10, "Building the SM64 mod on the control-plane node (the collection lives there)")
            j = C._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid, "rebuild": inp.rebuild,
                                           "launch": False}, cp, 1800)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
                return {"status": "failed", "mod": name, "error": r.get("error") or j.get("error") or r}
            built = r.get("build")
    res = {"mod": name, "build": built, "replaces": "Mario (player model; his skeleton and animations stay)"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(90, f"Launching Super Mario 64 with {meta['name']} (mod {name})")
    for _ in range(2):                                     # a new ROM file's first start can miss RetroArch's 30 s window
        lj = _wait(ctx, C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name,
                                                                                               "node": node}}), 600)
        if lj.get("state") == "succeeded" or "content not running" not in str(lj.get("error")):
            break
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    ok = lj.get("state") == "succeeded"
    status = ("built+launched" if built else "launched") if ok else ("built, launch " + str(lj.get("state")))
    msg = (f"Super Mario 64 is running with {meta['name']} in Mario's place (mod {name}, session {launch['session_id']}). "
           f"It's at the title screen: the big Mario head there is a separate model; {meta['name']} appears once a file is "
           "started (castle grounds, levels). Already launched: don't launch it again."
           if ok else f"Mod {name} is {'built' if built else 'ready'} but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": status, "launch": launch, "message": msg}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("rom")
    b.add_argument("character", help="library entry folder (meta.json + model)")
    b.add_argument("out")
    b.add_argument("--max-tris", type=int, default=MAX_TRIS)
    a = ap.parse_args()
    cdir = Path(a.character)
    meta = json.loads((cdir / "meta.json").read_text())
    od = Path(a.out)
    res = build(rom_bytes(a.rom), cdir / meta["model"], meta["rig"]["roles"], od, meta["name"], a.max_tris, _blender(),
                lambda p, m: print(f"{p:3.0f}% {m}"))
    (od / image_name(meta)).write_bytes(res["rom"])
    from .characters import render_preview
    render_preview(res["rigged"], od / "preview.png")
    print(json.dumps(res["report"], indent=1, default=str))
