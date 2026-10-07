"""Resident Evil 4 (GameCube, G4BE08) character models: read + write, glTF export/import.

Formats (reverse-engineered by gBox from the NTSC-U disc, see the KB entry "RE4 GC model formats"):

  em/plXX.drs  UDAS container. 0x20 bytes of 0xCAB6BE20 fill, then 32-byte entries (type u32, size u32, 0, offset u32,
               16 more bytes) ended by 0xFFFFFFFF; data starts at 0x400. Entry type 0 = a DAT (the model pack), type 4 =
               sound (another UDAS). pl00 = Leon (chapter 1 jacket), pl08/pl09 = other Leon costumes.
  DAT          u32 count, 12 pad, count x u32 offsets, count x 4-char extension ("BIN", "TPL", "FCV", "SEQ", "EFF", or
               0 = empty slot), entries 32-aligned.
  BIN          big-endian mesh. Header (0x60 skinned, 0x40 rigid):
                 0x00 bones off (= header size)  0x08 extra off (inside header)  0x0C vertex colours (RGBA8) off
                 0x10 uvs off (s16 pairs, frac = byte 0x3E)  0x14 weights off  0x18 u8 #weights  0x19 u8 #bones
                 0x1A u16 #materials  0x1C materials off  0x24 #textures  0x28 u8 position frac bits
                 0x2C morph off (raw)  0x30 positions off  0x34 normals off  0x38 u16 #pos  0x3A u16 #nrm
                 0x3C attr fmt bytes  0x40, 0x44 tables (raw; per-bone/IK data)
               bone   16 B: u8 id, u8 parent (0xFF root), 2 pad, 3 x f32 translation relative to parent (bind = no rot)
               pos    s16 x, y, z, weight index (model space, bind pose)
               nrm    s8 x, y, z, u8 weight index
               weight 8 B: bone0, bone1, bone2, count, w0, w1, w2 (percent), pad
               material 0x20 header (0x0C tex index into the paired TPL, 0x18 DL size (32-aligned), 0x1C tri count)
                 + GX display list: 0x98 strip / 0x90 triangles / 0x80 quads, u16 count, per vertex u16 pos, nrm,
                 colour, uv index. The game skins on the CPU from the weight index, so any topology works.
  TPL          standard GameCube TPL (magic 0x0020AF30): CMPR / IA8 / I4 ... here.

Used by the model-swap pipeline: Leon -> glTF (mesh, weights, bones, textures); glTF (rigged to Leon's bones, named
"b<id>") -> BIN + TPL -> DAT -> DRS -> disc copy (filemods.build_image).
"""
from __future__ import annotations

import base64
import io
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

UDAS_FILL = b"\xca\xb6\xbe\x20" * 8
PAD = bytes([0xCD])                                      # BIN end-of-file fill


def _al(n: int, a: int = 32) -> int:
    return (n + a - 1) & -a


# ---------------------------------------------------------------- containers

def udas_read(data: bytes) -> list[dict]:
    """[{type, entry (32 raw bytes), data}] for a UDAS (.drs/.udas)."""
    out, o = [], 0x20
    while struct.unpack_from(">I", data, o)[0] != 0xFFFFFFFF:
        t, size, _u, off = struct.unpack_from(">IIII", data, o)
        out.append({"type": t, "entry": data[o:o + 32], "data": data[off:off + size]})
        o += 32
    return out


def udas_write(entries: list[dict], fill: bytes = UDAS_FILL) -> bytes:
    hdr = bytearray(fill[:0x20])
    off = 0x400
    for e in entries:
        ent = bytearray(e["entry"])
        struct.pack_into(">II", ent, 4, len(e["data"]), 0)
        struct.pack_into(">I", ent, 12, off)
        hdr += ent
        off += len(e["data"])
    hdr += b"\xff\xff\xff\xff"
    hdr += bytes(0x400 - len(hdr))
    return bytes(hdr) + b"".join(e["data"] for e in entries)


def dat_read(data: bytes) -> list[tuple[str, bytes]]:
    """[(ext, bytes)]; if the header's u32 at 4 is set, the data from there to the end (a block not in the table) is
    returned as a last pseudo-entry ("@tail", bytes)."""
    n, tail = struct.unpack_from(">II", data, 0)
    end = tail or len(data)
    offs = list(struct.unpack_from(f">{n}I", data, 16)) + [end]
    exts = [data[16 + 4 * n + 4 * i:16 + 4 * n + 4 * i + 4].rstrip(b"\0").decode("latin-1") for i in range(n)]
    out = []
    for i in range(n):
        e = next((o for o in offs[i + 1:] if o >= offs[i]), end)
        out.append((exts[i], data[offs[i]:e] if exts[i] else b""))
    if tail:
        out.append(("@tail", data[tail:]))
    return out


def dat_write(items: list[tuple[str, bytes]]) -> bytes:
    tail = items[-1][1] if items and items[-1][0] == "@tail" else None
    if tail is not None:
        items = items[:-1]
    n = len(items)
    head = 16 + 8 * n
    off = _al(head)
    offs, body = [], bytearray()
    for ext, d in items:
        offs.append(off + len(body))
        body += d + bytes(_al(len(d)) - len(d))
    tail_off = off + len(body) if tail is not None else 0
    if tail is not None:
        body += tail
    h = struct.pack(">II8x", n, tail_off) + struct.pack(f">{n}I", *offs) + b"".join(e.encode().ljust(4, b"\0") for e, _ in items)
    return h + bytes(off - len(h)) + bytes(body)


# ---------------------------------------------------------------- TPL textures

def _blocks(w, h, bw, bh):
    for by in range(0, h, bh):
        for bx in range(0, w, bw):
            yield bx, by


def _rgb565(c):
    return np.stack([((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31], -1)


def tpl_decode_image(fmt: int, w: int, h: int, d: bytes) -> np.ndarray:
    """-> RGBA uint8 (h, w, 4)."""
    img = np.zeros((_al(h, 8), _al(w, 8), 4), np.uint8)
    p = 0
    if fmt == 14:                                          # CMPR: 8x8 tiles of 4 DXT1 sub-blocks
        for bx, by in _blocks(w, h, 8, 8):
            for sy in (0, 4):
                for sx in (0, 4):
                    c0, c1, bits = struct.unpack_from(">HHI", d, p)
                    p += 8
                    a, b = _rgb565(np.array(c0)), _rgb565(np.array(c1))
                    pal = [np.append(a, 255), np.append(b, 255)]
                    if c0 > c1:
                        pal += [np.append((2 * a + b) // 3, 255), np.append((a + 2 * b) // 3, 255)]
                    else:
                        pal += [np.append((a + b) // 2, 255), np.array([0, 0, 0, 0])]
                    for i in range(16):
                        img[by + sy + i // 4, bx + sx + i % 4] = pal[(bits >> (30 - 2 * i)) & 3]
    elif fmt in (0, 1, 2, 3, 4, 5, 6):
        bw, bh = {0: (8, 8), 1: (8, 4), 2: (8, 4), 3: (4, 4), 4: (4, 4), 5: (4, 4), 6: (4, 4)}[fmt]
        img = np.zeros((_al(h, bh), _al(w, bw), 4), np.uint8)
        for bx, by in _blocks(w, h, bw, bh):
            if fmt == 6:                                   # RGBA8: AR block then GB block
                ar, gb = d[p:p + 32], d[p + 32:p + 64]
                p += 64
                for i in range(16):
                    img[by + i // 4, bx + i % 4] = (ar[2 * i + 1], gb[2 * i], gb[2 * i + 1], ar[2 * i])
                continue
            for i in range(bw * bh):
                y, x = by + i // bw, bx + i % bw
                if fmt == 0:
                    v = (d[p + i // 2] >> (4 if i % 2 == 0 else 0)) & 15
                    img[y, x] = (v * 17,) * 4
                elif fmt == 1:
                    img[y, x] = (d[p + i],) * 4
                elif fmt == 2:
                    v = d[p + i]
                    img[y, x] = ((v & 15) * 17,) * 3 + ((v >> 4) * 17,)
                elif fmt == 3:
                    img[y, x] = (d[p + 2 * i + 1],) * 3 + (d[p + 2 * i],)
                else:
                    c = struct.unpack_from(">H", d, p + 2 * i)[0]
                    if fmt == 4:
                        img[y, x] = (*_rgb565(np.array(c)), 255)
                    elif c & 0x8000:
                        img[y, x] = (((c >> 10) & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31, (c & 31) * 255 // 31, 255)
                    else:
                        img[y, x] = (((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17, ((c >> 12) & 7) * 255 // 7)
            p += {0: 32, 1: 32, 2: 32}.get(fmt, 32)
    else:
        raise ValueError(f"TPL format {fmt} not supported")
    return img[:h, :w]


def _to565(c):
    c = np.clip(c, 0, 255).astype(int)
    return ((c[..., 0] * 31 + 127) // 255) << 11 | ((c[..., 1] * 63 + 127) // 255) << 5 | ((c[..., 2] * 31 + 127) // 255)


def cmpr_encode(img: np.ndarray) -> bytes:
    """RGBA (h, w, 4) -> CMPR. Endpoints = extremes along the block's principal axis; alpha < 128 -> transparent."""
    h, w = img.shape[:2]
    pad = np.zeros((_al(h, 8), _al(w, 8), 4), np.uint8)
    pad[:h, :w] = img
    out = bytearray()
    for bx, by in _blocks(w, h, 8, 8):
        for sy in (0, 4):
            for sx in (0, 4):
                blk = pad[by + sy:by + sy + 4, bx + sx:bx + sx + 4].reshape(16, 4).astype(float)
                rgb, transp = blk[:, :3], blk[:, 3] < 128
                src = rgb[~transp] if (~transp).any() else rgb
                mean = src.mean(0)
                u, s, vt = np.linalg.svd(src - mean, full_matrices=False) if len(src) > 1 else (None, None, np.eye(3))
                t = (src - mean) @ vt[0]
                a, b = mean + vt[0] * t.max(), mean + vt[0] * t.min()
                c0, c1 = int(_to565(a)), int(_to565(b))
                if transp.any():
                    if c0 > c1:
                        c0, c1 = c1, c0
                    pal = [_rgb565(np.array(c0)), _rgb565(np.array(c1))]
                    pal += [(pal[0] + pal[1]) // 2]
                    idx = [3 if tr else int(np.argmin([((px - q) ** 2).sum() for q in pal])) for px, tr in zip(rgb, transp)]
                else:
                    if c0 < c1:
                        c0, c1 = c1, c0
                    if c0 == c1:
                        idx = [0] * 16
                    else:
                        A, B = _rgb565(np.array(c0)), _rgb565(np.array(c1))
                        pal = np.array([A, B, (2 * A + B) // 3, (A + 2 * B) // 3], float)
                        idx = list(((rgb[:, None, :] - pal[None]) ** 2).sum(-1).argmin(1))
                bits = 0
                for i, v in enumerate(idx):
                    bits |= int(v) << (30 - 2 * i)
                out += struct.pack(">HHI", c0, c1, bits)
    return bytes(out)


@dataclass
class TplImage:
    w: int
    h: int
    fmt: int
    data: bytes
    hdr: bytes                    # 0x24-byte image header (wrap/filter/LOD kept)

    def rgba(self) -> np.ndarray:
        return tpl_decode_image(self.fmt, self.w, self.h, self.data)


def tpl_read(b: bytes) -> list[TplImage]:
    n, to = struct.unpack_from(">II", b, 4)
    hdrs = [struct.unpack_from(">II", b, to + 8 * i)[0] for i in range(n)]
    datas = sorted(struct.unpack_from(">I", b, h + 8)[0] for h in hdrs) + [len(b)]
    out = []
    for io_ in hdrs:
        h, w, fmt, do = struct.unpack_from(">HHII", b, io_)
        end = next(x for x in datas if x > do)           # includes mipmaps
        out.append(TplImage(w, h, fmt, b[do:end], b[io_:io_ + 0x24]))
    return out


def tpl_write(imgs: list[TplImage]) -> bytes:
    n = len(imgs)
    tab = 12
    hdrs = tab + 8 * n
    data_start = _al(hdrs + 0x24 * n)
    out = bytearray(struct.pack(">III", 0x0020AF30, n, 12))
    body, offs = bytearray(), []
    for im in imgs:
        offs.append(data_start + len(body))
        body += im.data + bytes(_al(len(im.data), 32) - len(im.data))
    for i in range(n):
        out += struct.pack(">II", hdrs + 0x24 * i, 0)
    out += bytes(hdrs - len(out))
    for im, o in zip(imgs, offs):
        h = bytearray(im.hdr.ljust(0x24, b"\0"))
        struct.pack_into(">HHII", h, 0, im.h, im.w, im.fmt, o)
        out += h
    out += bytes(data_start - len(out))
    return bytes(out + body)


def tpl_image_from_rgba(rgba: np.ndarray, template_hdr: bytes | None = None) -> TplImage:
    h, w = rgba.shape[:2]
    hdr = template_hdr or struct.pack(">HHII5I", h, w, 14, 0, 1, 1, 1, 1, 0)
    return TplImage(w, h, 14, cmpr_encode(rgba), hdr[:0x24])


# ---------------------------------------------------------------- BIN meshes

OFF_FIELDS = {0x00: "bones", 0x0C: "colors", 0x10: "uvs", 0x14: "weights", 0x1C: "mats", 0x2C: "morph",
              0x30: "pos", 0x34: "nrm", 0x40: "tabA", 0x44: "tabB"}


@dataclass
class Material:
    hdr: bytes                                   # 0x20 raw header
    prims: list                                  # [(cmd, [(p, n, c, t), ...])]

    @property
    def tex(self) -> int:
        return self.hdr[0x0C]

    def triangles(self):
        for cmd, vs in self.prims:
            if cmd == 0x98:
                for i in range(len(vs) - 2):
                    yield (vs[i], vs[i + 1], vs[i + 2]) if i % 2 == 0 else (vs[i + 1], vs[i], vs[i + 2])
            elif cmd == 0x90:
                for i in range(0, len(vs) - 2, 3):
                    yield vs[i], vs[i + 1], vs[i + 2]
            elif cmd == 0x80:
                for i in range(0, len(vs) - 3, 4):
                    yield vs[i], vs[i + 1], vs[i + 2]
                    yield vs[i], vs[i + 2], vs[i + 3]
            elif cmd == 0xA0:
                for i in range(1, len(vs) - 1):
                    yield vs[0], vs[i], vs[i + 1]


@dataclass
class Bin:
    header: bytearray
    raw: dict = field(default_factory=dict)      # section name -> raw bytes (sections we don't decode)
    order: list = field(default_factory=list)    # section names in file order
    bones: list = field(default_factory=list)    # [(id, parent, pad2, x, y, z)]
    pos: np.ndarray | None = None                # (n, 3) float model units
    pos_w: np.ndarray | None = None              # (n,) weight index
    nrm: np.ndarray | None = None                # (n, 3) int8
    nrm_w: np.ndarray | None = None
    colors: list = field(default_factory=list)   # [(r, g, b, a)]
    uvs: np.ndarray | None = None                # (n, 2) float
    weights: list = field(default_factory=list)  # [(b0, b1, b2, cnt, w0, w1, w2, pad)]
    mats: list = field(default_factory=list)
    nrm16: bool = False

    # header fields
    def u32(self, o):
        return struct.unpack_from(">I", self.header, o)[0]

    @property
    def pos_shift(self):
        return self.header[0x28]

    @property
    def uv_shift(self):
        return self.header[0x3E]

    def bone_world(self) -> dict[int, np.ndarray]:
        w = {}
        for bid, par, _p, x, y, z in self.bones:
            w[bid] = w.get(par, np.zeros(3)) + np.array([x, y, z]) if par != 0xFF else np.array([x, y, z])
        return w


def bin_read(b: bytes) -> Bin:
    hsz = struct.unpack_from(">I", b, 0)[0]
    m = Bin(bytearray(b[:hsz]))
    offs = {name: m.u32(o) for o, name in OFF_FIELDS.items() if o + 4 <= hsz and m.u32(o)}
    starts = sorted(set(offs.values())) + [len(b)]
    ext = {name: (o, starts[starts.index(o) + 1]) for name, o in offs.items()}
    m.order = sorted(offs, key=lambda k: offs[k])
    nw, nb = b[0x18], b[0x19]
    nm = struct.unpack_from(">H", b, 0x1A)[0]
    npos, nnrm = struct.unpack_from(">HH", b, 0x38)
    o = offs["bones"]
    for i in range(nb):
        bid, par, pad = struct.unpack_from(">BB2s", b, o + 16 * i)
        m.bones.append((bid, par, pad, *struct.unpack_from(">3f", b, o + 16 * i + 4)))
    p = np.frombuffer(b, ">i2", npos * 4, offs["pos"]).reshape(-1, 4).astype(np.int32)
    m.pos, m.pos_w = p[:, :3] / float(1 << m.pos_shift), p[:, 3].copy()
    a, e = ext["nrm"]
    m.nrm16 = e - a >= 8 * nnrm                    # rigid BINs: s16 normals (frac 14); skinned: s8 + u8 weight index
    if m.nrm16:
        nr = np.frombuffer(b, ">i2", nnrm * 4, a).reshape(-1, 4).astype(np.int32)
        m.nrm, m.nrm_w = nr[:, :3] // 129, nr[:, 3].copy()
        m.raw["_nrm16"] = b[a:a + 8 * nnrm]
    else:
        nr = np.frombuffer(b, np.uint8, nnrm * 4, a).reshape(-1, 4)
        m.nrm, m.nrm_w = nr[:, :3].astype(np.int8).astype(np.int32), nr[:, 3].astype(np.int32)
    if "colors" in offs:
        a, e = ext["colors"]
        m.colors = [tuple(b[a + 4 * i:a + 4 * i + 4]) for i in range((e - a) // 4)]
    a, e = ext["uvs"]
    m.uvs = np.frombuffer(b, ">i2", ((e - a) // 4) * 2, a).reshape(-1, 2) / float(1 << m.uv_shift)
    o = offs["weights"]
    m.weights = [tuple(b[o + 8 * i:o + 8 * i + 8]) for i in range(nw)]
    o = offs["mats"]
    for _ in range(nm):
        hdr = b[o:o + 0x20]
        sz = struct.unpack_from(">I", hdr, 0x18)[0]
        dl, p_, prims = b[o + 0x20:o + 0x20 + sz], 0, []
        while p_ < len(dl):
            cmd = dl[p_]
            if cmd == 0:
                p_ += 1
                continue
            n = struct.unpack_from(">H", dl, p_ + 1)[0]
            vs = [tuple(v) for v in np.frombuffer(dl, ">u2", n * 4, p_ + 3).reshape(-1, 4).tolist()]
            prims.append((cmd, vs))
            p_ += 3 + 8 * n
        m.mats.append(Material(hdr, prims))
        o += 0x20 + sz
    for name in m.order:
        if name in ("morph", "tabA", "tabB"):
            a, e = ext[name]
            raw = b[a:e]
            if e == len(b):                                # trailing 0xCD fill isn't part of the table
                raw = raw.rstrip(PAD)
                raw += PAD * ((-len(raw)) % 2)        # keep u16 alignment if a value ended in 0xCD
            m.raw[name] = raw
    return m


def _tri_count(prims) -> int:
    n = 0
    for cmd, vs in prims:
        n += len(vs) - 2 if cmd in (0x98, 0xA0) else (len(vs) // 3 if cmd == 0x90 else len(vs) // 4 * 2)
    return n


def bin_write(m: Bin) -> bytes:
    h = bytearray(m.header)
    out = bytearray(h)
    secs = {}
    sec = {}
    sh = m.pos_shift
    p = np.round(m.pos * (1 << sh)).astype(np.int64)
    if np.abs(p).max(initial=0) > 32767:
        raise ValueError(f"positions overflow s16 at frac {sh} bits (max {np.abs(m.pos).max():.1f}); lower header 0x28")
    sec["pos"] = np.concatenate([p, m.pos_w[:, None]], 1).astype(">i2").tobytes()
    sec["nrm"] = m.raw["_nrm16"] if m.nrm16 and "_nrm16" in m.raw else np.concatenate([m.nrm.astype(np.int8).view(np.uint8).reshape(-1, 3),
                                 m.nrm_w.astype(np.uint8)[:, None]], 1).astype(np.uint8).tobytes()
    sec["bones"] = b"".join(struct.pack(">BB2s3f", bid, par, pad, x, y, z) for bid, par, pad, x, y, z in m.bones)
    sec["colors"] = b"".join(bytes(c) for c in m.colors)
    sec["uvs"] = np.round(m.uvs * (1 << m.uv_shift)).astype(">i2").tobytes()
    sec["weights"] = b"".join(bytes(w) for w in m.weights)
    mb = bytearray()
    for mat in m.mats:
        dl = bytearray()
        for cmd, vs in mat.prims:
            dl += struct.pack(">BH", cmd, len(vs)) + np.array(vs, ">u2").tobytes()
        dl += bytes(_al(len(dl)) - len(dl))
        mh = bytearray(mat.hdr)
        struct.pack_into(">II", mh, 0x18, len(dl), _tri_count(mat.prims))
        mb += mh + dl
    sec["mats"] = bytes(mb)
    sec.update(m.raw)
    for name in m.order:
        out += bytes((_al(len(out), 4) if name == "tabB" else _al(len(out))) - len(out))
        secs[name] = len(out)
        out += sec[name]
    out += PAD * (_al(len(out)) - len(out))
    for o, name in OFF_FIELDS.items():
        if name in secs and o + 4 <= len(h):
            struct.pack_into(">I", out, o, secs[name])
    out[0x18], out[0x19] = len(m.weights), len(m.bones)
    struct.pack_into(">H", out, 0x1A, len(m.mats))
    struct.pack_into(">HH", out, 0x38, len(m.pos), len(m.nrm))
    if out[0x28] != sh:
        out[0x28] = sh
    if struct.unpack_from(">H", h, 0x2A)[0] == h[0x18]:      # some BINs keep the weight count here too
        struct.pack_into(">H", out, 0x2A, len(m.weights))
    return bytes(out)


# ---------------------------------------------------------------- model pack (a .drs)

class ModelPack:
    """One em/plXX.drs: its DAT entries + the other UDAS entries kept raw."""

    def __init__(self, drs: bytes):
        self.udas = udas_read(drs)
        self.fill = drs[:0x20]
        self.dat_i = next(i for i, e in enumerate(self.udas) if e["type"] == 0)
        self.items = dat_read(self.udas[self.dat_i]["data"])

    def bins(self) -> list[int]:
        return [i for i, (e, _) in enumerate(self.items) if e == "BIN"]

    def tpl_for(self, i: int) -> int | None:
        """The TPL a BIN's texture indices refer to: the next TPL in the DAT with the BIN's texture count, else the
        nearest TPL after it, else before it."""
        ntex = struct.unpack_from(">I", self.items[i][1], 0x24)[0]
        tpls = [j for j, (e, _) in enumerate(self.items) if e == "TPL"]
        same = [j for j in tpls if struct.unpack_from(">I", self.items[j][1], 4)[0] == ntex]
        for j in [j for j in same if j > i] + [j for j in reversed(same) if j < i]:
            return j
        after = [j for j in tpls if j > i]
        before = [j for j in tpls if j < i]
        return after[0] if after else (before[-1] if before else None)

    def to_bytes(self) -> bytes:
        ud = [dict(e) for e in self.udas]
        ud[self.dat_i]["data"] = dat_write(self.items)
        return udas_write(ud, self.fill)


# ---------------------------------------------------------------- glTF

def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG")
    return buf.getvalue()


def bin_to_gltf(m: Bin, textures: list[np.ndarray] | None, path: Path, scale: float = 0.001, name: str = "re4"):
    """Write a self-contained .gltf (buffers + PNGs embedded as data URIs): skinned mesh (one primitive per material),
    skeleton nodes named b<id> with translations, inverse bind matrices; RE4 units * scale (mm -> m)."""
    bw = m.bone_world()
    ids = [b[0] for b in m.bones]
    jidx = {bid: k for k, bid in enumerate(ids)}
    blob = bytearray()
    views, accs = [], []

    def add(arr: np.ndarray, comp: int, typ: str, target=None, minmax=False):
        nonlocal blob
        blob += bytes(_al(len(blob), 4) - len(blob))
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, **({"target": target} if target else {})})
        blob += arr.tobytes()
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    prims, materials, images, gtex = [], [], [], []
    tex_map = {}
    for mi, mat in enumerate(m.mats):
        corners = {}
        idx = []
        for tri in mat.triangles():
            for c in tri:
                if c not in corners:
                    corners[c] = len(corners)
                idx.append(corners[c])
        if not idx:
            continue
        cl = list(corners)
        P = np.array([m.pos[c[0]] for c in cl], np.float32) * scale
        N = np.array([m.nrm[c[1]] for c in cl], np.float32)
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-6)
        UV = np.array([m.uvs[c[3]] if c[3] < len(m.uvs) else (0, 0) for c in cl], np.float32)
        J = np.zeros((len(cl), 4), np.uint16)
        W = np.zeros((len(cl), 4), np.float32)
        for k, c in enumerate(cl):
            w = m.weights[m.pos_w[c[0]]]
            for s in range(min(w[3], 3)):
                J[k, s], W[k, s] = jidx.get(w[s], 0), w[4 + s] / 100.0
        W /= np.maximum(W.sum(1, keepdims=True), 1e-6)
        attrs = {"POSITION": add(P, 5126, "VEC3", 34962, True), "NORMAL": add(N, 5126, "VEC3", 34962),
                 "TEXCOORD_0": add(UV, 5126, "VEC2", 34962), "JOINTS_0": add(J, 5123, "VEC4", 34962),
                 "WEIGHTS_0": add(W, 5126, "VEC4", 34962)}
        if c and len(m.colors) and any(c[2] for c in cl):
            pass
        ind = add(np.array(idx, np.uint32), 5125, "SCALAR", 34963)
        t = mat.tex
        mdef = {"name": f"mat{mi:02d}_tex{t}", "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.9},
                "extras": {"re4_header": mat.hdr.hex()}}
        if textures and t < len(textures):
            if t not in tex_map:
                images.append({"uri": "data:image/png;base64," + base64.b64encode(_png(textures[t])).decode(), "name": f"tex{t}"})
                gtex.append({"source": len(images) - 1, "sampler": 0})
                tex_map[t] = len(gtex) - 1
            mdef["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex_map[t]}
            if (textures[t][..., 3] < 250).any():
                mdef["alphaMode"] = "MASK"
        materials.append(mdef)
        prims.append({"attributes": attrs, "indices": ind, "material": len(materials) - 1})

    nodes = []
    for bid, par, _p, x, y, z in m.bones:
        nodes.append({"name": f"b{bid:03d}", "translation": [x * scale, y * scale, z * scale]})
    for k, (bid, par, *_r) in enumerate(m.bones):
        if par != 0xFF and par in jidx:
            nodes[jidx[par]].setdefault("children", []).append(k)
    roots = [k for k, (bid, par, *_r) in enumerate(m.bones) if par == 0xFF or par not in jidx]
    ibm = np.zeros((len(ids), 16), np.float32)
    for k, bid in enumerate(ids):
        mtx = np.eye(4, dtype=np.float32)
        mtx[:3, 3] = -bw[bid] * scale
        ibm[k] = mtx.T.reshape(16)                       # glTF is column-major
    skin = {"joints": list(range(len(ids))), "inverseBindMatrices": add(ibm, 5126, "MAT4"), "skeleton": roots[0]}
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox re4gc_models"},
          "scene": 0, "scenes": [{"nodes": roots + [len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": name, "primitives": prims}], "skins": [skin], "materials": materials,
          "accessors": accs, "bufferViews": views,
          "buffers": [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," + base64.b64encode(bytes(blob)).decode()}],
          "extras": {"re4_pos_shift": m.pos_shift, "re4_scale": scale}}
    if images:
        gl.update(images=images, textures=gtex, samplers=[{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}])
    Path(path).write_text(json.dumps(gl))
    return path


def _gltf_load(path: Path):
    gl = json.loads(Path(path).read_text()) if str(path).endswith(".gltf") else None
    if gl is None:                                       # .glb
        d = Path(path).read_bytes()
        jl = struct.unpack_from("<I", d, 12)[0]
        gl = json.loads(d[20:20 + jl])
        bins = [d[20 + jl + 8:]]
    else:
        bins = []
        for b in gl["buffers"]:
            u = b["uri"]
            bins.append(base64.b64decode(u.split(",", 1)[1]) if u.startswith("data:") else (Path(path).parent / u).read_bytes())
    comp = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    def acc(i):
        a = gl["accessors"][i]
        v = gl["bufferViews"][a["bufferView"]]
        dt, nc = np.dtype(comp[a["componentType"]]), ncomp[a["type"]]
        stride = v.get("byteStride", dt.itemsize * nc)
        base = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        raw = bins[v["buffer"]]
        if stride == dt.itemsize * nc:
            arr = np.frombuffer(raw, dt, a["count"] * nc, base).reshape(a["count"], nc)
        else:
            arr = np.stack([np.frombuffer(raw, dt, nc, base + k * stride) for k in range(a["count"])])
        if a.get("normalized") and dt.kind in "ui":
            arr = arr / float(np.iinfo(dt).max)
        return arr

    def image(ti):
        from PIL import Image
        src = gl["images"][gl["textures"][ti]["source"]]
        if "uri" in src:
            u = src["uri"]
            data = base64.b64decode(u.split(",", 1)[1]) if u.startswith("data:") else (Path(path).parent / u).read_bytes()
        else:
            v = gl["bufferViews"][src["bufferView"]]
            data = bins[v["buffer"]][v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]]
        return np.array(Image.open(io.BytesIO(data)).convert("RGBA"))
    return gl, acc, image


def _node_world(gl):
    """World matrices of all nodes (TRS / matrix)."""
    from math import isclose  # noqa: F401
    n = len(gl["nodes"])
    parent = {}
    for i, nd in enumerate(gl["nodes"]):
        for c in nd.get("children", []):
            parent[c] = i

    def local(nd):
        if "matrix" in nd:
            return np.array(nd["matrix"], float).reshape(4, 4).T
        t = np.eye(4)
        t[:3, 3] = nd.get("translation", [0, 0, 0])
        x, y, z, w = nd.get("rotation", [0, 0, 0, 1])
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        s = np.diag(nd.get("scale", [1, 1, 1]))
        m = np.eye(4)
        m[:3, :3] = r @ s
        return t @ m
    cache = {}

    def world(i):
        if i not in cache:
            cache[i] = (world(parent[i]) if i in parent else np.eye(4)) @ local(gl["nodes"][i])
        return cache[i]
    return [world(i) for i in range(n)]


def gltf_to_bin(gltf_path: Path, template: Bin, scale: float = 0.001, max_tex: int = 256,
                pos_shift: int | None = None) -> tuple[Bin, list[np.ndarray]]:
    """A skinned glTF whose joints are named b<id> (RE4 bone ids of the template) -> a new BIN on the template's
    skeleton + its textures (RGBA, one per glTF material, resized to <= max_tex, power of two).
    Vertex positions are taken in bind pose (skin applied with the glTF's inverse bind matrices so any rest pose of
    the source is baked to the template skeleton)."""
    from PIL import Image
    gl, acc, image = _gltf_load(gltf_path)
    world = _node_world(gl)
    tb = {b[0] for b in template.bones}
    m = Bin(bytearray(template.header), raw=dict(template.raw), order=list(template.order), bones=list(template.bones),
            colors=[(255, 255, 255, 255)])
    P, PW, N, NW, UV, mats, texs = [], [], [], [], [], [], []
    wtab: dict[tuple, int] = {}
    pkey: dict[tuple, int] = {}
    nkey: dict[tuple, int] = {}
    uvkey: dict[tuple, int] = {}
    mat_tex: dict[int, int] = {}
    tex_of: dict[tuple, int] = {}
    for ni, nd in enumerate(gl["nodes"]):
        if "mesh" not in nd:
            continue
        skin = gl["skins"][nd["skin"]] if "skin" in nd else None
        jnames = [gl["nodes"][j].get("name", "") for j in skin["joints"]] if skin else []
        jbone = [int(n[1:]) if n[:1] == "b" and n[1:].isdigit() and int(n[1:]) in tb else None for n in jnames]
        ibm = acc(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1) if skin and "inverseBindMatrices" in skin else None
        jw = [world[j] for j in skin["joints"]] if skin else []
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            a = pr["attributes"]
            pos = acc(a["POSITION"]).astype(float)
            nrm = acc(a["NORMAL"]).astype(float) if "NORMAL" in a else np.tile([0, 1.0, 0], (len(pos), 1))
            uv = acc(a["TEXCOORD_0"]).astype(float) if "TEXCOORD_0" in a else np.zeros((len(pos), 2))
            idx = acc(pr["indices"]).reshape(-1) if "indices" in pr else np.arange(len(pos))
            if skin and "JOINTS_0" in a:
                J, W = acc(a["JOINTS_0"]).astype(int), acc(a["WEIGHTS_0"]).astype(float)
                # skinned bind-pose position = sum w * (jointWorld @ ibm) @ v
                ph = np.c_[pos, np.ones(len(pos))]
                outp, outn = np.zeros((len(pos), 3)), np.zeros((len(pos), 3))
                for k in range(4):
                    mats_k = np.stack([jw[j] @ (ibm[j] if ibm is not None else np.eye(4)) for j in J[:, k]])
                    outp += W[:, k:k + 1] * np.einsum("nij,nj->ni", mats_k, ph)[:, :3]
                    outn += W[:, k:k + 1] * np.einsum("nij,nj->ni", mats_k[:, :3, :3], nrm)
                pos, nrm = outp, outn
            else:
                wm = world[ni]
                pos = (np.c_[pos, np.ones(len(pos))] @ wm.T)[:, :3]
                nrm = nrm @ wm[:3, :3].T
                J, W = None, None
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
            # weights -> RE4 (<=3 bones, percent)
            vw = []
            for k in range(len(pos)):
                if J is None:
                    ws = [(nd.get("extras", {}).get("re4_bone", 0), 1.0)]
                else:
                    ws = sorted(((jbone[J[k, s]], W[k, s]) for s in range(4) if W[k, s] > 0 and jbone[J[k, s]] is not None),
                                key=lambda t: -t[1])
                    merged = {}
                    for bb, ww in ws:
                        merged[bb] = merged.get(bb, 0) + ww
                    ws = sorted(merged.items(), key=lambda t: -t[1])[:3] or [(template.bones[0][0], 1.0)]
                tot = sum(w for _, w in ws)
                pc = [int(round(100 * w / tot)) for _, w in ws]
                pc[0] += 100 - sum(pc)
                key = tuple(b for b, _ in ws) + (0,) * (3 - len(ws)) + (len(ws),) + tuple(pc) + (0,) * (3 - len(pc)) + (0,)
                if key not in wtab:
                    wtab[key] = len(wtab)
                vw.append(wtab[key])
            # material / texture
            gm = pr.get("material")
            md = gl["materials"][gm] if gm is not None and gl.get("materials") else {}
            bct = md.get("pbrMetallicRoughness", {}).get("baseColorTexture")
            pbr = md.get("pbrMetallicRoughness", {})
            tkey = ("img", gl["textures"][bct["index"]]["source"], str(pbr.get("baseColorFactor"))) if bct is not None else ("mat", gm)
            if tkey not in tex_of:
                img = image(bct["index"]) if bct is not None else None
                if img is None:
                    col = md.get("pbrMetallicRoughness", {}).get("baseColorFactor", [0.8, 0.8, 0.8, 1])
                    img = np.tile(np.array([int(c * 255) for c in col], np.uint8), (8, 8, 1))
                else:
                    fac = md.get("pbrMetallicRoughness", {}).get("baseColorFactor")
                    if fac:
                        img = np.clip(img * np.array(fac), 0, 255).astype(np.uint8)
                h, w = img.shape[:2]
                tw = min(max_tex, 1 << max(3, (w - 1).bit_length()))
                th = min(max_tex, 1 << max(3, (h - 1).bit_length()))
                if (tw, th) != (w, h):
                    img = np.array(Image.fromarray(img).resize((tw, th), Image.LANCZOS))
                texs.append(img)
                tex_of[tkey] = len(texs) - 1
            if gm not in mat_tex:
                mat_tex[gm] = len(mats)
                # a plain single-texture material of the template (no bump / second texture slot)
                mh = bytearray(next((mm.hdr for mm in template.mats if mm.hdr[0x0D] == 0xFF), template.mats[0].hdr))
                mh[0x0C] = tex_of[tkey]
                mats.append(Material(bytes(mh), []))
            mat = mats[mat_tex[gm]]
            corners = []
            for k in range(len(pos)):
                p = tuple(np.round(pos[k] / scale * 16).astype(int)) + (vw[k],)
                if p not in pkey:
                    pkey[p] = len(P)
                    P.append(pos[k] / scale)
                    PW.append(vw[k])
                q = tuple(np.clip(np.round(nrm[k] * 127), -127, 127).astype(int)) + (vw[k],)
                if q not in nkey:
                    nkey[q] = len(N)
                    N.append(q[:3])
                    NW.append(vw[k])
                t = (round(float(uv[k, 0]) * 1024), round(float(uv[k, 1]) * 1024))
                if t not in uvkey:
                    uvkey[t] = len(UV)
                    UV.append(uv[k])
                corners.append((pkey[p], nkey[q], 0, uvkey[t]))
            vs = [corners[i] for i in idx]
            mat.prims.append((0x90, vs))
    # merge each material's triangle lists into one 0x90 list split at 0xFFFF verts
    for mat in mats:
        allv = [v for _, vs in mat.prims for v in vs]
        mat.prims = [(0x90, allv[i:i + 65535 - 65535 % 3]) for i in range(0, len(allv), 65535 - 65535 % 3)]
    if len(wtab) > 255:
        raise ValueError(f"{len(wtab)} distinct weight sets > 255 (RE4 limit); simplify the skin weights")
    if len(P) > 65535 or len(N) > 65535 or len(UV) > 65535:
        raise ValueError("more than 65535 positions/normals/uvs")
    m.pos, m.pos_w = np.array(P), np.array(PW)
    m.nrm, m.nrm_w = np.array(N, np.int32), np.array(NW)
    m.uvs = np.array(UV)
    m.weights = [k for k, _ in sorted(wtab.items(), key=lambda t: t[1])]
    m.mats = mats
    mx = np.abs(m.pos).max()
    fit = int(np.floor(np.log2(32767 / max(mx, 1e-3))))   # largest frac that keeps positions in s16
    m.header[0x28] = pos_shift if pos_shift is not None else max(0, min(template.pos_shift, fit))
    # uv frac: keep the template's, unless the UVs don't fit s16
    while np.abs(m.uvs).max(initial=0) * (1 << m.uv_shift) > 32767 and m.header[0x3E] > 0:
        m.header[0x3E] -= 1
    struct.pack_into(">I", m.header, 0x24, len(texs))
    return m, texs


# ---------------------------------------------------------------- character swap

LEON_PARTS = {0: "body", 2: "head base", 4: "face", 5: "hair", 6: "jacket", 7: "eyes?", 8: "cutscene head", 9: "part",
              10: "part", 14: "hand pose", 15: "hand pose", 16: "hand pose", 17: "hand pose", 18: "hand pose",
              19: "hand pose", 20: "hand pose", 21: "hand pose"}


def collapse_bin(data: bytes, shrink: bool = False) -> bytes:
    """Hide a mesh without changing its layout: every position moves onto the mesh's centroid (zero-area
    triangles, inside the new body). Morph/face tables keep indexing valid vertices, so this is safe for any BIN.
    shrink=True also cuts every material's display list down to one degenerate triangle (frees most of the BIN's
    bytes for a bigger replacement body; vertex arrays stay so morph tables still index valid vertices)."""
    m = bin_read(data)
    m.pos[:] = m.pos.mean(0)
    if shrink:
        for mat in m.mats:
            first = next((vs[0] for _, vs in mat.prims if vs), (0, 0, 0, 0))
            mat.prims = [(0x90, [first] * 3)]
    return bin_write(m)


def swap_body(pack: "ModelPack", glb: Path, body: int = 0, hide: list[int] = (), scale: float = 0.001,
              max_tex: int = 128, shrink_hidden: bool = False) -> dict:
    """Replace a pack's body BIN with a glTF rigged to its bones (b<id> joint names), append the new textures to the
    body's TPL (other BINs keep their texture indices), and collapse the `hide` BINs (head/hair/jacket/hands...)."""
    tmpl = bin_read(pack.items[body][1])
    tj = pack.tpl_for(body)
    m, texs = gltf_to_bin(glb, tmpl, scale=scale, max_tex=max_tex)
    imgs = tpl_read(pack.items[tj][1])
    base = len(imgs)
    for mat in m.mats:
        h = bytearray(mat.hdr)
        h[0x0C] += base
        mat.hdr = bytes(h)
    imgs += [tpl_image_from_rgba(t, imgs[0].hdr if imgs else None) for t in texs]
    struct.pack_into(">I", m.header, 0x24, len(imgs))
    pack.items[body] = ("BIN", bin_write(m))
    pack.items[tj] = ("TPL", tpl_write(imgs))
    for i in hide:
        pack.items[i] = ("BIN", collapse_bin(pack.items[i][1], shrink_hidden))
    return {"verts": len(m.pos), "tris": sum(_tri_count(x.prims) for x in m.mats), "weights": len(m.weights),
            "materials": len(m.mats), "textures_added": len(texs), "pos_shift": m.pos_shift,
            "bin_bytes": len(pack.items[body][1])}


# ---------------------------------------------------------------- disc helpers + CLI

def load_pack_from_iso(iso: Path, name: str = "em/pl00.drs") -> ModelPack:
    from .gcdisc import GCDisc
    if Path(iso).is_dir():                                   # extracted Wii disc (gbox/re4wii.py)
        from .re4wii import FolderDisc
        return ModelPack(FolderDisc(iso).read(name))
    d = GCDisc(iso)
    try:
        return ModelPack(d.read(name))
    finally:
        d.f.close()


def export_pack(pack: ModelPack, out_dir: Path, scale: float = 0.001) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    for i in pack.bins():
        m = bin_read(pack.items[i][1])
        tj = pack.tpl_for(i)
        texs = [t.rgba() for t in tpl_read(pack.items[tj][1])] if tj is not None else None
        res.append(bin_to_gltf(m, texs, out_dir / f"bin{i:03d}.gltf", scale, f"bin{i:03d}"))
    return res


def roundtrip_check(pack: ModelPack) -> dict:
    """Decode + re-encode every BIN/TPL in the pack; report which come back byte-identical."""
    rep = {}
    for i, (e, d) in enumerate(pack.items):
        if e == "BIN":
            rep[i] = bin_write(bin_read(d)) == d
        elif e == "TPL":
            rep[i] = tpl_write(tpl_read(d)) == d
    return rep


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["export", "check"])
    ap.add_argument("iso")
    ap.add_argument("--file", default="em/pl00.drs")
    ap.add_argument("--out", default="re4_export")
    a = ap.parse_args()
    pk = load_pack_from_iso(Path(a.iso), a.file)
    if a.cmd == "check":
        print(roundtrip_check(pk))
    else:
        for p in export_pack(pk, Path(a.out)):
            print(p)
