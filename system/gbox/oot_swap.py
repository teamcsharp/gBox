"""Zelda: Ocarina of Time (N64): any character from gBox's collection in Link's place, in an NPC's place, or swapped
with them ("replace me with Tifa", "make the Kokiri kid Cloud", "swap Link and Saria", "play as Mido").

`characters op=use / swap / extract` route OoT here. Everything is built from the operator's own ROM and collection.
Pipeline (the gbox.sm64_swap recipe on OoT skeletons):
  1. the target skeleton: Link's FlexSkeleton (object_link_boy / object_link_child, 21 LOD limbs) posed with his idle
     animation (gameplay_keep gPlayerAnim_link_normal_wait), or an NPC's skeleton (its object, found from the actor
     under the screen point) posed with its CURRENT pose read from RAM (SkelAnime.jointTable) or an animation in the
     object. Body roles: Link's are fixed (LINK_ROLES); an NPC's are guessed from its limb layout (guess_roles).
  2. the library model retargeted onto those limbs (sm64_swap.retarget with the target's joint map): rigid, one limb per
     vertex; the skeleton (limb count, order, joint offsets) is never changed, so every animation of the game drives it.
  3. Blender decimation above the triangle budget, textures RGBA16 <= 64x32 (then smaller / flattened) until the new
     data fits the object (the replaced model's own bytes first, then GROWTH).
  4. gbox.oot_writer: new F3DEX2 display lists appended to the object, every limb pointed at its new list (limbs that
     had one keep one, so matrix and body-part counts stay). Link also: his hand / waist / first-person display-list
     tables in `code` (z_player_lib.c) point at the new hands; equipment lists (sword, shields, bow, hookshot, ocarina,
     hammer, bottle...) keep their item and lose Link's hand triangles (stripped by material), so items stay in the new
     hands; the sheath and shield on the back are kept; iron / hover boots and gauntlet plates are blanked.
  5. the patched ROM is written as a gBox file mod cache/mods/<game_id>/oot_<slug> whose image has the SAME file name
     as the operator's game, so RetroArch keeps using the same save file (progress carries over).
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from . import oot_writer as OW
from . import sm64_swap as S

LINK = {"adult": {"obj": OW.OBJECT_LINK_BOY, "skel": 0x377F4, "eyes": 0x0000, "mouth": 0x4000, "name": "Link (adult)"},
        "child": {"obj": OW.OBJECT_LINK_CHILD, "skel": 0x2CF6C, "eyes": 0x0000, "mouth": 0x4000, "name": "Link (child)"}}
IDLE_ANIM = 0x3238                                     # gameplay_keep: gPlayerAnim_link_normal_wait
TUNIC = 0x1E691BFF                                     # Kokiri tunic (env colour Player_DrawImpl sets)
# PlayerLimb - 1 (z64player.h): 0 root, 1 waist, 2 lower, 3-5 R thigh/shin/foot, 6-8 L, 9 upper, 10 head, 11 hat,
# 12 collar, 13-15 L shoulder/forearm/hand, 16-18 R, 19 sheath, 20 torso
LINK_ROLES = {"hip": 1, "chest": 20, "head": 10, "l_upper": 13, "l_fore": 14, "l_hand": 15, "r_upper": 16, "r_fore": 17,
              "r_hand": 18, "l_thigh": 6, "l_shin": 7, "l_foot": 8, "r_thigh": 3, "r_shin": 4, "r_foot": 5}
# Link's display-list tables in `code` (zeldaret/oot src/code/z_player_lib.c): name -> (limb they draw on, entries).
# Entries alternate adult / child (adult near, child near, adult far, child far; 2-entry tables: adult, child).
# Offsets are in object_link_boy (adult entries) / object_link_child (child entries). Sheath tables are left alone.
LINK_ARRAYS = {
    "sPlayerRightHandShieldDLs": (18, [0x226e0, 0x14320, 0x27690, 0x16620, 0x226e0, 0x14440, 0x27690, 0x16740, 0x22970,
                                       0x14320, 0x27918, 0x16620, 0x241c0, 0x14320, 0x28b40, 0x16620]),
    "gPlayerLeftHandBgsDLs": (15, [0x238c8, 0x15540, 0x286b8, 0x15540, 0x23d50, 0x15540, 0x291e8, 0x15540]),
    "gPlayerLeftHandOpenDLs": (15, [0x21aa8, 0x13cb0, 0x26c58, 0x16280]),
    "gPlayerLeftHandClosedDLs": (15, [0x21ce8, 0x13e18, 0x26df0, 0x163c0]),
    "sPlayerLeftHandSwordDLs": (15, [0x21f78, 0x13f38, 0x27078, 0x17630]),
    "sPlayerRightHandOpenDLs": (18, [0x22498, 0x141c0, 0x274f8, 0x164e0]),
    "sPlayerRightHandClosedDLs": (18, [0x226e0, 0x14320, 0x27690, 0x16620]),
    "sPlayerRightHandBowSlingshotDLs": (18, [0x22da8, 0x15df0, 0x27b88, 0x17d38]),
    "sPlayerWaistDLs": (1, [0x35330, 0x202a8, 0x2f530, 0x1aec8]),
    "sPlayerRightHandOcarinaDLs": (18, [0x24698, 0x15ba8, 0x28f58, 0x17af0]),
    "sPlayerRightHandOotDLs": (18, [0x24698, 0x15958, 0x28f58, 0x178a0]),
    "sPlayerRightHandHookshotDLs": (18, [0x24d70, 0x141c0, 0x24d70, 0x164e0]),
    "sPlayerLeftHandHammerDLs": (15, [0x233e0, 0x13cb0, 0x28288, 0x16280]),
    "gPlayerLeftHandBoomerangDLs": (15, [0x21aa8, 0x14660, 0x26c58, 0x16908]),
    "sPlayerLeftHandBottleDLs": (15, [0x24b58, 0x15fd0, 0x24b58, 0x15fd0]),
    "sFirstPersonLeftForearmDLs": (14, [0x29918, 0x0]),
    "sFirstPersonLeftHandDLs": (15, [0x29c20, 0x0]),
    "sFirstPersonRightShoulderDLs": (16, [0x36e58, 0x21ae8]),
    "sFirstPersonForearmDLs": (17, [0x29fa0, 0x0]),
    "sFirstPersonRightHandHoldingWeaponDLs": (18, [0x2a248, 0x18048]),
}
# tables gBox leaves alone (sheath + shields on the back, the bottle): only to know which bytes stay in use
KEPT_TABLES = [[0x23160, 0x15248, 0x27f00, 0x17360, 0x23160, 0x14d68, 0x27f00, 0x16ee8, 0x20a78, 0x148a8, 0x25fb8, 0x16a98,
                0x211b8, 0x15248, 0x264f0, 0x17360, 0x0, 0x0, 0x0, 0x0, 0x0, 0x22688, 0x0, 0x22688],
               [0x249d8, 0x15408, 0x28150, 0x17500, 0x249d8, 0x15010, 0x28150, 0x17150, 0x20e70, 0x14b40, 0x262b8, 0x16cf8,
                0x216b0, 0x15408, 0x26910, 0x17500, 0x0, 0x0, 0x0, 0x0, 0x249d8, 0x22688, 0x249d8, 0x22688],
               [0x2ad58, 0x18478]]
# plain hand lists of each age (their materials define "Link's body" when stripping equipment lists)
HAND_TABLES = ("gPlayerLeftHandOpenDLs", "gPlayerLeftHandClosedDLs", "sPlayerRightHandOpenDLs", "sPlayerRightHandClosedDLs")
# drawn by Player_DrawImpl on top of the body: gauntlet plates, iron / hover boots (adult), Goron bracelet (child)
BLANK = {"adult": [0x25218, 0x252D8, 0x25438, 0x25598, 0x25658, 0x257B8, 0x25918, 0x25A60, 0x25BA8, 0x25DB0],
         "child": [0x16118]}
MAX_TRIS = 1500
GROWTH = {"link": 0xA000, "npc": 0x9000}              # bytes an object may GROW by (object space is shared per scene:
                                                        # Kokiri Forest as child has ~130 KB free with vanilla objects)
TEX_STEPS = (2048, 1024, 512, 256, 64)
OBJ_FA, OBJ_OS_ANIME = 0x13D, 0xC5                     # object_fa (Fado's head), object_os_anime (Kokiri animations)
NAMES = json.loads((Path(__file__).with_name("oot_names.json")).read_text())
# limb numbers here are 0-based (the game's limb callbacks count from 1: En_Ko's "limbIndex == 15" is limb 14)
# compound NPCs: actors that draw one skeleton from several objects (segment 6 switched per limb) -> every object of the
# group gets the same new data at the same offset; head_dls = constant head lists the actor swaps in for the head limb
GROUPS = {
    # En_Ko (z_en_ko.c sModelInfo): boys draw head, body and legs from object_km1; girls from object_kw1; Fado has
    # object_fa's head on object_kw1's body -> boys = km1 alone, girls = kw1 + fa (her head list branched too)
    ("En_Ko", 0xFC): {"objects": [0xFC], "skels": [(0xFC, 0xF0)], "head_limb": 14, "head_dls": [(0xFC, 0x1890)],
                      "anim_objects": [OBJ_OS_ANIME], "note": "every Kokiri boy shares object_km1, so all of them change"},
    ("En_Ko", 0xFD): {"objects": [0xFD, OBJ_FA], "skels": [(0xFD, 0xF0)], "head_limb": 14,
                      "head_dls": [(0xFD, 0x2C10), (OBJ_FA, 0x2940)], "anim_objects": [OBJ_OS_ANIME],
                      "note": "every Kokiri girl (and Fado) shares object_kw1, so all of them change"},
}


def is_oot(game: dict) -> bool:
    t = (game.get("title") or "").lower()
    return "ocarina of time" in t and (game.get("platform") or "") == "n64"


def object_id(name: str) -> int | None:
    """object name -> id (the last entry: object_md has an empty unused duplicate before the real one)."""
    n = name.lower()
    return next((int(k, 16) for k, v in reversed(NAMES["objects"].items()) if v.lower() == n), None)


# ---------------------------------------------------------------- body roles of any skeleton

def guess_roles(P: np.ndarray, parent: list[int], front: float | None = None) -> tuple[dict, dict]:
    """Body roles from joint positions (Y up) and the hierarchy: legs = the two lowest leaf chains, head = the highest
    joint outside them, hip = where legs and head meet, arms = the two side-most remaining chains (left / right by the
    facing: +Z unless told). -> ({role: joint index}, report). Raises ValueError if it isn't
    a humanoid (no two legs / arms)."""
    P = np.asarray(P, float)
    n = len(P)
    kids = [[] for _ in range(n)]
    for i, p in enumerate(parent):
        if p >= 0:
            kids[p].append(i)

    def chain(i):
        out = [i]
        while parent[out[-1]] >= 0:
            out.append(parent[out[-1]])
        return out[::-1]
    H = float(np.ptp(P[:, 1])) or 1.0
    leaves = [i for i in range(n) if not kids[i]]
    order = sorted(leaves, key=lambda i: P[i, 1])
    if len(order) < 4:
        raise ValueError("fewer than 4 limb ends: not a humanoid skeleton")
    l1 = order[0]
    c1 = chain(l1)

    def lca(a, b):
        ca, cb = chain(a), set(chain(b))
        return next(x for x in reversed(ca) if x in cb)
    l2 = next((l for l in order[1:] if P[lca(l1, l) , 1] > max(P[l1, 1], P[l, 1]) + 0.2 * H), None)
    # A skirt can end below both feet. Prefer a low pair on opposite sides
    # of their common ancestor rather than treating the central dress as a leg.
    pairs = []
    for k, a in enumerate(order):
        for b in order[k + 1:]:
            root = lca(a, b)
            xa, xb = P[a, 0] - P[root, 0], P[b, 0] - P[root, 0]
            if (xa * xb < 0 and min(abs(xa), abs(xb)) > 0.02 * H
                    and P[root, 1] > max(P[a, 1], P[b, 1]) + 0.2 * H):
                pairs.append((P[a, 1] + P[b, 1], a, b))
    if pairs:
        _, l1, l2 = min(pairs)
        c1 = chain(l1)
    if l2 is None:
        raise ValueError("no second leg found: not a humanoid skeleton")
    legs_root = lca(l1, l2)
    leg_sets = [set(chain(l)) - set(chain(legs_root)) for l in (l1, l2)]
    used = leg_sets[0] | leg_sets[1]
    rest = [i for i in range(n) if i not in used]
    head = max(rest, key=lambda i: P[i, 1])
    hip = lca(lca(l1, l2), head)
    spine = set(chain(head)) - set(chain(hip)) | {hip}
    under_head = set()
    stack = list(kids[head])
    while stack:
        x = stack.pop()
        under_head.add(x)
        stack += kids[x]
    xc = P[hip, 0]
    cand = [l for l in leaves if l not in used and l not in under_head and l not in spine]
    if front is None:                                   # glTF / gBox's extractors / OoT: models face +Z (toe bones lie:
        front = 1.0                                     # FF7's foot leaves point backwards on some models)
    left_sign = 1.0 if front >= 0 else -1.0                # facing +Z (right-handed, Y up): left is +X
    # arms: the two longest limb chains hanging off the spine (not legs, not under the head); left / right by where
    # they leave the body (the shoulder side), not by the hands - idle arms hang down or cross in front
    groups = {}
    for l in cand:
        ch = [j for j in chain(l) if j not in spine]
        if ch and max(abs(P[j, 0] - xc) for j in ch) >= 0.08 * H:
            length = sum(float(np.linalg.norm(P[ch[k + 1]] - P[ch[k]])) for k in range(len(ch) - 1))
            if ch[0] not in groups or length > groups[ch[0]][0]:
                groups[ch[0]] = (length, l, ch)
    arms = sorted(groups.values(), key=lambda g: -g[0])[:2]
    if len(arms) < 2 or arms[1][0] < 0.15 * H:
        raise ValueError("no two arms found: not a humanoid skeleton")

    def side_x(ch):
        return max((P[j, 0] - xc for j in ch[:3]), key=abs)
    (_l1, a1, c1), (_l2, a2, c2) = arms
    if side_x(c1) * left_sign >= side_x(c2) * left_sign:
        la, ra = a1, a2
    else:
        la, ra = a2, a1
    if np.sign(side_x(c1)) == np.sign(side_x(c2)):
        raise ValueError("both arms on one side: not a humanoid skeleton")
    roles = {"hip": hip, "head": head}
    on_spine = [j for j in chain(head) if j in spine]
    for side, leaf in (("l", la), ("r", ra)):
        arm = [j for j in chain(leaf) if j not in spine]
        k0 = next((k for k, j in enumerate(arm) if abs(P[j, 0] - xc) >= 0.08 * H), len(arm))
        out = arm[k0:]                                      # from the shoulder out (inner joints = clavicle / dummies)
        if len(out) < 2:
            raise ValueError(f"the {side} arm is too short: not a humanoid skeleton")
        roles[f"{side}_upper"], roles[f"{side}_fore"] = out[0], out[1]
        if len(out) > 2:
            roles[f"{side}_hand"] = out[2]
        inner = [j for j in arm if j not in out]
        if inner and inner[-1] != hip:
            roles[f"{side}_clav"] = inner[-1]
    branch = [parent[chain(roles["l_upper"])[k]] for k in range(1)]
    arm_root = lca(la, ra)
    if arm_root in on_spine and arm_root != hip:
        roles["chest"] = arm_root
    elif len(on_spine) > 2:
        roles["chest"] = on_spine[len(on_spine) // 2]
    for leaf, ls in zip((l1, l2), leg_sets):
        leg = [j for j in chain(leaf) if j in ls]
        k = next((m for m in range(len(leg) - 1) if np.linalg.norm(P[leg[m + 1]] - P[leg[m]]) > 0.1 * H), None)
        if k is None or k + 1 >= len(leg):
            raise ValueError("a leg without a thigh / shin: not a humanoid skeleton")
        side = "l" if (P[leg[k], 0] - xc) * left_sign >= 0 else "r"
        roles[f"{side}_thigh"], roles[f"{side}_shin"] = leg[k], leg[k + 1]
        if k + 2 < len(leg):
            roles[f"{side}_foot"] = leg[k + 2]
    if not {"l_thigh", "r_thigh"} <= set(roles):
        raise ValueError("both legs on the same side: not a humanoid skeleton")
    del branch
    return roles, {"front": "+Z" if front >= 0 else "-Z", "height": round(H, 1)}


def topo_roles(skel: dict, P: np.ndarray | None = None) -> dict:
    """Body roles from the limb TREE when the pose-based guess fails (sitting / cranking / hunched NPCs, Moblins): the
    chest is the deepest limb with two limb chains (arms) and another child (the head); the hip is the nearest limb
    above it with two more limb chains (legs) - none for NPCs drawn without legs (robes, counters). Sides from where
    each chain leaves its parent (the limb's own translation, else the pose): +X is the character's left (OoT models
    face +Z). Raises ValueError when no chest with two arms exists."""
    limbs = skel["limbs"]
    n = len(limbs)
    par = OW.parents(skel)
    kids = [[] for _ in range(n)]
    for i, p in enumerate(par):
        if p >= 0:
            kids[p].append(i)

    def sub(i):
        out, st = [], [i]
        while st:
            x = st.pop()
            out.append(x)
            st += kids[x]
        return out

    def depth(i):
        return 1 + max((depth(k) for k in kids[i]), default=0)

    def chain(i):                                       # down the longest child path
        out = [i]
        while kids[out[-1]]:
            out.append(max(kids[out[-1]], key=lambda k: (depth(k), -k)))
        return out

    def limb_like(c):
        return depth(c) >= 2 and len(sub(c)) <= 9
    pos = np.asarray(P, float) if P is not None else None

    def side(c, root):                                  # + = left: the posed chain's mean x (limb offsets can lie
        if pos is not None:                             # along any axis of the parent)
            return float(np.mean([pos[k][0] for k in chain(c)]) - pos[root][0])
        return limbs[c]["pos"][0]

    def pair(node, exclude=()):
        cs = [c for c in kids[node] if limb_like(c) and c not in exclude]
        if len(cs) < 2:
            return None
        cs.sort(key=lambda c: -len(sub(c)))
        a, b = cs[0], cs[1]
        sa, sb = side(a, node), side(b, node)
        if sa * sb >= 0 and abs(sa - sb) < 1:           # both on one side: not a pair
            return None
        return (a, b) if sa > sb else (b, a)
    def legs_above(i):                                  # the nearest ancestor with a pair besides the way up
        a = i
        while par[a] >= 0:
            lg = pair(par[a], exclude=(a,))
            if lg:
                return par[a], lg
            a = par[a]
        return None, None
    chest, best, arms, others, hip, legs = None, None, None, [], None, None
    for i in range(n):                                  # arms with legs below them, then the biggest pair, deepest
        pr = pair(i)
        rest = [c for c in kids[i] if pr and c not in pr]
        if pr and rest:
            h, lg = legs_above(i)
            key = (lg is not None, len(sub(pr[0])) + len(sub(pr[1])), len(chain_to_root(par, i)))
            if best is None or key > best:
                best, chest, arms, others, hip, legs = key, i, pr, rest, h, lg
    if chest is None:
        raise ValueError("no limb with two arm chains and a head: not a humanoid limb tree")
    head = max(others, key=lambda c: (limbs[c]["pos"][1] if pos is None else pos[c][1] - pos[chest][1], -c))
    roles = {"chest": chest, "head": head}
    for sd, c in zip("lr", arms):
        ch = chain(c)
        roles[f"{sd}_upper"], roles[f"{sd}_fore"] = ch[0], ch[1]
        if len(ch) > 2:
            roles[f"{sd}_hand"] = ch[2]
    for sd, c in zip("lr", legs or ()):
        ch = chain(c)
        roles[f"{sd}_thigh"], roles[f"{sd}_shin"] = ch[0], ch[1]
        if len(ch) > 2:
            roles[f"{sd}_foot"] = ch[2]
    roles["hip"] = hip if hip is not None else (par[chest] if par[chest] >= 0 else chest)
    if roles["hip"] == chest:
        del roles["chest"]
    return roles


def chain_to_root(par: list[int], i: int) -> list[int]:
    out = [i]
    while par[out[-1]] >= 0:
        out.append(par[out[-1]])
    return out


def guess_model_roles(model: Path) -> dict:
    """Body roles {role: joint name} for a collection model that has none (FF7 battle models, SA2...)."""
    rig = S.load_rig(Path(model), {})
    roles, _rep = guess_roles(rig["joints"], rig["parent"])
    return {r: rig["names"][j] for r, j in roles.items()}


# ---------------------------------------------------------------- targets

def link_target(rom: OW.Rom, age: str) -> dict:
    L = LINK[age]
    obj = rom.object(L["obj"])
    skel = OW.skeleton(obj, L["skel"])
    if skel["count"] != 21:
        raise ValueError(f"object_link_{'boy' if age == 'adult' else 'child'} has no 21-limb skeleton at {L['skel']:#x} "
                         f"in this ROM ({rom.version})")
    fr = OW.link_frame(rom, IDLE_ANIM)
    if age == "child":                                  # Player_OverrideLimbDrawGameplayCommon: child root x 0.64
        fr[0] = tuple(v * 0.64 for v in fr[0])
    W = OW.pose(skel, fr)
    return target(obj, skel, W, dict(LINK_ROLES), {4: rom.object(OW.OBJECT_GAMEPLAY_KEEP)}) | {"kind": "link", "age": age}


def target(obj: bytes, skel: dict, W: list, roles: dict, segs: dict | None = None) -> dict:
    mesh = OW.object_mesh(obj, skel, W, segs)
    pos = np.concatenate([p["pos"] for p in mesh["prims"]]) if mesh["prims"] else np.array([w[:3, 3] for w in W])
    jj = np.concatenate([p["J"] for p in mesh["prims"]]) if mesh["prims"] else np.zeros(len(pos), int)
    head = pos[jj == roles.get("head", -1)]
    ground = float(pos[:, 1].min())
    height = float(pos[:, 1].max() - ground)
    return {"T": np.array([w[:3, 3] for w in W]), "W": W, "parent": OW.parents(skel), "ground": ground,
            "head_h": float(np.ptp(head[:, 1])) if len(head) else 0.2 * height, "height": height,
            "joints": len(W), "roles": roles, "skel": skel, "triangles": int(len(pos) // 3),
            "dl_limbs": [i for i, lb in enumerate(skel["limbs"]) if any(lb["dls"])]}


# ---------------------------------------------------------------- model -> limb parts

def _dl_owner(tgt: dict) -> np.ndarray:
    """limb -> the limb that draws its vertices (itself, else the nearest ancestor that has a display list)."""
    own = np.arange(tgt["joints"])
    have = set(tgt["dl_limbs"])
    for i in range(tgt["joints"]):
        j = i
        while j >= 0 and j not in have:
            j = tgt["parent"][j]
        own[i] = j if j >= 0 else (tgt["roles"].get("hip") if tgt["roles"].get("hip") in have else min(have))
    return own


def to_parts(prims: list[dict], tgt: dict) -> tuple[dict, list, list]:
    """read_rigged prims (world positions in the target pose, jid per vertex) -> (parts {limb: [(material, ((pos, nrm,
    uv) x3))]} limb-local, materials [{color, tex}], triangles per material)."""
    inv = [np.linalg.inv(w) for w in tgt["W"]]
    own = _dl_owner(tgt)
    mats, key_ix, parts, uses = [], {}, {}, []
    for p in prims:
        tex = p["tex"]
        key = (hash(np.ascontiguousarray(tex).tobytes()) if tex is not None else None, tuple(p["color"][:3]))   # same image = one material
        if key not in key_ix:
            col = np.array(p["color"][:3], float) / 255
            if tex is not None:
                t = S._fill_alpha(np.asarray(tex, np.uint8))
                if (col < 0.999).any():
                    t = t.copy()
                    t[..., :3] = (t[..., :3] * col).astype(np.uint8)
                m = {"color": (255, 255, 255), "tex": t}
            else:
                m = {"color": tuple(int(v) for v in col * 255), "tex": None}
            key_ix[key] = len(mats)
            mats.append(m)
            uses.append(0)
        mi = key_ix[key]
        for t in p["tris"]:
            j = int(own[int(np.bincount(p["jid"][t]).argmax())])
            M = inv[j]
            vs = []
            for i in t:
                q = (M @ np.r_[p["pos"][i], 1.0])[:3]
                nn = M[:3, :3] @ p["nrm"][i]
                vs.append((q, nn / (np.linalg.norm(nn) or 1), tuple(p["uv"][i])))
            parts.setdefault(j, []).append((mi, tuple(vs)))
            uses[mi] += 1
    return parts, mats, uses


def fit_budget(parts: dict, mats: list, uses: list, budget: int) -> tuple[list, dict]:
    """Textures 64x32 -> 8x8 with the least used ones flattened to their mean colour, until the new data fits."""
    from .sm64_writer import fit_tmem
    order = sorted((i for i, m in enumerate(mats) if m["tex"] is not None), key=lambda i: uses[i])
    step = max(1, len(order) // 8)
    tries = [(mt, 0) for mt in TEX_STEPS[:3]]          # smaller textures before flat colours
    tries += [(mt, f) for mt in TEX_STEPS for f in range(step, len(order) + 1, step)] + [(mt, 0) for mt in TEX_STEPS[3:]]
    for mt, flat in tries:
        cur = []
        for i, m in enumerate(mats):
            if m["tex"] is None:
                cur.append(m)
            elif i in order[:flat]:
                c = m["tex"][..., :3].reshape(-1, 3).mean(0).astype(int)
                cur.append({"color": tuple(int(v) for v in c), "tex": None})
            else:
                cur.append({**m, "tex": fit_tmem(m["tex"], mt)})
        blob, _ = OW.encode(parts, cur, 0x06000000)
        if len(blob) <= budget:
            return cur, {"bytes": len(blob), "budget": budget, "max_texels": mt, "textures": len(order) - flat,
                         "flattened": flat}
    blob, _ = OW.encode(parts, [{**m, "tex": None} for m in mats], 0x06000000)
    raise ValueError(f"{sum(len(v) for v in parts.values())} triangles need {len(blob)} bytes even untextured "
                     f"(budget {budget})")


def fit(model: Path, roles: dict, tgt: dict, work: Path, name: str, blender: str | None, budget: int,
        max_tris: int = MAX_TRIS, scale: dict | None = None, props=(), progress=lambda p, m: None) -> dict:
    """Library model -> {parts, mats, rigged (glTF on the target skeleton), report}."""
    from .re4gc_enemies import decimate
    work.mkdir(parents=True, exist_ok=True)
    rig = S.load_rig(Path(model), roles, props)
    if tgt.get("mode") == "rigid":
        prims, rep = rigid_place(rig, tgt)
    else:
        prims, rep = S.retarget(rig, tgt, scale, jmap=tgt["roles"])
    tag = tgt.get("age") or tgt.get("tag") or "npc"
    rigged = S.write_rigged(prims, tgt, work / f"oot_{tag}.gltf", name)
    tris = sum(len(p["tris"]) for p in prims)
    rep["source_triangles"] = tris
    src, last = rigged, None
    for target_tris in (max_tris, int(max_tris * 0.7), int(max_tris * 0.5), int(max_tris * 0.35), int(max_tris * 0.22),
                        int(max_tris * 0.15)):
        if tris > target_tris:
            if not blender:
                raise ValueError(f"{tris} triangles (budget ~{target_tris}) and no Blender on this node to decimate")
            progress(45, f"Decimating {name} -> {target_tris} triangles (Blender)")
            src = decimate(rigged, work / f"dec_{tag}_{target_tris}.glb", float(target_tris), blender)
        rprims = S.read_rigged(src)
        parts, mats, uses = to_parts(rprims, tgt)
        tris = sum(len(v) for v in parts.values())
        try:
            fitted, frep = fit_budget(parts, mats, uses, budget)
            return {"parts": parts, "mats": fitted, "rigged": rigged,
                    "report": rep | frep | {"triangles": tris, "limbs": sorted(int(j) for j in parts)}}
        except ValueError as e:
            last = e
    raise last


# ---------------------------------------------------------------- writing into the ROM

def _code_positions(rom: OW.Rom) -> dict:
    """Where each LINK_ARRAYS table sits in the ORIGINAL `code` (found by content, so any version)."""
    if not hasattr(rom, "_link_tables"):
        code = rom._orig_code if hasattr(rom, "_orig_code") else rom.file(rom.v["code"])
        rom._orig_code = code
        pos = {}
        for name, (_limb, arr) in LINK_ARRAYS.items():
            pat = b"".join(struct.pack(">I", (0x06000000 | a) if a else 0) for a in arr)
            hits, o = [], 0
            while (o := code.find(pat, o)) >= 0:
                if o % 4 == 0:
                    hits.append(o)
                o += 4
            pos[name] = hits
        rom._link_tables = pos
    return rom._link_tables


def link_reclaim(rom: OW.Rom, age: str) -> list[tuple[int, int]]:
    """The biggest run of object_link_boy / _child bytes that only Link's replaced body used (limb and plain-hand
    lists + their vertices; nothing an equipment list, the sheath tables or the player / pause code points into):
    the new model goes there, so Link's object grows by as little as possible (object space is shared per scene)."""
    L = LINK[age]
    ai = 0 if age == "adult" else 1
    obj = rom.object(L["obj"])
    skel = OW.skeleton(obj, L["skel"])
    body = [d for i, lb in enumerate(skel["limbs"]) if i != 19 for d in lb["dls"] if d]
    body += [0x06000000 | LINK_ARRAYS[n][1][ai + k] for n in HAND_TABLES for k in (0, 2)]
    every = {0x06000000 | a for _l, arr in LINK_ARRAYS.values() for a in arr if a}
    mine = {0x06000000 | a for _l, arr in LINK_ARRAYS.values() for k, a in enumerate(arr) if a and k % 2 == ai}
    kept = sorted({0x06000000 | a for arr in KEPT_TABLES for k, a in enumerate(arr) if a and k % 2 == ai} | (mine - set(body)))
    refs = set()
    for i in (rom.v["code"], rom.v["player"], rom.v["kaleido"]):
        refs |= OW.seg6_words(rom._orig_code if i == rom.v["code"] and hasattr(rom, "_orig_code") else rom.file(i))
    keep = {4: rom.object(OW.OBJECT_GAMEPLAY_KEEP)}
    starts = set(body) | {a for d in body for a, _n in OW.run_dl({**keep, 6: obj}, d).get("vtx", [])}
    refs = (refs - every) & starts                       # a code word naming a body list / vertex array elsewhere
    return OW.reclaimable(obj, body, kept, refs, keep)


def write_link(rom: OW.Rom, age: str, parts: dict, mats: list, regions=None) -> dict:
    """Link (adult / child) <- parts: new limb lists, hand / waist / first-person tables in code, equipment lists
    stripped of Link's hands (items kept), boots / gauntlet plates / bracelet blanked."""
    L = LINK[age]
    ai = 0 if age == "adult" else 1
    keep = rom.object(OW.OBJECT_GAMEPLAY_KEEP)
    obj0 = rom.object(L["obj"])
    skel = OW.skeleton(obj0, L["skel"])
    body = set()                                         # Link's own body materials: every limb list + plain hands

    def add_mat(st, ix, here, which):
        body.add(OW.material(st))
    base = [d for i, lb in enumerate(skel["limbs"]) if i != 19 for d in lb["dls"] if d]
    base += [0x06000000 | LINK_ARRAYS[n][1][ai + k] for n in HAND_TABLES for k in (0, 2)]
    for d in base:
        OW.run_dl({6: obj0, 4: keep}, d, add_mat)
    # strip Link's hands out of the equipment lists while the object is still the original (the new model then
    # overwrites the old body's bytes; equipment lists live outside them: oot_writer.reclaimable keeps them)
    objs = bytearray(obj0)
    stripped, todo = {}, []
    for name, (limb, arr) in LINK_ARRAYS.items():
        idx = [ai] if len(arr) == 2 else list(range(ai, len(arr), 2))
        for k in idx:
            d = arr[k]
            if not d or f"{d:#x}" in stripped:
                continue
            removed, kept = OW.strip_body(objs, 0x06000000 | d, body, {4: keep})
            stripped[f"{d:#x}"] = {"removed": removed, "kept": kept}
            todo.append((d, limb, kept))
    new, dls, empty = OW.patch_skeleton(bytes(objs), skel, lambda b, r: OW.encode(parts, mats, b, regions=r), regions)
    obj = bytearray(new)
    mapping = {}
    for d, limb, kept in todo:
        mine = dls.get(limb, empty)
        if kept == 0:
            mapping[d] = mine
        else:                                            # the new hand, then the item (Link's hand triangles removed)
            obj.extend(bytes((-len(obj)) % 8))
            mapping[d] = 0x06000000 + len(obj)
            obj.extend(OW._w(0xDE000000, mine, 0xDE010000, 0x06000000 | d))
    for o in BLANK[age]:
        obj[o:o + 8] = OW.ENDDL
    rom.put_object(L["obj"], bytes(obj))
    pos = _code_positions(rom)
    code_i = rom.v["code"]
    code = bytearray(rom.changed.get(code_i, rom._orig_code))
    patched = 0
    for name, (limb, arr) in LINK_ARRAYS.items():
        idx = [ai] if len(arr) == 2 else list(range(ai, len(arr), 2))
        for o in pos[name]:
            for k in idx:
                if arr[k] in mapping:
                    struct.pack_into(">I", code, o + 4 * k, mapping[arr[k]])
                    patched += 1
    rom.put(code_i, bytes(code))
    missing = [n for n in LINK_ARRAYS if not pos[n]]
    return {"object_bytes": len(obj), "grew": len(obj) - len(obj0), "reused_bytes": sum(b - a for a, b in regions or []),
            "code_entries": patched, "tables_not_found": missing,
            "equipment_lists": len(stripped), "limb_lists": len(dls)}


def write_group(rom: OW.Rom, group: dict, parts: dict, mats: list, regions=None) -> dict:
    """An NPC: the same new data at the same offset in every object of its group (compound actors switch segment 6
    between them per limb), every skeleton of the group pointed at it, constant head lists branched to the new head.
    A single-object NPC reuses its old model's bytes first (regions)."""
    if len(group["objects"]) == 1:
        oid, off = group["skel"]
        obj0 = rom.object(oid)
        new, dls, empty = OW.patch_skeleton(obj0, OW.skeleton(obj0, off),
                                            lambda b, r: OW.encode(parts, mats, b, regions=r), regions)
        obj = bytearray(new)
        for hoid, hoff in group.get("head_dls", []):
            if hoid == oid:
                obj[hoff:hoff + 8] = OW._w(0xDE010000, dls.get(group["head_limb"], empty))
        for boid, boff, limb in group.get("branch_dls", []):      # lists the actor draws in place of a limb's own
            if boid == oid:
                obj[boff:boff + 8] = OW._w(0xDE010000, dls.get(limb, empty))
        rom.put_object(oid, bytes(obj))
        out = {"objects": [f"{oid:#x}"], "object_bytes": {f"{oid:#x}": len(obj)}, "grew": len(obj) - len(obj0),
               "reused_bytes": sum(b - a for a, b in regions or [])}
        for eoid, eoff in group.get("extra_heads", []):            # a head drawn from another object (Fado's): the
            hl = group["head_limb"]                               # new head alone, encoded into that object
            eobj = bytearray(rom.object(eoid))
            eobj.extend(bytes((-len(eobj)) % 16))
            used = sorted({mi for mi, _t in parts.get(hl, [])})
            remap = {mi: k for k, mi in enumerate(used)}
            hparts = {hl: [(remap[mi], t) for mi, t in parts.get(hl, [])]}
            blob, hdls = OW.encode(hparts, [mats[mi] for mi in used], 0x06000000 + len(eobj))
            eobj.extend(blob)
            hempty = 0x06000000 + len(eobj)
            eobj.extend(OW.ENDDL + bytes(8))
            eobj[eoff:eoff + 8] = OW._w(0xDE010000, hdls.get(hl, hempty))
            rom.put_object(eoid, bytes(eobj))
            out["object_bytes"][f"{eoid:#x}"] = len(eobj)
        return out
    objs = {oid: bytearray(rom.object(oid)) for oid in group["objects"]}
    end = (max(len(o) for o in objs.values()) + 15) & ~15
    blob, dls = OW.encode(parts, mats, 0x06000000 + end)
    empty = 0x06000000 + end + len(blob)
    for o in objs.values():
        o.extend(bytes(end - len(o)))
        o.extend(blob + OW.ENDDL + bytes(8))
    for oid, off in group["skels"]:
        sk = OW.skeleton(bytes(objs[oid]), off)
        for i, lb in enumerate(sk["limbs"]):
            if any(lb["dls"]):
                for k in range(len(lb["dls"])):
                    struct.pack_into(">I", objs[oid], lb["at"] + 8 + 4 * k, dls.get(i, empty))
    for oid, off in group.get("head_dls", []):
        objs[oid][off:off + 8] = OW._w(0xDE010000, dls.get(group["head_limb"], empty))
    for oid, o in objs.items():
        rom.put_object(oid, bytes(o))
    return {"objects": [f"{oid:#x}" for oid in objs], "object_bytes": {f"{k:#x}": len(v) for k, v in objs.items()},
            "added": len(blob)}


# ---------------------------------------------------------------- NPC skeletons + poses from the ROM

def find_skeletons(obj: bytes) -> list[int]:
    """Skeleton headers in an object: a segment-6 pointer to a table of `count` limb pointers, then the count."""
    out = []
    for o in range(0, len(obj) - 7, 4):                # a 12-byte header may end the object (object_link_boy)
        w = OW.u32(obj, o)
        cnt = obj[o + 4]
        if w >> 24 != 6 or not 2 <= cnt <= 80 or obj[o + 5:o + 8] != b"\0\0\0":
            continue
        t = w & 0xFFFFFF
        if t + 4 * cnt > len(obj) or t % 4:
            continue
        ptrs = [OW.u32(obj, t + 4 * i) for i in range(cnt)]
        if all(p >> 24 == 6 and (p & 0xFFFFFF) + 12 <= len(obj) for p in ptrs):
            try:
                sk = OW.skeleton(obj, o)
                if all(lb["child"] in (0xFF,) or lb["child"] < cnt for lb in sk["limbs"]):
                    out.append(o)
            except struct.error:
                pass
    return out


def anim_frames(obj: bytes, limbs: int) -> list[list]:
    """Frame 0 of every standard AnimationHeader in an object that drives `limbs` limbs -> [frame]."""
    out = []
    for o in range(0, len(obj) - 16, 4):
        fc, pad, fd, ji, smax = struct.unpack_from(">hhIIH", obj, o)
        if not 0 < fc < 2000 or pad or fd >> 24 != 6 or ji >> 24 != 6:
            continue
        fd, ji = fd & 0xFFFFFF, ji & 0xFFFFFF
        if ji + 6 * (limbs + 1) > len(obj) or fd >= len(obj) or ji <= fd:
            continue
        idx = struct.unpack_from(f">{3 * (limbs + 1)}H", obj, ji)
        n = (ji - fd) // 2
        if max(idx) >= n + 1:
            continue
        data = struct.unpack_from(f">{n}h", obj, fd)
        if max(idx) >= len(data):
            continue
        vals = [data[i] for i in idx]                   # frame 0: static and animated values both start at idx
        out.append([tuple(vals[k:k + 3]) for k in range(0, len(vals), 3)])
    return out


def npc_target(rom: OW.Rom, obj_id: int, skel_off: int, frame: list | None, group: dict | None = None) -> dict:
    obj = rom.object(obj_id)
    skel = OW.skeleton(obj, skel_off)
    frames = [frame] if frame else []
    for oid in [obj_id] + list((group or {}).get("anim_objects", [])):
        frames += anim_frames(rom.object(oid), skel["count"])
    if not frames:
        raise ValueError(f"no pose for {NAMES['objects'].get(hex(obj_id), hex(obj_id))}: no animation in its object "
                         "and no running session to read it from")
    best = None
    down = np.array([0, -1.0, 0])
    for fr in frames[:60]:
        try:
            W = OW.pose(skel, fr)
            P = np.array([w[:3, 3] for w in W])
            roles, rep = guess_roles(P, OW.parents(skel), front=1.0)
        except (ValueError, IndexError):
            continue
        # the most upright standing pose: straight vertical legs, head high above the hip (the live pose wins)
        H = float(np.ptp(P[:, 1])) or 1.0
        legs = 0.0
        for sd in "lr":
            for a, b in ((f"{sd}_thigh", f"{sd}_shin"), (f"{sd}_shin", f"{sd}_foot")):
                if a in roles and b in roles:
                    v = P[roles[b]] - P[roles[a]]
                    legs += float(np.dot(v, down) / (np.linalg.norm(v) or 1))
        score = legs + (P[roles["head"], 1] - P[roles["hip"], 1]) / H + (10 if fr is frame else 0)
        if best is None or score > best[0]:
            best = (score, W, roles, fr is frame)
    if best is None:                                    # no pose shows two arms + two legs: read the limb tree instead
        fr = frame or (frames[0] if frames else None)
        W = OW.pose(skel, fr)
        try:
            best = (0, W, topo_roles(skel, np.array([w[:3, 3] for w in W])), frame is not None)
        except ValueError:
            pass
    if best is None:
        raise ValueError(f"{NAMES['objects'].get(hex(obj_id), hex(obj_id))}'s skeleton ({skel['count']} limbs) isn't "
                         "humanoid (no two arms + two legs): it can't take a character; use characters op=overlay instead")
    _h, W, roles, live = best
    tgt = target(obj, skel, W, roles, {4: rom.object(OW.OBJECT_GAMEPLAY_KEEP)})
    return tgt | {"kind": "npc", "object": obj_id, "pose": "live" if live else "animation"}


def npc_group(rom: OW.Rom, actor: str | None, obj_id: int, skel_off: int | None = None) -> dict:
    """The objects to write for an NPC: a known compound actor's group, else just its own object."""
    if (actor, obj_id) in GROUPS:
        g = dict(GROUPS[(actor, obj_id)])
        g["objects"] = list(g["objects"])
        g["skel"] = next((s for s in g["skels"] if s[0] == obj_id), g["skels"][0])
        return g
    obj = rom.object(obj_id)
    sk = [skel_off] if skel_off is not None else find_skeletons(obj)
    if not sk:
        raise ValueError(f"{NAMES['objects'].get(hex(obj_id), hex(obj_id))} has no skeleton (a static object): "
                         "nothing to retarget onto")
    off = max(sk, key=lambda o: obj[o + 4])
    return {"objects": [obj_id], "skels": [(obj_id, off)], "skel": (obj_id, off)}


# ---------------------------------------------------------------- the mod build

def rom_of(cfg, game: dict) -> tuple[OW.Rom, Path]:
    from .models import CatalogEntry
    from .tools import rom_path
    p = rom_path(CatalogEntry.model_validate(game), cfg)
    return OW.Rom(S.rom_bytes(p)), p


def roles_of(meta: dict, model: Path, root: Path | None = None) -> dict:
    """The entry's body roles; guessed from its skeleton when it has none (and kept in its meta.json, marked
    roles_guessed, so every swap writer can use them)."""
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        roles = guess_model_roles(model)
        if root is not None and (root / meta["slug"] / "meta.json").is_file():
            from . import characters as C
            m = C.get(root, meta["slug"])
            m["rig"] = {**(m.get("rig") or {}), "roles": roles, "roles_guessed": True}
            C.put_meta(root, m)
    return roles


def actor_table(rom: OW.Rom) -> int:
    """gActorOverlayTable in code: 0x20-byte entries {vromStart, vromEnd, vramStart, vramEnd, ...}, the first (Player)
    empty -> its offset."""
    if not hasattr(rom, "_actor_table"):
        code = rom._orig_code if hasattr(rom, "_orig_code") else rom.file(rom.v["code"])
        pairs = {(e[0], e[1]) for e in rom.dma}
        known = {int(k, 16) for k in NAMES["actors"]} - {0}  # actor ids with an overlay (the gaps are ACTOR_UNSET)
        def fits(o):                                    # unset ids are empty, most known ids have an overlay
            hits = 0
            for k in range(1, 200):
                v = struct.unpack_from(">II", code, o + 0x20 * k)
                if v != (0, 0) and v not in pairs:
                    return False
                hits += (v in pairs) == (k in known)
            return hits >= 180
        rom._actor_table = next(o for o in range(0, len(code) - 0x20 * 470, 4) if fits(o))
    return rom._actor_table


def actor_overlay(rom: OW.Rom, actor_id: int) -> bytes | None:
    code = rom._orig_code if hasattr(rom, "_orig_code") else rom.file(rom.v["code"])
    vs, ve = struct.unpack_from(">II", code, actor_table(rom) + 0x20 * actor_id)
    return rom.file(rom.index_of_vrom(vs)) if vs else None


DL_OPS = {0x01, 0xD7, 0xD9, 0xDA, 0xDE, 0xE2, 0xE3, 0xE7, 0xFA, 0xFB, 0xFC, 0xFD}


def npc_reclaim(rom: OW.Rom, group: dict, actor_id: int | None) -> list[tuple[int, int]]:
    """Free bytes of a single-object NPC: its limb lists + vertices, minus lists / arrays its actor's code names."""
    if len(group["objects"]) != 1:
        return []                                        # compound actors need the data at one offset in every object
    oid, off = group["skel"]
    obj = rom.object(oid)
    sk = OW.skeleton(obj, off)
    body = sorted({d for lb in sk["limbs"] for d in lb["dls"] if d})
    words = OW.seg6_words(actor_overlay(rom, actor_id) or b"") if actor_id is not None else set()
    words |= {0x06000000 | o for _oid, o in group.get("head_dls", [])}
    kept = [w for w in words if w % 8 == 0 and (w & 0xFFFFFF) + 8 <= len(obj) and obj[w & 0xFFFFFF] in DL_OPS
            and w not in body]
    keep = {4: rom.object(OW.OBJECT_GAMEPLAY_KEEP)}
    starts = set(body) | {a for d in body for a, _n in OW.run_dl({**keep, 6: obj}, d).get("vtx", [])}
    return OW.reclaimable(obj, body, kept, words & starts, keep)


# ---------------------------------------------------------------- any SkelAnime limb tree (the whole cast)

def rigid_target(rom: OW.Rom, obj_id: int, skel_off: int, group: dict | None = None) -> dict:
    """A skeleton that has no humanoid layout (Skulltula, Octorok, Kaepora Gaebora): posed with the first frame of an
    animation in its object (else its bind layout); the donor rides the limb that draws the most of the body."""
    obj = rom.object(obj_id)
    skel = OW.skeleton(obj, skel_off)
    frames = []
    for oid in [obj_id] + list((group or {}).get("anim_objects", [])):
        frames += anim_frames(rom.object(oid), skel["count"])
    W = OW.pose(skel, frames[0] if frames else None)
    keep = {4: rom.object(OW.OBJECT_GAMEPLAY_KEEP)}
    mesh = OW.object_mesh(obj, skel, W, keep)
    if not mesh["prims"]:
        raise ValueError(f"{NAMES['objects'].get(hex(obj_id), hex(obj_id))}: the skeleton draws nothing")
    jj = np.concatenate([p["J"] for p in mesh["prims"]])
    body = int(np.bincount(jj).argmax())
    tgt = target(obj, skel, W, {"hip": body}, keep)
    return tgt | {"kind": "npc", "object": obj_id, "mode": "rigid", "rigid_limb": body,
                  "pose": "animation" if frames else "bind"}


def rigid_place(rig: dict, tgt: dict) -> tuple[list[dict], dict]:
    """The donor whole and upright (its own facing: left +X, up +Y, front +Z), scaled to the target's height, standing
    on its ground under the body limb, every vertex on that limb (moves with the body, no limb animation)."""
    B = S.facing(rig)
    allp = np.concatenate([p["pos"] for p in rig["prims"]]) @ B.T
    lo, hi = allp.min(0), allp.max(0)
    s = float(tgt["height"]) / max(float(hi[1] - lo[1]), 1e-9)
    body = int(tgt["rigid_limb"])
    at = np.asarray(tgt["W"][body])[:3, 3]
    src = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    dst = np.array([at[0], tgt["ground"], at[2]])
    out = []
    for p in rig["prims"]:
        n = len(p["pos"])
        J = np.zeros((n, 4), np.int64)
        J[:, 0] = body
        Wv = np.zeros((n, 4))
        Wv[:, 0] = 1
        out.append({"pos": (p["pos"] @ B.T - src) * s + dst, "nrm": p["nrm"] @ B.T, "uv": p["uv"], "tris": p["tris"],
                    "J": J, "W": Wv, "tex": p["tex"], "color": p["color"], "wrap": p.get("wrap", (10497, 10497)),
                    "name": f"m{len(out)}", "prop": bool(p.get("prop"))})
    flipped = S._orient(out)
    return out, {"mode": "rigid", "scale": round(s, 4), "limb": body, "normals_flipped": flipped}


def slot_target(rom: OW.Rom, spec: dict) -> dict:
    """A cast slot (gbox.oot_cast.slot_spec) -> the fit target: Link's roles on Link-shaped skeletons (Dark Link),
    the guessed humanoid roles on any other SkelAnime limb tree (retarget: every limb keeps its animation), else the
    rigid ride on the body limb. Raises ValueError only when the skeleton draws nothing."""
    oid, off = spec["group"]["skel"]
    keep = {4: rom.object(OW.OBJECT_GAMEPLAY_KEEP)}
    if spec.get("shape") == "creature":                 # wings / legs / leaves are no arms: never a humanoid fit
        return rigid_target(rom, oid, off, spec["group"]) | {"why_rigid": "a creature"}
    if spec.get("roles_hint") == "link":
        obj = rom.object(oid)
        skel = OW.skeleton(obj, off)
        if skel["count"] == 21:
            W = OW.pose(skel, OW.link_frame(rom, IDLE_ANIM))
            return target(obj, skel, W, dict(LINK_ROLES), keep) | {"kind": "npc", "object": oid, "mode": "retarget",
                                                                     "pose": "Link idle"}
    try:
        return npc_target(rom, oid, off, spec.get("frame"), spec["group"]) | {"mode": "retarget"}
    except ValueError as e:
        why = str(e)
    return rigid_target(rom, oid, off, spec["group"]) | {"why_rigid": why.split(":")[0]}


def build(cfg, game: dict, jobs: list[dict], progress=lambda p, m: None, placements: list | None = None) -> dict:
    """jobs: [{"target": {"kind": "link", "ages": (...)} | {"kind": "npc", "actor", "actor_id", "object", "skel",
    "frame", "name"}, "meta": library entry, "model": path}] -> {rom bytes, report}. Every model goes first into the
    bytes of the model it replaces (reclaimable), then the object grows by at most the GROWTH allowance."""
    from . import characters as C
    rom, rom_file = rom_of(cfg, game)
    blender = C._blender(cfg)
    report = {"version": rom.version, "targets": []}
    for k, job in enumerate(jobs):
        meta, tg = job["meta"], job["target"]
        model = Path(job["model"])
        roles = roles_of(meta, model, C.library_root(cfg))
        props = [p["node"] for p in meta.get("props") or []]
        scale = (meta.get("rig") or {}).get("scale")
        work = Path(cfg.cache) / "characters_build" / meta["slug"] / "oot"
        shutil.rmtree(work, ignore_errors=True)
        if tg["kind"] == "link":
            for age in tg.get("ages", ("adult", "child")):
                progress(10 + 30 * k // len(jobs), f"Retargeting {meta['name']} onto {LINK[age]['name']}")
                tgt = link_target(rom, age)
                regions = link_reclaim(rom, age)
                budget = int(sum(b - a for a, b in regions) * 0.85) + GROWTH["link"]
                f = fit(model, roles, tgt, work, meta["name"], blender, budget, scale=scale, props=props, progress=progress)
                w = write_link(rom, age, f["parts"], f["mats"], regions)
                report["targets"].append({"target": LINK[age]["name"], "character": meta["name"], **f["report"], **w,
                                          "rigged": str(f["rigged"])})
        else:
            group = npc_group(rom, tg.get("actor"), tg["object"], tg.get("skel"))
            oid, off = group["skel"]
            tgt = npc_target(rom, oid, off, tg.get("frame"), group)
            regions = npc_reclaim(rom, group, tg.get("actor_id"))
            budget = int(sum(b - a for a, b in regions) * 0.85) + GROWTH["npc"] // len(group["objects"])
            progress(10 + 30 * k // len(jobs), f"Retargeting {meta['name']} onto {tg.get('name') or hex(oid)}")
            f = fit(model, roles, tgt, work, meta["name"], blender, budget, scale=scale, props=props, progress=progress)
            w = write_group(rom, group, f["parts"], f["mats"], regions)
            report["targets"].append({"target": tg.get("name") or NAMES["objects"].get(hex(oid)), "character": meta["name"],
                                      "pose": tgt["pose"], "roles": {r: int(j) for r, j in tgt["roles"].items()},
                                      **f["report"], **w, "note": group.get("note", ""), "rigged": str(f["rigged"])})
    if placements:
        from . import oot_place
        report["placements"] = oot_place.write_rom(cfg, rom, placements, progress)
    progress(80, "Rebuilding the ROM (DMA table, CRC)")
    out = rom.build()
    check = OW.Rom(out)                                   # read it back: the new objects load through the new DMA table
    for job in jobs:
        tg = job["target"]
        for age in (tg.get("ages", ("adult", "child")) if tg["kind"] == "link" else ()):
            sk = OW.skeleton(check.object(LINK[age]["obj"]), LINK[age]["skel"])
            assert sk["count"] == 21 and sk["dlcount"] == 18, "Link's skeleton changed"
    report["rom_bytes"] = len(out)
    return {"rom": out, "report": report, "rom_file": rom_file}


def image_name(rom_file: Path) -> str:
    """The mod image keeps the game's own name: RetroArch names save files after the content, so the operator's save
    is shared between the plain game and every OoT mod."""
    return Path(rom_file).stem + ".z64"


def write_mod(cfg, game: dict, name: str, built: dict, extra: dict) -> Path:
    from . import filemods
    gid = game["game_id"]
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    img = image_name(built["rom_file"])
    (d / img).write_bytes(built["rom"])
    mj = {"name": name, "game_id": gid, "image": img, "files": ["@image: OoT models (gbox.oot_swap)"], "built": time.time(),
          **extra}
    (d / ".gbox-mod.json").write_text(json.dumps(mj, default=str))
    return d


# ---------------------------------------------------------------- the whole cast in one ROM (characters op=cast_swap)

def cast_slots(game: dict | None = None) -> list[dict]:
    """The cast menu / whole-cast swap slots (gbox.oot_cast.CAST measured on the owned ROM)."""
    from . import oot_cast
    return oot_cast.cast_slots(game)


def _fit_into(rom: OW.Rom, objects: list[int], allow: int, reclaim: int, attempt, slack: int = 0x200) -> tuple:
    """Run attempt(budget) -> (fit, write report) until the written objects grew by at most `allow` (+ slack for the
    empty list and alignment): the first budget assumes the free regions pack at 85 %, every retry takes off what it
    overshot. Staged writes of a failed try are rolled back. -> (fit, write report, {object: grew})."""
    before = {o: len(rom.object(o)) for o in objects}
    budget = int(reclaim * 0.85) + allow
    last = None
    for _ in range(4):
        saved = dict(rom.changed)
        try:
            f, w = attempt(budget)
        except ValueError as e:
            rom.changed = saved
            raise ValueError(f"the model doesn't fit: {e} - the old model frees {reclaim // 1024} KB and its rooms' "
                             f"object space lets the object grow {allow // 1024} KB") from None
        grew = {o: len(rom.object(o)) - before[o] for o in objects}
        over = max(grew.values()) - allow - slack
        if over <= 0:
            return f, w, grew
        rom.changed = saved
        last = over
        budget -= over + 0x400
        if budget <= 0x800:
            break
    raise ValueError(f"the model doesn't fit: {last} bytes over what the object may grow here ({allow // 1024} KB "
                     "left in its rooms' object space)")


def build_cast(cfg, game: dict, pairs: list[tuple[str, dict]], name: str, progress=lambda p, m: None,
               root: Path | None = None, rom_data: bytes | None = None, strict_cutscenes: bool = False) -> dict:
    """The whole-cast build: [(cast slot, collection entry)] -> ONE patched ROM (one gBox file mod `name`).
    Each slot's object is rebuilt in turn on the previous slots' output: retargeted onto the slot's own skeleton
    (humanoid roles; Link's roles on Dark Link; the rigid ride for the rest), the old model's lists / vertices /
    textures reused first, then the object grows within what every room that loads it leaves free (gbox.oot_cast
    growth_plan: Kokiri Forest's NPCs share ~130 KB). Grown objects get a fresh VROM range, the DMA table and
    gObjectTable follow, the CRC is fixed (oot_writer.Rom.build). A slot that can't be rebuilt is reported with the
    reason and the rest still build. -> {"mod", "slots": {slot: {status, reason?, mode, ...}}, "detail"}."""
    from . import characters as C, oot_cast as OC
    if rom_data is None:
        rom, rom_file = rom_of(cfg, game)
    else:
        rom, rom_file = OW.Rom(rom_data), Path(f"{game.get('title') or 'oot'}.z64")
    root = Path(root) if root is not None else C.library_root(cfg)
    blender = C._blender(cfg)
    per: dict[str, dict] = {}
    specs = {}
    for slot, meta in pairs:
        try:
            specs[slot] = OC.slot_spec(rom, slot)
        except (ValueError, LookupError) as e:
            per[slot] = {"status": "failed", "reason": str(e)}
    caps: dict[int, int] = {}
    share: dict[int, int] = {}
    for slot, sp in specs.items():
        objs = list(OC.LINK_OBJECTS.values()) if sp["kind"] == "link" else sp["objects"]
        for o in objs:
            caps[o] = OC.GROWTH_CAP["link" if sp["kind"] == "link" else "npc"]
            share[o] = share.get(o, 0) + 1
    plan = OC.growth_plan(rom, caps, cutscenes=strict_cutscenes)
    allow = plan["allow"]
    grown: dict[int, int] = {}
    built = []
    for k, (slot, meta) in enumerate(pairs):
        if slot not in specs:
            continue
        progress(5 + 70 * k // max(1, len(pairs)), f"{meta['name']} -> {specs[slot]['name']} ({k + 1}/{len(pairs)})")
        model = root / meta["slug"] / meta["model"]
        work = Path(cfg.cache) / "characters_build" / "cast" / name / slot
        saved = dict(rom.changed)
        try:
            roles = roles_of(meta, model, root)
            props = [p["node"] for p in meta.get("props") or []]
            scale = (meta.get("rig") or {}).get("scale")
            sp = OC.slot_spec(rom, slot) if specs[slot]["kind"] == "npc" else specs[slot]   # on the previous slots' output
            row = {"status": "built", "character": meta["slug"]}
            if sp["kind"] == "link":
                for age in sp["ages"]:
                    o = LINK[age]["obj"]
                    tgt = link_target(rom, age)
                    regions = link_reclaim(rom, age)
                    rec = sum(b - a for a, b in regions)

                    def attempt(budget, age=age, tgt=tgt, regions=regions):
                        f = fit(model, roles, tgt, work, meta["name"], blender, budget, scale=scale, props=props)
                        return f, write_link(rom, age, f["parts"], f["mats"], regions)
                    f, w, g = _fit_into(rom, [o], allow.get(o, 0) // share.get(o, 1), rec, attempt)
                    grown[o] = grown.get(o, 0) + g[o]
                    row[age] = {"triangles": f["report"]["triangles"], "grew": g[o], "code_entries": w["code_entries"]}
                row["mode"] = "retarget (Link's roles)"
            else:
                tgt = slot_target(rom, sp) | {"tag": slot}
                objs = sp["objects"]
                room = min(allow.get(o, 0) // share.get(o, 1) for o in objs)
                rec = sum(b - a for a, b in sp["regions"])

                def attempt(budget, sp=sp, tgt=tgt):
                    f = fit(model, roles, tgt, work, meta["name"], blender, budget, scale=scale, props=props)
                    return f, write_group(rom, sp["group"], f["parts"], f["mats"], sp["regions"])
                f, w, g = _fit_into(rom, objs, room, rec, attempt)
                for o in objs:
                    grown[o] = grown.get(o, 0) + g[o]
                row |= {"mode": tgt["mode"], "triangles": f["report"]["triangles"], "grew": max(g.values()),
                        "reused": rec, "pose": tgt.get("pose"), "textures": f["report"].get("textures"),
                        "branched_lists": len(sp["group"].get("branch_dls", []))}
                if tgt["mode"] == "rigid":
                    row["note"] = (f"{sp['name']} isn't humanoid ({tgt.get('why_rigid', 'no two arms and two legs')}): "
                                   "the character rides its body limb whole (moves with it, no limb animation)")
            per[slot] = row
            built.append(slot)
        except Exception as e:                            # noqa: BLE001 - one slot never stops the cast
            rom.changed = saved
            per[slot] = {"status": "failed", "reason": str(e)[:500] or type(e).__name__}
    if not built:
        return {"mod": None, "slots": per, "detail": {"growth": plan}}
    over = OC.space_report(rom, grown)
    progress(80, "Rebuilding the ROM (DMA table, object table, CRC)")
    out = rom.build()
    check, orig = OW.Rom(out), OW.Rom(rom.data)
    assert struct.unpack_from(">II", out, 0x10) == OW.crc6105(out), "CRC"
    for slot in built:
        sp = specs[slot]
        for o, off in ([(LINK[a]["obj"], LINK[a]["skel"]) for a in sp["ages"]] if sp["kind"] == "link"
                       else [sp["group"]["skel"]]):
            sk = OW.skeleton(check.object(o), off)
            assert sk["count"] == OW.skeleton(orig.object(o), off)["count"], f"{slot}: skeleton changed"
            bad = OC.check_object(check.object(o), off, {4: check.object(OW.OBJECT_GAMEPLAY_KEEP)})
            if bad:
                raise RuntimeError(f"{slot}: the rebuilt {NAMES['objects'].get(hex(o), hex(o))} reads outside "
                                   f"itself: {bad[0]}")
    hard = [r for r in over if not r["cutscene"]]
    soft = sorted({(r["scene"], r["layer"]) for r in over if r["cutscene"]})
    detail = {"version": rom.version, "rom_bytes": len(out), "growth": plan,
              "grew": {NAMES["objects"].get(hex(o), hex(o)): n for o, n in grown.items()}, "over_budget_rooms": hard,
              "cutscenes_over_budget": [f"{s} (cutscene layer {lay})" for s, lay in soft]}
    if hard:
        detail["warning"] = (f"{len(hard)} rooms end up over the object space; the first: {hard[0]['scene']} room "
                             f"{hard[0]['room']} (layer {hard[0]['layer']}) by {hard[0]['over'] // 1024 + 1} KB")
    elif soft:
        detail["warning"] = (f"{len(soft)} cutscene layers load more grown characters than their object space holds "
                             f"(the game may crash there; e.g. {soft[0][0]} layer {soft[0][1]}); rebuild with "
                             "strict_cutscenes to fit those too (smaller models)")
    rec = [{"slot": s, "character": per[s]["character"], **{k: v for k, v in per[s].items() if k != "character"}}
           for s in built]
    write_mod(cfg, game, name, {"rom": out, "rom_file": rom_file},
              {"writer": "gbox.oot_swap (cast)", "cast_build": rec, "detail": detail})
    return {"mod": name, "slots": per, "detail": detail}


def mod_name(jobs_desc: list[str]) -> str:
    return "oot_" + "_".join(re.sub(r"[^a-z0-9]+", "", s.lower()) for s in jobs_desc)[:60]


# ---------------------------------------------------------------- who is who (names, points, actors)

NPCS = {                                               # spoken name -> (actor, object); everything else: NAMES
    "saria": ("En_Sa", "object_sa"), "mido": ("En_Md", "object_md"), "kokiri boy": ("En_Ko", "object_km1"),
    "kokiri kid": ("En_Ko", "object_km1"), "kokiri": ("En_Ko", "object_km1"), "know it all brother": ("En_Ko", "object_km1"),
    "kokiri girl": ("En_Ko", "object_kw1"), "fado": ("En_Ko", "object_kw1"), "malon": ("En_Ma1", "object_ma1"),
    "adult malon": ("En_Ma2", "object_ma2"), "talon": ("En_Ta", "object_ta"), "ingo": ("En_In", "object_in"),
    "zelda": ("En_Zl4", "object_zl4"), "sheik": ("En_Xc", "object_xc"), "ruto": ("En_Ru1", "object_ru1"),
    "kaepora gaebora": ("En_Owl", "object_owl"), "owl": ("En_Owl", "object_owl"), "dog": ("En_Dog", "object_dog"),
}
LINK_WORDS = {"link", "player", "me", "myself", "hero", "young link", "child link", "adult link", "you"}


def actor_object(rom: OW.Rom, actor_id: int) -> int | None:
    """The object an actor's profile names (ActorProfile.objectId at +8 of its init data in the overlay)."""
    code = rom._orig_code if hasattr(rom, "_orig_code") else rom.file(rom.v["code"])
    vs, _ve, vram, _vend, _ram, init = struct.unpack_from(">IIIIII", code, actor_table(rom) + 0x20 * actor_id)
    if not vs or not init:
        return None
    ov = rom.file(rom.index_of_vrom(vs))
    o = init - vram
    return struct.unpack_from(">h", ov, o + 8)[0] if 0 <= o < len(ov) - 12 else None


def _api_job(ctx, sid: str, op: str, **kw) -> dict:
    from . import characters as C
    j = C._job(ctx, "oot_models", {"session_id": sid, "op": op, **kw}, sid.split("-")[0], 300)
    if j.get("state") != "succeeded":
        raise RuntimeError(f"oot_models {op} on the session {j.get('state')}: {j.get('error')}")
    return (j.get("output") or {}).get("result") or {}


def _point(spec: str) -> tuple[float, float] | None:
    m = re.fullmatch(r"\s*[\(\[]?\s*([0-9.]+)\s*%?\s*[, ]\s*([0-9.]+)\s*%?\s*[\)\]]?\s*", spec or "")
    if not m:
        return None
    x, y = float(m.group(1)), float(m.group(2))
    if x > 1 or y > 1:                                  # percentages
        x, y = x / 100, y / 100
    return x, y


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower().replace("'", "")).split())


def resolve(ctx, rom: OW.Rom, sid: str | None, spec: str = "", x: float | None = None, y: float | None = None) -> dict:
    """A thing in the game -> target: {"kind": "link", "ages": (...)} | {"kind": "npc", "actor", "actor_id", "object",
    "skel", "frame", "name"}. spec: "link" / "me" | "x,y" (picture fractions) | an NPC ("Saria", "kokiri boy") | an
    actor or object name (En_Sa, object_sa). With a session, points and present actors use the live game (pose)."""
    pt = (x, y) if x is not None and y is not None else _point(spec)
    live = None
    if pt and sid:
        live = _api_job(ctx, sid, "pick", x=pt[0], y=pt[1])
        a = live.get("actor")
        if not a:
            raise LookupError(f"nothing that gBox can swap at ({pt[0]:.2f}, {pt[1]:.2f}) of the picture (no character "
                              "drawn there)")
        if a["category"] == "player":
            return {"kind": "link", "ages": (live["where"]["age"],), "name": f"Link ({live['where']['age']})"}
        return _npc_from_live(rom, a, live.get("skeleton"))
    if pt:
        raise ValueError("a picture point needs the session_id of the running game")
    n = _norm(spec)
    if not n or n in LINK_WORDS or n.endswith(" link"):
        ages = ("child",) if "child" in n or "young" in n else ("adult",) if "adult" in n else ("adult", "child")
        if len(ages) == 2 and sid:                      # Link as he is right now (the age his model is taken from)
            try:
                age = _api_job(ctx, sid, "where")["age"]
                ages = (age, "adult" if age == "child" else "child")
            except RuntimeError:
                pass
        return {"kind": "link", "ages": ages, "name": "Link"}
    actor, obj = NPCS.get(n, (None, None))
    if actor is None:
        for k, v in NAMES["actors"].items():
            if _norm(v) == n or _norm(v).replace(" ", "") == n.replace(" ", ""):
                actor = v
        for k, v in NAMES["objects"].items():
            if _norm(v) == n or _norm(v) == "object " + n:
                obj = v
    if actor is None and obj is None:
        raise LookupError(f"don't know {spec!r} in Ocarina of Time: name an NPC (Saria, Mido, a Kokiri boy / girl, Malon, "
                          "Talon, Zelda, ...), an actor / object name (En_Sa, object_sa), or point at it on the picture")
    want_obj = object_id(obj) if obj else None
    if sid and actor:
        try:
            acts = [a for a in _api_job(ctx, sid, "actors").get("actors", []) if a["name"] == actor and
                    (want_obj is None or a.get("object") == want_obj)]
            if acts:
                r = _api_job(ctx, sid, "skeleton", actor=hex(acts[0]["addr"]))
                if r.get("actor"):
                    return _npc_from_live(rom, r["actor"], r.get("skeleton"))
        except RuntimeError:
            pass
    aid = next((int(k, 16) for k, v in NAMES["actors"].items() if v == actor), None)
    oid = object_id(obj) if obj else (actor_object(rom, aid) if aid is not None else None)
    if oid is None:
        raise LookupError(f"no object for {spec!r}")
    return {"kind": "npc", "actor": actor, "actor_id": aid, "object": oid, "skel": None, "frame": None,
            "name": NAMES["objects"].get(hex(oid), hex(oid)) if not actor else f"{actor} ({NAMES['objects'].get(hex(oid))})"}


def _npc_from_live(rom: OW.Rom, a: dict, sk: dict | None) -> dict:
    oid = a.get("object")
    if oid is None or oid <= 1:
        raise LookupError(f"{a['name']} draws from {a.get('object_name') or 'gameplay_keep'} (shared by everything): "
                          "not a character gBox can replace")
    obj = rom.object(oid)
    off = None
    if sk:
        tbl = sk["skeleton"] & 0xFFFFFF
        off = next((o for o in find_skeletons(obj) if OW.u32(obj, o) & 0xFFFFFF == tbl), None)
    if off is None and not find_skeletons(obj):
        raise LookupError(f"{a['name']} ({a.get('object_name')}) has no skeleton: a static object, nothing to swap a "
                          "character onto (op=overlay can still draw one over it)")
    return {"kind": "npc", "actor": a["name"], "actor_id": a["id"], "object": oid, "skel": off,
            "frame": [tuple(v) for v in sk["frame"]] if sk else None, "name": f"{a['name']} ({a.get('object_name')})"}


# ---------------------------------------------------------------- extraction (game -> collection)

def extract_target(rom: OW.Rom, tg: dict, out: Path, name: str) -> dict:
    """A Link age or an NPC -> skinned glTF (limbs l00.., the target's pose) + body roles. -> {path, roles, triangles}."""
    keep = {4: rom.object(OW.OBJECT_GAMEPLAY_KEEP)}
    if tg["kind"] == "link":
        age = tg["ages"][0]
        tgt = link_target(rom, age)
        obj = rom.object(LINK[age]["obj"])
        hints = {8: obj[LINK[age]["eyes"]:], 9: obj[LINK[age]["mouth"]:]}
        mesh = OW.object_mesh(obj, tgt["skel"], tgt["W"], keep, hints, init={"env": TUNIC})   # Kokiri tunic (env)
        roles = dict(LINK_ROLES)
    else:
        group = npc_group(rom, tg.get("actor"), tg["object"], tg.get("skel"))
        oid, off = group["skel"]
        tgt = npc_target(rom, oid, off, tg.get("frame"), group)
        obj = rom.object(oid)
        mesh = OW.object_mesh(obj, tgt["skel"], tgt["W"], keep)
        roles = tgt["roles"]
    if not mesh["prims"]:
        raise ValueError(f"{name}: the skeleton draws nothing")
    path = OW.write_gltf(mesh, tgt["skel"], tgt["W"], out, name)
    tris = sum(len(p["tris"]) for p in mesh["prims"])
    return {"path": path, "roles": {r: f"l{int(j):02d}" for r, j in roles.items()}, "triangles": tris}


def extracted_slug(tg: dict) -> str:
    if tg["kind"] == "link":
        return f"oot_link_{tg['ages'][0]}"
    return "oot_" + re.sub(r"^object_", "", NAMES["objects"].get(hex(tg["object"]), f"obj{tg['object']:x}"))


def extract(ctx, game: dict, tg: dict, root: Path, force: bool = False) -> dict:
    """The thing into the collection (or the entry that's already there)."""
    from . import characters as C
    slug = extracted_slug(tg)
    if (root / slug / "meta.json").is_file() and not force:
        return {"status": "in_collection", "entry": C.get(root, slug)}
    rom, _p = rom_of(ctx.config, game)
    pretty = {"oot_link_adult": "Link (adult, OoT)", "oot_link_child": "Young Link (OoT)"}.get(slug)
    if not pretty:
        who = next((k.title() for k, v in NPCS.items() if v[1] == NAMES["objects"].get(hex(tg["object"]))), None)
        pretty = f"{who or tg.get('actor') or slug} (OoT)"
    work = Path(ctx.config.cache) / "characters_build" / "extract" / slug
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    ctx.progress(30, f"Reading {pretty} from the ROM (skeleton, display lists, textures)")
    r = extract_target(rom, tg, work / f"{slug}.gltf", pretty)
    aliases = [pretty.replace(" (OoT)", "")] + ([k.title() for k, v in NPCS.items()
                                                 if tg["kind"] == "npc" and v[1] == NAMES["objects"].get(hex(tg["object"]))])
    meta = C.add(root, slug, pretty, [r["path"]],
                 {"game_title": game["title"], "game_id": game["game_id"], "platform": "n64",
                  "files": [NAMES["objects"].get(hex(LINK[tg["ages"][0]]["obj"] if tg["kind"] == "link" else tg["object"]))]},
                 "gbox.oot_swap (object skeleton + F3DEX2 lists)", rig={"roles": r["roles"]}, aliases=aliases,
                 notes=f"{r['triangles']} triangles; limbs l00.. = the game's own limbs (pose: "
                       f"{'idle animation' if tg['kind'] == 'link' else 'as seen in the game' if tg.get('frame') else 'an animation in its object'})",
                 extra={"native_player": tg["kind"] == "link"})
    shutil.rmtree(work, ignore_errors=True)
    return {"status": "extracted", "entry": meta}


# ---------------------------------------------------------------- characters op=use / swap / place

def _session_mod(ctx, sid: str | None, gid: str) -> dict:
    """The OoT mod the session runs (its jobs: what replaces whom), or {}."""
    from . import characters as C, filemods
    if not sid:
        return {}
    s = C._session(ctx, sid) or {}
    m = s.get("mod") or ""
    if not m.startswith("oot_"):
        return {}
    p = filemods.mod_dir(ctx.config, gid, m) / ".gbox-mod.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _key(tg: dict) -> str:
    return "link" if tg["kind"] == "link" else f"obj{tg['object']:x}"


def run_jobs(ctx, game: dict, new_jobs: list[dict], sid: str | None, launch: bool = True) -> dict:
    """Merge with what the session's mod already does (the same target is replaced), build, write, record, launch."""
    from . import characters as C, oot_place
    gid = game["game_id"]
    root = C.library_root(ctx.config)
    prev = _session_mod(ctx, sid, gid).get("jobs", [])
    keys = {_key(j["target"]) for j in new_jobs}
    jobs = [j for j in prev if _key(j["target"]) not in keys] + new_jobs
    full = []
    for j in jobs:
        meta = C.get(root, j["character"])
        tg = dict(j["target"])
        if tg["kind"] == "link":                          # Link: always both ages (the operator may change age)
            tg["ages"] = ("adult", "child")
        full.append({"target": tg, "meta": meta, "model": root / meta["slug"] / meta["model"]})
    places = oot_place.load(ctx.config, gid)
    built = build(ctx.config, game, full, ctx.progress, places)
    desc = [j["meta"]["slug"] + ("" if j["target"]["kind"] == "link" else "-" + _key(j["target"])) for j in full]
    name = mod_name(desc) if desc else "oot_world"
    rec = [{"target": {k: v for k, v in j["target"].items() if k != "frame"} | ({"frame": j["target"].get("frame")}
                                                                                  if j["target"].get("frame") else {}),
            "character": j["meta"]["slug"]} for j in full]
    write_mod(ctx.config, game, name, built, {"jobs": rec, "placements": len(places), "report": built["report"]})
    for j, t in zip(full, built["report"]["targets"]):
        try:
            C._api(ctx, "POST", f"/api/characters/{j['meta']['slug']}/targets",
                   json={"game_id": gid, "slot": "player" if j["target"]["kind"] == "link" else j["target"].get("name"),
                         "mod": name, "nodes": [C.HOST_OS],
                         "notes": f"OoT {t['target']}: {t['triangles']} triangles, {t.get('textures', 0)} textures "
                                  f"<= {t.get('max_texels')} texels; object +{t.get('grew', 0) // 1024} KB"})
        except Exception:                                # noqa: BLE001 - the record is a convenience
            pass
    keep = ("target", "character", "triangles", "source_triangles", "textures", "max_texels", "flattened", "bytes", "grew",
            "reused_bytes", "pose", "note", "equipment_lists", "tables_not_found")
    summary = {"version": built["report"]["version"], "rom_bytes": built["report"]["rom_bytes"],
               "targets": [{k: t[k] for k in keep if k in t} for t in built["report"]["targets"]],
               "placements": built["report"].get("placements")}
    res = {"mod": name, "build": summary, "jobs": [f"{j['meta']['name']} -> {j['target'].get('name') or 'Link'}" for j in full]}
    if not launch:
        return res | {"status": "built"}
    node = sid.split("-")[0] if sid else C.HOST_OS
    ctx.progress(90, f"Launching Ocarina of Time with mod {name}")
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    from .sm64_swap import _wait
    lj = _wait(ctx, lj, 600)
    ok = lj.get("state") == "succeeded"
    return res | {"status": "built+launched" if ok else f"built, launch {lj.get('state')}",
                  "launch": {"job": lj.get("id"), "state": lj.get("state"), "node": node,
                             "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")},
                  "message": (f"Ocarina of Time restarted with {', '.join(res['jobs'])} (mod {name}). It uses the same save "
                              "file as the plain game: load your file. Already launched: don't launch it again." if ok
                              else f"Mod {name} is built but the launch {lj.get('state')}: {lj.get('error')}")}


def _on_control_plane(ctx, inp) -> dict | None:
    """Builds need the collection: on another node, run the same request on the control plane (no launch), then
    launch here."""
    from . import characters as C
    if C.library_root(ctx.config).is_dir():
        return None
    cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux" and w.get("online")), None)
    j = C._job(ctx, "characters", inp.model_dump() | {"launch": False}, cp, 1800)
    r = (j.get("output") or {}).get("result") or {}
    if j.get("state") != "succeeded" or not r.get("mod"):
        return {"status": "failed", "error": r.get("error") or r.get("message") or j.get("error") or r}
    if inp.launch:
        r |= {"launch": C._launch(ctx, inp_game_id(inp, r), r["mod"], (inp.session_id or "").split("-")[0] or C.HOST_OS)}
    return r


def inp_game_id(inp, r: dict) -> str:
    return r.get("game_id") or inp.game_id


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for OoT: the library character replaces Link (default; both ages), or whoever is at x,y on the
    picture / the NPC named in slot."""
    if (r := _on_control_plane(ctx, inp)) is not None:
        return r
    rom, _p = rom_of(ctx.config, game)
    spec = "" if (inp.slot or "player") == "player" else inp.slot
    tg = resolve(ctx, rom, inp.session_id or None, spec, inp.x, inp.y)
    tgt_name = tg.get("name") or "Link"
    ctx.progress(5, f"{meta['name']} -> {tgt_name}")
    res = run_jobs(ctx, game, [{"target": tg, "character": meta["slug"]}], inp.session_id or None, inp.launch)
    return res | {"replaces": tgt_name, "game_id": game["game_id"]}


def swap(ctx, game: dict, inp) -> dict:
    """characters op=swap a=<who> b=<who> [one_way]: B's model on A (and A's on B unless one_way = "play as B").
    Each side is extracted from the ROM into the collection first if it isn't there."""
    from . import characters as C
    if (r := _on_control_plane(ctx, inp)) is not None:
        return r
    root = C.library_root(ctx.config)
    rom, _p = rom_of(ctx.config, game)
    sid = inp.session_id or None
    ta = resolve(ctx, rom, sid, inp.a or "link")
    tb = resolve(ctx, rom, sid, inp.b)
    ea, eb = extract(ctx, game, ta, root), extract(ctx, game, tb, root)
    jobs = [{"target": ta, "character": eb["entry"]["slug"]}]
    if not inp.one_way:
        jobs.append({"target": tb, "character": ea["entry"]["slug"]})
    res = run_jobs(ctx, game, jobs, sid, inp.launch)
    what = (f"{ta.get('name')} now looks like {tb.get('name')}" + ("" if inp.one_way else f" and {tb.get('name')} like {ta.get('name')}"))
    return res | {"swap": what, "extracted": [ea["status"], eb["status"]], "game_id": game["game_id"]}



def extract_cmd(ctx, game: dict, inp, root: Path) -> dict:
    """characters op=extract for OoT: by picture point (x, y + session), or by name (Link, Saria, a Kokiri girl,
    En_Sa, object_sa)."""
    rom, _p = rom_of(ctx.config, game)
    tg = resolve(ctx, rom, inp.session_id or None, inp.character, inp.x, inp.y)
    r = extract(ctx, game, tg, root)
    return {"status": r["status"], "route": "dedicated:oot", "entry": r["entry"], "target": tg.get("name")}


def tool(ctx, inp, meta: dict | None) -> dict | None:
    """The OoT side of the `characters` tool (use / swap / place / unplace). None = not an OoT game."""
    from . import characters as C
    game = C._game(ctx, inp)
    if not is_oot(game):
        return None
    out = {"game": game["title"], "game_id": game["game_id"]}
    try:
        if inp.op == "swap":
            if not inp.b:
                raise ValueError("swap needs b = who to take the looks of (a picture point 'x,y' or a name); a defaults to Link")
            return out | swap(ctx, game, inp)
        if inp.op == "use":
            return out | {"character": meta["name"], "slug": meta["slug"]} | use(ctx, meta, game, inp)
        from . import oot_place
        if inp.op == "place":
            return out | oot_place.place(ctx, meta, game, inp)
        if inp.op == "unplace":
            return out | oot_place.unplace(ctx, game, inp)
    except LookupError as e:
        return out | {"status": "not_found", "message": str(e),
                      "hint": "characters op=overlay draws a collection character over any spot of the picture instead"}
    except ValueError as e:
        return out | {"status": "cannot", "message": str(e),
                      "hint": "characters op=overlay draws a collection character over any spot of the picture instead"}
    return None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rom")
    ap.add_argument("character", help="library entry folder (meta.json + model)")
    ap.add_argument("out")
    ap.add_argument("--age", default="adult,child")
    a = ap.parse_args()
    cdir = Path(a.character)
    meta = json.loads((cdir / "meta.json").read_text())
    rom = OW.Rom(S.rom_bytes(a.rom))
    roles = roles_of(meta, cdir / meta["model"])
    od = Path(a.out)
    for age in a.age.split(","):
        tgt = link_target(rom, age)
        regions = link_reclaim(rom, age)
        f = fit(cdir / meta["model"], roles, tgt, od, meta["name"], S._blender(),
                int(sum(b - a for a, b in regions) * 0.85) + GROWTH["link"],
                scale=(meta.get("rig") or {}).get("scale"), props=[p["node"] for p in meta.get("props") or []],
                progress=lambda p, m: print(f"{p:3.0f}% {m}"))
        w = write_link(rom, age, f["parts"], f["mats"], regions)
        print(age, json.dumps({**f["report"], **w}, default=str))
        from .characters import render_preview
        render_preview(f["rigged"], od / f"preview_{age}.png")
    (od / "oot_test.z64").write_bytes(rom.build())
