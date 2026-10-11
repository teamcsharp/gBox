"""Super Smash Bros. Melee (GameCube, GALE01) fighter models -> glTF (skeleton + skinned mesh + textures).

Formats (HAL "HSD" archives, as documented by the Melee modding community: HSDLib/HSDRaw, the SSBM data sheet):

  .dat         0x20 header (u32 file size, data size, #relocations, #roots, #references), data block, relocation table
               (u32 offsets of every pointer field in the data block), root table (u32 offset, u32 name offset), names.
               A pointer field is valid iff its own offset is in the relocation table (offset 0 is a valid target).
  Pl<Xx>Nr.dat costume file. Root "Ply<Name>5K_Share_joint" = JObj tree:
               JObj 0x40: 0 class, 4 flags, 8 child, 0xC next, 0x10 DObj, 0x14 rot xyz, 0x20 scale, 0x2C trans,
               0x38 inverse bind 3x4. World = parent @ T @ Rz @ Ry @ Rx @ S. Joints are numbered depth-first.
               DObj 0x10: 4 next, 8 MObj, 0xC PObj.  MObj: 8 TObj, 0xC material (ambient, diffuse RGBA8, ...).
               PObj 0x18: 4 next, 8 vertex attribute descriptors, 0xC u16 flags (0x2000 envelope), 0xE u16 DL size
               (x32 bytes), 0x10 display list, 0x14 envelope list (envelope = [{JObj*, f32 weight}], null-terminated).
               Attribute descriptor 0x18: attr (9 pos, 10 nrm, 11 clr0, 13 tex0, 0 PNMTXIDX), type (1 direct,
               2 index8, 3 index16), comp count, comp type, u8 frac, u16 stride, data ptr; ends with attr 0xFF.
               Envelope vertices: one joint (weight 1) -> joint-local coordinates (world = W_j @ v); several ->
               bind-pose model space (world = sum w * W_j @ invBind_j @ v). Rigid PObjs: world = W_owner @ v.
               TObj 0x5C: 0x1C scale xyz, 0x34 wrap S/T, 0x3C repeat S/T, 0x40 flags, 0x4C image (data, u16 w, u16 h,
               u32 GX format), 0x50 TLUT (data, fmt, ?, u16 count).
  Pl<Xx>.dat   root "ftData<Name>"; ftData+0x08 = model lookup tables {u32 #groups, costume visibility tables[0x10]
               = (high poly, low poly, metal, ?)}, each a list of #groups x {count, [{count, u8 DObj indices[]}]}.
               High poly default = first option of every group (the others are swap-in hands/eyes/low poly).
  PlCo.dat     "ftLoadCommonData"+0x10 -> per fighter {u8 joint->common bone id[], u8 common->joint[], count}
               (common ids: TopN 0, TransN 1, XRotN 2, YRotN 3, HipN 4, WaistN 5, LLegJA 6, LLegJ 7, LKneeJ 8,
               LFootJA 9, LFootJ 10, RLegJA 11 ... RFootJ 15, BustN 16, LShoulderN 17, LShoulderJA 18, LShoulderJ 19,
               LArmJ 20, LHandN 21, ... NeckN 33?, HeadN ... see COMMON).
"""
from __future__ import annotations

import base64
import io
import json
import struct
from pathlib import Path

import numpy as np

# internal fighter order (PlCo bone tables are indexed by this) + file codes
FIGHTERS = [("Mario", "Mr"), ("Fox", "Fx"), ("CaptainFalcon", "Ca"), ("DonkeyKong", "Dk"), ("Kirby", "Kb"),
            ("Bowser", "Kp"), ("Link", "Lk"), ("Sheik", "Sk"), ("Ness", "Ns"), ("Peach", "Pe"), ("Popo", "Pp"),
            ("Nana", "Nn"), ("Pikachu", "Pk"), ("Samus", "Ss"), ("Yoshi", "Ys"), ("Jigglypuff", "Pr"),
            ("Mewtwo", "Mt"), ("Luigi", "Lg"), ("Marth", "Ms"), ("Zelda", "Zd"), ("YoungLink", "Cl"),
            ("DrMario", "Dr"), ("Falco", "Fc"), ("Pichu", "Pc"), ("GameAndWatch", "Gw"), ("Ganondorf", "Gn"),
            ("Roy", "Fe"), ("MasterHand", "Mh"), ("CrazyHand", "Ch"), ("WireframeMale", "Bo"),
            ("WireframeFemale", "Gl"), ("GigaBowser", "Gk"), ("Sandbag", "Sb")]
CODE = {name: code for name, code in FIGHTERS}
PLAYABLE = [n for n, _ in FIGHTERS[:27]]          # the 26 fighters (Popo + Nana = Ice Climbers, both listed)

COMMON = ["TopN", "TransN", "XRotN", "YRotN", "HipN", "WaistN", "LLegJA", "LLegJ", "LKneeJ", "LFootJA", "LFootJ",
          "RLegJA", "RLegJ", "RKneeJ", "RFootJA", "RFootJ", "BustN", "LShoulderN", "LShoulderJA", "LShoulderJ",
          "LArmJ", "LHandN", "L1stNa", "L1stNb", "L2ndNa", "L2ndNb", "L3rdNa", "L3rdNb", "L4thNa", "L4thNb",
          "LThumbNa", "LThumbNb", "LHandNb", "LHaveN", "NeckN", "HeadN", "RShoulderJA", "RShoulderJ", "RArmJ",
          "RHandN", "R1stNa", "R1stNb", "R2ndNa", "R2ndNb", "R3rdNa", "R3rdNb", "R4thNa", "R4thNb", "RThumbNa",
          "RThumbNb", "RHandNb", "RHaveN", "ThrowN", "TransN2"]
# body roles -> common bone id, checked against Peach's rest pose (T-pose: shoulder joint, elbow, hand pivots)
ROLE_IDS = {"hip": 4, "chest": 16, "neck": 34, "head": 35, "l_clav": 18, "l_upper": 20, "l_fore": 21, "l_hand": 22,
            "r_clav": 36, "r_upper": 38, "r_fore": 39, "r_hand": 40, "l_thigh": 7, "l_shin": 8, "l_foot": 10,
            "r_thigh": 12, "r_shin": 13, "r_foot": 15}
ROLE_FALLBACK = {"l_upper": [19], "r_upper": [37], "l_hand": [32, 21], "r_hand": [50, 39], "l_foot": [9],
                 "r_foot": [14], "chest": [5, 17], "neck": [35, 16], "head": [34, 16, 5], "l_clav": [17, 19], "r_clav": [37],
                 "l_thigh": [6], "r_thigh": [11]}


# ---------------------------------------------------------------- HSD archive
class HSD:
    def __init__(self, data: bytes):
        self.raw = data
        fs, ds, nr, nroot, nref = struct.unpack_from(">5I", data, 0)
        self.d = data[0x20:0x20 + ds]
        self.rel = set(struct.unpack_from(f">{nr}I", data, 0x20 + ds))
        o = 0x20 + ds + 4 * nr
        strs = o + 8 * (nroot + nref)
        self.roots = {}
        for i in range(nroot):
            off, so = struct.unpack_from(">II", data, o + 8 * i)
            self.roots[data[strs + so:data.index(b"\0", strs + so)].decode("latin-1")] = off

    def u8(self, o):
        return self.d[o]

    def u16(self, o):
        return struct.unpack_from(">H", self.d, o)[0]

    def u32(self, o):
        return struct.unpack_from(">I", self.d, o)[0]

    def f32(self, o, n=1):
        v = struct.unpack_from(f">{n}f", self.d, o)
        return v[0] if n == 1 else v

    def ptr(self, o):
        """Pointer stored at o, or None if that field is not relocated (null)."""
        return self.u32(o) if o in self.rel else None

    def root(self, suffix: str):
        return next(v for k, v in self.roots.items() if k.endswith(suffix))


# ---------------------------------------------------------------- GX textures
def _rgb5a3(c):
    c = c.astype(np.int32)
    op = (c & 0x8000) != 0
    r = np.where(op, ((c >> 10) & 31) * 255 // 31, ((c >> 8) & 15) * 17)
    g = np.where(op, ((c >> 5) & 31) * 255 // 31, ((c >> 4) & 15) * 17)
    b = np.where(op, (c & 31) * 255 // 31, (c & 15) * 17)
    a = np.where(op, 255, ((c >> 12) & 7) * 255 // 7)
    return np.stack([r, g, b, a], -1).astype(np.uint8)


def _rgb565(c):
    c = c.astype(np.int32)
    return np.stack([((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31,
                     np.full(c.shape, 255)], -1).astype(np.uint8)


def _ia8(c):
    c = c.astype(np.int32)
    i, a = c & 0xFF, c >> 8
    return np.stack([i, i, i, a], -1).astype(np.uint8)


def _palette(tlut: bytes, fmt: int, n: int) -> np.ndarray:
    v = np.frombuffer(tlut[:2 * n], ">u2")
    return {0: _ia8, 1: _rgb565, 2: _rgb5a3}[fmt](v)


_BLOCK = {0: (8, 8, 4), 1: (8, 4, 8), 2: (8, 4, 8), 3: (4, 4, 16), 4: (4, 4, 16), 5: (4, 4, 16), 6: (4, 4, 32),
          8: (8, 8, 4), 9: (8, 4, 8), 10: (4, 4, 16), 14: (8, 8, 4)}


def tex_size(fmt: int, w: int, h: int) -> int:
    bw, bh, bpp = _BLOCK[fmt]
    return ((w + bw - 1) // bw) * ((h + bh - 1) // bh) * bw * bh * bpp // 8


def _untile(px: np.ndarray, w: int, h: int, bw: int, bh: int) -> np.ndarray:
    """px: (nblocks, bh*bw, C) in GX block order -> (h, w, C)."""
    W, H = (w + bw - 1) // bw * bw, (h + bh - 1) // bh * bh
    img = px.reshape(H // bh, W // bw, bh, bw, -1).transpose(0, 2, 1, 3, 4).reshape(H, W, -1)
    return img[:h, :w]


def decode_texture(data: bytes, fmt: int, w: int, h: int, tlut: bytes | None = None, tlut_fmt: int = 0,
                   tlut_n: int = 256) -> np.ndarray:
    """GameCube GX texture -> RGBA uint8 (h, w, 4). I4 I8 IA4 IA8 RGB565 RGB5A3 RGBA8 CI4 CI8 CMPR."""
    bw, bh, bpp = _BLOCK[fmt]
    nb = ((w + bw - 1) // bw) * ((h + bh - 1) // bh)
    d = np.frombuffer(data[:tex_size(fmt, w, h)], np.uint8)
    if fmt in (0, 8):                                        # 4-bit
        v = np.stack([d >> 4, d & 15], -1).reshape(nb, 64)
        if fmt == 0:
            px = np.repeat((v * 17)[..., None], 4, -1).astype(np.uint8)
        else:
            px = _palette(tlut, tlut_fmt, tlut_n)[np.minimum(v, tlut_n - 1)]
    elif fmt in (1, 9):
        v = d.reshape(nb, 32)
        px = np.repeat(v[..., None], 4, -1) if fmt == 1 else _palette(tlut, tlut_fmt, tlut_n)[np.minimum(v, tlut_n - 1)]
    elif fmt == 2:
        v = d.reshape(nb, 32).astype(np.int32)
        i, a = (v & 15) * 17, (v >> 4) * 17
        px = np.stack([i, i, i, a], -1).astype(np.uint8)
    elif fmt in (3, 4, 5, 10):
        v = d.view(">u2").reshape(nb, 16)
        if fmt == 3:
            v = v.astype(np.int32)
            px = np.stack([v & 0xFF, v & 0xFF, v & 0xFF, v >> 8], -1).astype(np.uint8)
        elif fmt == 4:
            px = _rgb565(v)
        elif fmt == 5:
            px = _rgb5a3(v)
        else:
            px = _palette(tlut, tlut_fmt, tlut_n)[np.minimum(v & 0x3FFF, tlut_n - 1)]
    elif fmt == 6:
        v = d.reshape(nb, 2, 16, 2)
        px = np.stack([v[:, 0, :, 1], v[:, 1, :, 0], v[:, 1, :, 1], v[:, 0, :, 0]], -1)
    elif fmt == 14:                                          # CMPR: 8x8 tiles of 2x2 DXT1 4x4 blocks
        v = d.reshape(nb, 4, 8)
        c0 = (v[..., 0].astype(np.int32) << 8) | v[..., 1]
        c1 = (v[..., 2].astype(np.int32) << 8) | v[..., 3]
        bits = (v[..., 4].astype(np.uint32) << 24) | (v[..., 5].astype(np.uint32) << 16) | (v[..., 6].astype(np.uint32) << 8) | v[..., 7]
        a, b = _rgb565(c0).astype(np.int32), _rgb565(c1).astype(np.int32)
        gt = (c0 > c1)[..., None]
        p2 = np.where(gt, (2 * a + b) // 3, (a + b) // 2)
        p3 = np.where(gt, (a + 2 * b) // 3, 0)
        p3[..., 3] = np.where(gt[..., 0], 255, 0)
        p2[..., 3] = 255
        pal = np.stack([a, b, p2, p3], -2)                   # (nb, 4, 4 colours, 4)
        idx = (bits[..., None] >> (30 - 2 * np.arange(16, dtype=np.uint32))) & 3   # (nb, 4, 16)
        sub = np.take_along_axis(pal, idx[..., None].astype(np.int64).repeat(4, -1), 2)  # (nb, 4, 16, 4)
        sub = sub.reshape(nb, 2, 2, 4, 4, 4).transpose(0, 1, 3, 2, 4, 5).reshape(nb, 64, 4)
        px = sub.astype(np.uint8)
    else:
        raise ValueError(f"GX texture format {fmt} not supported")
    return _untile(px.reshape(nb, bw * bh, 4), w, h, bw, bh)


# ---------------------------------------------------------------- scene graph
def _rot(rx, ry, rz):
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


ATTR_SIZE = {0: 1, 3: 2, 4: 4}                             # comp type -> bytes (u8/s8 1, u16/s16 2, f32 4)
CLR_SIZE = {0: 2, 1: 3, 2: 4, 3: 2, 4: 3, 5: 4}


def _decode_attr(h, o, attr, cnt, ctype, frac):
    """One GX vertex attribute value at h.d[o]."""
    if attr == 11 or attr == 12:
        if ctype == 5 or ctype == 2:
            return tuple(h.d[o:o + 4]) if ctype == 5 else tuple(h.d[o:o + 3]) + (255,)
        if ctype == 1:
            return tuple(h.d[o:o + 3]) + (255,)
        if ctype == 3:
            c = struct.unpack_from(">H", h.d, o)[0]
            return ((c >> 12) * 17, ((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17)
        if ctype == 0:
            return tuple(_rgb565(np.array([struct.unpack_from(">H", h.d, o)[0]]))[0])
        c = h.d[o:o + 3]
        x = (c[0] << 16) | (c[1] << 8) | c[2]
        return tuple(((x >> s) & 63) * 255 // 63 for s in (18, 12, 6, 0))
    nc = {9: (2, 3), 10: (3, 9)}.get(attr, (1, 2))[min(cnt, 1)]
    fmt = {0: "B", 1: "b", 2: "H", 3: "h", 4: "f"}[ctype]
    vals = struct.unpack_from(">" + fmt * nc, h.d, o)
    if ctype != 4:
        vals = tuple(x / (1 << frac) for x in vals)
    return vals


class Model:
    """One Melee costume model: joints (rest pose) + DObjs with decoded geometry."""

    def __init__(self, nr: bytes, ft: bytes | None = None, costume: int = 0):
        self.h = h = HSD(nr)
        root = h.root("_Share_joint") if any(k.endswith("_Share_joint") for k in h.roots) else h.root("_joint")
        self.joints = []          # [{off, parent, flags, local(4x4), world, dobj}]
        self.jidx = {}
        self._walk(root, -1, np.eye(4))
        self.dobjs = []           # (joint index, dobj offset)
        for ji, j in enumerate(self.joints):
            d = j["dobj"]
            while d is not None:
                self.dobjs.append((ji, d))
                d = h.ptr(d + 4)
        self.visible = set(range(len(self.dobjs)))
        if ft is not None:
            self.visible = self._high_poly(HSD(ft), costume)
        self._tex_cache = {}

    def _walk(self, o, parent, pw):
        h = self.h
        while o is not None:
            rx, ry, rz, sx, sy, sz, tx, ty, tz = h.f32(o + 0x14, 9)
            loc = np.eye(4)
            loc[:3, :3] = _rot(rx, ry, rz) @ np.diag([sx, sy, sz])
            loc[:3, 3] = (tx, ty, tz)
            w = pw @ loc
            ib = h.ptr(o + 0x38)
            inv = None
            if ib is not None:
                inv = np.eye(4)
                inv[:3, :] = np.array(h.f32(ib, 12)).reshape(3, 4)
            flags = h.u32(o + 4)
            dobj = h.ptr(o + 0x10) if not flags & 0x4020 else None   # 0x20 = spline/particle? 0x4000 = ptcl
            self.jidx[o] = len(self.joints)
            self.joints.append({"off": o, "parent": parent, "flags": flags, "local": loc, "world": w,
                                "invbind": inv, "dobj": dobj})
            me = len(self.joints) - 1
            c = h.ptr(o + 8)
            if c is not None:
                self._walk(c, me, w)
            o = h.ptr(o + 0xC)

    def _high_poly(self, ft: HSD, costume: int) -> set:
        fd = ft.root("ftData" + "") if False else next(v for k, v in ft.roots.items() if k.startswith("ftData"))
        lt = ft.ptr(fd + 8)
        if lt is None:
            return set(range(len(self.dobjs)))
        ngroups = ft.u32(lt)
        cos = ft.ptr(lt + 4)
        hi = ft.ptr(cos + 0x10 * costume) if cos is not None else None
        if hi is None:
            hi = ft.ptr(cos)
        vis = set()
        self.part_groups = []
        for g in range(ngroups):
            cnt, ents = ft.u32(hi + 8 * g), ft.ptr(hi + 8 * g + 4)
            if not cnt or ents is None:
                continue
            opts = []
            for k in range(cnt):
                c2, q = ft.u32(ents + 8 * k), ft.ptr(ents + 8 * k + 4)
                opts.append(list(ft.d[q:q + c2]) if q is not None else [])
            self.part_groups.append(opts)
            vis.update(opts[0])                      # default = first option (other options: swap-in parts)
        return vis

    # ---- textures
    def texture(self, tobj: int) -> np.ndarray | None:
        h = self.h
        img = h.ptr(tobj + 0x4C)
        if img is None:
            return None
        if img in self._tex_cache:
            return self._tex_cache[img]
        dp = h.ptr(img)
        w, hh, fmt = h.u16(img + 4), h.u16(img + 6), h.u32(img + 8)
        tl = h.ptr(tobj + 0x50)
        tlut, tf, tn = None, 0, 256
        if tl is not None:
            tp = h.ptr(tl)
            tf, tn = h.u32(tl + 4), h.u16(tl + 0xC)
            tlut = h.d[tp:tp + 2 * tn]
        rgba = decode_texture(h.d[dp:], fmt, w, hh, tlut, tf, tn)
        self._tex_cache[img] = rgba
        return rgba

    def material(self, mobj: int) -> dict:
        """{'tex': RGBA or None, 'color': (r,g,b,a), 'uv_scale': (s,t), 'tobj': off}; base = first UV-mapped TObj."""
        h = self.h
        mat = h.ptr(mobj + 0xC)
        col = tuple(h.d[mat + 4:mat + 8]) if mat is not None else (200, 200, 200, 255)
        alpha = h.f32(mat + 0xC) if mat is not None else 1.0
        t = h.ptr(mobj + 8)
        out = {"tex": None, "color": col[:3] + (int(255 * min(max(alpha, 0), 1)),), "uv_scale": (1, 1), "tobj": None,
               "layers": []}
        while t is not None:
            fl = h.u32(t + 0x40)
            if fl & 0xF == 0:                                # UV coords (not reflection/sphere maps)
                sx, sy = h.f32(t + 0x1C, 2)
                rs, rt = h.u8(t + 0x3C), h.u8(t + 0x3D)
                tx, ty = h.f32(t + 0x28, 2)
                layer = {"tobj": t, "flags": fl, "scale": (sx * rs, sy * rt), "trans": (tx, ty),
                         "blend": h.f32(t + 0x44), "src": h.u32(t + 0xC)}
                out["layers"].append(layer)
                if out["tex"] is None:
                    out["tex"] = self.texture(t)
                    out["uv_scale"], out["tobj"] = layer["scale"], t
                    out["uv_trans"] = layer["trans"]
            t = h.ptr(t + 4)
        return out

    # ---- geometry
    def pobj_geometry(self, pobj: int, owner: int):
        """-> dict(pos (n,3) world, nrm (n,3), uv (n,2), clr (n,4), tris (m,3) local indices, env ([(joint, w)]) per vertex)."""
        h = self.h
        attrs = []
        a = h.ptr(pobj + 8)
        while a is not None and h.u32(a) != 0xFF:
            attr, typ, cnt, ctype = struct.unpack_from(">4I", h.d, a)
            frac, stride, dp = h.u8(a + 0x10), h.u16(a + 0x12), h.ptr(a + 0x14)
            attrs.append((attr, typ, cnt, ctype, frac, stride, dp))
            a += 0x18
        flags = h.u16(pobj + 0xC)
        dl_size = h.u16(pobj + 0xE) * 32
        dl = h.d[h.ptr(pobj + 0x10):h.ptr(pobj + 0x10) + dl_size]
        envs = []
        if flags & 0x2000:
            el = h.ptr(pobj + 0x14)
            k = 0
            while el is not None and (el + 4 * k) in h.rel:
                e = h.u32(el + 4 * k)
                ws, m = [], 0
                while (e + 8 * m) in h.rel:
                    ws.append((self.jidx[h.u32(e + 8 * m)], h.f32(e + 8 * m + 4)))
                    m += 1
                envs.append(ws)
                k += 1
        # read display list
        verts, tris = [], []
        p = 0
        while p < len(dl):
            cmd = dl[p] & 0xF8
            if cmd == 0 or cmd not in (0x80, 0x90, 0x98, 0xA0):
                if cmd == 0:
                    p += 1
                    continue
                break
            n = struct.unpack_from(">H", dl, p + 1)[0]
            p += 3
            base = len(verts)
            for _ in range(n):
                v = {}
                for attr, typ, cnt, ctype, frac, stride, dp in attrs:
                    if typ == 1:                              # direct
                        if attr <= 8:
                            v[attr] = dl[p]
                            p += 1
                            continue
                        if attr in (11, 12):
                            n_ = CLR_SIZE[ctype]
                        else:
                            n_ = {9: (2, 3), 10: (3, 9)}.get(attr, (1, 2))[min(cnt, 1)] * {0: 1, 1: 1, 2: 2, 3: 2, 4: 4}[ctype]
                        v[attr] = ("direct", bytes(dl[p:p + n_]))
                        p += n_
                        continue
                    if typ == 2:
                        v[attr] = dl[p]
                        p += 1
                    else:
                        v[attr] = struct.unpack_from(">H", dl, p)[0]
                        p += 2
                verts.append(v)
            idx = list(range(base, base + n))
            if cmd == 0x90:
                tris += [idx[i:i + 3] for i in range(0, n - 2, 3)]
            elif cmd == 0x98:
                tris += [(idx[i], idx[i + 1], idx[i + 2]) if i % 2 == 0 else (idx[i + 1], idx[i], idx[i + 2]) for i in range(n - 2)]
            elif cmd == 0xA0:
                tris += [(idx[0], idx[i], idx[i + 1]) for i in range(1, n - 1)]
            elif cmd == 0x80:
                for i in range(0, n - 3, 4):
                    tris += [(idx[i], idx[i + 1], idx[i + 2]), (idx[i], idx[i + 2], idx[i + 3])]

        def fetch(attr, i):
            for at, typ, cnt, ctype, frac, stride, dp in attrs:
                if at != attr:
                    continue
                if isinstance(i, tuple):                      # direct data: decode from a private buffer
                    sub = HSD.__new__(HSD)
                    sub.d, sub.rel = i[1], set()
                    return _decode_attr(sub, 0, attr, cnt, ctype, frac)
                o = dp + i * stride
                return _decode_attr(h, o, attr, cnt, ctype, frac)
            return None

        has = {at for at, *_ in attrs}
        n = len(verts)
        pos, nrm = np.zeros((n, 3)), np.zeros((n, 3))
        uv, clr = np.zeros((n, 2)), np.full((n, 4), 255.0)
        env = []
        cache = {}
        for k, v in enumerate(verts):
            pv = cache.get(("p", v[9])) or cache.setdefault(("p", v[9]), fetch(9, v[9]))
            pos[k, :len(pv)] = pv[:3]
            if 10 in has:
                nv = fetch(10, v[10])
                nrm[k] = nv[:3]
            if 13 in has:
                uv[k] = fetch(13, v[13])[:2]
            if 11 in has:
                clr[k] = fetch(11, v[11])
            if envs:
                env.append(envs[v.get(0, 0) // 3])
            else:
                env.append([(owner, 1.0)])
        # to world (rest pose)
        J = self.joints
        wp, wn = np.zeros_like(pos), np.zeros_like(nrm)
        for k in range(n):
            ws = env[k]
            if envs and len(ws) == 1:
                M = J[ws[0][0]]["world"]
            elif envs:
                M = sum(w * (J[j]["world"] @ (J[j]["invbind"] if J[j]["invbind"] is not None else np.linalg.inv(J[j]["world"])))
                        for j, w in ws)
            else:
                M = J[owner]["world"]
            wp[k] = M[:3, :3] @ pos[k] + M[:3, 3]
            wn[k] = M[:3, :3] @ nrm[k]
        wn /= np.maximum(np.linalg.norm(wn, axis=1, keepdims=True), 1e-9)
        return {"pos": wp, "nrm": wn, "uv": uv, "clr": clr, "tris": np.array(tris, np.int64).reshape(-1, 3), "env": env,
                "flags": flags}

    def meshes(self, all_dobjs: bool = False):
        """[(dobj index, material dict, geometry)] for the visible (high poly default) DObjs."""
        h = self.h
        out = []
        for di, (ji, d) in enumerate(self.dobjs):
            if not all_dobjs and di not in self.visible:
                continue
            if self.joints[ji]["flags"] & 0x10:              # hidden joint
                pass
            mobj = h.ptr(d + 8)
            mat = self.material(mobj) if mobj is not None else {"tex": None, "color": (200, 200, 200, 255), "uv_scale": (1, 1), "layers": []}
            p = h.ptr(d + 0xC)
            while p is not None:
                g = self.pobj_geometry(p, ji)
                if len(g["tris"]):
                    out.append((di, mat, g))
                p = h.ptr(p + 4)
        return out


def common_ids(plco: bytes, fighter: str) -> dict[int, int]:
    """joint index -> common bone id for a fighter (PlCo.dat ftLoadCommonData+0x10, per-fighter u8 table)."""
    h = HSD(plco)
    cd = h.roots["ftLoadCommonData"]
    tabs = h.ptr(cd + 0x10)
    i = [n for n, _ in FIGHTERS].index(fighter)
    e = h.ptr(tabs + 4 * i)
    a, cnt = h.ptr(e), h.u32(e + 8)
    return {j: h.d[a + j] for j in range(cnt) if h.d[a + j] != 0xFF}


def bone_table(plco: bytes, fighter: str) -> dict[int, str]:
    """joint index -> common bone name for a fighter (from PlCo.dat)."""
    return {j: COMMON[c] if c < len(COMMON) else f"C{c}" for j, c in common_ids(plco, fighter).items()}


def body_roles(ids: dict[int, int], njoints: int = 1 << 30) -> dict[str, int]:
    """common ids of a fighter's joints -> {role: joint index} (hip, chest, neck, head, l_upper ... r_foot)."""
    inv = {}
    for j, c in ids.items():
        if j >= njoints:
            continue
        inv.setdefault(c, j)
    out = {}
    for role, c in ROLE_IDS.items():
        for cc in [c] + ROLE_FALLBACK.get(role, []):
            if cc in inv:
                out[role] = inv[cc]
                break
    return out


def source_rig(model: "Model", ids: dict[int, int]) -> dict:
    """Generic rig for gbox.re4gc_enemies.retarget: joints (world xyz), parents, roles, prims with a per-vertex owner
    joint (largest skin weight)."""
    prims = fighter_prims(model)
    for p in prims:
        p["owner"] = p["J"][:, 0].copy()
    return {"joints": np.array([j["world"][:3, 3] for j in model.joints]), "parent": [j["parent"] for j in model.joints],
            "roles": body_roles(ids, len(model.joints)), "prims": prims}


# ---------------------------------------------------------------- glTF
def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgba), "RGBA").save(buf, "PNG")
    return buf.getvalue()


def _al4(n):
    return (n + 3) & -4


def write_gltf(path: Path, joints: list[dict], prims: list[dict], scale: float = 1.0, name: str = "melee",
               joint_names: list[str] | None = None, extras: dict | None = None) -> Path:
    """joints: [{parent, world (4x4)}] in rest pose; prims: [{pos, nrm, uv, tris, J (n,4), W (n,4), tex RGBA|None,
    color, wrap (s,t)}]. Writes a self-contained skinned .gltf (joint nodes with rest translations only; the mesh
    is in world rest pose with inverse bind = -joint world translation... full inverse of the joint world)."""
    blob = bytearray()
    views, accs = [], []

    def add(arr, comp, typ, target=None, minmax=False):
        nonlocal blob
        blob += bytes(_al4(len(blob)) - len(blob))
        arr = np.ascontiguousarray(arr)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, **({"target": target} if target else {})})
        blob += arr.tobytes()
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": int(len(arr)), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    names = joint_names or [f"j{i:03d}" for i in range(len(joints))]
    nodes = []
    wpos = [np.asarray(j["world"])[:3, 3] * scale for j in joints]
    for i, j in enumerate(joints):
        t = wpos[i] - (wpos[j["parent"]] if j["parent"] >= 0 else 0)
        nodes.append({"name": names[i], "translation": [float(x) for x in t]})
    for i, j in enumerate(joints):
        if j["parent"] >= 0:
            nodes[j["parent"]].setdefault("children", []).append(i)
    roots = [i for i, j in enumerate(joints) if j["parent"] < 0]
    ibm = np.zeros((len(joints), 16), np.float32)
    for i in range(len(joints)):
        m = np.eye(4, dtype=np.float32)
        m[:3, 3] = -wpos[i]
        ibm[i] = m.T.reshape(16)
    images, textures, materials, gprims, samplers = [], [], [], [], []
    seen = {}
    for p in prims:
        if not len(p["tris"]):
            continue
        attrs = {"POSITION": add((p["pos"] * scale).astype(np.float32), 5126, "VEC3", 34962, True),
                 "NORMAL": add(p["nrm"].astype(np.float32), 5126, "VEC3", 34962),
                 "TEXCOORD_0": add(p["uv"].astype(np.float32), 5126, "VEC2", 34962),
                 "JOINTS_0": add(p["J"].astype(np.uint16), 5123, "VEC4", 34962),
                 "WEIGHTS_0": add(p["W"].astype(np.float32), 5126, "VEC4", 34962)}
        ind = add(p["tris"].reshape(-1).astype(np.uint32), 5125, "SCALAR", 34963)
        col = p.get("color", (255, 255, 255, 255))
        md = {"name": p.get("name", f"mat{len(materials)}"), "doubleSided": True,
              "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.9}}
        if p.get("tex") is not None:
            pixels = np.asarray(p["tex"], dtype=np.uint8)
            wrap = tuple(p.get("wrap", (10497, 10497)))
            key = (id(p["tex"]), wrap)
            if key not in seen:
                images.append({"uri": "data:image/png;base64," + base64.b64encode(_png(pixels)).decode()})
                samplers.append({"magFilter": 9729, "minFilter": 9729, "wrapS": wrap[0], "wrapT": wrap[1]})
                textures.append({"source": len(images) - 1, "sampler": len(textures)})
                seen[key] = (len(textures) - 1, wrap)
            ti, wrap = seen[key]
            md["pbrMetallicRoughness"]["baseColorTexture"] = {"index": ti}
            alpha = pixels[..., 3]
            if (alpha < 250).any():
                md["alphaMode"] = "BLEND" if ((alpha > 0) & (alpha < 255)).any() else "MASK"
            md["pbrMetallicRoughness"]["baseColorFactor"] = [c / 255 for c in col]
        else:
            md["pbrMetallicRoughness"]["baseColorFactor"] = [c / 255 for c in col]
        materials.append(md)
        gprims.append({"attributes": attrs, "indices": ind, "material": len(materials) - 1})
    skin = {"joints": list(range(len(joints))), "inverseBindMatrices": add(ibm, 5126, "MAT4"), "skeleton": roots[0]}
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox melee_models"}, "scene": 0,
          "scenes": [{"nodes": roots + [len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": name, "primitives": gprims}], "skins": [skin], "materials": materials,
          "accessors": accs, "bufferViews": views,
          "buffers": [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," + base64.b64encode(bytes(blob)).decode()}],
          "extras": extras or {}}
    if images:
        gl.update(images=images, textures=textures, samplers=samplers)
    Path(path).write_text(json.dumps(gl))
    return Path(path)


_WRAP = {0: 33071, 1: 10497, 2: 33648}


def fighter_prims(model: Model) -> list[dict]:
    """Visible DObjs -> glTF-ready primitives (world rest pose, Melee units), up to 4 weights per vertex."""
    prims = []
    meshes = model.meshes()
    allp = np.concatenate([g["pos"] for _, _, g in meshes]) if meshes else np.zeros((1, 3))
    height = float(np.ptp(allp[:, 1])) or 1.0
    drop = set()
    for opts in getattr(model, "part_groups", [])[1:]:      # held items (clubs, swords...): long things off a hand
        o0 = set(opts[0])
        for di, mat, g in meshes:
            if di in o0:
                own = np.array([model.joints[e[0][0]]["world"][:3, 3] for e in g["env"]])
                if np.linalg.norm(g["pos"] - own, axis=1).max() > 0.3 * height:
                    drop |= o0
    for di, mat, g in meshes:
        if di in drop:
            continue
        n = len(g["pos"])
        J, W = np.zeros((n, 4), np.int64), np.zeros((n, 4))
        for k, ws in enumerate(g["env"]):
            ws = sorted(ws, key=lambda t: -t[1])[:4]
            for s, (j, w) in enumerate(ws):
                J[k, s], W[k, s] = j, w
        W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
        su, sv = mat.get("uv_scale", (1, 1))
        tu, tv = mat.get("uv_trans", (0, 0))
        uv = g["uv"] * np.array([su or 1, sv or 1]) + np.array([tu, tv])
        tex = mat["tex"]
        if tex is not None and mat["color"][3] < 255:
            pass
        prims.append({"pos": g["pos"], "nrm": g["nrm"], "uv": uv, "tris": g["tris"], "J": J, "W": W, "tex": tex,
                      "color": mat["color"], "dobj": di, "clr": g["clr"], "name": f"dobj{di:02d}"})
    return prims


def load_fighter(iso_or_dir, fighter: str, costume: str = "Nr") -> tuple[Model, dict]:
    """fighter = name from FIGHTERS ("Peach") -> (Model of Pl<code><costume>.dat high poly, joint->common names)."""
    code = CODE[fighter]
    files = {}
    names = [f"Pl{code}{costume}.dat", f"Pl{code}.dat", "PlCo.dat"]
    p = Path(iso_or_dir)
    if p.is_dir():
        for n in names:
            files[n] = (p / n).read_bytes()
    else:
        from .gcdisc import GCDisc
        d = GCDisc(p)
        try:
            for n in names:
                files[n] = d.read(n)
        finally:
            d.f.close()
    m = Model(files[names[0]], files[names[1]])
    return m, bone_table(files["PlCo.dat"], fighter)


def export_fighter(iso_or_dir, fighter: str, out: Path, costume: str = "Nr", scale: float = 0.1) -> dict:
    """Write <out> (.gltf) for a fighter: skinned to its own joints, joint nodes named j<idx>_<CommonName>."""
    m, bones = load_fighter(iso_or_dir, fighter, costume)
    prims = fighter_prims(m)
    names = [f"j{i:03d}" + (f"_{bones[i]}" if i in bones else "") for i in range(len(m.joints))]
    write_gltf(out, m.joints, prims, scale, fighter, names, {"melee_fighter": fighter, "costume": costume})
    allp = np.concatenate([p["pos"] for p in prims])
    return {"fighter": fighter, "joints": len(m.joints), "dobjs": len(m.dobjs), "visible": len(m.visible),
            "prims": len(prims), "tris": int(sum(len(p["tris"]) for p in prims)),
            "verts": int(sum(len(p["pos"]) for p in prims)), "height": float(np.ptp(allp[:, 1])), "path": str(out)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src", help="Melee disc image (ISO) or a folder with the Pl*.dat files")
    ap.add_argument("fighter", nargs="?", default="Peach")
    ap.add_argument("--out", default=".")
    ap.add_argument("--costume", default="Nr")
    a = ap.parse_args()
    fs = PLAYABLE if a.fighter == "all" else [a.fighter]
    for f in fs:
        print(export_fighter(a.src, f, Path(a.out) / f"melee_{f}.gltf", a.costume))
