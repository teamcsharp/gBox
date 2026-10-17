"""Native character writer for Metal Gear Solid: VR Missions (PS1, USA): Snake, the soldiers and the other 16-object
figures of the disc, from any collection character, plus the PS1 container layer gbox.mgs1_swap shares.

Slots (SLOTS; docs/mgs_vr_decomp.md "Models and slots"):
  player         Snake, init/39213.kmd (GV_StrCode "snake") in init.stg's model DAR; textures in init's 1_0.dar
  enemy:soldier  every VR soldier ("watcher.c" actors): 38582.kmd and its low-detail twin 55267.kmd, a cached file of
                 each of the 88 mission stages that has soldiers; textures in each stage's texture DAR (one copy per
                 stage: same pixels, stage-specific VRAM / CLUT places and palettes)
  enemy:ninja    the sword-carrying figure of vcd_n01..03 (37617.kmd)
  model:<hash>   the other stage-specific 16-object figures (46243, 37567, 31475, 26944)
Every one of them has Snake's object tree (parents [-1,0,1,2,3,1,5,1,7,8,0,10,11,0,13,14]), so SNAKE_ROLES maps any
of them onto the body roles, and the game's motions keep driving object i with bone i.

The fit (fit_slot / fit_kmd_textured), for each model of a slot:
  1. sm64_swap.retarget onto the model's bind-pose joints, scaled to the model's whole height (fit_height; the head
     joint fit made big-headed donors 1.7x Snake's height with the feet through the floor, see "What was wrong");
  2. proportion(): a head taller than HEAD_ROOM x the model's height is shrunk about its base, the feet are squashed
     or stretched about the ankle until the soles stand on the model's ground; then the operator's Retarget editor
     profile (meta rig.scale["profile"]) and head scale apply, as in the other writers;
  3. every triangle goes to the object of its bone, in that object's local frame;
  4. decimate(): quadric edge collapse per object (gbox.auf_swap.decimate) to per-object triangle targets that share
     the KMD's byte allocation in proportion to the donor's own detail (small objects keep a floor), within the
     u8 vertex / 7-bit normal index limits;
  5. textures: the kept faces' images are painted into the model's own texture slots (gbox.mgs_vr_tex.paint), once
     per texture archive (Snake: init's; soldiers: each stage's own);
  6. seam welding (mgs_kmd.weld_seams) and the game contract check (mgs_kmd.check_compatible).

The container layer is native (no MetalMintSolid): STAGE.DIR -> .stg entries (streamed, sector aligned; a run of
cached entries is one block whose entries' size fields are offsets into it) -> DAR entries.  A KMD is rewritten in
place at its own size (zero padded), a texture DAR is repacked to its own size, and only the changed raw sectors get
new EDC/ECC (psxdisc.RawBin).  build() (MetalMintSolid) stays for gbox.mgs1_swap.

What was wrong with Sonic (2026-10-13): no Sonic Adventure character could be built at all ("could not fit the model
into the 13608-byte KMD allocation"): one vertex-cluster cell for the whole body grew until Sonic's 490-685-triangle
head fitted, which collapsed his hands and feet to nothing first, and an object without triangles failed the fit.
Scaled at Snake's head joint, Sonic stood 1.7x Snake's height with his shoes 450 units under the floor, and the
operator's Retarget editor profile and head size were never passed to the fit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from . import mgs_kmd, mgs_pcc, mgs_vr_tex, psxdisc

GAME_IDS = {"f55555ee6513391b", "afd2fc507bb69843"}
MOD_NAME = "mgs_vr_hucast_native"
DISC_NAME = "Metal Gear Solid - VR Missions (USA)"
DISC_BYTES = 492487632
PLAYER_KMD_SHA256 = "5dda0c64dfef4523675fee16af56d7d119b8c4ddab43c20f912f2de33f810254"
STAGE_DIR_SIZES = (72593408, 71892992)                   # VR Missions, MGS disc 1
# Snake's 16 KMD objects = motion bones (left = +X, up = +Y, front = +Z, like sm64_swap's frame).  Every 16-object
# figure on the disc (soldiers, the ninja, the puzzle-stage figures) has the same tree, so the map holds for all.
SNAKE_ROLES = {"hip": 0, "chest": 1, "neck": 5, "head": 6,
               "r_upper": 2, "r_fore": 3, "r_hand": 4, "l_upper": 7, "l_fore": 8, "l_hand": 9,
               "r_thigh": 10, "r_shin": 11, "r_foot": 12, "l_thigh": 13, "l_shin": 14, "l_foot": 15}
TREE = [-1, 0, 1, 2, 3, 1, 5, 1, 7, 8, 0, 10, 11, 0, 13, 14]
FIT_TEXTURE_OBJECT = 0   # untextured fit (fit_kmd): faces reuse the model's waist texture/uv
PLAYER_MODEL = 39213
HEAD_ROOM = 1.2          # a donor's head may reach this x the game model's height (a big head stays big, not a tower)
MIN_OBJECT_TRIS = 6      # decimation floor per object (a hand never vanishes to make room for the head)
WELD_RADIUS = 48.0       # KMD units (Snake is ~1720 tall): seam vertices this close to the parent are welded

# The writer's slots.  models: KMD names (GV_StrCode) rebuilt for the slot; stages: where the disc keeps them.
SLOTS = {
    "player": {"name": "Solid Snake (the player)", "kind": "player", "models": [PLAYER_MODEL], "model": PLAYER_MODEL,
               "where": "init.stg 0_0.dar, every stage", "objects": 16, "size": 1.0,
               "motion": "snake (init 39213.oar)", "textures": "init.stg 1_0.dar, 28 slots in CLUTs 784,226 / 768,226",
               "loaded_by": "player actor 0x8005DDC0 (GCL param m, default GV_StrCode('snake')); no mission script "
                            "sets m, so Sneaking, Weapon, Advanced and special stages all use it",
               "actor": "../snake_vr/sna_init.c", "writer": "mgs_vr_swap.fit_slot"},
    "enemy:soldier": {"name": "Genome soldiers (every VR soldier)", "kind": "enemy", "models": [38582, 55267],
                      "model": 38582, "bytes": 9936, "objects": 16, "motion": 0xA8A1, "size": 1.02,
                      "where": "a cached file of the 88 mission stages with soldiers (vr_*, vab_*, vcd_*, vefgh_*, "
                               "vijkl_*); 55267 is the same soldier with fewer triangles (6,060 bytes)",
                      "textures": "each stage's texture DAR (23 textures, 9 CLUTs at y 236/237; per-stage palettes)",
                      "loaded_by": "the soldier actor 'watcher.c' of each stage overlay (GM_InitObject(.., 38582, "
                                   "0x32D, motion GV_StrCode('enemy') 0xA8A1) at 0x800C5D7C in vr_sud03; 55267 when "
                                   "its GCL param y = 1)",
                      "actor": "watcher.c", "writer": "mgs_vr_swap.fit_slot"},
    "enemy:ninja": {"name": "Ninja (sword, vcd_n01-03)", "kind": "enemy", "models": [37617], "model": 37617,
                    "objects": 16, "size": 1.0, "where": "vcd_n01, vcd_n02, vcd_n03 (cached file)",
                    "note": "named from its long sword (object 4, right hand); the actor's source name is not read yet",
                    "writer": "mgs_vr_swap.fit_slot"},
    "model:46243": {"name": "Puzzle-stage figure 46243 (vijkl_01/03/06/10)", "kind": "npc", "models": [46243],
                    "model": 46243, "objects": 16, "size": 1.0, "writer": "mgs_vr_swap.fit_slot"},
    "model:37567": {"name": "Puzzle-stage figure 37567 (vijkl_01/03/06/10, low detail)", "kind": "npc",
                    "models": [37567], "model": 37567, "objects": 16, "size": 1.0, "writer": "mgs_vr_swap.fit_slot"},
    "model:31475": {"name": "Long-haired figure 31475 (vcd_n05, 'camera_def2')", "kind": "npc", "models": [31475],
                    "model": 31475, "objects": 16, "size": 1.0, "writer": "mgs_vr_swap.fit_slot"},
    "model:26944": {"name": "Soldier variant 26944 (vefgh_10)", "kind": "enemy", "models": [26944], "model": 26944,
                    "objects": 16, "size": 1.02, "writer": "mgs_vr_swap.fit_slot"},
}
ALIASES = {"snake": "player", "solid snake": "player", "me": "player", "soldier": "enemy:soldier",
           "soldiers": "enemy:soldier", "genome": "enemy:soldier", "genome soldier": "enemy:soldier",
           "genome soldiers": "enemy:soldier", "guard": "enemy:soldier", "guards": "enemy:soldier",
           "enemy": "enemy:soldier", "watcher": "enemy:soldier", "ninja": "enemy:ninja"}
GROUPS = {"enemies": [s for s, r in SLOTS.items() if r["kind"] == "enemy"], "all": list(SLOTS),
          "everyone": list(SLOTS), "cast": list(SLOTS)}


def slot_of(name: str) -> str | None:
    """'snake' / 'soldiers' / 'enemy:soldier' / 'model:46243' / '46243' -> a slot key, else None."""
    s = re.sub(r"\s+", " ", str(name or "").strip().lower())
    if s in SLOTS:
        return s
    if s in ALIASES:
        return ALIASES[s]
    m = re.fullmatch(r"(?:model:|enemy:)?(\d{3,5})", s)
    if m:
        h = int(m.group(1))
        return next((k for k, r in SLOTS.items() if h in r["models"]), None)
    if s.startswith("enemy:") and s[6:] in ALIASES:
        return ALIASES[s[6:]]
    return None


def is_slot(name: str) -> bool:
    return slot_of(name) is not None or str(name or "").strip().lower() in GROUPS


def slots_of(name: str) -> list[str]:
    """A slot or a group (enemies / all) -> its slot keys."""
    s = str(name or "").strip().lower()
    if s in GROUPS:
        return list(GROUPS[s])
    one = slot_of(s)
    if not one:
        raise ValueError(f"VR Missions has no slot {name!r}: player | enemy:soldier | enemy:ninja | "
                         f"{' | '.join(k for k in SLOTS if k.startswith('model:'))} | enemies | all")
    return [one]


def cast_slots() -> list[dict]:
    """The slots for the whole-cast menu (gbox.cast_swap): every model kind once."""
    return [{"slot": k, "name": r["name"], "kind": r["kind"], "size": r.get("size"), "writer": "gbox.mgs_vr_swap",
             "models": list(r["models"])} for k, r in SLOTS.items()]


# ---------------------------------------------------------------------------------------------- disc layout (native)
def stage_dir(data: bytes) -> dict[str, int]:
    """MGS/STAGE.DIR: u32 header size, then {char name[8], u32 sector} per stage -> {name: byte offset}."""
    size = struct.unpack_from("<I", data, 0)[0]
    out = {}
    for o in range(4, size, 12):
        name = data[o:o + 8].split(b"\0")[0].decode("latin-1")
        if name:
            out[name] = struct.unpack_from("<I", data, o + 8)[0] * 2048
    return out


def stage_files(data: bytes, off: int) -> list[dict]:
    """Every entry of the .stg at *off* in STAGE.DIR -> [{index, hash, mode, ext, offset, size}] (offset absolute).

    Header u8 1, u8 0, u16 sectors, then 8-byte entries {u16 hash, u8 mode, u8 ext, u32 size} up to an all-zero one.
    Streamed entries (mode 's', 'n', 'r', ...) follow from +0x800 in order, each sector aligned.  A run of cached
    entries (mode 'c') is one block starting at the next sector boundary: each entry's size field is its offset in
    the block, and the run's last entry (hash 0) holds the block length (MetalMintSolid's rebuild.json agrees)."""
    ents, i = [], 0
    while off + 4 + 8 * i + 8 <= len(data) and i < 256:
        h, mode, ext, size = struct.unpack_from("<HBBI", data, off + 4 + 8 * i)
        if h == 0 and mode == 0 and ext == 0 and size == 0:
            break
        ents.append((i, h, mode, ext, size))
        i += 1
    out, pos, run = [], off + 0x800, []

    def flush():
        nonlocal pos, run
        if not run:
            return
        length = run[-1][4]
        for k, (ci, ch, cm, ce, cs) in enumerate(run):
            nxt = run[k + 1][4] if k + 1 < len(run) else length
            out.append({"index": ci, "hash": ch, "mode": chr(cm), "ext": chr(ce) if ce < 128 else f"{ce:#x}",
                        "offset": pos + cs, "size": max(0, nxt - cs), "cached": True})
        pos += (length + 2047) // 2048 * 2048
        run = []
    for e in ents:
        if chr(e[2]) == "c":
            run.append(e)
            continue
        flush()
        i, h, m, x, s = e
        out.append({"index": i, "hash": h, "mode": chr(m), "ext": chr(x) if x < 128 else f"{x:#x}", "offset": pos,
                    "size": s, "cached": False})
        pos += (s + 2047) // 2048 * 2048
    flush()
    return sorted(out, key=lambda r: r["index"])


def dar_entries(data: bytes, base: int = 0, size: int | None = None) -> list[dict]:
    """[{hash, ext, offset (of the body, absolute when base is), size}] of a PSX DAR at data[base:base+size]."""
    end = base + (len(data) - base if size is None else size)
    out, o = [], base
    while o + 8 <= end:
        h, ext, _zero, n = struct.unpack_from("<HBBI", data, o)
        if ext == 0 and n == 0:
            break
        if o + 8 + n > end:
            raise ValueError(f"DAR entry {h} runs past its archive")
        out.append({"hash": h, "ext": chr(ext) if ext < 128 else f"{ext:#x}", "offset": o + 8, "size": n})
        o += 8 + (n + 3 & ~3)
    return out


def stage_textures(data: bytes, stage_off: int) -> list[dict]:
    """The stage's texture DARs: [{offset, size, entries: {hash: (body offset, size)}}] (streamed 'd' entries)."""
    out = []
    for f in stage_files(data, stage_off):
        if f["ext"] != "d" or f["cached"]:
            continue
        try:
            ents = dar_entries(data, f["offset"], f["size"])
        except ValueError:
            continue
        pcc = {e["hash"]: (e["offset"], e["size"]) for e in ents if e["ext"] == "p"}
        if pcc:
            out.append({"offset": f["offset"], "size": f["size"], "entries": pcc})
    return out


def model_sites(data: bytes, models) -> list[dict]:
    """Where the disc keeps each of *models*: [{stage, model, offset, size, stage_offset}] in STAGE.DIR order.  A model
    inside a DAR (init's 0_0.dar) is addressed by its body; a cached stage file by its block slot."""
    want = set(models)
    out = []
    for name, off in sorted(stage_dir(data).items(), key=lambda kv: kv[1]):
        for f in stage_files(data, off):
            if f["ext"] == "k" and f["hash"] in want:
                out.append({"stage": name, "model": f["hash"], "offset": f["offset"], "size": f["size"],
                            "stage_offset": off})
            elif f["ext"] == "d" and not f["cached"]:
                try:
                    ents = dar_entries(data, f["offset"], f["size"])
                except ValueError:
                    continue
                for e in ents:
                    if e["ext"] == "k" and e["hash"] in want:
                        out.append({"stage": name, "model": e["hash"], "offset": e["offset"], "size": e["size"],
                                    "stage_offset": off, "dar": f["offset"]})
    return out


# ---------------------------------------------------------------------------------------------- the fit
def kmd_target(original: mgs_kmd.Kmd) -> dict:
    """sm64_swap.retarget's target for a 16-object KMD in bind pose (KMD joints carry no rotation)."""
    import numpy as np
    T = np.zeros((len(original.objects), 3))
    for i, o in enumerate(original.objects):
        T[i] = (T[o.parent] if o.parent >= 0 else 0) + np.array(o.pos, float)
    world = np.array([[v[0] + T[i][0], v[1] + T[i][1], v[2] + T[i][2]]
                      for i, o in enumerate(original.objects) for v in o.vertices], float)
    head = np.array([v[:3] for v in original.objects[SNAKE_ROLES["head"]].vertices], float)
    ground = float(world[:, 1].min())
    height = float(world[:, 1].max() - ground)
    hj = SNAKE_ROLES["head"]
    return {"T": T, "ground": ground, "top": ground + height, "head_h": float(np.ptp(head[:, 1])) if len(head) else 200.0,
            "head_base": float(T[hj][1] + head[:, 1].min()) if len(head) else float(T[hj][1]),
            "height": height, "fit_height": height, "roles": SNAKE_ROLES}


snake_target = kmd_target          # the first writer's name for it


LIMB_CHAIN = [(2, 3), (3, 4), (7, 8), (8, 9), (10, 11), (11, 12), (13, 14), (14, 15)]   # (segment, the joint it reaches)


def proportion(prims: list[dict], tgt: dict, head_room: float = HEAD_ROOM) -> tuple[list[dict], dict]:
    """Keep a fitted figure inside the game model's proportions (in place on *prims*, target space):
      * the head sits on the neck: its lowest point moves to the model's own head base (a big head fitted at the
        torso's scale otherwise hangs over the chest and turns about its middle), then it is shrunk about that base
        when the figure's top passes head_room x the model's height;
      * a limb segment that stops short of the next joint (short-legged donors hit the retarget's 2x stretch limit)
        is stretched along its bone until it reaches it, so no gap opens at the knee, ankle, elbow or wrist;
      * each foot is squashed / stretched about its ankle so the soles stand on the model's ground."""
    import numpy as np
    T, ground = np.asarray(tgt["T"], float), float(tgt["ground"])
    head_j, feet = SNAKE_ROLES["head"], (SNAKE_ROLES["r_foot"], SNAKE_ROLES["l_foot"])
    live = [p for p in prims if not p.get("prop") and len(p["pos"])]
    rep = {"head_lift": 0.0, "head_shrink": 1.0, "limb_reach": {}, "feet": {}}
    if not live:
        return prims, rep

    def verts(j):
        return [(p, p["J"][:, 0] == j) for p in live]
    tol = 0.01 * float(tgt["height"])
    hv = np.concatenate([p["pos"][m] for p, m in verts(head_j)]) if any(m.any() for _p, m in verts(head_j)) else None
    if hv is not None and "head_base" in tgt and float(np.ptp(hv[:, 1])) > 2.0 * float(tgt["head_h"]):
        # only a head over twice the model's own head height (Sonic's, Tails'): a human head with long hair keeps the
        # retarget's place (its lowest point is a hair tip, not the chin)
        lift = float(tgt["head_base"]) - float(hv[:, 1].min())
        if abs(lift) > tol:
            for p, m in verts(head_j):
                p["pos"][m, 1] += lift
            rep["head_lift"] = round(lift, 1)
        chest_j = SNAKE_ROLES["chest"]                   # the chest grows up to the seated head (no neck gap)
        parts = [(p, m) for p, m in verts(chest_j) if m.any()]
        if parts:
            y1 = float(T[chest_j][1])
            top = max(float(p["pos"][m, 1].max()) for p, m in parts)
            want = float(tgt["head_base"])
            if y1 + tol < top < want - tol:
                k = min(2.5, (want - y1) / (top - y1))
                for p, m in parts:
                    q = p["pos"][m]
                    up = q[:, 1] > y1
                    q[up, 1] = y1 + (q[up, 1] - y1) * k
                    p["pos"][m] = q
                rep["chest_stretch"] = round(k, 2)
    P = np.concatenate([p["pos"] for p in live])
    cap = ground + head_room * float(tgt["height"])
    if hv is not None and float(P[:, 1].max()) > cap:
        hv = np.concatenate([p["pos"][m] for p, m in verts(head_j)])
        base, top = float(hv[:, 1].min()), float(hv[:, 1].max())
        if top > cap > base:
            k = (cap - base) / (top - base)
            piv = np.array([T[head_j][0], base, T[head_j][2]])
            for p, m in verts(head_j):
                p["pos"][m] = piv + (p["pos"][m] - piv) * k
            rep["head_shrink"] = round(k, 3)
    for j, c in LIMB_CHAIN:
        d = T[c] - T[j]
        L = float(np.linalg.norm(d))
        parts = [(p, m) for p, m in verts(j) if m.any()]
        if L < 1e-6 or not parts:
            continue
        u = d / L
        reach = max(float(((p["pos"][m] - T[j]) @ u).max()) for p, m in parts)
        if not 0.1 * L < reach < 0.92 * L:
            continue
        k = min(3.0, L / reach)
        for p, m in parts:
            q = p["pos"][m] - T[j]
            a = q @ u
            p["pos"][m] = T[j] + q + np.outer(np.maximum(a, 0.0) * (k - 1), u)
        rep["limb_reach"][str(j)] = round(k, 2)
    for f in feet:
        if not any(m.any() for _p, m in verts(f)):
            continue
        ank = float(T[f][1])
        lo = float(np.concatenate([p["pos"][p["J"][:, 0] == f, 1] for p in live]).min())
        if abs(lo - ground) <= tol or ank - lo < 1e-6 or ank <= ground:
            continue
        k = float(np.clip((ank - ground) / (ank - lo), 0.1, 4.0))
        for p in live:
            m = (p["J"][:, 0] == f) & (p["pos"][:, 1] < ank)
            p["pos"][m, 1] = ank + (p["pos"][m, 1] - ank) * k
        rep["feet"][str(f)] = round(k, 3)
    return prims, rep


def fit_prims(original: mgs_kmd.Kmd, rig: dict, scale: dict | None = None) -> tuple[list[dict], dict, dict]:
    """The donor (sm64_swap.load_rig) retargeted onto one 16-object model: (prims in target space, report, target)."""
    from . import fit_events as FE, retarget_profile as RP, sm64_swap as S
    tgt = kmd_target(original)
    prof = RP.profile_of(scale)
    plain = {k: v for k, v in (scale or {}).items() if k != "profile"} or None
    prims, rep = S.retarget(rig, tgt, plain, jmap=SNAKE_ROLES)
    prims, rep["proportion"] = proportion(prims, tgt)
    if prof is not None:                                  # the operator's Retarget editor profile, after the auto fit
        prims, rep["profile"] = RP.apply_jmap(prims, tgt["T"], SNAKE_ROLES, prof, tgt["ground"])
    FE.stage("proportion", data={**rep["proportion"], "profile": bool(prof), "fit_height": round(tgt["height"]),
                                 "fitted_height": FE.height(prims)}, prims=prims)
    return prims, rep, tgt


def split_objects(prims: list[dict], tgt: dict, count: int = 16) -> dict[int, dict]:
    """Every fitted triangle to the object of its bone (majority of its corners), in that object's local frame:
    {object: {P (3n,3), N (3n,3), A [(image key, image, uv (3,2), colour)]}}."""
    import numpy as np
    T = np.asarray(tgt["T"], float)
    per = {i: {"P": [], "N": [], "A": []} for i in range(count)}
    for p in prims:
        if p.get("prop"):
            continue
        J = p["J"][:, 0]
        img = p.get("tex")
        key = id(img) if img is not None else None
        uvs = np.asarray(p["uv"] if p.get("uv") is not None else np.zeros((len(p["pos"]), 2)), float)
        colour = tuple(p.get("color") or (255, 255, 255))
        for tri in np.asarray(p["tris"]).reshape(-1, 3):
            j = int(np.bincount(J[tri], minlength=count).argmax())
            o = per[j]
            o["P"].append(p["pos"][tri] - T[j])
            o["N"].append(p["nrm"][tri])
            o["A"].append((key, img, uvs[tri], colour))
    for o in per.values():
        o["P"] = np.concatenate(o["P"]) if o["P"] else np.zeros((0, 3))
        o["N"] = np.concatenate(o["N"]) if o["N"] else np.zeros((0, 3))
    return per


def _mesh(P, N, target: int):
    """One object's triangles (3 corners each) -> (vertices (v,3) int, normals (v,3), faces (f,3), kept source triangle
    indices), quadric-decimated to at most *target* triangles where the surface allows."""
    import numpy as np
    from .auf_swap import decimate
    n = len(P) // 3
    F = np.arange(3 * n).reshape(n, 3)
    Q = P
    if n > target:
        Q, F = decimate(P, F, max(1, target))
    if len(F) > 1.3 * target + 2:                         # a triangle soup has no edges to collapse: cluster it
        F0 = np.arange(3 * n).reshape(n, 3)
        ext = float(np.ptp(P, 0).max()) or 1.0
        cell = ext / 64
        while len(F) > target and cell < 4 * ext:
            key = np.round(P / cell).astype(np.int64)
            _u, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
            inv = inv.reshape(-1)
            Q = P[first][inv]
            t = inv[F0]
            good = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
            _s, once = np.unique(np.sort(t[good], 1), axis=0, return_index=True)
            F = F0[good][np.sort(once)]
            cell *= 1.25
    keep = F[:, 0] // 3
    Qi = np.clip(np.round(Q), -32767, 32767).astype(np.int64)
    key, inv = np.unique(Qi[F.reshape(-1)], axis=0, return_inverse=True)
    inv = inv.reshape(-1, 3)
    good = (inv[:, 0] != inv[:, 1]) & (inv[:, 1] != inv[:, 2]) & (inv[:, 0] != inv[:, 2])
    inv, keep, Fg = inv[good], keep[good], F[good]
    used = np.unique(inv)
    remap = -np.ones(len(key), int)
    remap[used] = np.arange(len(used))
    faces = remap[inv]
    vn = np.zeros((len(used), 3))
    np.add.at(vn, faces.reshape(-1), N[Fg.reshape(-1)])
    return key[used], vn, faces, keep


def _normals(vn):
    """Unit normals on a coarse grid (7 steps, then 5): the KMD indexes them with 7 bits."""
    import numpy as np
    for steps in (3, 2, 1):
        nq = np.round(vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-9) * steps) / steps
        nq[np.all(nq == 0, axis=1)] = (0, 1, 0)
        keys, inv = np.unique(nq, axis=0, return_inverse=True)
        if len(keys) <= 127:
            unit = keys / np.maximum(np.linalg.norm(keys, axis=1, keepdims=True), 1e-9)
            return [(int(round(x * 4096)), int(round(y * 4096)), int(round(z * 4096)), 0) for x, y, z in unit], \
                inv.reshape(-1)
    raise ValueError("too many distinct normals for one KMD object")


def _object_bytes(nv: int, nn: int, nf: int) -> int:
    n = 8 * nv + 8 * nn + 18 * nf
    return n + (-n % 4)


def decimate(original: mgs_kmd.Kmd, per: dict, budget: int) -> tuple[dict, dict]:
    """Per-object meshes that together fit *budget* KMD bytes: {object: (verts, normals, faces, kept, normal index)}.
    Triangle targets follow the donor's own detail per object (an object keeps at least MIN_OBJECT_TRIS when its
    source has them), so a 550-triangle head no longer starves the hands; a factor shrinks them all until the packed
    size fits, and an object over 255 vertices / 127 normals is cut back on its own."""
    count = len(original.objects)
    fixed = mgs_kmd.HEADER.size + count * mgs_kmd.RECORD.size
    src = {i: len(per[i]["P"]) // 3 for i in range(count)}
    total = sum(src.values()) or 1
    cache: dict = {}
    cap = {i: src[i] for i in range(count)}

    def mesh(i, t):
        if (i, t) not in cache:
            v, vn, f, keep = _mesh(per[i]["P"], per[i]["N"], t)
            cache[(i, t)] = (v, vn, f, keep, *_normals(vn)) if len(f) else (v, vn, f, keep, [], [])
        return cache[(i, t)]
    f = min(1.0, (budget - fixed) / (30.0 * total))
    for _ in range(40):
        out, size = {}, fixed
        for i in range(count):
            if not src[i]:
                out[i] = None
                continue
            t = min(cap[i], max(min(src[i], MIN_OBJECT_TRIS), int(src[i] * f)))
            while True:
                m = mesh(i, t)
                if len(m[0]) <= 255 and len(m[4]) <= 127 or t <= 1:
                    break
                t = max(1, int(t * 0.8))
                cap[i] = t
            out[i] = m
            size += _object_bytes(len(m[0]), len(m[4]), len(m[2]))
        if size <= budget:
            return out, {"factor": round(f, 4), "bytes": size, "budget": budget, "source_triangles": src,
                         "triangles": {i: (len(m[2]) if m else 0) for i, m in out.items()}}
        f *= max(0.5, min(0.95, (budget - fixed) / max(size - fixed, 1)))
    raise ValueError(f"could not fit the model into the {budget}-byte KMD allocation")


def _reseat_chest(meshes: dict, tgt: dict, prop: dict):
    """Decimation rounds a stretched chest's neck ring down; stretch the kept vertices back up to the seated head."""
    import numpy as np
    j = SNAKE_ROLES["chest"]
    m = meshes.get(j)
    if not prop.get("chest_stretch") or not m or not len(m[0]):
        return
    v = np.array(m[0], np.int64)
    want = float(tgt["head_base"]) - float(tgt["T"][j][1])
    top = float(v[:, 1].max())
    if 0 < top < want - 0.01 * float(tgt["height"]):
        up = v[:, 1] > 0
        v[up, 1] = np.round(v[up, 1] * min(2.5, want / top)).astype(np.int64)
        meshes[j] = (v, *m[1:])


def assemble(original: mgs_kmd.Kmd, meshes: dict, face_tex: dict, weld_radius: float = WELD_RADIUS):
    """KMD objects from the per-object meshes; face_tex[i] = [(texture hash, 8 uv bytes)] per kept face (None: the
    model's own first texture of object FIT_TEXTURE_OBJECT).  -> (packed bytes, model, welds)."""
    src = original.objects[FIT_TEXTURE_OBJECT]
    tex0, uv0 = (src.textures[0], src.uvs[0]) if src.textures else (0, bytes(8))
    objs = []
    for i, o in enumerate(original.objects):
        m = meshes.get(i)
        if not m or not len(m[2]):
            objs.append(mgs_kmd.KmdObject(o.flags, o.pos, o.parent, o.unknown, bbox=o.bbox))
            continue
        v, _vn, t, _keep, normals, ninv = m
        verts = [(int(x), int(y), int(z), -1) for x, y, z in v]
        faces = [(int(a), int(b), int(b), int(c)) for a, b, c in t]       # a triangle is a quad a,b,b,c
        fn = [(int(ninv[a]), int(ninv[b]), int(ninv[b]), int(ninv[c])) for a, b, c in t]
        ft = face_tex.get(i)
        ftex = [x[0] for x in ft] if ft else [tex0] * len(faces)
        fuv = [x[1] for x in ft] if ft else [uv0] * len(faces)
        ko = mgs_kmd.KmdObject(o.flags, o.pos, o.parent, o.unknown, verts, list(normals), faces, fn, fuv, ftex)
        ko.bbox = ko.computed_bbox()
        objs.append(ko)
    model = mgs_kmd.Kmd(original.bones, original.bbox, objs)
    welds = 0
    if weld_radius:
        # welded child vertices follow the parent bone, so joints stay shut when the game's motion plays
        model, welds = mgs_kmd.weld_seams(original, model, radius=weld_radius)
    data = mgs_kmd.dumps(model, recompute_bbox=True)
    return data, model, welds


def _textures_of(original: mgs_kmd.Kmd) -> set[int]:
    return {t for o in original.objects for t in o.textures if t}


def fit_slot(originals: dict[int, bytes], rig: dict, scale: dict | None, archives: list[dict],
             weld_radius: float = WELD_RADIUS) -> dict:
    """One donor onto every model of a slot, for every texture archive the slot's models live with.

    originals: {model hash: the disc's KMD bytes}; rig: sm64_swap.load_rig(donor); archives: [{key, archive {hash:
    pcc bytes} (every texture of that place), bins {hash: DAR id} (optional)}] - one per place with its own texture
    copies (init; or each mission stage).  The geometry is fitted once per model; textures are painted once per
    archive over the faces of all the slot's models together (they share the texture names).
    -> {"models": {hash: {"report"}}, "archives": {key: {"kmd": {hash: bytes}, "painted": {hash: bytes},
    "report"}}}."""
    from . import fit_events as FE
    geo, out = {}, {"models": {}, "archives": {}}
    for h, raw in originals.items():
        original = mgs_kmd.loads(raw)
        prims, rep, tgt = fit_prims(original, rig, scale)
        per = split_objects(prims, tgt, len(original.objects))
        meshes, drep = decimate(original, per, len(raw))
        _reseat_chest(meshes, tgt, rep.get("proportion") or {})
        FE.weights([p for p in prims if not p.get("prop")], SNAKE_ROLES, skeleton=len(original.objects), word="object")
        FE.stage("decimate", data={"model": h, "budget": len(raw), "bytes": drep["bytes"],
                                   "source_triangles": sum(drep["source_triangles"].values()),
                                   "triangles": sum(drep["triangles"].values()), "factor": drep["factor"]})
        geo[h] = (original, per, meshes)
        out["models"][h] = {"report": {**{k: rep.get(k) for k in ("scale", "torso_up", "torso_down", "head_scale",
                                                                   "limb_stretch", "proportion", "profile")},
                                       "decimate": drep, "budget": len(raw)}}
    # the slots every model of the slot names (the soldier's 55267 lacks one of 38582's and has one 38582 lacks): a
    # face may only use a texture name its own model already uses (mgs_kmd.check_compatible)
    names = set.intersection(*(_textures_of(g[0]) for g in geo.values())) if geo else set()
    for arc in archives or [{"key": "untextured", "archive": None}]:
        archive = arc.get("archive") or {}
        mine = {}
        for t in sorted(names):
            if t in archive:
                try:
                    mine[t] = mgs_pcc.loads(archive[t])
                except ValueError:
                    pass
        flat, owner = [], []
        for h, (original, per, meshes) in geo.items():
            for i in range(len(original.objects)):
                m = meshes.get(i)
                if m:
                    flat += [per[i]["A"][int(s)] for s in m[3]]
                    owner += [(h, i)] * len(m[3])
        painted, face_tex, trep = {}, {}, {"textured": False}
        if mine and flat:
            try:
                painted, per_face, trep = mgs_vr_tex.paint(mine, archive, flat, bins=arc.get("bins"))
                trep["textured"] = True
                for (h, i), ft in zip(owner, per_face):
                    face_tex.setdefault(h, {}).setdefault(i, []).append(ft)
            except ValueError as e:                       # the textures don't fit / decode: an untextured fit
                painted, face_tex, trep = {}, {}, {"textured": False, "reason": str(e)}
        kmds, reps = {}, {}
        for h, (original, per, meshes) in geo.items():
            data, model, welds = assemble(original, meshes, face_tex.get(h, {}), weld_radius)
            if len(data) > len(originals[h]):
                raise ValueError(f"fitted KMD {h} is {len(data)} bytes; its allocation is {len(originals[h])}")
            issues = mgs_kmd.check_compatible(original, model, raw=data)
            if issues:
                raise ValueError("fitted KMD breaks the game contract: " + "; ".join(issues[:5]))
            kmds[h] = data
            reps[h] = {"kmd_bytes": len(data), "triangles": sum(len(o.faces) for o in model.objects), "welds": welds,
                       "per_object_triangles": [len(o.faces) for o in model.objects]}
        out["archives"][arc.get("key", "untextured")] = {"kmd": kmds, "painted": painted,
                                                          "report": {"models": reps, "textures": trep}}
        FE.stage("encode", data={"archive": str(arc.get("key"))[:40], "textured": bool(trep.get("textured")),
                                 "kmd_bytes": sum(len(b) for b in kmds.values()),
                                 "budget": sum(len(originals[h]) for h in kmds), "textures": len(painted)})
    return out


def fit_kmd(original_bytes: bytes, glb: Path, roles: dict, budget: int | None = None,
            weld_radius: float = WELD_RADIUS, scale: dict | None = None) -> tuple[bytes, dict]:
    """fit_kmd_textured without textures: every face wears the model's waist texture (the first fitted build)."""
    data, rep, _ = fit_kmd_textured(original_bytes, glb, roles, None, budget, weld_radius, scale)
    return data, rep


def fit_kmd_textured(original_bytes: bytes, glb: Path, roles: dict, textures: dict | None,
                     budget: int | None = None, weld_radius: float = WELD_RADIUS,
                     scale: dict | None = None) -> tuple[bytes, dict, dict]:
    """Retarget a skinned library GLB onto one 16-object KMD (Snake's by default) -> (KMD bytes, report, repainted
    textures).  With *textures* ({"snake": {hash: Pcc}, "archive": {hash: pcc bytes}}) every face keeps the library
    model's own image and UVs, painted into the model's texture slots (gbox.mgs_vr_tex)."""
    from . import sm64_swap as S
    raw = original_bytes
    if budget is not None and budget != len(raw):
        raise ValueError("the fit always fills the model's own allocation (budget = its KMD size)")
    rig = S.load_rig(Path(glb), roles)
    arcs = [{"key": "init", "archive": textures["archive"]}] if textures else []
    res = fit_slot({0: raw}, rig, scale, arcs, weld_radius)
    model_rep = res["models"][0]["report"]
    arc = next(iter(res["archives"].values()))
    data = arc["kmd"][0]
    mrep = arc["report"]["models"][0]
    rep = {**model_rep, **mrep, "budget": len(raw), "cluster_cell": 0.0, "textured": bool(arc["painted"])}
    if textures:
        rep["textures"] = arc["report"]["textures"]
    return data, rep, arc["painted"]


# ---------------------------------------------------------------------------------------------- the build (native)
class StageDir:
    """STAGE.DIR bytes being patched: same-size writes only, so every .stg keeps its sectors."""

    def __init__(self, data: bytes, strict: bool = True):
        if strict and len(data) not in STAGE_DIR_SIZES:
            raise ValueError("this MGS PS1 disc has an unknown STAGE.DIR size")
        self.orig = bytes(data)
        self.data = bytearray(data)
        self.writes: list[dict] = []

    def put(self, offset: int, size: int, body: bytes, what: str):
        if len(body) > size:
            raise ValueError(f"{what}: {len(body)} bytes do not fit its {size}-byte allocation")
        self.data[offset:offset + size] = body.ljust(size, b"\0")
        self.writes.append({"what": what, "offset": offset, "size": size})

    def repack_dar(self, dar_offset: int, dar_size: int, bodies: dict[int, bytes], what: str):
        """Repack the DAR at dar_offset with new bodies for some entries; the archive keeps its size (and anything
        after its last entry, e.g. a terminator)."""
        blob = bytes(self.data[dar_offset:dar_offset + dar_size])
        ents = dar_entries(blob)
        end = (ents[-1]["offset"] + ents[-1]["size"] + 3 & ~3) if ents else 0
        tail = blob[end:]
        parts = [(e["hash"], int(e["ext"], 16) if e["ext"].startswith("0x") else ord(e["ext"]),
                  bodies.get(e["hash"], blob[e["offset"]:e["offset"] + e["size"]])) for e in ents]
        new = mgs_vr_tex.pack_dar(parts, dar_size - len(tail)) + tail
        if len(new) != dar_size:
            raise ValueError(f"{what}: repacked archive is {len(new)} bytes, allocation {dar_size}")
        self.put(dar_offset, dar_size, new, what)

    def changed_runs(self):
        """[(offset, bytes)] runs of changed 2048-byte sectors."""
        runs, cur = [], None
        for off in range(0, len(self.data), 2048):
            if self.data[off:off + 2048] != self.orig[off:off + 2048]:
                if cur and cur[0] + len(cur[1]) == off:
                    cur[1].extend(self.data[off:off + 2048])
                else:
                    cur = [off, bytearray(self.data[off:off + 2048])]
                    runs.append(cur)
        return [(o, bytes(b)) for o, b in runs]


def write_disc(base: Path, stage: StageDir, out_bin: Path, progress=lambda _p, _m: None) -> dict:
    """Copy the owned BIN and rewrite only the changed STAGE.DIR sectors (new EDC/ECC); writes the .cue."""
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    part = out_bin.with_name(out_bin.name + ".part")
    progress(80, "Copying the original disc before the sector patch")
    shutil.copyfile(base, part)
    sectors = 0
    try:
        disc = psxdisc.RawBin(part)
        try:
            for off, blob in stage.changed_runs():
                sectors += disc.write_file("MGS/STAGE.DIR", off, blob)
        finally:
            disc.close()
        os.replace(part, out_bin)
    finally:
        part.unlink(missing_ok=True)
    out_bin.with_suffix(".cue").write_text(
        f'FILE "{out_bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    progress(95, f"Bootable disc ready; {sectors} raw sectors patched")
    return {"bin": str(out_bin), "cue": str(out_bin.with_suffix(".cue")), "sectors_written": sectors}


def read_stage_dir(base: Path) -> bytes:
    disc = psxdisc.RawBin(base, writable=False)
    try:
        return disc.read("MGS/STAGE.DIR")
    finally:
        disc.close()


def apply_slot(stage: StageDir, slot: str, rig: dict, scale: dict | None, label: str = "",
               weld_radius: float = WELD_RADIUS, progress=lambda _p, _m: None) -> dict:
    """Fit one donor into every place the slot's models live and write the results into *stage* (in memory).
    -> report {slot, models, stages, places: [...], textured}."""
    spec = SLOTS[slot]
    data = bytes(stage.data)
    sites = model_sites(data, spec["models"])
    if not sites:
        raise ValueError(f"{spec['name']}: none of the models {spec['models']} is on this disc")
    by_stage: dict[str, list[dict]] = {}
    for s in sites:
        by_stage.setdefault(s["stage"], []).append(s)
    originals = {}
    for s in sites:
        body = data[s["offset"]:s["offset"] + s["size"]]
        originals.setdefault(s["model"], body)
    if slot == "player" and hashlib.sha256(originals[PLAYER_MODEL]).hexdigest() != PLAYER_KMD_SHA256:
        raise ValueError("player KMD differs from the verified US VR Missions revision")
    # one texture archive per stage: every texture of the stage (CLUT neighbours are re-indexed with the palette)
    archives, dars = [], {}
    for name, ss in by_stage.items():
        texs = stage_textures(data, ss[0]["stage_offset"])
        arc, bins = {}, {}
        for k, d in enumerate(texs):
            for h, (o, n) in d["entries"].items():
                arc.setdefault(h, data[o:o + n])
                bins.setdefault(h, k)
        archives.append({"key": name, "archive": arc, "bins": bins})
        dars[name] = texs
    groups: dict[bytes, list[str]] = {}                   # stages whose models + textures are byte-identical fit once
    for a in archives:
        sig = hashlib.sha256(b"".join(originals[s["model"]] + data[s["offset"]:s["offset"] + s["size"]]
                                      for s in by_stage[a["key"]]) +
                             b"".join(struct.pack("<H", h) + a["archive"][h] for h in sorted(a["archive"]))).digest()
        groups.setdefault(sig, []).append(a["key"])
    firsts = [a for a in archives if any(a["key"] == g[0] for g in groups.values())]
    progress(10, f"{label or spec['name']}: fitting {len(originals)} model(s) for {len(archives)} place(s)")
    res = fit_slot({h: originals[h] for h in originals}, rig, scale, firsts, weld_radius)
    textured = 0
    for g in groups.values():
        r = res["archives"][g[0]]
        textured += len(g) if r["painted"] else 0
        for name in g:
            for s in by_stage[name]:
                stage.put(s["offset"], s["size"], r["kmd"][s["model"]], f"{name}/{s['model']}.kmd")
            if r["painted"]:
                for k, d in enumerate(dars[name]):
                    bodies = {h: b for h, b in r["painted"].items() if h in d["entries"]}
                    if bodies:
                        stage.repack_dar(d["offset"], d["size"], bodies, f"{name} texture archive {k}")
    return {"slot": slot, "name": spec["name"], "models": {str(h): res["models"][h]["report"] for h in res["models"]},
            "stages": sorted(by_stage), "places": len(sites), "textured_stages": textured,
            "archives": {k: v["report"] for k, v in list(res["archives"].items())[:3]}}


def build_slots(base: Path, out_bin: Path, plan: list[tuple[str, dict, dict | None]], progress=lambda _p, _m: None,
                labels: dict | None = None) -> dict:
    """Build one disc: plan = [(slot, rig (sm64_swap.load_rig), rig scale)].  Every slot is fitted and written into one
    staged STAGE.DIR; a slot that fails is reported and the others still build.  -> {bin, cue, sectors_written,
    slots: {slot: {status, reason? , report?}}}."""
    from . import fit_events as FE
    stage = StageDir(read_stage_dir(base))
    per = {}
    for k, (slot, rig, scale) in enumerate(plan):
        FE.model(slot, (labels or {}).get(slot))
        try:
            per[slot] = {"status": "built", "report": apply_slot(
                stage, slot, rig, scale, (labels or {}).get(slot, slot),
                progress=lambda p, m, k=k: progress(5 + 70 * (k + p / 100) / max(1, len(plan)), m))}
        except Exception as e:                             # noqa: BLE001 - one slot never stops the others
            per[slot] = {"status": "failed", "reason": str(e)[:500] or type(e).__name__}
            FE.stage("write", "failed", {"reason": per[slot]["reason"][:150]})
    if not any(r["status"] == "built" for r in per.values()):
        return {"slots": per, "sectors_written": 0}
    out = write_disc(base, stage, out_bin, progress)
    for slot, r in per.items():                           # the write stage of every built slot: where it went
        if r["status"] == "built":
            FE.model(slot, (labels or {}).get(slot))
            FE.stage("write", data={"image": Path(out["bin"]).name, "stages": len(r["report"]["stages"]),
                                    "models": r["report"]["places"], "textured_stages": r["report"]["textured_stages"],
                                    "sectors": out["sectors_written"]})
    return out | {"slots": per}


def _mint(cfg) -> Path:
    candidates = [os.environ.get("GBOX_METAL_MINT"),
                  Path(cfg.cache).parent / "runtime" / "tools" / "metal_mint" / "MetalMintSolid.exe",
                  shutil.which("MetalMintSolid")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError("MetalMintSolid is required to rebuild the MGS PS1 stage archive")


def _run(mint: Path, *args: str | Path) -> None:
    result = subprocess.run([str(mint), *(str(a) for a in args)], capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"MetalMintSolid {' '.join(map(str, args[:2]))}: {(result.stderr or result.stdout)[-1200:]}")


def base_bin(cfg, progress=lambda _p, _m: None) -> Path:
    """Unpack the operator's QuickSwap US disc once; both catalog entries use it."""
    archive = cfg.library("quickswap-root").root() / f"{DISC_NAME}.7z"
    out = Path(cfg.cache) / "modbase" / "mgs_vr_us"
    image = out / f"{DISC_NAME}.bin"
    if image.is_file() and image.stat().st_size == DISC_BYTES:
        return image
    if not archive.is_file():
        raise FileNotFoundError(f"VR Missions source archive is not reachable: {archive}")
    seven_zip = shutil.which("7z") or shutil.which("7zz") or Path(r"C:\Program Files\7-Zip\7z.exe")
    if not seven_zip or not Path(seven_zip).is_file():
        raise FileNotFoundError("7-Zip is required to unpack the VR Missions source archive")
    out.mkdir(parents=True, exist_ok=True)
    progress(5, "Unpacking the original VR Missions disc")
    result = subprocess.run([str(seven_zip), "x", "-y", f"-o{out}", str(archive)],
                            capture_output=True, text=True, timeout=1800)
    if result.returncode or not image.is_file():
        raise RuntimeError(f"VR Missions archive extraction failed: {(result.stderr or result.stdout)[-1200:]}")
    return image


def decode_original_player(cfg, out_glb: Path, progress=lambda _p, _m: None) -> Path:
    """Read Snake's original VR Missions KMD and its PS1 textures into a textured GLB."""
    base = base_bin(cfg, progress)
    disc = psxdisc.RawBin(base, writable=False)
    try:
        stage_dir_bytes = disc.read("MGS/STAGE.DIR")
    finally:
        disc.close()
    if len(stage_dir_bytes) not in STAGE_DIR_SIZES:
        raise ValueError("this MGS PS1 disc has an unknown STAGE.DIR size")
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    mint = _mint(cfg)
    with tempfile.TemporaryDirectory(prefix="mgs_vr_read_", dir=out_glb.parent) as temp:
        work = Path(temp)
        (work / "stage.dir").write_bytes(stage_dir_bytes)
        for name in ("stage", "init", "models", "texture_archive", "textures"):
            (work / name).mkdir()
        progress(20, "Opening the VR Missions stage archive")
        _run(mint, "dir", "extract", work / "stage.dir", work / "stage")
        _run(mint, "stg", "extract", work / "stage" / "init.stg", work / "init")
        _run(mint, "dar", "extract", work / "init" / "0_0.dar", work / "models", "--platform", "Psx")
        original = work / "models" / "39213.kmd"
        if hashlib.sha256(original.read_bytes()).hexdigest() != PLAYER_KMD_SHA256:
            raise ValueError("Snake KMD differs from the known US VR Missions revision")
        progress(60, "Decoding Snake's PS1 texture archive")
        _run(mint, "dar", "extract", work / "init" / "1_0.dar", work / "texture_archive", "--platform", "Psx")
        _run(mint, "pcx", "batchdecode", work / "texture_archive", work / "textures")
        progress(80, "Converting the original Snake mesh and textures to glTF")
        _run(mint, "kmd", "decode", original, work / "snake.glb", "--textures", work / "textures")
        if (work / "snake.glb").read_bytes()[:4] != b"glTF":
            raise ValueError("MetalMintSolid did not produce a GLB model")
        shutil.copy2(work / "snake.glb", out_glb)
    progress(100, "Original Snake model and textures decoded")
    return out_glb


def build(base: Path, replacement_kmd: Path | None, out_bin: Path, mint: Path,
          progress=lambda _p, _m: None, fit=None, textures: bool = False) -> dict:
    """Build a bootable modded BIN/CUE from an owned raw disc and a fitted player KMD with MetalMintSolid (the first
    writer; gbox.mgs1_swap still uses it for the MGS disc).  VR Missions builds go through build_slots().

    *fit*, when given, is called with the disc's own player KMD bytes and returns the replacement (see
    :func:`fit_kmd`); otherwise *replacement_kmd* is read.  With *textures*, fit is called as fit(kmd, {"snake",
    "archive"}) and returns (kmd, {hash: repainted pcc}); the texture DAR (init.stg entry 1) is repacked to its
    original size and patched in as well (gbox.mgs_vr_tex).
    """
    original = psxdisc.RawBin(base, writable=False)
    try:
        stage_dir_bytes = original.read("MGS/STAGE.DIR")
    finally:
        original.close()
    if len(stage_dir_bytes) not in STAGE_DIR_SIZES:
        raise ValueError("this MGS PS1 disc has an unknown STAGE.DIR size")
    work_parent = out_bin.parent
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mgs_vr_", dir=work_parent) as temp:
        work = Path(temp)
        directory = work / "stage.dir"
        directory.write_bytes(stage_dir_bytes)
        progress(25, "Extracting the PS1 stage containers")
        # MetalMintSolid creates a relative directory when a requested output
        # directory does not exist, so create each absolute target first.
        for name in ("stage", "init", "dar"):
            (work / name).mkdir()
        _run(mint, "dir", "extract", directory, work / "stage")
        init = work / "stage" / "init.stg"
        if not init.is_file():
            raise ValueError("init.stg was absent from the stage directory")
        init_bytes = init.read_bytes()
        init_offset = stage_dir_bytes.find(init_bytes)
        if init_offset < 0 or init_offset % 2048 or stage_dir_bytes.find(init_bytes, init_offset + 1) >= 0:
            raise ValueError("init.stg does not have one aligned location in the stage directory")
        _run(mint, "stg", "extract", init, work / "init")
        _run(mint, "dar", "extract", work / "init" / "0_0.dar", work / "dar", "--platform", "Psx")
        model = work / "dar" / "39213.kmd"
        own_kmd = model.read_bytes()
        if hashlib.sha256(own_kmd).hexdigest() != PLAYER_KMD_SHA256:
            raise ValueError("player KMD differs from the verified US VR Missions revision")
        painted = {}
        tex_dar = (work / "init" / "1_0.dar").read_bytes() if (work / "init" / "1_0.dar").is_file() else b""
        if fit and textures:
            if not tex_dar:
                raise ValueError("init.stg has no texture archive (1_0.dar)")
            archive = {h: body for h, _e, body in mgs_vr_tex.parse_dar(tex_dar)}
            names = {t for o in mgs_kmd.loads(own_kmd).objects for t in o.textures}
            donor, painted = fit(own_kmd, {"snake": {h: mgs_pcc.loads(archive[h]) for h in names},
                                           "archive": archive})
        else:
            donor = fit(own_kmd) if fit else replacement_kmd.read_bytes()
        if fit:
            replacement_kmd = work / "replacement.kmd"
            replacement_kmd.write_bytes(donor)
        if not donor or len(donor) > len(own_kmd):
            raise ValueError(f"replacement KMD exceeds its {len(own_kmd)}-byte disc budget")
        if donor == own_kmd:
            raise ValueError("replacement KMD is identical to the original player model")
        # The game's own contract (gbox.mgs_kmd): same skeleton records, word-aligned
        # SVECTOR arrays, in-range welds and weld-export flags.  The first HUcast KMD
        # broke the alignment and flag rules and corrupted the whole frame (#848).
        try:
            issues = mgs_kmd.check_compatible(mgs_kmd.loads(own_kmd), mgs_kmd.loads(donor), raw=donor)
        except ValueError as exc:
            issues = [f"unreadable KMD: {exc}"]
        if issues:
            raise ValueError("replacement KMD would break the game: " + "; ".join(issues[:6]))
        # Structural validation: MetalMintSolid must be able to decode the donor as a PS1 KMD.
        # A malformed KMD passes the size check but will hang the game's loader (black screen / hung core).
        progress(33, "Validating replacement KMD structure")
        validate_glb = work / "validate.glb"
        try:
            _run(mint, "kmd", "decode", replacement_kmd, validate_glb)
        except RuntimeError as exc:
            raise ValueError(f"replacement KMD failed KMD decode validation: {exc}") from exc
        if not validate_glb.is_file() or validate_glb.read_bytes()[:4] != b"glTF":
            raise ValueError("replacement KMD decoded to an invalid GLB")
        model.write_bytes(donor.ljust(len(own_kmd), b"\0"))
        order = work / "dar" / "order.txt"
        if not order.is_file():
            raise ValueError("DAR extraction omitted its archive order")
        progress(45, "Rebuilding the player model archive")
        new_dar = work / "player.dar"
        _run(mint, "dar", "pack", work / "dar", new_dar, "--platform", "Psx", "--order", order)
        if new_dar.stat().st_size != (work / "init" / "0_0.dar").stat().st_size:
            raise ValueError("replacement DAR changed its stage allocation")
        new_init = work / "new_init.stg"
        _run(mint, "stg", "patch", new_dar, init, "0", new_init)
        if painted:
            progress(55, "Repainting Snake's texture slots with the character's own textures")
            entries = mgs_vr_tex.parse_dar(tex_dar)
            for h, body in painted.items():
                mgs_pcc.loads(body)                        # every repainted texture must decode
            new_tex = work / "textures.dar"
            new_tex.write_bytes(mgs_vr_tex.pack_dar([(h, e, painted.get(h, b)) for h, e, b in entries], len(tex_dar)))
            textured_init = work / "new_init_tex.stg"
            _run(mint, "stg", "patch", new_tex, new_init, "1", textured_init)
            new_init = textured_init
        patched_init = new_init.read_bytes()
        if len(patched_init) != len(init_bytes):
            raise ValueError("replacement init.stg changed its directory allocation")
        changed = bytearray(stage_dir_bytes)
        changed[init_offset:init_offset + len(init_bytes)] = patched_init
        progress(65, "Copying the original disc before the sector patch")
        part = out_bin.with_name(out_bin.name + ".part")
        shutil.copyfile(base, part)
        sectors = 0
        try:
            disc = psxdisc.RawBin(part)
            try:
                # Only changed 2 KiB sectors need new EDC/ECC (eight for HUcast).
                for off in range(0, len(stage_dir_bytes), 2048):
                    if changed[off:off + 2048] != stage_dir_bytes[off:off + 2048]:
                        sectors += disc.write_file("MGS/STAGE.DIR", off, changed[off:off + 2048])
            finally:
                disc.close()
            os.replace(part, out_bin)
        finally:
            part.unlink(missing_ok=True)
    out_bin.with_suffix(".cue").write_text(
        f'FILE "{out_bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    progress(95, f"Bootable disc ready; {sectors} raw sectors patched")
    return {"bin": str(out_bin), "cue": str(out_bin.with_suffix(".cue")),
            "sectors_written": sectors, "kmd_sha256": hashlib.sha256(donor).hexdigest(),
            "textures_repainted": sorted(painted)}


def _publish(ctx, folder: Path, gid: str, mod_name: str = MOD_NAME) -> None:
    """Send a newly built mod to the central collection, including same-size rebuilds."""
    import httpx

    if not ctx.server:
        return
    url = f"{ctx.server}/api/modfiles/{gid}/{mod_name}"
    response = httpx.get(url, headers=ctx.headers, timeout=60)
    if response.status_code not in (200, 404):
        response.raise_for_status()
    have = {f["path"]: f for f in response.json().get("files", [])} if response.status_code == 200 else {}
    files = sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.name == ".gbox-mod.json")
    for file in files:
        with file.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        old = have.get(file.name) or {}
        if old.get("sha256") == digest and old.get("size") == file.stat().st_size:
            continue
        with file.open("rb") as stream:
            result = httpx.put(f"{url}/file/{file.name}", headers=ctx.headers,
                               content=stream, timeout=1200)
        result.raise_for_status()


# ---------------------------------------------------------------------------------------------- mods
def mod_name(slug: str, slot: str = "player") -> str:
    """The player build keeps its first fitted name (mgs_vr_<slug>_fit); other slots get their own."""
    if slot == "player":
        return f"mgs_vr_{slug}_fit"
    return f"mgs_vr_{slug}_{re.sub(r'[^a-z0-9]+', '_', slot.lower()).strip('_')}"


def plan_mod_name(rows: list[tuple[str, str]]) -> str:
    """[(slot, donor slug)] -> the mod that holds exactly that plan (one row: the single-slot name)."""
    rows = sorted(set(rows), key=lambda r: list(SLOTS).index(r[0]) if r[0] in SLOTS else 99)
    if len(rows) == 1:
        return mod_name(rows[0][1], rows[0][0])
    digest = hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:10]
    return f"mgs_vr_cast_{digest}"


def build_mod(ctx, game: dict, rows: list[tuple[str, dict]], name: str, inp=None) -> dict:
    """Build mod *name* for *game* holding [(slot, collection meta)] on this node (native writer), publish it.
    -> {mod, slots: {slot: {status, reason?}}, build}."""
    from . import characters as chars, filemods, oot_swap, sm64_swap as S
    from . import fit_events as FE, retarget_profile as RP
    gid = game["game_id"]
    folder = filemods.mod_dir(ctx.config, gid, name)
    plan, labels, metas = [], {}, {}
    FE.plan([(slot, meta["slug"], f"{meta.get('name', meta['slug'])} -> {SLOTS[slot]['name']}") for slot, meta in rows])
    for slot, meta in rows:
        meta = RP.apply_to_meta(meta, gid, slot)          # the operator's Retarget editor profile for this slot
        glb = chars._local_or_fetch(ctx, meta, meta["model"])
        roles = oot_swap.roles_of(meta, glb)
        rig = S.load_rig(glb, roles, [p["node"] for p in meta.get("props") or []])
        plan.append((slot, rig, (meta.get("rig") or {}).get("scale")))
        labels[slot] = f"{meta.get('name', meta['slug'])} -> {SLOTS[slot]['name']}"
        metas[slot] = meta
    source = base_bin(ctx.config, ctx.progress)
    res = build_slots(source, folder / f"{DISC_NAME}.bin", plan, ctx.progress, labels)
    built = [s for s, r in res["slots"].items() if r["status"] == "built"]
    if not built:
        return {"mod": None, "slots": res["slots"], "build": res}
    rec = {"name": name, "game_id": gid, "image": f"{DISC_NAME}.cue", "built": time.time(), "textured": True,
           "writer": "gbox.mgs_vr_swap (native)", "character": rows[0][1]["slug"] if len(rows) == 1 else None,
           "cast": [{"slot": s, "character": metas[s]["slug"], **{k: v for k, v in res["slots"][s].items()
                                                                  if k in ("status", "reason")}} for s, _m in rows],
           "files": ["MGS/STAGE.DIR"], "verified_in_game": False,
           # how this exact disc is built again (special builds menu); op=use / cast_swap calls record their own
           "recipe": {"tool": "characters", "input": {"op": "use", "character": rows[0][1]["slug"], "game_id": gid,
                                                      "slot": "cast", "title": name, "launch": False, "rebuild": True,
                                                      "pairs": [{"slot": s, "character": m["slug"]} for s, m in rows]},
                      "recorded": time.time()},
           "report": {"sectors_written": res.get("sectors_written"),
                      "slots": {s: (r.get("report") or {}).get("stages", [])[:4] for s, r in res["slots"].items()}}}
    (folder / ".gbox-mod.json").write_text(json.dumps(rec, default=str))
    _publish(ctx, folder, gid, name)
    return {"mod": name, "slots": {s: {k: v for k, v in r.items() if k != "report"} for s, r in res["slots"].items()},
            "build": {k: v for k, v in res.items() if k != "slots"} | {"reports": {s: r.get("report")
                                                                                  for s, r in res["slots"].items()}}}


def _windows_worker(ctx) -> str | None:
    from . import characters as chars
    return next((w["id"] for w in chars._api(ctx, "GET", "/api/workers")
                 if w.get("os") == "windows" and w.get("online")), None)


def _can_build_here(ctx) -> bool:
    try:
        base_bin(ctx.config, ctx.progress)
        return True
    except (FileNotFoundError, RuntimeError, OSError, KeyError, ValueError):
        return False


def build_cast(ctx, game: dict, pairs: list[tuple[str, dict]], name: str, inp=None) -> dict:
    """gbox.cast_swap's pairs builder: every (slot, donor meta) in one disc; on a node without the disc image the
    build runs as one characters op=use slot=cast job on a Windows worker."""
    from . import characters as chars
    rows = [(slot_of(s) or s, m) for s, m in pairs]
    bad = [s for s, _m in rows if s not in SLOTS]
    if bad:
        raise ValueError(f"unknown VR Missions slots {bad}")
    if not _can_build_here(ctx):
        worker = _windows_worker(ctx)
        if not worker:
            raise RuntimeError("no node here or online Windows worker can reach the VR Missions disc image")
        j = chars._job(ctx, "characters", {"op": "use", "character": rows[0][1]["slug"], "game_id": game["game_id"],
                                           "slot": "cast", "title": name, "rebuild": True, "launch": False,
                                           "pairs": [{"slot": s, "character": m["slug"]} for s, m in rows]},
                       worker, 7200)
        if j.get("state") != "succeeded":
            raise RuntimeError(f"Windows VR Missions cast build {j.get('state')}: {j.get('error')}")
        r = (j.get("output") or {}).get("result") or {}
        return {"mod": r.get("mod"), "slots": r.get("slots") or {}, "detail": {"built_by": j.get("id")}}
    return build_mod(ctx, game, rows, name, inp)


def _rows_of_mod(cfg, gid: str, mod: str | None) -> list[tuple[str, str]]:
    """The (slot, donor slug) rows a built VR Missions mod holds (its marker), [] for anything else."""
    from . import filemods
    if not mod or not mod.startswith("mgs_vr_"):
        return []
    try:
        rec = json.loads((filemods.mod_dir(cfg, gid, mod.split(filemods.STAGED_SEP)[0]) / ".gbox-mod.json").read_text())
    except (OSError, ValueError):
        return []
    rows = [(r["slot"], r["character"]) for r in rec.get("cast") or [] if r.get("status", "built") == "built"
            and r.get("slot") in SLOTS and r.get("character")]
    if not rows and rec.get("character"):
        rows = [("player", rec["character"])]
    return rows


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use: the character into slot=player | enemy:soldier | enemy:ninja | model:<hash> | enemies | all,
    or slot=cast with pairs [{slot, character}]; build the disc, offer it as Play, and (session_id / a running VR
    Missions session) apply it to the running game through session_swap, keeping the moment."""
    from . import characters as chars
    gid = game["game_id"]
    slot_in = (inp.slot or "player").strip().lower()
    if slot_in == "cast":
        rows_meta = []
        collection = chars._api(ctx, "GET", "/api/characters") if inp.pairs else []
        for p in inp.pairs or []:
            s = slot_of(p.get("slot") or "")
            m = chars.best_match(collection, p.get("character") or "")
            if not s or not m:
                raise ValueError(f"cast pair {p}: needs a VR Missions slot and a collection character")
            rows_meta.append((s, m))
        if not rows_meta:
            raise ValueError("slot=cast needs pairs [{slot, character}]")
        name = inp.title or plan_mod_name([(s, m["slug"]) for s, m in rows_meta])
    else:
        rows_meta = [(s, meta) for s in slots_of(slot_in)]
        name = plan_mod_name([(s, meta["slug"]) for s, _m in rows_meta])
    from . import filemods
    folder = filemods.mod_dir(ctx.config, gid, name)
    marker = folder / ".gbox-mod.json"
    try:
        current = json.loads(marker.read_text()) if marker.is_file() else {}
    except ValueError:
        current = {}
    fresh = bool(current.get("textured")) and current.get("writer", "").startswith("gbox.mgs_vr_swap (native)")
    report = None
    if inp.rebuild or not fresh:
        if chars.HOST_OS != "windows" and not _can_build_here(ctx):
            worker = _windows_worker(ctx)
            if not worker:
                raise RuntimeError("No online Windows worker can build the MGS VR disc")
            body = {"op": "use", "character": meta["slug"], "game_id": gid, "slot": inp.slot, "rebuild": True,
                    "launch": False, "pairs": list(inp.pairs or []), "title": name}
            j = chars._job(ctx, "characters", body, worker, 7200)
            if j.get("state") != "succeeded":
                raise RuntimeError(f"Windows MGS VR build failed: {j.get('error') or j.get('state')}")
            report = (j.get("output") or {}).get("result")
        else:
            report = build_mod(ctx, game, rows_meta, name, inp)
            if not report.get("mod"):
                why = "; ".join(f"{s}: {r.get('reason')}" for s, r in report["slots"].items())
                raise RuntimeError(f"VR Missions build failed: {why}")
        for s, m in rows_meta:
            chars._api(ctx, "POST", f"/api/characters/{m['slug']}/targets", json={
                "game_id": gid, "slot": s, "mod": name, "nodes": ["windows"],
                "notes": f"Native PS1 KMD fitted onto {SLOTS[s]['name']} (16 objects), its own textures painted into "
                         "the model's texture slots; gameplay verification pending."})
        title = (f"{meta.get('name', meta['slug'])} as {SLOTS[rows_meta[0][0]]['name']} in Metal Gear Solid VR Missions"
                 if len(rows_meta) == 1 else
                 f"Metal Gear Solid VR Missions cast: " + ", ".join(f"{m.get('name', m['slug'])} as {SLOTS[s]['name']}"
                                                                     for s, m in rows_meta))
        chars._api(ctx, "POST", "/api/mods", json={"title": title[:200],
                   "calls": [{"tool": "@launch", "input": {"mod": name}}], "game_id": gid,
                   "game_title": game["title"], "desc": "Native PS1 KMD retargeted onto the game's 16-object figures.",
                   "verified": False, "requests": [848, 1597]})
    launched = None
    if inp.launch and inp.session_id:                      # the running game gets it in place (session_swap)
        launched = swap_into_session(ctx, gid, name, inp.session_id, wait=False)
    elif inp.launch:
        launched = chars._launch(ctx, gid, name, "windows")   # a running VR Missions session gets it in place too
    return {"status": "built" if report else "ready", "mod": name, "slots": [s for s, _m in rows_meta],
            "build": report, "launch": launched,
            "message": f"{', '.join(SLOTS[s]['name'] for s, _m in rows_meta)}: "
                       f"{'built into' if report else 'ready in'} {name} for VR Missions"
                       + (" and applied to the running game (session_swap keeps the moment)"
                          if inp.session_id and inp.launch else "")
                       + "; unverified in game until seen on screen."}


def swap_into_session(ctx, gid: str, mod: str, sid: str, wait: bool = True, limit: float = 1500) -> dict:
    """Put *mod* into the running session *sid* (server session_swap: save the moment, launch the mod on the same PC,
    load the moment, close the old copy)."""
    from . import characters as chars
    j = chars._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": mod,
                                                                                "session_id": sid}})
    out = {"job": j.get("id"), "state": j.get("state"), "session_id": sid}
    t0 = time.time()
    while wait and j.get("state") in ("queued", "running") and time.time() - t0 < limit:
        time.sleep(2)
        j = chars._api(ctx, "GET", f"/api/jobs/{j['id']}")
    if wait:
        res = j.get("output") or {}
        out |= {"state": j.get("state"), "error": j.get("error"), "new_session_id": res.get("session_id"),
                "state_loaded": res.get("state_loaded"), "notes": res.get("notes")}
    return out


# ---------------------------------------------------------------------------------------------- live (pick whip)
def resolve_slot(ctx, game: dict, inp) -> dict:
    """The slot under a picture point of the running VR Missions session (mgs_vr op=pick: the actors projected through
    the game's own view matrix), or the named slot."""
    from . import characters as chars
    if inp.x is None or inp.y is None:
        s = slot_of(inp.slot or "player") or "player"
        return {"slot": s, "name": SLOTS[s]["name"], "kind": SLOTS[s]["kind"], "how": "named"}
    sid = inp.session_id
    try:
        from .tools import SESSIONS
        local = sid in SESSIONS
    except Exception:                                      # noqa: BLE001 - the control plane has no live sessions
        local = False
    args = {"x": float(inp.x), "y": float(inp.y), "window_aspect": float(getattr(inp, "window_aspect", 0) or 4 / 3)}
    if local:
        from . import mgs_vr_tool as T
        ad, g = SESSIONS[sid]
        r = T.run(ad, g.get("title", ""), "pick", **args)
    else:
        j = chars._job(ctx, "mgs_vr", {"session_id": sid, "op": "pick", **args}, sid.split("-")[0], 60)
        if j.get("state") != "succeeded":
            raise RuntimeError(f"mgs_vr pick on the session {j.get('state')}: {j.get('error')}")
        r = (j.get("output") or {}).get("result") or {}
    if r.get("error"):
        raise LookupError(r["error"])
    p = r.get("picked")
    if not p:
        raise LookupError(f"no Snake or soldier under ({inp.x:.2f}, {inp.y:.2f}) of the picture"
                          + (f"; nearest: {r['actors'][0]['name']} at {r['actors'][0]['screen']}" if r.get("actors")
                             else ""))
    return {"slot": p["slot"], "name": SLOTS[p["slot"]]["name"], "kind": SLOTS[p["slot"]]["kind"], "how": "picked",
            "actor": p, "stage": r.get("stage"), "others": r.get("actors", [])[:4]}


def live_use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=live_use on a running VR Missions session: the slot under the pick (or slot=), a disc holding
    the session's current VR Missions mod plus this replacement (stacked: Snake stays replaced when the soldiers are
    replaced next), applied through session_swap so the game comes back at the same moment."""
    from . import characters as chars
    sid = inp.session_id
    if not sid:
        raise ValueError("live_use needs a running session_id")
    session = chars._session(ctx, sid)
    if not session or session.get("state") != "running" or session.get("game_id") != game["game_id"]:
        raise ValueError("the selected game session is no longer running")
    if not _can_build_here(ctx):                           # the PC the game runs on has the disc image: build there
        j = chars._job(ctx, "characters", inp.model_dump() if hasattr(inp, "model_dump") else dict(vars(inp)),
                       sid.split("-")[0], 7200)
        if j.get("state") != "succeeded":
            raise RuntimeError(f"live replacement on the game's PC {j.get('state')}: {j.get('error')}")
        return (j.get("output") or {}).get("result") or {}
    target = resolve_slot(ctx, game, inp)
    slot, gid = target["slot"], game["game_id"]
    rows = [r for r in _rows_of_mod(ctx.config, gid, session.get("mod")) if r[0] != slot] + [(slot, meta["slug"])]
    name = plan_mod_name(rows)
    from . import filemods
    have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").is_file()
    built = None
    if not have or inp.rebuild:
        catalog = {m["slug"]: m for m in chars._api(ctx, "GET", "/api/characters")}
        metas = [(s, meta if c == meta["slug"] else catalog.get(c)) for s, c in rows]
        metas = [(s, m) for s, m in metas if m]
        built = build_mod(ctx, game, metas, name, inp)
        if not built.get("mod") or built["slots"].get(slot, {}).get("status") != "built":
            why = built["slots"].get(slot, {}).get("reason") or "no slot was built"
            return {"status": "failed", "in_engine": False, "session_preserved": True, "slot": slot,
                    "message": f"{meta['name']} could not be built into {target['name']}: {why}. The game was left "
                               "running unchanged.", "build": built}
    swap = swap_into_session(ctx, gid, name, sid)
    ok = swap.get("state") == "succeeded"
    return {"status": "live_swapped" if ok else "failed", "in_engine": ok, "session_preserved": True,
            "character": meta["name"], "slot": slot, "replaces": target["name"], "target": target, "mod": name,
            "stacked": [r for r in rows if r[0] != slot], "swap": swap, "build": built,
            "message": (f"{meta['name']} replaces {target['name']} in the running game; session_swap restored your "
                        f"moment ({'state loaded' if swap.get('state_loaded') else 'state load not confirmed'})."
                        if ok else f"The {name} disc is built but applying it failed: {swap.get('error')}. "
                        "Your game was kept running.")}
