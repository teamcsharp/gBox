"""Sega Ninja asset decoding (PSO Dreamcast/GameCube): PRS, BML archives, NJCM chunk models, PVM/PVR textures -> UAP.

Formats follow the public Ninja SDK layouts as documented by the PSO / Sonic Adventure modding communities
(newserv for PRS + BML). Little-endian = Dreamcast; big-endian = GameCube (be=True).
"""
import math
import struct
import zlib

import numpy as np

from . import uap


# ---------------------------------------------------------------- PRS (LZ77 variant) + BML archives
def prs_decompress(data: bytes) -> bytes:
    out, pos, ctrl, bits = bytearray(), 0, 0, 0

    def bit():
        nonlocal ctrl, bits, pos
        if bits == 0:
            ctrl, bits = data[pos], 8
            pos += 1
        b = ctrl & 1
        ctrl >>= 1
        bits -= 1
        return b

    while pos < len(data):
        if bit():
            out.append(data[pos])
            pos += 1
            continue
        if bit():                                            # long backreference
            if pos + 1 >= len(data):
                break
            a = data[pos] | (data[pos + 1] << 8)
            pos += 2
            offset = (a >> 3) | ~0x1FFF
            if offset == ~0x1FFF:
                break
            count = (a & 7) + 2 if a & 7 else data[pos] + 1
            if not a & 7:
                pos += 1
        else:                                                # short backreference
            count = ((bit() << 1) | bit()) + 2
            offset = data[pos] | ~0xFF
            pos += 1
        start = len(out) + offset
        for z in range(count):
            out.append(out[start + z])
    return bytes(out)


def bml(data: bytes, be: bool = False) -> dict[str, tuple[bytes, bytes | None]]:
    """{name: (decompressed file, decompressed texture archive or None)}; entries are 0x20-aligned from 0x800."""
    e = ">" if be else "<"
    n = struct.unpack_from(e + "I", data, 4)[0]
    out, off = {}, 0x800
    for i in range(n):
        h = 0x40 + 0x40 * i
        name = data[h:h + 0x20].split(b"\0")[0].decode("latin-1")
        csize, _, dsize, cgvm, dgvm = struct.unpack_from(e + "5I", data, h + 0x20)
        body = prs_decompress(data[off:off + csize])
        off = (off + csize + 0x1F) & ~0x1F
        tex = None
        if cgvm:
            tex = prs_decompress(data[off:off + cgvm])
            off = (off + cgvm + 0x1F) & ~0x1F
        out[name] = (body, tex)
    return out


# ---------------------------------------------------------------- textures (PVR / PVM)
def _twiddle(x: int, y: int) -> int:
    r = 0
    for i in range(12):
        r |= ((y >> i) & 1) << (2 * i) | ((x >> i) & 1) << (2 * i + 1)
    return r


def _px(fmt: int, v: int) -> tuple:
    if fmt == 0:                                              # ARGB1555
        return ((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31, 255 if v & 0x8000 else 0
    if fmt == 1:                                              # RGB565
        return ((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31, 255
    if fmt == 2:                                              # ARGB4444
        return ((v >> 8) & 15) * 17, ((v >> 4) & 15) * 17, (v & 15) * 17, ((v >> 12) & 15) * 17
    return (v >> 8) & 255, (v >> 8) & 255, (v >> 8) & 255, 255     # YUV/bump: luminance approximation


def pvr_decode(data: bytes) -> tuple[int, int, bytes, str]:
    """PVRT chunk (optionally preceded by GBIX) -> (width, height, RGBA bytes, description)."""
    o = data.find(b"PVRT")
    if o < 0:
        raise ValueError("no PVRT chunk")
    pix, dfmt, w, h = data[o + 8], data[o + 9], *struct.unpack_from("<HH", data, o + 12)
    body = data[o + 16:o + 8 + struct.unpack_from("<I", data, o + 4)[0]]
    rgba = bytearray(w * h * 4)

    def put(x, y, c):
        rgba[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(c)

    if dfmt in (3, 4, 0x10, 0x11):                            # VQ: codebook of 2x2 blocks (256, or fewer for small VQ)
        n = 256
        if dfmt in (0x10, 0x11):                              # small VQ: codebook size by width (more when mipmapped)
            mip = dfmt == 0x11
            n = 16 if w <= 16 else (64 if mip else 32) if w <= 32 else (256 if mip else 128) if w <= 64 else 256
        book = [[_px(pix, struct.unpack_from("<H", body, (c * 4 + k) * 2)[0]) for k in range(4)] for c in range(n)]
        idx = body[n * 8:]
        if dfmt in (4, 0x11):                                 # mipmaps first, smallest first: 1x1 and 2x2 take one
            pre, s = 0, 1                                      # index byte each, then (size/2)^2; the chunk may be
            while s < w:                                       # padded at the end, so count from the start
                pre += max(1, (s // 2) ** 2)
                s *= 2
            idx = idx[pre:pre + (w // 2) * (h // 2)]
        for y in range(0, h, 2):
            for x in range(0, w, 2):
                blk = book[idx[_twiddle(x // 2, y // 2)]]
                put(x, y, blk[0]); put(x, y + 1, blk[1]); put(x + 1, y, blk[2]); put(x + 1, y + 1, blk[3])
        return w, h, bytes(rgba), f"VQ pixfmt {pix}"
    if dfmt in (1, 2, 0x0D, 0x12):                            # twiddled (square or rectangle of squares), maybe mipmapped
        if dfmt in (2, 0x12):
            body = body[len(body) - w * h * 2:]
        s = min(w, h)
        for y in range(h):
            for x in range(w):
                blk = (y // s) * (w // s) + (x // s)
                v = struct.unpack_from("<H", body, (blk * s * s + _twiddle(x % s, y % s)) * 2)[0]
                put(x, y, _px(pix, v))
        return w, h, bytes(rgba), f"twiddled pixfmt {pix}"
    if dfmt in (9, 0x0B):                                     # linear rectangle / stride
        for y in range(h):
            for x in range(w):
                put(x, y, _px(pix, struct.unpack_from("<H", body, (y * w + x) * 2)[0]))
        return w, h, bytes(rgba), f"linear pixfmt {pix}"
    raise ValueError(f"PVR data format {dfmt:#x} not supported yet")


def pvm(data: bytes) -> list[tuple[str, bytes]]:
    """PVM archive -> [(texture name, PVR chunk bytes)] in archive order (= Ninja texture ids)."""
    if data[:4] != b"PVMH":
        raise ValueError("not a PVM")
    hsize = struct.unpack_from("<I", data, 4)[0]
    flags, count = struct.unpack_from("<HH", data, 8)
    names, o = [], 12
    for _ in range(count):
        o += 2
        if flags & 8:
            names.append(data[o:o + 28].split(b"\0")[0].decode("latin-1"))
            o += 28
        else:
            names.append(f"tex{len(names)}")
        o += (2 if flags & 4 else 0) + (2 if flags & 2 else 0) + (4 if flags & 1 else 0)
    out, o = [], 8 + hsize
    for nm in names:
        while o + 8 <= len(data) and data[o:o + 4] not in (b"GBIX", b"PVRT"):   # other chunks (MDLN model name...): skip
            o = (o + 8 + struct.unpack_from("<I", data, o + 4)[0] + 3) & ~3
        g = o
        if data[o:o + 4] == b"GBIX":
            o += 8 + struct.unpack_from("<I", data, o + 4)[0]
        size = struct.unpack_from("<I", data, o + 4)[0]
        out.append((nm, data[g:o + 8 + size]))
        o = (o + 8 + size + 3) & ~3
    return out


def png(w: int, h: int, rgba: bytes) -> bytes:
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw, 6)) + ch(b"IEND", b"")


def njtl(data: bytes, be: bool = False) -> list[str]:
    """Texture names a model references, in texture-id order (NJTL chunk: {names*, count}; entry = {name*, attr, addr})."""
    o = data.find(b"NJTL")
    if o < 0:
        return []
    e = ">" if be else "<"
    d = data[o + 8:o + 8 + struct.unpack_from(e + "I", data, o + 4)[0]]
    arr, n = struct.unpack_from(e + "II", d, 0)
    names = []
    for i in range(n):
        p = struct.unpack_from(e + "I", d, arr + 12 * i)[0]
        names.append(d[p:d.index(b"\0", p)].decode("latin-1"))
    return names


# ---------------------------------------------------------------- NJCM chunk models
def _mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _node_matrix(pos, ang, scl, zxy: bool):
    rad = [a * math.pi / 32768 for a in ang]
    cx, sx, cy, sy, cz, sz = math.cos(rad[0]), math.sin(rad[0]), math.cos(rad[1]), math.sin(rad[1]), math.cos(rad[2]), math.sin(rad[2])
    rx = [[1, 0, 0, 0], [0, cx, -sx, 0], [0, sx, cx, 0], [0, 0, 0, 1]]
    ry = [[cy, 0, sy, 0], [0, 1, 0, 0], [-sy, 0, cy, 0], [0, 0, 0, 1]]
    rz = [[cz, -sz, 0, 0], [sz, cz, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    r = _mat_mul(ry, _mat_mul(rx, rz)) if zxy else _mat_mul(rz, _mat_mul(ry, rx))
    s = [[scl[0], 0, 0, 0], [0, scl[1], 0, 0], [0, 0, scl[2], 0], [0, 0, 0, 1]]
    t = [[1, 0, 0, pos[0]], [0, 1, 0, pos[1]], [0, 0, 1, pos[2]], [0, 0, 0, 1]]
    return _mat_mul(t, _mat_mul(r, s))


def _xf(m, v, w=1.0):
    return [m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] + m[i][3] * w for i in range(3)]


def _quat(m):
    """Rotation matrix (upper 3x3, scale removed) -> quaternion x,y,z,w."""
    c = [[m[i][j] for j in range(3)] for i in range(3)]
    for j in range(3):
        n = math.sqrt(sum(c[i][j] ** 2 for i in range(3))) or 1
        for i in range(3):
            c[i][j] /= n
    tr = c[0][0] + c[1][1] + c[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1) * 2
        return [(c[2][1] - c[1][2]) / s, (c[0][2] - c[2][0]) / s, (c[1][0] - c[0][1]) / s, s / 4]
    i = max(range(3), key=lambda k: c[k][k])
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1 + c[i][i] - c[j][j] - c[k][k]) * 2
    q = [0.0] * 4
    q[i], q[j], q[k], q[3] = s / 4, (c[j][i] + c[i][j]) / s, (c[k][i] + c[i][k]) / s, (c[k][j] - c[j][k]) / s
    return q


class NJ:
    """Parse an NJCM model tree. Positions are emitted in bind-pose model space; each vertex records the node
    (bone) that wrote it, so the model imports as a skinned mesh on a skeleton."""

    def __init__(self, data: bytes, be: bool = False):
        o = data.find(b"NJCM")
        if o < 0:
            raise ValueError("no NJCM chunk")
        self.e = ">" if be else "<"
        size = struct.unpack_from(self.e + "I", data, o + 4)[0]
        self.d = data[o + 8:o + 8 + size]
        self.bones: list[dict] = []
        self.vbuf: dict[int, dict] = {}                         # global vertex cache: index -> {pos, nrm, joints}
        self.tris: dict[int, list] = {}                         # texture id -> [(i0, uv0), (i1, uv1), (i2, uv2)] lists
        self.tex = 0
        self.plcache: dict[int, int] = {}                       # cached polygon lists (chunk bits 4 / 5)
        self._walk(0, None, [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])

    def u(self, fmt, off):
        return struct.unpack_from(self.e + fmt, self.d, off)

    def _walk(self, off, parent, pm):
        while True:
            flags, model = self.u("II", off)
            pos, ang, scl = self.u("3f", off + 8), self.u("3i", off + 20), self.u("3f", off + 32)
            child, sib = self.u("II", off + 44)
            local = _node_matrix([0, 0, 0] if flags & 1 else pos, [0, 0, 0] if flags & 2 else ang,
                                 [1, 1, 1] if flags & 4 else scl, bool(flags & 0x20))
            m = _mat_mul(pm, local)
            bi = len(self.bones)
            self.bones.append({"name": f"node{bi:03d}", "parent": parent, "t": [local[0][3], local[1][3], local[2][3]],
                               "r": _quat(local), "s": [abs(x) or 1 for x in (scl if not flags & 4 else (1, 1, 1))], "m": m})
            if model and not flags & 8:
                vlist, plist = self.u("II", model)
                if vlist:
                    self._vertices(vlist, m, bi)
                if plist:
                    self._polys(plist)
            if child and not flags & 0x10:
                self._walk(child, bi, m)
            if not sib:
                return
            off = sib

    def _vertices(self, o, m, bone):
        while True:
            head = self.u("I", o)[0]
            typ, flg, size = head & 0xFF, (head >> 8) & 0xFF, head >> 16
            if typ == 0xFF:
                return
            if typ < 0x20 or typ > 0x32:
                o += 4 + size * 4
                continue
            base, count = self.u("HH", o + 4)
            p = o + 8
            stride = (size * 4 - 4) // max(count, 1)
            for i in range(count):
                v = self.u("3f", p)
                pos = _xf(m, v)
                nrm = None
                if typ in (0x21, 0x29, 0x2A, 0x2B, 0x2C):
                    n = self.u("3f", p + (16 if typ == 0x21 else 12))
                    nrm = _xf(m, n, 0.0)
                idx, wgt = base + i, 1.0
                if typ in (0x25, 0x2C):                           # Ninja-flag weights: low = vertex, high = weight
                    nf = self.u("I", p + stride - 4)[0]
                    idx, wgt = base + (nf & 0xFFFF), (nf >> 16) / 255.0
                    status = flg & 3                              # 0 start, 1 middle, 2 end
                    cur = self.vbuf.get(idx) if status else None
                    if cur:
                        cur["pos"] = [a + b * wgt for a, b in zip(cur["pos"], pos)]
                        if nrm and cur["nrm"]:
                            cur["nrm"] = [a + b * wgt for a, b in zip(cur["nrm"], nrm)]
                        cur["joints"].append((bone, wgt))
                        p += stride
                        continue
                    self.vbuf[idx] = {"pos": [c * wgt for c in pos], "nrm": [c * wgt for c in nrm] if nrm else None,
                                      "joints": [(bone, wgt)]}
                else:
                    self.vbuf[idx] = {"pos": pos, "nrm": nrm, "joints": [(bone, 1.0)]}
                p += stride
            o += 4 + size * 4

    def _snap(self, idx):
        """The vertex cache entry as it is when a strip is drawn: later nodes reuse cache slots (player models do),
        so resolving indices after the whole walk would pick up the wrong vertices."""
        v = self.vbuf.get(idx)
        return None if v is None else {"pos": list(v["pos"]), "nrm": list(v["nrm"]) if v["nrm"] else None,
                                       "joints": list(v["joints"])}

    def _polys(self, o):
        while True:
            head = self.u("H", o)[0]
            typ, flg = head & 0xFF, head >> 8
            if typ == 0xFF:
                return
            if typ == 4:                                         # cache polygon list: the rest of this list is drawn
                self.plcache[flg] = o + 2                        # later by a "draw polygon list" chunk (weighted
                return                                           # models: after all bones wrote their vertices)
            if typ == 5:
                if flg in self.plcache:
                    self._polys(self.plcache[flg])
                o += 2
            elif typ == 0 or 1 <= typ <= 7:                      # null, bits
                o += 2
            elif typ in (8, 9):                                  # tiny: texture id
                self.tex = self.u("H", o + 2)[0] & 0x1FFF
                o += 4
            elif 0x10 <= typ <= 0x3A:                            # material / volume: skip by size (in shorts)
                o += 4 + self.u("H", o + 2)[0] * 2
            elif 0x40 <= typ <= 0x4B:
                size, hdr = self.u("HH", o + 2)
                nstrips, user = hdr & 0x3FFF, hdr >> 14
                uvs = typ in (0x41, 0x42, 0x44, 0x45, 0x47, 0x48, 0x4A, 0x4B)
                uvdiv = 255.0 if typ in (0x41, 0x44, 0x47, 0x4A) else 1023.0
                extra = 3 if typ in (0x43, 0x44, 0x45) else (2 if typ in (0x46, 0x47, 0x48) else 0)
                p = o + 6
                for _ in range(nstrips):
                    n = self.u("h", p)[0]
                    p += 2
                    flip, n = n < 0, abs(n)
                    pts = []
                    for k in range(n):
                        idx = self.u("H", p)[0]
                        p += 2
                        uv = None
                        if uvs:
                            uu, vv = self.u("hh", p)
                            uv = [uu / uvdiv, vv / uvdiv]
                            p += 4
                        p += extra * 2 + (user * 2 if k >= 2 else 0)
                        pts.append((idx, uv, self._snap(idx)))
                    for k in range(len(pts) - 2):
                        a, b, c = pts[k], pts[k + 1], pts[k + 2]
                        if (k % 2 == 1) ^ flip:
                            a, b = b, a
                        self.tris.setdefault(self.tex, []).append((a, b, c))
                o += 4 + size * 2
            else:
                return                                           # unknown chunk: stop this list rather than misparse


def to_manifest(nj: NJ, name: str, source: dict, textures: list[str] | None = None) -> uap.Manifest:
    """One mesh per texture id, de-indexed per corner (UVs live on strips, not vertices), skinned to the node skeleton."""
    meshes, materials = [], []
    for tex, tris in sorted(nj.tris.items()):
        pos, nrm, uv, jnt, wgt, idx = [], [], [], [], [], []
        for tri in tris:
            vs = [(c[2] if len(c) > 2 else nj.vbuf.get(c[0]), c[1]) for c in tri]   # snapshot taken at draw time
            if all(v is not None for v, _ in vs):
                for (v, t) in vs:
                    idx.append(len(pos))
                    pos.append([round(c, 5) for c in v["pos"]])
                    n = v["nrm"] or [0, 1, 0]
                    ln = math.sqrt(sum(c * c for c in n)) or 1
                    nrm.append([c / ln for c in n])
                    uv.append(t or [0, 0])
                    js = sorted(v["joints"], key=lambda jw: -jw[1])[:4]
                    tot = sum(w for _, w in js) or 1
                    jnt.append([j for j, _ in js] + [0] * (4 - len(js)))
                    wgt.append([w / tot for _, w in js] + [0.0] * (4 - len(js)))
        if not idx:
            continue
        mi = len(materials)
        tex_name = textures[tex] if textures and tex < len(textures) else None
        materials.append(uap.Material(name=f"tex{tex}", texture=tex_name, source={"ninja_texture_id": tex}))
        meshes.append(uap.Mesh(name=f"{name}_tex{tex}", positions=pos, normals=nrm, uvs=uv, indices=idx, material=mi,
                               joints=jnt, weights=wgt))
    skel = [uap.Bone(name=b["name"], parent=b["parent"], translation=b["t"], rotation=b["r"], scale=[1, 1, 1]) for b in nj.bones]
    nodes = [uap.Node(name=m.name, mesh=i, skinned=True) for i, m in enumerate(meshes)]
    return uap.Manifest(name=name, source=source, meshes=meshes, materials=materials, skeleton=skel, nodes=nodes,
                        roots=list(range(len(nodes))),
                        confidence={"geometry": "partial", "materials": "partial", "textures": "partial" if textures else "missing",
                                    "skeleton": "partial", "skin_weights": "partial", "animations": "missing",
                                    "source_identity": "verified"})


# ---------------------------------------------------------------- writing (gBox character swaps: gbox.sa2_chars, gbox.pso_player)
def prs_compress(data: bytes, depth: int = 256) -> bytes:
    """PRS encoder (the exact inverse of prs_decompress): literals (9 bits), short refs (2..5 bytes, 256 back, 12
    bits), long refs (3..9 bytes inline, 18 bits; 10..256 with a count byte, 26 bits; 8191 back). Hash-chain match
    finder + an optimal parse (shortest bit cost, dynamic programming from the end): about SEGA's own ratio."""
    n = len(data)
    head, prev = {}, [-1] * n
    longm = [(0, 0)] * n                                     # (length, distance) longest match, distance <= 8191
    shortm = [(0, 0)] * n                                    # longest match with distance <= 255 (short refs)
    for i in range(n):
        if i + 2 < n:
            key = data[i:i + 3]
            j, tries = head.get(key, -1), 0
            lim = min(256, n - i)
            bl = bo = sl = so = 0
            while j >= 0 and i - j <= 8191 and tries < depth:
                if data[j + bl:j + bl + 1] == data[i + bl:i + bl + 1] or (i - j <= 255 and sl < 5):
                    k = 0
                    while k < lim and data[j + k] == data[i + k]:
                        k += 1
                    if k > bl:
                        bl, bo = k, i - j
                    if i - j <= 255 and k > sl:
                        sl, so = min(k, 5), i - j
                    if bl == lim:
                        break
                j, tries = prev[j], tries + 1
            longm[i] = (bl, bo)
            if sl < 2 and i + 1 < n and i >= 1 and data[i - 1:i + 1] == data[i:i + 2]:
                sl, so = 2, 1
            shortm[i] = (sl, so)
            prev[i] = head.get(key, -1)
            head[key] = i
        elif i + 1 < n:                                      # the last two bytes: a 2-byte short ref is possible
            for d in range(1, min(255, i) + 1):
                if data[i - d:i - d + 2] == data[i:i + 2]:
                    shortm[i] = (2, d)
                    break
    INF = float("inf")
    cost = [INF] * (n + 1)
    choice = [None] * (n + 1)
    cost[n] = 0
    for i in range(n - 1, -1, -1):
        best, ch = 9 + cost[i + 1], (1, 0)
        sl, so = shortm[i]
        for L in range(2, sl + 1):
            c = 12 + cost[i + L]
            if c < best:
                best, ch = c, (L, -so)
        ll, lo = longm[i]
        if ll >= 3:
            for L in range(3, min(9, ll) + 1):
                c = 18 + cost[i + L]
                if c < best:
                    best, ch = c, (L, lo)
            if ll >= 10:
                Ls = range(10, ll + 1) if ll < 48 else list(range(10, 48)) + [ll]
                for L in Ls:
                    c = 26 + cost[i + L]
                    if c < best:
                        best, ch = c, (L, lo)
        cost[i], choice[i] = best, ch
    out = bytearray()
    st = {"pos": None, "n": 8}

    def bit(b):
        if st["n"] == 8:                                     # the decoder fetches a control byte when it needs a bit
            st["pos"], st["n"] = len(out), 0
            out.append(0)
        out[st["pos"]] |= (b & 1) << st["n"]
        st["n"] += 1
    i = 0
    while i < n:
        L, off = choice[i]
        if L == 1:
            bit(1)
            out.append(data[i])
        elif off < 0:                                        # short reference
            bit(0), bit(0)
            c = L - 2
            bit(c >> 1), bit(c & 1)
            out.append((off) & 0xFF)
        else:
            bit(0), bit(1)
            o = (-off) & 0x1FFF
            if L <= 9:
                a = (o << 3) | (L - 2)
                out += bytes((a & 0xFF, a >> 8))
            else:
                a = o << 3
                out += bytes((a & 0xFF, a >> 8, L - 1))
        i += L
    bit(0), bit(1)
    out += b"\0\0"
    return bytes(out)


def _px16(c, pix: int) -> int:
    """RGB(A) 0..255 -> a 16-bit PVR pixel: 0 ARGB1555, 1 RGB565, 2 ARGB4444 (opaque unless alpha given)."""
    c = np.clip(np.asarray(c, float), 0, 255)
    a = c[3] if len(c) > 3 else 255
    if pix == 0:
        return (0x8000 if a >= 128 else 0) | (int(c[0]) >> 3) << 10 | (int(c[1]) >> 3) << 5 | int(c[2]) >> 3
    if pix == 2:
        return (int(a) >> 4) << 12 | (int(c[0]) >> 4) << 8 | (int(c[1]) >> 4) << 4 | int(c[2]) >> 4
    return (int(c[0]) >> 3) << 11 | (int(c[1]) >> 2) << 5 | int(c[2]) >> 3


def _rgb565(c) -> int:
    return _px16(c, 1)


def _vq_nearest(blocks, book, batch_size=1024):
    """Nearest VQ codewords with a bounded temporary, including the large mip levels."""
    return np.concatenate([((blocks[start:start + batch_size, None, :] - book[None]) ** 2).sum(2).argmin(1)
                           for start in range(0, len(blocks), batch_size)])


def pvr_vq(rgba, gbix: int | None = None, iters: int = 12, pix: int = 1, small: bool = False,
           mips: bool = False) -> bytes:
    """Square power-of-two image -> [GBIX] + PVRT VQ: data format 3 (256-entry codebook of 2x2 blocks, k-means) or,
    small=True, format 0x10 (small VQ: the codebook size pvr_decode expects for the width), + one twiddled index
    byte per block. mips=True writes format 4 with all smaller levels first, using Flycast's VQMipPoint offsets.
    RGBA alpha is retained for ARGB1555/4444. Mipmapped small VQ remains unsupported."""
    if pix not in (0, 1, 2):
        raise ValueError(f"VQ pixel format {pix} is not written (ARGB1555, RGB565, ARGB4444 only)")
    if mips and small:
        raise ValueError("mipmapped small VQ (0x11) is not written")
    img = np.asarray(rgba, float)
    if img.ndim != 3 or img.shape[2] not in (3, 4):
        raise ValueError("VQ needs an RGB or RGBA image")
    channels = 4 if pix != 1 and img.shape[2] == 4 else 3
    img = img[..., :channels]
    h, w = img.shape[:2]
    if h != w or w & (w - 1) or not 8 <= w <= 1024:
        raise ValueError(f"VQ needs a square power-of-two texture, got {w}x{h}")
    bw = w // 2
    # block k: (x, y), (x, y + 1), (x + 1, y), (x + 1, y + 1) = pvr_decode's order
    blocks = np.stack([img[0::2, 0::2], img[1::2, 0::2], img[0::2, 1::2], img[1::2, 1::2]], 2).reshape(-1, 4 * channels)
    mip_blocks = []
    if mips:
        # Include reduced-level patterns in the shared codebook. Full-resolution-only
        # training cannot represent the different texels of a coarse 2x2 mip block.
        mip_blocks.append((1, np.tile(img.mean((0, 1)), 4).reshape(1, -1)))
        side = 2
        while side < w:
            reduced = img.reshape(side, h // side, side, w // side, channels).mean((1, 3))
            values = np.stack([reduced[0::2, 0::2], reduced[1::2, 0::2],
                               reduced[0::2, 1::2], reduced[1::2, 1::2]], 2).reshape(-1, 4 * channels)
            mip_blocks.append((side, values))
            side *= 2
    training = np.concatenate([blocks] + [values for _, values in mip_blocks]) if mips else blocks
    rng = np.random.default_rng(0)
    nbook = (16 if w <= 16 else 32 if w <= 32 else 128 if w <= 64 else 256) if small else 256
    k = min(nbook, len(training))
    cb = training[rng.choice(len(training), k, replace=False)].copy()
    anchors = np.concatenate([values for side, values in mip_blocks if side <= 4]) if mips else []
    fixed = len(anchors)
    if fixed:
        cb[:fixed] = anchors  # At most six entries retain the 1x1, 2x2 and 4x4 averages.

    def labels():
        return _vq_nearest(training, cb)
    for _ in range(iters):
        lab = labels()
        for c in range(fixed, k):
            m = lab == c
            cb[c] = training[m].mean(0) if m.any() else training[rng.integers(len(training))]
    lab = labels()[:len(blocks)]
    book = b"".join(struct.pack("<4H", *[_px16(cb[c, channels * q:channels * (q + 1)], pix)
                                       for q in range(4)]) for c in range(k))
    book += bytes(8 * (nbook - k))
    def level(grid):
        side = grid.shape[0]
        out = bytearray(side * side)
        for by in range(side):
            for bx in range(side):
                out[_twiddle(bx, by)] = grid[by, bx]
        return bytes(out)
    idx = level(lab.reshape(bw, bw))                         # [by, bx]
    prefix = b""
    if mips:
        prefix = b"".join(level(_vq_nearest(values, cb).reshape(max(1, side // 2), -1))
                          for side, values in mip_blocks)
    body = book + prefix + idx
    pvrt = b"PVRT" + struct.pack("<IBBHHH", 8 + len(body), pix, 0x10 if small else 4 if mips else 3, 0, w, h) + body
    return (b"GBIX" + struct.pack("<II", 8, gbix) + bytes(4) if gbix is not None else b"") + pvrt


def pvr_twiddled(rgba, pix: int = 1) -> bytes:
    """Square power-of-two image -> PVRT data format 1 (twiddled 16-bit pixels)."""
    img = np.asarray(rgba, float)
    h, w = img.shape[:2]
    if h != w or w & (w - 1):
        raise ValueError(f"twiddled needs a square power-of-two texture, got {w}x{h}")
    out = bytearray(2 * w * h)
    for y in range(h):
        for x in range(w):
            struct.pack_into("<H", out, 2 * _twiddle(x, y), _px16(img[y, x], pix))
    return b"PVRT" + struct.pack("<IBBHHH", 8 + len(out), pix, 1, 0, w, h) + bytes(out)


def pvr_like(old: bytes, rgb_img) -> bytes:
    """Encode like `old`: VQ (3), VQ+mips (4), small VQ (0x10), or twiddled (1).

    Keep the original header, GBIX and trailing bytes; the declared PVRT extent must fit the new body.
    """
    q = old.find(b"PVRT")
    if q < 0 or q + 16 > len(old):
        raise ValueError("missing or truncated PVRT header")
    size = struct.unpack_from("<I", old, q + 4)[0]
    if size < 8 or q + 8 + size > len(old):
        raise ValueError("truncated or invalid PVRT chunk extent")
    pix, fmt, w, h = old[q + 8], old[q + 9], *struct.unpack_from("<HH", old, q + 12)
    if pix not in (0, 1, 2):
        raise ValueError(f"PVR pixel format {pix} is not written")
    if fmt not in (1, 3, 4, 0x10):
        raise ValueError(f"PVR data format {fmt:#x} not written")
    minimum = 1 if fmt == 1 else 8
    if w != h or w & (w - 1) or not minimum <= w <= 1024:
        raise ValueError(f"unsupported PVR replacement dimensions {w}x{h}")
    img = np.asarray(rgb_img.convert("RGBA" if pix != 1 else "RGB").resize((w, h)))
    if fmt == 3:
        new = pvr_vq(img, pix=pix)
    elif fmt == 0x10:
        new = pvr_vq(img, pix=pix, small=True)
    elif fmt == 4:
        new = pvr_vq(img, pix=pix, mips=True)
    elif fmt == 1:
        new = pvr_twiddled(img, pix)
    body = new[16:]
    if len(body) > size - 8:
        raise ValueError(f"replacement body {len(body)} bytes exceeds the declared PVRT body {size - 8}")
    return old[:q + 16] + body + old[q + 16 + len(body):]


def pvm_entry_gbix(chunk: bytes) -> int | None:
    return struct.unpack_from("<I", chunk, 8)[0] if chunk[:4] == b"GBIX" else None


def pvm_replace(data: bytes, index: int, chunk: bytes) -> bytes:
    """A PVM with entry `index` (GBIX + PVRT) swapped for `chunk`; the header and the other entries stay."""
    hsize = struct.unpack_from("<I", data, 4)[0]
    o, k = 8 + hsize, 0
    while o + 8 <= len(data):
        if data[o:o + 4] not in (b"GBIX", b"PVRT"):
            o = (o + 8 + struct.unpack_from("<I", data, o + 4)[0] + 3) & ~3
            continue
        g = o
        if data[o:o + 4] == b"GBIX":
            o += 8 + struct.unpack_from("<I", data, o + 4)[0]
        end = (o + 8 + struct.unpack_from("<I", data, o + 4)[0] + 3) & ~3
        if k == index:
            return data[:g] + chunk + bytes((-len(chunk)) % 4) + data[end:]
        o, k = end, k + 1
    raise IndexError(f"PVM has no entry {index}")


def chunk_list_len(d: bytes, off: int, kind: str, e: str = "<") -> int:
    """Byte length of a chunk vertex list ("v") or polygon list ("p"), its end chunk included."""
    o = off
    if kind == "v":
        while True:
            h = struct.unpack_from(e + "I", d, o)[0]
            o += 4
            if h & 0xFF == 0xFF:
                return o - off
            o += (h >> 16) * 4
    while True:
        h = struct.unpack_from(e + "H", d, o)[0]
        t = h & 0xFF
        if t == 0xFF:
            return o + 2 - off
        if t in (8, 9):
            o += 4
        elif 0x10 <= t <= 0x4B:
            o += 4 + struct.unpack_from(e + "H", d, o + 2)[0] * 2
        else:
            o += 2


def tree_nodes(d: bytes, off: int, e: str = "<") -> list[dict]:
    """An NJS_OBJECT tree in depth-first order: {off, flags, model, pos/ang/scl raw bytes, child, sibling (indices)}."""
    out = []

    def walk(o, parent, root=False):
        first = None
        prev = None
        while o or root:                                     # the root may sit at offset 0 (NJ files)
            root = False
            flags, model = struct.unpack_from(e + "II", d, o)
            child, sib = struct.unpack_from(e + "II", d, o + 44)
            i = len(out)
            out.append({"off": o, "flags": flags, "model": model, "trs": d[o + 8:o + 44], "parent": parent,
                        "child": None, "sibling": None})
            if first is None:
                first = i
            if prev is not None:
                out[prev]["sibling"] = i
            if child:
                out[i]["child"] = walk(child, i)
            prev, o = i, sib
        return first
    walk(off, None, True)
    return out


def tree_ranges(d: bytes, off: int, e: str = "<") -> list[tuple[int, int]]:
    """Every byte range an object tree uses (node structs, NJS_CNK_MODELs, vertex and polygon lists)."""
    rs = []
    for nd in tree_nodes(d, off, e):
        rs.append((nd["off"], nd["off"] + 52))
        if nd["model"]:
            vl, pl = struct.unpack_from(e + "II", d, nd["model"])
            rs.append((nd["model"], nd["model"] + 24))
            if vl:
                rs.append((vl, vl + chunk_list_len(d, vl, "v", e)))
            if pl:
                rs.append((pl, pl + chunk_list_len(d, pl, "p", e)))
    return rs


def cnk_model_lists(pos, nrm, tris, texid: int, mat: bytes, tiny_flags: int = 0x34, tex_flags: int = 0x4000,
                    strip_flags: int = 0x12, e: str = "<", base: int = 0,
                    keep_vlist: bytes = b"") -> tuple[bytes, bytes, list, float]:
    """One rigid node's geometry -> (vertex list, polygon list, bound centre, radius). pos/nrm: (n, 3) node-local;
    tris: [((i0, i1, i2), ((u0, v0), (u1, v1), (u2, v2)))]. Vertex chunk 0x29 (position + normal), one strip
    chunk 0x41 (UVs, 1.0 = 255) of strips (gbox.re4gc_enemies.stripify); strip_flags 0x10 = double sided. base: the first vertex
    cache slot; keep_vlist: the node's original vertex chunks (without their end chunk), run first (games that read
    the original vertices, SA2's weighted characters, need them kept)."""
    pos, nrm = np.asarray(pos, np.float32), np.asarray(nrm, np.float32)
    n = len(pos)
    vb = np.concatenate([pos, nrm], 1).astype(e + "f4").tobytes()
    vl = keep_vlist + struct.pack(e + "IHH", 0x29 | ((1 + 6 * n) << 16), base, n) + vb + struct.pack(e + "I", 0xFF)
    pl = bytearray()
    if mat:
        pl += mat
    pl += struct.pack(e + "HH", 8 | (tiny_flags << 8), (texid & 0x1FFF) | tex_flags)
    from .re4gc_enemies import stripify                    # greedy strips; a strip vertex = index + uv
    q = lambda x: int(np.clip(round(x * 255), -32768, 32767))
    corners = [tuple((i + base, q(u), q(v)) for i, (u, v) in zip(idx, uvs)) for idx, uvs in tris]
    strips = []
    for kind, vs in stripify(corners):
        strips += [vs] if kind == 0x98 else [vs[k:k + 3] for k in range(0, len(vs), 3)]
    body = bytearray(struct.pack(e + "H", len(strips)))
    for vs in strips:
        body += struct.pack(e + "h", len(vs))
        for i, u, v in vs:
            body += struct.pack(e + "Hhh", i, u, v)
    if len(body) % 4:                                        # size counts shorts; keep the list 4-aligned
        body += bytes(2)
    pl += struct.pack(e + "HH", 0x41 | (strip_flags << 8), len(body) // 2) + body
    pl += struct.pack(e + "H", 0xFF) + bytes(2)
    c = (pos.min(0) + pos.max(0)) / 2 if n else np.zeros(3)
    r = float(np.linalg.norm(pos - c, axis=1).max()) if n else 0.0
    return bytes(vl), bytes(pl), [float(x) for x in c], r


def write_tree(nodes: list[dict], models: dict, base: int, e: str = "<") -> tuple[bytes, int, list[int]]:
    """Serialize a node tree (tree_nodes layout; flags / trs may be edited) with new chunk models at file offset
    `base`. models: {node index: (vlist, plist, centre, radius)}. -> (bytes, root offset, pointer field offsets
    (absolute, for a POF0 table))."""
    out = bytearray()
    ptrs = []
    node_off = [base + 52 * i for i in range(len(nodes))]
    out += bytes(52 * len(nodes))
    model_off = {}
    for i in sorted(models):
        vl, pl, c, r = models[i]
        mo = base + len(out)
        out += bytes(24)
        vo = base + len(out)
        out += vl
        po = base + len(out)
        out += pl
        out += bytes((-len(out)) % 4)
        out[mo - base:mo - base + 24] = struct.pack(e + "II4f", vo if vl else 0, po if pl else 0, *c, r)
        if vl:
            ptrs.append(mo)
        if pl:
            ptrs.append(mo + 4)
        model_off[i] = mo
    for i, nd in enumerate(nodes):
        o = node_off[i] - base
        mo = model_off.get(i, 0)
        ch = node_off[nd["child"]] if nd["child"] is not None else 0
        sb = node_off[nd["sibling"]] if nd["sibling"] is not None else 0
        out[o:o + 52] = struct.pack(e + "II", nd["flags"], mo) + nd["trs"] + struct.pack(e + "II", ch, sb)
        for k, v in ((4, mo), (44, ch), (48, sb)):
            if v:
                ptrs.append(node_off[i] + k)
    return bytes(out), node_off[0], ptrs


def pof0(ptrs: list[int], base: int = 0) -> bytes:
    """POF0 relocation chunk for pointer field offsets (relative to the data start): 2-bit size class + distance
    in 4-byte units (0x40 | d: 6 bits, 0x80 | d: 14 bits, 0xC0 | d: 30 bits)."""
    body, last = bytearray(), base
    for p in sorted(ptrs):
        d = (p - last) // 4
        last = p
        if d < 0x40:
            body.append(0x40 | d)
        elif d < 0x4000:
            body += struct.pack(">H", 0x8000 | d)
        else:
            body += struct.pack(">I", 0xC0000000 | d)
    body += bytes((-len(body)) % 4)
    return b"POF0" + struct.pack("<I", len(body)) + bytes(body)


def _selftest():
    raw = b"ABCDEFGHIJKL"
    def lit_only(b):                                          # literals, then the stop code (bits 0,1 + zero offset)
        out, bits, nb, pend = bytearray(), [], 0, bytearray()
        ctrl_pos = None
        def flush():
            nonlocal ctrl_pos
        stream = [(1, c) for c in b] + [(0, None), (1, None)]
        ctrl, n, cpos = 0, 0, len(out)
        out.append(0)
        for bit, c in stream:
            if n == 8:
                out[cpos] = ctrl
                ctrl, n, cpos = 0, 0, len(out)
                out.append(0)
            ctrl |= bit << n
            n += 1
            if c is not None:
                out.append(c)
        out[cpos] = ctrl
        return bytes(out + b"\0\0")
    assert prs_decompress(lit_only(raw)) == raw
    for blob in (raw, b"abcabcabcabcabcabcabcabcabc" * 50, bytes(range(256)) * 40, b""):
        assert prs_decompress(prs_compress(blob)) == blob
    img = np.zeros((16, 16, 3), np.uint8)
    img[:8] = (255, 0, 0)
    for f in (pvr_vq(img), pvr_vq(img, small=True, pix=2), pvr_twiddled(img, 1)):
        w, h, rgba, _ = pvr_decode(f)
        assert (w, h) == (16, 16) and rgba[0] > 200 and rgba[(15 * 16) * 4] < 50, (rgba[:4], rgba[(15 * 16) * 4:][:4])
    assert _twiddle(1, 0) == 2 and _twiddle(0, 1) == 1 and _twiddle(1, 1) == 3
    m = _node_matrix([1, 2, 3], [0, 16384, 0], [1, 1, 1], False)          # 90 deg about Y
    v = _xf(m, [1, 0, 0])
    assert all(abs(a - b) < 1e-6 for a, b in zip(v, [1, 2, 2])), v
    print("ninja selftest ok")


if __name__ == "__main__":
    _selftest()
