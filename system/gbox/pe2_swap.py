"""Parasite Eve II (PS1, USA): any character from gBox's collection in Aya Brea's place (#559; reverse of pe2_models).

`characters op=use` routes PE2 here. Pipeline (the operator's own disc + collection, nothing downloaded):
  1. Target = Aya's body model of an outfit file (gbox.pe2_models): 19 bones at rest (identity rotations), body roles
     from the hierarchy, PSX axes turned to the retargeter's frame (left +X, up +Y, front +Z).
  2. gbox.sm64_swap.load_rig + retarget (the generic rigid retarget, as gbox.pe_swap does for PE1). Aya's bones, their
     offsets and the hand/prop sub-models' headers never move, so her animations keep playing.
  3. Model tables in pe2_models' layout: a triangle whose corners share a bone is a lit textured triangle (0x38) on that
     bone; one spanning bones becomes a seam triangle (0x39) with a 0xC8 entry per corner, exactly like Aya's own
     joints. Budget = Aya's: table bytes <= the space between her bone table and her header (the EXE points at the
     header, 0x8011C210 for file 10200, so it can't move), vertices <= hers, GPU packet bytes (GT3 0x28 / GT4 0x34) and
     seam packet bytes <= hers. Over budget -> Blender decimate (re4gc_enemies.decimate), then fewer triangles.
  4. Texture: one 256x256 8-bit page (tpage 0xB6 = VRAM 384,256: both of her columns) with one 256-colour CLUT (row 245);
     the face-animation frames after her header (eye / mouth rectangles the game re-uploads) are refilled from the new
     page, and the four hand sub-models are collapsed to a point (the character's own hands ride bones 8 / 12).
  5. The outfit file is rebuilt in place: CLUT, image (two columns x eight LZ strips) and model chunks re-encoded with
     pe2_inventory.lz_encode, chained in the file's own sectors (the HED does not change), written into a raw copy of the
     disc (gbox.psxdisc.RawBin: EDC/ECC recomputed) -> file mod cache/mods/<game_id>/pe2_<slug>.

  python -m gbox.pe2_swap build <disc.chd | .bin> <character dir (meta.json)> <out dir> [--outfits 1,2,3,4,5]
"""
from __future__ import annotations

import json
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from . import pe2_inventory as I
from . import pe2_models as M

GAME_IDS = dict(I.GAME_IDS)
TPAGE, CLUT = 0xB6, 0x3D40                      # 8-bit page at VRAM (384, 256); CLUT row 245
FIT_HEIGHT = 0.9
HEIGHT_MAX = 1.1
MAX_VERTS = 1024        # seam corners index the draw call's per-vertex screen table: 4 KB on the stack (0x800418C0)
GRIDS = (4, 8, 12, 16, 20, 24, 32, 40, 48, 64)     # vertex-clustering cells (mm) when there's no Blender
C = M.C


# ---------------------------------------------------------------- target

def aya_target(disc: I.PE2Disc, fid: int) -> dict:
    m, vram, info = M.load_file_model(disc, fid)
    roles = M.infer_roles(m)
    Wp = m.world()
    Tg = Wp @ C.T
    pv = m.rest_vertices() @ C.T
    head = roles["head"]
    front = pv[m.vbone == head].mean(0) - Tg[head]
    front[1] = 0
    k = int(np.argmax(np.abs(front)))
    front = np.eye(3)[k] * np.sign(front[k])
    up = np.array([0, 1.0, 0])
    B = np.stack([np.cross(up, front), up, front])
    T = Tg @ B.T
    pc = pv @ B.T
    jmap = {r: roles[r] for r in ("hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                                  "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot")}
    hv = pc[m.vbone == head]
    return {"model": m, "vram": vram, "info": info, "file": fid, "B": B, "T": T, "W": Wp,
            "parent": [max(p, -1) for p in m.parent], "joints": m.nbones, "ground": float(pc[:, 1].min()),
            "head_h": float(np.ptp(hv[:, 1])) if len(hv) else 200.0, "jmap": jmap, "roles": roles,
            "height": float(np.ptp(pc[:, 1])), "fit_height": FIT_HEIGHT * float(np.ptp(pc[:, 1]))}


# ---------------------------------------------------------------- texture page

def _c15(rgb) -> int:
    r, g, b = (int(x) >> 3 for x in rgb[:3])
    return (r | (g << 5) | (b << 10)) or 0x8000          # 0x0000 is see-through: opaque black instead


class Atlas8:
    """Materials -> one 256x256 RGB page (textures up to 64 px with a 1-texel border, flat colours as 4x4 cells),
    quantized at the end to 256 colours (one CLUT)."""

    def __init__(self):
        self.rgb = np.zeros((256, 256, 3), np.uint8)
        self.x = self.y = self.row_h = 0
        self.mat: dict = {}
        self.limit = 64

    def _place(self, w, h):
        if self.x + w > 256:
            self.x, self.y, self.row_h = 0, self.y + self.row_h, 0
        if self.y + h > 256:
            raise ValueError("the character's textures don't fit Aya's 256x256 page")
        x, y = self.x, self.y
        self.x += w
        self.row_h = max(self.row_h, h)
        return x, y

    def add(self, key, tex, color):
        from .sm64_swap import _fill_alpha
        col = np.array(color[:3], float) / 255
        if tex is None:
            x, y = self._place(4, 4)
            self.rgb[y:y + 4, x:x + 4] = np.clip(col * 255, 0, 255).astype(np.uint8)
            self.mat[key] = ("flat", x + 1.5, y + 1.5)
            return
        img = _fill_alpha(np.asarray(tex, np.uint8))
        if (col < 0.999).any():
            img = img.copy()
            img[..., :3] = (img[..., :3] * col).astype(np.uint8)
        while img.shape[0] > self.limit or img.shape[1] > self.limit:
            img = img[::2, ::2]
        h, w = img.shape[:2]
        x, y = self._place(w + 2, h + 2)
        self.rgb[y:y + h + 2, x:x + w + 2] = np.pad(img[..., :3], ((1, 1), (1, 1), (0, 0)), mode="edge")
        self.mat[key] = ("tex", x + 1, y + 1, w, h)

    def uv(self, key, uv):
        m = self.mat[key]
        if m[0] == "flat":
            return [(int(m[1]), int(m[2]))] * len(uv)
        _k, x, y, w, h = m
        return [(int(round(x + min(max(float(u), 0), 1) * (w - 1))), int(round(y + min(max(float(v), 0), 1) * (h - 1))))
                for u, v in uv]

    def indexed(self, colors: int = 256) -> tuple[np.ndarray, list[int]]:
        from PIL import Image
        q = Image.fromarray(self.rgb, "RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette()[:3 * colors]
        cl = [_c15(pal[3 * i:3 * i + 3]) for i in range(len(pal) // 3)]
        return np.asarray(q, np.uint8), cl + [0x8000] * (256 - len(cl))


def face_rects(blob: bytes, m: M.Model, page_idx: np.ndarray) -> list[dict]:
    """Face-animation frames after the header: descriptors {u16 0 x4, u16 w (VRAM halfwords), u16 h, u32 frame*} ->
    where each frame sits in Aya's page (best match of its texels), so the writer can refill it from the new page."""
    out = []
    o = 0
    while o + 16 <= len(blob):
        w, h, p = struct.unpack_from("<HHI", blob, o + 8)
        fo = p - m.base
        if blob[o:o + 8] == bytes(8) and 4 <= w <= 64 and 4 <= h <= 64 and 0 <= fo and fo + 2 * w * h <= len(blob) \
                and not m.layout["bones"] <= fo < m.layout["header"]:
            fr = np.frombuffer(blob[fo:fo + 2 * w * h], np.uint8).reshape(h, 2 * w)
            best = None
            for y in range(256 - h + 1):
                for x in range(0, 256 - 2 * w + 1, 2):
                    s = int((page_idx[y:y + h, x:x + 2 * w] != fr).sum())
                    if best is None or s < best[0]:
                        best = (s, x, y)
                        if s == 0:
                            break
                if best and best[0] == 0:
                    break
            out.append({"desc": o, "frame": fo, "w": 2 * w, "h": h, "x": best[1], "y": best[2], "mismatch": best[0]})
            o += 16
        else:
            o += 4
    return out


# ---------------------------------------------------------------- model

def build_model(tgt: dict, prims: list[dict], atlas: Atlas8, grid: int = 1) -> tuple[M.Model, dict]:
    """retargeted prims (canonical positions, jid = Aya bone per vertex) -> a pe2_models.Model on Aya's bones."""
    m = tgt["model"]
    nb, W, B = m.nbones, tgt["W"], tgt["B"]
    per_bone_v: dict[int, dict] = {b: {} for b in range(nb)}
    vlist: dict[int, list] = {b: [] for b in range(nb)}
    nrm_acc: dict[tuple, np.ndarray] = {}
    tris = []
    for p in prims:
        key = (id(p["tex"]) if p["tex"] is not None else None, tuple(p["color"][:3]))
        psx = (p["pos"] @ B) @ C.T                         # canonical -> glTF -> PSX (C is its own inverse)
        nps = (p["nrm"] @ B) @ C.T
        for t in p["tris"]:
            corners = []
            for i in t:
                b = int(p["jid"][i])
                lp = tuple(np.clip(np.round((psx[i] - W[b]) / grid) * grid, -32768, 32767).astype(int))
                if lp not in per_bone_v[b]:
                    per_bone_v[b][lp] = len(vlist[b])
                    vlist[b].append(lp)
                    nrm_acc[(b, lp)] = np.zeros(3)
                nrm_acc[(b, lp)] += nps[i] / (np.linalg.norm(nps[i]) or 1)
                corners.append((b, lp))
            if len(set(corners)) == 3:
                tris.append((corners, atlas.uv(key, [p["uv"][i] for i in t])))
    # global vertex numbering, contiguous per bone
    base, counts, verts, vbone = {}, [], [], []
    for b in range(nb):
        base[b] = len(verts)
        counts.append(len(vlist[b]))
        verts += vlist[b]
        vbone += [b] * len(vlist[b])
    gid = lambda c: base[c[0]] + per_bone_v[c[0]][c[1]]  # noqa: E731
    # normals: quantized directions, shared
    ntab, nidx = [], {}
    vnorm = []
    for b in range(nb):
        for lp in vlist[b]:
            n = nrm_acc[(b, lp)]
            n = n / (np.linalg.norm(n) or 1)
            q = tuple(np.round(n * 8).astype(int))
            if q not in nidx:
                nidx[q] = len(ntab)
                v = np.array(q, float)
                ntab.append(v / (np.linalg.norm(v) or 1))
            vnorm.append(nidx[q])
    out_prims = []
    for corners, uv in tris:
        ids = [gid(c) for c in corners]
        bones = {c[0] for c in corners}
        a, b_, c = ids                                     # glTF CCW -> PSX clockwise: (a, c, b)
        uvs = [uv[0], uv[2], uv[1]]
        if len(bones) == 1:
            out_prims.append(M.Prim([a, c, b_], uvs, CLUT, TPAGE, corners[0][0], normals=[vnorm[a], vnorm[c], vnorm[b_]]))
        else:
            out_prims.append(M.Prim([a, c, b_], uvs, CLUT, TPAGE, nb, seam=True, normals=[vnorm[a], vnorm[c], vnorm[b_]],
                                    code=0x39))
    out_prims = pair_quads(out_prims)
    out_prims.sort(key=lambda q: q.seam)
    new = M.Model(m.base, m.header, nb, m.rot.copy(), m.trans.copy(), list(m.parent), counts,
                  np.array(verts, float).reshape(-1, 3), np.array(vbone, int), np.array(ntab, float).reshape(-1, 3),
                  out_prims, [], dict(m.layout), {})
    L = m.layout
    tab, ptr = M.serialize_tables(new, m.base + L["bones"])
    old_hdr = struct.unpack_from("<9I", tgt["info"]["blob"], m.header)
    rep = {"verts": len(verts), "triangles": sum(len(q.verts) - 2 for q in out_prims),
           "quads": sum(len(q.verts) == 4 for q in out_prims), "seam_triangles": sum(q.seam for q in out_prims),
           "normals": len(ntab), "bytes": len(tab), "budget_bytes": L["header"] - L["bones"],
           "budget_verts": MAX_VERTS, "packet_bytes": ptr["pk_all"], "budget_packet": old_hdr[1],
           "seam_packet_bytes": ptr["pk_seam"], "budget_seam_packet": old_hdr[2]}
    rep["fits"] = fits(rep)
    return new, rep | {"_tables": tab, "_ptr": ptr}


def pair_quads(prims: list[M.Prim]) -> list[M.Prim]:
    """Two triangles of one bone sharing an edge with the same UVs on it -> one GT4 (0x78): the GPU splits a GT4 into
    (0,1,2) + (1,3,2), so tris (a,b,c) + (c,b,d) draw exactly as before for 0x34 packet bytes instead of 2 x 0x28."""
    tri = [p for p in prims if len(p.verts) == 3 and not p.seam]
    rest = [p for p in prims if p not in tri]
    edges: dict = {}
    for i, p in enumerate(tri):
        for k in range(3):
            a, b = p.verts[k], p.verts[(k + 1) % 3]
            edges.setdefault((p.bone, a, b), []).append((i, k))
    used, out = set(), []
    for i, p in enumerate(tri):
        if i in used:
            continue
        hit = None
        for k in range(3):
            a, b = p.verts[k], p.verts[(k + 1) % 3]
            for j, kk in edges.get((p.bone, b, a), []):             # the neighbour runs the shared edge backwards
                q = tri[j]
                if j == i or j in used or q.uvs[kk] != p.uvs[(k + 1) % 3] or q.uvs[(kk + 1) % 3] != p.uvs[k]:
                    continue
                hit = (k, j, kk)
                break
            if hit:
                break
        if not hit:
            out.append(p)
            continue
        k, j, kk = hit
        q = tri[j]
        used |= {i, j}
        # p = (x, a, b) rotated so the shared edge a->b is last: x = opposite corner
        x = (k + 2) % 3
        d = (kk + 2) % 3
        # PSX clockwise tri (x, a, b) + (b, a, d): quad v0 = x, v1 = a, v2 = b, v3 = d -> (0,1,2) + (1,3,2)
        ia, ib = k, (k + 1) % 3
        out.append(M.Prim([p.verts[x], p.verts[ia], p.verts[ib], q.verts[d]],
                          [p.uvs[x], p.uvs[ia], p.uvs[ib], q.uvs[d]], p.clut, p.tpage, p.bone,
                          normals=[p.normals[x], p.normals[ia], p.normals[ib], q.normals[d]], code=0x78))
    return out + rest


def fits(rep: dict) -> bool:
    return (rep["bytes"] <= rep["budget_bytes"] and rep["verts"] <= rep["budget_verts"]
            and rep["packet_bytes"] <= rep["budget_packet"] and rep["seam_packet_bytes"] <= rep["budget_seam_packet"])


def new_blob(tgt: dict, rep: dict, page_idx: np.ndarray) -> bytes:
    m, blob = tgt["model"], bytearray(tgt["info"]["blob"])
    L = m.layout
    tab = rep["_tables"]
    blob[L["bones"]:L["header"]] = tab + bytes(L["header"] - L["bones"] - len(tab))
    blob[L["header"]:L["header"] + 36] = M.header_bytes(rep["_ptr"], m.nbones)
    for h in M.find_headers(bytes(blob), m.base):                 # hand / prop sub-models: collapse to a point
        if h == L["header"]:
            continue
        sub = M.parse_model(bytes(blob), m.base, h)
        o = sub.layout["verts"]
        blob[o:o + 8 * len(sub.verts)] = bytes(8 * len(sub.verts))
    old_page = tgt["page_idx"]
    for f in face_rects(bytes(tgt["info"]["blob"]), m, old_page):
        x, y, w, h = f["x"], f["y"], f["w"], f["h"]
        blob[f["frame"]:f["frame"] + w * h] = page_idx[y:y + h, x:x + w].tobytes()
    return bytes(blob)


def _chunk(t: int, flag: int, data: bytes, addr: int = 0) -> bytes:
    n = max(1, (16 + len(data) + 2047) // 2048)
    used = 16 + len(data) - (n - 1) * 2048
    return (struct.pack("<BBHIII", t, flag, used, n, addr, 0) + data).ljust(n * 2048, b"\0")


def rebuild_file(disc: I.PE2Disc, fid: int, blob: bytes, page_idx: np.ndarray, clut: list[int]) -> bytes:
    """The outfit file's chunk chain re-encoded with the new model / page / CLUT, in the original chunk order, padded to
    the file's sectors. Raises when it doesn't fit."""
    cdf = disc.cdf
    sec, nsec = disc.spans()[fid]
    chain = I.walk_file(cdf, sec, nsec)
    words = page_idx.reshape(256, 128, 2).astype(np.uint16)
    vram16 = (words[..., 0] | (words[..., 1] << 8)).astype("<u2")       # 256 rows x 128 VRAM halfwords
    out = bytearray()
    for k, c in enumerate(chain):
        flag = 0xFF if k == len(chain) - 1 else 1
        p = I.payload(cdf, c)
        if c.type == 0:
            data = I.lz_encode(blob)
        elif c.type == 1:
            ents = I.decode_image(p)
            head = bytearray(p[:ents[0]["offset"]])
            body = bytearray()
            for e in ents:
                col = (e["x"] - 384) // 64
                if not 0 <= col < 2 or (e["y"] & 0x1FF) != 256:
                    raise ValueError(f"file {fid}: image column at {e['x']},{e['y']} isn't on Aya's page")
                struct.pack_into("<I", head, 8 * ents.index(e) + 4, len(head) + len(body))
                cols = vram16[:, 64 * col:64 * col + 64]
                for s in range(8):
                    body += I.lz_encode(cols[32 * s:32 * s + 32].tobytes())
            data = bytes(head + body)
        elif c.type == 2:
            x, y, h, w = struct.unpack_from("<4H", p, 0)
            rows = b"".join(struct.pack("<256H", *clut) for _ in range(h)) if w == 256 else None
            if rows is None:
                raise ValueError(f"file {fid}: CLUT chunk {w}x{h} isn't Aya's 256-colour rows")
            data = p[:16] + I.lz_encode(rows)
        else:
            data = p
        out += _chunk(c.type, flag, data, c.addr)
    if len(out) > nsec * 2048:
        raise ValueError(f"file {fid}: rebuilt chunks need {len(out) // 2048} sectors, the file has {nsec}")
    return bytes(out.ljust(nsec * 2048, b"\0"))


# ---------------------------------------------------------------- one outfit / build

def build_outfit(disc: I.PE2Disc, outfit: int, model_path: Path, roles: dict, work: Path, name: str,
                 blender: str | None, progress=lambda p, m: None, scale=None, props=()) -> dict:
    from .sm64_swap import load_rig, read_rigged, retarget, write_rigged
    from .re4gc_enemies import decimate
    fid = disc.outfit_files()[outfit]
    tgt = aya_target(disc, fid)
    orig_page = tgt["vram"].mem[256:512, 384:512].copy().view(np.uint8).reshape(256, 256)
    tgt["page_idx"] = orig_page
    rig = load_rig(Path(model_path), roles, props)
    prims, rep = retarget(rig, tgt, scale, jmap=tgt["jmap"])
    head_y = tgt["T"][tgt["jmap"]["head"]][1]
    top = max(float(p["pos"][:, 1].max()) for p in prims)
    want = tgt["ground"] + HEIGHT_MAX * tgt["height"]
    if top > want and top > head_y:
        k = max(0.25, (want - head_y) / (top - head_y))
        scale = dict(scale or {}) | {"head": float((scale or {}).get("head", 1.0)) * k}
        prims, rep = retarget(rig, tgt, scale, jmap=tgt["jmap"])
        rep["head_fit_to_height"] = round(k, 3)
    work.mkdir(parents=True, exist_ok=True)
    rigged = write_rigged(prims, tgt, work / f"pe2_aya{outfit}.gltf", name)
    src_tris = sum(len(p["tris"]) for p in prims)

    def fit(rp, grid, limit):
        atlas = Atlas8()
        atlas.limit = limit
        for p in rp:
            key = (id(p["tex"]) if p["tex"] is not None else None, tuple(p["color"][:3]))
            if key not in atlas.mat:
                atlas.add(key, p["tex"], p["color"])
        model, mrep = build_model(tgt, rp, atlas, grid)
        return atlas, model, mrep
    rp = read_rigged(rigged)
    target, last, grid, ok = src_tris, None, 1, False
    for _attempt in range(6):                            # Blender decimation first, when this node has one
        atlas, model, mrep = fit(rp, grid, 64)
        last = {k: v for k, v in mrep.items() if not k.startswith("_")}
        if mrep["fits"] or not blender:
            ok = mrep["fits"]
            break
        k = min(mrep["budget_bytes"] / mrep["bytes"], mrep["budget_verts"] / max(1, mrep["verts"]),
                mrep["budget_packet"] / max(1, mrep["packet_bytes"]),
                mrep["budget_seam_packet"] / max(1, mrep["seam_packet_bytes"]))
        target = int(min(target, mrep["triangles"]) * min(k, 1.0) * 0.95)
        progress(None, f"outfit {outfit}: decimating {src_tris} -> {target} triangles")
        rp = read_rigged(decimate(rigged, work / f"pe2_aya{outfit}_d{target}.glb", float(target), blender))
    if not ok:                                           # then vertex clustering per bone (PSX units, mm)
        for grid in GRIDS:
            atlas, model, mrep = fit(rp, grid, 64)
            last = {k: v for k, v in mrep.items() if not k.startswith("_")}
            if mrep["fits"]:
                ok = True
                break
    if not ok:
        raise ValueError(f"{name} doesn't fit Aya's outfit-{outfit} model budget: {last}")
    data = None
    for limit in (64, 32, 16, 8):                        # smaller textures compress into the file's sectors
        if limit != 64:
            atlas, model, mrep = fit(rp, grid, limit)
            last = {k: v for k, v in mrep.items() if not k.startswith("_")}
        page_idx, clut = atlas.indexed()
        blob = new_blob(tgt, mrep, page_idx)
        chk = M.parse_model(blob, tgt["model"].base, tgt["model"].header)    # self-check: parses back, same bones
        assert len(chk.verts) == last["verts"] and chk.parent == tgt["model"].parent
        assert sum(len(q.verts) - 2 for q in chk.prims) == last["triangles"]
        if len(blob) != len(tgt["info"]["blob"]):
            raise AssertionError("model blob changed size")
        try:
            data = rebuild_file(disc, fid, blob, page_idx, clut)
            last["texture_limit_px"] = limit
            break
        except ValueError as e:
            if "sectors" not in str(e) or limit == 8:
                raise
    last["cluster_grid"] = grid
    return {"outfit": outfit, "file": fid, "data": data, "report": rep | last | {"source_triangles": src_tris},
            "rigged": rigged}


def build(disc_path: Path, model_path: Path, roles: dict, work: Path, name: str, out_bin: Path,
          base_bin: Path | None = None, outfits=None, blender: str | None = None, progress=lambda p, m: None,
          scale=None, props=()) -> dict:
    """Disc image (CHD or raw .bin) -> modded raw .bin/.cue with every chosen outfit file rebuilt in STAGE0.CDF."""
    from . import psxdisc
    work = Path(work)
    disc = I.PE2Disc(disc_path) if Path(disc_path).suffix.lower() != ".bin" else _BinDisc(disc_path)
    outfits = list(outfits or sorted(I.AYA_OUTFIT_NAMES))
    res = []
    done_files: dict[int, dict] = {}
    for k, o in enumerate(outfits):
        fid = disc.outfit_files()[o]
        if fid in done_files:                              # outfits 4 and 5 can share a model file layout
            continue
        progress(10 + 60 * k / len(outfits), f"Fitting {name} onto Aya ({I.AYA_OUTFIT_NAMES[o].replace('_', ' ')})")
        r = build_outfit(disc, o, model_path, roles, work, name, blender,
                         lambda p, m: progress(10 + 60 * k / len(outfits), m), scale, props)
        done_files[fid] = r
        res.append(r)
    progress(75, "Copying the disc image")
    out_bin = Path(out_bin)
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    if base_bin is None:
        base_bin = work / "base.bin"
        if not base_bin.exists():
            psxdisc.chd_to_bin(disc_path, base_bin)
    shutil.copyfile(base_bin, out_bin)
    rb = psxdisc.RawBin(out_bin)
    spans = disc.spans()
    written = 0
    for r in res:
        sec, n = spans[r["file"]]
        assert len(r["data"]) == n * 2048
        written += rb.write_file("STAGE0.CDF", sec * 2048, r["data"])
    rb.close()
    out_bin.with_suffix(".cue").write_text(f'FILE "{out_bin.name}" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    return {"bin": str(out_bin), "cue": str(out_bin.with_suffix(".cue")), "sectors_written": written,
            "outfits": {I.AYA_OUTFIT_NAMES[r["outfit"]]: r["report"] for r in res}, "rigged": [r["rigged"] for r in res]}


class _BinDisc(I.PE2Disc):
    """PE2Disc over a raw MODE2/2352 .bin (the vanilla base image)."""

    def __init__(self, path):
        from .psxdisc import RawBin
        self._rb = RawBin(path, writable=False)
        self.files = {}
        self._get = self._rb.read
        self.names = sorted(self._rb.files)
        self.disc_no = next((v for k, v in I.BOOT_EXE.items() if k in self.names), None)
        if self.disc_no is None or "STAGE0.HED" not in self.names:
            raise ValueError(f"{path}: not a Parasite Eve II (USA) disc")
        self.hed_bytes = self.read("STAGE0.HED")
        self.records, self.pairs = I.parse_hed(self.hed_bytes)


# ---------------------------------------------------------------- characters op=use

def image_name(meta: dict, gid: str) -> str:
    import re
    disc = "2" if gid == "5318e0449fee32b2" else "1"
    return "Parasite Eve II - " + re.sub(r"[^\w .()'-]+", "", meta["name"]).strip() + f" (USA) (Disc {disc}).bin"


def build_mod(cfg, meta: dict, game: dict, progress=lambda p, m: None, root: Path | None = None) -> dict:
    from . import characters as Cm, filemods
    from .pe_swap import base_bin
    root = root or Cm.library_root(cfg)
    gid, name = game["game_id"], f"pe2_{meta['slug']}"
    roles = (meta.get("rig") or {}).get("roles") or {}
    if "hip" not in roles:
        raise ValueError(f"{meta['name']} has no body roles (rig.roles in meta.json): can't map it onto Aya's bones")
    base = base_bin(cfg, game, progress)
    work = Path(cfg.cache) / "characters_build" / meta["slug"] / "pe2"
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
    shutil.copy2(b["rigged"][0], tdir / "pe2_aya.gltf")
    prev = Cm.render_preview(tdir / "pe2_aya.gltf", tdir / "pe2_preview.png")
    cue = Path(b["cue"]).name
    mj = {"name": name, "game_id": gid, "image": cue, "built": time.time(), "character": meta["slug"],
          "files": ["STAGE0.CDF: Aya's outfit files 10200..10600 (model + page + CLUT chunks, gbox.pe2_swap)"],
          "source": meta["model"], "outfits": b["outfits"]}
    (d / ".gbox-mod.json").write_text(json.dumps(mj, default=str))
    shutil.rmtree(work, ignore_errors=True)
    return {"mod": name, "image": cue, "preview": str(prev), "report": b["outfits"]}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Parasite Eve II: build pe2_<slug> if missing, record it, launch it."""
    from . import characters as Cm
    from .sm64_swap import _have_mod, _wait
    gid, name = game["game_id"], f"pe2_{meta['slug']}"
    if meta.get("source", {}).get("game_id") in GAME_IDS and not meta.get("variant_of"):
        return {"status": "native", "message": f"{meta['name']} is Parasite Eve II's own player: launch without a mod."}
    sess = Cm._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else Cm.HOST_OS
    built = None
    if inp.rebuild or not _have_mod(ctx, gid, name):
        if Cm.library_root(ctx.config).is_dir():
            built = build_mod(ctx.config, meta, game, ctx.progress)
            tris = {k: v["triangles"] for k, v in built["report"].items()}
            Cm._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                    json={"game_id": gid, "slot": "player", "mod": name, "nodes": [Cm.HOST_OS],
                          "notes": f"replaces Aya (every outfit file, field model; her animations); triangles {tris}; "
                                   "unverified in game; preview targets/pe2_preview.png"})
        else:
            cp = next((w["id"] for w in Cm._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
            ctx.progress(10, "Building the Parasite Eve II mod on the control-plane node (the collection lives there)")
            j = Cm._job(ctx, "characters", {"op": "use", "character": meta["slug"], "game_id": gid, "rebuild": inp.rebuild,
                                            "launch": False}, cp, 3600)
            r = (j.get("output") or {}).get("result") or {}
            if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
                return {"status": "failed", "mod": name, "error": r.get("error") or j.get("error") or r}
            built = r.get("build")
    res = {"mod": name, "build": built, "replaces": "Aya Brea (every outfit's field model; her skeleton and animations stay)"}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(90, f"Launching Parasite Eve II with {meta['name']} (mod {name})")
    lj = _wait(ctx, Cm._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name,
                                                                                          "node": node}}), 600)
    ok = lj.get("state") == "succeeded"
    launch = {"job": lj.get("id"), "state": lj.get("state"), "node": node,
              "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")}
    msg = (f"Parasite Eve II is running with {meta['name']} in Aya's place (mod {name}, session {launch['session_id']}). "
           "FMV scenes are pre-rendered video and stay as they are." if ok else
           f"Mod {name} is {'built' if built else 'ready'} but the launch {lj.get('state')}: {lj.get('error')}")
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
    b.add_argument("--outfits", default="1,2,3,4,5")
    b.add_argument("--base-bin", default=None)
    a = ap.parse_args()
    cdir = Path(a.character)
    meta = json.loads((cdir / "meta.json").read_text())
    od = Path(a.out)
    from .sm64_swap import _blender
    res = build(Path(a.disc), cdir / meta["model"], meta["rig"]["roles"], od / "work", meta["name"],
                od / f"pe2_{meta['slug']}.bin", Path(a.base_bin) if a.base_bin else None,
                [int(x) for x in a.outfits.split(",")], _blender(), lambda p, m: print(f"{p if p is not None else '':>5} {m}"))
    from .characters import render_preview
    for r in res["rigged"]:
        render_preview(Path(r), Path(r).with_suffix(".png"))
    print(json.dumps({k: v for k, v in res.items() if k != "rigged"}, indent=1, default=str))
