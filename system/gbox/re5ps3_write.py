"""Bounded RE5 PS3 MOD vertex and TEX replacement in copied owned ARCs.

Fixed native topology, skeleton, palettes and resource extents only. No semantic
joint guessing, new cast topology, animation writer or gameplay acceptance.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image

from .re5ps3_arc import Arc, sha, MAX_ARCHIVE
from .re5ps3_models import Model, Texture, finite, extent, MAX_TEXTURE
from .re5ps3_collection import CHRIS, SHEVA, FILES

MAX_GLB = 128 * 1024 * 1024


def _array(value, shape, label):
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label}: expected numeric array') from exc
    if result.shape != shape:
        raise ValueError(f'{label}: expected shape {shape}')
    finite(result, label)
    return result


def _same(a, b):
    # Values exported as float32 and unchanged in the editor retain their native
    # bytes, including weight sums 253..257 and quantized non-unit normals.
    with np.errstate(over='ignore', invalid='ignore'):
        left, right = np.asarray(a, dtype='<f4'), np.asarray(b, dtype='<f4')
    return bool(np.isfinite(left).all() and np.isfinite(right).all() and np.array_equal(left, right))


def patch_model(data, patches, *, expected_sha256):
    """Native-coordinate arrays by mesh index; preserve all unspecified bytes.

    Positions use native centimetres; joints use numeric native joint IDs.
    Returning unchanged decoded attributes is a byte-exact no-op.
    """
    if sha(data) != expected_sha256:
        raise ValueError('MOD source hash differs from requested revision')
    model = Model(data)
    if not isinstance(patches, dict) or len(patches) > len(model.meshes):
        raise ValueError('expected bounded mesh patch map')
    meshes_at, vertices_at = struct.unpack_from('>2I', data, 56)
    # The owned targets have disjoint primary vertex spans. Reject aliases even
    # when only one descriptor is patched: otherwise an unselected mesh (and
    # potentially another LOD) would change without appearing in the receipt.
    spans = []
    for index, mesh in enumerate(model.meshes):
        start, offset = struct.unpack_from('>2I', data, meshes_at + index * 52 + 16)
        begin = vertices_at + offset + start * 32
        if len(mesh['positions']):
            spans.append((begin, begin + len(mesh['positions']) * 32))
    spans.sort()
    if any(right[0] < left[1] for left, right in zip(spans, spans[1:])):
        raise ValueError('overlapping native vertex spans are not supported by this writer')
    planned = {}
    changes = []
    touched = set()
    def write(at, raw):
        extent(data, at, len(raw), 'MOD write')
        for offset, byte in enumerate(raw, at):
            if offset in planned and planned[offset] != byte:
                raise ValueError('conflicting edits to aliased native vertex bytes')
            planned[offset] = byte
            touched.add(offset)
    for index, patch in patches.items():
        if type(index) is not int or not 0 <= index < len(model.meshes) or not isinstance(patch, dict):
            raise ValueError('invalid native mesh patch index')
        if set(patch) - {'positions', 'normals', 'uv', 'joints', 'weights'}:
            raise ValueError('unsupported MOD edit; topology/material/skeleton are fixed')
        mesh = model.meshes[index]
        touched = set()
        n, influences = mesh['joints'].shape
        descriptor = meshes_at + index * 52
        start, offset = struct.unpack_from('>2I', data, descriptor + 16)
        base = vertices_at + offset + start * 32
        raw = np.frombuffer(data, dtype=np.uint8, count=n * 32, offset=base).reshape(n, 32)
        edited = []
        if 'positions' in patch:
            positions = _array(patch['positions'], (n, 3), 'positions')
            if not _same(positions, mesh['positions']):
                with np.errstate(over='ignore', invalid='ignore'):
                    packed = np.rint((positions - model.bbox_min) / (model.bbox_max - model.bbox_min) * 32767)
                finite(packed, 'packed positions')
                if np.any(packed < -32768) or np.any(packed > 32767):
                    raise ValueError('positions exceed original MOD quantization bounds')
                for v, row in enumerate(packed.astype('>i2')):
                    write(base + v * 32, row.tobytes())
                edited.append('positions')
        if 'normals' in patch:
            normals = _array(patch['normals'], (n, 3), 'normals')
            if not _same(normals, mesh['normals']):
                lengths = np.linalg.norm(normals, axis=1)
                finite(lengths, 'normal lengths')
                if np.any(lengths <= 1e-12):
                    raise ValueError('zero-length native normal')
                packed = np.rint((normals / lengths[:, None] + 1) * 127.5).astype(np.uint8)
                for v, row in enumerate(packed):
                    write(base + v * 32 + (24 if influences == 8 else 16), row.tobytes())
                edited.append('normals')
        if 'uv' in patch:
            uv = _array(patch['uv'], (n, 2), 'UV')
            if not _same(uv, mesh['uv']):
                with np.errstate(over='ignore', invalid='ignore'):
                    packed = uv.astype('>f2')
                finite(packed, 'half-float UV conversion')
                for v, row in enumerate(packed):
                    write(base + v * 32 + (28 if influences == 8 else 24), row.tobytes())
                edited.append('uv')
        joints = _array(patch.get('joints', mesh['joints']), (n, influences), 'joints')
        weights = _array(patch.get('weights', mesh['weights']), (n, influences), 'weights')
        if not _same(joints, mesh['joints']) or not _same(weights, mesh['weights']):
            if np.any(joints != np.floor(joints)) or np.any(joints < 0) or np.any(joints >= len(model.parents)):
                raise ValueError('joint IDs outside native skeleton')
            if np.any(weights < 0) or np.any(weights > 1) or not np.allclose(weights.sum(1), 1, atol=1e-6, rtol=0):
                raise ValueError('edited weights must sum to one')
            if np.any(np.count_nonzero(weights, axis=1) > data[descriptor + 7]):
                raise ValueError('edited weights exceed native declared influence count')
            palette = model.palettes[mesh['palette']]
            decode = [palette[j] if j < len(palette) else model.bone_map[j] for j in range(256)]
            quantized = np.floor(weights * 255).astype(np.uint16)
            fractions = weights * 255 - quantized
            for v in range(n):
                order = np.argsort(-fractions[v], kind='stable')
                quantized[v, order[:255 - int(quantized[v].sum())]] += 1
                ids = bytearray(raw[v, 8:8 + influences].tobytes())
                for c in range(influences):
                    if not quantized[v, c]:
                        continue
                    bone = int(joints[v, c])
                    choices = [code for code, resolved in enumerate(decode) if resolved == bone]
                    if not choices:
                        raise ValueError('joint is not addressable by this native mesh palette/map')
                    if ids[c] not in choices:
                        ids[c] = choices[0]
                write(base + v * 32 + 8, ids + quantized[v].astype(np.uint8).tobytes())
            edited.extend(['joints', 'weights'])
        if any(data[at] != planned[at] for at in touched):
            changes.append({'mesh': index, 'fields': edited, 'native_lod_mask': mesh['lod']})
    output = bytearray(data)
    for at, byte in planned.items():
        output[at] = byte
    output = bytes(output)
    checked = Model(output)
    if checked.parents != model.parents or checked.anim_map != model.anim_map:
        raise ValueError('writer changed native skeleton mapping')
    return output, {'source_sha256': sha(data), 'sha256': sha(output), 'changes': changes,
                    'affected_lod_masks': sorted({mask for item in changes for mask in (1, 2, 4)
                                                 if item['native_lod_mask'] & mask}),
                    'changed_bytes': sum(a != b for a, b in zip(data, output)),
                    'noop_identical': output == data, 'gameplay_verified': False}


def _glb(data):
    if not 28 <= len(data) <= MAX_GLB or struct.unpack_from('<3I', data) != (0x46546c67, 2, len(data)):
        raise ValueError('expected bounded binary glTF v2')
    size, kind = struct.unpack_from('<2I', data, 12)
    extent(data, 20, size + 8, 'GLB JSON')
    if kind != 0x4e4f534a or size % 4 or size > 8 * 1024 * 1024:
        raise ValueError('expected aligned GLB JSON chunk')
    doc = json.loads(data[20:20 + size])
    if not isinstance(doc, dict):
        raise ValueError('expected GLB JSON object')
    count, kind = struct.unpack_from('<2I', data, 20 + size)
    if kind != 0x004e4942 or count % 4 or 28 + size + count != len(data):
        raise ValueError('expected one embedded GLB binary chunk')
    blob = data[28 + size:]
    if len(doc.get('buffers', [])) != 1 or doc['buffers'][0].get('uri') or doc['buffers'][0].get('byteLength') != len(blob):
        raise ValueError('GLB must use one exact embedded buffer')
    def acc(index, shape, components):
        if type(index) is not int or not 0 <= index < len(doc.get('accessors', [])):
            raise ValueError('missing GLB accessor')
        a = doc['accessors'][index]
        if a.get('sparse') or a.get('normalized') or a.get('type') != shape or a.get('componentType') not in components:
            raise ValueError('unsupported GLB accessor representation')
        count = a.get('count')
        if type(count) is not int or not 0 <= count <= 8_000_000:
            raise ValueError('GLB accessor count exceeds limit')
        vi = a.get('bufferView')
        if type(vi) is not int or not 0 <= vi < len(doc.get('bufferViews', [])):
            raise ValueError('missing GLB buffer view')
        view = doc['bufferViews'][vi]
        if view.get('buffer', 0) != 0 or view.get('byteStride'):
            raise ValueError('only tightly packed embedded GLB accessors are supported')
        width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[shape]
        dtype = {5126: '<f4', 5123: '<u2', 5125: '<u4'}[a['componentType']]
        offset, length = view.get('byteOffset', 0), view.get('byteLength')
        inner = a.get('byteOffset', 0)
        if any(type(v) is not int for v in (offset, length, inner)):
            raise ValueError('invalid GLB accessor offsets')
        extent(blob, offset, length, 'GLB buffer view')
        needed = count * width * np.dtype(dtype).itemsize
        if inner < 0 or inner + needed > length:
            raise ValueError('GLB accessor outside buffer view')
        out = np.frombuffer(blob, dtype=dtype, count=count * width, offset=offset + inner).reshape(count, width)
        finite(out, 'GLB accessor')
        return out
    return doc, acc


def model_from_glb(data, glb, *, expected_sha256):
    """Read edited attributes from our exported GLB; reject topology/rig edits."""
    model = Model(data)
    doc, acc = _glb(glb)
    evidence = doc.get('extras') or {}
    if evidence.get('source_sha256') != expected_sha256 or sha(data) != expected_sha256:
        raise ValueError('edited GLB does not identify this exact native MOD')
    lod = evidence.get('lod_mask')
    if lod not in (1, 2, 4):
        raise ValueError('missing explicit native LOD mask')
    selected = {m['index']: m for m in model.meshes if m['visible'] and m['lod'] & lod and len(m['triangles'])}
    if len(doc.get('meshes', [])) != 1 or len(doc.get('skins', [])) != 1:
        raise ValueError('native edit must retain one mesh and one skin')
    if doc.get('animations') or doc['meshes'][0].get('weights'):
        raise ValueError('native animation and morph edits are not supported')
    nodes = doc.get('nodes', [])
    skin = doc['skins'][0]
    if len(nodes) != len(model.parents) + 2 or skin.get('joints') != list(range(2, len(nodes))):
        raise ValueError('native joint IDs/order changed')
    roots = [i + 2 for i, parent in enumerate(model.parents) if parent == 255]
    if nodes[0].get('children') != [1] + roots or nodes[1].get('mesh') != 0 or nodes[1].get('skin') != 0:
        raise ValueError('native mesh/root bindings changed')
    if any(key in n for n in nodes[:2] for key in ('matrix', 'translation', 'rotation', 'scale')):
        raise ValueError('mesh transforms must be applied before native export')
    for i, node in enumerate(nodes[2:]):
        matrix = model.local[i].copy(); matrix[:3, 3] *= .01
        value = _array(node.get('matrix'), (16,), 'joint matrix').reshape(4, 4).T
        if not _same(value, matrix) or any(k in node for k in ('translation', 'rotation', 'scale')):
            raise ValueError('native bind-pose matrix changed')
        if node.get('children', []) != [j + 2 for j, parent in enumerate(model.parents) if parent == i]:
            raise ValueError('native joint hierarchy changed')
    inverse = model.inverse_bind.copy(); inverse[:, :3, 3] *= .01
    if not _same(acc(skin.get('inverseBindMatrices'), 'MAT4', {5126}), inverse.transpose(0, 2, 1).reshape(-1, 16)):
        raise ValueError('native inverse bind matrices changed')
    patches = {}
    for primitive in doc['meshes'][0].get('primitives', []):
        if primitive.get('targets'):
            raise ValueError('native morph targets are not supported')
        index = (primitive.get('extras') or {}).get('index')
        if type(index) is not int or index not in selected or index in patches or primitive.get('mode', 4) != 4:
            raise ValueError('missing, duplicated or unsupported native primitive identity')
        mesh = selected[index]
        if not np.array_equal(acc(primitive.get('indices'), 'SCALAR', {5123, 5125}).reshape(-1, 3), mesh['triangles']):
            raise ValueError('native topology or vertex ordering changed')
        attrs = primitive.get('attributes') or {}
        joints, weights = [], []
        for slot in range(mesh['joints'].shape[1] // 4):
            joints.append(acc(attrs.get(f'JOINTS_{slot}'), 'VEC4', {5123}))
            weights.append(acc(attrs.get(f'WEIGHTS_{slot}'), 'VEC4', {5126}))
        # Convert in float64; float32 centimetre conversion would move unchanged
        # vertices by an unnecessary extra rounding step.
        positions = acc(attrs.get('POSITION'), 'VEC3', {5126}).astype(float) / .01
        original_export = (mesh['positions'] * .01).astype('<f4')
        if np.array_equal(acc(attrs.get('POSITION'), 'VEC3', {5126}), original_export):
            positions = mesh['positions']
        patches[index] = {'positions': positions, 'normals': acc(attrs.get('NORMAL'), 'VEC3', {5126}),
                          'uv': acc(attrs.get('TEXCOORD_0'), 'VEC2', {5126}),
                          'joints': np.concatenate(joints, axis=1), 'weights': np.concatenate(weights, axis=1)}
    if set(patches) != set(selected):
        raise ValueError('edited GLB omitted native LOD primitives')
    return patch_model(data, patches, expected_sha256=expected_sha256)


def replace_texture(data, image, *, expected_sha256):
    """Replace one same-size native texture and regenerate its existing mip chain."""
    if sha(data) != expected_sha256:
        raise ValueError('TEX source hash differs from requested revision')
    texture = Texture(data)
    if image.size != (texture.width, texture.height):
        raise ValueError('texture replacement must retain exact native dimensions')
    image = image.convert('RGBA')
    if image.tobytes() == texture.image().tobytes():
        return data, {'noop_identical': True, 'source_sha256': sha(data), 'sha256': sha(data), 'mips': texture.mips,
                      'gameplay_verified': False}
    # DXT1's one-bit alpha is not an arbitrary-alpha storage format.
    if texture.format == 'DXT1' and not np.isin(np.asarray(image)[:, :, 3], [0, 255]).all():
        raise ValueError('DXT1 replacement requires binary alpha')
    output = bytearray(data)
    errors = []
    for mip, (at, size) in enumerate(zip(texture.offsets, texture.sizes)):
        width, height = max(1, texture.width >> mip), max(1, texture.height >> mip)
        pixels = image if not mip else image.resize((width, height), Image.Resampling.LANCZOS)
        if texture.format == 'DXT1':
            alpha = pixels.getchannel('A').point(lambda x: 255 if x >= 128 else 0)
            pixels = pixels.copy(); pixels.putalpha(alpha)
        # Encode full blocks, edge-replicating padding for small mips.
        array = np.asarray(pixels)
        padded = np.pad(array, ((0, (-height) % 4), (0, (-width) % 4), (0, 0)), mode='edge')
        stream = io.BytesIO()
        try:
            Image.fromarray(padded).save(stream, format='DDS', pixel_format=texture.format)
        except (OSError, ValueError) as exc:
            raise ValueError('native TEX writing requires Pillow with the DXT1/DXT5 BCn encoder') from exc
        encoded = stream.getvalue()
        if len(encoded) != 128 + size or encoded[:4] != b'DDS ' or encoded[84:88] != texture.format.encode():
            raise ValueError('unexpected DXT encoder output extent/format')
        output[at:at + size] = encoded[128:]
    checked = Texture(bytes(output))
    for mip in range(texture.mips):
        width, height = max(1, texture.width >> mip), max(1, texture.height >> mip)
        desired = image if not mip else image.resize((width, height), Image.Resampling.LANCZOS)
        actual = np.asarray(checked.image(mip)).astype(int)
        wanted = np.asarray(desired).astype(int)
        if texture.format == 'DXT1' and not np.array_equal(actual[:, :, 3] >= 128, wanted[:, :, 3] >= 128):
            raise ValueError('DXT1 encoder did not retain the requested binary alpha')
        error = np.abs(actual - wanted)
        errors.append({'mip': mip, 'mean_absolute_rgba_error': float(error.mean()), 'max_rgba_error': int(error.max())})
    output = bytes(output)
    return output, {'source_sha256': sha(data), 'sha256': sha(output), 'noop_identical': False,
                    'mips': texture.mips, 'compression_error': errors, 'gameplay_verified': False}


def write_archive(source, member, output, *, expected_sha256, geometry_glb=None, texture_image=None):
    if sha(source) != expected_sha256 or expected_sha256 not in (FILES[CHRIS][1], FILES[SHEVA][1]):
        raise ValueError('writer requires an exact owned BLUS30491 normal Chris/Sheva ARC')
    if (geometry_glb is None) == (texture_image is None):
        raise ValueError('choose exactly one native geometry or texture edit')
    archive = Arc(source)
    magic = b'\0DOM' if geometry_glb is not None else b'\0XET'
    found = [(e, archive.read(e)) for e in archive.entries if e.name == member]
    found = [(e, data) for e, data in found if data[:4] == magic]
    if len(found) != 1:
        raise ValueError('expected one exact native resource of the requested format')
    entry, data = found[0]
    if geometry_glb is not None:
        changed, receipt = model_from_glb(data, geometry_glb, expected_sha256=sha(data))
    else:
        changed, receipt = replace_texture(data, texture_image, expected_sha256=sha(data))
    built = archive.replace(member, entry.type_hash, changed, expected_sha256=expected_sha256)
    checked = Arc(built)
    for old in archive.entries:
        current = checked.read(checked.find(*old.key))
        if current != (changed if old.key == entry.key else archive.read(old)):
            raise ValueError('copied ARC resource readback mismatch')
    with Path(output).open('xb') as stream:
        stream.write(built)
    if Path(output).read_bytes() != built:
        raise OSError('written ARC readback mismatch')
    return {'source_archive_sha256': sha(source), 'sha256': sha(built), 'output': str(output),
            'member': member, 'native_edit': receipt, 'unchanged_members_verified': len(archive.entries) - 1,
            'gameplay_verified': False, 'scope': 'fixed topology/rig and same-size TEX only; no full-cast writer'}


def _bounded_file(path, maximum):
    if Path(path).stat().st_size > maximum:
        raise ValueError('input exceeds supported byte limit')
    with Path(path).open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('input grew beyond supported byte limit')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--member', required=True)
    parser.add_argument('--expected-sha256', required=True)
    edit = parser.add_mutually_exclusive_group(required=True)
    edit.add_argument('--geometry-glb', type=Path, help='Our native GLB with vertex edits; fixed topology and rig')
    edit.add_argument('--texture-png', type=Path, help='Same native dimensions; existing mip chain is regenerated')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    image = None
    if args.texture_png:
        image = Image.open(io.BytesIO(_bounded_file(args.texture_png, MAX_TEXTURE)))
        if image.format != 'PNG' or image.width * image.height > 16 * 1024 * 1024:
            parser.error('expected bounded PNG texture replacement')
    receipt = write_archive(_bounded_file(args.archive, MAX_ARCHIVE), args.member, args.out,
                            expected_sha256=args.expected_sha256,
                            geometry_glb=_bounded_file(args.geometry_glb, MAX_GLB) if args.geometry_glb else None,
                            texture_image=image)
    print(json.dumps(receipt, allow_nan=False))


if __name__ == '__main__':
    main()
