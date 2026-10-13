"""Resident Evil 4 (GameCube, G4BE08) enemy model swaps: put other characters (Melee fighters, Aya, ...) on the
Ganados, driven by RE4's own enemy animations.

Findings (disc 1, verified live on the Spark's Dolphin 2026-10-06):
  * Every Ganado-family enemy file em/emXX.drs (XX = 10..20, 46, 4c..50, 56, 5c..60, 66, 6c..70) holds the same
    699-slot DAT layout (re4gc_models.dat_read); a slot index means the same model in every file and each file only
    fills the slots its area needs. The ESL enemy id is the file number: id 0x16 -> em16.drs (0x46/0x56/0x66 = the
    same models with other animation sets).
  * The Mercenaries Village (room r400) loads em16: villager bodies 453, 457 (women), 472, 476 (men), heads
    455/459/474/478, Dr. Salvador's head 461 + sack 480, headscarf 463, eyes 456/460/475/479, hand poses 444-452,
    weapons 256/258/466/592-616 (rigid 1-2 bone BINs). Other bodies: 440/468 (men, em12/13/15/17),
    504/537 zealots (em11/14/19/1a/1b/1c/4c/5c/6c), 541/543 zealot leaders, 551 + 555/579 island soldiers
    (em1d/1e/1f/20/4d/4f/50/5d/5f/60/6d/6f/70), 492 robed zealot (em13/14/1e).
  * All of them share bones 0..33 (b017 pelvis, b001 hip, b002 chest, b003 neck, b004 head, b005-b010 right arm
    (-X), b011-b016 left arm (+X), b018-b021 right leg, b022-b025 left leg; faces +Z), T-pose bind.
  * A BIN draws with the TPL right after it, else the previous TPL in the DAT; heads/eyes/hands are separate BINs.

swap_enemy(): a body slot gets the new character (rigid per limb, any source rig with body roles), every other skinned
part of the same skeleton (heads, eyes, hands, hats) is emptied (one degenerate triangle per material; vertex arrays
and face-morph tables kept so nothing indexes out of range), the slot's TPL gets the new textures (padded to its
original image count). The rebuilt file must not be larger than the original (disc 1 is full); fit_file() lowers
the triangle count (Blender decimate) and texture size until it fits.
"""
from __future__ import annotations

import json
import random
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import re4gc_models as R
from .formats.rig import role_of_joint as _role_of_joint  # noqa: F401  (shared, moved to gbox.formats)

GANADO_ROLES = {"pelvis": 17, "hip": 1, "chest": 2, "neck": 3, "head": 4,
                "r_clav": 5, "r_upper": 7, "r_fore": 8, "r_hand": 9, "r_hand_end": 10,
                "l_clav": 11, "l_upper": 13, "l_fore": 14, "l_hand": 15, "l_hand_end": 16,
                "r_thigh": 18, "r_shin": 19, "r_foot": 20, "r_toe": 21,
                "l_thigh": 22, "l_shin": 23, "l_foot": 24, "l_toe": 25}

GANADO_FILES = ["em10", "em11", "em12", "em13", "em14", "em15", "em16", "em17", "em19", "em1a", "em1b", "em1c",
                "em1d", "em1e", "em1f", "em20", "em46", "em4c", "em4d", "em4f", "em50", "em56", "em5c", "em5d",
                "em5f", "em60", "em66", "em6c", "em6d", "em6f", "em70"]
VILLAGE_FILES = ["em16", "em46", "em56", "em66"]           # Mercenaries Village (r400) loads em16
BODY_SLOTS = {440: "villager man", 453: "villager woman", 457: "villager woman", 468: "villager man",
              472: "villager man", 476: "villager man", 492: "robed zealot", 504: "zealot", 537: "zealot",
              541: "zealot leader", 543: "zealot leader", 551: "island soldier (big)", 555: "island soldier",
              579: "island soldier"}

LIMBS = [("l_upper", "l_fore"), ("l_fore", "l_hand"), ("r_upper", "r_fore"), ("r_fore", "r_hand"),
         ("l_thigh", "l_shin"), ("l_shin", "l_foot"), ("r_thigh", "r_shin"), ("r_shin", "r_foot")]
FOLLOW = {"l_hand": "l_fore", "r_hand": "r_fore", "l_foot": "l_shin", "r_foot": "r_shin"}


# ---------------------------------------------------------------- DAT helpers
def tpl_of(pack: R.ModelPack, i: int) -> int | None:
    """The TPL a BIN draws with: the item right after it if that is a TPL, else the previous TPL."""
    if i + 1 < len(pack.items) and pack.items[i + 1][0] == "TPL":
        return i + 1
    for j in range(i - 1, -1, -1):
        if pack.items[j][0] == "TPL":
            return j
    return None


def minimize_bin(data: bytes) -> bytes:
    """Hide a part and shrink it: every material draws one degenerate triangle (vertex 0); vertex/normal/uv arrays
    and morph tables stay so face animation keeps indexing valid data."""
    m = R.bin_read(data)
    for mat in m.mats:
        mat.prims = [(0x90, [(0, 0, 0, 0)] * 3)]
    m.pos[:] = m.pos.mean(0)
    return R.bin_write(m)


def skeleton_key(data: bytes) -> tuple:
    m = R.bin_read(data)
    return tuple((b[0], b[1]) for b in m.bones[:34])


def body_slots(pack: R.ModelPack) -> list[int]:
    return [i for i in BODY_SLOTS if i < len(pack.items) and pack.items[i][0] == "BIN"]


# ---------------------------------------------------------------- retarget (numpy port of scripts/retarget_rigid.py)
def _rot_between(a, b):
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v, c = np.cross(a, b), float(np.dot(a, b))
    if c < -0.999999:
        ax = np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0])
        ax /= np.linalg.norm(ax)
        return 2 * np.outer(ax, ax) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def retarget(rig: dict, tmpl: R.Bin, roles: dict = GANADO_ROLES, max_stretch: float = 1.8,
             height_range=(1450.0, 2050.0), scale: dict | None = None, fit_shoulders: bool = False) -> list[dict]:
    """Rigid per-limb retarget of a source rig onto an RE4 enemy skeleton (template BIN). Returns glTF-ready prims
    in RE4 units with J = template bone index (single weight).

    rig: {"joints": (J,3) rest-pose world positions (any units, +Y up, facing +Z, left = +X), "parent": [J],
          "roles": {hip, chest, neck, head, l_upper, l_fore, l_hand, r_..., l_thigh, l_shin, l_foot, r_...},
          "prims": [{pos, nrm, uv, tris, owner (per-vertex source joint), tex, color, name}]}
    Torso: source hip -> target pelvis, uniform horizontal scale s, vertical scale fitted hip->neck above the hip and
    hip->feet below it (skirts reach the feet). Head/neck ride the target neck. Limbs: source segment rotated onto
    the target segment and stretched along it (clamped), hands/feet keep the forearm/shin rotation, sit on the wrist
    / ankle. Every vertex follows the rule of its owner joint's nearest ancestor with a role."""
    S = np.asarray(rig["joints"], float)
    rr = rig["roles"]
    bw = tmpl.bone_world()
    T = {r: np.asarray(bw[b], float) for r, b in roles.items()}
    tidx = {b[0]: k for k, b in enumerate(tmpl.bones)}

    def src(r):
        return S[rr[r]]
    foot_s = np.mean([src(r)[1] for r in ("l_foot", "r_foot") if r in rr]) if any(r in rr for r in ("l_foot", "r_foot")) else 0.0
    head_s = src("head")[1] if "head" in rr else S[:, 1].max()
    s = (T["head"][1] - T["r_foot"][1]) / max(head_s - foot_s, 1e-6)
    allp = np.concatenate([p["pos"] for p in rig["prims"]])
    tall = np.ptp(allp[:, 1]) * s
    s *= float(np.clip(tall, *height_range)) / tall
    hip = src("hip")
    neck_s = src("neck") if "neck" in rr else src("head")
    sy_up = float(np.clip((T["neck"][1] - T["pelvis"][1]) / max(neck_s[1] - hip[1], 1e-6), 0.6 * s, 1.6 * s))
    sy_dn = float(np.clip((T["pelvis"][1] - T["r_foot"][1] + 60) / max(hip[1] - min(allp[:, 1].min(), foot_s), 1e-6),
                          0.6 * s, 1.6 * s))

    wx = wz = 1.0
    if fit_shoulders and all(r in rr and r in T for r in ("l_upper", "r_upper")):   # wide robots (Metal Arms Glitch):
        span_s = abs(src("l_upper")[0] - src("r_upper")[0]) * s                     # widen the torso so the arms,
        span_t = abs(T["l_upper"][0] - T["r_upper"][0])                             # placed on the target shoulders,
        wx = float(np.clip(span_t / max(span_s, 1e-6) * 0.85, 1.0, 2.2))           # still meet the body
        wz = (1.0 + wx) / 2

    def torso(p):
        q = (p - hip) * s
        dy = p[:, 1] - hip[1]
        q[:, 1] = np.where(dy > 0, dy * sy_up, dy * sy_dn)
        q[:, 0] *= wx
        q[:, 2] *= wz
        return q + T["pelvis"]

    mats = {}
    for a, b in LIMBS:
        if a in rr and b in rr and np.linalg.norm(src(b) - src(a)) > 1e-4 * np.ptp(S[:, 1]):
            ds, dt = src(b) - src(a), T[b] - T[a]
            R_ = _rot_between(ds, dt)
            k = float(np.clip(np.linalg.norm(dt) / max(np.linalg.norm(ds) * s, 1e-6), 1 / max_stretch, max_stretch))
            d = dt / np.linalg.norm(dt)
            St = s * (np.eye(3) + (k - 1) * np.outer(d, d))
            M = St @ R_
            mats[a] = (M, src(a), T[a])
            mats[a + "@rot"] = (s * R_, src(a), T[a])
    for leaf, par in FOLLOW.items():
        if leaf in rr and par + "@rot" in mats:
            M = mats[par + "@rot"][0]
            mats[leaf] = (M, src(leaf), T[leaf])
    neck_t = T["neck"]

    bone_for = {"hip": "hip", "pelvis": "pelvis", "chest": "chest", "neck": "neck", "head": "head",
                "l_clav": "l_clav", "r_clav": "r_clav"}
    jrole = _role_of_joint(rig)
    out = []
    for p in rig["prims"]:
        pos, nrm = np.asarray(p["pos"], float), np.asarray(p["nrm"], float)
        own = np.asarray(p["owner"], int)
        role = np.array([jrole[j] for j in own])
        P, N = np.zeros_like(pos), nrm.copy()
        bone = np.zeros(len(pos), int)
        for r in set(role.tolist()):
            sel = role == r
            if r in mats:
                M, a, t = mats[r]
                P[sel] = (pos[sel] - a) @ M.T + t
                N[sel] = nrm[sel] @ mats.get(r + "@rot", mats[r])[0].T
                tb = roles[r]
            elif r == "head" and float((scale or {}).get("head", 1.0)) != 1.0:   # head-bone scale (variants): about
                hs = src("head") if "head" in rr else neck_s                      # the head joint, which stays put
                P[sel] = (pos[sel] - hs) * s * float(scale["head"]) + (hs - neck_s) * s + neck_t
                tb = roles[r]
            elif r in ("neck", "head"):
                P[sel] = (pos[sel] - neck_s) * s + neck_t
                tb = roles[r]
            else:                                          # torso family (hip, chest, clavicles, anything unmapped)
                P[sel] = torso(pos[sel])
                if r in ("chest", "l_clav", "r_clav"):
                    tb = roles[bone_for[r]]
                else:
                    tb = None
            if tb is None:                                 # hip: above the pelvis -> spine root, below -> pelvis
                bone[sel] = np.where(pos[sel][:, 1] >= hip[1] + 0.05 * (neck_s[1] - hip[1]), roles["hip"], roles["pelvis"])
            else:
                bone[sel] = tb
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        J = np.zeros((len(pos), 4), np.int64)
        J[:, 0] = [tidx[b] for b in bone]
        W = np.zeros((len(pos), 4))
        W[:, 0] = 1
        out.append({**{k: v for k, v in p.items() if k not in ("pos", "nrm", "J", "W", "owner")},
                    "pos": P, "nrm": N, "J": J, "W": W})
    return out


def write_rigged_gltf(prims: list[dict], tmpl: R.Bin, path: Path, name: str = "enemy") -> Path:
    """RE4-skeleton glTF (joint nodes b<id>, metres) for gltf_to_bin / decimate_gltf.py / previews."""
    from .melee_models import write_gltf
    bw = tmpl.bone_world()
    idx = {b[0]: k for k, b in enumerate(tmpl.bones)}
    joints = []
    for bid, par, *_ in tmpl.bones:
        w = np.eye(4)
        w[:3, 3] = bw[bid]
        joints.append({"parent": idx.get(par, -1) if par != 0xFF else -1, "world": w})
    return write_gltf(path, joints, prims, 0.001, name, [f"b{b[0]:03d}" for b in tmpl.bones])


# ---------------------------------------------------------------- building
def blender_exe() -> str | None:
    import glob
    cands = sorted(glob.glob("C:/Users/maste/Desktop/Blender Builds/Builds/stable/blender-4.5*/blender.exe")) + \
        sorted(glob.glob("/usr/bin/blender"))
    return cands[-1] if cands else None


def decimate(src: Path, dst: Path, amount: float, blender: str | None = None) -> Path:
    script = Path(__file__).resolve().parent / "decimate_gltf.py"
    if not script.exists():        # pre-PR #r1292 layout
        script = Path(__file__).resolve().parents[1] / "scripts" / "decimate_gltf.py"
    exe = blender or blender_exe()
    r = subprocess.run([exe, "--background", "--factory-startup", "--python", str(script), "--", str(src), str(dst),
                        str(amount)], capture_output=True, text=True, timeout=600)
    if not Path(dst).exists():
        raise RuntimeError("decimate failed: " + (r.stdout + r.stderr)[-2000:])
    return Path(dst)


def stripify(tris: list[tuple]) -> list[tuple[int, list]]:
    """Triangle list (corner tuples, CCW as in the BIN) -> GX prims: greedy 0x98 strips + one 0x90 list of leftovers.
    A strip vertex is a full corner (pos, nrm, clr, uv), so texture seams end strips."""
    edge: dict = {}
    for t, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            edge.setdefault(e, []).append(t)
    used = [False] * len(tris)

    def take(e):
        for t in edge.get(e, ()):
            if not used[t]:
                return t
        return None
    strips, singles = [], []
    for t0 in range(len(tris)):
        if used[t0]:
            continue
        used[t0] = True
        a, b, c = tris[t0]
        best = None
        for s0 in ((a, b, c), (b, c, a), (c, a, b)):           # try the 3 rotations, keep the longest
            st, tk = list(s0), []
            while True:
                i = len(st) - 2
                e = (st[-2], st[-1]) if i % 2 == 0 else (st[-1], st[-2])
                t = take(e)
                if t is None:
                    break
                used[t] = True
                tk.append(t)
                x = next(v for v in tris[t] if v not in e) if len(set(tris[t])) == 3 else tris[t][2]
                st.append(x)
            if best is None or len(tk) > len(best[1]):
                if best:
                    for t in best[1]:
                        used[t] = False
                best = (st, tk)
            else:
                for t in tk:
                    used[t] = False
        for t in best[1]:
            used[t] = True
        if len(best[0]) == 3:
            singles += best[0]
        else:
            strips.append((0x98, best[0]))
    if singles:
        strips.append((0x90, singles))
    return strips


def strip_bin(m: R.Bin) -> R.Bin:
    for mat in m.mats:
        tris = [tuple(t) for t in mat.triangles()]
        if tris:
            mat.prims = stripify(tris)
    return m


def build_body(gl: Path, tmpl: R.Bin, max_tex: int = 64) -> tuple[R.Bin, list[np.ndarray]]:
    """Rigged glTF -> (stripped BIN on the template's skeleton, textures)."""
    m, texs = R.gltf_to_bin(gl, tmpl, scale=0.001, max_tex=max_tex)
    return strip_bin(m), texs


def swap_enemy(pack: R.ModelPack, bodies: dict[int, tuple[R.Bin, list[np.ndarray]]], hide_parts: bool = True) -> dict:
    """bodies: {body slot: (new BIN on that slot's skeleton, its textures)}. Writes each body, rebuilds its TPL with
    the new textures (padded with 8x8 dummies to the original image count), and empties every other skinned part
    of the Ganado skeleton (heads, eyes, hands, hats). Rigid 1-2 bone props (weapons) stay."""
    rep = {}
    key = None
    for slot, (m, texs) in bodies.items():
        tj = tpl_of(pack, slot)
        old = R.tpl_read(pack.items[tj][1])
        hdr = old[0].hdr if old else None
        imgs = [R.tpl_image_from_rgba(t, hdr) for t in texs]
        while len(imgs) < len(old):
            imgs.append(R.tpl_image_from_rgba(np.full((8, 8, 4), 128, np.uint8), hdr))
        struct.pack_into(">I", m.header, 0x24, len(texs))
        pack.items[slot] = ("BIN", R.bin_write(m))
        pack.items[tj] = ("TPL", R.tpl_write(imgs))
        key = key or skeleton_key(pack.items[slot][1])
        rep[slot] = {"bin": len(pack.items[slot][1]), "tpl": len(pack.items[tj][1]), "textures": len(texs),
                     "tris": sum(R._tri_count(x.prims) for x in m.mats)}
    if hide_parts and key:
        hidden = []
        for i, (e, d) in enumerate(pack.items):
            if e == "BIN" and i not in bodies and d[0x19] >= 30 and skeleton_key(d) == key:
                pack.items[i] = ("BIN", minimize_bin(d))
                hidden.append(i)
        rep["hidden"] = hidden
    return rep


def file_budget(orig: bytes, pack: R.ModelPack) -> int:
    return len(orig) - len(pack.to_bytes())


def plan_assignment(cast: list[str], slots: list[int], seed: int | None = None) -> dict[int, str]:
    """A new random character per body slot (distinct while the cast lasts)."""
    rng = random.Random(seed)
    pool = list(cast)
    rng.shuffle(pool)
    return {s: pool[k % len(pool)] for k, s in enumerate(sorted(slots))}


# ---------------------------------------------------------------- whole-file build with size fitting
LEVELS = [(1.0, 64), (1.0, 32), (0.8, 64), (0.8, 32), (0.65, 32), (0.5, 32), (0.38, 32), (0.28, 32), (0.2, 16)]


class Builder:
    """Caches retargets / decimations / BINs across files. chars: {name: callable() -> source rig}."""

    def __init__(self, chars: dict, work: Path, log=print):
        self.chars, self.work, self.log = chars, Path(work), log
        self.work.mkdir(parents=True, exist_ok=True)
        self._rig, self._bin = {}, {}

    def rig(self, name):
        if name not in self._rig:
            self._rig[name] = self.chars[name]()
        return self._rig[name]

    def gltf(self, name: str, slot: int, tmpl: R.Bin, ratio: float) -> Path:
        full = self.work / f"{name}_s{slot}.gltf"
        if not full.exists():
            write_rigged_gltf(retarget(self.rig(name), tmpl), tmpl, full, name)
        if ratio >= 0.999:
            return full
        dec = self.work / f"{name}_s{slot}_r{int(ratio * 100)}.glb"
        if not dec.exists():
            decimate(full, dec, ratio)
        return dec

    def body(self, name: str, slot: int, tmpl_bytes: bytes, ratio: float, max_tex: int):
        k = (name, slot, ratio, max_tex)
        if k not in self._bin:
            tmpl = R.bin_read(tmpl_bytes)
            m, texs = build_body(self.gltf(name, slot, tmpl, ratio), tmpl, max_tex)
            self._bin[k] = (R.bin_write(m), texs)
        d, texs = self._bin[k]
        return R.bin_read(d), texs

    def build_file(self, orig: bytes, assign: dict[int, str], levels=LEVELS) -> tuple[bytes, dict]:
        """assign: {body slot: character}. Returns (new .drs bytes <= original size, report)."""
        for ratio, mt in levels:
            pk = R.ModelPack(orig)
            bodies = {s: self.body(c, s, pk.items[s][1], ratio, mt) for s, c in assign.items()}
            rep = swap_enemy(pk, bodies)
            out = pk.to_bytes()
            if len(out) <= len(orig):
                rep.update(ratio=ratio, max_tex=mt, size=len(out), orig=len(orig),
                           assign={s: c for s, c in assign.items()})
                return out, rep
            self.log(f"  {len(out) - len(orig):+d} bytes at ratio {ratio} tex {mt}; lowering")
        raise ValueError("does not fit even at the lowest level")


def melee_chars(melee_dir: Path, names: list[str]) -> dict:
    from . import melee_models as M
    plco = (Path(melee_dir) / "PlCo.dat").read_bytes()

    def mk(n):
        def f():
            m, _ = M.load_fighter(melee_dir, n)
            return M.source_rig(m, M.common_ids(plco, n))
        return f
    return {n: mk(n) for n in names}


# ---------------------------------------------------------------- combining file mods (player swap + enemy swap)
def collect_mod_files(mod_dirs: list[Path], out_dir: Path) -> dict[str, str]:
    """Read every replaced file out of built file mods (cache/mods/<game>/<mod>/, image + .gbox-mod.json) into
    out_dir, later mods winning on the same path. Returns {disc path: local file}."""
    from .gcdisc import GCDisc
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for md in mod_dirs:
        md = Path(md)
        meta = json.loads((md / ".gbox-mod.json").read_text())
        d = GCDisc(md / meta["image"])
        try:
            for f in meta["files"]:
                if f == "@image":
                    raise ValueError(f"{md.name}: raw image patches can't be combined")
                dst = out_dir / f.replace("/", "__")
                dst.write_bytes(d.read(f))
                files[f] = str(dst)
        finally:
            d.f.close()
    return files


def combine(cache: Path, base_rom: Path, mods: list[str], name: str, image_name: str | None = None,
            game_id: str = "78ab9efa2e310db4") -> dict:
    """One launchable file mod from several (e.g. ["re4_mario", "re4_enemies_peach"] = Mario vs Peach Ganados):
    their replaced files applied to the vanilla image (base_rom: the catalog's disc 1 GCZ/ISO), image renamed to
    image_name (default <name>.iso) so gBox's staging cache can't confuse it with another mod; a stale staged copy
    of that name is removed. Run it on the node whose cache holds the mods (launch_game(mod=name) there)."""
    import types
    from . import filemods
    cache = Path(cache)
    mdirs = [cache / "mods" / game_id / m for m in mods]
    work = cache / "mods" / game_id / f".{name}.parts"
    files = collect_mod_files(mdirs, work)
    try:
        res = filemods.build_image(types.SimpleNamespace(cache=cache), game_id, Path(base_rom), name,
                                   {k: {"from": v} for k, v in files.items()})
    finally:
        for p in work.glob("*"):
            p.unlink()
        work.rmdir()
    out = cache / "mods" / game_id / name
    meta = json.loads((out / ".gbox-mod.json").read_text())
    image_name = image_name or f"{name}.iso"
    if meta["image"] != image_name:
        (out / meta["image"]).replace(out / image_name)
        meta["image"] = image_name
    meta["combined"] = mods
    (out / ".gbox-mod.json").write_text(json.dumps(meta))
    stale = cache / game_id / image_name
    if stale.exists():
        stale.unlink()
    return {**res, "image": str(out / image_name), "mods": mods}
