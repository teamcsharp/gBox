"""Final Fantasy VII (PS1, USA): any character from gBox's collection in Cloud's place (the reverse of gbox.ff7_models).

`characters op=use` routes FF7 here. Two models are replaced, both rigid on Cloud's own skeletons so every field and
battle animation keeps playing:
  * field: FIELD/CLOUD.BCX (22 bones, 15 mesh parts). Native textured triangles retain donor-map interiors in Cloud's
    own FIELD.TDB face allocation; Gouraud triangles keep flat colours and FIELD.BIN's 240-entry lighting normals.
    Cloud-only expression table entries keep static donor maps across KAWAI updates. Budget: FIELD.BIN's file table
    loads exactly 7072 bytes (LBA 126841): the LZS-compressed file must not grow;
    per-part u8 vertex/polygon counts; GPU packet bytes (28 per G3) <= Cloud's.
    The 10 special-scene BSX files that carry their own copy of Cloud's mesh (e.g. CLSIN2_1, LAS4_4) are left as they are.
  * battle: ENEMY6/CLOUD.LZS (read_battle_model; 24 bones). Section 0 keeps textured donor faces as native textured
    triangles and uses Gouraud polygons for flat colours. The TIM keeps its allocation and upload coordinates;
    animations, settings and untextured weapons are copied unchanged.
    Compressed size <= the original file (66694 bytes).
Pipeline: Cloud posed in his standing frame -> target skeleton (joint per body role, ground, head height) ->
gbox.sm64_swap.load_rig + retarget -> Blender decimate until it fits (protect field texture patches) -> native polygons
and fixed texture banks -> LZS -> sectors of a raw copy of the disc rewritten in place
(gbox.psxdisc.RawBin, EDC/ECC) -> versioned immutable file mod. Discs 1-3 share the layout.

  python -m gbox.ff7_swap build <disc.chd|.bin> <character dir (meta.json)> <out dir> [--no-battle]
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import struct
import time
import uuid
from pathlib import Path

import numpy as np

from . import ff7_models as F

GAME_IDS = {"6703ee6f461a2ea5": "Final Fantasy VII (USA) (Disc 1)", "52d73a58e6b29209": "Final Fantasy VII (USA) (Disc 2)",
            "18581bf582f81eb2": "Final Fantasy VII (USA) (Disc 3)"}
C = np.diag([1.0, -1.0, -1.0])                     # PSX (y down) <-> y up
FIELD_NORMALS_AT = 0x3F520                         # FIELD.BIN (gunzipped): 240 x (s16 x, y, z, 0), 4096 = 1
NORMALS = 240
CACHE_VERSION = 4  # Native field textures and battle brightness; preserve earlier builds.
FIELD_FIT_HEIGHT = 1.0                             # x Cloud's height (whole figure), then at most HEIGHT_MAX
HEIGHT_MAX = 1.12
FIELD_ROLES = {"hip": 1, "chest": 2, "head": 3, "armA": (6, 7, 8), "armB": (11, 12, 13), "legA": (15, 16, 17),
               "legB": (19, 20, 21)}
BATTLE_ROLES = {"hip": 1, "chest": 2, "head": 3, "armA": (6, 7, 8), "armB": (11, 12, 13), "legA": (15, 16, 17),
                "legB": (20, 21, 22)}


# ---------------------------------------------------------------- LZS (FF7) encoder

def lzs_encode(data: bytes) -> bytes:
    """Greedy LZSS in FF7's LZS format (u32 compressed size, flag bytes LSB first, 1 = literal, references into a
    4 KiB ring that starts at 0xFEE, 3..18 bytes). ff7_models.lzs() decodes it."""
    n = len(data)
    out = bytearray()
    heads: dict[bytes, list[int]] = {}
    i = 0
    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            best_len, best_pos = 0, 0
            key = data[i:i + 3]
            if len(key) == 3:
                cands = heads.get(key, [])
                for j in reversed(cands[-64:]):
                    if i - j > 4078:
                        break
                    ln = 3
                    while ln < 18 and i + ln < n and data[j + ln] == data[i + ln]:
                        ln += 1
                    if ln > best_len:
                        best_len, best_pos = ln, j
                        if ln == 18:
                            break
            if best_len >= 3:
                o = (best_pos + 0xFEE) & 0xFFF
                out += bytes([o & 0xFF, ((o >> 4) & 0xF0) | (best_len - 3)])
                step = best_len
            else:
                flags |= 1 << bit
                out.append(data[i])
                step = 1
            for k in range(i, i + step):
                if k + 3 <= n:
                    heads.setdefault(data[k:k + 3], []).append(k)
            i += step
        out[flag_pos] = flags
    return struct.pack("<I", len(out)) + bytes(out)


# ---------------------------------------------------------------- shared: target skeleton + per-bone geometry

def make_target(W: list[np.ndarray], verts: dict[int, np.ndarray], spec: dict, fit_height: float | None) -> dict:
    """W: bone world matrices (PSX, column vectors); verts: {bone: posed PSX vertices}; spec: FIELD_ROLES-like."""
    Tg = np.array([C @ w[:3, 3] for w in W])
    allv = np.concatenate([v for v in verts.values()]) @ C.T
    feet = [spec["legA"][2], spec["legB"][2]]
    front = np.concatenate([verts[b] @ C.T - Tg[b] for b in feet if b in verts]).mean(0)
    front[1] = 0
    k = int(np.argmax(np.abs(front)))                       # models face along an axis: snap
    front = np.eye(3)[k] * np.sign(front[k])
    up = np.array([0, 1.0, 0])
    B = np.stack([np.cross(up, front), up, front])
    T = Tg @ B.T
    jmap = {"hip": spec["hip"], "chest": spec["chest"], "head": spec["head"]}
    a, b = spec["armA"], spec["armB"]
    if T[a[0]][0] < T[b[0]][0]:
        a, b = b, a
    for side, ch in (("l", a), ("r", b)):
        jmap.update({f"{side}_upper": ch[0], f"{side}_fore": ch[1], f"{side}_hand": ch[2]})
    a, b = spec["legA"], spec["legB"]
    if T[a[0]][0] < T[b[0]][0]:
        a, b = b, a
    for side, ch in (("l", a), ("r", b)):
        jmap.update({f"{side}_thigh": ch[0], f"{side}_shin": ch[1], f"{side}_foot": ch[2]})
    pc = allv @ B.T
    head = verts[spec["head"]] @ C.T @ B.T if spec["head"] in verts else pc
    parent = [-1] * len(W)
    tgt = {"W": W, "B": B, "T": T, "joints": len(W), "ground": float(pc[:, 1].min()), "head_h": float(np.ptp(head[:, 1])),
           "height": float(np.ptp(pc[:, 1])), "jmap": jmap, "parent": parent}
    if fit_height:
        tgt["fit_height"] = fit_height * tgt["height"]
    return tgt


def fit(tgt: dict, model: Path, roles: dict, scale=None, props=()) -> tuple[list[dict], dict]:
    """retarget + keep the figure under HEIGHT_MAX x the target's height (big heads shrink about their base)."""
    from .sm64_swap import load_rig, retarget
    rig = load_rig(Path(model), roles, props)
    prims, rep = retarget(rig, tgt, scale, jmap=tgt["jmap"])
    head_y = tgt["T"][tgt["jmap"]["head"]][1]
    top = max(float(p["pos"][:, 1].max()) for p in prims)
    want = tgt["ground"] + HEIGHT_MAX * tgt["height"]
    if top > want and top > head_y:
        k = max(0.25, (want - head_y) / (top - head_y))
        scale = dict(scale or {}) | {"head": float((scale or {}).get("head", 1.0)) * k}
        prims, rep = retarget(rig, tgt, scale, jmap=tgt["jmap"])
        rep["head_fit_to_height"] = round(k, 3)
    return prims, rep


def _corner_colour(p: dict, i: int) -> tuple[int, int, int]:
    col = np.array(p["color"][:3], float)
    if p["tex"] is None:
        return tuple(int(c) for c in col)
    t = np.asarray(p["tex"])
    h, w = t.shape[:2]
    u, v = (min(max(float(x), 0.0), 1.0) for x in p["uv"][i])
    px = t[min(int(v * h), h - 1), min(int(u * w), w - 1)]
    if t.shape[2] == 4 and px[3] < 128:                    # see-through texel: the texture's mean opaque colour
        a = t[..., 3] >= 128
        px = t[a].mean(0) if a.any() else px
    return tuple(int(c) for c in np.clip(px[:3].astype(float) * col / 255.0, 0, 255))


class BattleAtlas:
    """Keep donor texture interiors in Cloud's existing 4-bit TIM allocation.

    Cloud's weapons use untextured polygons. Refuse other layouts rather than
    silently repainting weapon textures or extending the native upload region.
    """
    def __init__(self, bm: dict, prims: list[dict]):
        from PIL import Image
        tim = bm['tim']
        if tim['bpp'] != 4 or tim['clut'] is None or tim['clut']['rows'].shape[1] != 16:
            raise ValueError('FF7 battle texture replacement requires a 4-bit TIM with 16-colour palettes')
        if any(w['mesh']['tt'] or w['mesh']['tq'] for w in bm['weapons']):
            raise ValueError('FF7 battle weapon textures share the TIM; preserve them before replacing it')
        height, width = tim['idx'].shape
        self.page = tim['x'] // 64 | (tim['y'] // 256) << 4
        self.clut = tim['clut']['x'] // 16 | tim['clut']['y'] << 6
        self.rects = {}
        canvas = np.zeros((height, width, 4), np.uint8)
        x = y = row_height = 0
        for p in prims:
            if p['tex'] is None:
                continue
            key = self.key(p)
            if key in self.rects:
                continue
            image = np.asarray(p['tex'], dtype=np.uint8)
            h, w = image.shape[:2]
            if w > width or h > height:
                raise ValueError('FF7 battle donor texture exceeds the native TIM allocation')
            if x+w > width:
                x = 0
                y += row_height
                row_height = 0
            if y+h > height:
                raise ValueError('FF7 battle donor textures do not fit the native TIM allocation')
            patch = canvas[y:y+h, x:x+w]
            patch[..., :3] = np.clip(image[..., :3].astype(float) * np.asarray(p['color'][:3]) / 255, 0, 255)
            patch[..., 3] = image[..., 3] if image.shape[2] == 4 else 255
            self.rects[key] = (x, y, w, h)
            x += w
            row_height = max(row_height, h)
        # Quantize only occupied opaque texels, so unused VRAM cannot consume a
        # palette entry. Index zero remains transparent; opaque black is 0x8000.
        mask = canvas[..., 3] >= 128
        if not mask.any():
            raise ValueError('FF7 battle donor textures have no opaque pixels')
        colours = Image.fromarray(canvas[..., :3][mask].reshape(1, -1, 3)).quantize(colors=15)
        palette = colours.getpalette() + [0] * 45
        indices = np.zeros((height, width), np.uint8)
        indices[mask] = np.asarray(colours).ravel() + 1
        rows = np.array(tim['clut']['rows'], copy=True)
        rows[0] = 0
        for i in range(15):
            r, g, b = (int(c) >> 3 for c in palette[3*i:3*i+3])
            rows[0, i+1] = (r | g << 5 | b << 10) or 0x8000
        packed = indices[:, 0::2] | (indices[:, 1::2] << 4)
        self.tim = (struct.pack('<II', 0x10, 8)
                    + struct.pack('<I4H', 12+rows.nbytes, tim['clut']['x'], tim['clut']['y'], 16, len(rows))
                    + rows.astype('<u2').tobytes()
                    + struct.pack('<I4H', 12+packed.nbytes, tim['x'], tim['y'], width//4, height)
                    + packed.tobytes())
        self.origin = ((tim['x'] % 64)*4, tim['y'] % 256)
        if self.origin[0]+width > 256 or self.origin[1]+height > 256:
            raise ValueError('FF7 battle TIM crosses a texture-page boundary')

    @staticmethod
    def key(p):
        import hashlib
        image = np.asarray(p['tex'])
        return (image.shape, hashlib.sha256(image.tobytes()).digest(), tuple(p['color'][:3]))

    def uv(self, p, ids):
        x, y, w, h = self.rects[self.key(p)]
        ox, oy = self.origin
        return [(ox+x+min(int(max(float(p['uv'][i][0]), 0)*w), w-1),
                 oy+y+min(int(max(float(p['uv'][i][1]), 0)*h), h-1)) for i in ids]


def bone_geometry(tgt: dict, prims: list[dict], bones_ok: set[int], atlas: BattleAtlas | None = None) -> dict[int, dict]:
    """read_rigged prims -> {bone: {"verts": [(x, y, z) local PSX ints], "nrm": [unit local], "tris": [((a, b, c),
    (col a, col b, col c))]}} with PSX winding (glTF CCW (a, b, c) -> (a, c, b)), vertices welded per bone."""
    out: dict[int, dict] = {}
    Winv = [np.linalg.inv(w) for w in tgt["W"]]
    for p in prims:
        for t in p["tris"]:
            b = int(np.bincount(p["jid"][t]).argmax())
            if b not in bones_ok:
                b = min(bones_ok, key=lambda k: np.linalg.norm(tgt["T"][k] - p["pos"][t].mean(0)))
            g = out.setdefault(b, {"verts": [], "nacc": [], "weld": {}, "tris": [], "tex_tris": []})
            ids, cols = [], []
            for i in t:
                pg = (p["pos"][i] @ tgt["B"]) @ C.T          # canonical -> y-up -> PSX
                ng = (p["nrm"][i] @ tgt["B"]) @ C.T
                lp = (Winv[b] @ np.r_[pg, 1.0])[:3]
                ln = Winv[b][:3, :3] @ ng
                k = tuple(np.clip(np.round(lp), -32768, 32767).astype(int))
                if k not in g["weld"]:
                    g["weld"][k] = len(g["verts"])
                    g["verts"].append(k)
                    g["nacc"].append(np.zeros(3))
                vi = g["weld"][k]
                g["nacc"][vi] += ln / (np.linalg.norm(ln) or 1)
                ids.append(vi)
                cols.append(_corner_colour(p, i))
            if len(set(ids)) == 3:
                if atlas is not None and getattr(atlas,'field',False) and p['tex'] is not None:
                    page,uv=atlas.uv(p,(t[0],t[2],t[1]))
                    g.setdefault('field_tex_tris',[]).append(((ids[0],ids[2],ids[1]),uv,page))
                elif atlas is not None and p['tex'] is not None:
                    uv = atlas.uv(p, (t[0], t[2], t[1]))
                    g['tex_tris'].append(((ids[0], ids[2], ids[1]), uv, atlas.clut))
                    g['texture_page'] = atlas.page
                else:
                    g["tris"].append(((ids[0], ids[2], ids[1]), (cols[0], cols[2], cols[1])))
    for g in out.values():
        g["nrm"] = [n / (np.linalg.norm(n) or 1) for n in g["nacc"]]
        g["quads"], g["tris"] = pair_quads(g["tris"], g["verts"])
    return out


def pair_quads(tris: list, verts: list) -> tuple[list, list]:
    """Merge coplanar triangles with matching edge colours into PS1 quads.

    FF7 culls the whole quad using only its first triangle. Folding a pair around
    an edge can therefore hide a front-facing triangle with its back-facing
    neighbour. Require exact coplanarity of the final integer vertices: no
    geometric tolerance can guarantee matching facing at silhouette angles.
    Shared corners also need identical colours; one quad cannot retain a seam.
    """
    # Cross-products of s16-coordinate differences can overflow int64 when
    # comparing the resulting normals. Use Python integers for exact tests.
    points = [tuple(map(int, p)) for p in verts]
    def sub(a, b):
        return tuple(x-y for x, y in zip(a, b))
    def cross(a, b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    edge = {}
    for k, ((a, b, c), _cols) in enumerate(tris):
        for e in ((a, b), (b, c), (c, a)):
            edge.setdefault(e, []).append(k)
    used, quads, rest = set(), [], []
    for k, ((a, b, c), cols) in enumerate(tris):
        if k in used:
            continue
        done = False
        for r in range(3):                                  # rotate so the shared edge is v1 -> v2
            v = (a, b, c)[r:] + (a, b, c)[:r]
            cv = cols[r:] + cols[:r]
            for j in edge.get((v[2], v[1]), []):
                if j == k or j in used:
                    continue
                (x, y, z), cj = tris[j]
                for s in range(3):                          # tri j as (v2, v1, d)
                    w = (x, y, z)[s:] + (x, y, z)[:s]
                    if w[0] == v[2] and w[1] == v[1]:
                        wc = cj[s:] + cj[:s]
                        d, cd = w[2], wc[2]
                        a0, b0, c0, d0 = (points[i] for i in (*v, d))
                        n1 = cross(sub(b0, a0), sub(c0, a0))
                        n2 = cross(sub(d0, b0), sub(c0, b0))
                        same_plane = any(n1) and any(n2) and not any(cross(n1, n2)) and sum(x*y for x,y in zip(n1,n2)) > 0
                        same_colour = tuple(cv[1]) == tuple(wc[1]) and tuple(cv[2]) == tuple(wc[0])
                        if d not in v and same_plane and same_colour:
                            quads.append(((v[0], v[1], v[2], d), (cv[0], cv[1], cv[2], cd)))
                            used |= {k, j}
                            done = True
                        break
                if done:
                    break
            if done:
                break
        if not done:
            used.add(k)
            rest.append(tris[k])
    return quads, rest


# ---------------------------------------------------------------- field (FIELD/CLOUD.BCX)

def field_normals(disc) -> np.ndarray:
    fb = gzip.decompress(disc.read("FIELD/FIELD.BIN")[8:])
    return np.frombuffer(fb[FIELD_NORMALS_AT:FIELD_NORMALS_AT + 8 * NORMALS], "<i2").reshape(-1, 4)[:, :3] / 4096.0


def field_spec(fm: dict) -> dict | None:
    """Body roles of a field skeleton from its topology (FF7 party layout: root -> pelvis 1 -> chest 2 -> head; each arm
    hangs off the pelvis through mesh-less joints, then upper / fore / hand; each leg off the root through a mesh-less
    joint, then thigh / shin / foot). None when the skeleton doesn't follow it (Cait Sith)."""
    bones = fm["bones"]
    kids = {i: [k for k, b in enumerate(bones) if b["parent"] == i] for i in range(len(bones))}
    W = F.field_pose(bones, fm["anims"][0][0] if fm["anims"] else None)
    y = {i: -W[i][1, 3] for i in range(len(bones))}       # height (PSX y is down)

    def depth(i):
        return 1 + max((depth(k) for k in kids[i]), default=0)

    def chain(start):                                     # the first three mesh bones down the deepest branch
        out, cur = [], start
        while cur is not None and len(out) < 3:
            if bones[cur]["has_mesh"]:
                out.append(cur)
            cur = max(kids[cur], key=depth) if kids[cur] else None
        return tuple(out) if len(out) == 3 else None
    if len(bones) < 4 or not bones[1]["has_mesh"] or not kids.get(1):
        return None
    chest = next((k for k in kids[1] if bones[k]["has_mesh"]), None)
    head = next((k for k in kids.get(chest, []) if bones[k]["has_mesh"]), None) if chest is not None else None
    arms = [c for c in (chain(k) for k in kids[1] if k != chest and not bones[k]["has_mesh"]) if c]
    legs = sorted((c for c in (chain(k) for k in kids[0] if k != 1) if c), key=lambda c: y[c[2]])[:2]   # lowest ends
    if len(arms) > 2:                                     # e.g. a tail: keep the two chains reaching furthest sideways
        arms = sorted(arms, key=lambda c: -abs(W[c[2]][0, 3] - W[1][0, 3]))[:2]
    if head is None or len(arms) != 2 or len(legs) != 2:
        return None
    return {"hip": 1, "chest": chest, "head": head, "armA": arms[0], "armB": arms[1], "legA": legs[0], "legB": legs[1]}


def field_target(fm: dict) -> dict:
    W = F.field_pose(fm["bones"], fm["anims"][0][0])
    verts = {p["bone"]: (np.c_[p["verts"], np.ones(len(p["verts"]))] @ W[p["bone"]].T)[:, :3] for p in fm["parts"]}
    spec = field_spec(fm)
    if spec is None:
        raise ValueError("this field skeleton doesn't have the party layout (two arms off the pelvis, two legs off the root)")
    return make_target(W, verts, spec, FIELD_FIT_HEIGHT)


def write_field(fm: dict, geo: dict[int, dict], normals: np.ndarray, nsign: float) -> tuple[bytes, dict]:
    """Rebuild the decompressed BCX: new part blocks at 8, the animation data copied after them, then the header,
    skeleton, part table and animation headers (pointers moved)."""
    u = fm["raw"]
    osk, op, oa = fm["skeleton"], fm["parts_off"], fm["anims_off"]
    h = fm["header"]
    nanim = len(fm["anims"])
    anim_hdr = [bytearray(u[osk + oa + 16 * k:osk + oa + 16 * k + 16]) for k in range(nanim)]
    data_offs = [struct.unpack_from("<I", a, 12)[0] & 0x7FFFFFFF for a in anim_hdr]
    a0, a1 = min(data_offs), h                               # animation data block (contiguous, before the header)
    blocks, table = bytearray(), []
    total_buf = 0
    for p in fm["parts"]:
        g = geo.get(p["bone"]) or {"verts": [(0, 0, 0)], "nrm": [np.array([0, 0, 1.0])], "tris": [((0, 0, 0), ((0, 0, 0),) * 3)],
                                   "quads": []}
        textured=g.get('field_tex_tris',[])
        nv, nt, nq, ntt = len(g["verts"]), len(g["tris"]), len(g["quads"]),len(textured)
        if nv > 255 or nt > 255 or nq > 255 or ntt>255:
            raise ValueError(f"bone {p['bone']}: {nv} vertices / {nt} triangles / {nq} quads (max 255 each per part)")
        nidx = [int(np.argmax(normals @ (nsign * n))) for n in g["nrm"]]
        blk = bytearray(4)
        for v in g["verts"]:
            blk += struct.pack("<hhhh", *v, 0)
        opoly = len(blk)
        uvpool=[];uvid={}
        for ids,uv,page in textured:
            blk+=bytes([*ids,0])
            for vi in ids:blk+=bytes([255,255,255,nidx[vi]])
            indices=[]
            for pair in uv:
                if pair not in uvid:uvid[pair]=len(uvpool);uvpool.append(pair)
                indices.append(uvid[pair])
            if len(uvpool)>255:raise ValueError('FF7 field part has more than 255 texture coordinates')
            blk+=bytes([*indices,0])
        for (a, b, c), cols in g["tris"]:
            blk += bytes([a, b, c, 0])
            for vi, col in zip((a, b, c), cols):
                blk += bytes([col[0], col[1], col[2], nidx[vi]])
        for ids, cols in g["quads"]:
            blk += bytes(ids)
            for vi, col in zip(ids, cols):
                blk += bytes([col[0], col[1], col[2], nidx[vi]])
        ofl=len(blk)
        if textured:blk+=struct.pack('<2I',0x78141c00,0x78141c01)
        otc=len(blk)
        for uv in uvpool:blk+=bytes(uv)
        octl=len(blk)
        blk+=bytes(page for ids,uv,page in textured)
        while len(blk)%4:blk+=b'\0'
        ovx = 8 + len(blocks)
        blocks += blk
        buf = 28 * nt + 36 * nq + 40 * ntt
        total_buf += buf
        table.append(struct.pack("<12B2B5H2I", p["raw"][0], p["bone"], nv, len(uvpool), 0, ntt, 0, 0, 0, 0, nt, nq, 2 if textured else 0, ntt,
                                 opoly, otc, ofl, octl, buf, ovx | 0x80000000, 0))
    out = bytearray(8) + blocks
    shift = len(out) - a0
    out += u[a0:a1]                                          # animation data (+ anything between it and the header)
    new_h = len(out)
    out += u[h:osk + op]                                     # header .. skeleton
    for t in table:
        out += t
    for a, d in zip(anim_hdr, data_offs):
        struct.pack_into("<I", a, 12, (d + shift) | 0x80000000)
        out += a
    out += u[osk + oa + 16 * nanim:]                         # tail after the animation headers (if any)
    struct.pack_into("<I", out, new_h + 0x1C, (osk - h + new_h) | 0x80000000)
    struct.pack_into("<II", out, 0, len(out), new_h)
    old_buf = sum(p["buffer"] for p in fm["parts"])
    return bytes(out), {"bytes": len(out), "budget_bytes": len(u), "gpu_buffer": total_buf, "budget_gpu_buffer": old_buf,
                        "triangles": sum(len(g["tris"]) + 2 * len(g["quads"])+len(g.get('field_tex_tris',[])) for g in geo.values()),
                        "textured_triangles":sum(len(g.get('field_tex_tris',[])) for g in geo.values()),
                        "quads": sum(len(g["quads"]) for g in geo.values()),
                        "verts": sum(len(g["verts"]) for g in geo.values())}


# ---------------------------------------------------------------- battle (ENEMY6/CLOUD.LZS)

def battle_target(bm: dict, anim: int = 0) -> dict:
    nb = len(bm["bones"]) - 1
    frames = F.read_animation(bm["raw"], bm["anims"][anim], nb)
    W = F.pose(bm["bones"], frames[0] if frames else None)
    verts = {i: (np.c_[b["mesh"]["verts"], np.ones(len(b["mesh"]["verts"]))] @ W[i].T)[:, :3]
             for i, b in enumerate(bm["bones"]) if b["mesh"]}
    return make_target(W, verts, BATTLE_ROLES, FIELD_FIT_HEIGHT)


def write_battle(bm: dict, geo: dict[int, dict], tim: bytes | None = None) -> tuple[bytes, dict]:
    """Rebuild section 0 and optionally the same-size TIM; preserve animations, settings and weapons."""
    u, offs = bm["raw"], bm["sections"]
    ns = len(offs)
    base = offs[0]
    nb = struct.unpack_from("<I", u, base)[0]
    sec = bytearray(u[base:base + 4 + 8 * (nb + 1)])
    for i in range(nb + 1):
        g = geo.get(i)
        if not g:
            struct.pack_into("<I", sec, 4 + 8 * i + 4, 0)
            continue
        struct.pack_into("<I", sec, 4 + 8 * i + 4, len(sec))
        mesh = bytearray(struct.pack("<I", 8 * len(g["verts"])))
        for v in g["verts"]:
            mesh += struct.pack("<hhhh", *v, 0)
        mesh += struct.pack('<HH', len(g.get('tex_tris', [])), g.get('texture_page', 0))
        for ids, uv, clut in g.get('tex_tris', []):
            # The fourth WORD is a polygon attribute, not padding: the native
            # renderer uses its low byte as texture brightness (model flag 0x80).
            # Match stock Cloud's neutral 0x80; zero blacks out the texture.
            mesh += struct.pack('<4H', *(8*j for j in ids), 0x80)
            mesh += struct.pack('<BBH4B', *uv[0], clut, *uv[1], *uv[2])
        mesh += struct.pack('<HH', 0, 0)                     # no textured quads
        mesh += struct.pack("<HH", len(g["tris"]), 0)
        for (a, b, c), cols in g["tris"]:
            mesh += struct.pack("<4H", 8 * a, 8 * b, 8 * c, 0)
            for k, col in enumerate(cols):
                mesh += bytes([col[0], col[1], col[2], 0x30 if k == 0 else 0])
        mesh += struct.pack("<HH", len(g["quads"]), 0)
        for ids, cols in g["quads"]:
            mesh += struct.pack("<4H", *(8 * i for i in ids))
            for k, col in enumerate(cols):
                mesh += bytes([col[0], col[1], col[2], 0x38 if k == 0 else 0])
        sec += mesh
    sec += bytes(-len(sec) % 4)
    new = [4 + 4 * ns]
    body = bytearray(sec)
    for k in range(1, ns):
        end = offs[k + 1] if k + 1 < ns else len(u)
        new.append(new[0] + len(body))
        section = u[offs[k]:end]
        if tim is not None and len(section) >= 8 and struct.unpack_from('<II', section) in ((0x10, 8), (0x10, 9)):
            if len(tim) != len(section):
                raise ValueError('FF7 replacement TIM must preserve the native upload size')
            section = tim
        body += section
    out = struct.pack(f"<I{ns}I", ns, *new) + bytes(body)
    return out, {"bytes": len(out), "budget_bytes": len(u),
                 "gpu_buffer": sum(28*len(g['tris']) + 36*len(g['quads']) + 32*len(g.get('tex_tris', []))
                                   for g in geo.values()),
                 "budget_gpu_buffer": sum(sum(len(b['mesh'][k])*size for k, size in
                                               (('tt', 32), ('tq', 40), ('ct', 28), ('cq', 36)))
                                          for b in bm['bones'] if b['mesh']),
                 "triangles": sum(len(g["tris"]) + 2 * len(g["quads"]) + len(g.get('tex_tris', [])) for g in geo.values()),
                 "textured_triangles": sum(len(g.get('tex_tris', [])) for g in geo.values()),
                 "quads": sum(len(g["quads"]) for g in geo.values()), "verts": sum(len(g["verts"]) for g in geo.values())}


# ---------------------------------------------------------------- build

def _fit_loop(name: str, tgt: dict, model: Path, roles: dict, work: Path, blender, make, start_tris: int, progress,
              scale=None, props=(), protect_textures=False) -> tuple[bytes, dict, Path]:
    """retarget once, then decimate (Blender) until make(read_rigged prims) returns (bytes, report, ok)."""
    from .sm64_swap import read_rigged, write_rigged
    from .re4gc_enemies import decimate
    prims, rep = fit(tgt, model, roles, scale, props)
    work.mkdir(parents=True, exist_ok=True)
    rigged = write_rigged(prims, tgt, work / f"{name}.gltf", name)
    fixed=[p for p in prims if protect_textures and p['tex'] is not None]
    reduced=[p for p in prims if not (protect_textures and p['tex'] is not None)]
    fixed_tris=sum(len(p['tris']) for p in fixed)
    reduce_path=write_rigged(reduced,tgt,work/f'{name}_body.gltf',name) if fixed and reduced else rigged
    fixed_read=[dict(p,jid=p['J'][:,0]) for p in fixed]
    src_tris = sum(len(p["tris"]) for p in prims)
    target = min(src_tris, start_tris)
    last = None
    for _ in range(10):
        src = reduce_path
        if target < src_tris:
            if target<=fixed_tris or not reduced:
                raise ValueError(f'{name}: protected texture surfaces exceed the native model budget ({last})')
            if not blender:
                raise ValueError(f"{name}: needs decimating ({last}) and there's no Blender on this node")
            progress(None, f"{name}: decimating {src_tris} -> {target} triangles")
            src = decimate(reduce_path, work / f"{name}_d{target}.glb", float(target-fixed_tris), blender)
        geometry=read_rigged(src)+fixed_read if fixed and reduced else read_rigged(src)
        data, r, ok, k = make(geometry)
        last = r
        if ok:
            from . import fit_events as FE
            FE.comparison(prims, geometry, reason="Original triangle count kept" if sum(len(p['tris']) for p in geometry)==src_tris
                          else "Writer allocation / configured triangle budget",
                          limits={"configured_triangle_budget": start_tris, "encoded": r})
            return data, rep | r | {"source_triangles": src_tris,"protected_texture_triangles":fixed_tris}, rigged
        target = int(min(target, r.get("triangles", target)) * min(k, 0.97))
    raise ValueError(f"{name} doesn't fit: {last}")


def build(disc: Path, model_path: Path, roles: dict, work: Path, name: str, out_bin: Path, base_bin: Path | None = None,
          battle: bool = True, blender: str | None = None, progress=lambda p, m: None, scale=None, props=()) -> dict:
    from . import psxdisc
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    if base_bin is None:
        base_bin = work / "base.bin"
        if not base_bin.exists():
            progress(3, "Unpacking the disc to a raw image")
            psxdisc.chd_to_bin(disc, base_bin)
    src = psxdisc.RawBin(base_bin, writable=False)
    bcx_lba, bcx_size = src.files["FIELD/CLOUD.BCX"]
    fm = F.read_field_model(src.read("FIELD/CLOUD.BCX"))
    normals = field_normals(src)
    # lighting normals point outward; check the sign on Cloud's own vertices
    dots = []
    for p in fm["parts"]:
        cen = p["verts"].mean(0)
        for pl in p["polys"]:
            for vi, ni in zip(pl["idx"], pl["nrm"]):
                if ni < NORMALS:
                    dots.append(float((p["verts"][vi] - cen) @ normals[ni]))
    nsign = 1.0 if np.mean(np.sign(dots)) >= 0 else -1.0
    res = {"normal_sign": nsign}
    progress(10, f"Fitting {name} onto Cloud's field skeleton")
    ftgt = field_target(fm)
    mesh_bones = {p["bone"] for p in fm["parts"]}
    field_atlas=None

    def make_field(rp):
        nonlocal field_atlas
        if field_atlas is None and any(p['tex'] is not None for p in rp):
            from .ff7_field_textures import FieldAtlas
            field_atlas=FieldAtlas(src.read('FIELD/FIELD.TDB'),src.read('FIELD/FIELD.BIN'),rp)
        geo = bone_geometry(ftgt, rp, mesh_bones,field_atlas)
        try:
            raw, r = write_field(fm, geo, normals, nsign)
        except ValueError as e:
            per = max(max(len(g["verts"]), len(g["tris"])) for g in geo.values())
            return None, {"error": str(e), "triangles": sum(len(g["tris"]) for g in geo.values())}, False, 250 / per
        comp = lzs_encode(raw)
        assert F.lzs(comp) == raw
        r["compressed"] = len(comp)
        r["budget_compressed"] = bcx_size
        ok = len(comp) <= bcx_size and r["bytes"] <= r["budget_bytes"] and r["gpu_buffer"] <= r["budget_gpu_buffer"]
        k = min(bcx_size / len(comp), r["budget_bytes"] / r["bytes"], r["budget_gpu_buffer"] / max(r["gpu_buffer"], 1))
        return comp, r, ok, k
    bcx, frep, frig = _fit_loop("ff7_field", ftgt, model_path, roles, work, blender, make_field, 640, progress, scale, props,protect_textures=True)
    encoded_field=F.read_field_model(bcx)
    if field_atlas:
        from .ff7_field_textures import face_tim
        encoded_field['tim']=face_tim(field_atlas.tdb,field_atlas.field)
    native_preview=work/'ff7_field_native.gltf'
    F.field_to_gltf(encoded_field,native_preview)
    res["field"] = frep
    res["rigged_field"] = str(native_preview)
    writes = [("FIELD/CLOUD.BCX", bcx)]
    if field_atlas:
        frep['textures']=field_atlas.report
        writes.extend([('FIELD/FIELD.TDB',field_atlas.tdb),('FIELD/FIELD.BIN',field_atlas.field)])
    if battle:
        progress(45, f"Fitting {name} onto Cloud's battle skeleton")
        blba, bsize = src.files["ENEMY6/CLOUD.LZS"]
        bm = F.read_battle_model(src.read("ENEMY6/CLOUD.LZS"))
        btgt = battle_target(bm)
        bbones = {i for i, b in enumerate(bm["bones"]) if b["mesh"]}

        def make_battle(rp):
            atlas = BattleAtlas(bm, rp) if any(p['tex'] is not None for p in rp) else None
            geo = bone_geometry(btgt, rp, bbones, atlas)
            raw, r = write_battle(bm, geo, atlas.tim if atlas else None)
            comp = lzs_encode(raw)
            r["compressed"] = len(comp)
            r["budget_compressed"] = bsize
            ok = len(comp) <= bsize and r["bytes"] <= r["budget_bytes"] and r['gpu_buffer'] <= r['budget_gpu_buffer']
            return comp, r, ok, min(bsize / len(comp), r["budget_bytes"] / r["bytes"],
                                   r['budget_gpu_buffer'] / max(r['gpu_buffer'], 1))
        blz, brep, brig = _fit_loop("ff7_battle", btgt, model_path, roles, work, blender, make_battle, 2000, progress,
                                    scale, props)
        F.read_battle_model(blz)
        res["battle"] = brep
        res["rigged_battle"] = str(brig)
        writes.append(("ENEMY6/CLOUD.LZS", blz))
    src.close()
    progress(75, "Copying the disc image")
    out_bin = Path(out_bin)
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base_bin, out_bin)
    rb = psxdisc.RawBin(out_bin)
    res["sectors_written"] = sum(rb.write_file(k, 0, data) for k, data in writes)
    rb.close()
    out_bin.with_suffix(".cue").write_text(f'FILE "{out_bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    res |= {"bin": str(out_bin), "cue": str(out_bin.with_suffix(".cue"))}
    return res


# ---------------------------------------------------------------- characters op=use

def image_name(meta: dict, gid: str) -> str:
    disc = {"52d73a58e6b29209": "2", "18581bf582f81eb2": "3"}.get(gid, "1")
    return "Final Fantasy VII - " + re.sub(r"[^\w .()'-]+", "", meta["name"]).strip() + f" (USA) (Disc {disc}).bin"


def mod_name(meta: dict) -> str:
    return f"ff7_{meta['slug']}_v{CACHE_VERSION}"


def build_mod(cfg, meta: dict, game: dict, progress=lambda p, m: None, root: Path | None = None) -> dict:
    from . import characters as Cm
    from . import filemods
    from .pe_swap import base_bin
    root = root or Cm.library_root(cfg)
    gid, name = game["game_id"], mod_name(meta)
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json): can't map it onto Cloud's bones")
    base = base_bin(cfg, game, progress)
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        name += '_' + uuid.uuid4().hex[:12]
        d = filemods.mod_dir(cfg, gid, name)
    d.mkdir(parents=True, exist_ok=False)
    work = Path(cfg.cache) / "characters_build" / gid / name
    work.mkdir(parents=True, exist_ok=False)
    img = image_name(meta, gid)
    b = build(base, root / meta["slug"] / meta["model"], roles, work, meta["name"], d / img, base, battle=True,
              blender=Cm._blender(cfg), progress=progress, scale=(meta.get("rig") or {}).get("scale"),
              props=[p["node"] for p in meta.get("props") or []])
    progress(88, "Rendering a preview of the model on Cloud's skeleton")
    tdir = root / meta["slug"] / "targets" / gid / name
    tdir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(b["rigged_field"], tdir / "ff7_cloud_field.gltf")
    prev = Cm.render_preview(tdir / "ff7_cloud_field.gltf", tdir / "ff7_preview.png")
    cue = Path(b["cue"]).name
    mj = {"name": name, "game_id": gid, "image": cue, "built": time.time(), "character": meta["slug"],
          "writer_version": CACHE_VERSION,
          "files": ["FIELD/CLOUD.BCX (field model)", "ENEMY6/CLOUD.LZS (battle model)"]+
                   (["FIELD/FIELD.TDB (Cloud face banks)","FIELD/FIELD.BIN (Cloud expression mapping)"] if b['field'].get('textures') else []), "source": meta["model"],
          "field": b["field"], "battle": b.get("battle")}
    (d / ".gbox-mod.json").write_text(json.dumps(mj, default=str))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": cue, "preview": str(prev), "report": {"field": b["field"], "battle": b.get("battle")}}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """Build/reuse the current writer version; an explicit rebuild creates a new immutable output."""
    from . import characters as Cm
    from .sm64_swap import _have_mod, _wait
    gid, name = game["game_id"], mod_name(meta)
    if meta.get("source", {}).get("game_id") in GAME_IDS and meta["slug"] in ("cloud", "ff7_cloud") \
            and not meta.get("variant_of"):
        return {"status": "native", "message": f"{meta['name']} is FF7's own player: launch the game without a mod."}
    sess = Cm._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else Cm.HOST_OS
    built = None
    if inp.rebuild or not _have_mod(ctx, gid, name):
        if Cm.library_root(ctx.config).is_dir():
            built = build_mod(ctx.config, meta, game, ctx.progress)
            name = built['mod']
            Cm._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                    json={"game_id": gid, "slot": "player", "mod": name, "nodes": [Cm.HOST_OS],
                          "notes": f"replaces Cloud: field model {built['report']['field']['triangles']} triangles, battle "
                                   f"model {(built['report']['battle'] or {}).get('triangles')} triangles (his animations); "
                                   f"preview targets/{gid}/{name}/ff7_preview.png"})
        else:
            cp = next((w["id"] for w in Cm._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
            ctx.progress(10, "Building the FF7 mod on the control-plane node (the collection lives there)")
            j = Cm._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid, "rebuild": inp.rebuild,
                                            "launch": False}, cp, 3600)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
                return {"status": "failed", "mod": name, "error": r.get("error") or j.get("error") or r}
            built = r.get("build")
            name = r['mod']
    res = {"mod": name, "build": built, "replaces": "Cloud Strife (field + battle models; his skeletons and animations stay)"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(90, f"Launching Final Fantasy VII with {meta['name']} (mod {name})")
    lj = _wait(ctx, Cm._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name,
                                                                                          "node": node}}), 600)
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = (f"Final Fantasy VII is running with {meta['name']} in Cloud's place (mod {name}, session {launch['session_id']}). "
           "Field and battle models are replaced; FMVs and the menu portrait stay Cloud."
           if ok else f"Mod {name} is {'built' if built else 'ready'} but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": ("built+launched" if built else "launched") if ok else f"launch {lj.get('state')}",
                  "launch": launch, "message": msg}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("disc")
    b.add_argument("character", help="library entry folder (meta.json + model)")
    b.add_argument("out")
    b.add_argument("--no-battle", action="store_true")
    a = ap.parse_args()
    cdir = Path(a.character)
    meta = json.loads((cdir / "meta.json").read_text())
    od = Path(a.out)
    from .sm64_swap import _blender
    disc = Path(a.disc)
    res = build(disc, cdir / meta["model"], meta["rig"]["roles"], od / "work", meta["name"], od / f"ff7_{meta['slug']}.bin",
                disc if disc.suffix.lower() == ".bin" else None, not a.no_battle, _blender(),
                lambda p, m: print(f"{p if p is not None else '':>5} {m}", flush=True))
    from .characters import render_preview
    for k in ("rigged_field", "rigged_battle"):
        if res.get(k):
            render_preview(Path(res[k]), Path(res[k]).with_suffix(".png"))
    print(json.dumps(res, indent=1, default=str))
