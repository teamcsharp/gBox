"""Super Mario 64 (N64, USA ROM): write a new Mario model into a copy of the ROM (the injection side of gbox.sm64_mario).

Input: rigid parts on Mario's 20 animated joints (sm64_mario joint order j00..j19) - triangles in each joint's local
space plus materials (a colour, or an RGBA texture). Typical source: a character retargeted onto Mario's skeleton with
scripts/retarget_rigid.py (target = `python -m gbox.sm64_mario rom mario.gltf --anim 197`, the standing idle pose),
read back from that .glb by `parts_from_glb`.

What gets written (never to the original ROM):
  * Fast3D (F3D) display lists, one per joint: G_VTX batches of <= 16 vertices (x, y, z, s, t, normal), G_TRI1,
    per material gsSPLight x2 (+ NumLights 1) and a combiner: textured = G_CC_MODULATERGB (TEXEL0 * SHADE) with a
    LoadBlock RGBA16 texture (downscaled so it fits the 4 KB TMEM: <= 2048 texels, power-of-two sides, wrap),
    untextured = G_CC_SHADE with the colour in the lights. Back-face culling is off while the model draws; texture and
    combiner are restored to the SM64 default (texture off, G_CC_SHADE) at the end of every list.
  * Segment 0x04 (group0: Mario + common data) becomes the original decompressed MIO0 block + the new data appended,
    stored raw in extended ROM space (0x800000+, ROM padded to 24 MB like the sm64extend hacks), and the main level
    script's LOAD_MIO0(0x04) at 0x28CEE0 is rewritten to LOAD_RAW (0x17) of that range. Mario's old data stays where
    it was, so every other reference into segment 0x04 (caps, effects, other objects) still works.
  * Mario's geo layout (segment 0x17, raw at 0x108590) is patched in place: each animated part (cmd 0x13) gets its
    joint's new display list (switch cases restart the joint count, so every hand / cap / eye / body variant of the
    cap-effect switch gets the same parts), every other display list in the layout (eyes, caps, wings, hands under
    scalers) is set to NULL, which the geo processor skips.
  * The CIC-6102 header CRC (0x10/0x14, over 0x1000..0x101000) is recomputed (the patches above lie outside that
    range, so it normally stays the same; it is fixed anyway).
Memory: the new data is loaded into SM64's main pool together with group0 (about 220 KB + the model); keep the model
around <= 2000 triangles / a few 64x32 textures.

  python -m gbox.sm64_writer roundtrip rom.z64 out.z64          # Mario re-encoded by this writer, read back, compared
  python -m gbox.sm64_writer inject rom.z64 model.glb out.z64 [--anim 197]
  python -m gbox.sm64_writer mod <gbox cache> rom.z64 model.glb <mod name> "<image name>.z64" [--game-id ...]
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import numpy as np

from . import sm64_mario as sm

ROM_EXT = 0x1800000                                         # extended ROM size (24 MB)
DATA_AT = 0x800000                                          # new segment 0x04 copy in extended space
MARIO_END = 0x1CD20                                         # segment 0x04 [0, this): Mario's own model data only
                                                            # (nothing outside his geo layout points into it)
GAME_ID = "b7aecee966090bfa"                                # Super Mario 64 (USA) in the gBox catalog


# ---------------------------------------------------------------- CRC (CIC-6102)

def crc6102(rom: bytes) -> tuple[int, int]:
    m = 0xFFFFFFFF
    t1 = t2 = t3 = t4 = t5 = t6 = 0xF8CA4DDC
    words = struct.unpack_from(">262144I", rom, 0x1000)
    for d in words:
        t = (t6 + d) & m
        if t < t6:
            t4 = (t4 + 1) & m
        t6 = t
        t3 ^= d
        s = d & 0x1F
        r = ((d << s) | (d >> (32 - s))) & m if s else d
        t5 = (t5 + r) & m
        t2 = t2 ^ r if t2 > d else t2 ^ t6 ^ d
        t1 = (t1 + (t5 ^ d)) & m
    return t6 ^ t4 ^ t3, t5 ^ t2 ^ t1


def fix_crc(rom: bytearray) -> bytearray:
    struct.pack_into(">II", rom, 0x10, *crc6102(rom))
    return rom


# ---------------------------------------------------------------- textures

def png_decode(data: bytes) -> np.ndarray:
    """Minimal PNG reader (8-bit grey/RGB/RGBA/palette, non-interlaced) -> (h, w, 4) uint8. No PIL on the Spark venv."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    o, idat, plte, trns = 8, b"", None, None
    while o < len(data):
        n, typ = struct.unpack_from(">I4s", data, o)
        body = data[o + 8:o + 8 + n]
        if typ == b"IHDR":
            w, h, depth, ctype, _c, _f, inter = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and inter == 0, "PNG: only 8-bit non-interlaced"
        elif typ == b"PLTE":
            plte = np.frombuffer(body, np.uint8).reshape(-1, 3)
        elif typ == b"tRNS":
            trns = np.frombuffer(body, np.uint8)
        elif typ == b"IDAT":
            idat += body
        o += 12 + n
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = w * ch
    img = np.zeros((h, stride), np.int32)
    prev = np.zeros(stride, np.int32)
    p = 0
    for y in range(h):
        f = raw[p]
        line = np.frombuffer(raw, np.uint8, stride, p + 1).astype(np.int32)
        p += 1 + stride
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:                                               # 1 sub, 3 average, 4 paeth: left-dependent, per byte
            cur = np.zeros(stride, np.int32)
            for x in range(stride):
                a = cur[x - ch] if x >= ch else 0
                b, c = prev[x], (prev[x - ch] if x >= ch else 0)
                if f == 1:
                    pr = a
                elif f == 3:
                    pr = (a + b) >> 1
                else:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[x] = (line[x] + pr) & 255
        img[y] = cur
        prev = cur
    img = img.astype(np.uint8).reshape(h, w, ch)
    if ctype == 3:
        al = np.full(len(plte), 255, np.uint8)
        if trns is not None:
            al[:len(trns)] = trns
        return np.concatenate([plte[img[..., 0]], al[img[..., 0]][..., None]], -1)
    if ctype == 0:
        img = np.repeat(img, 3, -1)
    elif ctype == 4:
        img = np.concatenate([np.repeat(img[..., :1], 3, -1), img[..., 1:]], -1)
    if img.shape[2] == 3:
        img = np.concatenate([img, np.full((h, w, 1), 255, np.uint8)], -1)
    return img


def fit_tmem(img: np.ndarray, max_texels: int = 2048) -> np.ndarray:
    """Power-of-two sides (nearest), then halve the longer side (2x box filter) until it fits RGBA16 in 4 KB TMEM."""
    h, w = img.shape[:2]
    p2 = lambda n: 1 << max(0, int(np.floor(np.log2(max(1, n)))))
    if (p2(w), p2(h)) != (w, h):
        ys = (np.arange(p2(h)) * h // p2(h))
        xs = (np.arange(p2(w)) * w // p2(w))
        img = img[ys][:, xs]
    img = img.astype(np.float32)
    while img.shape[0] * img.shape[1] > max_texels:
        if img.shape[1] >= img.shape[0]:
            img = (img[:, 0::2] + img[:, 1::2]) / 2
        else:
            img = (img[0::2] + img[1::2]) / 2
    return np.clip(np.round(img), 0, 255).astype(np.uint8)


def rgba16(img: np.ndarray) -> bytes:
    r, g, b, a = (img[..., i].astype(np.uint16) for i in range(4))
    v = ((r >> 3) << 11) | ((g >> 3) << 6) | ((b >> 3) << 1) | (a >= 128)
    return v.astype(">u2").tobytes()


# ---------------------------------------------------------------- F3D encoding

def _w(*ws) -> bytes:
    return struct.pack(f">{len(ws)}I", *ws)


CC_MODULATERGB = _w(0xFC127E24, 0xFFFFF9FC)
CC_SHADE = _w(0xFCFFFFFF, 0xFFFE793C)
PIPESYNC = _w(0xE7000000, 0)
LOADSYNC = _w(0xE6000000, 0)
ENDDL = _w(0xB8000000, 0)
G_CULL_BACK = 0x2000


def tex_load(addr: int, w: int, h: int) -> bytes:
    """gsDPLoadTextureBlock(addr, G_IM_FMT_RGBA, G_IM_SIZ_16b, w, h, 0, wrap, wrap, log2 w, log2 h, 0, 0)."""
    ms, mt = int(np.log2(w)), int(np.log2(h))
    dxt = (2048 + max(1, w * 2 // 8) - 1) // max(1, w * 2 // 8)
    tile = lambda t, line: _w(0xF5000000 | (0 << 21) | (2 << 19) | (line << 9), (t << 24) | (mt << 14) | (ms << 4))
    return (_w(0xFD000000 | (2 << 19), addr) + tile(7, 0) + LOADSYNC +
            _w(0xF3000000, (7 << 24) | ((w * h - 1) << 12) | dxt) + PIPESYNC + tile(0, (w * 2 + 7) >> 3) +
            _w(0xF2000000, (((w - 1) << 2) << 12) | ((h - 1) << 2)))


def lights(diffuse, ambient, direction=(0x28, 0x28, 0x28)) -> bytes:
    """Lights1: Ambient (8 bytes) then Light (16 bytes)."""
    a = bytes(ambient) + b"\0" + bytes(ambient) + b"\0"
    d = bytes(diffuse) + b"\0" + bytes(diffuse) + b"\0" + bytes(np.array(direction, np.int8).view(np.uint8)) + b"\0" + bytes(4)
    return a + d


def build(parts: dict, materials: list, base: int) -> tuple[bytes, dict]:
    """parts {joint: [(material, ((pos, nrm, uv), x3))]} (joint-local) -> (blob placed at segmented address `base`,
    {joint: segmented address of its display list}). materials: [{"diffuse", "ambient", "tex": (h, w, 4) or None}]."""
    blob = bytearray()

    def put(b: bytes, align=8) -> int:
        blob.extend(bytes((-len(blob)) % align))
        o = len(blob)
        blob.extend(b)
        return base + o
    mat_addr = []
    for m in materials:
        t = None
        if m.get("tex") is not None:
            img = fit_tmem(m["tex"])
            t = (put(rgba16(img)), img.shape[1], img.shape[0])
        mat_addr.append((put(lights(m["diffuse"], m["ambient"]), 8), t))
    dls = {}
    for j, tris in sorted(parts.items()):
        if not tris:
            continue
        out = [_w(0xB6000000, G_CULL_BACK), _w(0xBC000002, 0x80000040)]
        by_mat = {}
        for mi, tri in tris:
            by_mat.setdefault(mi, []).append(tri)
        for mi, mtris in by_mat.items():
            la, tex = mat_addr[mi]
            out.append(PIPESYNC)
            out.append(_w(0x03860010, la + 8) + _w(0x03880010, la))
            if tex:
                out += [CC_MODULATERGB, _w(0xBB000001, 0xFFFFFFFF), tex_load(*tex)]
                tw, th = tex[1], tex[2]
            else:
                out += [CC_SHADE, _w(0xBB000000, 0xFFFFFFFF)]
                tw = th = 32
            batch, cache, pend = [], {}, []

            def flush():
                if not batch:
                    return
                va = put(b"".join(batch), 16)
                out.append(_w(0x04000000 | ((len(batch) - 1) << 20) | (len(batch) * 16), va))
                out.extend(pend)
                batch.clear(), cache.clear(), pend.clear()
            for tri in mtris:
                uv = np.array([v[2] for v in tri], float)
                off = np.floor(uv.min(0))                   # wrap: keep s/t small (s16, S10.5)
                vs = []
                for (p, n, _), (u, v) in zip(tri, uv - off):
                    s = int(np.clip(round(u * tw * 32), -32768, 32767))
                    t = int(np.clip(round(v * th * 32), -32768, 32767))
                    nn = np.clip(np.round(np.asarray(n, float) * 127), -128, 127).astype(np.int8).view(np.uint8)
                    pp = np.clip(np.round(p), -32768, 32767).astype(int)
                    vs.append(struct.pack(">hhhHhh4B", *pp, 0, s, t, *nn, 255))
                new = [v for v in dict.fromkeys(vs) if v not in cache]
                if len(cache) + len(new) > 16:
                    flush()
                for v in vs:
                    if v not in cache:
                        cache[v] = len(batch)
                        batch.append(v)
                i0, i1, i2 = (cache[v] for v in vs)
                pend.append(_w(0xBF000000, (i0 * 10 << 16) | (i1 * 10 << 8) | i2 * 10))
            flush()
        out += [PIPESYNC, _w(0xBB000000, 0xFFFFFFFF), CC_SHADE, _w(0xB7000000, G_CULL_BACK), ENDDL]
        dls[j] = put(b"".join(out), 8)
    blob.extend(bytes((-len(blob)) % 16))
    return bytes(blob), dls


# ---------------------------------------------------------------- ROM patching

def _patch_geo(rom: bytearray, mem: sm.Mem, dls: dict) -> list[int]:
    """Point every animated part at its joint's new list, NULL every other list. -> joint count per body variant."""
    tree = sm.geo_tree(mem, sm.MARIO_GEO)
    counts = []

    def rom_off(addr):
        assert addr >> 24 == 0x17, hex(addr)
        return sm.SEG17[0] + (addr & 0xFFFFFF)

    def walk(n, k):
        c = n["cmd"]
        if c == 0x13:
            o = rom_off(n["addr"])
            dl = dls.get(k, 0)
            if dl and not n["dl"]:
                rom[o + 1] = 1                              # layer: opaque
            struct.pack_into(">I", rom, o + 8, dl)
            k += 1
        elif n.get("dl"):
            struct.pack_into(">I", rom, rom_off(n["addr"]) + n["size"] - 4, 0)
        if c == 0x0E:                                       # one case is drawn: each case starts at the same joint
            ends = [walk(ch, k) for ch in n["children"]]
            if len(set(ends)) > 1:
                counts.append(sorted(set(e - k for e in ends)))
            return ends[0] if ends else k
        lods = []
        for ch in n["children"]:
            if ch["cmd"] == 0x0D:                           # LOD siblings: one draws, each starts at the same joint
                lods.append(walk(ch, k))
            else:
                k = walk(ch, k)
        if len(set(lods)) > 1:
            counts.append(sorted(set(e - k for e in lods)))
        return max(lods + [k])
    total = walk(tree, 0)
    assert not counts, f"switch cases with different joint counts: {counts}"
    return [total]


def inject(rom: bytes, parts: dict, materials: list) -> bytes:
    """-> a new ROM (extended to 24 MB) whose Mario draws `parts`."""
    assert rom[:4] == b"\x80\x37\x12\x40", "need a big-endian .z64 ROM"
    mem = sm.Mem(rom)
    seg4 = bytearray(sm.mio0(rom, sm.SEG04[0]))             # always rebuild from the original MIO0 block
    seg4.extend(bytes((-len(seg4)) % 16))
    blob, dls = build(parts, materials, 0x04000000)
    if len(blob) > MARIO_END:
        raise ValueError(f"model data {len(blob)} bytes > the {MARIO_END} of Mario's own data it replaces "
                         "(fewer triangles / smaller textures)")
    seg4[:len(blob)] = blob                                 # in place over Mario's old data: the pool size stays
    end = len(rom.rstrip(rom[-1:]))                         # the ROM's padding: 0xFF (or 0x01 after sm64extend)
    at = (end + 0xFFFF) & ~0xFFFF
    if at + len(seg4) <= len(rom):                          # fits in the ROM's own padding: keep its size
        out = bytearray(rom)
    else:                                                   # else extend like sm64extend (24 MB, 0x01 fill)
        at = max(DATA_AT, len(rom))
        out = bytearray(rom) + b"\x01" * (ROM_EXT - len(rom))
    out[at:at + len(seg4)] = seg4
    DATA = at
    struct.pack_into(">BBHII", out, sm.LOAD_SEG04, 0x17, 0x0C, 0x0004, DATA, DATA + len(seg4))
    counts = _patch_geo(out, mem, dls)
    assert all(c == 20 for c in counts), f"Mario body variants with {counts} joints (expected 20)"
    from .sm64_startup import apply as native_startup
    out,_startup=native_startup(bytes(out))
    return bytes(fix_crc(bytearray(out)))


# ---------------------------------------------------------------- inputs

def parts_from_extract(model: dict) -> tuple[dict, list]:
    """sm64_mario.extract() output -> writer input (Mario re-encoded: the round-trip test)."""
    mats, key_ix, parts = [], {}, {}
    for j, jt in enumerate(model["joints"]):
        for key, tri in jt["tris"]:
            if key not in key_ix:
                diff, amb, tex = key
                key_ix[key] = len(mats)
                mats.append({"diffuse": diff, "ambient": amb, "tex": model["textures"][tex] if tex else None})
            tex = key[2]
            vs = []
            for p, c, (s, t) in tri:
                n = np.array(c[:3], np.uint8).view(np.int8).astype(float) / 127
                uv = (s / 32 / tex[3], t / 32 / tex[4]) if tex else (0.0, 0.0)
                vs.append((p, n, uv))
            parts.setdefault(j, []).append((key_ix[key], tuple(vs)))
    return parts, mats


def _glb(path):
    d = Path(path).read_bytes()
    n = struct.unpack_from("<I", d, 12)[0]
    gl = json.loads(d[20:20 + n])
    bin_ = d[20 + n + 8:]
    ct = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
    nc = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    def acc(i):
        a = gl["accessors"][i]
        bv = gl["bufferViews"][a["bufferView"]]
        dt, k = np.dtype(ct[a["componentType"]]), nc[a["type"]]
        stride = bv.get("byteStride", dt.itemsize * k)
        o = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        arr = np.lib.stride_tricks.as_strided(np.frombuffer(bin_, dt, offset=o), (a["count"], k), (stride, dt.itemsize))
        arr = np.array(arr)
        if a.get("normalized"):
            arr = arr.astype(np.float32) / np.iinfo(dt).max
        return arr

    def view(i):
        bv = gl["bufferViews"][i]
        return bin_[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
    return gl, acc, view


def _node_world(gl):
    par = {c: i for i, n in enumerate(gl["nodes"]) for c in n.get("children", [])}

    def local(n):
        if "matrix" in n:
            return np.array(n["matrix"], float).reshape(4, 4).T
        x, y, z, w = n.get("rotation", [0, 0, 0, 1])
        m = np.eye(4)
        m[:3, :3] = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                              [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                              [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]) * n.get("scale", [1, 1, 1])
        m[:3, 3] = n.get("translation", [0, 0, 0])
        return m
    memo = {}

    def world(i):
        if i not in memo:
            memo[i] = (world(par[i]) if i in par else np.eye(4)) @ local(gl["nodes"][i])
        return memo[i]
    return world


def parts_from_glb(path, rom: bytes, anim: int = 197, ambient=(0x80, 0x80, 0x80), diffuse=(0xFF, 0xFF, 0xFF)) -> tuple[dict, list]:
    """A glb skinned to Mario's joints (names j00..j19, as scripts/retarget_rigid.py writes it against
    `sm64_mario --anim <anim>`) -> writer input, every vertex rigid on its strongest joint, moved into that joint's
    local space for the same pose."""
    gl, acc, view = _glb(path)
    world = _node_world(gl)
    model = sm.extract(rom, anim)
    W = [jt["world"] for jt in model["joints"]]             # row-vector world matrices of the pose
    mats, mat_ix, parts = [], {}, {}
    for ni, node in enumerate(gl["nodes"]):
        if "mesh" not in node:
            continue
        skin = gl["skins"][node["skin"]] if "skin" in node else None
        if skin:
            jn = [int(gl["nodes"][j]["name"].lstrip("j")) for j in skin["joints"]]
            ibm = acc(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
            skin_m = [world(j) @ ibm[k] for k, j in enumerate(skin["joints"])]
        for pr in gl["meshes"][node["mesh"]]["primitives"]:
            a = pr["attributes"]
            P, N = acc(a["POSITION"]).astype(float), acc(a["NORMAL"]).astype(float)
            UV = acc(a["TEXCOORD_0"]).astype(float) if "TEXCOORD_0" in a else np.zeros((len(P), 2))
            idx = acc(pr["indices"]).reshape(-1) if "indices" in pr else np.arange(len(P))
            if skin:
                J, Wt = acc(a["JOINTS_0"]), acc(a["WEIGHTS_0"])
                own = np.array([J[i][int(np.argmax(Wt[i]))] for i in range(len(P))])
                M = np.array([skin_m[o] for o in own])
                joint = np.array([jn[o] for o in own])
            else:
                M = np.repeat(world(ni)[None], len(P), 0)
                joint = np.full(len(P), 1)
            Pw = np.einsum("nij,nj->ni", M, np.c_[P, np.ones(len(P))])[:, :3]
            Nw = np.einsum("nij,nj->ni", M[:, :3, :3], N)
            mi = pr.get("material")
            if mi not in mat_ix:
                md = gl["materials"][mi] if mi is not None else {}
                pbr = md.get("pbrMetallicRoughness", {})
                col = np.array(pbr.get("baseColorFactor", [1, 1, 1, 1]))[:3]
                tex = None
                if "baseColorTexture" in pbr:
                    img = gl["images"][gl["textures"][pbr["baseColorTexture"]["index"]]["source"]]
                    tex = png_decode(view(img["bufferView"]))
                    if (col < 0.999).any():
                        tex = tex.copy()
                        tex[..., :3] = (tex[..., :3] * col).astype(np.uint8)
                    m = {"diffuse": diffuse, "ambient": ambient, "tex": tex}
                else:
                    c = (col * 255).astype(int)
                    m = {"diffuse": tuple(int(v) for v in c), "ambient": tuple(int(v) // 2 for v in c), "tex": None}
                mat_ix[mi] = len(mats)
                mats.append(m)
            for k in range(0, len(idx) - 2, 3):
                tri = idx[k:k + 3]
                j = int(np.bincount(joint[tri]).argmax())   # a triangle is rigid on one joint
                inv = np.linalg.inv(W[j])
                vs = []
                for i in tri:
                    p = (np.r_[Pw[i], 1.0] @ inv)[:3]
                    n = Nw[i] @ inv[:3, :3]
                    vs.append((p, n / (np.linalg.norm(n) or 1), tuple(UV[i])))
                parts.setdefault(j, []).append((mat_ix[mi], tuple(vs)))
    return parts, mats


def write_mod(cache, rom_path, glb, name: str, image_name: str, game_id: str = GAME_ID, anim: int = 197) -> dict:
    """A gBox file mod (cache/mods/<game_id>/<name>/<image_name> + .gbox-mod.json): launch_game(mod=<name>)."""
    import time
    rom = Path(rom_path).read_bytes()
    parts, mats = parts_from_glb(glb, rom, anim)
    out = inject(rom, parts, mats)
    d = Path(cache) / "mods" / game_id / name
    d.mkdir(parents=True, exist_ok=True)
    (d / image_name).write_bytes(out)
    meta = {"name": name, "game_id": game_id, "image": image_name, "files": ["@image: Mario model (gbox.sm64_writer)"],
            "built": time.time(), "source": str(glb), "triangles": sum(len(v) for v in parts.values())}
    (d / ".gbox-mod.json").write_text(json.dumps(meta))
    return {"mod": name, "dir": str(d), "image": str(d / image_name), "triangles": meta["triangles"],
            "joints": sorted(parts), "materials": len(mats)}


def roundtrip(rom: bytes) -> dict:
    """Mario -> writer -> ROM -> sm64_mario reader: same joints, triangle counts and positions."""
    a = sm.extract(rom, 197)
    parts, mats = parts_from_extract(a)
    new = inject(rom, parts, mats)
    b = sm.extract(new, 197)
    ok, worst = len(a["joints"]) == len(b["joints"]), 0.0
    for ja, jb in zip(a["joints"], b["joints"]):
        if len(ja["tris"]) != len(jb["tris"]):              # triangles are regrouped by material: compare as sets
            ok = False
            continue
        sa = sorted(tuple(np.ravel([p for p, _, _ in t])) for _, t in ja["tris"])
        sb = sorted(tuple(np.ravel([p for p, _, _ in t])) for _, t in jb["tris"])
        if sa:
            worst = max(worst, float(np.abs(np.array(sa) - np.array(sb)).max()))
    return {"ok": ok and worst == 0, "joints": len(b["joints"]), "tris": sum(len(j["tris"]) for j in b["joints"]),
            "max_pos_err": worst, "textures": len(b["textures"]), "crc": [hex(v) for v in crc6102(new)],
            "crc_orig_ok": crc6102(rom) == struct.unpack_from(">II", rom, 0x10), "size": len(new), "rom": new}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("roundtrip")
    r.add_argument("rom")
    r.add_argument("out", nargs="?")
    i = sub.add_parser("inject")
    i.add_argument("rom")
    i.add_argument("glb")
    i.add_argument("out")
    i.add_argument("--anim", type=int, default=197)
    m = sub.add_parser("mod")
    m.add_argument("cache")
    m.add_argument("rom")
    m.add_argument("glb")
    m.add_argument("name")
    m.add_argument("image_name")
    m.add_argument("--game-id", default=GAME_ID)
    m.add_argument("--anim", type=int, default=197)
    a = ap.parse_args()
    if a.cmd == "roundtrip":
        res = roundtrip(Path(a.rom).read_bytes())
        if a.out:
            Path(a.out).write_bytes(res["rom"])
        res.pop("rom")
        print(json.dumps(res, indent=1))
    elif a.cmd == "inject":
        rom = Path(a.rom).read_bytes()
        parts, mats = parts_from_glb(a.glb, rom, a.anim)
        Path(a.out).write_bytes(inject(rom, parts, mats))
        print(a.out, sum(len(v) for v in parts.values()), "triangles on joints", sorted(parts), len(mats), "materials")
    else:
        print(json.dumps(write_mod(a.cache, a.rom, a.glb, a.name, a.image_name, a.game_id, a.anim), indent=1))
