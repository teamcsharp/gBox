"""Parasite Eve (PS1, USA, SLUS-00662) asset extractor: PE.IMG packages -> rigged glTF (mesh, skeleton, skin, texture
atlas, animations). Reverse-engineered with Ghidra from SLUS_006.62 (see KB "Parasite Eve" format notes); no
third-party tools. Works straight from the disc image (gbox.psxdisc reads the CHD) or from extracted PE.IMG + SLUS.

Layout (all little-endian; addresses are RAM, the EXE text is loaded at 0x80010000 = file offset 0x800):
  * Room package table @0x80093378 (438 x {u32 start sector in PE.IMG, u32 info}); info packs three section sizes in
    sectors: A = info & 0xFF (VRAM images), B = (info >> 8) & 0xFFF (background images), C = info >> 20 (scene data:
    enemy/NPC models, animations, scripts). Loader: FUN_8006b4f8.
  * Common blob table @0x800930d8 (u16 start sectors, blob i = [t[i], t[i+1])): Aya's VRAM textures = 13..17, Aya's
    model+animations = 18..22 (one pair per outfit, picked by DAT_800b0ce2 - 10; loader FUN_8006becc), Aya's weapon
    models 23..38.
  * Every section/blob: u32 size, u32 dir_off; at dir_off: u32 tag + 12 x u32 (count << 22 | offset) per asset type.
    Type 2 = models (12-byte entries: u32 size, u24 offset + u8 model id, u32 VRAM placement), type 3 = animations
    (12-byte entries: u32 size, u24 offset + u8 anim id, u32 model-id byte at +11), type 9 = VRAM uploads (20-byte
    entries, FUN_8006e1c0: u24 offset + u8 height(0=256), u32 rect (w = &0x3FF, x = >>10 & 0x7FF, y = >>21), optional
    second rect for the tail rows).
  * Model (FUN_8003d050): 0x1C header (u8 nbones @2, u16 nverts @6, u16 #GT4 @8, #GT3 @A, #G4 @C, #G3 @E,
    u16 traversal length @18), bones 12 bytes (u16 first vertex, u16 vertex count, u8 has-geometry, u8, u8 parent,
    u8, s32 offset along the parent's Z), vertices 8 bytes (s16 x,y,z, s16 normal index into the EXE's normal table
    @0x80091a58), vertex colours 4 bytes, primitives 12 bytes (rgb, code, u16 vertex indices), 0x10 + nbones*0x10 +
    8 bytes of attachment data, traversal bytes (bone index / 0xFF push / 0xFE pop; FUN_8003a088), then UVs:
    GT4 16 bytes (u0 v0 clut u1 v1 tpage u2 v2 - u3 v3 -), GT3 12 bytes.
  * Animation (FUN_80039d24 / FUN_80039ed4): header 12 bytes (u8 kind: &3 == 2 -> 16-bit angles else 8-bit << 4,
    u8 nbones-1, u8 nframes-1), then 3 root translation tracks (s16) and 3 rotation tracks per bone (X, Y, Z;
    RotMatrix FUN_80079754 = Ry * Rx * Rz, 4096 = 360 degrees). Track: flag 0 -> one value per frame, else a constant.
"""
from __future__ import annotations

import io
import json
import math
import struct
from pathlib import Path

import numpy as np

SECTOR = 2048
TEXT_BASE = 0x80010000
ROOM_TABLE = 0x80093378
COMMON_TABLE = 0x800930D8
COMMON_COUNT = 82
NORMAL_TABLE = 0x80091A58
IMG_SECTORS = 100690

AYA_OUTFITS = 5                      # blobs 13..17 = VRAM, 18..22 = model + animations
AYA_TEX_BLOB, AYA_MODEL_BLOB = 13, 18
WEAPON_BLOBS = range(23, 39)
AYA_OUTFITS_NAMES = ["evening_dress", "long_coat", "jacket_jeans", "tshirt_jeans", "liberated"]   # blobs 18..22
AYA_ANIM_NAMES: dict[int, str] = {}  # filled in as animations are identified
DISC1 = "collections/Sony Playstation/roms/Parasite Eve (USA) (Disc 1).chd"     # relative to the hyperspin library


# ------------------------------------------------------------------------------------------------ data access

class PEData:
    """PE.IMG + SLUS_006.62 from a CHD/BIN disc image (via gbox.psxdisc) or a directory with the extracted files."""

    def __init__(self, src: str | Path):
        src = Path(src)
        if src.is_dir():
            self._img = open(src / "PE.IMG", "rb")
            exe = (src / "SLUS_006.62").read_bytes()
            self._disc = None
        else:
            from .psxdisc import PSXDisc, RawBin
            self._disc = RawBin(src, writable=False) if src.suffix.lower() == ".bin" else PSXDisc(str(src))
            self._img_lba = self._disc.files["PE.IMG"][0]
            exe = self._disc.read(next(n for n in ("SLUS_006.62", "SLUS_006.68") if n in self._disc.files))
            # disc 2 (SLUS_006.68) carries a byte-identical EXE and PE.IMG
        assert exe[:8] == b"PS-X EXE", "not a PS-X EXE"
        t_addr = struct.unpack_from("<I", exe, 0x18)[0]
        assert t_addr == TEXT_BASE, hex(t_addr)
        self.text = exe[0x800:]
        self.rooms = self._room_table()
        self.common = list(struct.unpack_from(f"<{COMMON_COUNT}H", self.text, COMMON_TABLE - TEXT_BASE))

    def ram(self, addr: int, n: int) -> bytes:
        o = addr - TEXT_BASE
        return self.text[o:o + n]

    def read(self, sector: int, count: int) -> bytes:
        if self._disc is None:
            self._img.seek(sector * SECTOR)
            return self._img.read(count * SECTOR)
        return b"".join(self._disc.data(self._img_lba + sector + i) for i in range(count))

    def _room_table(self):
        out, o = [], ROOM_TABLE - TEXT_BASE
        while True:
            s, info = struct.unpack_from("<II", self.text, o + 8 * len(out))
            if s >= IMG_SECTORS:
                return out
            out.append((s, info))

    def room_sections(self, i: int) -> list[bytes]:
        s, info = self.rooms[i]
        a, b, c = info & 0xFF, (info >> 8) & 0xFFF, info >> 20
        return [self.read(s, a), self.read(s + a, b), self.read(s + a + b, c)]

    def common_blob(self, i: int) -> bytes:
        a, b = self.common[i], self.common[i + 1]
        return self.read(a, b - a) if b > a else b""

    def normals(self, n: int = 4096) -> np.ndarray:
        """Global vertex-normal table (s16 x, y, z, pad; 4096 = 1.0); a model vertex's 4th short indexes it."""
        raw = self.ram(NORMAL_TABLE, n * 8)
        return np.frombuffer(raw, "<i2").reshape(-1, 4)[:, :3].astype(np.float64) / 4096.0


def section_dir(sec: bytes) -> dict[int, tuple[int, int]] | None:
    """{asset type: (count, offset)} of a section/blob, or None if it has no directory."""
    if len(sec) < 8:
        return None
    size, d = struct.unpack_from("<II", sec, 0)
    if size > len(sec) or d + 0x34 > len(sec) or d < 8:
        return None
    out = {}
    for t in range(12):
        e = struct.unpack_from("<I", sec, d + 4 + 4 * t)[0]
        out[t] = (e >> 22, e & 0x3FFFFF)
    return out


def assets(sec: bytes, t: int, esize: int = 12) -> list[dict]:
    """Type-2/3 entries: {'id', 'offset', 'size', 'raw'}; offsets are relative to the section start."""
    d = section_dir(sec)
    if not d:
        return []
    c, o = d[t]
    out = []
    for k in range(c):
        e = sec[o + esize * k:o + esize * (k + 1)]
        size, off = struct.unpack_from("<II", e, 0)
        out.append({"id": off >> 24, "offset": off & 0xFFFFFF, "size": size, "raw": e})
    return out


# ------------------------------------------------------------------------------------------------ VRAM / textures

class VRAM:
    W, H = 1024, 512

    def __init__(self):
        self.m = np.zeros((self.H, self.W), np.uint16)

    def upload(self, x, y, w, h, data: bytes):
        a = np.frombuffer(data[:w * h * 2], "<u2")
        h = min(h, len(a) // w)
        self.m[y:y + h, x:x + w] = a[:w * h].reshape(h, w)

    def load_section(self, sec: bytes):
        """Apply a section's type-9 VRAM uploads (FUN_8006e1c0)."""
        d = section_dir(sec)
        if not d:
            return 0
        c, o = d[9]
        for k in range(c):
            e = sec[o + 20 * k:o + 20 * k + 20]
            off = struct.unpack_from("<I", e, 4)[0]
            h = (off >> 24) or 256
            off &= 0xFFFFFF
            r = struct.unpack_from("<I", e, 8)[0]
            self.upload((r >> 10) & 0x7FF, r >> 21, r & 0x3FF, h, sec[off:])
            off2 = struct.unpack_from("<I", e, 12)[0]
            if off2 & 0xFFFFFF:
                r2 = struct.unpack_from("<I", e, 16)[0]
                self.upload((r2 >> 10) & 0x7FF, r2 >> 21, r2 & 0x3FF, off2 >> 24, sec[off + (off2 & 0xFFFFFF):])
        return c

    @staticmethod
    def rgba(c: np.ndarray) -> np.ndarray:
        r = (c & 31).astype(np.uint16) * 255 // 31
        g = ((c >> 5) & 31) * 255 // 31
        b = ((c >> 10) & 31) * 255 // 31
        a = np.where(c == 0, 0, 255)
        return np.stack([r, g, b, a], -1).astype(np.uint8)

    def page(self, tpage: int, clut: int) -> np.ndarray:
        """256x256 RGBA view of a texture page through a CLUT (4/8-bit) or direct (15-bit)."""
        px, py, mode = (tpage & 15) * 64, ((tpage >> 4) & 1) * 256, (tpage >> 7) & 3
        cx, cy = (clut & 63) * 16, (clut >> 6) & 511
        if mode == 0:
            raw = self.m[py:py + 256, px:px + 64]
            idx = np.stack([(raw >> s) & 15 for s in (0, 4, 8, 12)], -1).reshape(raw.shape[0], -1)
            pal = self.m[cy, cx:cx + 16]
        elif mode == 1:
            raw = self.m[py:py + 256, px:px + 128]
            idx = np.stack([raw & 255, raw >> 8], -1).reshape(raw.shape[0], -1)
            pal = self.m[cy, cx:cx + 256]
        else:
            idx, pal = None, None
        if idx is None:
            col = self.m[py:py + 256, px:px + 256]
        else:
            pal = np.pad(pal, (0, 256 - len(pal)))
            col = pal[idx]
        out = np.zeros((256, 256), np.uint16)
        out[:col.shape[0], :col.shape[1]] = col[:256, :256]
        return self.rgba(out)


# ------------------------------------------------------------------------------------------------ models

class Model:
    """A PE skinned model: rigid per-bone vertex ranges, GT4/GT3 (textured) and G4/G3 (flat) primitives."""

    def __init__(self, data: bytes, off: int = 0):
        d = data
        h = struct.unpack_from("<4B12H", d, off)
        self.nbones, self.nverts = h[2], h[5]
        self.counts = h[6:10]                                     # GT4, GT3, G4, G3
        self.trav_len = h[14]
        p = off + 0x1C
        self.bones = []                                           # (first, count, geo, parent, offset_z)
        for i in range(self.nbones):
            first, cnt, geo, _b5, parent, _b7, oz = struct.unpack_from("<HHBBBBi", d, p + 12 * i)
            self.bones.append((first, cnt, geo, parent if parent != 255 else -1, oz))
        p += 12 * self.nbones
        v = np.frombuffer(d, "<i2", self.nverts * 4, p).reshape(-1, 4)
        self.verts, self.vnorm = v[:, :3].astype(np.float64), v[:, 3].copy()
        p += 8 * self.nverts
        self.vcol = np.frombuffer(d, np.uint8, self.nverts * 4, p).reshape(-1, 4)[:, :3].copy()
        p += 4 * self.nverts
        self.prims = []                                           # (kind, code, rgb, [vertex idx])
        for kind, n, nv in (("gt4", self.counts[0], 4), ("gt3", self.counts[1], 3),
                            ("g4", self.counts[2], 4), ("g3", self.counts[3], 3)):
            for k in range(n):
                r, g, b, code = d[p:p + 4]
                idx = list(struct.unpack_from(f"<{nv}H", d, p + 4))
                self.prims.append((kind, code, (r, g, b), idx))
                p += 12
        p += 0x10
        self.attach = [struct.unpack_from("<8h", d, p + 16 * i) for i in range(self.nbones)]
        p += 16 * self.nbones + 8
        self.trav = [x if x < 0x80 else x - 256 for x in d[p:p + self.trav_len]]
        p += (self.trav_len + 3) & ~3
        self.uvs = []                                             # per textured prim: ([(u,v)...], clut, tpage)
        for kind, n in (("gt4", self.counts[0]), ("gt3", self.counts[1])):
            for k in range(n):
                if kind == "gt4":
                    u0, v0, clut, u1, v1, tp, u2, v2, _a, u3, v3, _b = struct.unpack_from("<BBHBBHBBHBBH", d, p)
                    self.uvs.append(([(u0, v0), (u1, v1), (u2, v2), (u3, v3)], clut, tp))
                    p += 16
                else:
                    u0, v0, clut, u1, v1, tp, u2, v2, _a = struct.unpack_from("<BBHBBHBBH", d, p)
                    self.uvs.append(([(u0, v0), (u1, v1), (u2, v2)], clut, tp))
                    p += 12
        self.end = p
        self.vbone = np.zeros(self.nverts, np.int32)
        for i, (first, cnt, *_r) in enumerate(self.bones):
            self.vbone[first:first + cnt] = i

    def relocate(self, place: int):
        """Room models: patch UV page/CLUT for the VRAM slot packed in the type-2 entry's third word
        (FUN_80035038 -> FUN_8003d94c). Models already placed at the Aya slot (x=960, tpage 0x1F) are left alone."""
        x = (place >> 6) & 0x3C0
        y = (place >> 9) & 0x180
        clut_row = ((place >> 18) & 0xFF) + 0x1C0
        if x == 0x3C0 and self.uvs and self.uvs[0][2] == 0x1F:
            return
        shift = (((x >> 6) - 8) * 2 + (y >> 7) + (y >> 8) * 0x1E) & 0xFFFF
        shift >>= 1
        out = []
        for uv, clut, tp in self.uvs:
            if y == 0x80:                                       # second half of the page: v += 128 (POLY_GT v bytes)
                tp2 = tp + shift + (1 if uv[0][1] >= 0x80 else 0)
                uv = [(u, (v + 0x80) & 0xFF) for u, v in uv]
            else:
                tp2 = tp + shift
            out.append((uv, (clut + clut_row * 0x40 - 0x7080) & 0xFFFF, tp2 & 0xFFFF))
        self.uvs = out


def rot_matrix(rx: float, ry: float, rz: float) -> np.ndarray:
    """FUN_80079754 (libgte RotMatrix variant): R = Ry @ Rx @ Rz, angles in 4096-per-turn units."""
    a, b, c = (v * 2 * math.pi / 4096 for v in (rx, ry, rz))
    sx, cx, sy, cy, sz, cz = math.sin(a), math.cos(a), math.sin(b), math.cos(b), math.sin(c), math.cos(c)
    return np.array([[cy * cz + sy * sx * sz, sy * sx * cz - cy * sz, sy * cx],
                     [sz * cx, cz * cx, -sx],
                     [cy * sx * sz - sy * cz, sy * sz + cy * sx * cz, cy * cx]])


class Anim:
    """Decoded animation: trans[f] (root, 3), rot[f][bone] (3 angles, 4096 units)."""

    def __init__(self, data: bytes, off: int = 0):
        d = data
        kind, nb1, nf1 = d[off], d[off + 1], d[off + 2]
        self.kind, self.nbones, self.nframes = kind, nb1 + 1, nf1 + 1
        self.hdr = struct.unpack_from("<4h", d, off + 4)
        p = off + 12
        nf = self.nframes

        def t16():
            nonlocal p
            if struct.unpack_from("<h", d, p)[0] == 0:
                vals = list(struct.unpack_from(f"<{nf}h", d, p + 2))
                p += ((nf1 >> 1) + 1) * 4
            else:
                vals = [struct.unpack_from("<h", d, p + 2)[0]] * nf
                p += 4
            return vals

        def r8():
            nonlocal p
            if d[p] == 0:
                vals = [x << 4 for x in d[p + 1:p + 1 + nf]]
                p += ((nf1 >> 2) + 1) * 4
            else:
                vals = [d[p + 1] << 4] * nf
                p += 4
            return vals
        tr = [t16() for _ in range(3)]
        rd = t16 if (kind & 3) == 2 else r8
        rot = [[rd() for _ in range(3)] for _ in range(self.nbones)]
        self.end = p
        self.trans = np.array(tr, np.float64).T                              # (nf, 3)
        self.rot = np.array(rot, np.float64).transpose(2, 0, 1)               # (nf, nb, 3)


def pose(model: Model, anim: Anim | None, frame: int = 0):
    """World (R 3x3, t 3) of every bone, following the model's traversal list (FUN_8003a088)."""
    nb = model.nbones
    local_r = [np.eye(3)] * nb
    root_t = np.zeros(3)
    if anim is not None:
        f = min(frame, anim.nframes - 1)
        for b in range(min(nb, anim.nbones)):
            local_r[b] = rot_matrix(*anim.rot[f, b])
        root_t = anim.trans[f]
    world = [None] * nb
    parent = [-1] * nb
    cur = (np.eye(3), np.zeros(3), -1)
    stack = []
    for b in model.trav:
        if b == -1:
            stack.append(cur)
        elif b == -2:
            cur = stack.pop()
        elif 0 <= b < nb:
            t = root_t if b == 0 else np.array([0.0, 0.0, model.bones[b][4]])
            R = cur[0] @ local_r[b]
            T = cur[0] @ t + cur[1]
            world[b] = (R, T)
            parent[b] = cur[2]
            cur = (R, T, b)
    for b in range(nb):                                                     # bones missing from the traversal
        if world[b] is None:
            world[b] = (np.eye(3), np.zeros(3))
    return world, parent


def posed_vertices(model: Model, world) -> np.ndarray:
    out = np.zeros_like(model.verts)
    for i, (first, cnt, *_r) in enumerate(model.bones):
        R, T = world[i]
        out[first:first + cnt] = model.verts[first:first + cnt] @ R.T + T
    return out


# ------------------------------------------------------------------------------------------------ glTF

C = np.diag([1.0, -1.0, -1.0])                     # PS1 (Y down, Z into screen) -> glTF (Y up)


def _quat(m: np.ndarray) -> list[float]:
    u, _s, vt = np.linalg.svd(m)                     # nearest rotation (the data is 4.12 fixed point)
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1
        r = u @ vt
    t = np.trace(r)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = [(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, 0.25 * s]
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
        q = [0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s, (r[2, 1] - r[1, 2]) / s]
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
        q = [(r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s, (r[0, 2] - r[2, 0]) / s]
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
        q = [(r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s, (r[1, 0] - r[0, 1]) / s]
    n = math.sqrt(sum(x * x for x in q))
    return [x / n for x in q]


def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def model_to_glb(model: Model, vram: VRAM | None, anims: dict[int, Anim], path: Path, name: str = "pe",
                 scale: float = 1 / 290, rest_anim: int | None = None, fps: float = 30.0,
                 normals: np.ndarray | None = None, anim_names: dict[int, str] | None = None) -> dict:
    """Write a .glb: skinned mesh (rigid 1-bone weights), joints j00.. (hierarchy from the traversal list), texture
    atlas (one 256x256 slot per used tpage/CLUT pair), and one glTF animation per PE animation.
    Rest pose = frame 0 of `rest_anim` (default: lowest anim id) so the bind pose is a natural stance."""
    ids = sorted(anims)
    rest = anims.get(rest_anim if rest_anim is not None else (ids[0] if ids else -1))
    world, parent = pose(model, rest, 0)
    nb = model.nbones

    # local TRS in glTF space
    def local_trs(anim, f):
        w, _p = pose(model, anim, f)
        out = []
        for b in range(nb):
            R, T = w[b]
            if parent[b] >= 0:
                PR, PT = w[parent[b]]
                lr, lt = PR.T @ R, PR.T @ (T - PT)
            else:
                lr, lt = R, T
            out.append((C @ lr @ C, scale * (C @ lt)))
        return out
    rest_trs = local_trs(rest, 0)
    # feet on the ground: lift the root so the rest pose's lowest vertex sits at y = 0
    pv = posed_vertices(model, world)
    gpos = scale * (pv @ C.T)
    lift = -float(gpos[:, 1].min()) if len(gpos) else 0.0          # applied on node 0 (mesh + joints live under it)

    # atlas
    keys = []
    for uv, clut, tp in model.uvs:
        k = (tp, clut)
        if k not in keys:
            keys.append(k)
    atlas = None
    if keys and vram is not None:
        atlas = np.concatenate([vram.page(tp, clut) for tp, clut in keys], 0)

    # per-corner vertex streams
    P, N, UV, COL, J = [], [], [], [], []
    tex_idx, flat_idx = [], []
    vnorm = None
    if normals is not None:
        vnorm = np.zeros_like(model.verts)
        for i in range(model.nverts):
            n = normals[model.vnorm[i]] if 0 <= model.vnorm[i] < len(normals) else np.zeros(3)
            R = world[model.vbone[i]][0]
            vnorm[i] = C @ (R @ n)
    nk = max(len(keys), 1)
    for pi, (kind, code, rgb, idx) in enumerate(model.prims):
        tris = [(0, 1, 2), (1, 3, 2)] if len(idx) == 4 else [(0, 1, 2)]
        textured = kind in ("gt4", "gt3")
        if textured:
            uvl, clut, tp = model.uvs[pi]
            slot = keys.index((tp, clut))
        for tri in tris:
            # PS1 front faces are clockwise on screen (Y down); after the Y/Z flip they are CCW -> keep order reversed
            for c in (tri[0], tri[2], tri[1]):
                vi = idx[c]
                if vi >= model.nverts:
                    vi = 0
                (tex_idx if textured else flat_idx).append(len(P))
                P.append(gpos[vi])
                J.append(model.vbone[vi])
                if vnorm is not None:
                    N.append(vnorm[vi])
                if textured:
                    u, v = uvl[c]
                    UV.append(((u + 0.5) / 256.0, (slot * 256 + v + 0.5) / (256.0 * nk)))
                    COL.append((1.0, 1.0, 1.0, 1.0))
                else:
                    UV.append((0.0, 0.0))
                    COL.append((rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, 1.0))
    P = np.array(P, np.float32).reshape(-1, 3)
    if vnorm is None or not N:
        N = np.zeros_like(P)                                         # face normals
        for s in range(0, len(P), 3):
            n = np.cross(P[s + 1] - P[s], P[s + 2] - P[s])
            ln = np.linalg.norm(n)
            N[s:s + 3] = n / ln if ln > 0 else (0, 1, 0)
    N = np.array(N, np.float32)
    ln = np.linalg.norm(N, axis=1, keepdims=True)
    N = np.where(ln > 1e-6, N / np.maximum(ln, 1e-6), np.array([0, 1, 0], np.float32)).astype(np.float32)
    UV = np.array(UV, np.float32).reshape(-1, 2)
    COL = np.array(COL, np.float32).reshape(-1, 4)
    J4 = np.zeros((len(P), 4), np.uint8)
    J4[:, 0] = np.array(J, np.uint8)
    W4 = np.zeros((len(P), 4), np.float32)
    W4[:, 0] = 1.0

    blob = bytearray()
    views, accs = [], []

    def add(arr, comp, typ, target=None, minmax=False):
        nonlocal blob
        blob += bytes((-len(blob)) % 4)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, **({"target": target} if target else {})})
        blob += arr.tobytes()
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": int(arr.shape[0]), "type": typ}
        if minmax:
            a["min"] = [float(x) for x in arr.min(0)]
            a["max"] = [float(x) for x in arr.max(0)]
        accs.append(a)
        return len(accs) - 1

    attrs = {"POSITION": add(P, 5126, "VEC3", 34962, True), "NORMAL": add(N, 5126, "VEC3", 34962),
             "TEXCOORD_0": add(UV, 5126, "VEC2", 34962), "COLOR_0": add(COL, 5126, "VEC4", 34962),
             "JOINTS_0": add(J4, 5121, "VEC4", 34962), "WEIGHTS_0": add(W4, 5126, "VEC4", 34962)}
    prims, mats = [], []
    if tex_idx:
        mats.append({"name": f"{name}_tex", "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1,
                     **({"baseColorTexture": {"index": 0}} if atlas is not None else {})},
                     "alphaMode": "MASK", "alphaCutoff": 0.5, "doubleSided": True})
        prims.append({"attributes": attrs, "indices": add(np.array(tex_idx, np.uint32), 5125, "SCALAR", 34963),
                      "material": len(mats) - 1})
    if flat_idx:
        mats.append({"name": f"{name}_flat", "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1},
                     "doubleSided": True})
        prims.append({"attributes": attrs, "indices": add(np.array(flat_idx, np.uint32), 5125, "SCALAR", 34963),
                      "material": len(mats) - 1})

    # skeleton nodes: 0 = scene root (lift), 1 = mesh, 2.. = joints
    jn = lambda b: 2 + b  # noqa: E731
    nodes = [{"name": name, "translation": [0, lift, 0], "children": [1]},
             {"name": f"{name}_mesh", "mesh": 0, "skin": 0}]
    for b in range(nb):
        lr, lt = rest_trs[b]
        nodes.append({"name": f"j{b:02d}", "translation": [float(x) for x in lt], "rotation": _quat(lr)})
    for b in range(nb):
        kids = [jn(c) for c in range(nb) if parent[c] == b]
        if kids:
            nodes[jn(b)]["children"] = kids
    roots = [jn(b) for b in range(nb) if parent[b] < 0]
    nodes[0]["children"] += roots
    ibm = []
    for b in range(nb):
        R, T = world[b]
        m = np.eye(4)
        m[:3, :3], m[:3, 3] = C @ R @ C, scale * (C @ T)
        ibm.append(np.linalg.inv(m).T.reshape(-1))
    skin = {"joints": [jn(b) for b in range(nb)],
            "inverseBindMatrices": add(np.array(ibm, np.float32), 5126, "MAT4"), "skeleton": roots[0] if roots else jn(0)}

    # animations
    gl_anims = []
    for aid in ids:
        a = anims[aid]
        times = np.arange(a.nframes, dtype=np.float32) / fps
        tin = add(times.reshape(-1, 1), 5126, "SCALAR", minmax=True)
        frames = [local_trs(a, f) for f in range(a.nframes)]
        chans, samps = [], []
        for b in range(nb):
            q = np.array([_quat(frames[f][b][0]) for f in range(a.nframes)], np.float32)
            for f in range(1, len(q)):                                # keep quaternion signs continuous
                if np.dot(q[f], q[f - 1]) < 0:
                    q[f] = -q[f]
            samps.append({"input": tin, "output": add(q, 5126, "VEC4"), "interpolation": "LINEAR"})
            chans.append({"sampler": len(samps) - 1, "target": {"node": jn(b), "path": "rotation"}})
            if parent[b] < 0:
                t = np.array([frames[f][b][1] for f in range(a.nframes)], np.float32)
                samps.append({"input": tin, "output": add(t, 5126, "VEC3"), "interpolation": "LINEAR"})
                chans.append({"sampler": len(samps) - 1, "target": {"node": jn(b), "path": "translation"}})
        nm = (anim_names or {}).get(aid, f"anim_{aid:02d}")
        gl_anims.append({"name": nm, "channels": chans, "samplers": samps})

    gl = {"asset": {"version": "2.0", "generator": "gBox parasite_eve.py"},
          "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
          "meshes": [{"name": f"{name}_mesh", "primitives": prims}], "skins": [skin], "materials": mats,
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": 0}]}
    if gl_anims:
        gl["animations"] = gl_anims
    if atlas is not None:
        png = _png(atlas)
        blob += bytes((-len(blob)) % 4)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(png)})
        blob += png
        gl["images"] = [{"bufferView": len(views) - 1, "mimeType": "image/png", "name": f"{name}_atlas"}]
        gl["textures"] = [{"source": 0, "sampler": 0}]
        gl["samplers"] = [{"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}]
    blob += bytes((-len(blob)) % 4)
    gl["buffers"][0]["byteLength"] = len(blob)
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    Path(path).write_bytes(out)
    return {"path": str(path), "bones": nb, "verts": int(model.nverts), "prims": len(model.prims),
            "corners": int(len(P)), "materials": len(mats), "atlas_slots": len(keys), "animations": len(gl_anims),
            "height_m": float(gpos[:, 1].max() - gpos[:, 1].min()) if len(gpos) else 0.0}


# ------------------------------------------------------------------------------------------------ high level

def load_models(sec: bytes) -> list[tuple[Model, dict[int, Anim], dict]]:
    """Every type-2 model of a section/blob with its type-3 animations (anim entry byte 11 = model id, byte 7 = slot)."""
    out = []
    anims_all = assets(sec, 3)
    for e in assets(sec, 2):
        model = Model(sec, e["offset"])
        place = struct.unpack_from("<I", e["raw"], 8)[0]
        if (place >> 8) & 0xF:                                   # FUN_80035038 passes this as the relocate flag
            model.relocate(place)
        anims = {}
        for a in anims_all:
            if a["raw"][11] != e["id"]:
                continue
            try:
                an = Anim(sec, a["offset"])
            except (struct.error, IndexError, ValueError):
                continue
            if an.nbones <= model.nbones:
                anims[a["id"]] = an
        out.append((model, anims, e))
    return out


def load_model_blob(blob: bytes) -> tuple[Model, dict[int, Anim], dict]:
    m = load_models(blob)
    if not m:
        raise ValueError("no model in blob")
    return m[0]


def export_aya(pe: PEData, out: Path, outfit: int = 0, scale: float = 1 / 290, **kw) -> dict:
    """Aya Brea (outfit 0..4) -> .glb."""
    blob = pe.common_blob(AYA_MODEL_BLOB + outfit)
    model, anims, _e = load_model_blob(blob)
    vram = VRAM()
    vram.load_section(pe.common_blob(AYA_TEX_BLOB + outfit))
    return model_to_glb(model, vram, anims, out, name=f"aya_{AYA_OUTFITS_NAMES[outfit]}", scale=scale, normals=pe.normals(),
                        anim_names=AYA_ANIM_NAMES, **kw)


def room_vram(pe: PEData, i: int) -> tuple[VRAM, list[bytes]]:
    secs = pe.room_sections(i)
    v = VRAM()
    v.load_section(pe.common_blob(AYA_TEX_BLOB))                 # Aya's slot (some room models reuse it)
    for sec in secs:
        v.load_section(sec)
    return v, secs


def export_room_models(pe: PEData, i: int, out_dir: Path, scale: float = 1 / 290, seen: dict | None = None) -> list[dict]:
    """All models of room package i -> out_dir/pe_r{i:03d}_m{id:02d}.glb (skipping models already in `seen`,
    keyed by the model bytes' hash)."""
    import hashlib
    vram, secs = room_vram(pe, i)
    out = []
    for model, anims, e in load_models(secs[2]):
        h = hashlib.sha1(secs[2][e["offset"]:e["offset"] + e["size"]]).hexdigest()[:12]
        if seen is not None and h in seen:
            seen[h]["rooms"].append(i)
            continue
        path = Path(out_dir) / f"pe_r{i:03d}_m{e['id']:02d}.glb"
        r = model_to_glb(model, vram, anims, path, name=f"pe_r{i:03d}_m{e['id']:02d}", scale=scale,
                         normals=pe.normals())
        r.update({"room": i, "model_id": e["id"], "hash": h, "rooms": [i]})
        if seen is not None:
            seen[h] = r
        out.append(r)
    return out


def list_packages(pe: PEData) -> list[dict]:
    out = []
    for i, (s, info) in enumerate(pe.rooms):
        if not info:
            continue
        secs = pe.room_sections(i)
        d = section_dir(secs[2])
        tag = struct.unpack_from("<I", secs[2], struct.unpack_from("<I", secs[2], 4)[0])[0] if d else 0
        out.append({"index": i, "sector": s, "sectors": [info & 0xFF, (info >> 8) & 0xFFF, info >> 20],
                    "tag": f"{tag:08x}", "models": [a["id"] for a in assets(secs[2], 2)],
                    "anims": len(assets(secs[2], 3))})
    return out
