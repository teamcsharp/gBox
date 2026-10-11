"""Find and decode NaomiLib (AM2) models in any Dreamcast/NAOMI file.

NaomiLib is the model format SEGA AM2 used on NAOMI and Dreamcast (DOA2,
MVC2, Shenmue 2, Daytona USA 2001, Virtua Tennis...). NaomiMod's nl_scan.py
(games-ExtractTools) finds these models by scanning raw game files instead of
relying on one game's archive table. This module does the same job inside
gBox, written independently from the published format notes:
https://github.com/NaomiMod/NL-ModelFormat/wiki and
https://github.com/NaomiMod/games-ExtractTools/blob/main/DOA2/CHR_Format.md
(credits: VincentNL, EgregiousGuy, The_Zocker160). No GPL code is copied.

Layout handled (verified on the owned DOA2 LE Japan disc, #1275):
  model   +0  u32 global flag 0, +4 u32 global flag 1,
          +8  4 x f32 bounding centroid xyz + radius,
          +24 mesh headers, ended by u32 0 then u32 total vertex records.
  mesh    80-byte header: +0 PVR parameter control word (top 3 bits = 4),
          +32 i32 texture id, +36 i32 shader (-2: 56-byte vertices,
          -3: packed s8 normals), +76 u32 byte length of the polygon data.
  polygon u32 flags (bit 3 triangle list, bit 4 strip, bits 0-1 culling),
          u32 count, then inline vertices or 8-byte back-references
          (tag 0x5ffxxxxx, i32 relative to the end of the reference).

A scan result is a list of models; `to_obj`/`to_glb` write them for Blender
(or the blender-NaomiLib addon can open the original file at the reported
offset). Character archives (DOA2 CHR) hold each body part in its bone's local
space: a scan export shows the parts unassembled. Do not add a scan export to
the character collection; a fighter needs the game's skeleton placement
(gbox/doa2_chars.py on the #1135 branch for DOA2).
Pure Python plus optional numpy, no Blender dependency.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

_U32 = struct.Struct('<I')
MESH_HEADER = 80
MODEL_HEADER = 24


def _u32(data, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError(f'u32 outside data at {offset:#x}')
    return _U32.unpack_from(data, offset)[0]


def _triangles(flags: int, indices: list[int]) -> list[tuple[int, int, int]]:
    culling = flags & 3
    if flags & 8:
        triples = [(indices[k], indices[k+1], indices[k+2]) for k in range(0, len(indices) - 2, 3)]
        if culling == 2:
            triples = [(y, x, z) for x, y, z in triples]
    elif flags & 0x10:
        triples = []
        for k in range(len(indices) - 2):
            x, y, z = indices[k:k+3]
            if (k % 2 == 0) == (culling == 2):
                x, y = y, x
            triples.append((x, y, z))
    else:
        raise ValueError('unsupported NaomiLib fan/sprite primitive')
    return [t for t in triples if len(set(t)) == 3]


def decode_model(data, start: int, limit: int | None = None) -> dict:
    """Decode one NaomiLib model at `start`; raise ValueError when it isn't one."""
    limit = len(data) if limit is None else min(limit, len(data))
    if start < 0 or start + MODEL_HEADER + 8 > limit:
        raise ValueError('short NaomiLib model')
    gp0, gp1 = struct.unpack_from('<2I', data, start)
    centroid = struct.unpack_from('<4f', data, start + 8)
    if not all(math.isfinite(v) for v in centroid) or not 0 <= centroid[3] < 1e7:
        raise ValueError('implausible bounding sphere')
    cursor = start + MODEL_HEADER
    meshes, vertex_total = [], 0
    while cursor + 4 <= limit and _u32(data, cursor):
        if cursor + MESH_HEADER > limit:
            raise ValueError(f'truncated mesh header at {cursor:#x}')
        if _u32(data, cursor) >> 29 != 4:
            raise ValueError(f'not a polygon parameter at {cursor:#x}')
        texture_id, shader = struct.unpack_from('<2i', data, cursor + 32)
        length = _u32(data, cursor + 76)
        position = cursor + MESH_HEADER
        stop = position + length
        if not 0 < length or stop > limit:
            raise ValueError(f'mesh at {cursor:#x} runs past the data')
        vertices, triangles, registered = [], [], {}
        while position < stop:
            if position + 8 > stop:
                raise ValueError('short polygon header')
            flags, count = struct.unpack_from('<2I', data, position)
            if flags > 0x1ff or not 0 < count <= 65536:
                raise ValueError(f'invalid polygon at {position:#x}')
            logical = count * (3 if flags & 8 else 1)
            position += 8
            indices = []
            for _ in range(logical):
                if position + 4 > stop:
                    raise ValueError('short vertex record')
                tag = _u32(data, position)
                if 0x5ff00000 <= tag <= 0x5fffffff:
                    if position + 8 > stop:
                        raise ValueError('short vertex reference')
                    target = position + 8 + struct.unpack_from('<i', data, position + 4)[0]
                    if target not in registered:
                        raise ValueError(f'reference to no earlier vertex at {position:#x}')
                    indices.append(registered[target])
                    position += 8
                    continue
                size = 56 if shader == -2 else 32
                if position + size > stop:
                    raise ValueError('vertex crosses the mesh end')
                xyz = struct.unpack_from('<3f', data, position)
                if shader == -3:
                    normal = tuple(max(-1.0, v / 127) for v in struct.unpack_from('<3b', data, position + 12))
                    uv = struct.unpack_from('<2f', data, position + 24)
                else:
                    normal = struct.unpack_from('<3f', data, position + 12)
                    uv = struct.unpack_from('<2f', data, position + size - 8)
                if not all(math.isfinite(v) for v in (*xyz, *normal, *uv)):
                    raise ValueError('non-finite vertex')
                registered[position] = len(vertices)
                indices.append(len(vertices))
                vertices.append((*xyz, *normal, *uv))
                position += size
            triangles.extend(_triangles(flags, indices))
            vertex_total += logical
        meshes.append({'offset': cursor, 'texture_id': texture_id, 'shader': shader,
                       'vertices': vertices, 'triangles': triangles})
        cursor = stop
    if not meshes:
        raise ValueError('model has no meshes')
    if cursor + 8 > limit or _u32(data, cursor) != 0:
        raise ValueError(f'model has no end marker at {cursor:#x}')
    declared = _u32(data, cursor + 4)
    if declared != vertex_total:
        raise ValueError(f'declared {declared} vertex records, found {vertex_total}')
    return {'offset': start, 'end_offset': cursor + 8, 'global_flags': (gp0, gp1),
            'centroid': centroid, 'meshes': meshes, 'vertex_count': vertex_total,
            'triangle_count': sum(len(m['triangles']) for m in meshes)}


def _candidates(data) -> list[int]:
    """Model starts whose first mesh word is a PVR polygon parameter (top bits 100)."""
    n = len(data) // 4
    try:
        import numpy as np
        words = np.frombuffer(data, dtype='<u4', count=n)
        hits = np.nonzero((words >> 29) == 4)[0] * 4 - MODEL_HEADER
        return [int(h) for h in hits if h >= 0]
    except ImportError:
        words = struct.unpack_from(f'<{n}I', data)
        return [4 * k - MODEL_HEADER for k, w in enumerate(words) if w >> 29 == 4 and 4 * k >= MODEL_HEADER]


def scan(data, *, min_triangles: int = 1) -> list[dict]:
    """Every NaomiLib model in `data`, found without an archive table (nl_scan-style)."""
    data = bytes(data)
    found, resume = [], 0
    for start in _candidates(data):
        if start < resume:
            continue
        try:
            model = decode_model(data, start)
        except (ValueError, struct.error):
            continue
        if model['triangle_count'] < min_triangles:
            continue
        found.append(model)
        resume = model['end_offset']
    return found


def to_obj(models: list[dict], name: str = 'naomilib') -> str:
    """Wavefront OBJ text: one object per model, one group per mesh/texture."""
    lines, base = [f'# {name}: {len(models)} NaomiLib models (gbox.naomilib)'], 1
    for m in models:
        lines.append(f"o model_{m['offset']:08x}")
        for k, mesh in enumerate(m['meshes']):
            lines.append(f"g model_{m['offset']:08x}_mesh{k}_tex{mesh['texture_id']}")
            for v in mesh['vertices']:
                lines.append('v %.6g %.6g %.6g' % v[:3])
            for v in mesh['vertices']:
                lines.append('vt %.6g %.6g' % (v[6], 1 - v[7]))
            for v in mesh['vertices']:
                lines.append('vn %.6g %.6g %.6g' % v[3:6])
            for a, b, c in mesh['triangles']:
                a, b, c = a + base, b + base, c + base
                lines.append(f'f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}')
            base += len(mesh['vertices'])
    return '\n'.join(lines) + '\n'


def to_glb(models: list[dict], path, name: str = 'naomilib') -> Path:
    """Binary glTF: one node + mesh per NaomiLib model, one primitive per mesh (untextured, unskinned).

    Vertices stay in the file's own coordinates; nothing is re-posed or invented."""
    import json
    blob, views, accessors, meshes, nodes = bytearray(), [], [], [], []

    def add(raw: bytes, target: int | None) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(raw),
                      **({'target': target} if target else {})})
        blob.extend(raw)
        return len(views) - 1

    for m in models:
        prims = []
        for mesh in m['meshes']:
            if not mesh['triangles']:
                continue
            verts = mesh['vertices']
            pos = [v[:3] for v in verts]
            lo = [min(p[k] for p in pos) for k in range(3)]
            hi = [max(p[k] for p in pos) for k in range(3)]
            normals = []
            for v in verts:
                length = math.sqrt(v[3] ** 2 + v[4] ** 2 + v[5] ** 2)
                normals.append((v[3] / length, v[4] / length, v[5] / length) if length > 1e-6 else (0.0, 0.0, 1.0))
            attrs = {}
            for key, rows, extra in (('POSITION', pos, {'min': lo, 'max': hi}), ('NORMAL', normals, {}),
                                     ('TEXCOORD_0', [v[6:8] for v in verts], {})):
                width = len(rows[0])
                view = add(struct.pack(f'<{len(rows) * width}f', *(c for r in rows for c in r)), 34962)
                accessors.append({'bufferView': view, 'componentType': 5126, 'count': len(rows),
                                  'type': f'VEC{width}', **extra})
                attrs[key] = len(accessors) - 1
            flat = [i for tri in mesh['triangles'] for i in tri]
            view = add(struct.pack(f'<{len(flat)}I', *flat), 34963)
            accessors.append({'bufferView': view, 'componentType': 5125, 'count': len(flat), 'type': 'SCALAR'})
            prims.append({'attributes': attrs, 'indices': len(accessors) - 1, 'mode': 4,
                          'extras': {'texture_id': mesh['texture_id'], 'shader': mesh['shader']}})
        if prims:
            meshes.append({'name': f"model_{m['offset']:08x}", 'primitives': prims})
            nodes.append({'name': f"model_{m['offset']:08x}", 'mesh': len(meshes) - 1})
    if not meshes:
        raise ValueError(f'{name}: no NaomiLib triangles to write')
    while len(blob) % 4:
        blob.append(0)
    gl = {'asset': {'version': '2.0', 'generator': 'gbox.naomilib'},
          'scene': 0, 'scenes': [{'name': name, 'nodes': list(range(len(nodes)))}], 'nodes': nodes,
          'meshes': meshes, 'accessors': accessors, 'bufferViews': views, 'buffers': [{'byteLength': len(blob)}]}
    js = json.dumps(gl, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    out = struct.pack('<3I', 0x46546C67, 2, 28 + len(js) + len(blob))
    out += struct.pack('<2I', len(js), 0x4E4F534A) + js + struct.pack('<2I', len(blob), 0x004E4942) + bytes(blob)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


def summary(models: list[dict]) -> dict:
    return {'models': len(models), 'meshes': sum(len(m['meshes']) for m in models),
            'triangles': sum(m['triangle_count'] for m in models),
            'offsets': [m['offset'] for m in models]}


def main(argv=None) -> int:
    import argparse
    import json
    p = argparse.ArgumentParser(description='Scan files for NaomiLib models')
    p.add_argument('files', nargs='+')
    p.add_argument('--obj', help='write an OBJ per input file into this directory')
    p.add_argument('--glb', help='write a GLB per input file into this directory (parts stay in file coordinates)')
    a = p.parse_args(argv)
    for f in a.files:
        models = scan(Path(f).read_bytes())
        s = summary(models)
        print(json.dumps({'file': f, **{k: v for k, v in s.items() if k != 'offsets'},
                          'first_offsets': [hex(o) for o in s['offsets'][:8]]}))
        if a.obj and models:
            out = Path(a.obj) / (Path(f).name + '.obj')
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(to_obj(models, Path(f).name))
        if a.glb and models:
            to_glb(models, Path(a.glb) / (Path(f).name + '.glb'), Path(f).name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
