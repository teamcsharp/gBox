"""Bounded RE5 PS3 Gold MOD 156/revision 1 and TEX 102 bind-pose reader.

Produces editable GLBs, retaining native joints, 4/8 weights, UVs and diffuse
textures. The CLI consumes an already extracted owned ARC. It does not rewrite
game assets, claim shader equivalence, play animations or implement cast swaps.
Format facts checked against pinned Albam and RevilLib; see the RE5 reader doc.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from .re5ps3_arc import Arc, MAX_ARCHIVE, sha

READER_VERSION = 1
GAME_ID = 'e7ca89bbeb67360d'
TITLE_ID = 'BLUS30491'
MAX_MODEL = 64 * 1024 * 1024
MAX_TEXTURE = 64 * 1024 * 1024
MAX_TEXTURE_PIXELS = 16 * 1024 * 1024
MAX_TOTAL_TEXTURE_PIXELS = 64 * 1024 * 1024


def extent(data, at, size, label):
    if at < 0 or size < 0 or at > len(data) or size > len(data) - at:
        raise ValueError(f'{label} outside source extent')


def finite(values, label):
    if not np.isfinite(values).all():
        raise ValueError(f'{label} has a non-finite component')


class Texture:
    """Single-face PS3 TEX 102; DXT blocks are linear and little endian."""
    def __init__(self, data):
        self.data = bytes(data)
        if not 40 <= len(data) <= MAX_TEXTURE or data[:4] != b'\0XET':
            raise ValueError('not a bounded PS3 TEX')
        version, layout, self.mips, faces, self.width, self.height, depth = struct.unpack_from('>HHBBHHH', data, 4)
        if version != 102 or faces != 1 or depth not in (0, 1) or layout >> 12 != 2:
            raise ValueError('unsupported PS3 TEX version, layout or face/depth count')
        if not 1 <= self.width <= 4096 or not 1 <= self.height <= 4096 or self.width * self.height > MAX_TEXTURE_PIXELS:
            raise ValueError('TEX dimensions exceed limits')
        if not 1 <= self.mips <= max(self.width, self.height).bit_length():
            raise ValueError('TEX mip count exceeds dimensions')
        self.format = bytes(data[16:20][::-1]).decode('ascii', errors='replace')
        if self.format not in ('DXT1', 'DXT5'):
            raise ValueError('unsupported PS3 TEX compression')
        self.color_correction = list(struct.unpack_from('>4f', data, 20))
        finite(self.color_correction, 'TEX color correction')
        table_end = 36 + self.mips * 4
        extent(data, 36, self.mips * 4, 'TEX mip table')
        self.offsets = struct.unpack_from(f'>{self.mips}I', data, 36)
        previous_end = table_end
        self.sizes = []
        for mip, at in enumerate(self.offsets):
            w, h = max(1, self.width >> mip), max(1, self.height >> mip)
            size = ((w + 3) // 4) * ((h + 3) // 4) * (8 if self.format == 'DXT1' else 16)
            if at < previous_end:
                raise ValueError('overlapping or unordered TEX mip extents')
            extent(data, at, size, 'TEX mip payload')
            previous_end = at + size
            self.sizes.append(size)

    def image(self, mip=0):
        if not isinstance(mip, int) or not 0 <= mip < self.mips:
            raise ValueError('TEX mip index outside table')
        w, h = max(1, self.width >> mip), max(1, self.height >> mip)
        at = self.offsets[mip]
        raw = self.data[at:at + self.sizes[mip]]
        return Image.frombytes('RGBA', (((w + 3) // 4) * 4, ((h + 3) // 4) * 4), raw,
                               'bcn', 1 if self.format == 'DXT1' else 3).crop((0, 0, w, h))


def triangles(indices):
    """Native restartable strip; degenerates advance parity, restarts reset it."""
    out, tail, length = [], [], 0
    for value in indices:
        value = int(value)
        if value == 65535:
            tail, length = [], 0
            continue
        length += 1
        tail.append(value)
        if length < 3:
            continue
        tri = tail[:]
        tail = tail[-2:]
        if length % 2 == 0:
            tri[0], tri[1] = tri[1], tri[0]
        if len(set(tri)) == 3:
            out.append(tri)
    return np.asarray(out, dtype='<u4').reshape(-1, 3)


class Model:
    def __init__(self, data):
        self.data = bytes(data)
        if not 176 <= len(data) <= MAX_MODEL or data[:4] != b'\0DOM':
            raise ValueError('not a bounded PS3 MOD')
        h = struct.unpack_from('>4H15I', data, 4)
        (version, nb, nm, nmat, nv, declared_indices, edges, size_v, size_v2,
         nt, ng, npal, bones, groups, mats, meshes, vertices, vertices2, indices) = h
        if version != 412:
            raise ValueError('expected PS3 MOD 156 revision 1 (combined 412)')
        if data[140] != 2:
            raise ValueError('unsupported MOD strip topology declaration')
        if not (1 <= nb <= 255 and 1 <= nm <= 4096 and 1 <= nmat <= 1024 and
                1 <= nv <= 1_000_000 and nt <= 1024 and 1 <= npal <= 256 and ng <= 4096):
            raise ValueError('MOD header counts exceed supported limits')
        if declared_indices < nm or declared_indices - nm > 8_000_000:
            raise ValueError('MOD index count outside supported range')
        self.header = dict(bones=nb, meshes=nm, materials=nmat, vertices=nv,
                           index_count=declared_indices - nm, textures=nt, palettes=npal)
        # On this PS3 format the header includes one sentinel per mesh, while
        # the stored spans omit those sentinels. Count every selected mesh from
        # its own descriptor; do not read num_indices*2 past EOF.
        spans = [(bones, nb * 152 + 256 + npal * 68, 'bones'),
                 (groups, ng * 32, 'groups'), (mats, nt * 64 + nmat * 160, 'materials'),
                 (meshes, nm * 52 + 4, 'meshes'), (vertices, size_v, 'vertices'),
                 (vertices2, size_v2, 'secondary vertices'),
                 (indices, (declared_indices - nm) * 2, 'indices')]
        occupied = []
        for at, size, label in spans:
            if size and at < 176:
                raise ValueError(f'MOD {label} overlaps header')
            extent(data, at, size, 'MOD ' + label)
            if size:
                occupied.append((at, at + size))
        occupied.sort()
        if any(a[1] > b[0] for a, b in zip(occupied, occupied[1:])):
            raise ValueError('overlapping MOD section extents')
        self.bbox_min = np.array(struct.unpack_from('>3f', data, 96))
        self.bbox_max = np.array(struct.unpack_from('>3f', data, 112))
        finite([self.bbox_min, self.bbox_max], 'MOD bounds')
        if np.any(self.bbox_max <= self.bbox_min):
            raise ValueError('invalid MOD bounding box')
        self.parents = [data[bones + i * 24 + 1] for i in range(nb)]
        self.anim_map = [data[bones + i * 24] for i in range(nb)]
        self.local = np.frombuffer(data, dtype='>f4', count=nb * 16, offset=bones + nb * 24).reshape(nb, 4, 4).transpose(0, 2, 1).astype(float)
        self.inverse_bind = np.frombuffer(data, dtype='>f4', count=nb * 16, offset=bones + nb * 88).reshape(nb, 4, 4).transpose(0, 2, 1).astype(float)
        finite(self.local, 'MOD local matrices'); finite(self.inverse_bind, 'MOD inverse binds')
        if not np.allclose(self.local[:, 3, :], [0, 0, 0, 1], atol=1e-5) or not np.allclose(self.inverse_bind[:, 3, :], [0, 0, 0, 1], atol=1e-5):
            raise ValueError('non-affine MOD bind matrix')
        self.world = np.empty_like(self.local)
        state = [0] * nb
        def visit(i):
            if state[i] == 1:
                raise ValueError('cycle in MOD bone hierarchy')
            if state[i] == 2:
                return self.world[i]
            state[i] = 1
            parent = self.parents[i]
            if parent != 255 and not 0 <= parent < nb:
                raise ValueError('MOD bone parent outside hierarchy')
            with np.errstate(over='ignore', invalid='ignore'):
                self.world[i] = self.local[i] if parent == 255 else visit(parent) @ self.local[i]
            finite(self.world[i], 'MOD accumulated world matrix')
            state[i] = 2
            return self.world[i]
        for i in range(nb):
            visit(i)
        with np.errstate(over='ignore', invalid='ignore'):
            bind_products = self.world @ self.inverse_bind
        finite(bind_products, 'MOD bind matrix products')
        self.bind_error = float(np.max(np.abs(bind_products - np.eye(4))))
        if not math.isfinite(self.bind_error) or self.bind_error > .002:
            raise ValueError('MOD local and inverse bind matrices disagree')
        map_at = bones + nb * 152
        self.bone_map = data[map_at:map_at + 256]
        self.palettes = []
        for i in range(npal):
            at = map_at + 256 + i * 68
            count = struct.unpack_from('>I', data, at)[0]
            if not 1 <= count <= 64:
                raise ValueError('MOD bone palette count outside 64-entry PS3 table')
            palette = list(data[at + 4:at + 4 + count])
            if max(palette) >= nb:
                raise ValueError('MOD bone palette references absent joint')
            self.palettes.append(palette)
        self.texture_names = []
        for i in range(nt):
            raw = data[mats + i * 64:mats + (i + 1) * 64]
            if b'\0' not in raw:
                raise ValueError('unterminated MOD texture name')
            try:
                name = raw.split(b'\0', 1)[0].decode('ascii')
            except UnicodeDecodeError as exc:
                raise ValueError('non-ASCII MOD texture name') from exc
            if not name or any(ord(c) < 32 for c in name):
                raise ValueError('invalid MOD texture name')
            self.texture_names.append(name)
        self.materials = []
        for i in range(nmat):
            at = mats + nt * 64 + i * 160
            word, shader = struct.unpack_from('>2I', data, at)
            base = struct.unpack_from('>I', data, at + 24)[0]
            vertex_type = (word >> 2) & 7
            if vertex_type not in (0, 1) or (shader >> 28) != (4 if vertex_type else 3):
                raise ValueError('unsupported MOD material vertex/shader declaration')
            if not 0 <= base <= nt:
                raise ValueError('MOD material texture index outside table')
            self.materials.append(dict(vertex_type=vertex_type, texture=base - 1,
                                        native_flags=f'{word:08x}', native_shader=f'{shader:08x}',
                                        native_blend_state=data[at + 144:at + 148].hex(),
                                        native_alpha_bytes=data[at + 148:at + 152].hex()))
        self.meshes = []
        all_index_spans = []
        total_vertices = 0
        total_indices = 0
        for i in range(nm):
            at = meshes + i * 52
            group, material = struct.unpack_from('>HH', data, at)
            visible, lod, alpha, max_weights, stride, stride2 = data[at + 4:at + 10]
            count, maximum = struct.unpack_from('>HH', data, at + 12)
            total_vertices += count
            if total_vertices > nv:
                raise ValueError('MOD mesh vertex counts exceed header budget')
            start, off, off2, first, ni, base = struct.unpack_from('>6I', data, at + 16)
            total_indices += ni
            if total_indices > self.header['index_count']:
                raise ValueError('MOD mesh index counts exceed header budget')
            minimum = struct.unpack_from('>H', data, at + 42)[0]
            # Packed 32-bit skinInfo is byte-reversed on PS3, unlike the PC
            # declaration's separate byte fields.
            palette = data[at + 46]
            if material >= nmat or group >= ng or palette >= npal or not count or visible not in (0, 1):
                raise ValueError('MOD mesh references absent material/group/palette')
            if stride != 32 or stride2 not in (0, 4, 8) or minimum != start or base != 0 or maximum - minimum + 1 != count:
                raise ValueError('unsupported MOD mesh vertex range or stride')
            if first + ni > self.header['index_count']:
                raise ValueError('MOD mesh indices outside index section')
            if off + (minimum + count) * stride > size_v:
                raise ValueError('MOD mesh vertices outside vertex section')
            if stride2:
                if off2 + (start + count) * stride2 > size_v2:
                    raise ValueError('MOD secondary vertices outside vertex section')
            idx = np.frombuffer(data, dtype='>u2', count=ni, offset=indices + first * 2).astype(np.uint32)
            valid = idx != 65535
            if np.any(idx[valid] < minimum) or np.any(idx[valid] > maximum):
                raise ValueError('MOD strip index outside mesh vertices')
            idx[valid] -= minimum
            raw = np.frombuffer(data, dtype=np.uint8, count=count * stride, offset=vertices + off + minimum * stride).reshape(count, stride)
            packed = np.frombuffer(raw.tobytes(), dtype='>i2').reshape(count, 16)[:, :3].astype(float)
            pos = packed / 32767 * (self.bbox_max - self.bbox_min) + self.bbox_min
            influences = 8 if self.materials[material]['vertex_type'] else 4
            if not 1 <= max_weights <= influences:
                raise ValueError('MOD mesh weight count exceeds vertex declaration')
            joints = raw[:, 8:8 + influences].astype(np.uint16)
            weights = raw[:, 8 + influences:8 + 2 * influences].astype(float)
            sums = weights.sum(axis=1)
            if np.any(sums < 253) or np.any(sums > 257):
                raise ValueError('MOD vertex weights do not sum near 255')
            weights /= sums[:, None]
            for row in range(count):
                for col in range(influences):
                    if not weights[row, col]:
                        joints[row, col] = 0
                        continue
                    j = int(joints[row, col])
                    j = self.palettes[palette][j] if j < len(self.palettes[palette]) else self.bone_map[j]
                    if j >= nb:
                        raise ValueError('MOD vertex references absent joint')
                    joints[row, col] = j
            normal_at = 24 if influences == 8 else 16
            normal = raw[:, normal_at:normal_at + 3].astype(float) / 127.5 - 1
            normal /= np.linalg.norm(normal, axis=1)[:, None]
            uv_at = 28 if influences == 8 else 24
            uv = np.frombuffer(raw[:, uv_at:uv_at + 4].copy().tobytes(), dtype='>f2').reshape(count, 2).astype(float)
            finite(pos, 'MOD positions'); finite(normal, 'MOD normals'); finite(uv, 'MOD UVs')
            self.meshes.append(dict(index=i, group=group, material=material, visible=bool(visible),
                                    lod=lod, alpha_priority=alpha, palette=palette, positions=pos,
                                    normals=normal, uv=uv, joints=joints, weights=weights,
                                    triangles=triangles(idx), index_start=first, index_count=ni))
            if ni:
                all_index_spans.append((first, first + ni))
        all_index_spans.sort()
        if any(a[1] > b[0] for a, b in zip(all_index_spans, all_index_spans[1:])):
            raise ValueError('overlapping MOD mesh index spans')
        if total_vertices != nv:
            raise ValueError('MOD mesh vertex count does not match header')


def export_glb(model, textures, path, *, name='re5ps3', lod=1, scale=.01):
    """One explicit native LOD mask, with all its visible material primitives."""
    if lod not in (1, 2, 4) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('invalid LOD mask or positive scale')
    selected = [m for m in model.meshes if m['visible'] and m['lod'] & lod and len(m['triangles'])]
    if not selected:
        raise ValueError('selected MOD LOD has no visible triangles')
    blob, views, accessors = bytearray(), [], []
    def view(data):
        blob.extend(bytes(-len(blob) % 4))
        views.append(dict(buffer=0, byteOffset=len(blob), byteLength=len(data)))
        blob.extend(data)
        return len(views) - 1
    def acc(values, dtype, component, kind, extrema=False):
        with np.errstate(over='ignore', invalid='ignore'):
            a = np.asarray(values, dtype=dtype)
        finite(a, 'GLB ' + kind + ' accessor')
        r = dict(bufferView=view(a.tobytes()), componentType=component, count=len(a), type=kind)
        if extrema:
            r.update(min=a.min(axis=0).tolist(), max=a.max(axis=0).tolist())
        accessors.append(r)
        return len(accessors) - 1
    images, gltextures, materials, texture_cache, material_map = [], [], [], {}, {}
    texture_evidence = []
    texture_pixels = 0
    for native in sorted({m['material'] for m in selected}):
        mat = model.materials[native]
        record = dict(name=f'material_{native:03d}', pbrMetallicRoughness=dict(metallicFactor=0, roughnessFactor=1),
                      doubleSided=False, extras=dict(native_material=native, **mat))
        texidx = mat['texture']
        if texidx >= 0:
            texname = model.texture_names[texidx]
            if texname not in textures:
                raise ValueError('missing exact referenced texture: ' + texname)
            if texname not in texture_cache:
                tex = Texture(textures[texname])
                texture_pixels += tex.width * tex.height
                if texture_pixels > MAX_TOTAL_TEXTURE_PIXELS:
                    raise ValueError('selected textures exceed decoded pixel budget')
                png = io.BytesIO(); tex.image().save(png, format='PNG')
                images.append(dict(bufferView=view(png.getvalue()), mimeType='image/png', name=texname))
                gltextures.append(dict(source=len(images) - 1, sampler=0))
                texture_cache[texname] = len(gltextures) - 1
                texture_evidence.append(dict(name=texname, sha256=sha(tex.data), width=tex.width, height=tex.height,
                                             format=tex.format, color_correction=tex.color_correction))
            record['pbrMetallicRoughness']['baseColorTexture'] = dict(index=texture_cache[texname])
            record['alphaMode'] = 'MASK'
            record['alphaCutoff'] = .5
        material_map[native] = len(materials)
        materials.append(record)
    primitives = []
    for m in selected:
        with np.errstate(over='ignore', invalid='ignore'):
            positions = m['positions'] * scale
        finite(positions, 'GLB scaled positions')
        attrs = dict(POSITION=acc(positions, '<f4', 5126, 'VEC3', True),
                     NORMAL=acc(m['normals'], '<f4', 5126, 'VEC3'),
                     TEXCOORD_0=acc(m['uv'], '<f4', 5126, 'VEC2'))
        for slot in range(m['joints'].shape[1] // 4):
            attrs[f'JOINTS_{slot}'] = acc(m['joints'][:, slot * 4:slot * 4 + 4], '<u2', 5123, 'VEC4')
            attrs[f'WEIGHTS_{slot}'] = acc(m['weights'][:, slot * 4:slot * 4 + 4], '<f4', 5126, 'VEC4')
        primitives.append(dict(attributes=attrs, indices=acc(m['triangles'].reshape(-1), '<u4', 5125, 'SCALAR'),
                               material=material_map[m['material']], mode=4,
                               extras={k: m[k] for k in ('index', 'group', 'lod', 'palette', 'alpha_priority')}))
    nodes = [dict(name=name, children=[1]), dict(name=name + '_mesh', mesh=0, skin=0)]
    for i, parent in enumerate(model.parents):
        local = model.local[i].copy()
        with np.errstate(over='ignore', invalid='ignore'):
            local[:3, 3] *= scale
            local_float32 = local.astype('<f4')
        finite(local, 'GLB scaled node matrix')
        finite(local_float32, 'GLB node matrix float32 conversion')
        node = dict(name=f'j{i:03d}', matrix=local.T.reshape(-1).tolist(), extras=dict(native_anim_map=model.anim_map[i]))
        children = [j + 2 for j, p in enumerate(model.parents) if p == i]
        if children:
            node['children'] = children
        nodes.append(node)
    roots = [i + 2 for i, p in enumerate(model.parents) if p == 255]
    nodes[0]['children'].extend(roots)
    inverse = model.inverse_bind.copy()
    with np.errstate(over='ignore', invalid='ignore'):
        inverse[:, :3, 3] *= scale
    finite(inverse, 'GLB scaled inverse bind matrices')
    skin = dict(joints=list(range(2, len(nodes))), inverseBindMatrices=acc(inverse.transpose(0, 2, 1).reshape(-1, 16), '<f4', 5126, 'MAT4'))
    if len(roots) == 1:
        skin['skeleton'] = roots[0]
    receipt = dict(reader_version=READER_VERSION, source_sha256=sha(model.data), bones=len(model.parents),
                   primitives=len(selected), native_meshes=len(model.meshes), lod_mask=lod,
                   triangles=sum(len(m['triangles']) for m in selected),
                   vertices=sum(len(m['positions']) for m in selected), textures=texture_evidence,
                   bind_matrix_max_error=model.bind_error, gameplay_verified=False,
                   limitations=['Bind pose only; native animation clips are not exported.',
                                'Diffuse textures and native normals only; engine shader passes, normal/mask maps and texture color correction are not reproduced.',
                                'Alpha uses a 0.5 preview cutoff; native blend states are retained as source evidence, not emulated.',
                                'No cast replacement, unlock, equipment editing or native game writer is provided by this reader.'])
    doc = dict(asset=dict(version='2.0', generator='gBox re5ps3_models'), scene=0, scenes=[dict(nodes=[0])],
               nodes=nodes, skins=[skin], meshes=[dict(primitives=primitives)], materials=materials,
               images=images, textures=gltextures, samplers=[dict(magFilter=9729, minFilter=9729, wrapS=10497, wrapT=10497)],
               bufferViews=views, accessors=accessors, buffers=[dict(byteLength=len(blob))], extras=receipt)
    raw = json.dumps(doc, separators=(',', ':'), allow_nan=False).encode(); raw += b' ' * (-len(raw) % 4)
    blob.extend(bytes(-len(blob) % 4))
    result = struct.pack('<3I', 0x46546c67, 2, 28 + len(raw) + len(blob))
    result += struct.pack('<2I', len(raw), 0x4e4f534a) + raw + struct.pack('<2I', len(blob), 0x004e4942) + blob
    with Path(path).open('xb') as file:
        file.write(result)
    if Path(path).read_bytes() != result:
        raise OSError('GLB readback mismatch')
    return dict(receipt, path=str(path), sha256=sha(result))


def export_archive(archive, model_name, output, *, lod=1):
    """Exact resource names from one ARC; no filesystem member extraction."""
    candidates = [e for e in archive.entries if e.name == model_name]
    models = [(e, archive.read(e)) for e in candidates]
    models = [(e, data) for e, data in models if data[:4] == b'\0DOM']
    if len(models) != 1:
        raise ValueError('expected one exact native model resource')
    model = Model(models[0][1])
    textures = {}
    needed = set(model.texture_names)
    for entry in archive.entries:
        if entry.name in needed:
            data = archive.read(entry)
            if data[:4] == b'\0XET':
                if entry.name in textures:
                    raise ValueError('ambiguous exact texture resource')
                textures[entry.name] = data
    return dict(export_glb(model, textures, output, name=model_name.rsplit('\\', 1)[-1], lod=lod),
                archive_sha256=sha(archive.data), model_member=model_name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--model', required=True, help='Exact native MOD resource name, without an extension')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lod', type=int, choices=(1, 2, 4), default=1)
    args = parser.parse_args()
    if args.archive.stat().st_size > MAX_ARCHIVE:
        parser.error('archive exceeds supported size')
    print(json.dumps(export_archive(Arc(args.archive.read_bytes()), args.model, args.out, lod=args.lod)))


if __name__ == '__main__':
    main()
