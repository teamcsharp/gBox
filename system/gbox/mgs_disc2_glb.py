"""Read-only MGS Disc 2 player export: the resolved player KMD + its PCX textures -> an editable glTF binary.

Pure stdlib + Pillow (no MetalMintSolid).  Nodes mirror the KMD bone hierarchy (object parent/pos), one
mesh per object with a primitive per texture hash.  Face = 4 vertex indices; c == d means a triangle, else a
PS1 strip quad (0,1,2)(2,1,3).  Per-face uv bytes are (u0,v0,..u3,v3) in 0..255 of the texture (hypothesis,
checked only for range/consistency).  MGS is Y-down, so a root node rotates 180 deg about X.
"""
from __future__ import annotations

import io
import json
import struct

from . import mgs_disc2_player as pl
from . import mgs_kmd

SCALE = 0.001


def _png(pcx: bytes) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.open(io.BytesIO(pcx)).convert("RGBA").save(out, "PNG")
    return out.getvalue()


def _tris(face):
    a, b, c, d = face
    return [(0, 1, 2)] if c == d else [(0, 1, 2), (2, 1, 3)]


def build_glb(kmd_bytes: bytes, textures: dict) -> tuple[bytes, dict]:
    kmd = mgs_kmd.loads(kmd_bytes)
    buf = bytearray()
    views, accs, meshes, mats, images, texs = [], [], [], {}, [], []

    def blob(data, target=None):
        while len(buf) % 4:
            buf.append(0)
        views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": len(data), **({"target": target} if target else {})})
        buf.extend(data)
        return len(views) - 1

    def acc(data, ctype, count, typ, target, mm=None):
        a = {"bufferView": blob(data, target), "componentType": ctype, "count": count, "type": typ}
        if mm:
            a["min"], a["max"] = mm
        accs.append(a)
        return len(accs) - 1

    def material(h):
        if h not in mats:
            if h in textures:
                images.append({"bufferView": blob(_png(textures[h])), "mimeType": "image/png"})
                texs.append({"source": len(images) - 1})
                m = {"name": f"tex_{h}", "doubleSided": True,
                     "pbrMetallicRoughness": {"baseColorTexture": {"index": len(texs) - 1}, "metallicFactor": 0}}
            else:
                m = {"name": f"missing_{h}", "doubleSided": True}
            mats[h] = len(mats)
            material.list.append(m)
        return mats[h]
    material.list = []

    nodes, stats = [], {"faces": 0, "tris": 0, "objects": len(kmd.objects)}
    for i, o in enumerate(kmd.objects):
        groups = {}
        for f, fn, uv, t in zip(o.faces, o.face_normals, o.uvs, o.textures):
            stats["faces"] += 1
            for tri in _tris(f):
                g = groups.setdefault(t, ([], []))
                for k in tri:
                    v = o.vertices[f[k]]
                    g[0].append((v[0] * SCALE, v[1] * SCALE, v[2] * SCALE))
                    g[1].append((uv[2 * k] / 255.0, uv[2 * k + 1] / 255.0))
                stats["tris"] += 1
        prims = []
        for t, (pos, uvs) in groups.items():
            xs = list(zip(*pos))
            pa = acc(b"".join(struct.pack("<3f", *p) for p in pos), 5126, len(pos), "VEC3", 34962,
                     ([min(c) for c in xs], [max(c) for c in xs]))
            ta = acc(b"".join(struct.pack("<2f", *u) for u in uvs), 5126, len(uvs), "VEC2", 34962)
            prims.append({"attributes": {"POSITION": pa, "TEXCOORD_0": ta}, "material": material(t)})
        node = {"name": f"obj{i}", "translation": [c * SCALE for c in o.pos]}
        if prims:
            meshes.append({"name": f"obj{i}", "primitives": prims})
            node["mesh"] = len(meshes) - 1
        nodes.append(node)
    root = {"name": "mgs_yflip", "rotation": [1.0, 0.0, 0.0, 0.0], "children": []}
    for i, o in enumerate(kmd.objects):
        if 0 <= o.parent < len(nodes) and o.parent != i:
            nodes[o.parent].setdefault("children", []).append(i)
        else:
            root["children"].append(i)
    nodes.append(root)
    gltf = {"asset": {"version": "2.0", "generator": "gbox.mgs_disc2_glb"}, "scene": 0,
            "scenes": [{"nodes": [len(nodes) - 1]}], "nodes": nodes, "meshes": meshes,
            "materials": material.list, "textures": texs, "images": images, "accessors": accs,
            "bufferViews": views, "buffers": [{"byteLength": len(buf)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(buf) % 4:
        buf.append(0)
    total = 12 + 8 + len(js) + 8 + len(buf)
    glb = (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
           + struct.pack("<I4s", len(buf), b"BIN\0") + bytes(buf))
    stats |= {"materials": len(material.list), "images": len(images), "bytes": len(glb)}
    return glb, stats


def export_player(stage: bytes, which: str = "init") -> tuple[bytes, dict]:
    site = next(s for s in pl.player_sites(stage) if s["stage"] == which)
    kmd, tex = pl.extract(stage, site)
    glb, st = build_glb(kmd, tex)
    return glb, st | {"stage": which, "offset": site["offset"], "size": site["size"]}
