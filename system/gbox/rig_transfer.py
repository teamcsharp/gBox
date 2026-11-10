"""Universal rig-transfer core (request #9533, stages 1-2).

Shared by every model writer: canonical humanoid joint map (donor -> canonical -> target), proportional
fit, static checks (normals/winding, head seat, stretch), per-donor/per-target corrections stored as data
(``<data>/mercs/rig_fixes/<donor>__<target>.json``) and a parser that turns a coaching note naming a rig
problem into a correction request. Pure Python; no game files, no I/O except the rig_fixes JSON.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Iterable, Sequence

CANONICAL_JOINTS = (
    "root", "pelvis", "spine", "chest", "neck", "head",
    "l_shoulder", "l_upper_arm", "l_forearm", "l_hand",
    "r_shoulder", "r_upper_arm", "r_forearm", "r_hand",
    "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot",
)
LIMBS = {  # canonical limb -> (start joint, end joint)
    "l_arm": ("l_upper_arm", "l_hand"), "r_arm": ("r_upper_arm", "r_hand"),
    "l_leg": ("l_thigh", "l_foot"), "r_leg": ("r_thigh", "r_foot"),
    "torso": ("pelvis", "neck"), "head": ("neck", "head"),
}
# name fragments (separators stripped, lower-case) -> canonical joint; first match wins.
_ALIASES = (
    ("pelvis", "pelvis"), ("hips", "pelvis"), ("hip", "pelvis"), ("root", "root"),
    ("spine2", "chest"), ("chest", "chest"), ("spine1", "spine"), ("spine", "spine"),
    ("neck", "neck"), ("head", "head"),
    ("clavicle", "shoulder"), ("shoulder", "shoulder"),
    ("upperarm", "upper_arm"), ("forearm", "forearm"), ("lowerarm", "forearm"),
    ("hand", "hand"), ("thigh", "thigh"), ("upleg", "thigh"), ("upperleg", "thigh"),
    ("calf", "shin"), ("shin", "shin"), ("lowerleg", "shin"), ("foot", "foot"),
)
_SIDED = {"shoulder", "upper_arm", "forearm", "hand", "thigh", "shin", "foot"}


def _side(name: str) -> str | None:
    low = name.lower()
    if "left" in low or re.match(r"^l[_.\-]", low) or re.search(r"[_.\-]l([_.\-]|$)", low):
        return "l"
    if "right" in low or re.match(r"^r[_.\-]", low) or re.search(r"[_.\-]r([_.\-]|$)", low):
        return "r"
    return None


def canonical_name(joint: str) -> str | None:
    """Best-effort canonical joint for a donor/target joint name; None when it names nothing humanoid."""
    flat = re.sub(r"[^a-z0-9]", "", joint.lower())
    for frag, canon in _ALIASES:
        if frag in flat:
            if canon in _SIDED:
                side = _side(joint)
                return f"{side}_{canon}" if side else None
            return canon
    return None


def build_joint_map(names: Iterable[str]) -> dict[str, str]:
    """canonical -> joint name (first claim wins; deterministic by input order)."""
    out: dict[str, str] = {}
    for n in names:
        c = canonical_name(n)
        if c and c not in out:
            out[c] = n
    return out


def map_donor_to_target(donor_joints: Iterable[str], target_joints: Iterable[str]) -> dict[str, str]:
    """donor joint -> target joint through the canonical skeleton; unmatched donor joints are omitted."""
    d, t = build_joint_map(donor_joints), build_joint_map(target_joints)
    return {d[c]: t[c] for c in CANONICAL_JOINTS if c in d and c in t}


def limb_lengths(pos: dict[str, Sequence[float]]) -> dict[str, float]:
    """Limb lengths from canonical-joint positions (rest pose). Missing joints skip the limb."""
    return {k: math.dist(pos[a], pos[b]) for k, (a, b) in LIMBS.items() if a in pos and b in pos}


def proportional_fit(donor: dict[str, Sequence[float]], target: dict[str, Sequence[float]]) -> dict[str, float]:
    """Per-limb scale target/donor plus overall foot->head height ratio (Z-up)."""
    dl, tl = limb_lengths(donor), limb_lengths(target)
    scales = {k: (tl[k] / dl[k] if dl[k] > 1e-9 else 1.0) for k in dl if k in tl}
    if all(k in p for p in (donor, target) for k in ("head", "l_foot")):
        dh = abs(donor["head"][2] - donor["l_foot"][2])
        th = abs(target["head"][2] - target["l_foot"][2])
        if dh > 1e-9:
            scales["height"] = th / dh
    return scales


# ---- static checks -------------------------------------------------------------------------------------
def check_normals(verts: Sequence[Sequence[float]], faces: Sequence[Sequence[int]],
                  normals: Sequence[Sequence[float]] | None = None) -> dict:
    """Flag inverted winding (faces point toward the centroid) and vertex normals disagreeing with winding.
    Star-convex heuristic for a single body part; not a verdict for strongly concave meshes."""
    if not faces:
        return {"flag": False, "inward_fraction": 0.0, "normal_disagree_fraction": None, "faces": 0}
    n = len(verts)
    c = [sum(v[i] for v in verts) / n for i in range(3)]
    inward = disagree = 0
    for f in faces:
        a, b, d = (verts[i] for i in f[:3])
        u = [b[i] - a[i] for i in range(3)]
        w = [d[i] - a[i] for i in range(3)]
        fn = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        mid = [(a[i] + b[i] + d[i]) / 3 - c[i] for i in range(3)]
        if sum(fn[i] * mid[i] for i in range(3)) < 0:
            inward += 1
        if normals is not None:
            vn = [sum(normals[i][k] for i in f[:3]) for k in range(3)]
            if sum(fn[k] * vn[k] for k in range(3)) < 0:
                disagree += 1
    nf = len(faces)
    dis = (disagree / nf) if normals is not None else None
    res = {"faces": nf, "inward_fraction": inward / nf, "normal_disagree_fraction": dis}
    res["flag"] = res["inward_fraction"] > 0.5 or bool(dis and dis > 0.5)
    return res


def check_head_seat(pos: dict[str, Sequence[float]], lo: float = 0.12, hi: float = 0.20) -> dict:
    """neck->head length as fraction of foot->head height (Z-up); below lo or head at/below shoulders = sunk."""
    if not all(k in pos for k in ("neck", "head", "l_foot")):
        return {"flag": None, "reason": "not determined: neck/head/foot joints missing"}
    height = abs(pos["head"][2] - pos["l_foot"][2]) or 1e-9
    ratio = abs(pos["head"][2] - pos["neck"][2]) / height
    sunk = "l_shoulder" in pos and pos["head"][2] <= pos["l_shoulder"][2]
    return {"flag": ratio < lo or ratio > hi or sunk, "ratio": ratio, "head_below_shoulders": sunk}


def check_stretch(fit: dict[str, float], tol: float = 0.25) -> dict:
    """Limb scale deviating from the overall height ratio by more than tol (relative)."""
    h = fit.get("height")
    if h is None:
        return {"flag": None, "reason": "not determined: height ratio unavailable"}
    bad = {k: v / h for k, v in fit.items() if k != "height" and abs(v / h - 1) > tol}
    return {"flag": bool(bad), "limbs": bad}


# ---- corrections as data -------------------------------------------------------------------------------
def fixes_path(root: Path, donor: str, target: str) -> Path:
    def safe(s: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", s)
    return Path(root) / "mercs" / "rig_fixes" / f"{safe(donor)}__{safe(target)}.json"


def empty_fixes(donor: str, target: str) -> dict:
    return {"version": 1, "donor": donor, "target": target, "joint_offsets": {}, "part_flips": [],
            "scales": {}, "history": []}


def load_fixes(root: Path, donor: str, target: str) -> dict:
    p = fixes_path(root, donor, target)
    if p.exists():
        return {**empty_fixes(donor, target), **json.loads(p.read_text())}
    return empty_fixes(donor, target)


def save_fixes(root: Path, fixes: dict) -> Path:
    p = fixes_path(root, fixes["donor"], fixes["target"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(fixes, indent=1, sort_keys=True))
    tmp.replace(p)
    return p


def apply_fixes(positions: dict[str, Sequence[float]], fixes: dict) -> dict[str, list[float]]:
    """Joint positions with offsets applied, then limb scales about the limb start joint."""
    out = {k: list(v) for k, v in positions.items()}
    for j, off in fixes.get("joint_offsets", {}).items():
        if j in out:
            out[j] = [out[j][i] + off[i] for i in range(3)]
    for limb, s in fixes.get("scales", {}).items():
        if limb in LIMBS:
            a, b = LIMBS[limb]
            if a in out and b in out:
                out[b] = [out[a][i] + (out[b][i] - out[a][i]) * s for i in range(3)]
    return out


# ---- critique -> correction ----------------------------------------------------------------------------
_RULES = (
    (r"normals?\b.*\b(invert|flip|backward|wrong|reverse)|\b(invert|flip)\w*\b.*normals?|inside[- ]out|see[- ]through",
     "flip_normals"),
    (r"head\b.*\b(shov|sunk|sink|too low|down|into|buried)|no neck|neck.*(missing|short)", "raise_head"),
    (r"head\b.*\b(too high|floating|up too|raised)|neck.*too long", "lower_head"),
    (r"\b(arms?|legs?|limbs?)\b.*\b(stretch|long|elongat|spaghetti)", "shrink_limb"),
    (r"\b(arms?|legs?|limbs?)\b.*\b(short|stubby|tiny)", "grow_limb"),
    (r"float|hover|above the ground|off the ground", "lower_model"),
    (r"too (big|large|tall|huge)|giant", "scale_down"),
    (r"too (small|short|tiny)", "scale_up"),
)
HEAD_STEP = 0.03   # model-height fraction per critique
LIMB_STEP = 0.10
SCALE_STEP = 0.10


def parse_critique(note: str) -> list[dict]:
    """Coaching note -> ordered correction requests [{action, part?}]. Empty when no rig problem is named."""
    low = note.lower()
    out, seen = [], set()
    for pat, action in _RULES:
        if action in seen or not re.search(pat, low):
            continue
        seen.add(action)
        req: dict = {"action": action}
        if action in ("shrink_limb", "grow_limb"):
            m = re.search(r"\b(arms?|legs?)\b", low)
            req["part"] = ["l_leg", "r_leg"] if m and m.group(1).startswith("leg") else ["l_arm", "r_arm"]
        out.append(req)
    return out


def apply_correction(fixes: dict, req: dict, note: str = "") -> dict:
    """Mutate+return fixes for one correction request and record it in history."""
    a = req["action"]
    if a == "flip_normals":
        for p in req.get("part") or ["*"]:
            if p in fixes["part_flips"]:
                fixes["part_flips"].remove(p)  # a second "inverted" note undoes the flip
            else:
                fixes["part_flips"].append(p)
    elif a in ("raise_head", "lower_head"):
        off = fixes["joint_offsets"].setdefault("head", [0.0, 0.0, 0.0])
        off[2] = round(off[2] + (HEAD_STEP if a == "raise_head" else -HEAD_STEP), 6)
    elif a in ("shrink_limb", "grow_limb"):
        f = (1 - LIMB_STEP) if a == "shrink_limb" else (1 + LIMB_STEP)
        for limb in req.get("part", []):
            fixes["scales"][limb] = round(fixes["scales"].get(limb, 1.0) * f, 6)
    elif a in ("scale_down", "scale_up"):
        f = (1 - SCALE_STEP) if a == "scale_down" else (1 + SCALE_STEP)
        fixes["scales"]["all"] = round(fixes["scales"].get("all", 1.0) * f, 6)
    elif a == "lower_model":
        off = fixes["joint_offsets"].setdefault("root", [0.0, 0.0, 0.0])
        off[2] = round(off[2] - HEAD_STEP, 6)
    else:
        raise ValueError(f"unknown correction {a!r}")
    fixes["history"].append({"action": a, "note": note[:200], "ts": time.time()})
    return fixes


def critique_to_fixes(root: Path, donor: str, target: str, note: str) -> dict:
    """Parse a coaching note, apply to the donor/target rig_fixes file, persist. Reply-ready summary."""
    reqs = parse_critique(note)
    if not reqs:
        return {"applied": [], "rebuild": False, "path": None}
    fixes = load_fixes(root, donor, target)
    for r in reqs:
        apply_correction(fixes, r, note)
    p = save_fixes(root, fixes)
    return {"applied": reqs, "rebuild": True, "path": str(p), "fixes": fixes}


# ---- coach-note hook -------------------------------------------------------------------------------------
def session_donor_target(session: dict) -> tuple[str, str] | None:
    """(donor, target) named by a session's build manifest, or None when it names none.
    Accepts session['build_manifest'] / ['manifest'] / the session itself with donor + slot/target keys."""
    for m in (session.get("build_manifest"), session.get("manifest"), session):
        if not isinstance(m, dict):
            continue
        donor = m.get("donor") or m.get("donor_slug")
        target = m.get("target") or m.get("slot") or m.get("game_id") or session.get("game_id")
        if donor and target:
            return str(donor), str(target)
    return None


def coach_reply(root: Path, session: dict, note: str) -> dict | None:
    """Coach-note entry point: None when the note names no rig problem or the session names no donor; otherwise
    {donor, target, applied, rebuild, path, reply} with the reply text for the note."""
    if not parse_critique(note):
        return None
    dt = session_donor_target(session)
    if not dt:
        return None
    res = critique_to_fixes(root, dt[0], dt[1], note)
    acts = ", ".join(r["action"] + (f"({'/'.join(r['part'])})" if r.get("part") else "") for r in res["applied"])
    res |= {"donor": dt[0], "target": dt[1],
            "reply": f"Rig correction for {dt[0]} -> {dt[1]}: {acts}. Saved to rig_fixes; a rebuild is queued for the "
                     f"next round (before/after renders follow with the rebuild)."}
    res.pop("fixes", None)
    return res
