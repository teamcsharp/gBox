"""Shenmue (Dreamcast) MT5 character models -> UAP / glTF (node skeleton + strips + PVR textures).

Containers (Shenmue US disc 1, read by gBox):
  *.PKS / *.PKF   gzip. PKS = "PAKS" (16 B) + "IPAC" {u32 dict offset, u32 count, u32 size}; dict entries 20 B:
                  name[8], ext[4], u32 offset, u32 size (offsets from the IPAC header). MISC/COLDINIT.PKS holds
                  Ryo Hazuki = "YKB": YKB_M (body, CHRM), YKB_F (face), YKB_B, YKB_TL/TR/UL/UR/XL/XR (hand poses).
                  PKF = "PAKF" {u32 size, u32, u32 count} + chunks {tag[4], u32 size}: "TEXN" + 8-byte texture id +
                  GBIX/PVRT (decoded with gbox.ninja.pvr_decode).
MT5 / HRCM (little-endian, offsets from the file start), reverse-engineered here with the layout known from the
Shenmue modding community:
  header  "HRCM", u32 TEXD offset, u32 first node
  node    64 B: u32 id, u32 mesh, s32 rot x/y/z (0x10000 = 360 deg), f32 scale x/y/z, f32 pos x/y/z,
          u32 child, u32 sibling, u32 parent, 8 B name/unused
  mesh    u32 poly type, u32 vertex offset, s32 vertex count, u32 face offset, f32 centre xyz, f32 radius;
          vertices = f32 position xyz + normal xyz (node space)
  faces   u16 op list ended by 0x8000: 0x02/0x03/0x04/0x0E/0x0F {u16 size, data}, 0x08..0x0B {u16 value}
          (0x09 = texture index into TEXD's NAME list, 0x0B = UV divisor), 0x10..0x1F strip groups {u16 size,
          u16 strip count, strips: s16 n (negative = flipped) then n x (s16 vertex, s16 u, s16 v)}; the next op
          starts at op + 4 + size. A negative vertex index points into the nearest ancestor mesh's vertices
          (count + index): that is how limbs are welded to their parents (rigid skinning per node).
  TEXD    "TEXD" u32 12, u32 count, "NAME" u32 size, count x 8-byte texture ids
"""
from __future__ import annotations

import gzip
import math
import struct
from pathlib import Path
from types import SimpleNamespace

from . import ninja, uap


def ipac(data: bytes) -> dict[str, bytes]:
    """PKS (gzip or raw) -> {"NAME.EXT": bytes}."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    b = data.find(b"IPAC")
    doff, n, _size = struct.unpack_from("<III", data, b + 4)
    out = {}
    for i in range(n):
        e = data[b + doff + 20 * i:b + doff + 20 * i + 20]
        name = e[:8].rstrip(b"\0").decode("latin-1")
        ext = e[8:12].rstrip(b"\0").decode("latin-1")
        o, s = struct.unpack_from("<II", e, 12)
        out[f"{name}.{ext}"] = data[b + o:b + o + s]
    return out


def pakf(data: bytes) -> dict[bytes, bytes]:
    """PKF -> {8-byte texture id: PVR (GBIX + PVRT) bytes}."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    out, o = {}, 16
    while o + 8 <= len(data):
        tag, size = data[o:o + 4], struct.unpack_from("<I", data, o + 4)[0]
        if size == 0:
            break
        if tag == b"TEXN":
            out[data[o + 8:o + 16]] = data[o + 16:o + size]
        o += size
    return out


def _rot(rx, ry, rz):
    a = [v * 2 * math.pi / 65536 for v in (rx, ry, rz)]
    cx, sx, cy, sy, cz, sz = math.cos(a[0]), math.sin(a[0]), math.cos(a[1]), math.sin(a[1]), math.cos(a[2]), math.sin(a[2])
    X = [[1, 0, 0, 0], [0, cx, -sx, 0], [0, sx, cx, 0], [0, 0, 0, 1]]
    Y = [[cy, 0, sy, 0], [0, 1, 0, 0], [-sy, 0, cy, 0], [0, 0, 0, 1]]
    Z = [[cz, -sz, 0, 0], [sz, cz, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    return ninja._mat_mul(Z, ninja._mat_mul(Y, X))


def parse(mt5: bytes, root=None):
    """-> an object shaped like gbox.ninja.NJ (bones, tris {tex: [(vi, uv, vertex)...]}) for ninja.to_manifest, plus
    .texnames (TEXD order)."""
    u = lambda f, o: struct.unpack_from("<" + f, mt5, o)
    tex_off, node0 = u("II", 4)
    nj = SimpleNamespace(bones=[], tris={}, vbuf={})
    verts: dict[int, list] = {}                             # node -> [vertex dict] (world space)
    I4 = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

    def mesh(bi, mo, m, anc):
        _pt, vo, vc, fo = u("IIiI", mo)
        vl = []
        for i in range(vc):
            p, n = u("3f", vo + 24 * i), u("3f", vo + 24 * i + 12)
            vl.append({"pos": ninja._xf(m, p), "nrm": ninja._xf(m, n, 0.0), "joints": [(bi, 1.0)]})
        verts[bi] = vl
        tex, uvdiv, p = 0, 1024.0, fo
        for _ in range(4096):
            t = u("H", p)[0]
            if t == 0x8000 or p + 2 > len(mt5):
                break
            if t in (0x02, 0x03, 0x04, 0x0E, 0x0F):
                p += 4 + u("H", p + 2)[0]
            elif 0x08 <= t <= 0x0B:
                v = u("H", p + 2)[0]
                if t == 0x09:
                    tex = v
                elif t == 0x0B and v:
                    uvdiv = float(v)
                p += 4
            elif 0x10 <= t <= 0x1F:
                size, ns = u("HH", p + 2)
                q = p + 6
                uvs = t in (0x11, 0x13, 0x19, 0x1B)
                col = t in (0x12, 0x13, 0x1A, 0x1B)
                for _s in range(ns):
                    n = u("h", q)[0]
                    q += 2
                    flip, n = n < 0, abs(n)
                    pts = []
                    for _k in range(n):
                        vi = u("h", q)[0]
                        q += 2
                        uv = None
                        if uvs:
                            uu, vv = u("hh", q)
                            uv = [uu / uvdiv, vv / uvdiv]
                            q += 4
                        if col:
                            q += 4
                        if vi < 0:                            # welded to the nearest ancestor mesh
                            src = verts.get(anc)
                            v = src[len(src) + vi] if src and len(src) + vi >= 0 else None
                        else:
                            v = vl[vi] if vi < len(vl) else None
                        pts.append((vi, uv, v))
                    for k in range(len(pts) - 2):
                        a, b, c = pts[k], pts[k + 1], pts[k + 2]
                        if (k % 2 == 1) ^ flip:
                            a, b = b, a
                        nj.tris.setdefault(tex, []).append((a, b, c))
                p += 4 + size
            else:
                break

    def walk(o, parent, pm, anc):
        while o:
            nid, mo = u("II", o)
            rot, scl, pos = u("3i", o + 8), u("3f", o + 20), u("3f", o + 32)
            child, sib = u("II", o + 44)
            local = ninja._mat_mul([[1, 0, 0, pos[0]], [0, 1, 0, pos[1]], [0, 0, 1, pos[2]], [0, 0, 0, 1]],
                                   ninja._mat_mul(_rot(*rot), [[scl[0], 0, 0, 0], [0, scl[1], 0, 0], [0, 0, scl[2], 0], [0, 0, 0, 1]]))
            m = ninja._mat_mul(pm, local)
            bi = len(nj.bones)
            if parent is None:
                t, r = [m[0][3], m[1][3], m[2][3]], ninja._quat(m)
            else:
                t, r = [local[0][3], local[1][3], local[2][3]], ninja._quat(local)
            nj.bones.append({"name": f"node{bi:03d}", "parent": parent, "t": t, "r": r, "m": m, "id": nid})
            if mo:
                mesh(bi, mo, m, anc)
            if child:
                walk(child, bi, m, bi if mo else anc)
            o = sib

    walk(node0, None, root or I4, None)
    names = []
    if mt5[tex_off:tex_off + 4] == b"TEXD":
        cnt = u("I", tex_off + 8)[0]
        if mt5[tex_off + 12:tex_off + 16] == b"NAME":
            names = [mt5[tex_off + 20 + 8 * i:tex_off + 28 + 8 * i] for i in range(cnt)]
    nj.texnames = names
    return nj


# Shenmue characters face -Z (Ryo's bind pose); turned 180 deg about Y to face +Z like RE4 Leon and glTF viewers
FACE_Z = [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]]


def export(gdi: str, out_dir: str, pks: str = "MISC/COLDINIT.PKS", pkf: str = "MISC/COLDINIT.PKF",
           model: str = "YKB_M.CHRM", root=FACE_Z) -> Path:
    from .gdrom import GDRom
    disc = GDRom(gdi)
    files = ipac(disc.read(pks))
    texs = pakf(disc.read(pkf))
    nj = parse(files[model], root)
    out = Path(out_dir)
    (out / "textures").mkdir(parents=True, exist_ok=True)
    tex_files = []
    for i, nm in enumerate(nj.texnames):
        pv = texs.get(nm)
        if pv is None:
            tex_files.append(None)
            continue
        w, h, rgba, _ = ninja.pvr_decode(pv)
        rel = f"textures/t{i:02d}.png"
        (out / rel).write_bytes(ninja.png(w, h, rgba))
        tex_files.append(rel)
    name = "shenmue_" + model.split(".")[0].lower()
    m = ninja.to_manifest(nj, name, {"game": "Shenmue (DC, US) disc 1", "files": [pks, pkf], "model": model,
                                     "extraction_method": "gbox.shenmue_mt5"}, tex_files)
    (out / "manifest.json").write_text(m.model_dump_json())
    glb = out / f"{name}.glb"
    glb.write_bytes(uap.to_glb(m, out))
    return glb


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("out")
    ap.add_argument("--model", default="YKB_M.CHRM")
    a = ap.parse_args()
    print(export(a.gdi, a.out, model=a.model))
