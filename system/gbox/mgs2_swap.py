"""Metal Gear Solid 2: Substance (PS2 SLUS-20554) character writer: any collection character in place of Snake, Raiden,
the soldiers or the main cast.

A mod is a patched copy of the DVD image: the vanilla two-layer ISO is unpacked from the catalog CHD once per game
(``cache/modbase/<game>/``), copied into the mod folder, and only the stages that carry a replaced model are rewritten
in place inside ``MGS2/STAGE.DAT`` / ``STAGE2.DAT`` (every stage keeps its sector span; the TOC is untouched).

Per slot (``SLOTS``) and per stage that carries one of its models:

1. **fit**: the donor (collection GLB + ``rig.roles``) is retargeted onto that model's own skeleton
   (``sm64_swap.retarget`` with the kms body roles: rigid per limb, one bone per vertex, the game's rest pose; a chibi
   head is shrunk to ~1.3 x the cast's head) - the retarget's scale / retarget / proportion fit events land on the
   slot's model, then weights / decimate / encode / write.
2. **kms**: the original header and bone records (offsets, parents, flags) are kept; every bone gets the donor
   triangles whose deepest corner bone it is, as triangle strips (greedy, <= 32 vertices per part, the game's strip
   parity: an even triangle is counter-clockwise), positions relative to the bone in millimetres, the weight word
   4096 on the bone or 0 for a corner on its parent (a two-bone blend part). The file is zero-padded to the original
   size (no offset in the stage moves); too many triangles -> vertex clustering per bone until it fits.
3. **texture**: the donor's textures are packed into one A x A 8-bit atlas (A = 512 / 256 / 128, median-cut palette)
   written into the model's texture pack: into a PSMT8 page region that only the slot's own textures use, with a CLUT
   only they use; one of those textures (the hijacked entry) is pointed at the atlas (TEX0 / CLAMP / rect) and every
   part uses it. Accessory models of the slot (Snake's bandana tails, Raiden's hair) become degenerate (invisible).
4. **stage**: every page holding a changed file is re-deflated and re-encrypted (``mgs2_inventory.rebuild_stage``);
   the stage must still fit its sectors (else the slot's models are encoded smaller and the stage is rebuilt again).
5. every written stage is read back from the image (header, pages, kms parse, atlas decode).

Unverified in game: the operator's PCSX2 run is the remaining check (docs/mgs2.md).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from . import mgs2_inventory as inv
from . import mgs2_models as M
from .ps2_gs import GSMemory, alpha_to_gs, csm1

GAME_IDS = dict(inv.GAME_IDS)
MAX_PART = 32                         # vertices per part (one VU batch, as every original part)
MAX_STRIP = 30
NRM_FLAG = 0x0FFF                     # the low 12 bits every original normal's flag word carries
CLUSTER = (0.0, 0.004, 0.007, 0.011, 0.016, 0.024, 0.035, 0.05, 0.07)
ATLAS = (512, 256, 128, 64)
H = inv.name_hash

# the soldiers' hands and eyes are separate models drawn on the hand / head bones (shared by every soldier of the
# family in a stage: replacing one family's slot hides them for that family's other soldier type too)
GBS_PARTS = [H("gbs_hand_def")] + [H(f"gbs_eye{i}") for i in range(5)]
GPS_PARTS = [H("gps_hand_def")] + [H(f"gps_eye{i}") for i in range(5)]
# slot -> (display name, kind, model hashes it replaces, accessory models made invisible)
SLOTS = {
    "snake": ("Solid Snake", "player", [H("sna_def"), 0x55AB65, 0xBFA829, H("sna_shadow")],
              [H("sna_mugen_bdn1"), H("sna_mugen_bdn2"), 0xCAED09]),
    "pliskin": ("Iroquois Pliskin", "player", [0x1A1AB0], []),
    "raiden": ("Raiden", "player", [H("rai_def"), 0xB41E89, H("rai_def_mt"), H("rai_shadow")], [0xCAD689]),
    "raiden_naked": ("Raiden (naked)", "player", [H("rai_naked"), 0x064E76], [0xCAD689]),
    "raiden_disguise": ("Raiden (soldier disguise)", "player", [0xFF6AB6, 0xB709C9], []),
    "soldier_tanker": ("Gurlukovich soldiers (Tanker)", "enemy", [H("gbs_def")], GBS_PARTS),
    "soldier_tanker_heavy": ("Gurlukovich heavy soldiers (Tanker)", "enemy", [0xC9AAAF], GBS_PARTS),
    "soldier_plant": ("Gurlukovich soldiers (Big Shell)", "enemy", [0xD83AAF], GPS_PARTS),
    "soldier_plant_heavy": ("Gurlukovich heavy soldiers (Big Shell)", "enemy", [0xD7AAAF], GPS_PARTS),
    "soldier_hightech": ("High-tech soldiers", "enemy", [0xFBBAAF], [H("htc_hand_def")]),
    "seal": ("Navy SEALs", "enemy", [0xF13A96], []),
    "marine": ("US Marines", "npc", [0x77E995], []),
    "tengu": ("Tengu soldiers", "enemy", [0x296D9C], []),
    "olga": ("Olga Gurlukovich", "character", [0xB3F701, 0xA175F6], []),
    "ninja": ("Cyborg Ninja (Mr. X)", "character", [0xC43F41], []),
    "ocelot": ("Revolver Ocelot", "character", [0x9BA944], []),
    "solidus": ("Solidus Snake", "character", [0xF4B943], []),
    "otacon": ("Otacon", "character", [0xB3F7F1], []),
}
PLAYER = ("snake", "raiden")
SOLDIERS = ("soldier_tanker", "soldier_tanker_heavy", "soldier_plant", "soldier_plant_heavy", "soldier_hightech",
            "seal", "tengu")
AGGREGATES = {"player": PLAYER, "soldiers": SOLDIERS, "enemies": SOLDIERS}
SIZE = {"snake": 1.0, "raiden": 0.95, "pliskin": 1.0, "ocelot": 1.05, "solidus": 1.05, "olga": 0.95,
        "otacon": 0.95, "ninja": 1.0}
SHADOWS = {H("sna_shadow"), H("rai_shadow")}
HEAD_KEEP = 1.8                       # a chibi donor head is shrunk to this many times the cast's head height


class SwapError(ValueError):
    pass


def cast_slots() -> list[dict]:
    out = [{"slot": "player", "name": "the playable heroes (Snake, Raiden)", "kind": "player", "aggregate": True,
            "writer": "gbox.mgs2_swap"},
           {"slot": "soldiers", "name": "every soldier variant", "kind": "enemy", "aggregate": True,
            "writer": "gbox.mgs2_swap"}]
    for s, (name, kind, models, _hide) in SLOTS.items():
        out.append({"slot": s, "name": name, "kind": kind, "models": len(models), "size": SIZE.get(s, 1.0),
                    "writer": "gbox.mgs2_swap"})
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def resolve_slot(slot: str) -> list[str]:
    """A slot, an aggregate (player, soldiers) or a display name -> the slot keys it covers."""
    s = _norm((slot or "player").split(":", 1)[-1])
    if s in AGGREGATES:
        return list(AGGREGATES[s])
    if s in SLOTS:
        return [s]
    for k, (name, _kind, _m, _h) in SLOTS.items():
        if s == _norm(name):
            return [k]
    hit = slot_for_name(slot or "")
    if hit:
        return [hit]
    raise SwapError(f"{slot!r} is not a Metal Gear Solid 2 cast slot (have: player, soldiers, {', '.join(SLOTS)})")


def is_slot(slot: str) -> bool:
    try:
        resolve_slot(slot)
        return True
    except SwapError:
        return False


# words a pick whip / the agent may use for what was clicked -> slot
NAME_WORDS = [("pliskin", "pliskin"), ("iroquois", "pliskin"), ("solidus", "solidus"), ("snake", "snake"),
              ("raiden", "raiden"), ("jack", "raiden"), ("olga", "olga"), ("ninja", "ninja"), ("mr x", "ninja"),
              ("ocelot", "ocelot"), ("otacon", "otacon"), ("emmerich", "otacon"), ("seal", "seal"),
              ("tengu", "tengu"), ("marine", "marine"), ("high tech", "soldier_hightech"),
              ("hi tech", "soldier_hightech"), ("hightech", "soldier_hightech")]


def slot_for_name(name: str, stage: str | None = None, kind: str | None = None) -> str | None:
    """What the operator whipped ("Snake", "a soldier in grey camo", kind player / enemy) -> a slot; soldiers and
    the player depend on where the game is (stage name: w0x = Tanker, the rest = Big Shell)."""
    t = " " + re.sub(r"[^a-z]+", " ", (name or "").lower()) + " "
    for w, s in NAME_WORDS:
        if f" {w} " in t:
            return s
    tanker = bool(stage) and re.match(r"(r_tnk|w0\d|d0\dt|a0\d)", stage or "") is not None
    if kind == "player" or " player " in t or " you " in t:
        return "snake" if tanker or not stage else "raiden"
    if kind == "enemy" or any(f" {w} " in t for w in ("soldier", "guard", "enemy", "gurlukovich", "trooper")):
        heavy = any(f" {w} " in t for w in ("heavy", "armor", "armored", "armoured", "helmet", "shield"))
        if tanker:
            return "soldier_tanker_heavy" if heavy else "soldier_tanker"
        return "soldier_plant_heavy" if heavy else "soldier_plant"
    return None


# ---------------------------------------------------------------- target skeleton (from the original kms)
def target(k: dict) -> dict:
    roles = M.roles_of(k["parents"], k["world"])
    if len(roles) != 18:
        raise SwapError(f"the slot's model has no human skeleton ({len(roles)} body roles)")
    g = M.assemble(k)
    allp = np.concatenate([x["pos"] for x in g.values()])
    ground = float(allp[:, 1].min())
    T = (k["world"] - np.array([0, ground, 0])) * M.GLTF_SCALE
    head = roles["head"]
    hp = np.concatenate([x["pos"][x["joints"][:, 0] == head] for x in g.values()])
    head_h = float(np.ptp(hp[:, 1])) * M.GLTF_SCALE if len(hp) > 8 else 0.22
    return {"T": T, "parent": list(k["parents"]), "ground": 0.0, "head_h": head_h, "joints": len(T), "roles": roles,
            "ground_mm": ground, "world_mm": k["world"], "height": float(np.ptp(allp[:, 1])) * M.GLTF_SCALE}


def fit(model: Path, roles: dict, tgt: dict, props=(), scale=None) -> dict:
    from .sm64_swap import load_rig, retarget
    if "hip" not in roles:
        raise SwapError("the character has no body roles (rig.roles): it can't be mapped onto the MGS2 skeleton")
    jmap = dict(tgt["roles"])
    rig = load_rig(Path(model), roles, props)
    prims, rep = retarget(rig, tgt, scale, jmap)
    head = jmap["head"]
    hp = [np.asarray(p["pos"])[np.asarray(p["J"])[:, 0] == head] for p in prims]
    hp = np.concatenate([h for h in hp if len(h)]) if any(len(h) for h in hp) else np.zeros((0, 3))
    if len(hp) and not (scale or {}).get("head"):          # chibi heads (Sonic): ~1.8 x the cast's head (still
        hh = float(np.ptp(hp[:, 1]))                      # the character's big-headed look), never grow
        if hh > 2.2 * tgt["head_h"]:
            kk = max(0.5, HEAD_KEEP * tgt["head_h"] / hh)
            prims, rep = retarget(rig, tgt, {**(scale or {}), "head": kk}, jmap)
            rep["auto_head_scale"] = round(kk, 3)
    prims = [p for p in prims if len(p["tris"])]
    if not prims:
        raise SwapError("the character has no triangles")
    return {"prims": prims, "report": rep}


def triangles(fitted: dict, atlas: int) -> dict:
    """Retargeted prims -> per-corner arrays (t, 3, *) in glTF metres + the atlas (RGBA, 8-bit index, palette)."""
    from .gta_stories_models import pack_atlases
    from .defjam_writer import quantize
    prims = fitted["prims"]
    atl, maps = pack_atlases(prims, [(atlas, atlas)])
    P, Nn, UV, J = [], [], [], []
    for p, (_a, uv) in zip(prims, maps):
        T = np.asarray(p["tris"], int).reshape(-1, 3)
        P.append(np.asarray(p["pos"], float)[T])
        Nn.append(np.asarray(p["nrm"], float)[T])
        J.append(np.asarray(p["J"])[:, 0][T])
        UV.append(uv)
    idx, pal = quantize(atl[0], 256)
    return {"pos": np.concatenate(P), "nrm": np.concatenate(Nn), "uv": np.concatenate(UV), "joint": np.concatenate(J),
            "atlas": atl[0], "index": np.asarray(idx, np.uint8).reshape(atlas, atlas),
            "palette": np.asarray(pal, np.uint8).reshape(-1, 4)}


def clustered(tri: dict, cell: float) -> dict:
    """Fewer triangles: corners snapped per (joint, cell) and the collapsed triangles dropped."""
    if cell <= 0:
        return tri
    P, J = tri["pos"], tri["joint"]
    h = float(np.ptp(P[..., 1]))
    flat = P.reshape(-1, 3)
    key = np.concatenate([J.reshape(-1)[:, None].astype(np.int64), np.floor(flat / (cell * h)).astype(np.int64)], 1)
    _u, inv_ = np.unique(key, axis=0, return_inverse=True)
    inv_ = inv_.reshape(-1)
    s = np.zeros((inv_.max() + 1, 3))
    np.add.at(s, inv_, flat)
    flat = (s / np.bincount(inv_)[:, None])[inv_].reshape(P.shape)
    a, b, c = flat[:, 0], flat[:, 1], flat[:, 2]
    keep = np.linalg.norm(np.cross(b - a, c - a), axis=1) > 1e-10
    return tri | {"pos": flat[keep], "nrm": tri["nrm"][keep], "uv": tri["uv"][keep], "joint": J[keep]}


# ---------------------------------------------------------------- strips + kms encoding
def _depth(parents, j):
    d = 0
    while parents[j] >= 0:
        j, d = parents[j], d + 1
    return d


def strips(tris: list[tuple[int, int, int]], max_len: int = MAX_STRIP) -> list[list[int]]:
    """Greedy triangle strips over welded vertices. Each strip [v0, v1, v2, ...]: triangle k uses v_k, v_k+1, v_k+2
    and is counter-clockwise as (v_k, v_k+1, v_k+2) when k is even, (v_k+1, v_k, v_k+2) when odd (the game's parity,
    measured on the original models). Input triangles are counter-clockwise."""
    by_edge: dict[tuple[int, int], list[int]] = {}
    for t, (a, b, c) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            by_edge.setdefault(e, []).append(t)
    used = [False] * len(tris)
    out = []
    for t0 in range(len(tris)):
        if used[t0]:
            continue
        used[t0] = True
        a, b, c = tris[t0]
        s = [a, b, c]
        while len(s) < max_len:
            k = len(s) - 2                              # index of the next triangle in the strip
            x, y = s[-2], s[-1]
            want = (x, y) if k % 2 == 0 else (y, x)      # the directed edge the next triangle must contain
            nxt = None
            for t in by_edge.get(want, ()):
                if not used[t]:
                    nxt = t
                    break
            if nxt is None:
                break
            tri = tris[nxt]
            z = next(v for v in tri if v not in want)
            used[nxt] = True
            s.append(z)
        out.append(s)
    return out


def _weld(P, N, UV, W, keyscale=1000.0):
    """Corner arrays (n, *) -> unique vertex index per corner (same position, normal, uv and weight)."""
    key = np.concatenate([np.round(P * 4), np.round(N * 64), np.round(UV * keyscale), W[:, None]], 1)
    _u, first, inv_ = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return first, inv_.reshape(-1)


def encode_kms(template: bytes, tri: dict, tex_hash: int, tgt: dict) -> bytes:
    """A new kms from the template's header and bone records with the fitted triangles (glTF metres) as strips."""
    k = M.parse_kms(template)
    parents = k["parents"]
    nb = len(parents)
    world = k["world"]
    ground = tgt["ground_mm"]
    P = tri["pos"] / M.GLTF_SCALE + np.array([0, ground, 0])          # model space, mm, (t, 3, 3)
    Nn = np.asarray(tri["nrm"], float)
    J = np.asarray(tri["joint"], int)
    if len(P) and (J.min() < 0 or J.max() >= nb):
        raise SwapError("a vertex is bound to a bone outside the skeleton")
    depth = [_depth(parents, j) for j in range(nb)]
    per_bone: dict[int, list[int]] = {}
    for t in range(len(P)):
        b = max(J[t], key=lambda j: depth[j])
        per_bone.setdefault(int(b), []).append(t)
    parts_of: dict[int, list[dict]] = {}
    for b, ts in per_bone.items():
        ts = np.array(ts)
        Pc = (P[ts] - world[b]).reshape(-1, 3)
        Nc = Nn[ts].reshape(-1, 3)
        Uc = tri["uv"][ts].reshape(-1, 2)
        Jc = J[ts].reshape(-1)
        Wc = np.where(Jc == b, 4096, np.where(Jc == parents[b], 0, 4096)).astype(np.int64)
        first, vid = _weld(Pc, Nc, Uc, Wc)
        tris = [tuple(vid[3 * i:3 * i + 3]) for i in range(len(ts))]
        tris = [t for t in tris if len(set(t)) == 3]
        blend = parents[b] >= 0 and bool((Wc == 0).any())
        for s in strips(tris):
            parts_of.setdefault(b, [])
            cur = parts_of[b][-1] if parts_of[b] and len(parts_of[b][-1]["v"]) + len(s) <= MAX_PART else None
            if cur is None:
                cur = {"v": [], "restart": [], "blend": blend}
                parts_of[b].append(cur)
            cur["v"] += s
            cur["restart"] += [True, True] + [False] * (len(s) - 2)
        for part in parts_of.get(b, []):
            part["data"] = (Pc[first], Nc[first], Uc[first], Wc[first])
    # layout: header, bone records, part records, positions, normals, uvs (16-byte aligned arrays)
    out = bytearray(template[:M.HDR + M.MESH * nb])
    nparts = sum(len(v) for v in parts_of.values())
    ptab = M.HDR + M.MESH * nb
    arrays = ptab + M.PART * max(nparts, 0)
    pos_blob, nrm_blob, uv_blob = bytearray(), bytearray(), bytearray()
    recs = []
    for b in range(nb):
        plist = parts_of.get(b, [])
        recs.append((b, len(plist)))
    # pass 1: arrays
    part_rows = []
    for b in range(nb):
        for part in parts_of.get(b, []):
            Pv, Nv, Uv, Wv = part["data"]
            v = np.array(part["v"], int)
            n = len(v)
            pp = np.zeros((n, 4), np.int16)
            pp[:, :3] = np.clip(np.round(Pv[v]), -32768, 32767)
            pp[:, 3] = Wv[v]
            nn = np.zeros((n, 4), np.int16)
            nrm = Nv[v] / np.maximum(np.linalg.norm(Nv[v], axis=1, keepdims=True), 1e-9)
            nn[:, :3] = np.clip(np.round(nrm * 4095), -4095, 4095)
            fl = np.where(np.array(part["restart"]), NRM_FLAG | 0x8000, NRM_FLAG).astype(np.uint16)
            nn[:, 3] = fl.view(np.int16)
            uu = np.clip(np.round(Uv[v] * 4096), -32768, 32767).astype(np.int16)
            part_rows.append((b, part, n, len(pos_blob), len(nrm_blob), len(uv_blob)))
            for blob, arr in ((pos_blob, pp), (nrm_blob, nn), (uv_blob, uu)):
                blob += arr.tobytes()
                blob += b"\0" * (-len(blob) % 16)
    o_pos = arrays
    o_nrm = o_pos + len(pos_blob)
    o_uv = o_nrm + len(nrm_blob)
    out += b"\0" * (M.PART * nparts)
    q = ptab
    first_part = {}
    for b, part, n, op, on, ou in part_rows:
        first_part.setdefault(b, q)
        flags = 0x48 | (1 if part["blend"] else 0)
        struct.pack_into("<12I", out, q, flags, n, tex_hash, 0, 0, o_pos + op, o_nrm + on, o_uv + ou, 0, 0, 0, 0)
        q += M.PART
    out += pos_blob + nrm_blob + uv_blob
    for b, n in recs:
        o = M.HDR + M.MESH * b
        struct.pack_into("<I", out, o + 4, n)
        struct.pack_into("<I", out, o + 48, first_part.get(b, ptab))
        pts = [part["data"][0][np.array(part["v"])] for part in parts_of.get(b, [])]
        if pts:
            allp = np.concatenate(pts)
            struct.pack_into("<3f", out, o + 8, *allp.min(0).astype(float))
            struct.pack_into("<3f", out, o + 20, *allp.max(0).astype(float))
        struct.pack_into("<3I", out, o + 52, 0, 0, 0)
    return bytes(out)


def degenerate_kms(template: bytes) -> bytes:
    """The template with every bone's geometry collapsed to one zero-area triangle (an invisible accessory); all the
    parts share one 3-vertex array."""
    k = M.parse_kms(template)
    nb = len(k["parents"])
    out = bytearray(template[:M.HDR + M.MESH * nb])
    ptab = M.HDR + M.MESH * nb
    base = ptab + M.PART * nb
    out += b"\0" * (M.PART * nb)
    pos = struct.pack("<4h", 0, 0, 0, 4096) * 3 + b"\0" * 8                      # 32 bytes
    nrm = (struct.pack("<3hH", 0, 4095, 0, NRM_FLAG | 0x8000) * 2 +
           struct.pack("<3hH", 0, 4095, 0, NRM_FLAG) + b"\0" * 8)                  # 32 bytes
    uv = b"\0" * 16
    for i in range(nb):
        o = M.HDR + M.MESH * i
        struct.pack_into("<I", out, o + 4, 1)
        struct.pack_into("<I", out, o + 48, ptab + M.PART * i)
        struct.pack_into("<6f", out, o + 8, 0, 0, 0, 0, 0, 0)
        struct.pack_into("<12I", out, ptab + M.PART * i, 0x48, 3, 0, 0, 0, base, base + 32, base + 64, 0, 0, 0, 0)
    out += pos + nrm + uv
    if len(out) > len(template):
        raise SwapError("the template is too small for an empty model")
    return bytes(out)


def verify_kms(new: bytes, tri_count: int | None = None) -> dict:
    k = M.parse_kms(new)
    n = M.triangles(k)
    ok = n > 0 and (tri_count is None or n >= tri_count)
    return {"ok": bool(ok), "triangles": n, "bones": len(k["parents"])}


def fit_kms(template: bytes, fitted: dict, tex_hash: int, tgt: dict, tri_full: dict, budget: int | None = None) -> dict:
    """The densest encoding (vertex clustering) whose kms fits the template's size (or `budget`)."""
    cap = len(template) if budget is None else budget
    tried = []
    for cl in CLUSTER:
        tri = clustered(tri_full, cl)
        data = encode_kms(template, tri, tex_hash, tgt)
        tried.append((cl, len(tri["pos"]), len(data)))
        if len(data) <= cap:
            v = verify_kms(data)
            if not v["ok"]:
                raise SwapError(f"the encoded model does not read back: {v}")
            return {"data": data + b"\0" * (len(template) - len(data)), "triangles": v["triangles"],
                    "source_triangles": len(tri_full["pos"]), "cluster": cl, "size": len(data), "cap": cap,
                    "tried": len(tried)}
    raise SwapError(f"the character does not fit the {cap}-byte model even at the coarsest clustering "
                    f"(last try {tried[-1]})")


# ---------------------------------------------------------------- texture pack: the donor atlas
def _rect_texels(e: dict):
    u0, v0, du, dv = e["rect"]
    x0, y0 = int(np.floor(u0 * e["tw"])), int(np.floor(v0 * e["th"]))
    x1, y1 = int(np.ceil((u0 + du) * e["tw"])), int(np.ceil((v0 + dv) * e["th"]))
    return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)


def _bytes_of(mem: GSMemory, e: dict, x0, y0, x1, y1) -> np.ndarray:
    y, x = np.mgrid[y0:y1, x0:x1]
    if e["psm"] == 0x13:
        return np.unique(mem.addr8(e["tbp"], e["tbw"], x, y))
    if e["psm"] == 0x14:
        return np.unique(mem.nib4(e["tbp"], e["tbw"], x, y) // 2)
    return np.zeros(0, int)


def _clut_bytes(mem: GSMemory, e: dict) -> np.ndarray:
    w, h = (16, 16) if e["psm"] == 0x13 else (8, 2)
    y, x = np.mgrid[0:h, 0:w]
    a = mem.addr32(e["cbp"], 1, x, y)
    return np.unique(np.concatenate([a + k for k in range(4)]))


def plan_atlas(pack: M.TexturePack, own: set[int], usage: dict[int, int], claimed: dict | None = None,
               mine: set[int] | None = None) -> dict:
    """Where the donor atlas can go in this pack: a PSMT8 page region and a CLUT that no texture outside `own` (the
    textures of every model this build replaces or hides) touches and no earlier slot of the build claimed
    (`claimed` {pix, clut, entries}); the hijacked entry is the slot's (`mine`) most used PSMT8 texture."""
    claimed = claimed or {"pix": set(), "clut": set(), "entries": set()}
    mine = own if mine is None else mine
    pix = GSMemory(max(pack.pix_blocks * 256, 1 << 16) * 2)
    limit = pack.pix_blocks * 256
    protected = set(claimed["pix"])
    for h, e in pack.entries.items():
        if h not in own:
            protected |= set(_bytes_of(pix, e, *_rect_texels(e)).tolist())
    clut_mem = GSMemory(max(pack.clut_blocks * 256, 1 << 14) * 2)
    cl_prot = set(claimed["clut"])
    for h, e in pack.entries.items():
        if h not in own:
            cl_prot |= set(_clut_bytes(clut_mem, e).tolist())
    eights = [e | {"hash": h} for h, e in pack.entries.items() if h in own and e["psm"] == 0x13]
    hij = [e for e in eights if e["hash"] in mine and e["hash"] not in claimed["entries"]]
    if not hij:
        raise SwapError("the slot's textures have no 8-bit entry of their own in this pack")
    hij.sort(key=lambda e: -usage.get(e["hash"], 0))
    pages = []
    for e in sorted(eights, key=lambda e: -usage.get(e["hash"], 0)):
        if (e["tbp"], e["tbw"]) not in [(p["tbp"], p["tbw"]) for p in pages]:
            pages.append(e)
    cl_entries = sorted({e["cbp"]: e for e in eights}.values(), key=lambda e: e["cbp"])
    cluts = [e for e in cl_entries if not (set(_clut_bytes(clut_mem, e).tolist()) & cl_prot)
             and (e["cbp"] + 4) * 256 <= pack.clut_blocks * 256]
    if not cluts:
        raise SwapError("no CLUT in this pack is used by the replaced models only")
    prot = np.fromiter(protected, np.int64) if protected else None
    for A in ATLAS:
        for pg in pages:
            if A > pg["tbw"] * 64 or A > pg["th"]:
                continue
            for oy in range(0, max(1, pg["th"] - A + 1), A):            # the page's free rows, in atlas steps
                y, x = np.mgrid[oy:oy + A, 0:A]
                ad = pix.addr8(pg["tbp"], pg["tbw"], x, y)
                if ad.max() >= limit:
                    break
                if prot is not None and np.isin(ad, prot).any():
                    continue
                cl = cluts[0]
                cy, cx = np.mgrid[0:16, 0:16]
                cad = clut_mem.addr32(cl["cbp"], 1, cx, cy)
                return {"page": pg, "A": A, "oy": oy, "hijack": hij[0]["hash"], "clut": cl["cbp"],
                        "claim": {"pix": set(np.unique(ad).tolist()),
                                  "clut": set(np.unique(np.concatenate([cad.reshape(-1) + k for k in range(4)])).tolist()),
                                  "entry": hij[0]["hash"]}}
    raise SwapError("no free 8-bit page region for the donor atlas in this pack")


def write_atlas(pack_bytes: bytes, plan: dict, index: np.ndarray, palette: np.ndarray) -> bytes:
    """The pack with the atlas pixels, the donor CLUT and the hijacked entry pointed at them (same size)."""
    pack = M.TexturePack(pack_bytes)
    A = plan["A"]
    pg, e = plan["page"], pack.entries[plan["hijack"]]
    b = bytearray(pack_bytes)
    pix = GSMemory(max(pack.pix_blocks * 256, 1 << 16) * 2)
    pix.load_linear(pack_bytes[pack.pix_off:pack.pix_off + 256 * pack.pix_blocks])
    if index.shape != (A, A):
        from PIL import Image
        index = np.asarray(Image.fromarray(index).resize((A, A), Image.NEAREST))
    oy = int(plan.get("oy", 0))
    full = pix.read8(pg["tbp"], pg["tbw"], pg["tbw"] * 64, oy + A)
    full[oy:oy + A, :A] = np.asarray(index, np.uint8)
    pix.write8(full, pg["tbp"], pg["tbw"])
    b[pack.pix_off:pack.pix_off + 256 * pack.pix_blocks] = pix.dump_linear(0, pack.pix_blocks)
    clut = GSMemory(max(pack.clut_blocks * 256, 1 << 14) * 2)
    clut.load_linear(pack_bytes[pack.clut_off:pack.clut_off + 256 * pack.clut_blocks])
    pal = np.zeros((256, 4), np.uint8)
    pal[:len(palette)] = palette[:256]
    pal[:, 3] = 255
    stored = csm1(alpha_to_gs(pal))                       # csm1 is its own inverse
    clut.write32(stored.reshape(16, 16, 4).tobytes(), plan["clut"], 1, 16, 16)
    b[pack.clut_off:pack.clut_off + 256 * pack.clut_blocks] = clut.dump_linear(0, pack.clut_blocks)
    # the hijacked entry: page, CLUT, rect, region clamp, centre / half size
    o = e["offset"]
    tw, th = pg["tw"], pg["th"]
    t0 = pg["tex0"]
    t0 = (t0 & ~(0x3FFF << 37)) | (plan["clut"] << 37)
    t0 &= ~(0x1F << 56)                                   # CSA 0
    u0, v0 = 0.5 / tw, (oy + 0.5) / th
    du, dv = (A - 1) / tw, (A - 1) / th
    struct.pack_into("<4f", b, o, u0, v0, du, dv)
    for kk in range(5):
        d, a = struct.unpack_from("<2Q", b, o + 0x30 + 16 * kk)
        reg = a & 0xFF
        if reg == 0x06:
            d = t0
        elif reg == 0x16:                                  # TEX2: PSM / CBP / CPSM / CSM / CSA / CLD of the CLUT load
            d = (d & ~((0x3FFF << 37) | (0x1F << 56))) | (plan["clut"] << 37)
            d = (d & ~(0x3F << 20)) | (0x13 << 20)
        elif reg == 0x08:                                  # CLAMP_1: region clamp to the atlas
            d = 2 | (2 << 2) | (0 << 4) | ((A - 1) << 14) | (oy << 24) | ((oy + A - 1) << 34)
        struct.pack_into("<Q", b, o + 0x30 + 16 * kk, d)
    struct.pack_into("<6f", b, o + 0x80, -du / 2, -dv / 2, 1.0, 1.0, u0 + du / 2, v0 + dv / 2)
    out = bytes(b)
    chk = M.TexturePack(out).image(plan["hijack"])
    if chk is None or chk.shape[0] < A - 2:
        raise SwapError("the atlas does not read back from the pack")
    return out


# ---------------------------------------------------------------- disc
def base_iso(cfg, game: dict, src: Path, progress=lambda p, m: None) -> Path:
    """The vanilla two-layer ISO, unpacked from the catalog CHD once per game (cache/modbase/<game>/<name>.iso)."""
    from . import filemods
    src = Path(src)
    if src.suffix.lower() == ".iso":
        return src
    out = filemods.base_dir(cfg, game["game_id"]) / (src.stem + ".iso")
    if not out.is_file():
        from .chd import ChdDisc
        progress(3, f"Unpacking {src.name} to a plain ISO (once per game, 6.4 GB, ~9 min)")
        ChdDisc(src).write_iso(out, lambda d, n: progress(3 + 20 * d / max(n, 1), "unpacking the CHD"))
    return out


class _Job:
    def __init__(self, slot, model, roles, name, props=(), scale=None, fit_key=None, slug=None):
        self.slot, self.model, self.roles, self.name = slot, Path(model), roles or {}, name
        self.props, self.scale, self.fit_key, self.slug = props or (), scale, fit_key or slot, slug


def _usage(k: dict) -> dict[int, int]:
    """Vertices per diffuse texture (the hijacked entry is the slot's most used one)."""
    u: dict[int, int] = {}
    for m in k["meshes"]:
        for p in m["parts"]:
            u[p["tex"][0]] = u.get(p["tex"][0], 0) + len(p["pos"])
    return u


def _textures(k: dict) -> set[int]:
    """Every texture a model's parts name (diffuse and the second / third maps)."""
    return {t for m in k["meshes"] for p in m["parts"] for t in p["tex"] if t}


def build_disc(src_iso: Path, out_iso: Path | None, jobs: list[dict], progress=lambda p, m: None) -> dict:
    """jobs [{slot, model, roles, name, props, scale, fit_key}] -> a copy of the ISO with every stage that carries a
    slot's models rewritten. A slot that fails (no roles, nothing fits) is reported and skipped. out_iso None = a dry
    run: everything is fitted, encoded and every stage rebuilt in memory, nothing is written."""
    from . import fit_events as FE
    disc = inv.Disc(src_iso)
    ident = inv.identify(disc)
    if not ident["exact_build"]:
        raise SwapError(f"{ident['boot']}: the writer is built on {inv.SERIAL} only")
    idx = M.Index(disc)
    reports, changes = [], {}                              # changes[(fn, stage)][(type, hash)] = bytes
    fits_cache: dict = {}
    page_cache: dict = {}
    claims: dict = {}                                      # (fn, stage, pack) -> what earlier slots took
    replaced = set()                                       # every model this build replaces or hides
    for jb in jobs:
        try:
            for kk in resolve_slot(jb["slot"] if isinstance(jb, dict) else jb.slot):
                replaced |= set(SLOTS[kk][2]) | set(SLOTS[kk][3])
        except SwapError:
            pass
    for n, jb in enumerate(jobs):
        jb = jb if isinstance(jb, _Job) else _Job(**jb)
        rep = {"slot": jb.slot, "character": jb.name, "models": [], "packs": [], "status": "failed"}
        try:
            keys = resolve_slot(jb.slot)
            if len(keys) != 1:
                raise SwapError("build one slot per job (aggregates are expanded by the caller)")
            key = keys[0]
            if "hip" not in jb.roles:
                raise SwapError("the character has no body roles (rig.roles): it can't be mapped onto the MGS2 skeleton")
            _name, _kind, models, hide = SLOTS[key]
            FE.model(jb.fit_key)
            progress(25 + 45 * n / max(len(jobs), 1), f"Fitting {jb.name} onto {key}")
            done_stages = set()
            plans: dict = {}
            written: set = set()
            weighed = False
            for h in models:
                places = idx.stages_with(inv.T_KMS, h)
                for fn, stage in places:
                    try:
                        tmpl = idx.read(fn, stage, inv.T_KMS, h, page_cache)
                        k = M.parse_kms(tmpl)
                        sig = hashlib.sha1(tmpl).hexdigest()
                        shadow = h in SHADOWS
                        try:
                            tgt = target(k)
                        except SwapError as x:
                            rep["models"].append({"model": f"{h:06x}", "stage": f"{fn}:{stage}", "status": "failed",
                                                  "reason": str(x)})
                            continue
                        ch = changes.setdefault((fn, stage), {})
                        if shadow:
                            tex_hash, plan = 0, None
                        else:
                            pk_h = k["tex"]
                            pkey = (fn, stage, pk_h)
                            if pkey not in plans:              # one atlas place per pack: every slot model shares it
                                own, mine, usage = set(), set(), {}
                                for p_ in idx.stage(fn, stage).pages:
                                    for f_ in p_.files:
                                        if f_[0] != inv.T_KMS or f_[1] not in replaced:
                                            continue
                                        ko = M.parse_kms(idx.read(fn, stage, inv.T_KMS, f_[1], page_cache))
                                        tx = _textures(ko)
                                        own |= tx
                                        if f_[1] in models or f_[1] in hide:
                                            mine |= tx
                                        if f_[1] in models and ko["tex"] == pk_h:
                                            for t, nv in _usage(ko).items():
                                                usage[t] = usage.get(t, 0) + nv
                                pb = changes.get((fn, stage), {}).get((inv.T_TEX, pk_h)) or \
                                    idx.read(fn, stage, inv.T_TEX, pk_h, page_cache)
                                if pb is None:
                                    raise SwapError(f"texture pack {pk_h:06x} is not in this stage")
                                cl = claims.setdefault(pkey, {"pix": set(), "clut": set(), "entries": set()})
                                pl = plan_atlas(M.TexturePack(idx.read(fn, stage, inv.T_TEX, pk_h, page_cache)), own,
                                                usage, cl, mine)
                                cl["pix"] |= pl["claim"]["pix"]
                                cl["clut"] |= pl["claim"]["clut"]
                                cl["entries"].add(pl["claim"]["entry"])
                                plans[pkey] = (pl, pb)
                            plan, pack_b = plans[pkey]
                            tex_hash = plan["hijack"]
                        fk = (str(jb.model), jb.fit_key, sig, plan["A"] if plan else 128)
                        if isinstance(fits_cache.get(fk), str):
                            raise SwapError(fits_cache[fk])
                        if fk not in fits_cache:
                            try:
                                fitted = fit(jb.model, jb.roles, tgt, jb.props, jb.scale)
                                if not weighed:
                                    weighed = True
                                    FE.weights(fitted["prims"], names={i: M.bone_name(i, tgt["roles"])
                                                                       for i in range(tgt["joints"])},
                                               skeleton=tgt["joints"])
                                tri = triangles(fitted, plan["A"] if plan else 128)
                                r = fit_kms(tmpl, fitted, tex_hash, tgt, tri)
                            except SwapError as x:
                                fits_cache[fk] = str(x)
                                raise
                            fits_cache[fk] = (r, tri, fitted["report"])
                        r, tri, frep = fits_cache[fk]
                        data = r["data"]
                        if tex_hash:
                            data = _retex(data, tex_hash)
                        ch[(inv.T_KMS, h)] = data
                        if plan is not None and (fn, stage, k["tex"], key) not in written:
                            written.add((fn, stage, k["tex"], key))
                            base_pack = ch.get((inv.T_TEX, k["tex"])) or pack_b
                            ch[(inv.T_TEX, k["tex"])] = write_atlas(base_pack, plan, tri["index"], tri["palette"])
                            rep["packs"].append({"pack": f"{k['tex']:06x}", "stage": f"{fn}:{stage}", "atlas": plan["A"],
                                                 "hijack": f"{plan['hijack']:06x}", "clut": plan["clut"]})
                        rep["models"].append({"model": f"{h:06x}", "stage": f"{fn}:{stage}", "status": "built",
                                              "triangles": r["triangles"], "cluster": r["cluster"], "size": r["size"],
                                              "cap": r["cap"], "shadow": shadow})
                        rep["fit"] = {k2: v for k2, v in frep.items() if k2 in ("scale", "head_scale", "limb_stretch",
                                                                                "auto_head_scale")}
                        done_stages.add((fn, stage))
                    except (SwapError, M.FormatError, inv.FormatError, ValueError, KeyError) as x:
                        shadow = h in SHADOWS
                        rep["models"].append({"model": f"{h:06x}", "stage": f"{fn}:{stage}",
                                              "status": "kept" if shadow else "failed", "reason": str(x)[:300]})
                        continue
            for h in hide:
                for fn, stage in idx.stages_with(inv.T_KMS, h):
                    if (fn, stage) not in done_stages:
                        continue
                    try:
                        tmpl = idx.read(fn, stage, inv.T_KMS, h, page_cache)
                        data = degenerate_kms(tmpl)
                    except (SwapError, M.FormatError, ValueError) as x:
                        rep["models"].append({"model": f"{h:06x}", "stage": f"{fn}:{stage}", "status": "kept",
                                              "reason": str(x)[:200]})
                        continue
                    changes[(fn, stage)][(inv.T_KMS, h)] = data + b"\0" * (len(tmpl) - len(data))
                    rep["models"].append({"model": f"{h:06x}", "stage": f"{fn}:{stage}", "status": "hidden"})
            built = [m for m in rep["models"] if m["status"] == "built"]
            rep["status"] = "built" if built and len(built) == len([m for m in rep["models"]
                                                                    if m["status"] not in ("hidden", "kept")]) else \
                "partial" if built else "failed"
            if not built and not rep.get("reason"):
                rep["reason"] = "; ".join(f"{m['model']}@{m['stage']}: {m.get('reason')}" for m in rep["models"]
                                          if m["status"] == "failed")[:400] or "none of the slot's models is on this disc"
            if built:
                FE.stage("decimate", data={"from": built[0].get("triangles"), "cluster": built[0].get("cluster")})
                FE.stage("encode", data={"models": len(built), "bytes": sum(m["size"] for m in built)})
        except (SwapError, M.FormatError, inv.FormatError, ValueError, KeyError) as x:
            rep["reason"] = str(x)[:400]
            try:
                FE.stage("write", "failed", {"reason": str(x)[:150]})
            except Exception:                              # noqa: BLE001 - the report carries it either way
                pass
        reports.append(rep)
    if not changes or not any(changes.values()):
        disc.close()
        raise SwapError("; ".join(f"{r['slot']}: {r.get('reason', 'nothing written')}" for r in reports))
    # rebuild every touched stage
    patches = []
    stage_rows = []
    for i, ((fn, stage), ch) in enumerate(sorted(changes.items())):
        if not ch:
            continue
        progress(70 + 12 * i / max(len(changes), 1), f"Rebuilding stage {stage}")
        a = idx.archives[fn]
        st = idx.stage(fn, stage)
        raw = {kk: a.page_raw(st, kk) for kk in range(len(st.pages))}
        pages = {}
        for kk, p in enumerate(st.pages):
            if any((f[0], f[1]) in ch for f in p.files):
                data = bytearray(idx.page(fn, stage, kk, page_cache))
                for f in p.files:
                    nb_ = ch.get((f[0], f[1]))
                    if nb_ is not None:
                        if len(nb_) != f[3]:
                            raise SwapError(f"{stage}: {f[0]:02x}:{f[1]:06x} changed size")
                        data[f[2]:f[2] + f[3]] = nb_
                pages[kk] = bytes(data)
        try:
            blob = inv.rebuild_stage(st, a.key, pages, raw)
        except inv.FormatError as x:
            for rep in reports:
                for m in rep["models"]:
                    if m["stage"] == f"{fn}:{stage}" and m["status"] == "built":
                        m["status"], m["reason"] = "failed", str(x)[:200]
            continue
        patches.append(((a.lba + st.sector) * inv.SECTOR, blob, fn, stage))
        stage_rows.append({"stage": f"{fn}:{stage}", "files": len(ch), "bytes": len(blob)})
    disc.close()
    for rep in reports:
        built = [m for m in rep["models"] if m["status"] == "built"]
        rest = [m for m in rep["models"] if m["status"] not in ("built", "hidden", "kept")]
        rep["status"] = "built" if built and not rest else "partial" if built else "failed"
    if not patches:
        raise SwapError("no stage could be rebuilt within its sectors")
    if out_iso is None:
        return {"image": None, "reports": reports, "stages": stage_rows}
    out_iso = Path(out_iso)
    out_iso.parent.mkdir(parents=True, exist_ok=True)
    progress(83, f"Copying the disc image ({Path(src_iso).stat().st_size >> 20} MB)")
    shutil.copyfile(src_iso, out_iso)
    with open(out_iso, "r+b") as f:
        for off, blob, _fn, _st in patches:
            f.seek(off)
            f.write(blob)
    progress(95, "Reading the written stages back from the image")
    back = inv.Disc(out_iso)
    try:
        bidx = {fn: inv.StageArchive(back, fn) for fn in inv.STAGE_FILES}
        for _off, _blob, fn, stage in patches:
            st = bidx[fn].stage(stage)
            for (t, h), want in changes[(fn, stage)].items():
                got = bidx[fn].file(st, t, h)
                if got != want:
                    raise SwapError(f"{stage}: {t:02x}:{h:06x} does not read back from the patched image")
    finally:
        back.close()
    for rep in reports:
        for m in rep["models"]:
            if m["status"] in ("built", "hidden"):
                m["read_back"] = True
    return {"image": str(out_iso), "reports": reports, "stages": stage_rows}


def _retex(data: bytes, tex_hash: int) -> bytes:
    """Every part of an encoded kms pointed at tex_hash (the fit cache is shared between packs)."""
    b = bytearray(data)
    k = M.parse_kms(bytes(data))
    for i in range(len(k["meshes"])):
        o = M.HDR + M.MESH * i
        n, ptab = struct.unpack_from("<I", b, o + 4)[0], struct.unpack_from("<I", b, o + 48)[0]
        for j in range(n):
            struct.pack_into("<I", b, ptab + M.PART * j + 8, tex_hash)
    return bytes(b)


# ---------------------------------------------------------------- characters op=use / op=match / cast / live
def mod_name(pairs: list[tuple[dict, str]], title: str | None = None) -> str:
    if title and len(pairs) > 1:
        return "mgs2_" + re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:48]
    return "mgs2_" + "_".join(f"{m['slug']}_as_{_norm(s)}" for m, s in pairs)[:96]


def _jobs_of(root: Path, meta: dict, slot: str) -> list[dict]:
    rig = meta.get("rig") or {}
    return [{"slot": s, "model": Path(root) / meta["slug"] / meta["model"], "roles": rig.get("roles") or {},
             "name": meta["name"], "props": [p["node"] for p in meta.get("props") or []], "scale": rig.get("scale"),
             "fit_key": s, "slug": meta["slug"]} for s in resolve_slot(slot)]


def build_mod(cfg, game: dict, pairs: list[tuple[dict, str]], progress=lambda p, m: None, root: Path | None = None,
              title: str | None = None, name: str | None = None, src: Path | None = None) -> dict:
    from . import characters as C, filemods, fit_events as FE

    class Ctx:
        config = cfg

        @staticmethod
        def progress(p, m):
            progress(p, m)
    root = Path(root or C.library_root(cfg))
    src = Path(src) if src else M.source_disc(Ctx(), game)
    jobs = [j for m, s in pairs for j in _jobs_of(root, m, s)]
    FE.plan([(j["fit_key"], j["slug"], f"{j['name']} -> {SLOTS[j['slot']][0]}") for j in jobs])
    iso = base_iso(cfg, game, src, progress)
    name = name or mod_name(pairs, title)
    d = filemods.mod_dir(cfg, game["game_id"], name)
    if d.exists():
        shutil.rmtree(d)
    img = d / (Path(src).stem + ".iso")
    b = build_disc(iso, img, jobs, progress)
    for r in b["reports"]:
        if r["status"] != "failed":
            FE.model(r["slot"])
            FE.stage("write", data={"mod": name, "image": img.name, "stages": len({m["stage"] for m in r["models"]}),
                                    "models": len([m for m in r["models"] if m["status"] == "built"])})
    mj = {"name": name, "game_id": game["game_id"], "image": img.name, "writer": "gbox.mgs2_swap",
          "title": title or ", ".join(f"{m['name']} as {s}" for m, s in pairs), "built": time.time(),
          "files": [s["stage"] for s in b["stages"]], "characters": [m["slug"] for m, _s in pairs],
          "slots": b["reports"], "launch": "PCSX2 (libretro pcsx2 or standalone) with the image",
          "verified_in_game": False}
    (d / ".gbox-mod.json").write_text(json.dumps(mj, default=str))
    return {"mod": name, "image": str(img), "reports": b["reports"], "stages": b["stages"]}


def build_cast(cfg, game: dict, pairs: list[tuple[str, dict]], name: str, progress=lambda p, m: None,
               root: Path | None = None) -> dict:
    """cast_swap pairs builder: [(slot, meta)] -> one image; a slot whose donor fails is reported alone."""
    try:
        res = build_mod(cfg, game, [(m, s) for s, m in pairs], progress, root, name=name)
    except Exception as e:                                # noqa: BLE001 - every slot fails with the reason
        return {"mod": None, "slots": {s: {"status": "failed", "reason": str(e)[:500]} for s, _m in pairs}}
    per = {}
    for r in res["reports"]:
        per[r["slot"]] = {"status": r["status"]} | ({"reason": r["reason"]} if r.get("reason") else {})
    return {"mod": res["mod"], "slots": per, "detail": {"image": res["image"], "stages": len(res["stages"])}}


def needs(game: dict) -> dict:
    return {"have": "Metal Gear Solid 2: Substance (USA) PS2 DVD (SLUS-20554) as the catalog CHD or an ISO",
            "game_ids": sorted(GAME_IDS)}


# EE RAM: the stage loader's state pointer (ELF 0x101700 keeps it at 0x1b9300); +0x3c = name_hash(stage name)
STAGE_STATE_PTR = 0x1B9300


def current_stage(ctx, sid: str) -> str | None:
    """The stage a running session is in (read through the session's memory RPC; None when it can't be told)."""
    from .characters import _api
    try:
        rd = lambda a, n: bytes.fromhex(_api(ctx, "POST", f"/api/sessions/{sid}/rpc",   # noqa: E731
                                             json={"op": "read_memory", "args": {"address": a, "length": n}}))
        ptr = struct.unpack("<I", rd(STAGE_STATE_PTR, 4))[0] & 0x1FFFFFF
        if not 0x100000 <= ptr < 0x2000000:
            return None
        h = struct.unpack("<I", rd(ptr + 0x3C, 4))[0] & 0xFFFFFF
    except Exception:                                     # noqa: BLE001 - no RPC / not a PS2 session
        return None
    return STAGE_NAMES().get(h)


_STAGES: dict = {}


def STAGE_NAMES() -> dict[int, str]:
    """name_hash -> stage name for every stage of both archives (static list from the owned disc's TOCs)."""
    if not _STAGES:
        _STAGES.update({H(n): n for n in STAGE_LIST})
    return _STAGES


def use(ctx, meta: dict, game: dict, inp, pairs: list | None = None, title: str | None = None) -> dict:
    """characters op=use / op=match / live_use: slot = snake, raiden, soldiers, soldier_tanker ... (player = Snake +
    Raiden); a session id (+ x, y from the pick whip) launches the built image in its place through session_swap,
    keeping the moment."""
    from . import characters as C, filemods
    gid = game["game_id"]
    if gid not in GAME_IDS:
        return {"status": "missing", "missing": needs(game), "message": needs(game)["have"]}
    slot = getattr(inp, "slot", "") or ""
    sid = getattr(inp, "session_id", "") or ""
    stage = current_stage(ctx, sid) if sid else None
    picked = None
    whip = getattr(inp, "target", "") or ""               # the pick whip's identified target ("a soldier", "Snake")
    if (not slot or slot == "player") and sid and (whip or getattr(inp, "x", None) is not None):
        picked = slot_for_name(whip, stage)
        slot = picked or ("raiden" if stage and not re.match(r"(r_tnk|w0\d)", stage) else "snake")
    slot = slot or "player"
    if not C.library_root(ctx.config).is_dir():           # not the control plane: build there
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
        args = {"op": "use" if inp.op == "live_use" else inp.op, "character": inp.character, "game_id": gid,
                "slot": slot, "rebuild": inp.rebuild, "launch": False, "pairs": getattr(inp, "pairs", None),
                "title": getattr(inp, "title", None)}
        j = C._job(ctx, "characters", args, cp, 7200)
        r = (j.get("output") or {}).get("result") or {}
        if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
            return {"status": "failed", "error": r.get("error") or j.get("error") or r}
        res = r
    else:
        pairs = pairs or [(meta, slot)]
        for _m, s in pairs:
            resolve_slot(s)
        name = mod_name(pairs, title)
        have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
        built = None
        if inp.rebuild or not have:
            built = build_mod(ctx.config, game, pairs, ctx.progress, title=title)
            for m, s in pairs:
                C._api(ctx, "POST", f"/api/characters/{m['slug']}/targets",
                       json={"game_id": gid, "slot": s, "mod": name, "nodes": [C.HOST_OS],
                             "notes": "replaces the slot's stage kms models (+ atlas in their texture packs) in "
                                      "STAGE.DAT / STAGE2.DAT; the game's skeletons and motions stay; not yet "
                                      "verified in PCSX2"})
        res = {"mod": name, "build": built, "replaces": ", ".join(f"{s} -> {m['name']}" for m, s in pairs),
               "status": "built" if built else "ready"}
    res |= {"slot": slot, "stage": stage, "picked": picked, "verified_in_game": False}
    if sid and getattr(inp, "launch", True) is not False:
        node = sid.split("-")[0]
        lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": res["mod"],
                                                                                  "node": node, "session_id": sid}})
        res |= {"status": "launching", "launch_job": lj.get("id"), "node": node,
                "message": f"MGS2 mod {res['mod']} replaces the running game through session_swap (save state -> "
                           "modded image -> load state). Models already in memory change at the next area load "
                           "(a door, an elevator, or Continue)."}
    else:
        res.setdefault("message", f"Mod {res['mod']} is built (a patched copy of the PS2 DVD). Launch it from the "
                                  "session (op=use with session_id) or run the image in PCSX2.")
    return res


def match(ctx, chars: list, game: dict, inp, pairs_in: list[tuple[str, str]], title: str | None = None) -> dict:
    from . import characters as C
    pairs = []
    for c, s in pairs_in:
        meta = C.best_match(chars, c) or C.find(chars, c)
        if not meta:
            raise ValueError(f"no library character matches {c!r}")
        pairs.append((meta, s or "player"))
    return use(ctx, pairs[0][0], game, inp, pairs, title)


def main(argv=None) -> int:
    """python -m gbox.mgs2_swap MGS2.iso|chd OUT.iso SLOT=DONOR.glb ... (roles from the GLB's collection meta.json)."""
    import sys
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) < 3:
        print(main.__doc__)
        return 2
    src = Path(a[0])
    if src.suffix.lower() == ".chd":
        from .chd import ChdDisc
        iso = Path(a[1]).with_name(src.stem + ".base.iso")
        if not iso.is_file():
            ChdDisc(src).write_iso(iso, lambda d, n: print(f"unpacking {100 * d / max(n, 1):5.1f}%", flush=True))
        src = iso
    jobs = []
    for spec in a[2:]:
        slot, model = spec.split("=", 1)
        meta = json.loads((Path(model).parent / "meta.json").read_text())
        for s in resolve_slot(slot):
            jobs.append({"slot": s, "model": Path(model), "roles": (meta.get("rig") or {}).get("roles") or {},
                         "name": meta.get("name", Path(model).stem)})
    r = build_disc(src, Path(a[1]), jobs, lambda p, m: print(f"{p:5.1f}% {m}", flush=True))
    print(json.dumps(r, indent=1, default=str))
    return 0


# every stage name of STAGE.DAT and STAGE2.DAT (from the owned disc's TOCs; for current_stage)
STAGE_LIST: list[str] = [
    'r_title', 'r_tnk0', 'r_plt0', 'r_plt1', 'r_plt2', 'r_plt3', 'r_plt4', 'r_plt5', 'r_plt6', 'r_plt7',
    'r_plt8', 'r_plt9', 'r_plt10', 'r_plt11', 'r_plt12', 'r_plt13', 'r_sna_b', 'r_rai_b', 'r_plt_s', 'r_tnk_r',
    'n_title', 'museum', 'ending', 'w00a', 'w00b', 'w00c', 'w01a', 'w01f', 'w01b', 'w01c', 'w01d', 'w01e',
    'w02a', 'w03a', 'w03b', 'w04a', 'w04b', 'w04c', 'w11a', 'w11b', 'w11c', 'w12a', 'w12c', 'w12b', 'w13a',
    'w13b', 'w14a', 'w15a', 'w15b', 'w16a', 'w16b', 'w17a', 'w18a', 'w19a', 'w20a', 'w20b', 'w20c', 'w20d',
    'w21a', 'w21b', 'w22a', 'w23a', 'w23b', 'w24a', 'w24b', 'w24c', 'w24d', 'w24e', 'w25a', 'w25b', 'w25c',
    'w25d', 'w28a', 'w31a', 'w31b', 'w31c', 'w31d', 'w31f', 'w32a', 'w32b', 'w41a', 'w42a', 'w43a', 'w44a',
    'w45a', 'w46a', 'w51a', 'w61a', 'wmovie', 'webdemo', 'boss', 'd00t', 'd01t', 'd04t', 'd05t', 'd10t', 'd11t',
    'd12t', 'd12t3', 'd12t4', 'd13t', 'd14t', 'd001p01', 'd001p02', 'd005p01', 'd005p03', 'd010p01', 'd012p01',
    'd014p01', 'd021p01', 'd036p03', 'd036p05', 'd045p01', 'd046p01', 'd053p01', 'd055p01', 'd063p01', 'd065p02',
    'd070p01', 'd070p09', 'd070px9', 'd078p01', 'd080p01', 'd080p06', 'd080p07', 'd080p08', 'd082p01', 'init',
    'select', 'r_vr_s', 'r_vr_r', 'r_vr_p', 'r_vr_t', 'r_vr_b', 'r_vr_1', 'r_vr_rp', 'r_vr_sp', 'r_vr_x', 'a00a',
    'a00b', 'a00c', 'a01a', 'a01f', 'a01b', 'a01c', 'a01d', 'a01e', 'a02a', 'a02b', 'a03a', 'a03b', 'a12a',
    'a12b', 'a13a', 'a13b', 'a13c', 'a14a', 'a14b', 'a15a', 'a15b', 'a16a', 'a17a', 'a18a', 'a19a', 'a20a',
    'a20b', 'a20c', 'a20e', 'a21a', 'a21b', 'a22a', 'a22b', 'a23a', 'a23b', 'a24a', 'a24b', 'a24c', 'a24f',
    'a24d', 'a24g', 'a25a', 'a25d', 'a28a', 'a31a', 'a31b', 'a31c', 'a41a', 'a41b', 'a42a', 'a43a', 'a45a',
    'a46a', 'a61a', 'tales', 'ta02a', 'ta24a', 'tsp03a', 'tvs03a', 'twp03a', 'tvs05a', 'tvs08a', 'ta31a',
    'ta12a', 'twp43a', 'ta20a', 'tvs06a', 'ta01f', 'ta00a', 'ta01a', 'ta01b', 'ta01c', 'ta01d', 'ta01e', 'ta22a',
    'twp34a', 'ta42a', 'vs01a', 'vs02a', 'vs03a', 'vs04a', 'vs05a', 'vs06a', 'vs07a', 'vs08a', 'vs09a', 'vs10a',
    'wp01a', 'wp02a', 'wp03a', 'wp04a', 'wp05a', 'wp11a', 'wp12a', 'wp13a', 'wp14a', 'wp15a', 'wp21a', 'wp22a',
    'wp23a', 'wp24a', 'wp25a', 'wp31a', 'wp32a', 'wp33a', 'wp34a', 'wp35a', 'wp41a', 'wp42a', 'wp43a', 'wp44a',
    'wp45a', 'wp51a', 'wp52a', 'wp53a', 'wp54a', 'wp55a', 'wp61a', 'wp62a', 'wp63a', 'wp64a', 'wp65a', 'wp71a',
    'wp72a', 'wp73a', 'wp74a', 'wp75a', 'sp01a', 'sp02a', 'sp03a', 'sp06a', 'sp07a', 'sp08a', 'sp21a', 'sp22a',
    'sp24a', 'sp25a', 'st01a', 'st02a', 'st03a', 'st04a', 'st05a', 'mselect', 'sselect']


if __name__ == "__main__":
    raise SystemExit(main())
