"""Def Jam: Vendetta (GameCube, USA GDTE69 rev 0): read-only native model reader.

Exact build (owned HyperSpin GCZ, unpacked once to the shared mod base by characters._gc_iso):
  ISO 1459978240 bytes, sha256 780138844d35d8b5087d8ace9f7efa5f1ab3776ea6f77a5d025c2e3adae2ad63
  main.dol 1770208 bytes, sha256 5d3cea0a80885cbf06458b3b58854dbf717b4f6b201b135c3786b099fcade692

Disc layout (FST, 1295 files):
  data/sNNNx/sNNNx_mK.{gpl,skn,act[,tpl]}  fighter NNN, costume x, part K. Trailer names: m0 body, m1 face,
                                            m2 L_hand_N, m3 R_hand_N, m5 accessory (glass, al, ...)
  data/aud/adNN_xK.*                        crowd models (same formats)
  data/BGnnA.{arn,bbd,lit}                  stages; data/*.anx animation banks; menu/*.tpl UI textures

.gpl mesh (big-endian; "rel" offsets are relative to file offset 0x1C):
  0x00 u32 magic 0x00B749E0
  0x1C u32 rel -> vertex header {u32 rel data, u16 count, u8 ?, u8 position fraction bits}
         vertex = s16 position xyz + s16 normal xyz (|n| ~ 1024): 12 bytes, block padded to 32 bytes
  0x24 u32 rel -> uv header {u32 rel data, u16 count, ...}; uv = f32 u, f32 v
  0x28 u32 rel -> draw header H: H+0 u32 bone count, H+0x38 {u32 ?, u32 vcd, u32 rel display list, u32 size}
         vcd: 2 bits per attribute (0 none, 1 direct, 2 index8, 3 index16): bits 0-1 matrix index,
              2-3 position, 4-5 normal, 6-7 colour0, 8-9 colour1, 10-11.. tex0..tex7
              (0x0C3C = pos/nrm/tex0 index16, 0x083C = tex0 index8, 0x0828 = all index8)
         display list: standard GX primitives (0x90 triangles, 0x98 strip, 0xA0 fan, 0x80 quads, 0x00 nop)
  after the display list: NUL-terminated texture file name and "<part>-<mesh name>"
Vertices are stored in model space (bind pose). Texture image 0 of the named .tpl is used when that file exists.

WIP (djv-gc-roles, decoded on the owned disc, not wired into extract_run yet; v1 exports a static, unrigged mesh):
.act skeleton (big-endian, absolute offsets): 0x00 u32 magic 0x007B7960, 0x04 u32 node count (BODY 42, face 11,
  hands 13, m4 10), 0x0C u32 -> node records, 0x1C u32 -> "ACTU" name table, 0x20 u32 -> first transform.
  Node record 0x1C bytes: u32 -> transform, u32 -> prev sibling, u32 -> next sibling, u32 -> parent, u32 -> first
  child (0 = none), u16 0xFFFF, u16 index, u32 0x01000000. Transform 0x34 bytes: u32 0x0D000000, f32 scale xyz,
  f32 quaternion xyzw, f32 translation xyz, 8 pad. local = T R S (column vectors), world = parent world @ local.
  ACTU: "ACTU", u32, u32, u32 count, u32 ?, then count u32 name offsets relative to ACTU. BODY names: body root
  tophip hip waist chest neck head backbone_eff L_arm_root L_shoulder L_arm1 L_arm2 L_hand L_arm_eff R_... ,
  L_hipbone_root L_hipbone L_hipbone_eff L_leg_root L_leg1 L_leg2 L_leg_eff L_foot_root L_foot L_foot_eff, R_...,
  Direction. Same 42-node tree and T-pose as PS2 (pelvis y 10.56, head end 20.71, hands x +-9.87), so the PS2
  ROLE_NODES (hip 2 chest 5 neck 6 head 7 l_clav 10..l_hand 13 r 16..19 l_thigh 25 l_shin 26 l_foot 29 r 35 36 39)
  and joint_name() body_NN apply unchanged. Face/accessory node 1 (head_bone) = BODY head 7 world; hand node 1 =
  BODY 13 / 19; m4 names root..head map to BODY 1..7.
.skn weights: u16 n_single, u16 n_pair, u16 n_list, u8 fraction bits (10; s308a_m4 11), u8 0, u32 -> single
  table, u32 -> pair table, u32 -> list table. Single (0x40): +0x30 u32 src, u32 dst byte offset in the .gpl vertex
  block, u16 bone, u16 n, u8 skip. Pair (0x74): +0x60 u32 src, u32 -> u8 weight pairs (sum 256), u32 dst, u16 bone a,
  u16 bone b, u16 n, u8 skip. First vertex = (dst + skip) / 12; src + skip holds the same s16 pos+nrm as the .gpl
  (verified byte-equal on all 255 parts). List (0x44): +0x30 u32 src, u32 -> u16 vertex indices, u32 0,
  u32 -> u8 weights, u16 bone, u16 n (scattered extra influences). Game units = raw / 2^skn fraction bits (the
  .gpl's own 6 gives 16x). TODO: confirm pair weight order (a, b), assemble one skin, READER_VERSION 2.
"""
import json
import re
import struct
import zlib
from pathlib import Path

import numpy as np

GPL_MAGIC = 0x00B749E0
TPL_MAGIC = 0x0020AF30
DISC_ID = "GDTE69"
ISO_SHA256 = "780138844d35d8b5087d8ace9f7efa5f1ab3776ea6f77a5d025c2e3adae2ad63"
DOL_SHA256 = "5d3cea0a80885cbf06458b3b58854dbf717b4f6b201b135c3786b099fcade692"
BASE = 0x1C
ATTRS = ["mtx", "pos", "nrm", "clr0", "clr1"] + [f"tex{i}" for i in range(8)]
PART_ROLES = {0: "body", 1: "face", 2: "left_hand", 3: "right_hand", 4: "part4", 5: "accessory"}
MIN_WINDING = 0.85          # share of triangles whose face normal agrees with the stored vertex normals


class FormatError(ValueError):
    pass


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def _u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def _need(b, o, n, what):
    if o < 0 or o + n > len(b):
        raise FormatError(f"{what} runs past the end of the file")


def identify(iso) -> dict:
    """Disc header of an ISO/GCM: game id, disc number, revision and internal name."""
    with open(iso, "rb") as f:
        h = f.read(0x60)
    return {"game_id": h[:6].decode("ascii", "replace"), "disc": h[6], "revision": h[7],
            "name": h[0x20:0x60].split(b"\0")[0].decode("latin-1"), "exact_build": h[:6] == DISC_ID.encode() and h[7] == 0}


def _triangulate(kind, v):
    if kind == 0x90:
        return [(v[i], v[i + 1], v[i + 2]) for i in range(0, len(v) - 2, 3)]
    if kind == 0x98:
        return [(v[i], v[i + 1], v[i + 2]) if i % 2 == 0 else (v[i + 1], v[i], v[i + 2]) for i in range(len(v) - 2)]
    if kind == 0xA0:
        return [(v[0], v[i + 1], v[i + 2]) for i in range(len(v) - 2)]
    return [t for i in range(0, len(v) - 3, 4) for t in ((v[i], v[i + 1], v[i + 2]), (v[i], v[i + 2], v[i + 3]))]


def decode_dl(dl: bytes, vcd: int, nv: int, nuv: int):
    """GX display list -> triangles of (pos, nrm, tex0) index corners, and the primitive count. Strict: any
    unknown opcode, truncated primitive or out-of-range index raises FormatError."""
    layout = []
    for k, name in enumerate(ATTRS):
        mode = (vcd >> (2 * k)) & 3
        if not mode:
            continue
        if mode == 1 and name != "mtx":
            raise FormatError(f"direct {name} data is not decoded (vcd 0x{vcd:x})")
        layout.append((name, 1 if mode in (1, 2) else 2))
    if not any(n == "pos" for n, _ in layout):
        raise FormatError(f"vcd 0x{vcd:x} has no position")
    stride = sum(s for _, s in layout)
    limits = {"pos": nv, "nrm": nv, "tex0": nuv}
    tris, prims, o = [], 0, 0
    while o < len(dl):
        op = dl[o]
        if op == 0:
            o += 1
            continue
        kind = op & 0xF8
        if kind not in (0x80, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8):
            raise FormatError(f"unknown display-list opcode 0x{op:02x} at 0x{o:x}")
        _need(dl, o, 3, "primitive header")
        n = _u16(dl, o + 1)
        o += 3
        _need(dl, o, n * stride, f"primitive 0x{op:02x}")
        verts = []
        for i in range(n):
            v, p = {}, o + i * stride
            for name, sz in layout:
                v[name] = dl[p] if sz == 1 else _u16(dl, p)
                p += sz
            for name, lim in limits.items():
                if name in v and v[name] >= lim:
                    raise FormatError(f"{name} index {v[name]} >= {lim} at 0x{o + i * stride:x}")
            verts.append((v["pos"], v.get("nrm", v["pos"]), v.get("tex0", -1)))
        o += n * stride
        prims += 1
        if kind in (0x80, 0x90, 0x98, 0xA0):
            tris.extend(_triangulate(kind, verts))
    return tris, prims


def parse_gpl(b: bytes) -> dict:
    if len(b) < 0x40 or _u32(b, 0) != GPL_MAGIC:
        raise FormatError("not a Def Jam Vendetta .gpl mesh (magic 0x00B749E0)")
    vh = BASE + _u32(b, 0x1C)
    _need(b, vh, 8, "vertex header")
    vdata, nv, frac = BASE + _u32(b, vh), _u16(b, vh + 4), b[vh + 7]
    _need(b, vdata, nv * 12, "vertex block")
    raw = np.frombuffer(b, ">i2", nv * 6, vdata).reshape(nv, 6).astype(np.float64)
    nrm_raw = raw[:, 3:]
    ln = np.linalg.norm(nrm_raw, axis=1, keepdims=True)
    uh = BASE + _u32(b, 0x24)
    _need(b, uh, 8, "uv header")
    udata, nuv = BASE + _u32(b, uh), _u16(b, uh + 4)
    _need(b, udata, nuv * 8, "uv block")
    uv = np.frombuffer(b, ">f4", nuv * 2, udata).reshape(nuv, 2).astype(np.float32)
    dh = BASE + _u32(b, 0x28)
    _need(b, dh, 0x48, "draw header")
    vcd, dl_rel, dl_size = struct.unpack_from(">III", b, dh + 0x3C)
    dl = BASE + dl_rel
    _need(b, dl, dl_size, "display list")
    tris, prims = decode_dl(b[dl:dl + dl_size], vcd, nv, nuv)
    names = [s.decode("latin-1") for s in b[dl + dl_size:].split(b"\0") if s.strip()]
    used = np.array(sorted({c[0] for t in tris for c in t}), dtype=np.int64)
    used_n = np.array(sorted({c[1] for t in tris for c in t}), dtype=np.int64)
    return {"used": used, "used_normal_length": float(ln[used_n].mean()) if len(used_n) else 0.0, "positions": (raw[:, :3] / float(1 << frac)).astype(np.float32),
            "normals": (nrm_raw / np.where(ln == 0, 1, ln)).astype(np.float32), "uvs": uv,
            "triangles": tris, "primitives": prims, "vertex_count": nv, "uv_count": nuv, "bones": _u32(b, dh),
            "vcd": vcd, "fraction_bits": frac, "normal_length": float(ln.mean()) if nv else 0.0,
            "texture": next((s for s in names if s.lower().endswith(".tpl")), None),
            "mesh_name": next((s for s in names if not s.lower().endswith(".tpl")), None)}


def normal_scale_ok(length: float) -> bool:
    """Stored normals are fixed point: |n| is 1024 in most files and 2048 in a few (s308a_m4, ad21_e0)."""
    if length <= 0:
        return False
    k = 2.0 ** round(float(np.log2(length)))
    return k >= 256 and 0.9 * k < length < 1.1 * k


def winding(mesh: dict) -> float:
    """Share of non-degenerate triangles whose counter-clockwise face normal agrees with the vertex normals."""
    if not mesh["triangles"]:
        return 0.0
    t = np.array(mesh["triangles"], dtype=np.int64)          # (n, 3 corners, (pos, nrm, tex))
    p, n = mesh["positions"].astype(np.float64), mesh["normals"].astype(np.float64)
    a, b, c = p[t[:, 0, 0]], p[t[:, 1, 0]], p[t[:, 2, 0]]
    fn = np.cross(b - a, c - a)
    vn = n[t[:, 0, 1]] + n[t[:, 1, 1]] + n[t[:, 2, 1]]
    ok = np.linalg.norm(fn, axis=1) > 1e-9
    return float(((fn * vn).sum(1)[ok] > 0).mean()) if ok.any() else 0.0


# --- GX textures (TPL) ---------------------------------------------------------------------------------------
BLOCK = {0: (8, 8, 4), 1: (8, 4, 8), 2: (8, 4, 8), 3: (4, 4, 16), 4: (4, 4, 16), 5: (4, 4, 16), 6: (4, 4, 32),
         8: (8, 8, 4), 9: (8, 4, 8), 10: (4, 4, 16), 14: (8, 8, 4)}


def parse_tpl(b: bytes) -> list[dict]:
    if len(b) < 12 or _u32(b, 0) != TPL_MAGIC:
        raise FormatError("not a TPL (magic 0x0020AF30)")
    n, tab = _u32(b, 4), _u32(b, 8)
    out = []
    for i in range(n):
        _need(b, tab + 8 * i, 8, "TPL image table")
        ih, ph = struct.unpack_from(">II", b, tab + 8 * i)
        _need(b, ih, 12, "TPL image header")
        h, w, fmt, data = struct.unpack_from(">HHII", b, ih)
        pal = None
        if ph:
            pn, _, _, pfmt, pdata = struct.unpack_from(">HBBII", b, ph)
            _need(b, pdata, 2 * pn, "TPL palette")
            pal = (pfmt, b[pdata:pdata + 2 * pn])
        out.append({"index": i, "width": w, "height": h, "format": fmt, "data_offset": data, "palette": pal})
    return out


def _c565(v):
    v = v.astype(np.uint32)
    return np.stack([((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31,
                     np.full_like(v, 255)], -1).astype(np.uint8)


def _c5a3(v):
    v = v.astype(np.uint32)
    op = (v & 0x8000) != 0
    r = np.where(op, ((v >> 10) & 31) * 255 // 31, ((v >> 8) & 15) * 17)
    g = np.where(op, ((v >> 5) & 31) * 255 // 31, ((v >> 4) & 15) * 17)
    b = np.where(op, (v & 31) * 255 // 31, (v & 15) * 17)
    a = np.where(op, 255, ((v >> 12) & 7) * 255 // 7)
    return np.stack([r, g, b, a], -1).astype(np.uint8)


def _ia(i, a):
    return np.stack([i, i, i, a], -1).astype(np.uint8)


def _palette(pal) -> np.ndarray:
    if pal is None:
        raise FormatError("palettized texture without a palette")
    fmt, d = pal
    v = np.frombuffer(d, ">u2")
    if fmt == 0:
        return _ia(v & 255, v >> 8)
    if fmt == 1:
        return _c565(v)
    if fmt == 2:
        return _c5a3(v)
    raise FormatError(f"palette format {fmt} is not decoded")


def decode_image(b: bytes, img: dict) -> np.ndarray:
    """One TPL image -> (height, width, 4) uint8 RGBA."""
    fmt, w, h = img["format"], img["width"], img["height"]
    if fmt not in BLOCK:
        raise FormatError(f"GX texture format {fmt} is not decoded")
    bw, bh, bpp = BLOCK[fmt]
    W, H = -(-w // bw) * bw, -(-h // bh) * bh
    size = W * H * bpp // 8
    d = b[img["data_offset"]:img["data_offset"] + size]
    if len(d) < size:
        raise FormatError("texture data runs past the end of the file")
    if fmt == 6:
        k = np.frombuffer(d, np.uint8).reshape(-1, 2, 16, 2)
        px = np.stack([k[:, 0, :, 1], k[:, 1, :, 0], k[:, 1, :, 1], k[:, 0, :, 0]], -1)
        out = px.reshape(H // 4, W // 4, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(H, W, 4)
        return np.ascontiguousarray(out[:h, :w])
    if fmt == 14:
        out = np.zeros((H, W, 4), np.uint8)
        o = 0
        for by in range(0, H, 8):
            for bx in range(0, W, 8):
                for sy, sx in ((0, 0), (0, 4), (4, 0), (4, 4)):
                    c0, c1, bits = struct.unpack_from(">HHI", d, o)
                    o += 8
                    p = _c565(np.array([c0, c1])).astype(np.int32)
                    if c0 > c1:
                        pal = [p[0], p[1], (2 * p[0] + p[1]) // 3, (p[0] + 2 * p[1]) // 3]
                    else:
                        pal = [p[0], p[1], (p[0] + p[1]) // 2, np.zeros(4, np.int32)]
                    for j in range(16):
                        out[by + sy + j // 4, bx + sx + j % 4] = pal[(bits >> (30 - 2 * j)) & 3]
        return np.ascontiguousarray(out[:h, :w])
    if fmt in (0, 8):
        a = np.frombuffer(d, np.uint8)
        vals = np.empty(a.size * 2, np.uint32)
        vals[0::2], vals[1::2] = a >> 4, a & 15
    elif fmt in (1, 2, 9):
        vals = np.frombuffer(d, np.uint8).astype(np.uint32)
    else:
        vals = np.frombuffer(d, ">u2").astype(np.uint32)
    px = vals.reshape(H // bh, W // bw, bh, bw).transpose(0, 2, 1, 3).reshape(H, W)
    if fmt in (0, 1):
        i = px * 17 if fmt == 0 else px
        out = _ia(i, i)
    elif fmt == 2:
        out = _ia((px & 15) * 17, (px >> 4) * 17)
    elif fmt == 3:
        out = _ia(px & 255, px >> 8)
    elif fmt == 4:
        out = _c565(px)
    elif fmt == 5:
        out = _c5a3(px)
    else:
        pal = _palette(img["palette"])
        idx = px & 0x3FFF if fmt == 10 else px
        if int(idx.max()) >= len(pal):
            raise FormatError("palette index out of range")
        out = pal[idx]
    return np.ascontiguousarray(out[:h, :w])


def png_bytes(rgba: np.ndarray) -> bytes:
    h, w = rgba.shape[:2]
    raw = b"".join(b"\0" + rgba[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# --- glTF --------------------------------------------------------------------------------------------------
def write_glb(path: Path, parts: list[dict], name: str, extras: dict | None = None) -> Path:
    """parts: {name, mesh (parse_gpl), flip (bool), image (RGBA ndarray or None)} -> one static GLB."""
    bin_, views, accs, meshes, nodes, mats, texs, imgs = bytearray(), [], [], [], [], [], [], []

    def view(data: bytes, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), **({"target": target} if target else {})})
        bin_.extend(data)
        return len(views) - 1

    def acc(arr: np.ndarray, typ: str, ctype=5126, target=34962, minmax=False):
        a = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    for part in parts:
        m, keys, P, N, T, idx = part["mesh"], {}, [], [], [], []
        for tri in m["triangles"]:
            for c in ((tri[0], tri[2], tri[1]) if part.get("flip") else tri):
                k = keys.get(c)
                if k is None:
                    k = keys[c] = len(P)
                    P.append(c[0]); N.append(c[1]); T.append(c[2])
                idx.append(k)
        if not idx:
            continue
        attrs = {"POSITION": acc(np.ascontiguousarray(m["positions"][P], np.float32), "VEC3", minmax=True),
                 "NORMAL": acc(np.ascontiguousarray(m["normals"][N], np.float32), "VEC3")}
        prim = {"attributes": attrs, "indices": acc(np.array(idx, np.uint32), "SCALAR", 5125, 34963)}
        if min(T) >= 0 and len(m["uvs"]):
            attrs["TEXCOORD_0"] = acc(np.ascontiguousarray(m["uvs"][T], np.float32), "VEC2")
            if part.get("image") is not None:
                img = part["image"]
                imgs.append({"bufferView": view(png_bytes(img)), "mimeType": "image/png", "name": part["name"]})
                texs.append({"source": len(imgs) - 1, "sampler": 0})
                mat = {"name": part["name"], "pbrMetallicRoughness": {"baseColorTexture": {"index": len(texs) - 1},
                                                                       "metallicFactor": 0.0, "roughnessFactor": 1.0}}
                if int(img[..., 3].min()) < 255:
                    mat.update(alphaMode="MASK", alphaCutoff=0.5)
                mats.append(mat)
                prim["material"] = len(mats) - 1
        meshes.append({"name": part["name"], "primitives": [prim]})
        nodes.append({"name": part["name"], "mesh": len(meshes) - 1})
    gl = {"asset": {"version": "2.0", "generator": "gbox.defjam_vendetta", **({"extras": extras} if extras else {})},
          "scene": 0, "scenes": [{"name": name, "nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes,
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(bin_)}]}
    if mats:
        gl.update(materials=mats, textures=texs, images=imgs, samplers=[{"wrapS": 10497, "wrapT": 10497}])
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(bin_) % 4:
        bin_.append(0)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


# --- disc inventory and extraction ------------------------------------------------------------------------------
def inventory(disc) -> dict:
    """Bounded inventory of model sources on the disc (GCDisc): fighter costume dirs, crowd models, stages."""
    fighters: dict[str, dict] = {}
    for n in disc.files:
        m = re.match(r"data/(s(\d{3})([a-z]))/\1_m(\d+)\.(gpl|skn|act|tpl)$", n)
        if m:
            f = fighters.setdefault(m[1], {"dir": m[1], "fighter": m[2], "costume": m[3], "parts": {}})
            f["parts"].setdefault(int(m[4]), []).append(m[5])
    crowd = sorted(re.match(r"data/aud/(.+)\.gpl$", n)[1] for n in disc.files if re.match(r"data/aud/.+\.gpl$", n))
    return {"fighter_dirs": [fighters[k] for k in sorted(fighters)],
            "fighters": sorted({f["fighter"] for f in fighters.values()}), "crowd": crowd,
            "stages": sorted(n for n in disc.files if n.lower().endswith(".arn")),
            "animation_banks": sorted(n for n in disc.files if n.lower().endswith(".anx"))}


def _find(disc, folder: str, base: str | None):
    if not base:
        return None
    for n in (f"{folder}/{base}",):
        if n in disc.files:
            return n
    low = base.lower()
    return next((n for n in sorted(disc.files) if n.lower().rsplit("/", 1)[-1] == low), None)


def extract_model(disc, folder: str, stem: str, out: Path) -> dict:
    """All parts `folder/stem_mK.gpl` (fighter costume dir, or one crowd model) -> one static GLB + checks."""
    files = sorted(n for n in disc.files if re.fullmatch(rf"{re.escape(folder)}/{re.escape(stem)}(_m\d+)?\.gpl", n))
    if not files:
        raise FormatError(f"no .gpl under {folder} for {stem}")
    parts, report = [], []
    for n in files:
        m = parse_gpl(disc.read(n))
        k = re.search(r"_m(\d+)\.gpl$", n)
        w = winding(m)
        flip = w < 0.5
        tex = _find(disc, folder, m["texture"])
        image, tex_err = None, None
        if tex:
            try:
                image = decode_image(disc.read(tex), parse_tpl(disc.read(tex))[0])
            except FormatError as e:
                tex_err = str(e)
        pos = m["positions"][m["used"]] if len(m["used"]) else m["positions"]
        label = (m["mesh_name"] or n.rsplit("/", 1)[-1]).split("-", 1)[-1]
        rec = {"file": n, "part": int(k[1]) if k else None, "role": PART_ROLES.get(int(k[1])) if k else "crowd",
               "mesh_name": m["mesh_name"], "vertices": m["vertex_count"], "uvs": m["uv_count"],
               "triangles": len(m["triangles"]), "primitives": m["primitives"], "bones": m["bones"],
               "vcd": f"0x{m['vcd']:04x}", "normal_length": round(m["used_normal_length"], 1),
               "winding": round(max(w, 1 - w), 4), "flipped": flip, "texture": m["texture"], "texture_file": tex,
               "texture_error": tex_err, "bbox": [pos.min(0).round(2).tolist(), pos.max(0).round(2).tolist()]}
        rec["verified"] = bool(rec["triangles"] and rec["winding"] >= MIN_WINDING and normal_scale_ok(rec["normal_length"]))
        report.append(rec)
        parts.append({"name": f"{stem}_{rec['role'] or 'part'}_{label}", "mesh": m, "flip": flip, "image": image})
    body = next((r for r in report if r["part"] == 0), report[0])
    lo, hi = np.array(body["bbox"][0]), np.array(body["bbox"][1])
    pad = (hi - lo) * 0.1
    for r in report:                                       # model space: every part sits on the body, not at a joint
        c = (np.array(r["bbox"][0]) + np.array(r["bbox"][1])) / 2
        r["inside_body_bbox"] = bool(((c >= lo - pad) & (c <= hi + pad)).all())
    glb = write_glb(out, parts, stem, {"source": "Def Jam Vendetta GDTE69 rev 0", "files": files,
                                       "units": "s16 / 2^fraction_bits game units, unrigged bind pose"})
    ok = all(r["verified"] and r["inside_body_bbox"] for r in report)
    return {"model": stem, "folder": folder, "glb": str(glb), "verified": ok, "parts": report,
            "height": round(float(hi[1] - lo[1]), 2)}


def extract_all(iso, out_dir: Path) -> dict:
    from .gcdisc import GCDisc
    disc = GCDisc(iso)
    inv = inventory(disc)
    out_dir = Path(out_dir)
    jobs = [(f"data/{f['dir']}", f["dir"]) for f in inv["fighter_dirs"]] + [("data/aud", c) for c in inv["crowd"]]
    results = []
    for folder, stem in jobs:
        try:
            results.append(extract_model(disc, folder, stem, out_dir / f"{stem}.glb"))
        except FormatError as e:
            results.append({"model": stem, "folder": folder, "verified": False, "error": str(e)})
    man = {"identity": identify(iso), "inventory": {k: (len(v) if isinstance(v, list) else v) for k, v in inv.items()},
           "verified": sum(r["verified"] for r in results), "total": len(results), "models": results}
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1))
    return man


FIGHTER_DIRS = ("s000a s000b s000c s001a s001b s001c s003a s003b s003c s004a s004b s004c s100a s101a s102a s103a "
                "s104a s105a s106a s106b s107a s107b s108a s109a s110a s111a s111b s112a s113a s114a s115a s116a "
                "s117a s118a s118b s200b s200c s300a s301a s303a s304a s305a s306a s307a s308a s309a s310a s311a "
                "s312a s400a s400b s401a s402a s501a s502a s503a s504a s505a").split()


def roster() -> list[dict]:
    """The 58 fighter costume directories of GDTE69 rev 0. Display names are not decoded yet (ids only)."""
    return [{"key": d, "slug": f"djv_{d}", "name": f"Def Jam Vendetta fighter {d[1:4]} costume {d[4]}",
             "aliases": [d, f"Def Jam Vendetta {d}"], "kind": "character"} for d in FIGHTER_DIRS]


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED hook: one costume directory -> verified static GLB (no rig: roles stay empty)."""
    from . import characters as C
    from .gcdisc import GCDisc
    iso = C._gc_iso(ctx, game)
    ident = identify(iso)
    if not ident["exact_build"]:
        raise FormatError(f"{ident['game_id']} rev {ident['revision']}: the reader is verified on {DISC_ID} rev 0 only")
    r = extract_model(GCDisc(iso), f"data/{e['key']}", e["key"], Path(work) / f"{e['slug']}.glb")
    bad = [p["file"] for p in r["parts"] if not (p["verified"] and p["inside_body_bbox"])]
    if bad:
        raise FormatError(f"{e['key']}: parts failed verification: {', '.join(bad)}")
    return {"files": [Path(r["glb"])], "roles": {}, "tool": "gbox.defjam_vendetta",
            "source_files": [p["file"] for p in r["parts"]] + sorted({p["texture_file"] for p in r["parts"] if p["texture_file"]}),
            "notes": (f"Native GDTE69 rev 0 meshes, {sum(p['triangles'] for p in r['parts'])} triangles, static bind pose. "
                      "Skeleton (.act) and weights (.skn) are not decoded, so the model is not retargetable yet.")}


if __name__ == "__main__":
    import sys
    m = extract_all(sys.argv[1], Path(sys.argv[2]))
    print(json.dumps({k: m[k] for k in ("identity", "inventory", "verified", "total")}, indent=1))
