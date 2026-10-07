"""Super Mario 64 (N64, USA ROM) -> Mario as a rigged glTF, read straight from the operator's ROM (no decomp, no Fast64).

  ROM (US .z64): main level script loads segment 0x04 = MIO0 block 0x0F5330-0x108590 (group0 model data) and segment
  0x17 = raw 0x108590-0x10B3C0 (group0 geo layouts); LOAD_MODEL_FROM_GEO(MODEL_MARIO=1, 0x17002DD4).
  Mario animations: DMA table at 0x4CE710 (u32 count 0xD1, pad, then (offset, size) per animation).

Pipeline: MIO0 decode -> geo layout walk (animated parts = joints, switch nodes take case 0, LOD = nearest) -> F3D display
lists (vertex cache, TRI1, lights = material colour, SETTIMG/SETTILE/LOADBLOCK textures RGBA16/IA/I) -> one rigid
joint per animated part. The rest pose is the first frame of a Mario animation (SM64 limbs point along +X with zero
rotation; the game always animates them), applied with SM64's row-vector rotate_xyz_and_translate.
Output glTF: nodes j00..jNN (tree of animated parts), mesh weighted 100% to its part, textures as PNG data URIs,
plain material colours from the F3D lights; SM64 units (Mario ~ 160 tall incl. the 0.25 geo scale is NOT applied).
"""
from __future__ import annotations

import base64
import io
import json
import struct
from pathlib import Path

import numpy as np

SEG04 = (0x0F5330, 0x108590)
SEG17 = (0x108590, 0x10B3C0)
MARIO_GEO = 0x17002DD4
ANIM_TABLE = 0x4CE710


def mio0(d: bytes, o: int = 0) -> bytes:
    assert d[o:o + 4] == b"MIO0"
    size, comp, raw = struct.unpack_from(">III", d, o + 4)
    out = bytearray()
    bits_p, comp_p, raw_p = o + 16, o + comp, o + raw
    word, nbits = 0, 0
    while len(out) < size:
        if nbits == 0:
            word = struct.unpack_from(">I", d, bits_p)[0]
            bits_p += 4
            nbits = 32
        bit = word & 0x80000000
        word = (word << 1) & 0xFFFFFFFF
        nbits -= 1
        if bit:
            out.append(d[raw_p])
            raw_p += 1
        else:
            v = struct.unpack_from(">H", d, comp_p)[0]
            comp_p += 2
            ln, back = (v >> 12) + 3, (v & 0xFFF) + 1
            for _ in range(ln):
                out.append(out[-back])
    return bytes(out)


LOAD_SEG04 = 0x28CEE0                                       # main level script: LOAD_MIO0(0x04, group0) (12 bytes)


class Mem:
    def __init__(self, rom: bytes):
        self.rom = rom
        cmd, _ln, seg, start, end = struct.unpack_from(">BBHII", rom, LOAD_SEG04)
        if (cmd, seg) == (0x17, 0x04):                      # rewritten by gbox.sm64_writer: LOAD_RAW of an extended copy
            seg04 = rom[start:end]
        else:
            seg04 = mio0(rom, SEG04[0])
        self.seg = {0x04: seg04, 0x17: rom[SEG17[0]:SEG17[1]]}

    def at(self, addr: int, n: int) -> bytes:
        s, o = addr >> 24, addr & 0xFFFFFF
        return self.seg[s][o:o + n]

    def u32(self, a):
        return struct.unpack(">I", self.at(a, 4))[0]


# ---------------------------------------------------------------- geo layout

GEO_SIZE = {0x01: 4, 0x03: 4, 0x04: 4, 0x05: 4, 0x06: 4, 0x07: 4, 0x08: 12, 0x09: 4, 0x0B: 4, 0x0C: 4, 0x0D: 8,
            0x0E: 8, 0x0F: 0x14, 0x13: 12, 0x15: 8, 0x16: 8, 0x17: 4, 0x18: 8, 0x19: 8, 0x1A: 8, 0x1C: 12, 0x1E: 8,
            0x1F: 16, 0x20: 4}


def geo_tree(mem: Mem, addr: int) -> dict:
    """Parse a geo layout into a node tree: {cmd, args, children}."""
    root = {"cmd": "root", "children": []}
    stack, last, ret = [root], None, []
    a = addr
    while True:
        cmd = mem.at(a, 1)[0]
        b = mem.at(a, 16)
        if cmd == 0x00:                                    # branch and link
            ret.append(a + 8)
            a = struct.unpack_from(">I", b, 4)[0]
            continue
        if cmd == 0x02:
            if b[1]:
                ret.append(a + 8)
            a = struct.unpack_from(">I", b, 4)[0]
            continue
        if cmd == 0x03:
            a = ret.pop()
            continue
        if cmd == 0x01:
            if ret:
                a = ret.pop()
                continue
            break
        if cmd == 0x04:
            stack.append(last if last is not None else stack[-1])
            a += 4
            continue
        if cmd == 0x05:
            stack.pop()
            last = None
            a += 4
            continue
        node = {"cmd": cmd, "raw": b, "children": []}
        if cmd == 0x0A:
            size = 8 + (4 if b[1] else 0)
        elif cmd == 0x10:
            kind = (b[1] >> 4) & 7
            size = {0: 16, 1: 8, 2: 8, 3: 4}[kind] + (4 if b[1] & 0x80 else 0)
            node["dl"] = struct.unpack_from(">I", b, size - 4)[0] if b[1] & 0x80 else 0
            node["t"] = struct.unpack_from(">3h", b, 2) if kind in (0, 1) else (0, 0, 0)
        elif cmd in (0x11, 0x12, 0x14):
            size = 8 + (4 if b[1] & 0x80 else 0)
            node["dl"] = struct.unpack_from(">I", b, 8)[0] if b[1] & 0x80 else 0
            node["t"] = struct.unpack_from(">3h", b, 2) if cmd == 0x11 else (0, 0, 0)
        elif cmd == 0x1D:
            size = 8 + (4 if b[1] & 0x80 else 0)
            node["dl"] = struct.unpack_from(">I", b, 8)[0] if b[1] & 0x80 else 0
        else:
            size = GEO_SIZE[cmd]
        if cmd == 0x13:
            node["t"] = struct.unpack_from(">3h", b, 2)
            node["dl"] = struct.unpack_from(">I", b, 8)[0]
        elif cmd == 0x15:
            node["dl"] = struct.unpack_from(">I", b, 4)[0]
        elif cmd == 0x0D:
            node["range"] = struct.unpack_from(">hh", b, 4)
        elif cmd == 0x0E:
            node["ncase"] = b[3]
        node["addr"], node["size"] = a, size              # segmented address (the writer patches DL pointers here)
        stack[-1]["children"].append(node)
        last = node
        a += size
    return root


# ---------------------------------------------------------------- F3D

def _tex_decode(raw: bytes, fmt: int, siz: int, w: int, h: int, pal=None) -> np.ndarray:
    img = np.zeros((h, w, 4), np.uint8)
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if fmt == 0 and siz == 2:                       # RGBA16
                c = struct.unpack_from(">H", raw, 2 * i)[0] if 2 * i + 2 <= len(raw) else 0
                img[y, x] = ((c >> 11) * 255 // 31, ((c >> 6) & 31) * 255 // 31, ((c >> 1) & 31) * 255 // 31, 255 * (c & 1))
            elif fmt == 0 and siz == 3:                     # RGBA32
                img[y, x] = raw[4 * i:4 * i + 4]
            elif fmt == 3 and siz == 1:                     # IA8
                v = raw[i]
                img[y, x] = ((v >> 4) * 17,) * 3 + ((v & 15) * 17,)
            elif fmt == 3 and siz == 2:                     # IA16
                img[y, x] = (raw[2 * i],) * 3 + (raw[2 * i + 1],)
            elif fmt == 3 and siz == 0:                     # IA4
                v = (raw[i // 2] >> (4 if i % 2 == 0 else 0)) & 15
                img[y, x] = (((v >> 1) * 255 // 7),) * 3 + (255 * (v & 1),)
            elif fmt == 4 and siz == 1:                     # I8
                img[y, x] = (raw[i],) * 4
            elif fmt == 4 and siz == 0:                     # I4
                v = (raw[i // 2] >> (4 if i % 2 == 0 else 0)) & 15
                img[y, x] = (v * 17,) * 4
    return img


def run_dl(mem: Mem, addr: int, out: list, state: dict):
    """Collect triangles: out += [(material_key, [(pos, nrm_or_col, uv), x3])]. state keeps vertex cache, lights, tex."""
    a = addr
    while True:
        w0, w1 = struct.unpack(">II", mem.at(a, 8))
        op = w0 >> 24
        a += 8
        if op == 0x04:                                      # G_VTX (F3D): ((n-1)<<4)|v0, len
            n, v0 = ((w0 >> 20) & 0xF) + 1, (w0 >> 16) & 0xF
            raw = mem.at(w1, 16 * n)
            for k in range(n):
                x, y, z, _f, s, t = struct.unpack_from(">hhhHhh", raw, 16 * k)
                r, g, b, al = raw[16 * k + 12:16 * k + 16]
                state["vc"][v0 + k] = ((x, y, z), (r, g, b, al), (s, t))
        elif op == 0xBF:                                    # G_TRI1
            i = [(w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF]
            tri = [state["vc"][k // 10] for k in i]
            out.append((state_key(state), tri))
        elif op == 0x06:                                    # DL call / branch
            if (w0 >> 16) & 0xFF == 1:
                a = w1
                continue
            run_dl(mem, w1, out, state)
        elif op == 0xB8:                                    # end
            return
        elif op == 0x03:                                    # movemem: lights
            idx = (w0 >> 16) & 0xFF
            if idx == 0x86:
                state["diffuse"] = tuple(mem.at(w1, 3))
            elif idx == 0x88:
                state["ambient"] = tuple(mem.at(w1, 3))
        elif op == 0xFD:                                    # settimg
            state["timg"] = (w1, (w0 >> 21) & 7, (w0 >> 19) & 3)
        elif op == 0xF5:                                    # settile
            tile = (w1 >> 24) & 7
            if tile == 0:
                state["tfmt"] = ((w0 >> 21) & 7, (w0 >> 19) & 3)
        elif op == 0xF2:                                    # settilesize
            tile = (w1 >> 24) & 7
            if tile == 0:
                state["tsize"] = (((w1 >> 12) & 0xFFF) // 4 + 1, (w1 & 0xFFF) // 4 + 1)
        elif op == 0xB6:                                    # cleargeometrymode
            if w1 & 0x20000:
                state["light"] = False if False else state["light"]
        elif op == 0xBB:                                    # G_TEXTURE
            state["texon"] = bool(w0 & 0xFF)
        elif op == 0xFC:                                    # setcombine: textured if combiner uses TEXEL0
            state["combine"] = (w0 & 0xFFFFFF, w1)


def state_key(st):
    tex = None
    w0, w1 = st.get("combine", (0, 0))
    uses_tex = 1 in ((w0 >> 20) & 0xF, (w0 >> 15) & 0x1F, (w1 >> 28) & 0xF, (w1 >> 15) & 7) or (w0 >> 15) & 0x1F == 8
    if uses_tex and st.get("texon") and st.get("timg") and st.get("tsize"):
        fmt, siz = st.get("tfmt", st["timg"][1:])
        tex = (st["timg"][0], fmt, siz, *st["tsize"])
    return (st.get("diffuse", (200, 200, 200)), st.get("ambient", (100, 100, 100)), tex)


def _rot_xyz(rx, ry, rz):
    """SM64 mtxf_rotate_xyz_and_translate rotation part (row-vector: v' = v @ M); angles in s16 units."""
    f = np.pi / 32768
    sx, cx, sy, cy, sz, cz = np.sin(rx * f), np.cos(rx * f), np.sin(ry * f), np.cos(ry * f), np.sin(rz * f), np.cos(rz * f)
    return np.array([[cy * cz, cy * sz, -sy],
                     [sx * sy * cz - cx * sz, sx * sy * sz + cx * cz, sx * cy],
                     [cx * sy * cz + sx * sz, cx * sy * sz - sx * cz, cx * cy]])


def anim_frame(rom: bytes, index: int, frame: int = 0):
    """-> (root translation (3,), [ (rx, ry, rz) per joint ]) for Mario animation `index`."""
    n = struct.unpack_from(">I", rom, ANIM_TABLE)[0]
    off, _size = struct.unpack_from(">II", rom, ANIM_TABLE + 8 + 8 * index)
    a = ANIM_TABLE + off
    flags, ydiv, start, loop_s, loop_e, nbones = struct.unpack_from(">6h", rom, a)
    vals_o, idx_o, _ln = struct.unpack_from(">III", rom, a + 12)
    vals, idxs = a + vals_o, a + idx_o

    def chan(c):
        cnt, st = struct.unpack_from(">HH", rom, idxs + 4 * c)
        return struct.unpack_from(">h", rom, vals + 2 * (st + min(frame, cnt - 1)))[0]
    root = np.array([chan(0), chan(1), chan(2)], float)
    rots = [(chan(3 + 3 * j), chan(4 + 3 * j), chan(5 + 3 * j)) for j in range(nbones + 1)]
    return root, rots, n


def _has_dl(n) -> bool:
    return bool(n.get("dl")) and n.get("cmd") != 0x10 or any(_has_dl(c) for c in n["children"] if c.get("cmd") != 0x10)


def extract(rom: bytes, anim: int | None = None, frame: int = 0) -> dict:
    """Walk Mario's geo layout -> joints [{parent, t, dl list}] + triangles per joint (local coords)."""
    mem = Mem(rom)
    tree = geo_tree(mem, MARIO_GEO)
    joints = []

    def walk(node, parent, take=True):
        kids = node["children"]
        if node.get("cmd") == 0x0E:                         # switch: the first case that draws something
            kids = [next((c for c in kids if _has_dl(c)), kids[0])] if kids else []
        if node.get("cmd") == 0x10:                         # wing-cap wings (shown by a geo asm only with the wing cap)
            return
        if node.get("cmd") == 0x0D and node["range"][0] > 0:
            return                                          # far LOD
        j = parent
        if node.get("cmd") == 0x13:
            joints.append({"parent": parent, "t": node["t"], "dls": [node["dl"]] if node["dl"] else []})
            j = len(joints) - 1
        elif node.get("dl") and node.get("cmd") in (0x15, 0x10, 0x11, 0x12, 0x14, 0x1D):
            if parent is None:
                joints.append({"parent": None, "t": (0, 0, 0), "dls": []})
                parent = j = len(joints) - 1
            joints[j]["dls"].append(node["dl"])
        for c in kids:
            walk(c, j)
    walk(tree, None)
    rots = None
    if anim is not None:
        _root, rots, _n = anim_frame(rom, anim, frame)
    # world matrices (row vector): M_j = R_j * T_j * M_parent
    st = {"vc": [None] * 16}
    for k, jt in enumerate(joints):
        r = _rot_xyz(*rots[k]) if rots and k < len(rots) else np.eye(3)
        m = np.eye(4)
        m[:3, :3] = r
        m[3, :3] = jt["t"]
        jt["local"] = m
        jt["world"] = m @ joints[jt["parent"]]["world"] if jt["parent"] is not None else m
        tris = []                                           # RDP/RSP state carries over in draw (DFS) order
        for dl in jt["dls"]:
            run_dl(mem, dl, tris, st)
        jt["tris"] = tris
    texcache = {}
    for jt in joints:
        for key, _t in jt["tris"]:
            tex = key[2]
            if tex and tex not in texcache:
                addr, fmt, siz, w, h = tex
                bpp = {0: 4, 1: 8, 2: 16, 3: 32}[siz]
                texcache[tex] = _tex_decode(mem.at(addr, w * h * bpp // 8), fmt, siz, w, h)
    return {"joints": joints, "textures": texcache}


def to_gltf(model: dict, path: Path, scale: float = 1.0):
    joints, texs = model["joints"], model["textures"]
    blob = bytearray()
    views, accs = [], []

    def add(arr, comp, typ, target=None, minmax=False):
        nonlocal blob
        blob += bytes((-len(blob)) % 4)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, **({"target": target} if target else {})})
        blob += arr.tobytes()
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    # group triangles by material key across joints, positions in bind (world) space
    groups = {}
    for ji, jt in enumerate(joints):
        W = jt["world"]
        for key, tri in jt["tris"]:
            groups.setdefault(key, []).append((ji, W, tri))
    mats, images, gtex, prims = [], [], [], []
    tex_index = {}
    for key, items in groups.items():
        diff, amb, tex = key
        P, N, UV, J = [], [], [], []
        for ji, W, tri in items:
            for (x, y, z), c, (s, t) in tri:
                v = np.array([x, y, z, 1.0]) @ W
                P.append(v[:3] * scale)
                n = np.array([((c[0] + 128) % 256) - 128, ((c[1] + 128) % 256) - 128, ((c[2] + 128) % 256) - 128], float)
                n = n @ W[:3, :3]
                N.append(n / (np.linalg.norm(n) or 1))
                if tex:
                    UV.append((s / 32.0 / tex[3], t / 32.0 / tex[4]))
                else:
                    UV.append((0, 0))
                J.append(ji)
        P, N, UV = np.array(P, np.float32), np.array(N, np.float32), np.array(UV, np.float32)
        Jt = np.zeros((len(J), 4), np.uint16)
        Jt[:, 0] = J
        Wt = np.zeros((len(J), 4), np.float32)
        Wt[:, 0] = 1
        col = [min(1.0, (diff[i] + amb[i]) / 255.0) for i in range(3)] + [1.0]
        md = {"name": f"m{len(mats)}", "pbrMetallicRoughness": {"baseColorFactor": col if not tex else [1, 1, 1, 1],
                                                                 "metallicFactor": 0, "roughnessFactor": 0.9}}
        if tex:
            if (tex, tuple(col)) not in tex_index:
                from PIL import Image
                buf = io.BytesIO()
                t = texs[tex].astype(float)
                al = t[..., 3:4] / 255.0                    # SM64 decals: texture over the shade (light) colour
                img = np.concatenate([t[..., :3] * al + np.array(col[:3]) * 255 * (1 - al),
                                      np.full(al.shape, 255.0)], -1).astype(np.uint8)
                Image.fromarray(img, "RGBA").save(buf, "PNG")
                images.append({"uri": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()})
                gtex.append({"source": len(images) - 1, "sampler": 0})
                tex_index[(tex, tuple(col))] = len(gtex) - 1
            md["pbrMetallicRoughness"]["baseColorTexture"] = {"index": tex_index[(tex, tuple(col))]}
        mats.append(md)
        attrs = {"POSITION": add(P, 5126, "VEC3", 34962, True), "NORMAL": add(N, 5126, "VEC3", 34962),
                 "TEXCOORD_0": add(UV, 5126, "VEC2", 34962), "JOINTS_0": add(Jt, 5123, "VEC4", 34962),
                 "WEIGHTS_0": add(Wt, 5126, "VEC4", 34962)}
        prims.append({"attributes": attrs, "material": len(mats) - 1})
    nodes = []
    for k, jt in enumerate(joints):
        L = jt["local"]
        # row-vector local -> glTF column: translation = L[3,:3], rotation = L[:3,:3].T
        nodes.append({"name": f"j{k:02d}", "matrix": _col(L, scale)})
    for k, jt in enumerate(joints):
        if jt["parent"] is not None:
            nodes[jt["parent"]].setdefault("children", []).append(k)
    ibm = np.zeros((len(joints), 16), np.float32)
    for k, jt in enumerate(joints):
        Wc = np.array(_col(jt["world"], scale)).reshape(4, 4).T     # column-major list -> matrix
        ibm[k] = np.linalg.inv(Wc).T.reshape(16)
    nodes.append({"name": "mario", "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox sm64_mario"}, "scene": 0,
          "scenes": [{"nodes": [0, len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": "mario", "primitives": prims}],
          "skins": [{"joints": list(range(len(joints))), "inverseBindMatrices": add(ibm, 5126, "MAT4"), "skeleton": 0}],
          "materials": mats, "accessors": accs, "bufferViews": views,
          "buffers": [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," + base64.b64encode(bytes(blob)).decode()}]}
    if images:
        gl.update(images=images, textures=gtex, samplers=[{"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}])
    Path(path).write_text(json.dumps(gl))
    return path


def _col(rowm: np.ndarray, scale: float) -> list:
    m = np.eye(4)
    m[:3, :3] = rowm[:3, :3].T
    m[:3, 3] = rowm[3, :3] * scale
    return m.T.reshape(16).tolist()                         # glTF matrices are column-major


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rom")
    ap.add_argument("out")
    ap.add_argument("--anim", type=int, default=None)
    ap.add_argument("--frame", type=int, default=0)
    a = ap.parse_args()
    rom = Path(a.rom).read_bytes()
    md = extract(rom, a.anim, a.frame)
    print(len(md["joints"]), "joints", sum(len(j["tris"]) for j in md["joints"]), "tris", len(md["textures"]), "textures")
    to_gltf(md, Path(a.out))
