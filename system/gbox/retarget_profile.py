"""Retarget profiles: the operator's own adjustments to how a donor character is fitted into one game (the Retarget
editor pop-up, clients/web/viz/retarget-editor.js).

A profile is stored per (donor character, target game[, slot]) in the character's meta.json:

    meta["retarget_profiles"][game_id][slot | "*"] = {
        "roles":  {role: donor bone name | ""},      # "specify what is what": which donor bone is which body role
                                                     #   ("" removes a role the automatic mapping guessed wrong)
        "height": 1.0,                               # whole figure, about the ground under the hip
        "ground": 0.0,                               # lift (+) / sink (-), a fraction of the target figure height
        "head": 1.0,                                 # head size, about the head joint
        "torso_width": 1.0,                          # torso x scale about the body centre; the limbs ride along
        "arm_length": 1.0, "leg_length": 1.0,        # every arm / leg segment along its bone
        "adjust": {role: {"length": 1, "girth": 1, "scale": [1, 1, 1], "offset": [0, 0, 0], "rotate": [0, 0, 0]}},
    }

"*" is the game-wide profile; a slot with its own (complete) profile uses that instead. Offsets are fractions of the target
figure height (game units differ: Mario's skeleton is ~100 units tall, DOA2's ~1.7), rotations are degrees (XYZ).

Writers apply a profile in two places:
  1. before fitting: apply_to_meta() returns the meta with the role overrides merged into rig.roles and the profile
     in rig.scale["profile"]; every writer already passes rig.roles to load_rig and rig.scale to retarget.
  2. after the automatic fit, in target space: the shared retargets (sm64_swap.retarget - used by SM64, OoT, PE1/2,
     FF7, SA2/JGR/PSO through ninja_swap, SmackDown! 2, No Mercy/WCW, Def Jam - doa2_weighted_retarget.retarget and
     re4gc_enemies.retarget) call apply_jmap()/apply_roles() on their output. Crazy Taxi's principal-axis fit scales
     its parts with part_transform().

The adjustment maths is pure numpy on prims ({pos, nrm, J, W}) and is tested on synthetic skeletons
(tests/test_retarget_profile.py); clients/web/viz/retarget-handles.js mirrors it for the editor's live preview.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math

import numpy as np

ROLES = ["hip", "chest", "neck", "head", "l_clav", "r_clav", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore",
         "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"]       # = sm64_swap.ORDER
TORSO = {"hip", "chest", "neck", "l_clav", "r_clav"}
ARMS = {"l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand"}
LEGS = {"l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"}
CHILD = {"hip": "chest", "chest": "neck", "neck": "head", "l_clav": "l_upper", "r_clav": "r_upper",
         "l_upper": "l_fore", "l_fore": "l_hand", "r_upper": "r_fore", "r_fore": "r_hand",
         "l_thigh": "l_shin", "l_shin": "l_foot", "r_thigh": "r_shin", "r_shin": "r_foot"}
PARENT = {c: p for p, c in CHILD.items()}
ROOT = {r: ("l_upper" if r in ARMS and r[0] == "l" else "r_upper" if r in ARMS else
            "l_thigh" if r[0] == "l" else "r_thigh") for r in ARMS | LEGS}
SCALE_RANGE = (0.25, 4.0)
DEFAULT = {"roles": {}, "height": 1.0, "ground": 0.0, "head": 1.0, "torso_width": 1.0, "arm_length": 1.0,
           "leg_length": 1.0, "adjust": {}}
ADJUST_DEFAULT = {"length": 1.0, "girth": 1.0, "scale": [1.0, 1.0, 1.0], "offset": [0.0, 0.0, 0.0],
                  "rotate": [0.0, 0.0, 0.0]}


# ---------------------------------------------------------------- the profile itself

def _num(v, default, lo, hi):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return float(min(hi, max(lo, f)))


def _vec(v, default, lo, hi):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return list(default)
    return [_num(x, d, lo, hi) for x, d in zip(v, default)]


def normalize(profile: dict | None) -> dict:
    """A clean profile: known keys only, numbers clamped to sane ranges, unknown roles dropped. Raises ValueError for
    something that is not a profile at all."""
    if profile is None:
        return copy.deepcopy(DEFAULT)
    if not isinstance(profile, dict):
        raise ValueError("a retarget profile is a JSON object")
    out = copy.deepcopy(DEFAULT)
    roles = profile.get("roles") or {}
    if not isinstance(roles, dict):
        raise ValueError("profile.roles maps a body role to a donor bone name")
    for role, bone in roles.items():
        if role not in ROLES:
            raise ValueError(f"unknown body role {role!r} (roles: {', '.join(ROLES)})")
        if bone is not None and not isinstance(bone, str):
            raise ValueError(f"profile.roles.{role} must be a bone name or empty")
        out["roles"][role] = (bone or "").strip()[:128]
    out["height"] = _num(profile.get("height"), 1.0, *SCALE_RANGE)
    out["ground"] = _num(profile.get("ground"), 0.0, -0.5, 0.5)
    out["head"] = _num(profile.get("head"), 1.0, *SCALE_RANGE)
    out["torso_width"] = _num(profile.get("torso_width"), 1.0, *SCALE_RANGE)
    out["arm_length"] = _num(profile.get("arm_length"), 1.0, *SCALE_RANGE)
    out["leg_length"] = _num(profile.get("leg_length"), 1.0, *SCALE_RANGE)
    adjust = profile.get("adjust") or {}
    if not isinstance(adjust, dict):
        raise ValueError("profile.adjust maps a body role to its adjustment")
    for role, a in adjust.items():
        if role not in ROLES:
            raise ValueError(f"unknown body role {role!r} in profile.adjust")
        a = a if isinstance(a, dict) else {}
        clean = {"length": _num(a.get("length"), 1.0, *SCALE_RANGE), "girth": _num(a.get("girth"), 1.0, *SCALE_RANGE),
                 "scale": _vec(a.get("scale"), [1.0] * 3, *SCALE_RANGE),
                 "offset": _vec(a.get("offset"), [0.0] * 3, -1.0, 1.0),
                 "rotate": _vec(a.get("rotate"), [0.0] * 3, -180.0, 180.0)}
        if clean != ADJUST_DEFAULT:
            out["adjust"][role] = clean
    for k in ("notes", "updated", "by"):
        if isinstance(profile.get(k), (str, int, float)):
            out[k] = profile[k] if not isinstance(profile[k], str) else profile[k][:500]
    return out


def is_identity(profile: dict | None) -> bool:
    """True when the profile changes nothing about the fitted geometry (role overrides aside)."""
    if not profile:
        return True
    p = normalize(profile)
    return (not p["adjust"] and all(p[k] == DEFAULT[k] for k in ("height", "ground", "head", "torso_width",
                                                                 "arm_length", "leg_length")))


def digest(profile: dict | None) -> str:
    """A short stable hash of what a profile changes (cache keys: a changed profile rebuilds the mod)."""
    if not profile:
        return ""
    p = {k: v for k, v in normalize(profile).items() if k not in ("notes", "updated", "by")}
    if is_identity(p) and not p["roles"]:
        return ""
    return hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()[:12]


def slot_key(slot: str | None) -> str:
    """'fighter:Kasumi:all' -> 'fighter:kasumi'; '' / 'all' / '*' -> '*' (the game-wide profile)."""
    s = str(slot or "").strip().casefold()
    if s.endswith(":all"):
        s = s[:-4]
    return s if s and s not in ("*", "all", "roster", "cast") else "*"


def stored(meta: dict, game_id: str) -> dict:
    """{slot key: raw profile} stored for one game."""
    return dict(((meta or {}).get("retarget_profiles") or {}).get(game_id) or {})


def resolve(meta: dict, game_ids, slot: str | None = None) -> dict | None:
    """The profile for this donor in this game, or None when the operator never made one: the slot's own profile when
    it has one (a complete profile: the editor starts it from the game-wide one), else the game-wide "*" profile.
    game_ids: one id or several (a writer serving a game's regional releases)."""
    ids = [game_ids] if isinstance(game_ids, str) else list(game_ids or [])
    profiles = (meta or {}).get("retarget_profiles") or {}
    for gid in ids:
        entry = profiles.get(gid)
        if not entry:
            continue
        key = slot_key(slot)
        game_wide, own = entry.get("*"), entry.get(key) if key != "*" else None
        if own is None and key != "*":                      # 'fighter:kasumi' also matches a profile saved as 'kasumi'
            own = entry.get(key.split(":", 1)[-1])
        if game_wide is None and own is None:
            continue
        return normalize(own if own is not None else game_wide)
    return None


def apply_to_meta(meta: dict, game_ids, slot: str | None = None) -> dict:
    """The meta a writer should fit with: role overrides merged into rig.roles, the profile in rig.scale['profile'].
    Returns meta unchanged (the same object) when there is no profile, so builds without one are byte-identical."""
    prof = resolve(meta, game_ids, slot)
    if prof is None:
        return meta
    out = copy.deepcopy(meta)
    rig = out.setdefault("rig", {})
    roles = dict(rig.get("roles") or {})
    for role, bone in prof["roles"].items():
        if bone:
            for other, b in list(roles.items()):            # a bone keeps one role: the operator's assignment wins
                if b == bone and other != role:
                    roles.pop(other)
            roles[role] = bone
        else:
            roles.pop(role, None)
    rig["roles"] = roles
    if not is_identity(prof):
        rig["scale"] = dict(rig.get("scale") or {}) | {"profile": prof}
    out["retarget_profile_digest"] = digest(prof)
    return out


def profile_of(scale) -> dict | None:
    """The profile a writer passed through rig.scale (None when there is none or it changes nothing)."""
    p = (scale or {}).get("profile") if isinstance(scale, dict) else None
    return None if not p or is_identity(p) else normalize(p)


# ---------------------------------------------------------------- the maths (target space, +Y up)

def _euler(deg) -> np.ndarray:
    x, y, z = (math.radians(float(a)) for a in deg)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def _axis(role: str, pos: dict) -> np.ndarray:
    """The bone direction of a role: towards its child joint, else continuing from its parent, else +Y."""
    p = pos[role]
    if CHILD.get(role) in pos:
        d = pos[CHILD[role]] - p
    elif PARENT.get(role) in pos:
        d = p - pos[PARENT[role]]
    else:
        d = np.array([0.0, 1.0, 0.0])
    n = float(np.linalg.norm(d))
    return d / n if n > 1e-9 else np.array([0.0, 1.0, 0.0])


def frame(role_pos: dict, ground: float | None = None) -> dict:
    """Reference points of the target figure: centre (hip x/z), ground y and figure height H (head over ground)."""
    pos = {r: np.asarray(v, float) for r, v in role_pos.items()}
    pts = np.array(list(pos.values())) if pos else np.zeros((1, 3))
    centre = pos.get("hip", pts.mean(0))
    g = float(ground) if ground is not None else float(pts[:, 1].min())
    top = pos["head"][1] if "head" in pos else float(pts[:, 1].max())
    return {"centre": centre, "ground": g, "H": max(float(top - g), 1e-6)}


def role_transforms(role_pos: dict, profile: dict, ground: float | None = None) -> tuple[dict, tuple]:
    """{role: (A 3x3, t 3)} with x' = A x + t for every role that has a target position, plus the transform used
    for vertices on joints without a role (the torso family: torso width + global height/ground)."""
    prof = normalize(profile)
    pos = {r: np.asarray(v, float) for r, v in role_pos.items() if r in ROLES}
    f = frame(pos, ground)
    c, H = f["centre"], f["H"]
    gpt = np.array([c[0], f["ground"], c[2]])
    k, lift = prof["height"], prof["ground"] * H
    G = np.eye(3) * k                                        # global: x -> gpt + k (x - gpt) + lift
    g_t = gpt - k * gpt + np.array([0.0, lift, 0.0])
    tw = prof["torso_width"]
    Wx = np.diag([tw, 1.0, 1.0])                            # torso width about the centre's x
    w_t = np.array([c[0] - tw * c[0], 0.0, 0.0])

    def compose(A, t):                                      # global after (A, t)
        return G @ A, G @ t + g_t

    out = {}
    for role, p in pos.items():
        a = prof["adjust"].get(role, ADJUST_DEFAULT)
        length = a["length"] * (prof["arm_length"] if role in ARMS else prof["leg_length"] if role in LEGS else 1.0)
        girth = a["girth"]
        d = _axis(role, pos)
        L = girth * np.eye(3) + (length - girth) * np.outer(d, d)
        S = np.diag(a["scale"])
        if role == "head":
            S = S * prof["head"]
        M = _euler(a["rotate"]) @ L @ S
        t = p - M @ p + np.asarray(a["offset"], float) * H   # about the role's own joint, then moved
        if role in TORSO:
            M, t = Wx @ M, Wx @ t + w_t
        else:                                               # limbs / head ride along with their root joint's x shift
            root = pos.get(ROOT.get(role, role), p)
            t = t + np.array([(tw - 1.0) * (root[0] - c[0]), 0.0, 0.0])
        out[role] = compose(M, t)
    return out, compose(Wx, w_t)


def apply_roles(prims: list[dict], role_pos: dict, joint_role: dict, profile: dict | None,
                ground: float | None = None) -> tuple[list[dict], dict]:
    """Apply a profile to fitted prims. role_pos: {role: target joint position}; joint_role: {native joint index:
    role} for the indices in prims' J. Each vertex blends its influences' role transforms by weight (single-weight
    prims just take their joint's). Returns (new prims, report); prims are returned as they were when the profile
    changes nothing."""
    prof = profile_of({"profile": profile}) if profile else None
    if prof is None:
        return prims, {"applied": False}
    tr, other = role_transforms(role_pos, prof, ground)
    nj = 1 + max([int(np.max(np.asarray(p["J"]))) for p in prims if len(np.asarray(p.get("J", [])))] + [0]
                 + [int(j) for j in joint_role])
    A = np.repeat(other[0][None], nj, 0)
    T = np.repeat(other[1][None], nj, 0)
    for j, role in joint_role.items():
        if role in tr and 0 <= int(j) < nj:
            A[int(j)], T[int(j)] = tr[role]
    Ainv_t = np.linalg.inv(A).transpose(0, 2, 1)
    out, shift = [], 0.0
    for p in prims:
        P, N = np.asarray(p["pos"], float), np.asarray(p.get("nrm", np.zeros_like(p["pos"])), float)
        J = np.asarray(p["J"], int)
        if J.ndim == 1:
            J = J[:, None]
        W = np.asarray(p["W"], float) if "W" in p else np.zeros(J.shape)
        if W.shape != J.shape:
            W = np.zeros(J.shape)
        if "W" not in p or not np.any(W):
            W = np.zeros(J.shape)
            W[:, 0] = 1.0
        tot = W.sum(1, keepdims=True)
        W = np.where(tot > 1e-12, W / np.maximum(tot, 1e-12), np.eye(J.shape[1])[0][None])
        newP = np.einsum("nk,nkij,nj->ni", W, A[J], P) + np.einsum("nk,nki->ni", W, T[J])
        newN = np.einsum("nk,nkij,nj->ni", W, Ainv_t[J], N)
        newN /= np.maximum(np.linalg.norm(newN, axis=1, keepdims=True), 1e-12)
        if len(P):
            shift = max(shift, float(np.abs(newP - P).max()))
        out.append({**p, "pos": newP, "nrm": newN})
    f = frame(role_pos, ground)
    return out, {"applied": True, "height": prof["height"], "ground": prof["ground"], "head": prof["head"],
                 "torso_width": prof["torso_width"], "arm_length": prof["arm_length"],
                 "leg_length": prof["leg_length"], "roles_adjusted": sorted(prof["adjust"]),
                 "max_shift": round(shift / f["H"], 4)}


def apply_jmap(prims: list[dict], T, jmap: dict, profile: dict | None, ground: float | None = None):
    """apply_roles for retargets that hold the target as joint positions T[index] and a {role: index} map."""
    if not profile:
        return prims, {"applied": False}
    T = np.asarray(T, float)
    role_pos = {r: T[j] for r, j in jmap.items() if r in ROLES and isinstance(j, (int, np.integer)) and 0 <= j < len(T)}
    joint_role = {}
    for role in ROLES:                                      # a joint keeps its first role (sm64_swap.ORDER)
        j = jmap.get(role)
        if isinstance(j, (int, np.integer)) and int(j) not in joint_role:
            joint_role[int(j)] = role
    return apply_roles(prims, role_pos, joint_role, profile, ground)


def part_transform(role: str | None, role_pos: dict, profile: dict | None, ground: float | None = None):
    """(A, t) for a rigid part that belongs to one role (Crazy Taxi's per-part fit), identity without a profile."""
    prof = profile_of({"profile": profile}) if profile else None
    if prof is None:
        return np.eye(3), np.zeros(3)
    tr, other = role_transforms(role_pos, prof, ground)
    return tr.get(role, other) if role else other
