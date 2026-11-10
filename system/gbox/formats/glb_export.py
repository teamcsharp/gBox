"""Minimal dependency-free glTF 2.0 (GLB) writer for Platinum Switch WMB3 characters.

Builds a skinned, textured model from pl*.wmb + .wta + .wtp:
 * skeleton: parents/rel_pos from the WMB (proved by wmb_platinum.skeleton_error)
 * per-batch primitives with batch-local JOINTS_0 = batch.bone_set[idx] (proved in range)
 * material -> base-colour texture: first material hash found in the .wta id table
   (HYPOTHESIS: slot order = albedo first; verify visually / against runtime)
Normals/tangents are packed (unproved) and therefore omitted.
"""
import json
import struct
import zlib
from typing import Dict, List, Optional

import numpy as np

from . import bntx_nx as B
from . import wmb_platinum as W


def parse_wta(buf: bytes):
    """WTA: magic 'WTB\\0', ver, count, then 4 u32 offsets -> offsets/sizes/flags/ids arrays."""
    if buf[:4] != b"WTB\0":
        raise ValueError("not WTA")
    n, o_off, o_sz, o_fl, o_id = struct.unpack_from("<5I", buf, 8)
    rd = lambda o: list(struct.unpack_from("<%dI" % n, buf, o))
    return {"count": n, "offsets": rd(o_off), "sizes": rd(o_sz), "flags": rd(o_fl), "ids": rd(o_id)}


def png_bytes(img: np.ndarray) -> bytes:
    h, w, _ = img.shape
    raw = b"".join(b"\0" + img[y].tobytes() for y in range(h))

    def ch(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + ch(b"IDAT", zlib.compress(raw, 6)) + ch(b"IEND", b""))


def decode_wta_texture(wtp: bytes, wta: dict, i: int, max_dim: int = 1024) -> np.ndarray:
    tex = B.parse_bntx(wtp, wta["offsets"][i])[0]
    lvl = 0
    while max(tex.width, tex.height) >> lvl > max_dim and lvl + 1 < tex.mips:
        lvl += 1
    return B.decode_mip(wtp, tex, lvl)


def _pad4(b: bytes, fill=b"\0") -> bytes:
    return b + fill * (-len(b) % 4)


def build_glb(wmb: bytes, wtp: Optional[bytes] = None, wta_buf: Optional[bytes] = None,
              max_tex_dim: int = 1024) -> bytes:
    wm = W.parse_wmb(wmb)
    meshes = W.parse_meshes(wmb)
    wta = parse_wta(wta_buf) if wta_buf else None
    mats = W.parse_materials(wmb, wta["ids"] if wta else ())
    nb = len(wm.parents)

    blob = bytearray()
    views: List[dict] = []
    accs: List[dict] = []

    def add_view(data: bytes, target=None) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data),
                      **({"target": target} if target else {})})
        blob.extend(data)
        return len(views) - 1

    def add_acc(data: np.ndarray, ctype: str, comp: int, target=None, minmax=False) -> int:
        a = {"bufferView": add_view(data.tobytes(), target), "componentType": comp,
             "count": int(data.shape[0]), "type": ctype}
        if minmax:
            a["min"] = [float(x) for x in data.min(0)]
            a["max"] = [float(x) for x in data.max(0)]
        accs.append(a)
        return len(accs) - 1

    # textures/materials
    images, textures, materials, mat_of = [], [], [], {}
    tex_cache: Dict[int, int] = {}
    for m in mats:
        tidx = None
        if wta and wtp:
            for h in m.texture_ids:
                if h in wta["ids"]:
                    tidx = wta["ids"].index(h)
                    break
        pbr = {"metallicFactor": 0.0, "roughnessFactor": 1.0}
        if tidx is not None:
            if tidx not in tex_cache:
                try:
                    png = png_bytes(decode_wta_texture(wtp, wta, tidx, max_tex_dim))
                except (ImportError, NotImplementedError):   # BC7/ASTC need texture2ddecoder
                    materials.append({"name": "mat%d" % m.index, "pbrMetallicRoughness": pbr,
                                      "doubleSided": True})
                    mat_of[m.index] = len(materials) - 1
                    continue
                images.append({"bufferView": add_view(png), "mimeType": "image/png",
                               "name": "wta_%d_%08x" % (tidx, wta["ids"][tidx])})
                textures.append({"source": len(images) - 1})
                tex_cache[tidx] = len(textures) - 1
            pbr["baseColorTexture"] = {"index": tex_cache[tidx]}
        materials.append({"name": "mat%d" % m.index, "pbrMetallicRoughness": pbr, "doubleSided": True})
        mat_of[m.index] = len(materials) - 1

    # nodes: bones first
    nodes = []
    children: Dict[int, list] = {i: [] for i in range(nb)}
    roots = []
    for i, p in enumerate(wm.parents):
        (children[p] if p >= 0 else roots).append(i)
    for i in range(nb):
        nd = {"name": "bone%d" % i, "translation": [float(x) for x in wm.rel_pos[i]]}
        if children[i]:
            nd["children"] = children[i]
        nodes.append(nd)
    ibm = np.zeros((nb, 16), dtype="<f4")
    for i in range(nb):
        m4 = np.eye(4, dtype="<f4")
        m4[3, :3] = [-x for x in wm.abs_pos[i]]  # column-major translation(-abs)
        ibm[i] = m4.reshape(-1)
    skin = {"joints": list(range(nb)), "inverseBindMatrices": add_acc(ibm.reshape(nb, 16), "MAT4", 5126)}
    # glTF MAT4 accessor: element is 16 floats column-major; add_acc used shape (nb,16)
    accs[skin["inverseBindMatrices"]]["type"] = "MAT4"

    gmeshes = []
    mesh_nodes = []
    for m in meshes:
        prims = []
        for b in m.batches:
            vs, ve = b.vertex_start, b.vertex_end
            vv = wm.vertices[vs:ve]
            if not vv or not b.indices:
                continue
            ix = np.asarray(b.indices, dtype=np.int64) - vs
            if ix.min() < 0 or ix.max() >= ve - vs:
                raise ValueError("batch index outside its vertex range")
            ix = ix[: len(ix) // 3 * 3]
            pos = np.array([v.pos for v in vv], dtype="<f4")
            uv = np.array([v.uv for v in vv], dtype="<f4")
            bs = b.bone_set
            joints = np.array([[bs[j] if (j < len(bs) and w) else 0 for j, w in zip(v.bone_idx, v.bone_w)]
                               for v in vv], dtype="<u2")
            wts = np.array([[w / 255.0 for w in v.bone_w] for v in vv], dtype="<f4")
            attrs = {"POSITION": add_acc(pos, "VEC3", 5126, 34962, True),
                     "TEXCOORD_0": add_acc(uv, "VEC2", 5126, 34962),
                     "JOINTS_0": add_acc(joints, "VEC4", 5123, 34962),
                     "WEIGHTS_0": add_acc(wts, "VEC4", 5126, 34962)}
            idx = add_acc(ix.astype("<u4").reshape(-1, 1), "SCALAR", 5125, 34963)
            prims.append({"attributes": attrs, "indices": idx, "mode": 4,
                          "material": mat_of.get(b.material, 0) if materials else None})
            if prims[-1]["material"] is None:
                del prims[-1]["material"]
        if prims:
            gmeshes.append({"name": m.name, "primitives": prims})
            nodes.append({"name": m.name, "mesh": len(gmeshes) - 1, "skin": 0})
            mesh_nodes.append(len(nodes) - 1)

    for a in accs:
        if a["type"] == "SCALAR":
            pass
    gltf = {"asset": {"version": "2.0", "generator": "gbox.formats.glb_export"},
            "scene": 0, "scenes": [{"nodes": roots + mesh_nodes}], "nodes": nodes,
            "meshes": gmeshes, "skins": [skin], "materials": materials, "accessors": accs,
            "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    if images:
        gltf["images"], gltf["textures"] = images, textures
    jb = _pad4(json.dumps(gltf, separators=(",", ":")).encode(), b" ")
    bb = _pad4(bytes(blob))
    total = 12 + 8 + len(jb) + 8 + len(bb)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(jb), 0x4E4F534A) + jb
            + struct.pack("<II", len(bb), 0x004E4942) + bb)
