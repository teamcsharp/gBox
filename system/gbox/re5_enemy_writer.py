"""Unregistered, bounded group-aware enemy writer: SM64 DS Mario onto the RE5 Switch Majini (`uEm10.arc`, `em1000`).

The player writers replace a body that lives in option group 0. An enemy has no group 0: `em1000` is 341-347 mesh
records spread over 55 option groups (heads, arm skin, leg skin, shirts, pants, sandals) and the game selects groups
per spawn. This module replaces the Majini inside that structure instead of flattening it:

* the fitted donor surface comes from `re5_mesh_import.build_archive(pose_mode='native_segments')`, so every donor
  joint sits on its native bind joint and the native skeleton, inverse binds and motion are not touched (the RE6
  `bind_mode="keep"` lesson: native animations carry absolute locals, so bind joints must not move);
* `graft()` keeps the complete native mesh table. Every native record keeps its 56 bytes, its vertices and its
  envelope records; only its index words are collapsed so it draws nothing. One new record per option group carries the
  whole donor at every LOD, so whichever groups a spawn selects, the donor is drawn and no native part is;
* archive entries are replaced by explicit reviewed index, never by name (MOD and MRL share names here).

Nothing is installed, launched or registered. A structurally valid archive is not a working replacement: every
receipt says `live_verified: False` until a round has been watched.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import characters, mt_arc, mt_model, mtf_author, mtf_materials, mtf_mrl, mtf_secondary, mtf_tex, re5_mesh_import

ARCHIVE_PATH = 'nativeNXx64/ImgNX/Archive/uEm10.arc'
ARCHIVE_SHA256 = '1fa271890891ff31ac1aeb8d6dfc9a6d8bdcdd1ec252954b9d22a61519634a0c'
SOURCE_SLUG, SOURCE_MODEL = 'sm64ds_mario', 'sm64ds_mario.glb'
SOURCE_SHA256 = 'ea509bdf870190e72c3fe9046b916a3b83d3a8058af422ad6186b11332bf12bb'
RECIPE_VERSION = 1

#: Donor joints of the measured SM64 DS Mario GLB (its library role metadata). `face_1`, the neck, carries no vertex.
SOURCE_ROLES = {'hip': 'skl_root', 'chest': 'spin', 'head': 'head:root',
                'l_upper': 'arm_l1', 'l_fore': 'arm_l2', 'l_hand': 'wrist_l1',
                'r_upper': 'arm_r1', 'r_fore': 'arm_r2', 'r_hand': 'wrist_r1',
                'l_thigh': 'leg_l1', 'l_shin': 'leg_l2', 'l_foot': 'ankle_l1',
                'r_thigh': 'leg_r1', 'r_shin': 'leg_r2', 'r_foot': 'ankle_r1'}
#: RE5 animation ids (bone header byte 0) of the same roles. The Majini shares the player numbering, with one measured
#: difference in use: native Majini skin never weights root id 0, it hangs the hips off pelvis id 15.
ROLE_ANIMATION_IDS = {'hip': 15, 'chest': 2, 'head': 4, 'l_upper': 11, 'l_fore': 12, 'l_hand': 14,
                      'r_upper': 6, 'r_fore': 7, 'r_hand': 9, 'l_thigh': 20, 'l_shin': 21, 'l_foot': 22,
                      'r_thigh': 16, 'r_shin': 17, 'r_foot': 18}
SEGMENTS = {'l_upper': 'l_fore', 'l_fore': 'l_hand', 'r_upper': 'r_fore', 'r_fore': 'r_hand',
            'l_thigh': 'l_shin', 'l_shin': 'l_foot', 'r_thigh': 'r_shin', 'r_shin': 'r_foot'}

NORMAL_HASH, MASK_HASH = 0x22660, 0xED1B        # measured: all 70 em1000 materials bind _NM and _MM through these
DONOR_FORMAT, DONOR_STRIDE = 0x2000D414, 28      # the four-weight layout `mtf_author.build_one_mesh` writes
ALL_LODS = 0xFF
NATIVE_LOD_MASKS = (1, 2, 252)                   # measured on all six Majini models: near, middle, bits 2-7


class EnemyWriterError(ValueError):
    """The archive, skeleton or donor is not the measured input of this bounded recipe."""


@dataclass(frozen=True)
class EnemySet:
    """One reviewed enemy model family in one archive: explicit entry indices and its complete option-group list."""
    name: str
    models: tuple[tuple[str, int, int], ...]            # (exact entry name, MOD entry index, MRL entry index)
    groups: tuple[tuple[str, tuple[int, ...]], ...]      # (selection slot, option group ids)
    albedo: tuple[int, str]                              # the BC7 entry that receives the donor atlas
    normal: tuple[int, str]                              # that material's BC5 normal map
    mask: tuple[int, str]                                # that material's BC4 mask map

    def group_ids(self) -> list[int]:
        return [group for _, ids in self.groups for group in ids]

    def slot_of(self) -> dict[int, str]:
        return {group: slot for slot, ids in self.groups for group in ids}


_MODEL = 'pawn\\em\\em10\\model\\'
#: Reviewed 2026-11-09 against uEm10.arc `1fa27189...`. The option-group id's last digit is the selection slot and the
#: leading digits the variant; each slot was confirmed from where the group's vertices sit and which material draws them
#: (heads y 125-186 with Head/Eye/Teeth, arm skin at shoulder height, feet and lower legs, shirts, pants, sandals).
EM1000 = EnemySet(
    name='em1000',
    models=((_MODEL + 'em1000', 234, 196), (_MODEL + 'em1000_low', 235, 197), (_MODEL + 'em1000_mid', 236, 198)),
    groups=(('head', (1, 11, 101, 111, 121, 131, 201, 211)),
            ('arm_skin', (2, 12, 22, 32, 52, 62, 72, 82, 92, 222)),
            ('leg_skin', (3, 13, 23, 33, 43, 103, 113, 123, 133, 143)),
            ('shirt', (4, 14, 54, 64, 74, 84, 104, 114, 124, 154, 164, 174, 184, 194)),
            ('pants', (5, 15, 25, 55, 65, 105, 115, 125, 135, 205, 215, 225)),
            ('sandals', (7,))),
    albedo=(108, _MODEL + 'gam01_007_BM'), normal=(110, _MODEL + 'gam01_007_NM'), mask=(109, _MODEL + 'gam01_007_MM'))
#: The sibling set in the same archive: the same 55 groups plus pants variant 35, 79 materials, farther LOD distances.
#: Reviewed the same way and buildable after EM1000 (`build(..., sets=('em1000', 'em1001'))`); the v1 candidate does not
#: include it, so which set a stage draws can be read off the first live round.
EM1001 = EnemySet(
    name='em1001',
    models=((_MODEL + 'em1001', 237, 199), (_MODEL + 'em1001_low', 238, 200), (_MODEL + 'em1001_mid', 239, 201)),
    groups=tuple((slot, ids + (35,) if slot == 'pants' else ids) for slot, ids in EM1000.groups),
    albedo=EM1000.albedo, normal=EM1000.normal, mask=EM1000.mask)
SETS = {'em1000': EM1000, 'em1001': EM1001}

OPTION_GROUP_DECISION = {
    'choice': 'carry_in_every_group',
    'native_records': 'kept byte for byte; index words collapsed so each draws only degenerate triangles',
    'donor_records': 'one per option group, all LODs, the complete donor in each',
    'why': ('Which groups a spawn selects is decided by game code and data outside this archive. A donor placed in '
            'one group would be invisible whenever that group is not selected or is hidden (a destroyed head); a '
            'donor split across slots would lose parts on a spawn that skips a slot (group 222 is arm and torso '
            'skin, which suggests a shirtless spawn selects no shirt group). Every group therefore carries the '
            'whole donor, so any selection draws it. Copies drawn together are the same vertex bytes, bones and '
            'material and are expected to resolve to the same depth and colour; that has not been observed.'),
    'undetermined_offline': [
        'which option groups the game selects per spawn, and whether it hides groups during damage or death',
        'whether a stage draws the em1000 or the em1001 set for this class, and which of high/mid/low per enemy',
        'whether the 32-byte group table spheres are used for culling (they are left native)',
        'whether a record without a native depth-only proxy (mesh type 0x1020) casts a shadow',
        'how the native sandal material shades this surface, and whether overlapping copies show under blending'],
}


# --- skeleton -----------------------------------------------------------------------------------------------------

def measure_roles(model: mt_model.ModFile) -> tuple[dict[str, int], dict]:
    """{role: bone index} read from the bind pose alone: the hierarchy and where each joint sits.

    No animation id is consulted. The root has two trunks, the one that reaches the floor (pelvis) and the one that
    reaches the top (spine). Legs are the pelvis' two deep branches; the chest is where the spine splits into two
    lateral arms and a midline neck; a hand is the last joint stacked on the wrist. Left is the +X side when the toes
    point to +Z.
    """
    table = model.bone_table()
    parents = [int(p) for p in table.get('parents', [])]
    points = {i: np.array((x, y, z), float) for i, x, y, z in model.bone_world()}
    count = len(parents)
    if not table.get('consistent') or not count or len(points) != count:
        raise EnemyWriterError('the enemy skeleton is incomplete')
    roots = [i for i, parent in enumerate(parents) if parent == 255]
    if len(roots) != 1 or any(parent != 255 and parent >= i for i, parent in enumerate(parents)):
        raise EnemyWriterError('the enemy skeleton needs one root and parents stored before their children')
    children = {i: [] for i in range(count)}
    depth, low, high = [1] * count, [points[i][1] for i in range(count)], [points[i][1] for i in range(count)]
    for i in range(count - 1, -1, -1):
        parent = parents[i]
        if parent != 255:
            children[parent].insert(0, i)
            depth[parent] = max(depth[parent], depth[i] + 1)
            low[parent], high[parent] = min(low[parent], low[i]), max(high[parent], high[i])

    def main(bone: int, what: str) -> int:
        best = max((depth[c] for c in children[bone]), default=0)
        picks = [c for c in children[bone] if depth[c] == best]
        if len(picks) != 1:
            raise EnemyWriterError(f'the {what} chain is ambiguous at bone {bone}')
        return picks[0]

    root = roots[0]
    trunks = [c for c in children[root] if depth[c] >= 3]
    if len(trunks) != 2:
        raise EnemyWriterError('the root needs exactly a pelvis trunk and a spine trunk')
    pelvis, spine = min(trunks, key=lambda c: low[c]), max(trunks, key=lambda c: high[c])
    if pelvis == spine:
        raise EnemyWriterError('the pelvis and spine trunks cannot be told apart')
    legs = [c for c in children[pelvis] if depth[c] >= 3]
    chest = spine
    while True:
        branches = [c for c in children[chest] if depth[c] >= 2]
        if len(branches) >= 3:
            break
        if len(branches) != 1:
            raise EnemyWriterError('the spine does not reach a chest with two arms and a neck')
        chest = branches[0]
    centre = points[root][0]
    arms = [c for c in branches if abs(points[c][0] - centre) >= 1.]
    necks = [c for c in branches if abs(points[c][0] - centre) < 1.]
    if len(legs) != 2 or len(arms) != 2 or len(necks) != 1:
        raise EnemyWriterError('the skeleton is not two legs, two arms and one neck')
    chains = {}
    for thigh in legs:
        shin = main(thigh, 'leg')
        foot = main(shin, 'leg')
        chains[thigh] = (thigh, shin, foot, main(foot, 'toe'))
    forward = sum(points[toe][2] - points[foot][2] for _, _, foot, toe in chains.values())
    if abs(forward) < 1e-6:
        raise EnemyWriterError('the toes do not show which way the skeleton faces')
    left = 1. if forward > 0 else -1.

    def side(bone: int) -> str:
        offset = (points[bone][0] - centre) * left
        if abs(offset) < 1e-6:
            raise EnemyWriterError(f'bone {bone} is on the midline, not on a side')
        return 'l' if offset > 0 else 'r'

    roles = {'hip': pelvis, 'chest': chest, 'head': main(necks[0], 'neck')}
    extra = {'root': root, 'spine': spine, 'neck': necks[0], 'facing': '+Z' if forward > 0 else '-Z',
             'left_side': '+X' if left > 0 else '-X'}
    for thigh, shin, foot, toe in chains.values():
        s = side(thigh)
        if not points[thigh][1] > points[shin][1] > points[foot][1]:
            raise EnemyWriterError('a leg chain does not descend thigh, shin, foot')
        roles.update({f'{s}_thigh': thigh, f'{s}_shin': shin, f'{s}_foot': foot})
        extra[f'{s}_toe'] = toe
    for clavicle in arms:
        upper = main(clavicle, 'arm')
        fore = main(upper, 'arm')
        hand = main(fore, 'arm')
        while True:                       # the wrist twist and the hand share one position; the hand is the last
            stacked = [c for c in children[hand] if np.linalg.norm(points[c] - points[hand]) < 1e-3]
            if len(stacked) != 1:
                break
            hand = stacked[0]
        s = side(clavicle)
        reach = [abs(points[b][0] - centre) for b in (upper, fore, hand)]
        if not reach[0] < reach[1] < reach[2]:
            raise EnemyWriterError('an arm chain does not run outward upper, fore, hand')
        roles.update({f'{s}_upper': upper, f'{s}_fore': fore, f'{s}_hand': hand})
        extra[f'{s}_clavicle'] = clavicle
    if len(roles) != 15 or len(set(roles.values())) != 15:
        raise EnemyWriterError('the skeleton does not give fifteen distinct role bones')
    if not points[roles['head']][1] > points[chest][1] > points[roles['l_thigh']][1]:
        raise EnemyWriterError('the head, chest and legs are not stacked upward')
    return roles, extra


def roles_by_animation_id(model: mt_model.ModFile) -> dict[str, int]:
    """{role: bone index} through the RE5 animation ids; each id must name exactly one bone."""
    ids = [int(v) for v in model.bone_table().get('anim_map', [])]
    roles = {}
    for role, animation in ROLE_ANIMATION_IDS.items():
        if ids.count(animation) != 1:
            raise EnemyWriterError(f'animation id {animation} ({role}) does not name exactly one bone')
        roles[role] = ids.index(animation)
    return roles


def role_map(model: mt_model.ModFile) -> tuple[dict[str, int], dict]:
    """The role map, accepted only when the bind-pose measurement and the animation ids name the same bones."""
    measured, extra = measure_roles(model)
    named = roles_by_animation_id(model)
    if measured != named:
        wrong = sorted(role for role in named if measured.get(role) != named[role])
        raise EnemyWriterError(f'the bind pose and the animation ids disagree on {wrong}')
    points = {i: (x, y, z) for i, x, y, z in model.bone_world()}
    return measured, {'method': 'bind-pose hierarchy and joint positions, cross-checked against RE5 animation ids',
                      'animation_ids': {role: ROLE_ANIMATION_IDS[role] for role in measured},
                      'bind_position': {role: [round(float(v), 4) for v in points[bone]] for role, bone in measured.items()},
                      'skeleton': extra, 'bone_count': len(points)}


# --- option groups ------------------------------------------------------------------------------------------------

def group_table(model: mt_model.ModFile) -> list[int]:
    header = model.header()
    start, end = header['offsets']['groups'], header['offsets']['materials']
    if end - start != 32 * header['group_count'] or not header['group_count']:
        raise EnemyWriterError('the option-group table does not match its count')
    return [struct.unpack_from('<I', model.raw, start + 32 * i)[0] for i in range(header['group_count'])]


def account_groups(model: mt_model.ModFile, target: EnemySet) -> dict[int, dict]:
    """Every option group of the model, matched one to one against the reviewed list; anything else is refused."""
    reviewed, table = target.group_ids(), group_table(model)
    records = model.meshes()
    used = {record['group_index'] for record in records}
    if len(set(reviewed)) != len(reviewed) or 0 in reviewed:
        raise EnemyWriterError('the reviewed option-group list must hold distinct nonzero ids')
    if sorted(table) != sorted(reviewed) or not used <= set(reviewed):
        raise EnemyWriterError(f'option groups differ from the reviewed list: unreviewed '
                               f'{sorted((set(table) | used) - set(reviewed))}, absent {sorted(set(reviewed) - set(table))}')
    slots = target.slot_of()
    out = {}
    for group in reviewed:
        own = [record for record in records if record['group_index'] == group]
        masks = sorted({record['level_of_detail'] for record in own})
        if not own or any(mask not in NATIVE_LOD_MASKS for mask in masks):
            raise EnemyWriterError(f'option group {group} does not have the measured native LOD records')
        out[group] = {'slot': slots[group], 'native_records': len(own),
                      'native_vertices': sum(record['vertex_count'] for record in own), 'native_lod_masks': masks}
    return out


# --- model --------------------------------------------------------------------------------------------------------

def _template(records: list[dict]) -> int:
    """A native record that already has the shape the donor is written in, so its opaque bytes carry over."""
    for index, record in enumerate(records):
        if (record['mesh_type'], record['vertex_format'], record['vertex_flags'], record['render_mode']) == (
                0xFFFF, DONOR_FORMAT, 33, 4):
            return index
    raise EnemyWriterError('the model has no native four-weight record to use as a template')


def _envelopes(model: mt_model.ModFile) -> list[bytes]:
    header, records = model.header(), model.meshes()
    start = header['offsets']['meshes'] + mt_model.MOD_MESH_RECORD_V211 * len(records)
    table = model.raw[start:header['offsets']['vertex_buffer']]
    counts = [record['vertex_group_count'] for record in records]
    if len(table) != mt_model.MOD_WEIGHT_BOUND * sum(counts) or header['weight_bound_count'] != sum(counts):
        raise EnemyWriterError('the envelope table does not match the mesh records and the header count at 0xA0')
    out, cursor = [], 0
    for count in counts:
        out.append(table[cursor:cursor + mt_model.MOD_WEIGHT_BOUND * count])
        cursor += mt_model.MOD_WEIGHT_BOUND * count
    return out


def _index_words(model: mt_model.ModFile) -> np.ndarray:
    """The index stream without its alignment word; every record must own one separated range of it."""
    header, records = model.header(), model.meshes()
    region = model.raw[header['offsets']['index_buffer']:header['offsets']['end']]
    faces = header['face_count']
    if len(region) != 2 * faces + (2 * faces) % 4 or any(region[2 * faces:]):
        raise EnemyWriterError('the index buffer is not its face count plus alignment')
    words = np.frombuffer(region[:2 * faces], '<u2').copy()
    cursor = 0
    for record in sorted(records, key=lambda r: r['face_index']):
        end = record['face_index'] + record['face_count']
        if record['face_index'] != cursor or end >= faces or words[end] != 0xFFFF:
            raise EnemyWriterError('mesh index ranges are not contiguous and separated')
        cursor = end + 1
    if cursor != faces:
        raise EnemyWriterError('mesh index ranges do not cover the index buffer')
    return words


def graft(native: mt_model.ModFile, donor: mt_model.ModFile, *, groups: list[int],
          material_index: int) -> tuple[bytes, dict]:
    """Add the one-mesh `donor` to `native` once per option group and make every native record draw nothing.

    The native table is not reshaped: each native record keeps its 56 bytes (group, material, LOD mask, mesh id,
    offsets), its vertex bytes and its envelope records. Only its index words change, to the record's own first vertex,
    so every strip is degenerate while restart markers and counts stay. The donor's vertex, index and envelope bytes
    are appended once per group as a new record (LOD mask 0xFF, ids after the native ones), inserted behind the last
    native record of the same material so the table stays sorted by material as shipped.
    """
    header, records = native.header(), native.meshes()
    count, offsets = len(records), header['offsets']
    if not records or not native.split_valid() or native.position_transform() is None:
        raise EnemyWriterError('the native model needs a complete mesh table and skeleton')
    if sorted(record['mesh_id'] for record in records) != list(range(1, count + 1)):
        raise EnemyWriterError('native mesh ids are not the measured permutation of 1..count')
    if any(record['min_index'] != record['vertex_index'] or
           record['max_index'] != record['vertex_index'] + record['vertex_count'] - 1 for record in records):
        raise EnemyWriterError('a native record does not address its own vertex window')
    if not groups or len(set(groups)) != len(groups) or count + len(groups) > 0xFFFF:
        raise EnemyWriterError('choose distinct option groups for the donor records')
    if not 0 <= material_index < header['material_count']:
        raise EnemyWriterError('the donor material is outside the model')
    native_envelopes, words = _envelopes(native), _index_words(native)
    for record in records:
        span = words[record['face_index']:record['face_index'] + record['face_count']]
        real = span != 0xFFFF
        if real.any() and (span[real].min() < record['min_index'] or span[real].max() > record['max_index']):
            raise EnemyWriterError('a native record indexes outside its vertex window')
        span[real] = record['min_index']

    donor_header, donor_records = donor.header(), donor.meshes()
    donor_offsets = donor_header['offsets']
    same_frame = (native.raw[offsets['bones']:offsets['meshes']] ==
                  donor.raw[donor_offsets['bones']:donor_offsets['meshes']])
    if len(donor_records) != 1 or donor_header['mesh_count'] != 1 or not same_frame:
        raise EnemyWriterError('the donor must be one mesh authored on this exact skeleton, groups and materials')
    piece = donor_records[0]
    vertices = donor.raw[donor_offsets['vertex_buffer']:donor_offsets['index_buffer']]
    indices = donor.raw[donor_offsets['index_buffer']:donor_offsets['end']]
    envelopes = donor.raw[donor_offsets['meshes'] + mt_model.MOD_MESH_RECORD_V211:donor_offsets['vertex_buffer']]
    shape = (piece['mesh_type'], piece['vertex_format'], piece['vertex_stride'], piece['vertex_index'],
             piece['vertex_offset'], piece['face_index'], piece['min_index'], piece['max_index'])
    if (shape != (0xFFFF, DONOR_FORMAT, DONOR_STRIDE, 0, 0, 0, 0, piece['vertex_count'] - 1)
            or len(vertices) != piece['vertex_count'] * DONOR_STRIDE
            or len(indices) != 2 * (piece['face_count'] + 1) or indices[-2:] != b'\xff\xff'
            or donor_header['face_count'] != piece['face_count'] + 1
            or len(envelopes) != mt_model.MOD_WEIGHT_BOUND * piece['vertex_group_count'] or not envelopes):
        raise EnemyWriterError('the donor mesh is not the measured four-weight one-mesh layout')
    triangles = len(mtf_author.mesh_triangles(donor, 0))
    if not triangles:
        raise EnemyWriterError('the donor mesh has no triangles')

    native_vertices = native.raw[offsets['vertex_buffer']:offsets['index_buffer']]
    if len(native_vertices) % 4 or len(vertices) % 4:
        raise EnemyWriterError('vertex data must stay four-byte aligned')
    template, faces = _template(records), header['face_count']
    fields = {name: piece[name] for name, _, _ in mt_model.MOD_MESH_FIELDS} | {'vertex_format': piece['vertex_format']}
    added = [fields | {'_template_index': template, 'group_index': group, 'material_index': material_index,
                       'level_of_detail': ALL_LODS, 'vertex_offset': len(native_vertices) + k * len(vertices),
                       'face_index': faces + k * (piece['face_count'] + 1), 'mesh_id': count + 1 + k}
             for k, group in enumerate(groups)]
    position = next((i for i, record in enumerate(records) if record['material_index'] > material_index), count)
    table = records[:position] + added + records[position:]
    trailer = (b''.join(native_envelopes[:position]) + envelopes * len(groups) + b''.join(native_envelopes[position:]))
    index_buffer = words.astype('<u2').tobytes() + indices * len(groups)
    index_buffer += bytes(len(index_buffer) % 4)
    result = mt_model.rebuild_mod(
        native, vertex_buffer=native_vertices + vertices * len(groups), index_buffer=index_buffer,
        mesh_records=table, mesh_count=len(table), vertex_count=header['vertex_count'] + len(groups) * piece['vertex_count'],
        face_count=faces + len(groups) * (piece['face_count'] + 1),
        edge_count=header['polygon_count'] + len(groups) * triangles, bounds=donor.bounds(), mesh_trailer=trailer)
    return result, {'native_records': count, 'donor_records': len(groups), 'mesh_records': len(table),
                    'donor_vertices_per_record': piece['vertex_count'], 'donor_triangles_per_record': triangles,
                    'donor_envelopes_per_record': piece['vertex_group_count'],
                    'envelope_count': header['weight_bound_count'] + len(groups) * piece['vertex_group_count'],
                    'template_record': template, 'material_index': material_index, 'inserted_at': position,
                    'native_index_words_collapsed': int(sum(record['face_count'] for record in records)),
                    'model_bytes': len(result)}


def _material(mrl: bytes, model: mt_model.ModFile, target: EnemySet) -> tuple[int, dict]:
    """The one native material that samples the atlas texture, with its secondary maps confirmed."""
    rows = [row for row in mtf_mrl.inspect_bindings(mrl, model)
            if any(b['shader_hash'] == mtf_mrl.ALBEDO_HASH and b['path'] == target.albedo[1] for b in row['bindings'])]
    if len(rows) != 1:
        raise EnemyWriterError('exactly one native material must sample the reviewed atlas texture')
    paths = {b['shader_hash']: b['path'] for b in rows[0]['bindings']}
    if paths.get(NORMAL_HASH) != target.normal[1] or paths.get(MASK_HASH) != target.mask[1]:
        raise EnemyWriterError('the atlas material does not bind the reviewed normal and mask maps')
    return rows[0]['mod_index'], {'index': rows[0]['mod_index'], 'name': rows[0]['name'],
                                  'albedo': target.albedo[1], 'normal': target.normal[1], 'mask': target.mask[1]}


def _entry(parsed: mt_arc.Arc, index: int, name: str, magic: bytes) -> bytes:
    if not 0 <= index < len(parsed.entries) or parsed.entries[index].name != name:
        raise EnemyWriterError(f'entry {index} is not the reviewed {name!r}')
    try:
        raw = zlib.decompress(parsed.entries[index].data)
    except zlib.error as exc:
        raise EnemyWriterError(f'entry {index} is not a zlib-wrapped resource') from exc
    if raw[:4] != magic:
        raise EnemyWriterError(f'entry {index} is not the reviewed {magic[:3].decode()} resource')
    return raw


def _contact_scale(vertices: list[dict], joints: dict[str, tuple], native: dict[str, tuple]) -> tuple[float, dict]:
    """Uniform donor scale that puts the donor's soles on the ground plane (model y 0) under the native ankles."""
    floor = min(v['position'][1] for v in vertices)
    ratios = []
    for role in ('l_foot', 'r_foot'):
        rise = joints[role][1] - floor
        if rise <= 1e-6 or native[role][1] <= 1e-6:
            raise EnemyWriterError('the ankles must sit above the floor to scale the donor')
        ratios.append(native[role][1] / rise)
    scale = float(sum(ratios) / len(ratios))
    return scale, {'rule': 'native ankle height over donor ankle height: donor soles land on model y 0',
                   'donor_floor_y': float(floor), 'scale': scale}


def author(archive: bytes, source: Path, target: EnemySet, *, source_roles: dict[str, str] | None = None,
           segments: dict[str, str] | None = None, scale: float | None = None, secondary: str = 'neutral'):
    """Return (archive, receipt) with every model of `target` carrying the donor; inputs are not hash-checked here.

    `scale` is the donor's uniform cross-section and extremity scale; limbs always stretch to the native segment
    lengths. Left unset it is measured so the soles meet the ground. `secondary='neutral'` flattens the atlas
    material's normal map and zeroes its mask (its native detail would be sampled through unrelated atlas UVs);
    `'native'` leaves both maps as shipped.
    """
    if secondary not in ('neutral', 'native'):
        raise EnemyWriterError("secondary maps are either 'neutral' or 'native'")
    source, source_roles, segments = Path(source), dict(source_roles or SOURCE_ROLES), dict(segments or SEGMENTS)
    if set(source_roles) != set(ROLE_ANIMATION_IDS):
        raise EnemyWriterError('the donor must name the fifteen measured roles')
    parsed = mt_arc.parse(archive)
    indices = [i for _, mod, mrl in target.models for i in (mod, mrl)] + [target.albedo[0], target.normal[0],
                                                                          target.mask[0]]
    if len(set(indices)) != len(indices) or not target.models:
        raise EnemyWriterError('the reviewed entry indices must be distinct')
    texture = _entry(parsed, *target.albedo, b'TEX\0')
    normal, mask = _entry(parsed, *target.normal, b'TEX\0'), _entry(parsed, *target.mask, b'TEX\0')
    surface = mtf_tex.parse(texture)
    vertices, triangles, _, appearance = mtf_materials.source_mesh(source, atlas_size=(surface.width, surface.height))
    gltf, _, _, world = characters._load(source)
    joints = {}
    for role, name in source_roles.items():
        nodes = [i for i, node in enumerate(gltf['nodes']) if node.get('name') == name]
        if len(nodes) != 1:
            raise EnemyWriterError(f'the donor needs exactly one joint named {name!r}')
        joints[role] = tuple(float(v) for v in world[nodes[0]][:3, 3])

    payloads: dict[int, bytes] = {}
    models, atlas_payload, fit, groups, positions = {}, None, None, None, None
    for name, mod_index, mrl_index in target.models:
        native_raw, mrl = _entry(parsed, mod_index, name, b'MOD\0'), _entry(parsed, mrl_index, name, b'MRL\0')
        native, short = mt_model.parse_mod(native_raw), name.rsplit('\\', 1)[-1]
        accounted = account_groups(native, target)
        roles, evidence = role_map(native)
        material_index, material = _material(mrl, native, target)
        template = _template(native.meshes())
        measured, rule = _contact_scale(vertices, joints, evidence['bind_position'])
        used = float(scale) if scale is not None else measured
        result, donor_raw, _, imported = re5_mesh_import.build_archive(
            archive, source, model_name=short, source_roles=source_roles, target_roles=roles,
            segments=segments, scale=used, material_index=material_index, template_index=template,
            pose_mode='native_segments')
        after = mt_arc.parse(result)
        changed = {i for i, (a, b) in enumerate(zip(parsed.entries, after.entries)) if a.data != b.data}
        if (imported['changed_entry_indices'] != [mod_index, target.albedo[0]] or len(after.entries) != len(parsed.entries)
                or not changed <= {mod_index, target.albedo[0]}
                or zlib.decompress(after.entries[mrl_index].data) != mrl):
            raise EnemyWriterError(f'the mesh import did not address the reviewed entries of {name!r}')
        new_texture = zlib.decompress(after.entries[target.albedo[0]].data)
        if atlas_payload not in (None, new_texture):
            raise EnemyWriterError('the models of one set must share one atlas')
        atlas_payload = new_texture
        grafted, report = graft(native, mt_model.parse_mod(donor_raw), groups=target.group_ids(),
                                material_index=material_index)
        payloads[mod_index] = grafted
        this_fit = {'pose_mode': imported['pose_mode'], 'cross_section_scale': used, 'ground_contact': rule,
                    'scale_source': 'caller' if scale is not None else 'measured ground contact',
                    'bounds': imported['bounds'], 'native_bounds': imported['original_bounds'],
                    'height': imported['bounds']['max']['y'] - imported['bounds']['min']['y'],
                    'native_height': imported['original_bounds']['max']['y'] - imported['original_bounds']['min']['y']}
        fit = fit or this_fit
        positions = positions or evidence['bind_position']
        if evidence['bind_position'] != positions:
            raise EnemyWriterError('the models of one set must share one bind pose for the role joints')
        groups = groups or {group: {'slot': row['slot'], 'native_lod_masks': row['native_lod_masks'],
                                    'native_records': {}, 'native_vertices': {}} for group, row in accounted.items()}
        for group, row in accounted.items():
            groups[group]['native_records'][short] = row['native_records']
            groups[group]['native_vertices'][short] = row['native_vertices']
        models[short] = report | {
            'mod_entry': mod_index, 'mrl_entry': mrl_index, 'bone_count': evidence['bone_count'], 'roles': roles,
            'skeleton': evidence['skeleton'], 'material': material,
            'position_roundtrip_max_error': imported['position_roundtrip_max_error'],
            'native_sha256': hashlib.sha256(native_raw).hexdigest(), 'sha256': hashlib.sha256(grafted).hexdigest()}
    payloads[target.albedo[0]] = atlas_payload
    if secondary == 'neutral':
        payloads[target.normal[0]] = mtf_secondary.constant_channels(normal, (128, 128))
        payloads[target.mask[0]] = mtf_secondary.constant_channels(mask, (0,))
    output = archive
    for index in sorted(payloads):                 # explicit index, never a name: MOD and MRL share names
        output = mtf_author.replace_archive_model(output, index, payloads[index])
    checks = verify(archive, output, target, secondary=secondary)
    final = mt_arc.parse(output)
    one = next(iter(models.values()))
    receipt = {
        'recipe': 're5_enemy_writer', 'recipe_version': RECIPE_VERSION, 'enemy_set': target.name,
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'target_archive_sha256': hashlib.sha256(archive).hexdigest(),
        'written_sha256': hashlib.sha256(output).hexdigest(), 'written_bytes': len(output),
        'entries': len(final.entries),
        'entries_replaced': [{'index': index, 'name': final.entries[index].name,
                              'kind': payloads[index][:3].decode('ascii'),
                              'bytes_before': parsed.entries[index].tag & 0xFFFFFF, 'bytes_after': len(payloads[index]),
                              'sha256': hashlib.sha256(payloads[index]).hexdigest()} for index in sorted(payloads)],
        'option_groups': OPTION_GROUP_DECISION | {'count': len(groups), 'groups': {
            str(group): row | {'native_action': 'index words collapsed; records, vertices and envelopes kept',
                               'donor_record': 'complete donor, LOD mask 0xFF'} for group, row in groups.items()}},
        'role_map': {'method': evidence['method'], 'source_roles': source_roles,
                     'animation_ids': dict(ROLE_ANIMATION_IDS), 'bind_position': positions,
                     'bones': {model: row['roles'] for model, row in models.items()}},
        'fit': fit | {'segments': segments, 'bind_joints_moved': False, 'native_motion_edited': False},
        'models': models,
        'counts': {'donor_vertices': one['donor_vertices_per_record'], 'donor_triangles': one['donor_triangles_per_record'],
                   'source_vertices': len(vertices), 'source_triangles': len(triangles),
                   'donor_records_per_model': one['donor_records'],
                   'written_donor_vertices': sum(m['donor_records'] * m['donor_vertices_per_record'] for m in models.values()),
                   'written_donor_triangles': sum(m['donor_records'] * m['donor_triangles_per_record'] for m in models.values()),
                   'native_records_blanked': sum(m['native_records'] for m in models.values())},
        'appearance': {
            'atlas_entry': target.albedo[0], 'atlas_texture': target.albedo[1],
            'atlas_size': [surface.width, surface.height], 'atlas_source': appearance,
            'material': one['material']['name'], 'mrl_entries_changed': False, 'secondary_maps': secondary,
            'normals': 'recomputed from the fitted triangles; flat wherever the donor splits its vertices per face',
            'shared_texture_note': 'the atlas, normal and mask entries are also sampled by other models of this '
                                   'archive that are not replaced; their sandals show the edited maps'},
        'checks': checks, 'live_verified': False, 'gameplay_verified': False, 'writer_registered': False}
    return output, receipt


# --- verification -------------------------------------------------------------------------------------------------

def _check_model(native_raw: bytes, raw: bytes, target: EnemySet) -> dict:
    """Re-parse one written model against its native original; every measured format rule must hold."""
    def need(condition, message):
        if not condition:
            raise EnemyWriterError(f'written model check failed: {message}')

    native, model = mt_model.parse_mod(native_raw), mt_model.parse_mod(raw)
    before, header = native.header(), model.header()
    old, new = before['offsets'], header['offsets']
    originals, records = native.meshes(), model.meshes()
    reviewed, size = target.group_ids(), mt_model.MOD_MESH_RECORD_V211
    need((header['version'], header['revision']) == (211, 0) and model.variant == 'model', 'MOD version')
    need(native.raw[old['bones']:old['meshes']] == model.raw[new['bones']:new['meshes']],
         'skeleton, group table and material names are native')
    need(native.raw[0x90:0xA0] == model.raw[0x90:0xA0] and raw[new['end']:] == native_raw[old['end']:],
         'LOD distances and file trailer are native')
    need(len(records) == header['mesh_count'] == len(originals) + len(reviewed), 'mesh count')
    need(model.split_valid() and header['vertex_buffer_size'] == new['index_buffer'] - new['vertex_buffer']
         == sum(r['vertex_count'] * r['vertex_stride'] for r in records), 'vertex accounting')
    envelopes = sum(r['vertex_group_count'] for r in records)
    need(new['vertex_buffer'] - new['meshes'] - size * len(records) == mt_model.MOD_WEIGHT_BOUND * envelopes
         and struct.unpack_from('<I', raw, 0xA0)[0] == envelopes, '144-byte envelope records and the count at 0xA0')
    bounds = model.weight_bounds()
    need(len(bounds) == envelopes and all(row['bone'] < header['bone_count'] for row in bounds), 'envelope bones')
    need(all(np.isfinite(row['sphere']).all() and np.isfinite(row['min']).all() and np.isfinite(row['max']).all()
             for row in bounds), 'envelope volumes are finite')
    faces = header['face_count']
    region = raw[new['index_buffer']:new['end']]
    need(sum(r['face_count'] for r in records) + len(records) == faces
         and len(region) == 2 * faces + (2 * faces) % 4, 'face accounting and index alignment')
    words = np.frombuffer(region[:2 * faces], '<u2')
    need(sorted(r['mesh_id'] for r in records) == list(range(1, len(records) + 1)), 'mesh ids')
    need([r['material_index'] for r in records] == sorted(r['material_index'] for r in records), 'material order')
    donors, natives = [], []
    for i, record in enumerate(records):
        packed = struct.unpack_from('<I', raw, new['meshes'] + size * i + 4)[0]
        need(packed == record['group_index'] | record['material_index'] << 12 | record['level_of_detail'] << 24,
             'packed group12/material12/LOD8 word')
        need(record['group_index'] in reviewed and record['material_index'] < header['material_count'], 'group/material')
        need(words[record['face_index'] + record['face_count']] == 0xFFFF, 'index range separator')
        span = words[record['face_index']:record['face_index'] + record['face_count']]
        real = span[span != 0xFFFF]
        need(len(real) and real.min() >= record['min_index'] and real.max() <= record['max_index']
             and record['max_index'] - record['min_index'] == record['vertex_count'] - 1, 'indices inside the vertex window')
        need(mt_model.fvf_stride(record['vertex_format']) == record['vertex_stride'], 'vertex format stride')
        (donors if record['level_of_detail'] == ALL_LODS else natives).append(i)
    need(len(natives) == len(originals) and all(records[i]['level_of_detail'] in NATIVE_LOD_MASKS for i in natives),
         'native records keep their LOD masks')
    native_vertices = native.raw[old['vertex_buffer']:old['index_buffer']]
    need(raw[new['vertex_buffer']:new['vertex_buffer'] + len(native_vertices)] == native_vertices,
         'native vertex bytes are untouched')
    native_words = np.frombuffer(native_raw[old['index_buffer']:old['index_buffer'] + 2 * before['face_count']], '<u2')
    need(np.array_equal(words[:len(native_words)] == 0xFFFF, native_words == 0xFFFF), 'native strip restarts are kept')
    old_envelopes, cursor, kept, drawn = _envelopes(native), new['meshes'] + size * len(records), 0, 0
    for i, record in enumerate(records):
        length = mt_model.MOD_WEIGHT_BOUND * record['vertex_group_count']
        if record['level_of_detail'] != ALL_LODS:
            original = originals[kept]
            start = old['meshes'] + size * kept
            need(raw[new['meshes'] + size * i:new['meshes'] + size * (i + 1)] == native_raw[start:start + size],
                 'native 56-byte mesh records are untouched')
            need(raw[cursor:cursor + length] == old_envelopes[kept], 'native envelope records are untouched')
            span = words[original['face_index']:original['face_index'] + original['face_count']]
            need(bool(np.all((span == 0xFFFF) | (span == original['min_index']))), 'native records draw nothing')
            drawn += len(mtf_author.mesh_triangles(model, i))
            kept += 1
        cursor += length
    need(drawn == 0, 'no native triangle survives the strip decoder')
    need(sorted(records[i]['group_index'] for i in donors) == sorted(reviewed), 'one donor record per option group')
    first = records[donors[0]]
    need(all((records[i]['material_index'], records[i]['vertex_format'], records[i]['vertex_stride'],
              records[i]['mesh_type'], records[i]['vertex_index']) ==
             (first['material_index'], DONOR_FORMAT, DONOR_STRIDE, 0xFFFF, 0) for i in donors), 'donor record shape')
    need(sorted(records[i]['mesh_id'] for i in donors) == list(range(len(originals) + 1, len(records) + 1)),
         'donor mesh ids follow the native ids')
    blobs = set()
    for i in donors:
        data, record = model.mesh_bytes(i)
        blobs.add((data, words[record['face_index']:record['face_index'] + record['face_count']].tobytes()))
    need(len(blobs) == 1, 'every option group carries the same donor bytes')
    points = np.asarray(model.positions(donors[0]), float)
    box = model.bounds()
    low, high = (np.array([box[k][a] for a in 'xyz']) for k in ('min', 'max'))
    need(np.isfinite(points).all() and (points >= low - .01).all() and (points <= high + .01).all()
         and box['sphere']['r'] > 0, 'donor vertices lie inside the written bounds')
    data, record = model.mesh_bytes(donors[0])
    block = np.frombuffer(data, np.uint8).reshape(-1, DONOR_STRIDE)
    joints = block[:, 16:20]
    first_weight = block[:, 6:8].copy().view('<i2')[:, 0] / 32767.
    others = block[:, 24:28].copy().view('<f2').astype(float)
    need(int(joints.max()) < header['bone_count'] and (first_weight >= 0).all() and (others >= 0).all()
         and (first_weight + others.sum(1) <= 1 + 1e-3).all(), 'donor skin bones and weights')
    triangles = len(mtf_author.mesh_triangles(model, donors[0]))
    need(triangles > 0, 'donor triangles')
    return {'mesh_records': len(records), 'native_records': len(natives), 'donor_records': len(donors),
            'envelope_count': envelopes, 'vertex_count': header['vertex_count'], 'face_count': faces,
            'donor_vertices_per_record': first['vertex_count'], 'donor_triangles_per_record': triangles,
            'bounds': box, 'native_drawn_triangles': drawn}


def verify(original: bytes, candidate: bytes, target: EnemySet, *, secondary: str = 'neutral') -> dict:
    """Re-parse a written archive against its original and return what was checked; any failure raises.

    Entry table unchanged; every entry outside the reviewed indices byte-identical; replaced entries in the shipped
    zlib framing (wrapped stream, level 6, size tag); each model through `_check_model`; textures in their native
    containers. Every model of the set must have changed. A texture may be unchanged only because an earlier set of
    the same archive already wrote it.
    """
    before, after = mt_arc.parse(original), mt_arc.parse(candidate)
    mods = {mod: name for name, mod, _ in target.models}
    textures = [target.albedo[0]] + ([target.normal[0], target.mask[0]] if secondary == 'neutral' else [])
    allowed = set(mods) | set(textures)
    if (after.version, len(after.entries)) != (before.version, len(before.entries)) or mt_arc.build(after) != candidate:
        raise EnemyWriterError('written archive check failed: entry count or container layout')
    changed = []
    for index, (a, b) in enumerate(zip(before.entries, after.entries)):
        if (a.name, a.hash) != (b.name, b.hash):
            raise EnemyWriterError(f'written archive check failed: entry {index} lost its name or hash')
        if (a.data, a.tag) == (b.data, b.tag):
            continue
        if index not in allowed:
            raise EnemyWriterError(f'written archive check failed: entry {index} is outside the reviewed indices')
        try:
            raw = zlib.decompress(b.data)
        except zlib.error:
            raw = None
        if (raw is None or b.data[:2] != a.data[:2] or zlib.compress(raw, 6) != b.data
                or b.tag != (a.tag & 0xFF000000 | len(raw)) or len(raw) > 0xFFFFFF):
            raise EnemyWriterError(f'written archive check failed: entry {index} is not in the shipped zlib framing')
        changed.append(index)
    if not set(mods) <= set(changed):
        raise EnemyWriterError('written archive check failed: a reviewed model was not replaced')
    models = {}
    for index, name in mods.items():
        models[name.rsplit('\\', 1)[-1]] = _check_model(zlib.decompress(before.entries[index].data),
                                                         zlib.decompress(after.entries[index].data), target)
    for index in textures:
        old, new = (zlib.decompress(arc.entries[index].data) for arc in (before, after))
        if mtf_tex.parse(old) != mtf_tex.parse(new) or len(old) != len(new) or old[:20] != new[:20]:
            raise EnemyWriterError(f'written archive check failed: texture {index} left its native container')
    return {'entry_count': len(after.entries), 'entry_count_unchanged': True, 'changed_entries': sorted(changed),
            'untouched_entries_byte_identical': len(after.entries) - len(changed),
            'zlib_framing': 'wrapped stream, level 6, tag = flags | uncompressed size on every replaced entry',
            'container_rebuild_identical': True, 'mrl_entries_untouched': True,
            'packed_mesh_fields': 'group12/material12/LOD8 re-derived on every record',
            'envelope_records': '144 bytes each; table length, per-record counts and header 0xA0 agree',
            'native_tables': 'every native 56-byte record, vertex byte and envelope record identical to the original',
            'textures': 'native TEX container, dimensions, format and mip layout kept', 'models': models}


# --- bounded recipe -----------------------------------------------------------------------------------------------

def build(archive: bytes, source: Path, *, sets: tuple[str, ...] = ('em1000',), scale: float | None = None,
          secondary: str = 'neutral'):
    """Return (complete uEm10.arc, receipt) for the measured donor and archive only; nothing is written or launched.

    The v1 candidate is `sets=('em1000',)`. `('em1000', 'em1001')` writes the sibling set on top of it; each step is
    verified against its own input, so the final archive differs from the original only at both sets' reviewed indices.
    """
    source, sets = Path(source), tuple(sets)
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise EnemyWriterError('Mario needs the exact measured sm64ds_mario.glb; this source revision is unsupported')
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise EnemyWriterError('Mario needs the exact measured original uEm10.arc')
    if sets[:1] != ('em1000',) or len(set(sets)) != len(sets) or any(name not in SETS for name in sets):
        raise EnemyWriterError('build the reviewed em1000 set first; em1001 may only follow it')
    output, receipt = author(archive, source, EM1000, scale=scale, secondary=secondary)
    for name in sets[1:]:
        output, more = author(output, source, SETS[name], scale=scale, secondary=secondary)
        receipt.setdefault('additional_sets', {})[name] = more
        receipt.update(written_sha256=more['written_sha256'], written_bytes=more['written_bytes'])
    models = [name.rsplit('\\', 1)[-1] for key in sets for name, _, _ in SETS[key].models]
    native = [name.rsplit('\\', 1)[-1] for key in SETS if key not in sets for name, _, _ in SETS[key].models]
    receipt.update(
        source={'slug': SOURCE_SLUG, 'model': SOURCE_MODEL, 'sha256': SOURCE_SHA256,
                'provenance': 'Super Mario 64 DS (USA), extracted by gbox.sm64ds_chars from the operator\'s copy'},
        target={'archive': ARCHIVE_PATH, 'sha256': ARCHIVE_SHA256, 'class': 'uEm10', 'models': models,
                'not_replaced': native + ['em2100', 'uEm11.arc']},
        replacement_scope={'route': 'measured_mario_enemy_mesh_recipe', 'complete': False, 'gameplay_verified': False,
                           'source_platform': 'nds', 'written_platform': 'switch', 'collection_model_used': True,
                           'requested_character': {'slug': SOURCE_SLUG, 'name': 'Mario'},
                           'target_archive': ARCHIVE_PATH,
                           'notes': ['Offline candidate; no boot, round or frame has been observed',
                                     f'Only {", ".join(models)} of uEm10.arc carry the donor',
                                     'uEm11 and every other enemy class stay native',
                                     'The title restarts to load the archive; a running round is not preserved']},
        acceptance='experimental; offline structural checks only')
    return output, receipt


def _donor(archive: bytes, target: EnemySet):
    """The first written donor record of the set's first model, and the atlas the archive holds."""
    parsed = mt_arc.parse(archive)
    name, mod_index, _ = target.models[0]
    model = mt_model.parse_mod(_entry(parsed, mod_index, name, b'MOD\0'))
    index = next((i for i, record in enumerate(model.meshes()) if record['level_of_detail'] == ALL_LODS), None)
    if index is None:
        raise EnemyWriterError('the archive holds no donor record to preview')
    atlas = np.asarray(mtf_tex.decode(_entry(parsed, *target.albedo, b'TEX\0')).convert('RGBA'), np.uint8)
    return model, index, atlas


def _sheet(poses, uvs, triangles, atlas, yaws, size: int, png: Path) -> None:
    """One row of z-buffered CPU views, every pose under every yaw, shaded flat per triangle by the previewer."""
    import tempfile
    from PIL import Image
    from . import melee_models

    views = []
    with tempfile.TemporaryDirectory() as folder:
        for number, points in enumerate(poses):
            count = len(points)
            prim = {'pos': np.asarray(points, np.float32), 'nrm': np.tile((0., 0., 1.), (count, 1)).astype(np.float32),
                    'uv': np.asarray(uvs, np.float32), 'tris': np.asarray(triangles, np.int64),
                    'J': np.zeros((count, 4), np.int64), 'W': np.eye(1, 4, dtype=np.float32).repeat(count, 0),
                    'color': (255, 255, 255, 255), 'tex': atlas}
            gltf = Path(folder) / f'pose{number}.gltf'
            melee_models.write_gltf(gltf, [{'parent': -1, 'world': np.eye(4)}], [prim], 1., 're5_enemy', ['root'])
            for yaw in yaws:
                path = Path(folder) / f'view{len(views)}.png'
                characters.render_preview(gltf, path, size=size, yaw=yaw, depth=True)
                views.append(Image.open(path).convert('RGB'))
    sheet = Image.new('RGB', (size * len(views), size))
    for i, view in enumerate(views):
        sheet.paste(view, (size * i, 0))
    sheet.save(png)


def preview(archive: bytes, png: Path, *, target: EnemySet = EM1000, size: int = 384) -> dict:
    """Write a rest-pose picture (front, side, three-quarter) of the donor record the archive actually holds.

    The geometry is decoded from the written MOD and the colours from the written BC7 atlas, so the picture shows the
    candidate's own bytes in the native bind pose. It is not the game's shading, animation or camera.
    """
    model, index, atlas = _donor(archive, target)
    points, triangles = model.positions(index), mtf_author.mesh_triangles(model, index)
    _sheet([points], model.uvs(index), triangles, atlas, (0., -90., -30.), size, Path(png))
    return {'preview': str(png), 'model': target.models[0][0].rsplit('\\', 1)[-1], 'record': index,
            'vertices': len(points), 'triangles': len(triangles), 'views': ['front', 'side', 'three-quarter'],
            'shows': 'written MOD geometry and written BC7 atlas in the native bind pose; not game shading or motion'}


def posed_preview(original: bytes, candidate: bytes, png: Path, *, motion_entry: int, clip: int, frames,
                  target: EnemySet = EM1000, size: int = 320) -> dict:
    """Write the donor record under frames of one native clip (three-quarter and side view per frame).

    The existing comparison sampler (`mtf_motion.sample_compare`) evaluates the clip on the native and on the written
    model: forward kinematics and linear skinning on the CPU. No engine IK, physics, clip layering or shading, so the
    picture shows whether the surface follows the native joints, never what the game draws.
    """
    from . import mtf_motion

    entries, frames = mt_arc.parse(original).entries, [float(frame) for frame in frames]
    motion = zlib.decompress(entries[motion_entry].data) if 0 <= motion_entry < len(entries) else b''
    if motion[:4] != b'LMT\0':
        raise EnemyWriterError(f'entry {motion_entry} is not a native motion resource')
    model, index, atlas = _donor(candidate, target)
    records = model.meshes()
    sampled = mtf_motion.sample_compare(original, candidate, motion, animation_index=clip, frames=frames,
                                        model_name=target.models[0][0].rsplit('\\', 1)[-1], raw_fk=True)
    starts, cursor = {}, 0
    for i in sampled['candidate']['mesh_indices']:
        starts[i] = cursor
        cursor += records[i]['vertex_count']
    copies = [i for i in starts if records[i]['level_of_detail'] == ALL_LODS]
    count, poses, spread = records[index]['vertex_count'], [], 0.
    for frame in sampled['candidate']['frames']:
        positions = np.asarray(frame['positions'], float).reshape(-1, 3)
        poses.append(positions[starts[index]:starts[index] + count])
        spread = max([spread] + [float(np.abs(positions[starts[i]:starts[i] + count] - poses[-1]).max()) for i in copies])
    moved = max((joint['distance_cm'] for row in sampled['diagnostics']['joint_displacements']
                 for joint in row['joints']), default=0.)
    _sheet(poses, model.uvs(index), mtf_author.mesh_triangles(model, index), atlas, (-30., -90.), size, Path(png))
    return {'preview': str(png), 'motion_entry': motion_entry, 'motion': entries[motion_entry].name, 'clip': clip,
            'frames': frames, 'views': ['three-quarter', 'side'], 'evaluation_mode': sampled['evaluation_mode'],
            'skeleton_displacement_max_cm': moved, 'donor_copies': len(copies),
            'donor_copies_max_difference_cm': spread, 'limits': sampled['diagnostics']['limitations'],
            'shows': 'written donor record skinned on the CPU by one native clip; not the game pose, IK or shading'}


def main(argv=None) -> int:
    """CLI: --archive <original uEm10.arc> --source <sm64ds_mario.glb> --out <folder>
    [--sets em1000[,em1001]] [--pose ENTRY:CLIP:FRAME[,FRAME...]] [--secondary native] [--no-preview]"""
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Build the offline Mario-on-Majini uEm10.arc candidate')
    parser.add_argument('--archive', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--sets', default='em1000', help='em1000 (the v1 candidate) or em1000,em1001')
    parser.add_argument('--secondary', default='neutral', choices=('neutral', 'native'))
    parser.add_argument('--pose', help='also draw a native clip: LMT entry index, clip index, frames (259:3:0,30,60)')
    parser.add_argument('--no-preview', action='store_true')
    args = parser.parse_args(argv)
    out, archive = Path(args.out), Path(args.archive).read_bytes()
    output, receipt = build(archive, Path(args.source), sets=tuple(args.sets.split(',')), secondary=args.secondary)
    path = out / 'romfs' / ARCHIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)
    receipt['output'] = {'path': 'romfs/' + ARCHIVE_PATH, 'sha256': receipt['written_sha256'], 'bytes': len(output)}
    if not args.no_preview:
        receipt['preview'] = preview(output, out / 'preview.png') | {'preview': 'preview.png'}
    if args.pose:
        entry, clip, frames = args.pose.split(':')
        receipt['posed_preview'] = posed_preview(
            archive, output, out / 'preview-posed.png', motion_entry=int(entry), clip=int(clip),
            frames=[float(frame) for frame in frames.split(',')]) | {'preview': 'preview-posed.png'}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'archive': str(path), 'sha256': receipt['written_sha256'], 'receipt': str(out / 'receipt.json')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
