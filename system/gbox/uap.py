"""Universal Asset Package (plan §14): canonical manifest, validator, glTF 2.0 / OBJ exporters.

A package is a directory: manifest.json (+ textures/ referenced by relative path).
ponytail: geometry is inline JSON arrays; move to binary buffers when packages exceed a few MB.
"""
import base64
import json
import math
import struct
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Vec3 = list[float]
Quat = list[float]                       # x, y, z, w
DIMENSIONS = ["entity", "geometry", "materials", "textures", "skeleton", "skin_weights",
              "animations", "collision", "source_identity", "runtime_linkage"]   # plan §12 confidence report


class Mesh(BaseModel):
    name: str
    positions: list[Vec3]
    normals: list[Vec3] | None = None
    uvs: list[list[float]] | None = None
    indices: list[int]
    material: int | None = None
    joints: list[list[int]] | None = None      # 4 per vertex
    weights: list[list[float]] | None = None   # 4 per vertex


class Material(BaseModel):
    name: str
    base_color: list[float] = [1, 1, 1, 1]
    texture: str | None = None                 # path relative to package dir
    source: dict = {}                          # original shader/material params, preserved verbatim


class Bone(BaseModel):
    name: str
    parent: int | None = None
    translation: Vec3 = [0, 0, 0]              # rest pose, local
    rotation: Quat = [0, 0, 0, 1]
    scale: Vec3 = [1, 1, 1]


class Channel(BaseModel):
    bone: int
    path: Literal["translation", "rotation", "scale"]
    times: list[float]
    values: list[list[float]]
    interpolation: Literal["LINEAR", "STEP"] = "LINEAR"


class Clip(BaseModel):
    name: str
    channels: list[Channel]
    events: list[dict] = []


class Node(BaseModel):
    name: str
    mesh: int | None = None
    skinned: bool = False
    translation: Vec3 = [0, 0, 0]
    rotation: Quat = [0, 0, 0, 1]
    scale: Vec3 = [1, 1, 1]
    children: list[int] = []


class Manifest(BaseModel):
    uap_version: str = "0.1"
    name: str
    source: dict                               # game_id, resource_ids, extraction_method, tool versions
    coordinate_system: dict = {"up": "Y", "forward": "-Z", "handedness": "right"}
    unit_scale_m: float = 1.0                  # metres per game unit
    meshes: list[Mesh] = []
    materials: list[Material] = []
    skeleton: list[Bone] = []
    animations: list[Clip] = []
    collision: list[Mesh] = []
    nodes: list[Node] = []
    roots: list[int] = []
    confidence: dict[str, str] = {}            # dimension -> verified | partial | missing | unknown
    provenance: list[dict] = []
    dependencies: list[str] = []


def load(pkg: Path) -> Manifest:
    return Manifest.model_validate_json((Path(pkg) / "manifest.json").read_text())


def validate(m: Manifest, pkg: Path | None = None) -> list[str]:
    """Plan §22 asset validation. Returns a list of problems; empty means valid."""
    p = []
    finite = lambda vs: all(math.isfinite(x) for v in vs for x in v)
    for i, me in enumerate(m.meshes + m.collision):
        tag, n = f"mesh[{i}] {me.name}", len(me.positions)
        if n == 0:
            p.append(f"{tag}: no vertices")
        if any(len(v) != 3 for v in me.positions) or not finite(me.positions):
            p.append(f"{tag}: positions must be finite xyz")
        if len(me.indices) % 3:
            p.append(f"{tag}: index count {len(me.indices)} not a multiple of 3")
        if me.indices and (min(me.indices) < 0 or max(me.indices) >= n):
            p.append(f"{tag}: index out of range")
        for attr in ("normals", "uvs", "joints", "weights"):
            a = getattr(me, attr)
            if a is not None and len(a) != n:
                p.append(f"{tag}: {attr} count {len(a)} != vertex count {n}")
        if me.material is not None and not 0 <= me.material < len(m.materials):
            p.append(f"{tag}: material {me.material} missing")
        if (me.joints is None) != (me.weights is None):
            p.append(f"{tag}: joints and weights must both be present")
        if me.joints:
            if any(j < 0 or j >= len(m.skeleton) for js in me.joints for j in js):
                p.append(f"{tag}: joint index outside skeleton")
            bad = sum(1 for w in me.weights if abs(sum(w) - 1) > 1e-3 or min(w) < 0)
            if bad:
                p.append(f"{tag}: {bad} vertices with weights not summing to 1")
    for i, mat in enumerate(m.materials):
        if mat.texture and pkg and not (Path(pkg) / mat.texture).exists():
            p.append(f"material[{i}] {mat.name}: texture missing {mat.texture}")
    for i, b in enumerate(m.skeleton):
        seen, j = set(), i
        while j is not None:
            if j in seen or not 0 <= j < len(m.skeleton):
                p.append(f"bone[{i}] {b.name}: invalid parent chain")
                break
            seen.add(j)
            j = m.skeleton[j].parent
        if abs(math.sqrt(sum(x * x for x in b.rotation)) - 1) > 1e-3:
            p.append(f"bone[{i}] {b.name}: rotation not unit quaternion")
    width = {"translation": 3, "rotation": 4, "scale": 3}
    for c in m.animations:
        for ch in c.channels:
            tag = f"clip {c.name} bone {ch.bone} {ch.path}"
            if not 0 <= ch.bone < len(m.skeleton):
                p.append(f"{tag}: bone missing")
            if len(ch.times) != len(ch.values) or not ch.times:
                p.append(f"{tag}: times/values mismatch")
            if any(b <= a for a, b in zip(ch.times, ch.times[1:])):
                p.append(f"{tag}: times not strictly increasing")
            if any(len(v) != width[ch.path] for v in ch.values):
                p.append(f"{tag}: value width != {width[ch.path]}")
    for i, nd in enumerate(m.nodes):
        if nd.mesh is not None and not 0 <= nd.mesh < len(m.meshes):
            p.append(f"node[{i}] {nd.name}: mesh missing")
        if any(not 0 <= c < len(m.nodes) for c in nd.children):
            p.append(f"node[{i}] {nd.name}: child missing")
    if any(not 0 <= r < len(m.nodes) for r in m.roots):
        p.append("roots reference missing nodes")
    if not m.provenance:
        p.append("no provenance recorded")
    if unknown := set(m.confidence) - set(DIMENSIONS):
        p.append(f"unknown confidence dimensions: {sorted(unknown)}")
    return p


def stats(m: Manifest) -> dict:
    return {"meshes": len(m.meshes), "vertices": sum(len(x.positions) for x in m.meshes),
            "triangles": sum(len(x.indices) // 3 for x in m.meshes), "materials": len(m.materials),
            "bones": len(m.skeleton), "clips": len(m.animations), "nodes": len(m.nodes)}


# --- matrices (column-major 4x4 as glTF expects) -------------------------------------------

def _trs(t, r, s):
    x, y, z, w = r
    m = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
         2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
         2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0,
         t[0], t[1], t[2], 1]
    for c in range(3):
        for rr in range(3):
            m[c * 4 + rr] *= s[c]
    return m


def _mul(a, b):
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def _inv_trs(t, r, s):
    inv_r = [-r[0], -r[1], -r[2], r[3]]
    inv_s = [1 / v for v in s]
    return _mul(_mul(_trs([0, 0, 0], [0, 0, 0, 1], inv_s), _trs([0, 0, 0], inv_r, [1, 1, 1])),
                _trs([-v for v in t], [0, 0, 0, 1], [1, 1, 1]))


def inverse_bind(skel: list[Bone]) -> list[list[float]]:
    out = []
    for i in range(len(skel)):
        m, j = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], i
        while j is not None:                                 # world^-1 = local_i^-1 ... local_root^-1
            b = skel[j]
            m = _mul(m, _inv_trs(b.translation, b.rotation, b.scale))
            j = b.parent
        out.append(m)
    return out


# --- glTF -----------------------------------------------------------------------------------

def to_gltf(m: Manifest) -> dict:
    buf, views, accs = bytearray(), [], []

    def add(values, comp, typ, fmt, target=None, minmax=False):
        while len(buf) % 4:
            buf.append(0)
        flat = [x for v in values for x in (v if isinstance(v, list) else [v])]
        data = struct.pack(f"<{len(flat)}{fmt}", *flat)
        views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": len(data), **({"target": target} if target else {})})
        buf.extend(data)
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": len(values), "type": typ}
        if minmax:
            n = len(values[0])
            acc["min"] = [min(v[i] for v in values) for i in range(n)]
            acc["max"] = [max(v[i] for v in values) for i in range(n)]
        accs.append(acc)
        return len(accs) - 1

    F, U16, U32, ARRAY, ELEMENT = 5126, 5123, 5125, 34962, 34963
    meshes = []
    for me in m.meshes:
        attrs = {"POSITION": add(me.positions, F, "VEC3", "f", ARRAY, minmax=True)}
        if me.normals:
            attrs["NORMAL"] = add(me.normals, F, "VEC3", "f", ARRAY)
        if me.uvs:
            attrs["TEXCOORD_0"] = add(me.uvs, F, "VEC2", "f", ARRAY)
        if me.joints:
            attrs["JOINTS_0"] = add(me.joints, U16, "VEC4", "H", ARRAY)
            attrs["WEIGHTS_0"] = add(me.weights, F, "VEC4", "f", ARRAY)
        prim = {"attributes": attrs, "indices": add(me.indices, U32, "SCALAR", "I", ELEMENT)}
        if me.material is not None:
            prim["material"] = me.material
        meshes.append({"name": me.name, "primitives": [prim]})

    images, textures, materials = [], [], []
    for mat in m.materials:
        pbr = {"baseColorFactor": mat.base_color, "metallicFactor": 0.0}
        if mat.texture:
            images.append({"uri": mat.texture})
            textures.append({"source": len(images) - 1})
            pbr["baseColorTexture"] = {"index": len(textures) - 1}
        materials.append({"name": mat.name, "pbrMetallicRoughness": pbr, "extras": {"source": mat.source}})

    # scene nodes first, then bones (bone node index = len(scene nodes) + bone index)
    nodes = [{"name": n.name, "translation": n.translation, "rotation": n.rotation, "scale": n.scale,
              **({"mesh": n.mesh} if n.mesh is not None else {}), **({"children": n.children} if n.children else {})}
             for n in m.nodes]
    base = len(nodes)
    skins, extra_roots = [], []
    if m.skeleton:
        for i, b in enumerate(m.skeleton):
            kids = [base + j for j, c in enumerate(m.skeleton) if c.parent == i]
            nodes.append({"name": b.name, "translation": b.translation, "rotation": b.rotation, "scale": b.scale,
                          **({"children": kids} if kids else {})})
        ib = add(inverse_bind(m.skeleton), F, "MAT4", "f")
        bone_roots = [base + i for i, b in enumerate(m.skeleton) if b.parent is None]
        skins.append({"joints": list(range(base, base + len(m.skeleton))), "inverseBindMatrices": ib,
                      "skeleton": bone_roots[0]})
        for i, n in enumerate(m.nodes):
            if n.skinned:
                nodes[i]["skin"] = 0
        extra_roots = bone_roots

    anims = []
    for c in m.animations:
        samplers, channels = [], []
        for ch in c.channels:
            inp = add(ch.times, F, "SCALAR", "f", minmax=False)
            accs[inp]["min"], accs[inp]["max"] = [min(ch.times)], [max(ch.times)]
            out = add(ch.values, F, "VEC4" if ch.path == "rotation" else "VEC3", "f")
            samplers.append({"input": inp, "output": out, "interpolation": ch.interpolation})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": base + ch.bone, "path": ch.path}})
        anims.append({"name": c.name, "samplers": samplers, "channels": channels})

    roots = m.roots or [i for i in range(len(m.nodes)) if not any(i in n.children for n in m.nodes)]
    g = {"asset": {"version": "2.0", "generator": "gbox-uap " + m.uap_version},
         "scene": 0, "scenes": [{"name": m.name, "nodes": roots + extra_roots}],
         "nodes": nodes, "meshes": meshes, "accessors": accs, "bufferViews": views,
         "buffers": [{"byteLength": len(buf), "uri": "data:application/octet-stream;base64," + base64.b64encode(bytes(buf)).decode()}],
         "extras": {"gbox": {"source": m.source, "unit_scale_m": m.unit_scale_m, "coordinate_system": m.coordinate_system,
                             "confidence": m.confidence, "provenance": m.provenance}}}
    for k, v in (("materials", materials), ("images", images), ("textures", textures), ("skins", skins), ("animations", anims)):
        if v:
            g[k] = v
    return g


def to_glb(m: Manifest, pkg: Path) -> bytes:
    """Self-contained binary glTF: geometry + every texture embedded (viewer, Blender paste, downloads)."""
    g = to_gltf(m)
    blob = bytearray(base64.b64decode(g["buffers"][0]["uri"].split(",", 1)[1]))
    for im in g.get("images", []):
        data = (pkg / im.pop("uri")).read_bytes()
        while len(blob) % 4:
            blob.append(0)
        g["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
        blob.extend(data)
        im.update(bufferView=len(g["bufferViews"]) - 1, mimeType="image/png" if data[:4] == b"\x89PNG" else "image/jpeg")
    while len(blob) % 4:
        blob.append(0)
    g["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(g, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


def read_accessor(g: dict, idx: int) -> list:
    """Decode an accessor back to Python values (used for round-trip validation)."""
    acc = g["accessors"][idx]
    view = g["bufferViews"][acc["bufferView"]]
    raw = base64.b64decode(g["buffers"][0]["uri"].split(",", 1)[1])
    fmt = {5126: "f", 5123: "H", 5125: "I"}[acc["componentType"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[acc["type"]]
    flat = struct.unpack_from(f"<{acc['count'] * width}{fmt}", raw, view["byteOffset"])
    return list(flat) if width == 1 else [list(flat[i:i + width]) for i in range(0, len(flat), width)]


def to_obj(m: Manifest) -> str:
    """Static geometry only (no rig/animation/node transforms) — OBJ cannot carry them."""
    lines, off = [f"# gbox-uap export of {m.name}; source {json.dumps(m.source)}"], 1
    for me in m.meshes:
        lines.append(f"o {me.name}")
        lines += [f"v {x} {y} {z}" for x, y, z in me.positions]
        lines += [f"vt {u} {v}" for u, v in (me.uvs or [])]
        lines += [f"vn {x} {y} {z}" for x, y, z in (me.normals or [])]
        def ref(i):
            i += off
            return f"{i}/{i if me.uvs else ''}/{i}" if me.normals else (f"{i}/{i}" if me.uvs else str(i))
        lines += [f"f {ref(a)} {ref(b)} {ref(c)}" for a, b, c in zip(*[iter(me.indices)] * 3)]
        off += len(me.positions)
    return "\n".join(lines) + "\n"
