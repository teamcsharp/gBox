"""Read-only Switch RE5 LMT67 motion comparison, in native centimetres/Y-up.

Independent implementation of measured x64 LMT67 and MOD211 layouts. Format
references: https://github.com/PredatorCZ/RevilLib/tree/master/src/mtf_lmt and
https://github.com/tge-was-taken/umvc3-tools/tree/main/src/python/mtio/modules/mtlib
(codec bit layouts and shader attribute layouts respectively). No code from
those projects is included or required at runtime.
RE IK limitations are documented by the original format author at
https://lukascone.wordpress.com/2017/06/18/mt-framework-tools/ .

This samples actual buffered FK tracks and all vertex influences. It does not
simulate the game's IK, physics, animation layers, or procedural constraints.
Unknown codecs/vertex layouts fail closed; unmapped auxiliary tracks are listed.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import math
import struct
import zlib

from . import mt_arc, mt_model, mtf_author


class MotionError(ValueError):
    """The requested motion cannot be represented faithfully by this reader."""


_SIZES = {1: 12, 2: 12, 3: 16, 4: 8, 5: 4, 6: 8, 7: 4,
          11: 4, 12: 4, 13: 4, 14: 6, 15: 5}
_QUATERNIONS = {2, 6, 7, 11, 12, 13, 14, 15}
_MAX_BYTES = 128 * 1024 * 1024


def _range(data, offset, size, what):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise MotionError(f"{what} runs outside its container")


def _finite(values, what):
    if not all(math.isfinite(v) for v in values):
        raise MotionError(f"{what} contains a non-finite value")


def _unit(q):
    _finite(q, 'quaternion')
    norm = math.sqrt(sum(v*v for v in q))
    if norm < 1e-8:
        raise MotionError('zero quaternion')
    return tuple(v/norm for v in q)


def _interpolate(a, b, t, rotation):
    if not rotation:
        return tuple(x + (y-x)*t for x, y in zip(a, b))
    a, b = _unit(a), _unit(b)
    dot = sum(x*y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-v for v in b), -dot
    if dot > .9995:
        return _unit(tuple(x + (y-x)*t for x, y in zip(a, b)))
    angle = math.acos(min(1., dot))
    sa, sb = math.sin((1-t)*angle)/math.sin(angle), math.sin(t*angle)/math.sin(angle)
    return tuple(sa*x + sb*y for x, y in zip(a, b))


def _decode_key(codec, raw, bounds):
    """One key's value and duration; packed fields are little endian."""
    if codec in (1, 2, 3):
        xyz = struct.unpack_from('<3f', raw)
        if codec == 2:
            value = (*xyz, math.sqrt(max(0., 1.-sum(v*v for v in xyz))))
        else:
            value = (*xyz, 1.)
        delta = struct.unpack_from('<I', raw, 12)[0] if codec == 3 else 1
    elif codec in (4, 5):
        fields = struct.unpack('<4H' if codec == 4 else '<4B', raw)
        value = (*(v/(65535. if codec == 4 else 255.) for v in fields[:3]), 1.)
        delta = fields[3]
    else:
        packed = int.from_bytes(raw, 'little')
        if codec == 6:
            fields = [(packed >> shift) & 16383 for shift in (42, 28, 14, 0)]
            value = tuple((v if v <= 8191.5 else v-16383)*4/16383 for v in fields)
            delta = packed >> 56
        elif codec == 7:
            value = tuple(((packed >> shift) & 127)/127 for shift in (21, 14, 7, 0))
            delta = packed >> 28
        elif codec in (11, 12, 13):
            fields = [0., 0., 0., ((packed >> 14) & 16383)/16383]
            fields[codec-11] = (packed & 16383)/16383
            value, delta = tuple(fields), packed >> 28
        elif codec == 14:
            # 11-bit lanes are rotated within their 16-bit storage boundaries.
            words = struct.unpack('<3H', raw)
            fields = (packed & 2047,
                      (((packed >> 11) << 6) | (words[1] & 63)) & 2047,
                      (((packed >> 22) << 1) | (words[2] & 1)) & 2047,
                      (packed >> 33) & 2047)
            value, delta = tuple(v/2047 for v in fields), packed >> 44
        elif codec == 15:
            # Each 9-bit component wraps at its following byte boundary.
            fields = [(((packed >> (9*i)) << (i+1)) | (raw[i+1] & ((1 << (i+1))-1))) & 511
                      for i in range(4)]
            value, delta = tuple(v/511 for v in fields), packed >> 36
        else:
            raise MotionError(f'unsupported LMT codec {codec}')
    if bounds is not None:
        value = tuple(bounds[i+4] + bounds[i]*v for i, v in enumerate(value))
    _finite(value, 'motion key')
    return value, delta


@dataclass(frozen=True)
class Track:
    codec: int
    usage: int
    joint_type: int
    anim_id: int
    reference: tuple
    times: tuple
    values: tuple

    def sample(self, frame, loop_frame):
        if not self.values or (loop_frame < 1 and frame == 0):
            return self.reference
        if loop_frame < 1:
            frame -= 1
        if frame < 0:
            # Native reference-to-buffer interpolation is linear, even for quaternions.
            return _interpolate(self.reference, self.values[0], frame+1, False)
        index = bisect_right(self.times, frame)-1
        if index >= len(self.values)-1:
            return self.values[-1]
        t = (frame-self.times[index])/(self.times[index+1]-self.times[index])
        return _interpolate(self.values[index], self.values[index+1], t, self.usage in (0, 3))


def _offsets(data):
    if len(data) > _MAX_BYTES or len(data) < 8 or data[:4] != b'LMT\0':
        raise MotionError('expected a bounded LMT container')
    version, count = struct.unpack_from('<HH', data, 4)
    if version != 67:
        raise MotionError(f'unsupported LMT version {version}; expected Switch version 67')
    _range(data, 8, count*8, 'animation offset table')
    return struct.unpack_from('<'+'Q'*count, data, 8)


def _clip(data, offset):
    _range(data, offset, 20, 'clip header')
    start, count, frames, loop = struct.unpack_from('<QIIi', data, offset)
    if not 1 <= frames <= 1000000 or not 1 <= count <= 4096:
        raise MotionError('invalid clip frame/track count')
    _range(data, start, count*48, 'track table')
    tracks, decoded_keys = [], 0
    for i in range(count):
        codec, usage, joint, bone, weight, size, ptr, *tail = struct.unpack_from('<4BfQQ4fQ', data, start+i*48)
        reference, bounds_ptr = tuple(tail[:4]), tail[4]
        if codec not in _SIZES:
            raise MotionError(f'track {i}: unsupported LMT codec {codec}')
        if usage not in range(5) or (usage in (0, 3)) != (codec in _QUATERNIONS):
            raise MotionError(f'track {i}: unsupported codec/usage {codec}/{usage}')
        if not math.isfinite(weight) or abs(weight-1.) > 1e-5:
            raise MotionError(f'track {i}: unsupported blend weight {weight}')
        _finite(reference, 'reference pose')
        if usage in (0, 3):
            _unit(reference)
        bounds = None
        if bounds_ptr:
            _range(data, bounds_ptr, 32, 'track quantization bounds')
            bounds = struct.unpack_from('<8f', data, bounds_ptr)
            _finite(bounds, 'track quantization bounds')
        if size and not ptr:
            raise MotionError('nonempty motion buffer has a null pointer')
        _range(data, ptr, size, 'motion buffer')
        stride = _SIZES[codec]
        if size % stride:
            raise MotionError(f'track {i}: buffer size is not a multiple of codec stride')
        decoded_keys += size//stride
        if decoded_keys > 1000000:
            raise MotionError('clip exceeds the decoded key limit')
        times, values, time = [], [], 0
        for p in range(ptr, ptr+size, stride):
            value, delta = _decode_key(codec, data[p:p+stride], bounds)
            if usage in (0, 3):
                _unit(value)
            times.append(time)
            values.append(value)
            if delta <= 0 and p+stride < ptr+size:
                raise MotionError(f'track {i}: non-increasing key times')
            time += delta
        tracks.append(Track(codec, usage, joint, bone, reference, tuple(times), tuple(values)))
    return frames, loop, tracks


def _engine_ik(tracks):
    # Measured RE5 leg chains: joint type 0x2a on thighs, local-labelled
    # ID19/23 toe positions are solver goals, not ordinary FK local offsets.
    # The original format author documents manual IK reconstruction for RE.
    return any((t.joint_type != 0 and t.anim_id not in (254, 255))
               or (t.anim_id in (19, 23) and t.usage == 1) for t in tracks)


def list_clips(lmt_bytes):
    """Catalog nonempty clips with original (possibly sparse) native indices."""
    data = bytes(lmt_bytes)
    result = []
    for index, offset in enumerate(_offsets(data)):
        if not offset:
            continue
        row = {'index': index, 'frame_count': 0, 'supported': False, 'raw_fk_supported': False,
               'engine_ik': False}
        try:
            _range(data, offset, 20, 'clip header')
            row['frame_count'] = struct.unpack_from('<I', data, offset+12)[0]
            count, loop, tracks = _clip(data, offset)
            needs_ik = _engine_ik(tracks)
            row.update(frame_count=count, loop_frame=loop, supported=not needs_ik,
                       raw_fk_supported=True, engine_ik=needs_ik, track_count=len(tracks),
                       buffered_tracks=sum(bool(t.values) for t in tracks))
            if needs_ik:
                row['reason'] = 'Engine IK is required; opt into raw FK diagnostics to inspect arms/root, not a complete game pose.'
        except MotionError as exc:
            row['reason'] = str(exc)
        result.append(row)
    return result


def _inflate(data):
    if data[:4] in (b'MOD\0', b'LMT\0'):
        return data
    for window in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            decoder = zlib.decompressobj(window)
            out = decoder.decompress(data, _MAX_BYTES+1)
            if len(out) > _MAX_BYTES or decoder.unconsumed_tail or not decoder.eof:
                raise MotionError('compressed entry exceeds the comparison limit or is incomplete')
            return out
        except zlib.error:
            continue
    raise MotionError('entry is neither a native model nor supported zlib data')


def _model(data, name):
    data = bytes(data)
    if len(data) > _MAX_BYTES:
        raise MotionError('model container exceeds the comparison limit')
    if data[:4] == b'MOD\0':
        raw = data
    else:
        archive = mt_arc.parse(data)
        matches = []
        for entry in archive.entries:
            if entry.name.replace('\\', '/').rsplit('/', 1)[-1] == name:
                decoded = _inflate(entry.data)
                if decoded[:4] == b'MOD\0':
                    matches.append(decoded)
        if len(matches) != 1:
            raise MotionError(f'expected exactly one MOD named {name!r}, found {len(matches)}')
        raw = matches[0]
    model = mt_model.parse_mod(raw)
    if model.variant != 'model' or model.header()['version'] != 211:
        raise MotionError('comparison requires a Switch MOD211 model')
    return model


def _influences(raw, record, bone_count):
    """Decode shader skin attributes, including residual and eight-way weights."""
    rows = []
    kind, stride = record['vertex_format'], record['vertex_stride']
    for offset in range(0, len(raw), stride):
        if kind in (0x133098B0, 0x18B0FAA8):
            bones, weights = struct.unpack_from('<H', raw, offset+6), [1.]
        elif kind in (0x14A07DDB, 0x1C201FC3):
            bones = struct.unpack_from('<2h' if kind == 0x14A07DDB else '<2e', raw,
                                       offset+(12 if kind == 0x14A07DDB else 20))
            weight = struct.unpack_from('<h', raw, offset+6)[0]/32767
            weights = [weight, 1-weight]
        elif kind in (0x1580B60C, 0x16C020A3):
            count = 4 if kind == 0x1580B60C else 8
            bones = raw[offset+8:offset+8+count]
            weights = [v/255 for v in raw[offset+8+count:offset+8+2*count]]
        elif kind in (0x2000D414, 0x244042BB):
            count = 4 if kind == 0x2000D414 else 8
            bones = raw[offset+16:offset+16+count]
            weights = [struct.unpack_from('<h', raw, offset+6)[0]/32767]
            if count == 8:
                weights += [v/255 for v in raw[offset+12:offset+16]]
            weights += list(struct.unpack_from('<2e', raw, offset+(24 if count == 4 else 28)))
            weights += [1-sum(weights)]
        else:
            raise MotionError(f'unsupported native skin vertex layout 0x{kind:08x}')
        _finite((*bones, *weights), 'skin attributes')
        if any(w < -.002 for w in weights) or abs(sum(weights)-1) > .025:
            raise MotionError(f'invalid skin weights in layout 0x{kind:08x}')
        # Only the tiny native byte/half quantization error is normalized.
        weights = [max(0., w) for w in weights]
        total = sum(weights)
        active = []
        for bone, weight in zip(bones, weights):
            if weight:
                if int(bone) != bone or not 0 <= bone < bone_count:
                    raise MotionError('positive skin weight addresses an invalid bone')
                active.append((int(bone), weight/total))
        if not active:
            raise MotionError('vertex has no positive skin weight')
        rows.append(active)
    return rows


def _rotation(q):
    import numpy as np
    x, y, z, w = _unit(q)
    return np.array(((1-2*(y*y+z*z), 2*(x*y+z*w), 2*(x*z-y*w)),
                     (2*(x*y-z*w), 1-2*(x*x+z*z), 2*(y*z+x*w)),
                     (2*(x*z+y*w), 2*(y*z-x*w), 1-2*(x*x+y*y))))


def _rig(model):
    import numpy as np
    table = model.bone_table()
    if not table.get('consistent') or not 1 <= table['bone_count'] <= 255:
        raise MotionError('missing or unsupported native skeleton')
    local = np.array([struct.unpack('<16f', x) for x in table['local']]).reshape(-1, 4, 4)
    inverse = np.array([struct.unpack('<16f', x) for x in table['inverse_bind']]).reshape(-1, 4, 4)
    if not np.isfinite(local).all() or not np.isfinite(inverse).all():
        raise MotionError('non-finite skeleton matrix')
    parents = table['parents']
    visiting, visited = set(), set()
    def visit(bone):
        if bone in visiting:
            raise MotionError('cycle in skeleton parents')
        if bone in visited:
            return
        visiting.add(bone)
        parent = parents[bone]
        if parent != 255:
            if not 0 <= parent < len(parents):
                raise MotionError('invalid skeleton parent')
            visit(parent)
        visiting.remove(bone)
        visited.add(bone)
    for bone in range(len(parents)):
        visit(bone)
    lookup = {}
    for bone, aid in enumerate(table['anim_map']):
        if aid != 255:
            if aid in lookup:
                raise MotionError(f'duplicate native animation bone ID {aid}')
            lookup[aid] = bone
    return table, local, inverse, lookup


def _world(rig, tracks, frame, loop):
    import numpy as np
    table, bind, _, lookup = rig
    local = bind.copy()
    rotations, positions, scales = {}, {}, {}
    absolute_rotation, absolute_position = {}, {}
    virtual = np.eye(4)
    seen = set()
    for track in tracks:
        if track.anim_id != 255 and track.anim_id not in lookup:
            continue
        key = (track.anim_id, track.usage)
        if key in seen:
            raise MotionError(f'ambiguous tracks for animation bone/usage {key}')
        seen.add(key)
        value = track.sample(frame, loop)
        if track.anim_id == 255:
            if track.usage in (0, 3):
                virtual[:3, :3] = _rotation(value)
            elif track.usage in (1, 4):
                virtual[3, :3] = value[:3]
            else:
                raise MotionError('unsupported virtual root scale track')
            continue
        bone = lookup[track.anim_id]
        (rotations, positions, scales, absolute_rotation, absolute_position)[track.usage][bone] = value
    for bone in range(len(local)):
        scale = np.linalg.norm(bind[bone, :3, :3], axis=1)
        if (scale < 1e-10).any():
            raise MotionError('singular bind scale')
        orientation = rotations.get(bone)
        rotation = _rotation(orientation) if orientation is not None else bind[bone, :3, :3]/scale[:, None]
        if bone in scales:
            scale = np.asarray(scales[bone][:3])
        local[bone, :3, :3] = scale[:, None]*rotation
        if bone in positions:
            local[bone, 3, :3] = positions[bone][:3]
    world = {}
    def compose(bone):
        if bone not in world:
            parent = table['parents'][bone]
            value = local[bone] @ (virtual if parent == 255 else compose(parent))
            if bone in absolute_rotation:
                scale = np.linalg.norm(value[:3, :3], axis=1)
                value[:3, :3] = scale[:, None]*_rotation(absolute_rotation[bone])
            if bone in absolute_position:
                value[3, :3] = absolute_position[bone][:3]
            world[bone] = value
        return world[bone]
    return np.array([compose(i) for i in range(len(local))])


def _geometry(model, rig):
    import numpy as np
    points, triangles, influences, selected = [], [], [], []
    for index, record in enumerate(model.meshes()):
        if not record['level_of_detail'] & 1:
            continue
        raw, record = model.mesh_bytes(index)
        if not record['vertex_count']:
            continue
        part = model.positions(index)
        weights = _influences(raw, record, rig[0]['bone_count'])
        if len(part) != record['vertex_count'] or len(weights) != len(part):
            raise MotionError('incomplete vertex decoding')
        faces = mtf_author.mesh_triangles(model, index)
        base, shift = len(points), record['vertex_index']
        for tri in faces:
            if any(not 0 <= i-shift < len(part) for i in tri):
                raise MotionError('triangle addresses a vertex outside its mesh')
            triangles.append([i-shift+base for i in tri])
        points.extend(part)
        influences.extend(weights)
        selected.append(index)
    if not points or not triangles or len(points) > 200000:
        raise MotionError('empty or excessive full-detail geometry')
    points = np.asarray(points)
    transform = model.position_transform()
    if transform is None:
        raise MotionError('model has no valid native position transform')
    try:
        compressed = np.column_stack((points, np.ones(len(points)))) @ np.linalg.inv(np.asarray(transform).reshape(4, 4))
    except np.linalg.LinAlgError as exc:
        raise MotionError('singular position transform') from exc
    ids = np.zeros((len(points), 8), dtype=int)
    weights = np.zeros((len(points), 8))
    for vertex, row in enumerate(influences):
        for slot, (bone, weight) in enumerate(row):
            ids[vertex, slot], weights[vertex, slot] = bone, weight
    return points, compressed, ids, weights, triangles, selected


def _sample_model(model, tracks, frames, loop):
    import numpy as np
    rig = _rig(model)
    points, compressed, ids, weights, triangles, selected = _geometry(model, rig)
    if len(points)*len(frames)*3 > 4000000:
        raise MotionError('too many exported vertex coordinates; request fewer frames')
    output = []
    for frame in frames:
        world = _world(rig, tracks, frame, loop)
        matrices = rig[2] @ world
        posed = np.zeros((len(points), 3))
        for slot in range(8):
            if not weights[:, slot].any():
                continue
            values = np.einsum('vi,vij->vj', compressed, matrices[ids[:, slot]])[:, :3]
            posed += values*weights[:, slot, None]
        if not np.isfinite(posed).all() or not np.isfinite(world).all():
            raise MotionError('non-finite sampled pose')
        output.append({'frame': frame, 'positions': posed.round(5).ravel().tolist(),
                       'bounds': {'min': posed.min(axis=0).tolist(), 'max': posed.max(axis=0).tolist()},
                       'skeleton': {'bones': world[:, 3, :3].round(5).tolist(),
                                    'parents': rig[0]['parents'], 'anim_ids': rig[0]['anim_map'],
                                    'world_matrices': world.round(6).reshape(-1, 16).tolist()}})
    missing = [{'anim_id': t.anim_id, 'usage': t.usage, 'joint_type': t.joint_type}
               for t in tracks if t.anim_id not in rig[3] and t.anim_id != 255]
    return {'model_sha256': hashlib.sha256(model.raw).hexdigest(), 'vertex_count': len(points),
            'mesh_indices': selected, 'triangles': triangles, 'frames': output,
            'bind_bounds': {'min': points.min(axis=0).tolist(), 'max': points.max(axis=0).tolist()},
            'unmapped_tracks': missing}


def sample_compare(native_arc, candidate_arc, lmt_bytes=None, *, animation_index=None,
                   frames=None, model_name='pl0000', candidate_lmt=None, candidate_lmt_bytes=None,
                   raw_fk=False):
    """Sample the same clip/frame indices against native and candidate skeletons.

    Inputs are ARC or raw MOD bytes; no paths or mutations. ``None`` selects bind
    pose. A bounded frame list can include fractional frames for interpolation.
    Optional candidate LMT bytes allow bounded motion authoring to be inspected;
    the same clip index, duration, loop point and track identities are required.
    Known engine IK clips require explicit ``raw_fk=True`` diagnostic opt-in;
    their unprocessed toe goal tracks do not represent the engine's leg pose.
    """
    if candidate_lmt is not None and candidate_lmt_bytes is not None:
        raise MotionError('supply only one candidate LMT argument')
    candidate_lmt = candidate_lmt_bytes if candidate_lmt_bytes is not None else candidate_lmt
    native, candidate = _model(native_arc, model_name), _model(candidate_arc, model_name)
    tracks, candidate_tracks, loop, frame_count = [], [], 0, 1
    catalog = list_clips(lmt_bytes) if lmt_bytes is not None else []
    if animation_index is not None:
        if not isinstance(animation_index, int) or isinstance(animation_index, bool) or lmt_bytes is None:
            raise MotionError('animation_index requires an integer and native LMT bytes')
        offsets = _offsets(lmt_bytes)
        if not 0 <= animation_index < len(offsets) or not offsets[animation_index]:
            raise MotionError('selected animation index is absent')
        frame_count, loop, tracks = _clip(lmt_bytes, offsets[animation_index])
        candidate_tracks = tracks
        if candidate_lmt is not None:
            candidate_offsets = _offsets(candidate_lmt)
            if animation_index >= len(candidate_offsets) or not candidate_offsets[animation_index]:
                raise MotionError('candidate has no corresponding animation index')
            other_frames, other_loop, candidate_tracks = _clip(candidate_lmt, candidate_offsets[animation_index])
            identity = lambda rows: sorted((t.anim_id, t.usage, t.joint_type) for t in rows)
            if (other_frames, other_loop) != (frame_count, loop) or identity(candidate_tracks) != identity(tracks):
                raise MotionError('candidate clip duration, loop point, or track identities differ from native')
    engine_ik = _engine_ik(tracks) or _engine_ik(candidate_tracks)
    if engine_ik and raw_fk is not True:
        raise MotionError('Engine IK is required for this clip; raw_fk=True explicitly enables incomplete FK diagnostics')
    frames = [0] if frames is None else list(frames)
    if not 1 <= len(frames) <= 60:
        raise MotionError('request between 1 and 60 sample frames')
    if any(isinstance(f, bool) or not isinstance(f, (int, float)) or not math.isfinite(f)
           or not 0 <= f < frame_count for f in frames):
        raise MotionError('sample frame is outside the selected clip')
    mode = 'bind_pose' if animation_index is None else 'raw_fk_without_game_ik' if engine_ik else 'sampled_fk'
    result = {'schema': 1, 'fps': 30, 'units': 'cm', 'up_axis': 'y', 'evaluation_mode': mode,
              'clip': {'animation_index': animation_index, 'frame_count': frame_count, 'loop_frame': loop},
              'clips': catalog, 'frame_indices': frames,
              'native': _sample_model(native, tracks, frames, loop),
              'candidate': _sample_model(candidate, candidate_tracks, frames, loop),
              'motion_sha256': {'native': hashlib.sha256(lmt_bytes).hexdigest() if lmt_bytes is not None else None,
                                'candidate': hashlib.sha256(candidate_lmt if candidate_lmt is not None else lmt_bytes).hexdigest()
                                    if candidate_lmt is not None or lmt_bytes is not None else None}}
    result['diagnostics'] = {
        'unsupported_tracks': [],
        'engine_ik': engine_ik,
        'limitations': ['Raw FK and linear skinning only; game IK, procedural constraints, physics, and clip layers are not simulated.',
                        'All native meshes with LOD bit 1 are shown; runtime part visibility is not simulated.'],
        'unmapped_tracks': {side: result[side]['unmapped_tracks'] for side in ('native', 'candidate')},
        'joint_types': sorted(set(t.joint_type for t in tracks)),
        'buffered_tracks': sum(bool(t.values) for t in tracks)}
    displacements = []
    for n, c in zip(result['native']['frames'], result['candidate']['frames']):
        ns, cs = n['skeleton'], c['skeleton']
        lookup = {aid: p for aid, p in zip(ns['anim_ids'], ns['bones']) if aid != 255}
        joints = [{'anim_id': aid, 'distance_cm': math.dist(lookup[aid], p),
                   'delta': [b-a for a, b in zip(lookup[aid], p)]}
                  for aid, p in zip(cs['anim_ids'], cs['bones']) if aid in lookup]
        displacements.append({'frame': n['frame'], 'joints': joints})
    result['diagnostics']['joint_displacements'] = displacements
    return result
