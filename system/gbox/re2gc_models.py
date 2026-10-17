"""RE2 GameCube player models: native rigid bind-pose meshes to editable GLB.

PLD parsing/writing lives in re2gc_native. Geometry, per-face TIM palette/page
selection and the native EMR hierarchy are retained here. Extra MD1 parts with
no proven EMR attachment are refused, not silently dropped. Animation playback
and complete cast replacement are separate from this bind-pose extraction.
Format reference: OpenBiohazard2 173f900d174a41af56bd478692892254a2e31aae,
fileio/{md1,emr,tim}.go and render/AnimatedEntity.go; owned GHAE08 verification.
"""
from __future__ import annotations

import argparse
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from .re2gc_native import Model, GAME_ID, DISC_ID, DOL_SHA256, sha

# Native +X is forward, +Y down, +Z left. Proper rotation, determinant +1.
C = np.array([[0., 0., 1.], [0., -1., 0.], [1., 0., 0.]])
ROLES = {'hip': 1, 'chest': 0, 'head': 8, 'neck': 8,
         'l_upper': 12, 'l_fore': 13, 'l_hand': 14, 'r_upper': 9, 'r_fore': 10, 'r_hand': 11,
         'l_thigh': 5, 'l_shin': 6, 'l_foot': 7, 'r_thigh': 2, 'r_shin': 3, 'r_foot': 4}
EXPECTED_CHILDREN = [[1, 8, 9, 12], [2, 5], [3], [4], [], [6], [7], [], [], [10], [11], [], [13], [14], []]
READER_VERSION = 1
KEYS = ('00', '00CH', '01', '01CH', '02', '03', '04', '05', '06', '07', '08', '09', '0A', '0B', '0BCH', '0C', '0D', '0E', '0ECH', '0F')
NAMES = {'00': 'Leon', '01': 'Claire', '0C': 'HUNK', '0D': 'Tofu', '0E': 'Ada', '0F': 'Sherry'}


def bind_pose(model):
    """Native EMR translations accumulated through its actual parent graph."""
    skeleton = model.skeleton
    if len(model.objects) != skeleton['bones']:
        raise ValueError(f"{len(model.objects)} mesh parts but {skeleton['bones']} bones: extra-part attachments require loader analysis")
    parents = [-1] * skeleton['bones']
    for parent, children in enumerate(skeleton['children']):
        for child in children:
            if parents[child] != -1:
                raise ValueError('EMR bone has multiple parents')
            parents[child] = parent
    positions = np.asarray(skeleton['positions'], dtype=float)
    worlds = np.zeros_like(positions)
    done = set()
    def visit(i):
        if i in done:
            return worlds[i]
        parent = parents[i]
        worlds[i] = positions[i] + (visit(parent) if parent >= 0 else 0)
        done.add(i)
        return worlds[i]
    for i in range(len(parents)):
        visit(i)
    return parents, worlds


def palette_image(model, clut):
    """One exact TIM palette, including transparent zero and opaque black."""
    t = model.texture; data = model.sections['tim']
    x = (clut & 63) * 16 - t['clut_x']
    y = (clut >> 6) - t['clut_y']
    colors = 16 if t['bpp'] == 4 else 256
    if y < 0 or y >= t['palettes'] or x < 0 or x + colors > t['colors']:
        raise ValueError('polygon CLUT outside owned TIM palettes')
    palette = np.frombuffer(data, dtype='<u2', count=colors, offset=20 + (y * t['colors'] + x) * 2)
    raw = np.frombuffer(data, dtype=np.uint8, count=t['width'] * t['height'] * t['bpp'] // 8, offset=t['image_offset'])
    if t['bpp'] == 4:
        indices = np.empty(len(raw) * 2, dtype=np.uint8)
        indices[0::2], indices[1::2] = raw & 15, raw >> 4
    else:
        indices = raw
    pixels = palette[indices].reshape(t['height'], t['width'])
    rgba = np.empty((*pixels.shape, 4), dtype=np.uint8)
    for channel, shift in enumerate((0, 5, 10)):
        bits = (pixels >> shift) & 31
        rgba[..., channel] = (bits << 3) | (bits >> 2)
    rgba[..., 3] = np.where(pixels == 0, 0, 255)
    return rgba


def geometry(model, scale=0.001):
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('scale must be positive and finite')
    parents, native_world = bind_pose(model)
    groups = {}
    for bone, primitive_groups in enumerate(model.objects):
        for group in primitive_groups:
            corners = 3 if group['kind'] == 'triangles' else 4
            for index, face in enumerate(group['indices']):
                raw = group['uv_bytes'][index * corners * 4:(index + 1) * corners * 4]
                clut, page = struct.unpack_from('<H', raw, 2)[0], struct.unpack_from('<H', raw, 6)[0]
                bpp = {0: 4, 1: 8, 2: 16}.get((page >> 7) & 3)
                if bpp != model.texture['bpp']:
                    raise ValueError('polygon texture depth does not match owned TIM')
                ox = (page & 15) * 64 * 16 // bpp - model.texture['image_x'] * 16 // bpp
                oy = ((page >> 4) & 1) * 256 - model.texture['image_y']
                uv = [(raw[k * 4] + ox, raw[k * 4 + 1] + oy) for k in range(corners)]
                if any(not 0 <= u < model.texture['width'] or not 0 <= v < model.texture['height'] for u, v in uv):
                    raise ValueError('polygon UV outside owned TIM image')
                dest = groups.setdefault(clut, {'pos': [], 'normal': [], 'uv': [], 'joint': []})
                positions = np.array([group['vertices'][face[k * 2 + 1]][:3] for k in range(corners)], float)
                positions = (positions + native_world[bone]) @ C.T * scale
                normals = np.array([group['normals'][face[k * 2]][:3] for k in range(corners)], float) @ C.T
                for tri in ([(0, 1, 2)] if corners == 3 else [(0, 1, 3), (0, 2, 3)]):
                    a, b, c = tri
                    # Native stored normals supply an independent front-side
                    # reference; do not hide reversed faces with doubleSided.
                    n = np.cross(positions[b] - positions[a], positions[c] - positions[a])
                    if np.dot(n, normals[[a, b, c]].sum(axis=0)) < 0:
                        tri = a, c, b
                    for k in tri:
                        norm = normals[k]
                        length = np.linalg.norm(norm)
                        if not length:
                            norm = n; length = np.linalg.norm(norm)
                        dest['pos'].append(positions[k])
                        dest['normal'].append(norm / (length or 1))
                        dest['uv'].append(((uv[k][0] + .5) / model.texture['width'], (uv[k][1] + .5) / model.texture['height']))
                        dest['joint'].append(bone)
    if not groups:
        raise ValueError('model has no faces')
    return parents, native_world @ C.T * scale, groups


def export_glb(model, path, *, name='re2gc', scale=0.001):
    parents, worlds, groups = geometry(model, scale)
    blob, views, accessors = bytearray(), [], []
    def view(data):
        blob.extend(bytes(-len(blob) % 4))
        views.append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(data)})
        blob.extend(data)
        return len(views) - 1
    def accessor(values, dtype, component, kind, extrema=False):
        values = np.asarray(values, dtype=dtype)
        record = {'bufferView': view(values.tobytes()), 'componentType': component, 'count': len(values), 'type': kind}
        if extrema:
            record.update(min=values.min(axis=0).tolist(), max=values.max(axis=0).tolist())
        accessors.append(record)
        return len(accessors) - 1
    materials, images, textures, primitives = [], [], [], []
    vertex_count = 0
    for clut, group in groups.items():
        count = len(group['pos']); vertex_count += count
        joints = np.zeros((count, 4), dtype='<u2'); joints[:, 0] = group['joint']
        weights = np.zeros((count, 4), dtype='<f4'); weights[:, 0] = 1
        attrs = {'POSITION': accessor(group['pos'], '<f4', 5126, 'VEC3', True),
                 'NORMAL': accessor(group['normal'], '<f4', 5126, 'VEC3'),
                 'TEXCOORD_0': accessor(group['uv'], '<f4', 5126, 'VEC2'),
                 'JOINTS_0': accessor(joints, '<u2', 5123, 'VEC4'),
                 'WEIGHTS_0': accessor(weights, '<f4', 5126, 'VEC4')}
        png = io.BytesIO(); Image.fromarray(palette_image(model, clut)).save(png, format='PNG')
        images.append({'bufferView': view(png.getvalue()), 'mimeType': 'image/png'})
        textures.append({'source': len(images) - 1, 'sampler': 0})
        materials.append({'name': f'clut_{clut:04x}', 'pbrMetallicRoughness': {
            'baseColorTexture': {'index': len(textures) - 1}, 'metallicFactor': 0, 'roughnessFactor': 1},
            'alphaMode': 'MASK', 'alphaCutoff': .5, 'doubleSided': False})
        primitives.append({'attributes': attrs, 'mode': 4, 'material': len(materials) - 1})
    ground = min(float(np.asarray(g['pos'])[:, 1].min()) for g in groups.values())
    nodes = [{'name': name, 'children': [1], 'translation': [0, -ground, 0]},
             {'name': name + '_mesh', 'mesh': 0, 'skin': 0}]
    inverse = []
    for i, parent in enumerate(parents):
        local = worlds[i] - (worlds[parent] if parent >= 0 else 0)
        node = {'name': f'j{i:02d}', 'translation': local.tolist()}
        children = [2 + j for j, p in enumerate(parents) if p == i]
        if children:
            node['children'] = children
        nodes.append(node)
        matrix = np.eye(4); matrix[:3, 3] = -worlds[i]
        inverse.append(matrix.T.reshape(-1))
    roots = [2 + i for i, p in enumerate(parents) if p < 0]
    nodes[0]['children'].extend(roots)
    skin = {'joints': list(range(2, 2 + len(parents))), 'inverseBindMatrices': accessor(inverse, '<f4', 5126, 'MAT4')}
    if len(roots) == 1:
        skin['skeleton'] = roots[0]
    gltf = {'asset': {'version': '2.0', 'generator': 'gBox re2gc_models'},
            'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': nodes, 'skins': [skin],
            'meshes': [{'primitives': primitives}], 'materials': materials, 'images': images, 'textures': textures,
            'samplers': [{'magFilter': 9728, 'minFilter': 9728, 'wrapS': 33071, 'wrapT': 33071}],
            'bufferViews': views, 'accessors': accessors, 'buffers': [{'byteLength': len(blob)}],
            'extras': {'native_source_sha256': sha(model.data), 'pose': 'native EMR bind translations',
                       'gameplay_verified': False, 'native_sem_transparency': 'nonzero colors use opaque alpha; zero is masked'}}
    raw = json.dumps(gltf, separators=(',', ':')).encode()
    raw += b' ' * (-len(raw) % 4); blob.extend(bytes(-len(blob) % 4))
    result = struct.pack('<3I', 0x46546c67, 2, 28 + len(raw) + len(blob))
    result += struct.pack('<2I', len(raw), 0x4e4f534a) + raw + struct.pack('<2I', len(blob), 0x004e4942) + blob
    with Path(path).open('xb') as f:
        f.write(result)
    if Path(path).read_bytes() != result:
        raise OSError('GLB write readback mismatch')
    roles = {k: f'j{v:02d}' for k, v in ROLES.items()} if model.skeleton['children'] == EXPECTED_CHILDREN else {}
    return {'path': str(path), 'source_sha256': sha(model.data), 'sha256': sha(result),
            'triangles': vertex_count // 3, 'bones': len(parents), 'palettes': len(groups), 'roles': roles,
            'pose': 'native EMR bind translations', 'gameplay_verified': False}


def roster():
    return [{'key': f'Pl{scenario}/PLD/PL{key}.PLD', 'slug': f're2gc_pl{scenario}_{key.lower()}',
             'name': f'{NAMES.get(key, "Player model PL" + key)} (RE2 GC, Pl{scenario}/PL{key})',
             'kind': 'character', 'aliases': [f'RE2 GC Pl{scenario} PL{key}']}
            for scenario in (0, 1) for key in KEYS]


def extract_run(ctx, game, entry, work):
    from .characters import _rom
    from .gcdisc import GCDisc
    if game.get('game_id') != GAME_ID or game.get('platform') != 'gamecube':
        raise ValueError('RE2 GameCube extractor requires the exact GHAE08 catalog game')
    if entry.get('key') not in {e['key'] for e in roster()}:
        raise ValueError('unknown RE2 player member')
    disc = GCDisc(_rom(ctx, game))
    try:
        if disc.game_id != DISC_ID or sha(disc.dol()) != DOL_SHA256:
            raise ValueError('unverified RE2 GameCube executable revision')
        model = Model(disc.read(entry['key']))
        out = Path(work) / (entry['slug'] + '.glb')
        result = export_glb(model, out, name=entry['slug'])
    finally:
        disc.f.close()
    return {'files': [out], 'roles': result['roles'], 'tool': 'gbox.re2gc_models',
            'source_files': [entry['key'], 'main.dol SHA256 ' + DOL_SHA256],
            'notes': 'Native textured, rigidly skinned bind-pose extraction. Extra-part attachments, animation playback and gameplay replacement acceptance remain separate.',
            'extra': {'re2gc_reader': READER_VERSION, 'native_evidence': result}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pld', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_glb(Model(args.pld.read_bytes()), args.out, name=args.pld.stem)))


if __name__ == '__main__':
    main()
