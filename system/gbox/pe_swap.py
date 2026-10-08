"""Parasite Eve (PS1, USA): any character from gBox's collection in Aya Brea's place (the reverse of gbox.parasite_eve).

`characters op=use` routes PE here. Pipeline (the operator's own disc + collection, nothing downloaded):
  1. Aya's model of every outfit (PE.IMG common blobs 18..22) posed in its rest animation (frame 0 of the lowest
     animation id, the pose the extractor binds) -> target skeleton: joint positions per body role (OUTFIT_BONES),
     ground, head height; PSX axes turned to the retargeter's frame (left +X, up +Y, front +Z).
  2. gbox.sm64_swap.load_rig + retarget (the generic rigid retarget: torso on the hip/chest, head on Aya's head bone,
     limbs rotated + stretched onto her arm/leg segments). Aya's bone count, hierarchy, traversal list and per-bone
     bounding spheres never change, so all her animations (field + battle: PE fights in the field) keep playing.
  3. Budget = Aya's own outfit model: model bytes <= her model's size in the blob (the blob keeps its sectors), vertices
     <= hers (transform scratch), GPU packet bytes (GT3 0x50, GT4 0x68 per prim, double-buffered) <= hers. Over budget
     -> Blender edge-collapse decimate (scripts/decimate_gltf.py via re4gc_enemies.decimate), then fewer triangles.
  4. Model bytes (parasite_eve.Model layout): per-bone contiguous vertex ranges (bone-local s16 + nearest of the EXE's
     240 vertex normals), vertex colours 128, one GT3 per triangle (code 15 = opaque), UVs in Aya's texture page
     (tpage 0x1F = 4-bit page at VRAM 960,256) with one of her 32 CLUT slots (VRAM rows 448/449).
  5. Texture blob (13..17): the same three VRAM uploads, re-filled: the character's textures packed into the 256x256
     4-bit page (one 15-colour CLUT per texture), flat colours as 4x4 cells on shared CLUTs.
  6. A copy of the raw disc (.bin/.cue): PE.IMG sectors of the 10 blobs rewritten in place, EDC/ECC recomputed
     (gbox.psxdisc.RawBin) -> file mod cache/mods/<game_id>/pe_<slug> (launch_game mod=...).

  python -m gbox.pe_swap build <disc.chd> <character dir (with meta.json)> <out dir> [--outfits 0,1,2,3,4]
"""
from __future__ import annotations

import json
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from . import parasite_eve as P

GAME_IDS = {"c0b85e0b89f6de74": "Parasite Eve (USA) (Disc 1)", "2ad5e8b6a18702cb": "Parasite Eve (USA) (Disc 2)"}
TPAGE = 0x1F                                   # Aya's texture page: 4-bit, VRAM x 960, y 256
CLUT_SLOTS = [0x7000 + i for i in range(16)] + [0x7040 + i for i in range(16)]    # VRAM (0..240, 448) and (.., 449)
FIT_HEIGHT = 0.9                               # the character is scaled to this x Aya's height (not to her head joint)
HEIGHT_MAX = 1.1                               # after the fit, its top at most this x her height (big heads shrink)
NORMALS = 240                                  # the EXE's vertex normal table (0x80091A58): 240 unit vectors
# per outfit: body roles -> Aya bone (chains A/B are put on left/right by geometry, see aya_target)
OUTFIT_BONES = {
    0: {"chest": 1, "neck": 10, "head": 11, "hip": 20, "armA": (3, 4, 5, 6), "armB": (13, 14, 15, 16), "legA": (22, 23, 24), "legB": (26, 27, 28)},
    1: {"chest": 1, "neck": 7, "head": 8, "hip": 14, "armA": (3, 4, 5, 6), "armB": (10, 11, 12, 13), "legA": (16, 17, 18), "legB": (20, 21, 22)},
    2: {"chest": 1, "neck": 10, "head": 11, "hip": 20, "armA": (3, 4, 5, 6), "armB": (13, 14, 15, 16), "legA": (22, 23, 24), "legB": (26, 27, 28)},
    3: {"chest": 1, "neck": 10, "head": 11, "hip": 20, "armA": (3, 4, 5, 6), "armB": (13, 14, 15, 16), "legA": (22, 23, 24), "legB": (26, 27, 28)},
    4: {"chest": 1, "neck": 9, "head": 10, "hip": 22, "armA": (3, 4, 5, 6), "armB": (16, 17, 18, 19), "legA": (24, 25, 26), "legB": (28, 29, 30)},
}
C = np.diag([1.0, -1.0, -1.0])                 # PSX (y down, z in) <-> glTF-like y up


# ---------------------------------------------------------------- target: Aya's skeleton

def aya_target(pe: P.PEData, outfit: int) -> dict:
    blob = pe.common_blob(P.AYA_MODEL_BLOB + outfit)
    model, anims, entry = P.load_model_blob(blob)
    rest = anims.get(min(anims)) if anims else None
    world, parent = P.pose(model, rest, 0)
    Tg = np.array([C @ t for _r, t in world])
    pv = P.posed_vertices(model, world) @ C.T
    ob = OUTFIT_BONES[outfit]
    # facing: up = +y; front = where the head's bulk sits from its joint (face/nose; the feet of some rest poses point
    # backwards), snapped to the nearest axis; left = up x front
    hb0 = model.bones[ob["head"]]
    front = pv[hb0[0]:hb0[0] + hb0[1]].mean(0) - Tg[ob["head"]]
    front[1] = 0
    k = int(np.argmax(np.abs(front)))
    front = np.eye(3)[k] * np.sign(front[k])
    up = np.array([0, 1.0, 0])
    left = np.cross(up, front)
    B = np.stack([left, up, front])                    # rows: canonical axes in glTF-like coordinates
    T = Tg @ B.T
    jmap = {"hip": ob["hip"], "chest": ob["chest"], "head": ob["head"]}
    a, b = ob["armA"], ob["armB"]
    if T[a[1]][0] < T[b[1]][0]:                         # chain A on the character's right
        a, b = b, a
    for side, ch in (("l", a), ("r", b)):
        jmap.update({f"{side}_upper": ch[1], f"{side}_fore": ch[2], f"{side}_hand": ch[3]})
    a, b = ob["legA"], ob["legB"]
    if T[a[0]][0] < T[b[0]][0]:
        a, b = b, a
    for side, ch in (("l", a), ("r", b)):
        jmap.update({f"{side}_thigh": ch[0], f"{side}_shin": ch[1], f"{side}_foot": ch[2]})
    pc = pv @ B.T
    hb = model.bones[ob["head"]]
    head = pc[hb[0]:hb[0] + hb[1]]
    return {"model": model, "blob": blob, "entry": entry, "world": world, "B": B, "T": T, "parent": parent,
            "joints": model.nbones, "ground": float(pc[:, 1].min()), "head_h": float(np.ptp(head[:, 1])),
            "jmap": jmap, "height": float(np.ptp(pc[:, 1])), "fit_height": FIT_HEIGHT * float(np.ptp(pc[:, 1])),
            "outfit": outfit}


# ---------------------------------------------------------------- textures: page + CLUTs

def _c15(rgb) -> int:
    r, g, b = (int(x) >> 3 for x in rgb[:3])
    v = r | (g << 5) | (b << 10)
    return v or 0x8000                                 # 0x0000 is see-through on the PS1: opaque black instead


def _quantize(img: np.ndarray, n: int = 15) -> tuple[np.ndarray, list[int]]:
    from PIL import Image
    rgb = Image.fromarray(np.ascontiguousarray(img[..., :3]), "RGB")
    q = rgb.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:3 * n]
    idx = np.asarray(q, np.uint8)
    cols = [_c15(pal[3 * i:3 * i + 3]) for i in range(len(pal) // 3)]
    return idx, cols + [0x8000] * (16 - len(cols))


class Atlas:
    """The character's materials -> 256x256 4-bit page (indices) + CLUT slots. Textures keep their size up to 64 px
    (larger ones are halved) with a 1-texel border; flat colours are 4x4 cells (15 per CLUT)."""

    def __init__(self):
        self.idx = np.zeros((256, 256), np.uint8)
        self.cluts: list[list[int]] = []
        self.x = self.y = self.row_h = 0
        self.flat_clut = None
        self.flat_n = 15
        self.mat: dict = {}

    def _place(self, w: int, h: int) -> tuple[int, int]:
        if self.x + w > 256:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        if self.y + h > 255:                            # row 255 is uploaded separately: keep it free
            raise ValueError("the character's textures don't fit Aya's 256x256 texture page")
        x, y = self.x, self.y
        self.x += w
        self.row_h = max(self.row_h, h)
        return x, y

    def add(self, key, tex, color) -> None:
        from .sm64_swap import _fill_alpha
        col = np.array(color[:3], float) / 255
        if tex is None:
            if self.flat_clut is None or self.flat_n >= 15:
                if len(self.cluts) >= len(CLUT_SLOTS):
                    raise ValueError("more than 32 palettes")
                self.cluts.append([0x8000] * 16)
                self.flat_clut, self.flat_n = len(self.cluts) - 1, 0
            k = self.flat_n
            self.flat_n += 1
            self.cluts[self.flat_clut][k] = _c15(col * 255)
            x, y = self._place(4, 4)
            self.idx[y:y + 4, x:x + 4] = k
            self.mat[key] = ("flat", x + 1.5, y + 1.5, self.flat_clut)
            return
        if len(self.cluts) >= len(CLUT_SLOTS):
            raise ValueError("more than 32 palettes")
        img = _fill_alpha(np.asarray(tex, np.uint8))
        if (col < 0.999).any():
            img = img.copy()
            img[..., :3] = (img[..., :3] * col).astype(np.uint8)
        while img.shape[0] > 64 or img.shape[1] > 64:
            img = img[::2, ::2]
        h, w = img.shape[:2]
        idx, pal = _quantize(img)
        self.cluts.append(pal)
        x, y = self._place(w + 2, h + 2)
        pad = np.pad(idx, 1, mode="edge")
        self.idx[y:y + h + 2, x:x + w + 2] = pad
        self.mat[key] = ("tex", x + 1, y + 1, w, h, len(self.cluts) - 1)

    def uv(self, key, uv) -> tuple[list[tuple[int, int]], int]:
        m = self.mat[key]
        if m[0] == "flat":
            return [(int(m[1]), int(m[2]))] * len(uv), CLUT_SLOTS[m[3]]
        _k, x, y, w, h, ci = m
        out = []
        for u, v in uv:
            u, v = min(max(float(u), 0.0), 1.0), min(max(float(v), 0.0), 1.0)
            out.append((int(round(x + u * (w - 1))), int(round(y + v * (h - 1)))))
        return out, CLUT_SLOTS[ci]

    def vram_into(self, vram: P.VRAM) -> None:
        px, py = (TPAGE & 15) * 64, ((TPAGE >> 4) & 1) * 256
        i = self.idx.astype(np.uint16)
        vram.m[py:py + 256, px:px + 64] = i[:, 0::4] | (i[:, 1::4] << 4) | (i[:, 2::4] << 8) | (i[:, 3::4] << 12)
        for k, pal in enumerate(self.cluts):
            c = CLUT_SLOTS[k]
            cx, cy = (c & 63) * 16, (c >> 6) & 511
            vram.m[cy, cx:cx + 16] = pal


def tex_blob(old: bytes, vram: P.VRAM) -> bytes:
    """The texture blob with every type-9 upload re-read from `vram` (same rects, same offsets, same size)."""
    out = bytearray(old)
    d = P.section_dir(old)
    c, o = d[9]
    for k in range(c):
        e = old[o + 20 * k:o + 20 * k + 20]
        off = struct.unpack_from("<I", e, 4)[0]
        h = (off >> 24) or 256
        off &= 0xFFFFFF
        r = struct.unpack_from("<I", e, 8)[0]
        x, y, w = (r >> 10) & 0x7FF, r >> 21, r & 0x3FF
        out[off:off + w * h * 2] = vram.m[y:y + h, x:x + w].astype("<u2").tobytes()
        off2 = struct.unpack_from("<I", e, 12)[0]
        if off2 & 0xFFFFFF:
            r2 = struct.unpack_from("<I", e, 16)[0]
            x2, y2, w2, h2 = (r2 >> 10) & 0x7FF, r2 >> 21, r2 & 0x3FF, off2 >> 24
            o2 = off + (off2 & 0xFFFFFF)
            out[o2:o2 + w2 * h2 * 2] = vram.m[y2:y2 + h2, x2:x2 + w2].astype("<u2").tobytes()
    return bytes(out)


# ---------------------------------------------------------------- model bytes

def _local(tgt: dict, b: int, pc: np.ndarray, nc: np.ndarray | None = None):
    """Canonical-frame points (+ normals) -> bone b's local PSX frame."""
    R, t = tgt["world"][b]
    p = (pc @ tgt["B"]) @ C.T                          # canonical -> glTF-like -> PSX (C is its own inverse)
    lp = (p - t) @ R                                   # R^T (p - t)
    if nc is None:
        return lp
    n = (nc @ tgt["B"]) @ C.T
    return lp, n @ R


def build_model(tgt: dict, prims: list[dict], atlas: Atlas, normals: np.ndarray) -> tuple[bytes, dict]:
    """read_rigged prims (canonical world positions, jid = Aya bone) -> PE model bytes with Aya's bones/traversal."""
    m, blob, e = tgt["model"], tgt["blob"], tgt["entry"]
    off = e["offset"]
    nb = m.nbones
    per_bone: dict[int, list] = {b: [] for b in range(nb)}           # (local corner positions, normals, uv, key)
    for p in prims:
        key = (id(p["tex"]) if p["tex"] is not None else None, tuple(p["color"][:3]))
        for t in p["tris"]:
            b = int(np.bincount(p["jid"][t]).argmax())
            lp, ln = _local(tgt, b, p["pos"][t], p["nrm"][t])
            per_bone[b].append((lp, ln, [tuple(p["uv"][i]) for i in t], key))
    verts, vnrm, bones, tris = [], [], [], []
    for b in range(nb):
        first, cnt, geo, parent, oz = m.bones[b]
        start = len(verts)
        if not per_bone[b]:                                            # no geometry here: keep Aya's pivot vertex
            verts.append(np.round(m.verts[first]).astype(int))
            vnrm.append(int(m.vnorm[first]))
            bones.append((start, 1, geo if cnt == 1 and not geo else 0, parent, oz))
            continue
        weld: dict = {}
        acc_n: dict = {}
        for lp, ln, uv, key in per_bone[b]:
            ids = []
            for q, n in zip(lp, ln):
                k = tuple(np.clip(np.round(q), -32768, 32767).astype(int))
                if k not in weld:
                    weld[k] = len(verts)
                    verts.append(np.array(k))
                    acc_n[weld[k]] = np.zeros(3)
                acc_n[weld[k]] += n / (np.linalg.norm(n) or 1)
                ids.append(weld[k])
            if len(set(ids)) == 3:
                tris.append((ids, uv, key))
        for vi in range(start, len(verts)):
            n = acc_n[vi]
            n = n / (np.linalg.norm(n) or 1)
            vnrm.append(int(np.argmax(normals[:NORMALS] @ n)))
        bones.append((start, len(verts) - start, 1, parent, oz))
    nv, nt = len(verts), len(tris)
    out = bytearray(blob[off:off + 0x1C])
    struct.pack_into("<HHHHHH", out, 4, nt, nv, 0, nt, 0, 0)
    for first, cnt, geo, parent, oz in bones:
        b5, b7 = 0, 0
        out += struct.pack("<HHBBBBi", first, cnt, geo, b5, parent if parent >= 0 else 255, b7, oz)
    # keep Aya's two pad bytes per bone record (bytes 5 and 7) as they were
    for i in range(nb):
        rec = off + 0x1C + 12 * i
        out[0x1C + 12 * i + 5] = blob[rec + 5]
        out[0x1C + 12 * i + 7] = blob[rec + 7]
    for v, n in zip(verts, vnrm):
        out += struct.pack("<hhhh", int(v[0]), int(v[1]), int(v[2]), n)
    out += bytes([128, 128, 128, 0]) * nv
    uvs = []
    for ids, uv, key in tris:
        a, b_, c = ids                                                 # glTF CCW (a, b, c) -> PSX order (a, c, b)
        out += bytes([128, 128, 128, 15]) + struct.pack("<HHH", a, c, b_) + b"\0\0"
        (t0, t1, t2), clut = atlas.uv(key, [uv[0], uv[2], uv[1]])
        uvs.append(struct.pack("<BBHBBHBBH", t0[0], t0[1], clut, t1[0], t1[1], TPAGE, t2[0], t2[1], 0))
    # 0x10 bytes + per-bone bounding data + 8 bytes + traversal (Aya's, unchanged: same bones)
    p_old = off + 0x1C + 12 * nb + 12 * m.nverts + 12 * len(m.prims)
    tail = blob[p_old:p_old + 0x10 + 16 * nb + 8 + ((m.trav_len + 3) & ~3)]
    out += tail
    out += b"".join(uvs)
    size = len(out)
    rep = {"verts": nv, "triangles": nt, "bytes": size, "budget_bytes": e["size"], "budget_verts": m.nverts,
           "packet_bytes": nt * 0x50, "budget_packet": m.counts[0] * 0x68 + m.counts[1] * 0x50 + m.counts[2] * 0x48 + m.counts[3] * 0x38}
    return bytes(out), rep


def fits(rep: dict) -> bool:
    return rep["bytes"] <= rep["budget_bytes"] and rep["verts"] <= rep["budget_verts"] and rep["packet_bytes"] <= rep["budget_packet"]


# ---------------------------------------------------------------- one outfit / whole build

def build_outfit(pe: P.PEData, outfit: int, model_path: Path, roles: dict, work: Path, name: str,
                 blender: str | None, progress=lambda p, m: None, scale=None, props=()) -> dict:
    from .sm64_swap import load_rig, read_rigged, retarget, write_rigged
    from .re4gc_enemies import decimate
    tgt = aya_target(pe, outfit)
    rig = load_rig(Path(model_path), roles, props)
    prims, rep = retarget(rig, tgt, scale, jmap=tgt["jmap"])
    # the retargeter fits the head joint to Aya's neck: a big-headed character (Mario) then towers over her. Keep the
    # whole figure within ~1.15 x Aya's height by shrinking the head about its base.
    head_y = tgt["T"][tgt["jmap"]["head"]][1]
    top = max(float(p["pos"][:, 1].max()) for p in prims)
    want = tgt["ground"] + HEIGHT_MAX * tgt["height"]
    if top > want and top > head_y:
        k = max(0.25, (want - head_y) / (top - head_y))
        scale = dict(scale or {}) | {"head": float((scale or {}).get("head", 1.0)) * k}
        prims, rep = retarget(rig, tgt, scale, jmap=tgt["jmap"])
        rep["head_fit_to_height"] = round(k, 3)
    work.mkdir(parents=True, exist_ok=True)
    rigged = write_rigged(prims, tgt, work / f"pe_aya{outfit}.gltf", name)
    normals = pe.normals(NORMALS)
    src_tris = sum(len(p["tris"]) for p in prims)
    target = src_tris
    last = None
    for attempt in range(8):
        src = rigged
        if target < src_tris:
            if not blender:
                raise ValueError(f"{name} needs decimating to fit Aya's model ({last}) and there's no Blender on this node")
            progress(None, f"outfit {outfit}: decimating {src_tris} -> {target} triangles")
            src = decimate(rigged, work / f"pe_aya{outfit}_d{target}.glb", float(target), blender)
        rp = read_rigged(src)
        atlas = Atlas()
        for p in rp:
            key = (id(p["tex"]) if p["tex"] is not None else None, tuple(p["color"][:3]))
            if key not in atlas.mat:
                atlas.add(key, p["tex"], p["color"])
        mb, mrep = build_model(tgt, rp, atlas, normals)
        last = mrep
        if fits(mrep):
            break
        k = min(mrep["budget_bytes"] / mrep["bytes"], mrep["budget_verts"] / mrep["verts"],
                mrep["budget_packet"] / mrep["packet_bytes"])
        target = int(min(target, mrep["triangles"]) * min(k, 1.0) * 0.96)
    else:
        raise ValueError(f"{name} doesn't fit Aya's outfit-{outfit} model budget: {last}")
    newblob = bytearray(tgt["blob"])
    e = tgt["entry"]
    newblob[e["offset"]:e["offset"] + e["size"]] = mb + bytes(e["size"] - len(mb))
    vram = P.VRAM()
    told = pe.common_blob(P.AYA_TEX_BLOB + outfit)
    vram.load_section(told)
    atlas.vram_into(vram)
    tb = tex_blob(told, vram)
    # self-check: the new blob parses and re-poses with Aya's first animation
    m2, an2, _e2 = P.load_model_blob(bytes(newblob))
    assert m2.nverts == mrep["verts"] and len(m2.prims) == mrep["triangles"] and m2.trav == tgt["model"].trav
    return {"outfit": outfit, "model_blob": bytes(newblob), "tex_blob": tb, "report": rep | mrep | {"source_triangles": src_tris},
            "rigged": rigged, "atlas_cluts": len(atlas.cluts)}


def build(disc: Path, model_path: Path, roles: dict, work: Path, name: str, out_bin: Path, base_bin: Path | None = None,
          outfits=range(P.AYA_OUTFITS), blender: str | None = None, progress=lambda p, m: None, scale=None, props=()) -> dict:
    """Disc image (CHD, or a raw .bin) -> modded raw .bin/.cue at out_bin with every chosen outfit replaced."""
    from . import psxdisc
    work = Path(work)
    pe = P.PEData(disc)
    res = []
    for k, o in enumerate(outfits):
        progress(10 + 60 * k / len(outfits), f"Fitting {name} onto Aya ({P.AYA_OUTFITS_NAMES[o].replace('_', ' ')})")
        res.append(build_outfit(pe, o, model_path, roles, work, name, blender,
                                lambda p, m: progress(10 + 60 * k / len(outfits), m), scale, props))
    progress(75, "Copying the disc image")
    out_bin = Path(out_bin)
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    if base_bin is None:
        base_bin = work / "base.bin"
        if not base_bin.exists():
            psxdisc.chd_to_bin(disc, base_bin)
    shutil.copyfile(base_bin, out_bin)
    rb = psxdisc.RawBin(out_bin)
    img_lba = rb.files["PE.IMG"][0]
    written = 0
    for r in res:
        o = r["outfit"]
        for blob_i, data in ((P.AYA_MODEL_BLOB + o, r["model_blob"]), (P.AYA_TEX_BLOB + o, r["tex_blob"])):
            a, b = pe.common[blob_i], pe.common[blob_i + 1]
            assert len(data) == (b - a) * 2048
            written += rb.write_data(img_lba + a, data)
    rb.close()
    out_bin.with_suffix(".cue").write_text(f'FILE "{out_bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    return {"bin": str(out_bin), "cue": str(out_bin.with_suffix(".cue")), "sectors_written": written,
            "outfits": {P.AYA_OUTFITS_NAMES[r["outfit"]]: r["report"] for r in res}, "rigged": [r["rigged"] for r in res]}


# ---------------------------------------------------------------- characters op=use

def image_name(meta: dict, gid: str) -> str:
    import re
    disc = "2" if gid == "2ad5e8b6a18702cb" else "1"
    return "Parasite Eve - " + re.sub(r"[^\w .()'-]+", "", meta["name"]).strip() + f" (USA) (Disc {disc}).bin"


def base_bin(cfg, game: dict, progress=lambda p, m: None) -> Path:
    """One vanilla raw image per game on this node (cache/modbase/<game_id>/<rom stem>.bin)."""
    from . import filemods, psxdisc
    from .models import CatalogEntry
    from .tools import rom_path
    rom = rom_path(CatalogEntry.model_validate(game), cfg)
    out = filemods.base_dir(cfg, game["game_id"]) / (rom.stem + ".bin")
    if not out.exists():
        progress(5, f"Unpacking {rom.name} to a raw image (once per game)")
        tmp = out.with_name(out.stem + ".part.bin")
        psxdisc.chd_to_bin(rom, tmp) if rom.suffix.lower() == ".chd" else shutil.copyfile(rom, tmp)
        tmp.replace(out)
        tmp.with_suffix(".cue").unlink(missing_ok=True)
    return out


def build_mod(cfg, meta: dict, game: dict, progress=lambda p, m: None, root: Path | None = None) -> dict:
    from . import characters as Cm, filemods
    root = root or Cm.library_root(cfg)
    gid, name = game["game_id"], f"pe_{meta['slug']}"
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json): can't map it onto Aya's bones")
    base = base_bin(cfg, game, progress)
    work = Path(cfg.cache) / "characters_build" / meta["slug"] / "pe"
    shutil.rmtree(work, ignore_errors=True)
    d = filemods.mod_dir(cfg, gid, name)
    if d.exists():
        shutil.rmtree(d)
    img = image_name(meta, gid)
    b = build(base, root / meta["slug"] / meta["model"], roles, work, meta["name"], d / img, base,
              blender=Cm._blender(cfg), progress=progress, scale=(meta.get("rig") or {}).get("scale"),
              props=[p["node"] for p in meta.get("props") or []])
    progress(88, "Rendering a preview of the model on Aya's skeleton")
    tdir = root / meta["slug"] / "targets"
    tdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(b["rigged"][min(2, len(b["rigged"]) - 1)], tdir / "pe_aya.gltf")
    prev = Cm.render_preview(tdir / "pe_aya.gltf", tdir / "pe_preview.png")
    cue = Path(b["cue"]).name
    mj = {"name": name, "game_id": gid, "image": cue, "files": ["PE.IMG: Aya model + texture blobs 13..22 (gbox.pe_swap)"],
          "built": time.time(), "character": meta["slug"], "source": meta["model"], "outfits": b["outfits"]}
    (d / ".gbox-mod.json").write_text(json.dumps(mj, default=str))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": cue, "preview": str(prev), "report": b["outfits"]}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Parasite Eve: build pe_<slug> (control plane) if missing, record it, launch it."""
    from . import characters as Cm
    from .sm64_swap import _have_mod, _wait
    gid, name = game["game_id"], f"pe_{meta['slug']}"
    if meta.get("source", {}).get("game_id") in GAME_IDS and not meta.get("variant_of"):
        return {"status": "native", "message": f"{meta['name']} is Parasite Eve's own player: launch the game without a mod."}
    sess = Cm._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else Cm.HOST_OS
    built = None
    if inp.rebuild or not _have_mod(ctx, gid, name):
        if Cm.library_root(ctx.config).is_dir():
            built = build_mod(ctx.config, meta, game, ctx.progress)
            tris = {k: v["triangles"] for k, v in built["report"].items()}
            Cm._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                    json={"game_id": gid, "slot": "player", "mod": name, "nodes": [Cm.HOST_OS],
                          "notes": f"replaces Aya (all 5 outfits, field + battle; her animations); triangles {tris}; "
                                   "preview targets/pe_preview.png"})
        else:
            cp = next((w["id"] for w in Cm._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
            ctx.progress(10, "Building the Parasite Eve mod on the control-plane node (the collection lives there)")
            j = Cm._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid, "rebuild": inp.rebuild,
                                            "launch": False}, cp, 3600)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
                return {"status": "failed", "mod": name, "error": r.get("error") or j.get("error") or r}
            built = r.get("build")
    res = {"mod": name, "build": built, "replaces": "Aya Brea (every outfit; her skeleton and animations stay)"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(90, f"Launching Parasite Eve with {meta['name']} (mod {name})")
    lj = _wait(ctx, Cm._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name,
                                                                                          "node": node}}), 600)
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = (f"Parasite Eve is running with {meta['name']} in Aya's place (mod {name}, session {launch['session_id']}). "
           "Aya's FMV/CG scenes are pre-rendered video and stay as they are; the real-time model (field + battle) is replaced."
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
    b.add_argument("--outfits", default="0,1,2,3,4")
    b.add_argument("--base-bin", default=None)
    a = ap.parse_args()
    cdir = Path(a.character)
    meta = json.loads((cdir / "meta.json").read_text())
    od = Path(a.out)
    from .sm64_swap import _blender
    res = build(Path(a.disc), cdir / meta["model"], meta["rig"]["roles"], od / "work", meta["name"],
                od / f"pe_{meta['slug']}.bin", Path(a.base_bin) if a.base_bin else None,
                [int(x) for x in a.outfits.split(",")], _blender(), lambda p, m: print(f"{p if p is not None else '':>5} {m}"))
    from .characters import render_preview
    for r in res["rigged"]:
        render_preview(Path(r), Path(r).with_suffix(".png"))
    print(json.dumps({k: v for k, v in res.items() if k != "rigged"}, indent=1, default=str))
