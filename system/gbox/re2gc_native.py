"""Bounded RE2 GameCube PLD reader and native mesh editor.

Owned GHAE08 keeps little-endian PLD/MD1/EMR/TIM data. MD1 offsets are
relative to the end of its 12-byte header (not the section start).
Reference: OpenBiohazard2/fileio/{pld,md1,emr}.go; verified against the
owned GameCube files. This module does not claim a donor retargeter,
unlocks, live inventory addresses, or gameplay acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

GAME_ID = 'c6adbfa00c20aaf9'
DISC_ID = 'GHAE08'
DOL_SHA256 = '71401bd622ab5a09e40d5cd6feb07f3725d7a24356fb0cf133e3991c941e2a05'
MAX_MODEL = 8 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


def extent(data, offset, size, label):
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ValueError(f'{label} outside source extent')
    return data[offset:offset + size]


class Model:
    """Lossless native storage with fully bounded mesh/animation references.

    Mesh edits preserve skeleton, animation, texture, topology and unknown
    fields. Shared triangle/quad vertex arrays are edited once. Full donor
    conversion must provide a separate validated retargeter; this is its
    native read/write substrate.
    """
    def __init__(self, data):
        self.data = bytes(data)
        if not 24 <= len(data) <= MAX_MODEL:
            raise ValueError('PLD size outside supported bounds')
        directory, count = struct.unpack_from('<II', data)
        if count != 4:
            raise ValueError('expected four-section player PLD')
        extent(data, directory, 16, 'PLD directory')
        self.offsets = struct.unpack_from('<4I', data, directory)
        if self.offsets[0] < 8 or list(self.offsets) != sorted(set(self.offsets)) or self.offsets[-1] >= directory:
            raise ValueError('PLD sections overlap or lie outside payload')
        self.directory = directory
        ends = (*self.offsets[1:], directory)
        self.sections = {k: data[a:b] for k, a, b in zip(('edd', 'emr', 'md1', 'tim'), self.offsets, ends)}
        self._animation()
        self._texture()
        self._mesh()

    def _animation(self):
        edd, emr = self.sections['edd'], self.sections['emr']
        extent(edd, 0, 4, 'EDD header')
        first = struct.unpack_from('<H', edd, 2)[0]
        if first < 4 or first % 4:
            raise ValueError('invalid EDD table start')
        extent(edd, 0, first, 'EDD table')
        frames = []
        for at in range(0, first, 4):
            count, offset = struct.unpack_from('<HH', edd, at)
            if count and offset < first:
                raise ValueError('EDD frames overlap header')
            raw = extent(edd, offset, count * 4, 'EDD frames')
            frames.extend(v[0] & 0xfff for v in struct.iter_unpack('<I', raw))
        extent(emr, 0, 8, 'EMR header')
        arms, start, bones, stride = struct.unpack_from('<4H', emr)
        if not 1 <= bones <= 255 or stride < 12 + (bones * 36 + 7) // 8:
            raise ValueError('invalid EMR bone count/frame stride')
        extent(emr, 8, bones * 6, 'EMR joint offsets')
        extent(emr, arms, bones * 4, 'EMR armatures')
        if arms < 8 + bones * 6 or start < arms + bones * 4:
            raise ValueError('EMR tables overlap')
        children = []
        for i in range(bones):
            count, offset = struct.unpack_from('<HH', emr, arms + i * 4)
            raw = extent(emr, arms + offset, count, 'EMR children')
            if count and (arms + offset < arms + bones * 4 or arms + offset + count > start):
                raise ValueError('EMR child list overlaps other data')
            if any(c >= bones for c in raw):
                raise ValueError('EMR child index outside skeleton')
            children.append(list(raw))
        visiting, visited = set(), set()
        def visit(i):
            if i in visiting:
                raise ValueError('EMR skeleton cycle')
            if i in visited:
                return
            visiting.add(i)
            for child in children[i]:
                visit(child)
            visiting.remove(i); visited.add(i)
        for i in range(bones):
            visit(i)
        if frames:
            extent(emr, start, (max(frames) + 1) * stride, 'EMR animation frames')
        self.skeleton = {'bones': bones, 'children': children,
                         'positions': list(struct.iter_unpack('<3h', emr[8:8 + 6 * bones])),
                         'animations': first // 4, 'frame_stride': stride,
                         'referenced_frames': max(frames) + 1 if frames else 0}

    def _texture(self):
        tim = self.sections['tim']
        extent(tim, 0, 20, 'TIM header')
        magic, flags, clut_size, x, y, colors, palettes = struct.unpack_from('<3I4H', tim)
        if magic != 0x10 or flags not in (8, 9):
            raise ValueError('expected indexed TIM texture')
        if not colors or not palettes or clut_size != 12 + 2 * colors * palettes:
            raise ValueError('invalid TIM palette size')
        extent(tim, 8, clut_size, 'TIM palettes')
        image = 8 + clut_size
        extent(tim, image, 12, 'TIM image header')
        size, ix, iy, words, height = struct.unpack_from('<I4H', tim, image)
        if not words or not height or size != 12 + 2 * words * height:
            raise ValueError('invalid TIM pixel size')
        extent(tim, image, size, 'TIM pixels')
        self.texture = {'bpp': 4 if flags == 8 else 8, 'width': words * (4 if flags == 8 else 2),
                        'height': height, 'colors': colors, 'palettes': palettes,
                        'image_offset': image + 12, 'clut_x': x, 'clut_y': y,
                        'image_x': ix, 'image_y': iy}

    def _mesh(self):
        mesh = self.sections['md1']
        extent(mesh, 0, 12, 'MD1 header')
        size, unknown, count = struct.unpack_from('<3I', mesh)
        if count % 2 or not 2 <= count <= 510:
            raise ValueError('invalid MD1 object count')
        table_end = 12 + (count // 2) * 56
        extent(mesh, 0, table_end, 'MD1 objects')
        if not table_end <= size <= len(mesh):
            raise ValueError('invalid MD1 geometry length')
        self.objects = []
        for i in range(count // 2):
            groups = []
            for kind, corners, at in (('triangles', 3, 12 + i * 56), ('quads', 4, 40 + i * 56)):
                vo, vc, no, nc, io, ic, to = struct.unpack_from('<7I', mesh, at)
                arrays = []
                for off, n, stride, label in ((vo, vc, 8, 'vertices'), (no, nc, 8, 'normals'),
                                            (io, ic, corners * 4, 'indices'), (to, ic, corners * 4, 'UVs')):
                    begin = 12 + off
                    if n and begin < table_end:
                        raise ValueError('MD1 array overlaps object table')
                    arrays.append(extent(mesh, begin, n * stride, 'MD1 ' + label))
                vertices = list(struct.iter_unpack('<3hH', arrays[0]))
                normals = list(struct.iter_unpack('<3hH', arrays[1]))
                indices = list(struct.iter_unpack('<' + 'H' * (2 * corners), arrays[2]))
                for face in indices:
                    if any(face[j] >= nc or face[j + 1] >= vc for j in range(0, corners * 2, 2)):
                        raise ValueError('MD1 face index outside vertex/normal array')
                groups.append({'kind': kind, 'vertex_offset': 12 + vo, 'vertices': vertices,
                               'normal_offset': 12 + no, 'normals': normals, 'indices': indices,
                               'uv_bytes': arrays[3]})
            self.objects.append(groups)

    def summary(self):
        return {'sha256': sha(self.data), 'bytes': len(self.data), 'sections': dict(zip(self.sections, self.offsets)),
                'skeleton': self.skeleton, 'texture': self.texture, 'objects': len(self.objects),
                'triangles': sum(len(o[0]['indices']) for o in self.objects),
                'quads': sum(len(o[1]['indices']) for o in self.objects),
                'gameplay_verified': False}

    def build(self):
        """Byte-exact no-op, including alignment and unknown trailing data."""
        return self.data

    def edit_vertices(self, edits, *, expected_sha256):
        """Set explicit native vertex coordinates, retaining all unrelated bytes.

        edits: [{object, group: triangles|quads, vertex, xyz: [x,y,z]}].
        Reject conflicting edits to an aliased vertex array before publication.
        """
        if expected_sha256 != sha(self.data):
            raise ValueError('source hash does not match requested revision')
        writes = {}
        for edit in edits:
            obj, vertex = edit['object'], edit['vertex']
            if type(obj) is not int or not 0 <= obj < len(self.objects):
                raise ValueError('invalid object index')
            name = edit['group']
            if name not in ('triangles', 'quads'):
                raise ValueError('invalid primitive group')
            group = self.objects[obj][0 if name == 'triangles' else 1]
            if type(vertex) is not int or not 0 <= vertex < len(group['vertices']):
                raise ValueError('invalid vertex index')
            xyz = edit['xyz']
            if len(xyz) != 3 or any(type(v) is not int or not -32768 <= v <= 32767 for v in xyz):
                raise ValueError('coordinates must be signed 16-bit integers')
            at = self.offsets[2] + group['vertex_offset'] + vertex * 8
            for offset, value in enumerate(struct.pack('<3h', *xyz), at):
                if offset in writes and writes[offset] != value:
                    raise ValueError('conflicting edits to shared vertex data')
                writes[offset] = value
        out = bytearray(self.data)
        for offset, value in writes.items():
            out[offset] = value
        result = bytes(out)
        Model(result)
        return result

    def replace_mesh(self, objects, *, expected_sha256, texture=None):
        """Write complete per-part geometry while retaining the native rig/motions.

        Each object has triangles and quads in the same schema as ``objects``.
        Coordinates must already be retargeted into that part's local space.
        The original MD1/TIM allocations are hard budgets, not guessed loader
        limits. Unknown PLD sections and directory addresses remain untouched.
        """
        if expected_sha256 != sha(self.data):
            raise ValueError('source hash does not match requested revision')
        if len(objects) != len(self.objects):
            raise ValueError('replacement must preserve native object/rig slots')
        table_size = len(objects) * 56
        body = bytearray(table_size)
        textures = []
        def append(payload):
            off = len(body)
            body.extend(payload)
            return off
        def coords(rows):
            if len(rows) > 65535:
                raise ValueError('too many native vertices or normals')
            out = bytearray()
            for row in rows:
                if len(row) != 4 or any(type(v) is not int for v in row) or \
                        any(not -32768 <= v <= 32767 for v in row[:3]) or not 0 <= row[3] <= 65535:
                    raise ValueError('invalid native vertex/normal')
                out.extend(struct.pack('<3hH', *row))
            return bytes(out)
        # Reuse identical native arrays, including triangle/quad aliases.
        shared = {}
        def array(payload):
            if payload not in shared:
                shared[payload] = append(payload)
            return shared[payload]
        for i, groups in enumerate(objects):
            if len(groups) != 2:
                raise ValueError('each object needs triangle and quad groups')
            for g, corners in enumerate((3, 4)):
                group = groups[g]
                vertices, normals, faces = group['vertices'], group['normals'], group['indices']
                if len(faces) > 65535:
                    raise ValueError('too many native faces')
                vo, no = array(coords(vertices)), array(coords(normals))
                packed = bytearray()
                for face in faces:
                    if len(face) != corners * 2 or any(type(v) is not int for v in face) or any(
                            not 0 <= face[j] < len(normals) or not 0 <= face[j + 1] < len(vertices)
                            for j in range(0, corners * 2, 2)):
                        raise ValueError('replacement face index outside array')
                    packed.extend(struct.pack('<' + 'H' * (corners * 2), *face))
                io = append(packed)
                uv = bytes(group['uv_bytes'])
                if len(uv) != len(faces) * corners * 4:
                    raise ValueError('one UV record is required per face')
                at = i * 56 + g * 28
                struct.pack_into('<7I', body, at, vo, len(vertices), no, len(normals), io, len(faces), 0)
                textures.append((at + 24, uv))
        size = 12 + len(body)
        for at, uv in textures:
            struct.pack_into('<I', body, at, append(uv))
        original = self.sections['md1']
        mesh = struct.pack('<3I', size, struct.unpack_from('<I', original, 4)[0], len(objects) * 2) + body
        if len(mesh) > len(original):
            raise ValueError(f'replacement mesh exceeds native allocation ({len(mesh)} > {len(original)})')
        out = bytearray(self.data)
        out[self.offsets[2]:self.offsets[3]] = mesh + bytes(len(original) - len(mesh))
        if texture is not None:
            if len(texture) != len(self.sections['tim']):
                raise ValueError('replacement TIM must preserve native allocation')
            out[self.offsets[3]:self.directory] = texture
        result = bytes(out)
        checked = Model(result)
        if checked.texture != self.texture:
            raise ValueError('replacement TIM must preserve dimensions, format and VRAM mapping')
        return result


def inventory(path):
    from .gcdisc import GCDisc
    disc = GCDisc(path)
    try:
        if disc.game_id != DISC_ID or sha(disc.dol()) != DOL_SHA256:
            raise ValueError('not the validated RE2 GameCube GHAE08 executable revision')
        rows = []
        for name in sorted(disc.files):
            if name.lower().endswith('.pld'):
                model = Model(disc.read(name))
                rows.append({'path': name, **model.summary(), 'noop_identical': model.build() == disc.read(name)})
        return {'game_id': GAME_ID, 'disc_id': disc.game_id, 'dol_sha256': DOL_SHA256,
                'source': str(path), 'files': len(disc.files), 'player_models': rows,
                'scope': 'Native player container/mesh reader and bounded vertex writer only; donor retargeting, unlocks and live inventory pending.'}
    finally:
        disc.f.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--edit-json', type=Path, help='Explicit native vertex edits; source must be a PLD')
    p.add_argument('--expected-sha256', help='Required source identity for an edit')
    args = p.parse_args()
    if args.edit_json:
        if not args.expected_sha256:
            p.error('--edit-json requires --expected-sha256')
        model = Model(args.source.read_bytes())
        edits = json.loads(args.edit_json.read_text(encoding='utf-8'))
        changed = model.edit_vertices(edits, expected_sha256=args.expected_sha256)
        with args.out.open('xb') as f:
            f.write(changed)
        if args.out.read_bytes() != changed:
            raise OSError('native edit readback mismatch')
        print(json.dumps({'source_sha256': sha(model.data), 'output_sha256': sha(changed),
                          'output': str(args.out), 'readback_verified': True, 'gameplay_verified': False}))
        return
    result = inventory(args.source)
    with args.out.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    print(json.dumps({'manifest': str(args.out), 'player_models': len(result['player_models'])}))


if __name__ == '__main__':
    main()
