"""Unregistered, bounded player-slot writer: one library donor onto one RE5 Switch Mercenaries roster slot.

`re5_sonic_writer` is the measured Sonic-on-Chris experiment (source proportions, moved bind joints, scaled root motion).
This module is the generic counterpart for the whole cast pool and follows `re5_enemy_writer` instead:

* the donor is authored IN the slot's native bind pose with `re5_mesh_import.build_archive(pose_mode='native_segments')`,
  so every donor joint sits on its native bind joint and no bind joint, inverse bind or motion resource is edited. The
  weapon stays in the native hand, the feet on the native floor and the camera on the native head;
* each slot's role bones are measured on that slot's own skeleton (`measure_roles`) and accepted only when the bind-pose
  measurement and the RE5 animation ids name the same bones (`role_map`). The same ids sit at different bone indices in
  different costume models, so nothing is copied from one slot to another;
* a slot is a reviewed archive: its SHA-256, the exact entry indices of each body model it holds and the native material
  and textures that carry the donor atlas. An unknown archive is refused. A costume archive holds the costume's own body
  model beside a copy of the base body; which of the two the class draws was not determined offline, so both carry the
  donor;
* a donor is any library model the shared donor module resolves (`re5_donor_pool.resolve`): fifteen role joints of its
  own rig, held against its joints, skin and surface. An incomplete rig is refused with the reason;
* every donor is brought to the slot's native height with its soles on the floor (`native_height_scales`), unless its
  metadata says it is meant to be larger or smaller. The scales used are in the receipt.

Nothing is installed, launched or registered. A structurally valid archive is not a working character: every receipt
says `live_verified: False` until a round has been watched.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import (characters, mt_arc, mt_model, mtf_author, mtf_materials, mtf_mrl, mtf_retarget, mtf_secondary, mtf_tex,
               re5_donor_pool, re5_mesh_import)
from .re5_donor_pool import ROLES, Donor, DonorError
from .re5_enemy_writer import DONOR_FORMAT, DONOR_STRIDE, MASK_HASH, NORMAL_HASH, ROLE_ANIMATION_IDS

RECIPE_VERSION = 1
ARCHIVE_DIR = 'nativeNXx64/ImgNX/Archive'
#: Each role's next joint. Limbs and the spine stretch to the native segment lengths, so a part ends where the next one
#: starts; cross-sections, the head, the hands and the feet take the solved scales.
SEGMENTS = {'hip': 'chest', 'chest': 'head', 'l_upper': 'l_fore', 'l_fore': 'l_hand', 'r_upper': 'r_fore',
            'r_fore': 'r_hand', 'l_thigh': 'l_shin', 'l_shin': 'l_foot', 'r_thigh': 'r_shin', 'r_shin': 'r_foot'}
#: Measured on `uPl00ChrisNormal.arc` material 108 (`Gear_000_LOD0_M4...`), the one material a donor has been drawn with
#: in the game: render-state words +16..+28 and +32..+52 of its 72-byte descriptor, and the SHA-256 of its forty
#: commands (type, shader object, value; a texture command's value left out). 43 to 133 materials of every body model of
#: the six slots carry exactly this signature; they differ in their constants, their textures and a per-model index.
STANDARD_STATE = '84d1b262b79113b8c4f18c100000808c0000803f0000803f0000803f0000803f'
STANDARD_COMMANDS_SHA256 = '47ec621673445a52b52ece33cc77b7fb2bd569ee26d95c41772c0e95840586e9'
ALL_LODS = 0xFF
SPINE_ANIMATION_ID = 1          # the lower spine joint just above the pelvis: where a waist-jointed donor torso goes


class CastWriterError(ValueError):
    """The archive is not a reviewed slot, or the donor cannot stand on it; the message says which and why."""


@dataclass(frozen=True)
class SlotModel:
    """One body model inside a slot archive, by explicit entry index, and the native material that carries the atlas."""
    name: str                       # exact entry name of the MOD and of its MRL
    mod: int
    mrl: int
    material: str                   # exact native material name
    albedo: tuple[int, str]         # BC7 entry that receives the donor atlas
    normal: tuple[int, str]         # that material's BC5 normal map
    mask: tuple[int, str]           # that material's BC4 mask map
    drawn: str                      # why this model is written: 'body', 'costume body' or 'base body'

    @property
    def short(self) -> str:
        return self.name.rsplit('\\', 1)[-1]


@dataclass(frozen=True)
class Slot:
    """One Mercenaries roster slot: the archive the game loads for it and every body model that archive holds."""
    key: str
    label: str                      # the roster label the bot uses (`re5_switch.CHARACTERS`)
    player_class: str               # the game's class name, which is also the archive's stem
    sha256: str
    entries: int
    models: tuple[SlotModel, ...]
    costume: str                    # what the body model was seen to be when its native bytes were decoded

    @property
    def archive(self) -> str:
        return f'{ARCHIVE_DIR}/{self.player_class}.arc'


_PL00, _PL01 = 'pawn\\pl\\pl00\\model\\', 'pawn\\pl\\pl01\\model\\'
_PL10, _PL11 = 'pawn\\pl\\pl10\\model\\', 'pawn\\pl\\pl11\\model\\'
_PL12, _PL13 = 'pawn\\pl\\pl12\\model\\', 'pawn\\pl\\pl13\\model\\'
_GEAR = 'Gear_000_LOD0_M4.polymsh.cls.otherPolygons.XfB_N__E8'
_SKINS = 'models.skins_000_M3_LOD0.polymsh.cls.otherPolygons.XfB_N__E'


def _chris_base(mod: int, mrl: int, drawn: str) -> SlotModel:
    return SlotModel(_PL00 + 'pl0000', mod, mrl, _GEAR, (34, _PL00 + 'pl00Gear_BM'), (36, _PL00 + 'pl00Gear_NM'),
                     (35, _PL00 + 'pl00Gear_MM'), drawn)


def _sheva_base(mod: int, mrl: int, drawn: str) -> SlotModel:
    return SlotModel(_PL01 + 'pl0100', mod, mrl, _SKINS, (31, _PL01 + 'pl0100_05Arm_BM'),
                     (33, _PL01 + 'pl0100_05Arm_NM'), (32, _PL01 + 'pl0100_05Arm_MM'), drawn)


#: Reviewed 2026-11-09 against the extracted RE5 Switch RomFS (title 010018100CD46000). The six classes are the ones the
#: pinned player vtables name (`mercs/native/re5_ebffdb22/vtables.py`); each archive is named after its class. Which
#: costume an archive holds was read from its own model: the body was decoded and drawn with its native textures.
#: A costume archive holds the base body `pl0000` / `pl0100` byte for byte beside the costume's model.
#:
#: The atlas material of each model is the native material with the measured standard shader (`STANDARD_STATE`,
#: `STANDARD_COMMANDS_SHA256`) and its own BC7 albedo, BC5 normal and BC4 mask whose shader constants are nearest to
#: Chris's Gear material, the larger albedo and then the larger near-LOD use breaking ties. The base Chris body is
#: pinned to the Gear material itself: it is the one material a donor has been drawn with in the game.
SLOTS = {slot.key: slot for slot in (
    Slot('chris_bsaa', 'Chris (BSAA)', 'uPl00ChrisNormal',
         '8ab0dc181d1f6ec155e193c5820d1756d877acf711424863b16f7850b592f6c8', 327,
         (_chris_base(97, 87, 'body'),), 'BSAA tactical gear'),
    Slot('chris_safari', 'Chris (Safari)', 'uPl00ChrisCos1',
         'fa3f0a85ca2c8c99546161871536f67e251108e6509dd2edce61dd9e40d53676', 365,
         (SlotModel(_PL10 + 'pl0000', 140, 129, 'Knife.tuka_004_LOD0_M4.polymsh.cls.otherPolygons.XfB_N__E6',
                    (118, _PL10 + 'pl1000_17Knife_BM'), (117, _PL10 + 'pl1000_17Knife_NM'),
                    (119, _PL10 + 'pl1000_17Knife_MM'), 'costume body'),
          _chris_base(134, 123, 'base body')), 'open short-sleeved patterned shirt over a black top'),
    Slot('chris_stars', 'Chris (STARS)', 'uPl00ChrisCos2',
         '4df4a987b59761cba76025c72b4129c05c78fcc1555926714ff769beb88e7e7b', 365,
         (SlotModel(_PL11 + 'pl1100', 140, 129, 'Pl0001Head.Head_002_LOD0_M7.polymsh.cls.otherPolygons.XfB_N__E2',
                    (85, _PL11 + 'pl00Face_BM'), (84, _PL11 + 'pl00Face_NM'), (86, _PL11 + 'pl00Face_MM'),
                    'costume body'),
          _chris_base(134, 123, 'base body')), 'green S.T.A.R.S. vest over a white shirt'),
    Slot('sheva_bsaa', 'Sheva (BSAA)', 'uPl01ShebaNormal',
         '77e9ede6a6bf84d74fa487acaca77624e503377c2910d1af62dda0b7f914957e', 332,
         (_sheva_base(92, 78, 'body'),), 'purple top, BSAA gear'),
    Slot('sheva_clubbin', 'Sheva (Clubbin)', 'uPl01ShebaCos2',
         'f63256a6e61a5b09bd5a527e08a8da3eff532c0699185bf181a8666f0e2b0c38', 362,
         (SlotModel(_PL13 + 'pl0100', 126, 111, 'body.skins_000_LOD0.polymsh.cls.left_M10.XfB_N__E6',
                    (86, _PL13 + 'pl0100_05Arm_BM'), (85, _PL13 + 'pl0100_05Arm_NM'), (87, _PL13 + 'pl0100_05Arm_MM'),
                    'costume body'),
          _sheva_base(121, 106, 'base body')), 'gold halter top and miniskirt, bob haircut'),
    Slot('sheva_tribal', 'Sheva (Tribal)', 'uPl01ShebaCos1',
         'd550005ea851af8da4398dc56ba87dd89697ea943fc25819ce0150bf4a184a68', 365,
         (SlotModel(_PL12 + 'pl1200', 129, 114, 'models.hand_003_M3_LOD0.polymsh.cls.otherPolygons.XfB_N__E3',
                    (87, _PL12 + 'pl1200_13hand_BM'), (86, _PL12 + 'pl1200_13hand_NM'), (88, _PL12 + 'pl1200_13hand_MM'),
                    'costume body'),
          _sheva_base(124, 109, 'base body')), 'leopard-print top, red loincloth, tooth necklace'),
)}


def slot_for(archive: bytes) -> Slot:
    """The reviewed slot whose archive this is, by SHA-256; anything else is refused."""
    digest = hashlib.sha256(archive).hexdigest()
    for slot in SLOTS.values():
        if slot.sha256 == digest:
            return slot
    raise CastWriterError(f'unknown slot: archive {digest[:16]}... is not one of the reviewed original Mercenaries '
                          f'archives ({", ".join(slot.player_class for slot in SLOTS.values())})')


# --- the slot's skeleton --------------------------------------------------------------------------------------------

def measure_roles(model: mt_model.ModFile) -> tuple[dict[str, int], dict]:
    """{role: bone index} read from the bind pose alone: the hierarchy and where each joint sits.

    A player skeleton carries face, hair, gear and twist bones beside the body, so a body chain is followed by where it
    leads, never by a child count: the root's two trunks are the pelvis (reaches the floor) and the spine (reaches the
    top); a leg is a pelvis branch that reaches the floor; the chest is the first spine joint with a far-reaching branch
    on each side; the neck is the chest's midline branch that reaches the top; along an arm the next joint is the child
    that reaches farthest out, along a leg the child that reaches lowest. A hand is the last joint stacked on the wrist.
    Left is the +X side when the toes point to +Z. No animation id is consulted.
    """
    table = model.bone_table()
    parents = [int(p) for p in table.get('parents', [])]
    points = {i: np.array((x, y, z), float) for i, x, y, z in model.bone_world()}
    count = len(parents)
    if not table.get('consistent') or not count or len(points) != count:
        raise CastWriterError('the slot skeleton is incomplete')
    roots = [i for i, parent in enumerate(parents) if parent == 255]
    if len(roots) != 1 or any(parent != 255 and parent >= i for i, parent in enumerate(parents)):
        raise CastWriterError('the slot skeleton needs one root and parents stored before their children')
    root = roots[0]
    centre = points[root][0]
    children = {i: [] for i in range(count)}
    depth = [1] * count
    low, high = [points[i][1] for i in range(count)], [points[i][1] for i in range(count)]
    reach = [abs(points[i][0] - centre) for i in range(count)]
    for i in range(count - 1, -1, -1):
        parent = parents[i]
        if parent != 255:
            children[parent].insert(0, i)
            depth[parent] = max(depth[parent], depth[i] + 1)
            low[parent], high[parent] = min(low[parent], low[i]), max(high[parent], high[i])
            reach[parent] = max(reach[parent], reach[i])

    def follow(bone: int, score, what: str) -> int:
        """The one child that leads on: the best score, and no other child within a millimetre of it."""
        if not children[bone]:
            raise CastWriterError(f'the {what} chain ends at bone {bone}')
        ranked = sorted(children[bone], key=score, reverse=True)
        if len(ranked) > 1 and score(ranked[0]) - score(ranked[1]) < .1:
            raise CastWriterError(f'the {what} chain is ambiguous at bone {bone}')
        return ranked[0]

    trunks = [c for c in children[root] if depth[c] >= 3]
    if len(trunks) != 2:
        raise CastWriterError('the root needs exactly a pelvis trunk and a spine trunk')
    pelvis, spine = min(trunks, key=lambda c: low[c]), max(trunks, key=lambda c: high[c])
    if pelvis == spine:
        raise CastWriterError('the pelvis and spine trunks cannot be told apart')
    floor = min(low)
    legs = [c for c in children[pelvis] if depth[c] >= 3 and low[c] - floor < .25 * (points[pelvis][1] - floor)]
    span = max(reach)
    if span < 1.:
        raise CastWriterError('the skeleton has no lateral extent to tell its arms by')
    chest = spine
    while True:
        arms = [c for c in children[chest] if reach[c] >= .5 * span and abs(points[c][0] - centre) >= 1.]
        if len(arms) >= 2:
            break
        chest = follow(chest, lambda c: high[c], 'spine')
    necks = [c for c in children[chest] if c not in arms and abs(points[c][0] - centre) < 1.]
    if len(legs) != 2 or len(arms) != 2 or not necks:
        raise CastWriterError('the skeleton is not two legs, two arms and a neck')
    neck = max(necks, key=lambda c: high[c])
    if sum(high[c] > high[neck] - .1 for c in necks) != 1:
        raise CastWriterError('the neck cannot be told from another midline branch of the chest')
    chains = {}
    for thigh in legs:
        shin = follow(thigh, lambda c: -low[c], 'leg')
        foot = follow(shin, lambda c: -low[c], 'leg')
        chains[thigh] = (thigh, shin, foot, follow(foot, lambda c: -low[c], 'toe'))
    forward = sum(points[toe][2] - points[foot][2] for _, _, foot, toe in chains.values())
    if abs(forward) < 1e-6:
        raise CastWriterError('the toes do not show which way the skeleton faces')
    left = 1. if forward > 0 else -1.

    def side(bone: int) -> str:
        offset = (points[bone][0] - centre) * left
        if abs(offset) < 1e-6:
            raise CastWriterError(f'bone {bone} is on the midline, not on a side')
        return 'l' if offset > 0 else 'r'

    roles = {'hip': pelvis, 'chest': chest, 'head': follow(neck, lambda c: high[c], 'neck')}
    extra = {'root': root, 'spine': spine, 'neck': neck, 'facing': '+Z' if forward > 0 else '-Z',
             'left_side': '+X' if left > 0 else '-X'}
    for thigh, shin, foot, toe in chains.values():
        s = side(thigh)
        if not points[thigh][1] > points[shin][1] > points[foot][1]:
            raise CastWriterError('a leg chain does not descend thigh, shin, foot')
        roles.update({f'{s}_thigh': thigh, f'{s}_shin': shin, f'{s}_foot': foot})
        extra[f'{s}_toe'] = toe
    for clavicle in arms:
        upper = follow(clavicle, lambda c: reach[c], 'arm')
        fore = follow(upper, lambda c: reach[c], 'arm')
        hand = follow(fore, lambda c: reach[c], 'arm')
        while True:                       # the wrist twist and the hand share one position; the hand is the last
            stacked = [c for c in children[hand] if np.linalg.norm(points[c] - points[hand]) < 1e-3]
            if len(stacked) != 1:
                break
            hand = stacked[0]
        s = side(clavicle)
        out = [abs(points[b][0] - centre) for b in (upper, fore, hand)]
        if not out[0] < out[1] < out[2]:
            raise CastWriterError('an arm chain does not run outward upper, fore, hand')
        roles.update({f'{s}_upper': upper, f'{s}_fore': fore, f'{s}_hand': hand})
        extra[f'{s}_clavicle'] = clavicle
    if len(roles) != 15 or len(set(roles.values())) != 15:
        raise CastWriterError('the skeleton does not give fifteen distinct role bones')
    if not points[roles['head']][1] > points[chest][1] > points[roles['l_thigh']][1]:
        raise CastWriterError('the head, chest and legs are not stacked upward')
    return roles, extra


def roles_by_animation_id(model: mt_model.ModFile) -> dict[str, int]:
    """{role: bone index} through the RE5 animation ids; each id must name exactly one bone."""
    ids = [int(v) for v in model.bone_table().get('anim_map', [])]
    roles = {}
    for role, animation in ROLE_ANIMATION_IDS.items():
        if ids.count(animation) != 1:
            raise CastWriterError(f'animation id {animation} ({role}) does not name exactly one bone')
        roles[role] = ids.index(animation)
    return roles


def role_map(model: mt_model.ModFile) -> tuple[dict[str, int], dict]:
    """The slot's role map, accepted only when the bind-pose measurement and the animation ids name the same bones."""
    measured, extra = measure_roles(model)
    named = roles_by_animation_id(model)
    if measured != named:
        wrong = sorted(role for role in named if measured.get(role) != named[role])
        raise CastWriterError(f'the bind pose and the animation ids disagree on {wrong}')
    if int(model.bone_table()['anim_map'][extra['spine']]) != SPINE_ANIMATION_ID:
        raise CastWriterError('the bind pose and the animation ids disagree on the lower spine')
    points = {i: (x, y, z) for i, x, y, z in model.bone_world()}
    return measured, {'method': 'bind-pose hierarchy and joint positions, cross-checked against RE5 animation ids',
                      'animation_ids': {role: ROLE_ANIMATION_IDS[role] for role in measured},
                      'bind_position': {role: [round(float(v), 4) for v in points[bone]] for role, bone in measured.items()},
                      'skeleton': extra, 'bone_count': len(points)}


# --- the donor's rig ------------------------------------------------------------------------------------------------

def donor_rig(gltf: dict, world, vertices: list[dict], triangles: list[tuple], roles: dict[str, str]) -> dict:
    """The shared rig check (`re5_donor_pool.rig_check`); an incomplete rig is refused with the reason."""
    try:
        return re5_donor_pool.rig_check(gltf, world, vertices, triangles, roles)
    except ValueError as exc:
        raise CastWriterError(str(exc)) from exc


# --- the slot's material --------------------------------------------------------------------------------------------

def material_signature(mrl: bytes, record_index: int) -> dict:
    """The render states, commands and constants of one MRL material record (the measured 72-byte descriptor layout)."""
    table = struct.unpack_from('<Q', mrl, 32)[0]
    descriptor = mrl[table + 72 * record_index:table + 72 * record_index + 72]
    if len(descriptor) != 72:
        raise CastWriterError('the material record lies outside the MRL')
    size = struct.unpack_from('<I', descriptor, 12)[0]
    word = struct.unpack_from('<I', descriptor, 28)[0]
    commands, start = word & 0xFFF, struct.unpack_from('<Q', descriptor, 56)[0]
    if start + size > len(mrl) or 24 * commands > size:
        raise CastWriterError('the material command buffer lies outside the MRL')
    rows = []
    for i in range(commands):
        kind, _, value, shader = struct.unpack_from('<IIQQ', mrl, start + 24 * i)
        rows.append((kind & 15, shader, None if kind & 15 == 3 else value))
    return {'state': (descriptor[16:28] + descriptor[32:52]).hex(),
            'commands_sha256': hashlib.sha256(repr(rows).encode()).hexdigest(), 'commands': commands,
            'index_word': word >> 12, 'constants': np.frombuffer(mrl[start + 24 * commands:start + size], '<f4').copy()}


def _entry(parsed: mt_arc.Arc, index: int, name: str, magic: bytes) -> bytes:
    if not 0 <= index < len(parsed.entries) or parsed.entries[index].name != name:
        raise CastWriterError(f'entry {index} is not the reviewed {name!r}')
    try:
        raw = zlib.decompress(parsed.entries[index].data)
    except zlib.error as exc:
        raise CastWriterError(f'entry {index} is not a zlib-wrapped resource') from exc
    if raw[:4] != magic:
        raise CastWriterError(f'entry {index} is not the reviewed {magic[:3].decode()} resource')
    return raw


def _material(mrl: bytes, model: mt_model.ModFile, target: SlotModel) -> tuple[int, dict]:
    """The reviewed native material, by exact name: the measured standard shader, bound to the reviewed textures."""
    rows = [row for row in mtf_mrl.inspect_bindings(mrl, model) if row['name'] == target.material]
    if len(rows) != 1:
        raise CastWriterError(f'{target.short} does not have exactly one material named {target.material!r}')
    row = rows[0]
    signature = material_signature(mrl, row['index'])
    if (signature['state'], signature['commands_sha256']) != (STANDARD_STATE, STANDARD_COMMANDS_SHA256):
        raise CastWriterError(f'{target.material!r} is not the measured standard material a donor has been drawn with')
    paths = {b['shader_hash']: b['path'] for b in row['bindings']}
    if (paths.get(mtf_mrl.ALBEDO_HASH), paths.get(NORMAL_HASH), paths.get(MASK_HASH)) != (
            target.albedo[1], target.normal[1], target.mask[1]):
        raise CastWriterError(f'{target.material!r} does not bind the reviewed albedo, normal and mask textures')
    return row['mod_index'], {'index': row['mod_index'], 'name': row['name'], 'albedo': target.albedo[1],
                              'normal': target.normal[1], 'mask': target.mask[1],
                              'constants_sha256': hashlib.sha256(signature['constants'].tobytes()).hexdigest()}


# --- the slot's model -----------------------------------------------------------------------------------------------

def _group_zero(model: mt_model.ModFile) -> int:
    """Byte offset of option group 0's 32-byte table entry: the always-drawn player body."""
    header = model.header()
    start, end = header['offsets']['groups'], header['offsets']['materials']
    if end - start != 32 * header['group_count'] or not header['group_count']:
        raise CastWriterError('the option-group table does not match its count')
    hits = [start + 32 * i for i in range(header['group_count'])
            if struct.unpack_from('<I', model.raw, start + 32 * i)[0] == 0]
    if len(hits) != 1:
        raise CastWriterError('the model has no single option group 0 to carry a player body')
    return hits[0]


def _template(model: mt_model.ModFile) -> int:
    """The first drawn four-weight record of option group 0; its group and its opaque bytes carry over."""
    records = model.meshes()
    if sorted(record['mesh_id'] for record in records) != list(range(1, len(records) + 1)):
        raise CastWriterError('native mesh ids are not the measured permutation of 1..count')
    for index, record in enumerate(records):
        if (record['group_index'], record['mesh_type'], record['vertex_format'], record['render_mode']) == (
                0, 0xFFFF, DONOR_FORMAT, 4):
            return index
    raise CastWriterError('option group 0 has no drawn four-weight record to use as a template')


def _local_sphere(model: mt_model.ModFile, points) -> tuple[float, float, float, float]:
    """Centre and radius around `points` in root bone 0's bind frame, where the native group spheres are kept."""
    local = np.asarray(mtf_author.bone_local_points(model, 0, [tuple(p) for p in points]), float)
    centre = (local.min(0) + local.max(0)) / 2
    return (*map(float, centre), float(np.linalg.norm(local - centre, axis=1).max()))


def finish(native: mt_model.ModFile, donor_raw: bytes) -> bytes:
    """The one-mesh donor as a player body: mesh id 1 and option group 0's sphere drawn around the donor.

    A native mesh table numbers its records 1..count, so the only record of a one-mesh model is 1 (the id the Sonic
    candidate was drawn with). Group 0's native sphere is the Chris or Sheva body; a donor's head, hair or quills reach
    beyond it, so it is rewritten around the donor, as the Sonic recipe does.
    """
    model = mt_model.parse_mod(donor_raw)
    header = model.header()
    if header['mesh_count'] != 1 or len(model.meshes()) != 1 or model.meshes()[0]['group_index'] != 0:
        raise CastWriterError('the fitted donor is not one record of option group 0')
    data = bytearray(donor_raw)
    struct.pack_into('<H', data, header['offsets']['meshes'] + 0x26, 1)
    struct.pack_into('<4f', data, _group_zero(model) + 16, *_local_sphere(native, model.positions(0)))
    return bytes(data)


def native_height_scales(vertices: list[dict], gltf: dict, world, roles: dict[str, str], target_roles: dict[str, int],
                         target_points: dict[int, tuple], segments: dict[str, str], *, top: float,
                         factor: float = 1.) -> tuple[dict, dict]:
    """Per-role scales that bring the fitted donor to the slot's native height with its soles on the floor.

    Limbs and spine take the native segment lengths whatever the scale, so the scale only sizes cross-sections and the
    parts beyond the last joints. One body scale is solved so the top of the fitted head reaches `top * factor` (the
    native model's top; `factor` is 1 unless the donor's metadata says it is meant to be larger or smaller): every
    fitted height is linear in that scale, so two trial fits give the exact answer. With that scale the soles would
    hang above or below the floor by however the donor's ankle height differs from the native one, so each foot keeps
    the body scale across and takes its own scale upward: the one that lands its lowest vertex on model y 0.
    """
    names = [node.get('name') for node in gltf.get('nodes') or []]
    pairs = {role: (names.index(roles[role]), target_roles[role]) for role in ROLES}
    parents = {child: i for i, node in enumerate(gltf.get('nodes') or []) for child in node.get('children', [])}
    source_points = {i: tuple(map(float, np.asarray(matrix, float)[:3, 3])) for i, matrix in enumerate(world)}

    def heights(scale):
        fitted, _ = mtf_retarget.transfer(vertices, source_points, parents, target_points, pairs, segments, scale=scale)
        return np.asarray([v['position'][1] for v in fitted], float), [v['bone'] for v in fitted]

    if not np.isfinite(factor) or not .5 <= factor <= 1.5:
        raise CastWriterError('a donor height factor lies between 0.5 and 1.5')
    one, bones = heights(1.)
    two, _ = heights(2.)
    slope = two - one
    # The head decides the height: it hangs on the last spine joint, so only its vertices rise with the scale without
    # limit. A part stretched along a native segment (a mane bound to the chest) keeps its length and may stand higher.
    head = np.asarray([bone == target_roles['head'] for bone in bones]) & (slope > 1e-9)
    base, target = one - slope, float(top) * float(factor)
    body = float(np.min((target - base[head]) / slope[head])) if head.any() else float('nan')
    if not np.isfinite(body) or body <= 0:
        raise CastWriterError('the donor cannot be brought to the native height of the slot: its head joint already '
                              'stands at that height or carries no surface above it')
    if not .1 <= body * float(np.ptp([v['position'][1] for v in vertices])) / target <= 3.:
        raise CastWriterError('the native height rule gives this donor a body far from the native size; its head joint '
                              'is not at the base of its head')
    level, _ = heights(body)
    scales, feet = {role: body for role in ROLES}, {}
    for role in ('l_foot', 'r_foot'):
        ankle = float(target_points[target_roles[role]][1])
        own = np.asarray([bone == target_roles[role] for bone in bones])
        drop = ankle - float(level[own].min()) if own.any() else 0.
        if drop <= 1e-6 or ankle <= 1e-6:
            raise CastWriterError('incomplete rig: the soles must sit below the ankles to stand the donor on the floor')
        feet[role] = body * ankle / drop
        scales[role] = (body, feet[role], body)
    return scales, {'rule': 'body scale solved so the fitted top reaches the native top; each foot scaled upward so '
                            'its sole lands on model y 0', 'body_scale': body, 'feet_vertical_scale': feet,
                    'height_factor': float(factor), 'native_top': float(top), 'target_top': target}


def _segments(segments: dict[str, str], joints: dict[str, tuple], height: float) -> dict[str, str]:
    """The segments to stretch, each checked to have a length in the donor; a segment without one is refused."""
    for start, end in segments.items():
        if start not in joints or end not in joints:
            raise CastWriterError(f'segment {start} -> {end} does not join two of the fifteen roles')
        if float(np.linalg.norm(np.subtract(joints[end], joints[start]))) < 1e-4 * height:
            raise CastWriterError(f'incomplete rig: {start} and {end} share one position, the part has no length')
    return dict(segments)


def fits(archive: bytes, source: Path, roles: dict[str, str], *, slot: Slot | None = None,
         height_factor: float = 1.) -> dict:
    """Whether `author` would accept this donor on this slot, without encoding or writing anything.

    The slot's skeleton and material, the donor surface at the slot's atlas size, the rig and the height rule are
    checked for every body model; a refusal raises exactly as `author` would. The body scales come back.
    """
    slot = slot or slot_for(archive)
    source, roles = Path(source), dict(roles)
    parsed = mt_arc.parse(archive)
    if len(parsed.entries) != slot.entries or not slot.models:
        raise CastWriterError(f'{slot.player_class} does not have the reviewed {slot.entries} entries')
    gltf, _, _, world = characters._load(source)
    scales = {}
    for target in slot.models:
        native = mt_model.parse_mod(_entry(parsed, target.mod, target.name, b'MOD\0'))
        target_roles, evidence = role_map(native)
        _material(_entry(parsed, target.mrl, target.name, b'MRL\0'), native, target)
        _template(native)
        _group_zero(native)
        surface = mtf_tex.parse(_entry(parsed, *target.albedo, b'TEX\0'))
        try:
            vertices, triangles, _, _ = mtf_materials.source_mesh(
                source, atlas_size=(surface.width, surface.height), strict_samplers='in_range')
        except mtf_materials.MaterialError as exc:
            raise CastWriterError(f'the donor surface does not fit the {surface.width}x{surface.height} atlas of '
                                  f'{target.short}: {exc}') from exc
        rig = donor_rig(gltf, world, vertices, triangles, roles)
        fit_roles, fit_segments = dict(target_roles), dict(SEGMENTS)
        if rig.get('torso') == 'waist':
            fit_roles['chest'] = evidence['skeleton']['spine']
            fit_segments.pop('hip', None)
        joints = {role: tuple(rig['role_position'][role]) for role in ROLES}
        scales[f'{target.mod}:{target.name}'] = native_height_scales(
            vertices, gltf, world, roles, fit_roles, {i: (x, y, z) for i, x, y, z in native.bone_world()},
            _segments(fit_segments, joints, rig['height']), top=native.bounds()['max']['y'], factor=height_factor)[1]
    return scales


def author(archive: bytes, source: Path, roles: dict[str, str], *, slot: Slot | None = None,
           height_factor: float = 1., scale: float | None = None, segments: dict[str, str] | None = None,
           secondary: str = 'neutral'):
    """Return (archive, receipt) with every body model of the slot carrying the donor; the donor is not hash-checked here.

    `archive` must be a reviewed slot (`SLOTS`, found by SHA-256) unless `slot` names one explicitly. `roles` is the
    donor's role profile, {role: joint name}. Limbs and spine always stretch to the native segment lengths; the scale
    of everything else is solved so the donor stands at the slot's native height times `height_factor` with its soles
    on the floor (`native_height_scales`). `scale` replaces that rule with one uniform number.
    `secondary='neutral'` flattens the atlas material's normal map and zeroes its mask (their native detail would be
    sampled through unrelated atlas UVs); `'native'` leaves both maps as shipped.
    """
    if secondary not in ('neutral', 'native'):
        raise CastWriterError("secondary maps are either 'neutral' or 'native'")
    slot = slot or slot_for(archive)
    source, roles, segments = Path(source), dict(roles), dict(SEGMENTS if segments is None else segments)
    parsed = mt_arc.parse(archive)
    if len(parsed.entries) != slot.entries or not slot.models:
        raise CastWriterError(f'{slot.player_class} does not have the reviewed {slot.entries} entries')
    indices = [i for m in slot.models for i in (m.mod, m.mrl, m.albedo[0], m.normal[0], m.mask[0])]
    if len(set(indices)) != len(indices):
        raise CastWriterError('the reviewed entry indices of a slot must be distinct')
    gltf, _, _, world = characters._load(source)
    payloads: dict[int, bytes] = {}
    models, rig, fit = {}, None, None
    for target in slot.models:
        native_raw = _entry(parsed, target.mod, target.name, b'MOD\0')
        mrl = _entry(parsed, target.mrl, target.name, b'MRL\0')
        texture = _entry(parsed, *target.albedo, b'TEX\0')
        normal, mask = _entry(parsed, *target.normal, b'TEX\0'), _entry(parsed, *target.mask, b'TEX\0')
        native = mt_model.parse_mod(native_raw)
        target_roles, evidence = role_map(native)
        material_index, material = _material(mrl, native, target)
        template = _template(native)
        _group_zero(native)
        surface = mtf_tex.parse(texture)
        try:
            vertices, triangles, _, appearance = mtf_materials.source_mesh(
                source, atlas_size=(surface.width, surface.height), strict_samplers='in_range')
        except mtf_materials.MaterialError as exc:
            raise CastWriterError(f'the donor surface does not fit the {surface.width}x{surface.height} atlas of '
                                  f'{target.short}: {exc}') from exc
        measured_rig = donor_rig(gltf, world, vertices, triangles, roles)
        rig = rig or measured_rig
        joints = {role: tuple(measured_rig['role_position'][role]) for role in ROLES}
        # A donor whose torso hangs on one joint at its waist follows the native lower spine instead of the chest and
        # is stretched from there to the head; a donor with a spine of its own follows hip, chest and head.
        fit_roles, fit_segments = dict(target_roles), dict(segments)
        if measured_rig.get('torso') == 'waist':
            fit_roles['chest'] = evidence['skeleton']['spine']
            fit_segments.pop('hip', None)
        target_roles = fit_roles
        fitted_segments = _segments(fit_segments, joints, measured_rig['height'])
        target_points = {i: (x, y, z) for i, x, y, z in native.bone_world()}
        if scale is not None:
            used, rule = float(scale), {'rule': 'one uniform scale given by the caller', 'body_scale': float(scale)}
        else:
            used, rule = native_height_scales(vertices, gltf, world, roles, target_roles, target_points, fitted_segments,
                                              top=native.bounds()['max']['y'], factor=height_factor)
        try:
            result, donor_raw, _, imported = re5_mesh_import.build_archive(
                archive, source, model_name=target.short, source_roles=roles, target_roles=target_roles,
                segments=fitted_segments, scale=used, material_index=material_index, template_index=template,
                pose_mode='native_segments', model_entry=target.mod, mrl_entry=target.mrl, keep_source_normals=True,
                reverse_winding=measured_rig['winding'] == 'cw', samplers_in_range=True)
        except (mtf_author.AuthorError, mt_model.ModelError, struct.error) as exc:
            raise CastWriterError(f'the fitted donor cannot be written as one native mesh record: {exc}') from exc
        after = mt_arc.parse(result)
        changed = {i for i, (a, b) in enumerate(zip(parsed.entries, after.entries)) if a.data != b.data}
        if (imported['changed_entry_indices'] != [target.mod, target.albedo[0]]
                or len(after.entries) != len(parsed.entries) or not changed <= {target.mod, target.albedo[0]}
                or zlib.decompress(after.entries[target.mrl].data) != mrl):
            raise CastWriterError(f'the mesh import did not address the reviewed entries of {target.name!r}')
        written = finish(native, donor_raw)
        payloads[target.mod] = written
        payloads[target.albedo[0]] = zlib.decompress(after.entries[target.albedo[0]].data)
        if secondary == 'neutral':
            payloads[target.normal[0]] = mtf_secondary.constant_channels(normal, (128, 128))
            payloads[target.mask[0]] = mtf_secondary.constant_channels(mask, (0,))
        bounds = imported['bounds']
        this_fit = {'pose_mode': imported['pose_mode'], 'scale': rule,
                    'scale_source': 'caller' if scale is not None else 'native height, soles on the floor',
                    'segments': fitted_segments, 'bounds': bounds, 'native_bounds': imported['original_bounds'],
                    'top': bounds['max']['y'], 'floor': bounds['min']['y'],
                    'height': bounds['max']['y'] - bounds['min']['y'], 'native_top': imported['original_bounds']['max']['y'],
                    'native_height': imported['original_bounds']['max']['y'] - imported['original_bounds']['min']['y']}
        fit = fit or this_fit
        model = mt_model.parse_mod(written)
        models[f'{target.mod}:{target.name}'] = {
            'drawn': target.drawn, 'mod_entry': target.mod, 'mrl_entry': target.mrl, 'bone_count': evidence['bone_count'],
            'roles': target_roles, 'bind_position': evidence['bind_position'], 'skeleton': evidence['skeleton'],
            'torso': 'the donor torso hangs on one waist joint: it follows the native lower spine (animation id 1)'
                     if measured_rig.get('torso') == 'waist' else 'the donor has its own spine: hip, chest and head',
            'material': material, 'template_record': template, 'atlas_size': [surface.width, surface.height],
            'atlas_source': appearance, 'vertices': imported['vertices'], 'triangles': imported['triangles'],
            'envelope_count': model.header()['weight_bound_count'], 'fit': this_fit,
            'position_roundtrip_max_error': imported['position_roundtrip_max_error'],
            'native_records_replaced': len(native.meshes()), 'native_sha256': hashlib.sha256(native_raw).hexdigest(),
            'sha256': hashlib.sha256(written).hexdigest(), 'bytes_before': len(native_raw), 'bytes_after': len(written)}
    output = archive
    for index in sorted(payloads):                 # explicit index, never a name: MOD and MRL share names
        output = mtf_author.replace_archive_model(output, index, payloads[index])
    checks = verify(archive, output, slot, secondary=secondary)
    final = mt_arc.parse(output)
    one = next(iter(models.values()))
    receipt = {
        'recipe': 're5_cast_writer', 'recipe_version': RECIPE_VERSION,
        'slot': {'key': slot.key, 'label': slot.label, 'player_class': slot.player_class, 'archive': slot.archive,
                 'costume_seen_in_native_model': slot.costume},
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'target_archive_sha256': hashlib.sha256(archive).hexdigest(),
        'written_sha256': hashlib.sha256(output).hexdigest(), 'written_bytes': len(output),
        'entries': len(final.entries),
        'entries_replaced': [{'index': index, 'name': final.entries[index].name,
                              'kind': payloads[index][:3].decode('ascii'),
                              'bytes_before': parsed.entries[index].tag & 0xFFFFFF, 'bytes_after': len(payloads[index]),
                              'sha256': hashlib.sha256(payloads[index]).hexdigest()} for index in sorted(payloads)],
        'role_map': {'method': 'bind-pose hierarchy and joint positions, cross-checked against RE5 animation ids',
                     'source_roles': roles, 'animation_ids': dict(ROLE_ANIMATION_IDS),
                     'bones': {key: row['roles'] for key, row in models.items()}},
        'donor_rig': rig,
        'fit': fit | {'bind_joints_moved': False, 'native_motion_edited': False},
        'models': models,
        'counts': {'vertices': one['vertices'], 'triangles': one['triangles'], 'envelopes': one['envelope_count'],
                   'models_written': len(models),
                   'native_records_replaced': sum(row['native_records_replaced'] for row in models.values())},
        'appearance': {'secondary_maps': secondary, 'mrl_entries_changed': False,
                       'normals': 'the donor\'s own, carried through the fit; faceted where the donor has none',
                       'winding_reversed': rig['winding'] == 'cw',
                       'shared_texture_note': 'other models of this archive that sample the atlas, normal or mask '
                                              'entries are not replaced and would show the edited maps if drawn'},
        'checks': checks, 'live_verified': False, 'gameplay_verified': False, 'writer_registered': False}
    return output, receipt


# --- verification ---------------------------------------------------------------------------------------------------

def _check_model(native_raw: bytes, raw: bytes, target: SlotModel, material_index: int, roles: dict[str, int]) -> dict:
    """Re-parse one written model against its native original; every measured format rule must hold."""
    def need(condition, message):
        if not condition:
            raise CastWriterError(f'written model check failed ({target.short}): {message}')

    native, model = mt_model.parse_mod(native_raw), mt_model.parse_mod(raw)
    before, header = native.header(), model.header()
    old, new = before['offsets'], header['offsets']
    records, size = model.meshes(), mt_model.MOD_MESH_RECORD_V211
    need((header['version'], header['revision']) == (211, 0) and model.variant == 'model', 'MOD version')
    need(native.raw[old['bones']:old['groups']] == model.raw[new['bones']:new['groups']], 'the skeleton is native')
    need(native.raw[old['materials']:old['meshes']] == model.raw[new['materials']:new['meshes']],
         'the material names are native')
    group, native_group = _group_zero(model), _group_zero(native)
    need(group - new['groups'] == native_group - old['groups'], 'option group 0 keeps its table position')
    table, native_table = bytearray(raw[new['groups']:new['materials']]), bytearray(native_raw[old['groups']:old['materials']])
    table[group - new['groups'] + 16:group - new['groups'] + 32] = bytes(16)
    native_table[native_group - old['groups'] + 16:native_group - old['groups'] + 32] = bytes(16)
    need(table == native_table, 'the option-group table is native apart from the sphere of group 0')
    need(native.raw[0x90:0xA0] == model.raw[0x90:0xA0] and raw[new['end']:] == native_raw[old['end']:],
         'LOD distances and file trailer are native')
    need(len(records) == header['mesh_count'] == 1, 'one mesh record')
    record = records[0]
    packed = struct.unpack_from('<I', raw, new['meshes'] + 4)[0]
    need(packed == record['group_index'] | record['material_index'] << 12 | record['level_of_detail'] << 24,
         'packed group12/material12/LOD8 word')
    need((record['group_index'], record['material_index'], record['level_of_detail']) == (0, material_index, ALL_LODS),
         'option group 0, the reviewed material, every LOD')
    need((record['mesh_type'], record['vertex_format'], record['vertex_stride'], record['vertex_flags'],
          record['render_mode'], record['mesh_class'], record['mesh_id']) == (0xFFFF, DONOR_FORMAT, DONOR_STRIDE, 33, 4, 0, 1),
         'the drawn four-weight record shape with mesh id 1')
    need((record['vertex_index'], record['vertex_offset'], record['face_index'], record['min_index'],
          record['max_index']) == (0, 0, 0, 0, record['vertex_count'] - 1), 'the record addresses the whole buffers')
    need(mt_model.fvf_stride(record['vertex_format']) == record['vertex_stride'], 'vertex format stride')
    need(model.split_valid() and header['vertex_count'] == record['vertex_count']
         and header['vertex_buffer_size'] == new['index_buffer'] - new['vertex_buffer'] == record['vertex_count'] * DONOR_STRIDE,
         'vertex accounting')
    envelopes = record['vertex_group_count']
    need(new['vertex_buffer'] - new['meshes'] - size == mt_model.MOD_WEIGHT_BOUND * envelopes
         and struct.unpack_from('<I', raw, 0xA0)[0] == envelopes > 0, '144-byte envelope records and the count at 0xA0')
    bounds = model.weight_bounds()
    need(len(bounds) == envelopes and all(row['bone'] < header['bone_count'] for row in bounds), 'envelope bones')
    need(all(np.isfinite(row['sphere']).all() and np.isfinite(row['min']).all() and np.isfinite(row['max']).all()
             for row in bounds), 'envelope volumes are finite')
    faces = header['face_count']
    region = raw[new['index_buffer']:new['end']]
    need(record['face_count'] + 1 == faces and len(region) == 2 * faces + (2 * faces) % 4, 'face accounting and index alignment')
    words = np.frombuffer(region[:2 * faces], '<u2')
    need(words[-1] == 0xFFFF and not any(region[2 * faces:]), 'index range separator and alignment word')
    real = words[words != 0xFFFF]
    need(len(real) and real.max() <= record['max_index'], 'indices inside the vertex window')
    triangles = mtf_author.mesh_triangles(model, 0)
    need(len(triangles) > 0 and 4 * len(triangles) == faces, 'every strip is one whole triangle')
    need(header['polygon_count'] == len(triangles), 'the polygon count is the triangle count')
    points = np.asarray(model.positions(0), float)
    box = model.bounds()
    low, high = (np.array([box[k][a] for a in 'xyz']) for k in ('min', 'max'))
    need(len(points) == record['vertex_count'] and np.isfinite(points).all() and (points >= low - .01).all()
         and (points <= high + .01).all() and box['sphere']['r'] > 0, 'vertices lie inside the written bounds')
    sphere = struct.unpack_from('<4f', raw, group + 16)
    local = np.asarray(mtf_author.bone_local_points(native, 0, [tuple(p) for p in points]), float)
    need(np.isfinite(sphere).all() and float(np.linalg.norm(local - sphere[:3], axis=1).max()) <= sphere[3] + .05,
         'the sphere of option group 0 holds the donor')
    data, _ = model.mesh_bytes(0)
    block = np.frombuffer(data, np.uint8).reshape(-1, DONOR_STRIDE)
    joints = block[:, 16:20]
    first = block[:, 6:8].copy().view('<i2')[:, 0] / 32767.
    others = block[:, 24:28].copy().view('<f2').astype(float)
    last = 1. - first - others.sum(1)
    need(int(joints.max()) < header['bone_count'] and (first > 0).all() and (others >= 0).all() and (last >= -1e-3).all(),
         'skin bones and weights')
    # The fourth weight is the remainder; half-float rounding leaves up to a few 1e-4 of it on an unused slot's bone 0.
    weights = np.column_stack((first, others, np.clip(last, 0., 1.)))
    used = {int(bone) for bone, weight in zip(joints.ravel(), weights.ravel()) if weight > 2e-3}
    enveloped = [row['bone'] for row in bounds]
    need(len(set(enveloped)) == len(enveloped) and set(enveloped) <= set(roles.values()),
         'one envelope record per bone, each a role bone of the slot or its lower spine')
    need(used <= set(enveloped), 'every weighted bone has its envelope record')
    normals = np.asarray(model.normals(0), float)
    need(len(normals) == len(points) and np.isfinite(normals).all()
         and (np.abs(np.linalg.norm(normals, axis=1) - 1.) < .05).all(), 'unit vertex normals')
    uvs = np.asarray(model.uvs(0), float)
    need(len(uvs) == len(points) and np.isfinite(uvs).all() and uvs.min() >= -.01 and uvs.max() <= 1.01, 'atlas UVs')
    return {'mesh_records': 1, 'native_records_replaced': len(native.meshes()), 'envelope_count': envelopes,
            'vertex_count': header['vertex_count'], 'triangles': len(triangles), 'face_count': faces,
            'weighted_bones': sorted(used), 'bounds': box, 'group0_sphere': [round(float(v), 4) for v in sphere]}


def verify(original: bytes, candidate: bytes, slot: Slot | None = None, *, secondary: str = 'neutral') -> dict:
    """Re-parse a written archive against its original and return what was checked; any failure raises.

    Entry table unchanged; every entry outside the reviewed indices byte-identical; replaced entries in the shipped zlib
    framing (wrapped stream, level 6, size tag); each model through `_check_model`; textures in their native containers;
    the MRL entries untouched. Every reviewed model of the slot must have changed.
    """
    slot = slot or slot_for(original)
    before, after = mt_arc.parse(original), mt_arc.parse(candidate)
    textures = [i for m in slot.models for i in ((m.albedo[0], m.normal[0], m.mask[0]) if secondary == 'neutral'
                                                 else (m.albedo[0],))]
    mods = {m.mod: m for m in slot.models}
    allowed = set(mods) | set(textures)
    if (after.version, len(after.entries)) != (before.version, len(before.entries)) or mt_arc.build(after) != candidate:
        raise CastWriterError('written archive check failed: entry count or container layout')
    changed = []
    for index, (a, b) in enumerate(zip(before.entries, after.entries)):
        if (a.name, a.hash) != (b.name, b.hash):
            raise CastWriterError(f'written archive check failed: entry {index} lost its name or hash')
        if (a.data, a.tag) == (b.data, b.tag):
            continue
        if index not in allowed:
            raise CastWriterError(f'written archive check failed: entry {index} is outside the reviewed indices')
        try:
            raw = zlib.decompress(b.data)
        except zlib.error:
            raw = None
        if (raw is None or b.data[:2] != a.data[:2] or zlib.compress(raw, 6) != b.data
                or b.tag != (a.tag & 0xFF000000 | len(raw)) or len(raw) > 0xFFFFFF):
            raise CastWriterError(f'written archive check failed: entry {index} is not in the shipped zlib framing')
        changed.append(index)
    if not set(mods) <= set(changed):
        raise CastWriterError('written archive check failed: a reviewed model was not replaced')
    models = {}
    for index, target in mods.items():
        native_raw = zlib.decompress(before.entries[index].data)
        native = mt_model.parse_mod(native_raw)
        mrl = zlib.decompress(after.entries[target.mrl].data)
        material_index, _ = _material(mrl, native, target)
        roles, evidence = role_map(native)
        models[f'{index}:{target.name}'] = _check_model(native_raw, zlib.decompress(after.entries[index].data), target,
                                                         material_index, roles | {'spine': evidence['skeleton']['spine']})
    for index in textures:
        old, new = (zlib.decompress(arc.entries[index].data) for arc in (before, after))
        if mtf_tex.parse(old) != mtf_tex.parse(new) or len(old) != len(new) or old[:20] != new[:20]:
            raise CastWriterError(f'written archive check failed: texture {index} left its native container')
    return {'entry_count': len(after.entries), 'entry_count_unchanged': True, 'changed_entries': sorted(changed),
            'untouched_entries_byte_identical': len(after.entries) - len(changed),
            'zlib_framing': 'wrapped stream, level 6, tag = flags | uncompressed size on every replaced entry',
            'container_rebuild_identical': True, 'mrl_entries_untouched': True,
            'packed_mesh_fields': 'group12/material12/LOD8 re-derived on the record',
            'envelope_records': '144 bytes each; table length, the record count and header 0xA0 agree',
            'native_tables': 'skeleton, material names, LOD distances and option groups (but the sphere of group 0) are native',
            'textures': 'native TEX container, dimensions, format and mip layout kept', 'models': models}


# --- previews -------------------------------------------------------------------------------------------------------

WINDOW = (-115., 115., -10., 240.)       # model x and y in cm that every view shows, so sizes compare across donors


def render(points, normals, uvs, triangles, atlas, *, yaw: float = 0., size: tuple[int, int] = (276, 300),
           window: tuple[float, float, float, float] = WINDOW):
    """One orthographic, z-buffered view (a PIL image) shaded per pixel with the interpolated vertex normals.

    `yaw` turns the model about its up axis: 0 looks at the front of a character facing +Z, 180 at its back. One light
    is fixed to the camera, up and to the left, with a constant ambient term, so a smooth surface shades smoothly, a
    donor without normals shows its facets and a surface whose normals face away shows dark. The line is the floor
    (model y 0). This is not the game's material, lighting, animation or camera.
    """
    from PIL import Image
    points, normals = np.asarray(points, float), np.asarray(normals, float)
    uvs, faces = np.asarray(uvs, float), np.asarray(triangles, int)
    atlas = np.asarray(atlas, np.uint8)[..., :3].astype(float)
    angle = np.radians(yaw)
    c, s = np.cos(angle), np.sin(angle)
    turn = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    view, facing = points @ turn.T, normals @ turn.T
    scale = 2                                                    # supersample, then reduce
    width, height = size[0] * scale, size[1] * scale
    x0, x1, y0, y1 = window
    px = (view[:, 0] - x0) / (x1 - x0) * width
    py = (y1 - view[:, 1]) / (y1 - y0) * height
    light = np.array((-.35, .45, .82))
    light /= np.linalg.norm(light)
    image = np.empty((height, width, 3))
    image[:] = (34, 37, 46)
    ground = int(round(y1 / (y1 - y0) * height))
    if 0 <= ground < height:
        image[ground:ground + scale] = (70, 76, 92)
    depth = np.full((height, width), -np.inf)
    th, tw = atlas.shape[:2]
    for a, b, d in faces:
        xs, ys = px[[a, b, d]], py[[a, b, d]]
        left, right = max(int(np.floor(xs.min())), 0), min(int(np.ceil(xs.max())) + 1, width)
        top, bottom = max(int(np.floor(ys.min())), 0), min(int(np.ceil(ys.max())) + 1, height)
        area = (xs[1] - xs[0]) * (ys[2] - ys[0]) - (xs[2] - xs[0]) * (ys[1] - ys[0])
        if left >= right or top >= bottom or abs(area) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(left, right) + .5, np.arange(top, bottom) + .5)
        w0 = ((xs[1] - gx) * (ys[2] - gy) - (xs[2] - gx) * (ys[1] - gy)) / area
        w1 = ((xs[2] - gx) * (ys[0] - gy) - (xs[0] - gx) * (ys[2] - gy)) / area
        w2 = 1. - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        z = w0 * view[a, 2] + w1 * view[b, 2] + w2 * view[d, 2]
        region = depth[top:bottom, left:right]
        inside &= z > region
        if not inside.any():
            continue
        normal = w0[..., None] * facing[a] + w1[..., None] * facing[b] + w2[..., None] * facing[d]
        normal /= np.maximum(np.linalg.norm(normal, axis=2, keepdims=True), 1e-9)
        shade = .38 + .62 * np.clip(normal @ light, 0., 1.)
        uv = w0[..., None] * uvs[a] + w1[..., None] * uvs[b] + w2[..., None] * uvs[d]
        tx = np.clip((uv[..., 0] * tw).astype(int), 0, tw - 1)
        ty = np.clip((uv[..., 1] * th).astype(int), 0, th - 1)
        colour = atlas[ty, tx] * shade[..., None]
        region[inside] = z[inside]
        image[top:bottom, left:right][inside] = colour[inside]
    picture = Image.fromarray(np.clip(image, 0, 255).astype(np.uint8))
    return picture.resize(size, Image.Resampling.LANCZOS)


def _smooth_normals(rest_points, rest_normals, posed_points, triangles) -> np.ndarray:
    """Normals for a posed surface that keep the smoothing of the written rest normals.

    Vertices that share a rest position and a rest normal are one smooth point however the UV seams split them, so the
    posed face normals are accumulated over that group; a hard edge of the donor stays hard.
    """
    rest_points, rest_normals = np.asarray(rest_points, float), np.asarray(rest_normals, float)
    posed, faces = np.asarray(posed_points, float), np.asarray(triangles, int)
    keys = {}
    group = np.array([keys.setdefault((tuple(np.round(p, 3)), tuple(np.round(n, 2))), len(keys))
                      for p, n in zip(rest_points, rest_normals)])
    face = np.cross(posed[faces[:, 1]] - posed[faces[:, 0]], posed[faces[:, 2]] - posed[faces[:, 0]])
    total = np.zeros((len(keys), 3))
    for corner in range(3):
        np.add.at(total, group[faces[:, corner]], face)
    normals = total[group]
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    return np.where(length > 1e-9, normals / np.maximum(length, 1e-9), rest_normals)


def written_surface(archive: bytes, target: SlotModel) -> dict:
    """The donor record a written archive holds, decoded from its own bytes, with the atlas it actually carries."""
    parsed = mt_arc.parse(archive)
    raw = _entry(parsed, target.mod, target.name, b'MOD\0')
    model = mt_model.parse_mod(raw)
    if len(model.meshes()) != 1:
        raise CastWriterError(f'{target.short} does not hold a one-mesh donor to preview')
    atlas = np.asarray(mtf_tex.decode(_entry(parsed, *target.albedo, b'TEX\0')).convert('RGBA'), np.uint8)
    return {'raw': raw, 'model': model, 'points': np.asarray(model.positions(0), float),
            'normals': np.asarray(model.normals(0), float), 'uvs': np.asarray(model.uvs(0), float),
            'triangles': mtf_author.mesh_triangles(model, 0), 'atlas': atlas}


def find_motion(archive: bytes, suffix: str) -> tuple[int, bytes]:
    """The one native motion resource whose entry name ends with `suffix` (for example `wp00`)."""
    hits = []
    for index, entry in enumerate(mt_arc.parse(archive).entries):
        if entry.name.endswith(suffix):
            raw = zlib.decompress(entry.data)
            if raw[:4] == b'LMT\0':
                hits.append((index, raw))
    if len(hits) != 1:
        raise CastWriterError(f'the archive has {len(hits)} motion resources named *{suffix}, not one')
    return hits[0]


def pose(surface: dict, motion: bytes, clip: int, frame: float) -> dict:
    """The written donor record under one frame of a native clip: CPU forward kinematics and linear skinning.

    The existing comparison sampler (`mtf_motion.sample_compare`) evaluates the clip on the written model. No engine IK,
    physics, clip layering or shading, so this shows whether the surface follows the native joints, never the game pose.
    """
    from . import mtf_motion
    sampled = mtf_motion.sample_compare(surface['raw'], surface['raw'], motion, animation_index=clip,
                                        frames=[float(frame)], raw_fk=True)
    points = np.asarray(sampled['candidate']['frames'][0]['positions'], float).reshape(-1, 3)
    if len(points) != len(surface['points']):
        raise CastWriterError('the sampler did not return the vertices of the donor record')
    return surface | {'points': points, 'evaluation_mode': sampled['evaluation_mode'],
                      'normals': _smooth_normals(surface['points'], surface['normals'], points, surface['triangles'])}


def views(surface: dict, yaws=(0., -90., 150.), size: tuple[int, int] = (276, 300)) -> list:
    """The same surface from several sides: by default the front, the side and the back as the game camera stands."""
    return [render(surface['points'], surface['normals'], surface['uvs'], surface['triangles'], surface['atlas'],
                   yaw=yaw, size=size) for yaw in yaws]


def contact_sheet(rows: list[tuple[str, list]], png: Path, *, title: str = '', columns: list[str] | None = None) -> None:
    """Rows of labelled pictures on one sheet; every row is one donor or slot, every column one view."""
    from PIL import Image, ImageDraw
    if not rows or not rows[0][1]:
        raise CastWriterError('a contact sheet needs at least one row of pictures')
    width, height = rows[0][1][0].size
    count, label, head = max(len(images) for _, images in rows), 190, 44 if title or columns else 0
    sheet = Image.new('RGB', (label + count * width, head + len(rows) * height), (22, 24, 30))
    draw = ImageDraw.Draw(sheet)
    if title:
        draw.text((8, 6), title, fill=(235, 235, 240))
    for i, name in enumerate(columns or []):
        draw.text((label + i * width + 8, 24), name, fill=(170, 176, 190))
    for r, (text, images) in enumerate(rows):
        top = head + r * height
        for k, line in enumerate(text.split('\n')):
            draw.text((8, top + 10 + 14 * k), line, fill=(235, 235, 240) if not k else (170, 176, 190))
        for i, image in enumerate(images):
            sheet.paste(image, (label + i * width, top))
    Path(png).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(png)


# --- bounded recipes ------------------------------------------------------------------------------------------------

POSE_CLIP, POSE_FRAME = 25, 30          # `wp00` clip 25 needs no engine IK on either skeleton family (measured)
PREVIEW_COLUMNS = ['rest pose, front', 'wp00 clip 25 frame 30, front', 'same, side', 'same, back (camera side)']


def donor_from(library: Path, slug: str) -> Donor:
    """The usable donor in one library folder, resolved by the shared donor module; anything else is refused."""
    folder = Path(library) / slug
    if not slug or Path(slug).name != slug or not folder.is_dir():
        raise CastWriterError(f'unknown donor {slug!r}: the library has no such folder')
    try:
        return re5_donor_pool.resolve(folder)[0]
    except DonorError as exc:
        raise CastWriterError(f'{slug} is not a usable donor ({exc.category}): {exc}') from exc


def build(archive: bytes, source: Path, donor: Donor, *, secondary: str = 'neutral'):
    """Return (complete slot archive, receipt) for a resolved donor on a reviewed slot; nothing is written or launched.

    The archive must be one of the six original Mercenaries archives and the source the exact model the donor was
    resolved from. The receipt names the donor by its own provenance: a native costume is never relabelled as a donor.
    """
    source = Path(source)
    if hashlib.sha256(source.read_bytes()).hexdigest() != donor.sha256:
        raise CastWriterError(f'{donor.name} needs the exact {donor.model} it was resolved from; this file differs')
    slot = slot_for(archive)
    output, receipt = author(archive, source, donor.role_names(), slot=slot, height_factor=donor.height_factor,
                             secondary=secondary)
    receipt.update(
        donor=donor.slug,
        source={'slug': donor.slug, 'name': donor.name, 'game': donor.game, 'franchise': donor.franchise,
                'model': donor.model, 'sha256': donor.sha256, 'provenance': donor.provenance,
                'roles_from': donor.roles_from, 'size': donor.size},
        target={'archive': slot.archive, 'sha256': slot.sha256, 'class': slot.player_class, 'roster_label': slot.label,
                'models': [m.name for m in slot.models]},
        replacement_scope={
            'route': 'measured_cast_mesh_recipe', 'complete': False, 'gameplay_verified': False,
            'source_platform': donor.platform, 'written_platform': 'switch', 'collection_model_used': True,
            'requested_character': {'slug': donor.slug, 'name': donor.name}, 'target_archive': slot.archive,
            'notes': ['Offline candidate; no boot, round or frame has been observed',
                      f'Only {", ".join(m.short for m in slot.models)} of {slot.player_class} carry the donor; the '
                      'other body variants, the severed-head models and the cutscene face models stay native',
                      'The donor has no finger or face animation: its hands follow the native hand bone as one piece',
                      'The title restarts to load the archive; a running round is not preserved']},
        acceptance='experimental; offline structural checks only')
    return output, receipt


def _preview(archive: bytes, original: bytes, slot: Slot, png: Path | None = None) -> tuple[list, dict]:
    """Rest and posed pictures of the donor a written slot archive holds (its first body model)."""
    surface = written_surface(archive, slot.models[0])
    index, motion = find_motion(original, 'wp00')
    posed = pose(surface, motion, POSE_CLIP, POSE_FRAME)
    images = [*views(surface, (0.,)), *views(posed)]
    if png is not None:
        contact_sheet([('', images)], png)
    return images, {'model': slot.models[0].name, 'views': PREVIEW_COLUMNS, 'motion_entry': index,
                    'clip': POSE_CLIP, 'frame': POSE_FRAME, 'evaluation_mode': posed['evaluation_mode'],
                    'shows': 'written MOD geometry, written normals and written BC7 atlas on the CPU under one '
                             'camera light; not the material, lighting, IK, clip layering or camera of the game'}


def _row(receipt: dict) -> str:
    rig, counts, fit = receipt['donor_rig'], receipt['counts'], receipt['fit']
    surface = next(iter(receipt['models'].values()))['atlas_source']
    faceted = surface.get('face_normal_fallback_corners', 0) > 0
    return (f"{receipt['source']['name'][:26]}\n{receipt['source']['game'][:28]}\n{receipt['slot']['label']}\n"
            f"{counts['triangles']} tris, {counts['vertices']} verts\nheight {fit['height']:.0f} cm\n"
            f"body scale {fit['scale']['body_scale']:.3g}\nblended skin {rig['blended_vertex_share']:.0%}\n"
            f"{'no normals: faceted' if faceted else 'own normals'}\natlas x{surface.get('texture_scale', 1):g}")


def compare(archive: bytes, library: Path, donors: list[str], out: Path, *, keep_archives: bool = False) -> dict:
    """Build several donors into one slot with the same path and draw them side by side under one light and one pose.

    A donor that is refused is listed with the reason instead of a picture. Writes `<donor>.png`, `contact-sheet.png`
    and `comparison.json` under `out`; the candidate archives are only kept on request.
    """
    import json
    library, out = Path(library), Path(out)
    slot = slot_for(archive)
    out.mkdir(parents=True, exist_ok=True)
    rows, report = [], {'slot': slot.key, 'archive': slot.archive, 'target_archive_sha256': slot.sha256, 'donors': {}}
    for slug in donors:
        try:
            donor = donor_from(library, slug)
            written, receipt = build(archive, library / slug / donor.model, donor)
        except (CastWriterError, ValueError, OSError) as exc:
            report['donors'][slug] = {'built': False, 'reason': str(exc)}
            continue
        images, preview = _preview(written, archive, slot, out / f'{slug}.png')
        rows.append((_row(receipt), images))
        receipt['preview'] = preview | {'preview': f'{slug}.png'}
        if keep_archives:
            path = out / slug / 'romfs' / slot.archive
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(written)
        report['donors'][slug] = {'built': True} | receipt
    if rows:
        contact_sheet(rows, out / 'contact-sheet.png', columns=PREVIEW_COLUMNS,
                      title=f'{slot.label} ({slot.player_class}): one generic native-pose fit per donor, one light, one '
                            'pose. CPU picture, not the game.')
    (out / 'comparison.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    return report


def cast(romfs: Path, library: Path, assignment: dict[str, str], out: Path, *, plan: dict | None = None) -> dict:
    """Write one overlay tree that carries a different donor in every assigned slot, with a receipt and a contact sheet.

    `romfs` holds the original archives under `nativeNXx64/ImgNX/Archive`, `library` the donor folders. Every slot must
    get its own donor. Nothing is written unless every slot builds: a refused donor raises with the slot and the reason.
    """
    import json
    romfs, library, out = Path(romfs), Path(library), Path(out)
    unknown = sorted(set(assignment) - set(SLOTS))
    if unknown or not assignment:
        raise CastWriterError(f'unknown slots {unknown}: the reviewed slots are {", ".join(SLOTS)}')
    if len(set(assignment.values())) != len(assignment):
        raise CastWriterError('every slot of a cast needs its own donor')
    chosen, built = {}, {}
    for key in SLOTS:                         # every slot's fit is checked before any slot is built
        if key in assignment:
            slot = SLOTS[key]
            try:                              # any refusal of the fit, the writer or the checks names its slot and donor
                donor = donor_from(library, assignment[key])
                original = (romfs / slot.archive).read_bytes()
                if hashlib.sha256((library / donor.slug / donor.model).read_bytes()).hexdigest() != donor.sha256:
                    raise CastWriterError(f'{donor.name} needs the exact {donor.model} it was resolved from')
                fits(original, library / donor.slug / donor.model, donor.role_names(), slot=slot_for(original),
                     height_factor=donor.height_factor)
            except ValueError as exc:
                raise CastWriterError(f'{key} <- {assignment[key]}: {exc}') from exc
            chosen[key] = (slot, donor, original)
    for key, (slot, donor, original) in chosen.items():
        try:
            written, receipt = build(original, library / donor.slug / donor.model, donor)
        except ValueError as exc:
            raise CastWriterError(f'{key} <- {donor.slug}: {exc}') from exc
        built[key] = (slot, original, written, receipt)
    rows, slots = [], {}
    for key, (slot, original, written, receipt) in built.items():
        path = out / 'romfs' / slot.archive
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(written)
        images, preview = _preview(written, original, slot, out / f'{key}.png')
        rows.append((_row(receipt), images))
        receipt['output'] = {'path': 'romfs/' + slot.archive, 'sha256': receipt['written_sha256'], 'bytes': len(written)}
        receipt['preview'] = preview | {'preview': f'{key}.png'}
        slots[key] = receipt
    contact_sheet(rows, out / 'contact-sheet.png', columns=PREVIEW_COLUMNS,
                  title='RE5 Switch Mercenaries cast overlay: one donor per roster slot. CPU picture, not the game.')
    receipt = {'recipe': 're5_cast_writer', 'recipe_version': RECIPE_VERSION, 'title_id': '010018100CD46000',
               'game_id': '52d15709be0fda1a', 'overlay_root': 'romfs', 'contact_sheet': 'contact-sheet.png',
               'assignment': {key: slots[key]['donor'] for key in slots}, 'plan': plan, 'slots': slots,
               'live_verified': False, 'gameplay_verified': False, 'writer_registered': False,
               'replacement_scope': {'complete': False, 'gameplay_verified': False,
                                     'notes': ['Six Mercenaries roster slots of fourteen; Jill, Wesker, Josh, Excella, '
                                               'Barry and Rebecca stay native',
                                               'No archive of this overlay has been booted']},
               'acceptance': 'experimental; offline structural checks only'}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=1), encoding='utf-8')
    return receipt


def pool_cast(romfs: Path, library: Path, donors: list[Donor], seed, out: Path, *, slots: list[str] | None = None,
              history: list | tuple = (), avoid_last: int = 3, games: list[str] | None = None,
              exclude: dict[str, str] | None = None) -> dict:
    """Deal donors to the slots from a seed (`re5_donor_pool.plan`) and write that overlay.

    A donor a slot refuses (its surface does not fit that slot's atlas, say) is set aside and the plan is dealt again
    from the same seed without it, so the outcome still follows from the seed, the donors, the history and `exclude`
    alone. `exclude` maps donors the caller leaves out to the reason; they are listed in the receipt with the rest.
    """
    slots = list(slots or SLOTS)
    refused: dict[str, str] = dict(exclude or {})
    while True:
        assignment = re5_donor_pool.plan(seed, slots, donors, history=history, avoid_last=avoid_last, games=games,
                                         exclude=set(refused))
        details = {'seed': seed, 'slots': slots, 'games': games, 'avoid_last': avoid_last,
                   'history': [dict(row) if isinstance(row, dict) else list(row) for row in history],
                   'pool_size': len(donors), 'set_aside': dict(refused)}
        try:
            return cast(romfs, library, assignment, out, plan=details)
        except CastWriterError as exc:
            slug = str(exc).split(':', 1)[0].rsplit('<- ', 1)[-1].strip()
            if slug not in assignment.values() or slug in refused:
                raise
            refused[slug] = str(exc)
            print(f'set aside: {exc}', flush=True)


def main(argv=None) -> int:
    """CLI. `build`, `compare`, `cast` and `pool` write candidates; `verify` re-checks one; `survey` reads a library."""
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Offline RE5 Switch Mercenaries cast candidates (never installs or launches)')
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('build', help='one donor on one slot archive')
    one.add_argument('--archive', required=True)
    one.add_argument('--library', required=True)
    one.add_argument('--donor', required=True)
    one.add_argument('--out', required=True)
    check = commands.add_parser('verify', help='re-parse a written archive against its original')
    check.add_argument('--original', required=True)
    check.add_argument('--candidate', required=True)
    many = commands.add_parser('compare', help='several donors on one slot, side by side')
    many.add_argument('--archive', required=True)
    many.add_argument('--library', required=True)
    many.add_argument('--donors', required=True, help='comma-separated donor slugs')
    many.add_argument('--out', required=True)
    many.add_argument('--keep-archives', action='store_true')
    whole = commands.add_parser('cast', help='one overlay with a named donor per slot')
    whole.add_argument('--romfs', required=True)
    whole.add_argument('--library', required=True)
    whole.add_argument('--assign', required=True, help='slot=donor,... (slots: ' + ', '.join(SLOTS) + ')')
    whole.add_argument('--out', required=True)
    look = commands.add_parser('survey', help='which library folders are usable donors, and why the others are not')
    look.add_argument('--library', required=True)
    look.add_argument('--out', required=True, help='JSON report to write')
    dealt = commands.add_parser('pool', help='one overlay dealt from a seed out of a survey report')
    dealt.add_argument('--romfs', required=True)
    dealt.add_argument('--library', required=True)
    dealt.add_argument('--survey', required=True, help='report written by `survey`')
    dealt.add_argument('--seed', required=True)
    dealt.add_argument('--out', required=True)
    dealt.add_argument('--games', help='comma-separated game titles or franchises to draw from')
    dealt.add_argument('--history', help='comma-separated receipt.json files of earlier overlays, oldest first')
    dealt.add_argument('--avoid-last', type=int, default=3)
    dealt.add_argument('--exclude', help='comma-separated donor slugs to leave out')
    dealt.add_argument('--exclude-reason', default='left out by the caller')
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            original = Path(args.original).read_bytes()
            candidate = Path(args.candidate).read_bytes()
            slot = slot_for(original)
            checks = verify(original, candidate, slot)
            print(json.dumps({'slot': slot.key, 'archive': slot.archive, 'verified': True,
                              'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
                              'changed_entries': checks['changed_entries'],
                              'untouched_entries_byte_identical': checks['untouched_entries_byte_identical'],
                              'models': {key: {k: row[k] for k in ('mesh_records', 'envelope_count', 'vertex_count',
                                                                    'triangles', 'weighted_bones')}
                                         for key, row in checks['models'].items()}}))
        elif args.command == 'build':
            archive = Path(args.archive).read_bytes()
            donor = donor_from(Path(args.library), args.donor)
            output, receipt = build(archive, Path(args.library) / donor.slug / donor.model, donor)
            slot, out = slot_for(archive), Path(args.out)
            path = out / 'romfs' / slot.archive
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(output)
            receipt['output'] = {'path': 'romfs/' + slot.archive, 'sha256': receipt['written_sha256'], 'bytes': len(output)}
            receipt['preview'] = _preview(output, archive, slot, out / 'preview.png')[1] | {'preview': 'preview.png'}
            (out / 'receipt.json').write_text(json.dumps(receipt, indent=1), encoding='utf-8')
            print(json.dumps({'archive': str(path), 'sha256': receipt['written_sha256']}))
        elif args.command == 'compare':
            report = compare(Path(args.archive).read_bytes(), Path(args.library), args.donors.split(','), Path(args.out),
                             keep_archives=args.keep_archives)
            print(json.dumps({slug: row.get('written_sha256') or row['reason'] for slug, row in report['donors'].items()}))
        elif args.command == 'survey':
            report = re5_donor_pool.survey(Path(args.library))
            Path(args.out).write_text(json.dumps(report, indent=1), encoding='utf-8')
            print(json.dumps({'usable': report['summary']['usable'], 'refused': report['summary']['refused'],
                              'refusals_by_reason': report['summary']['refusals_by_reason']}))
        elif args.command == 'pool':
            donors = re5_donor_pool.donors_of(json.loads(Path(args.survey).read_text(encoding='utf-8')))
            history = [json.loads(Path(name).read_text(encoding='utf-8'))['assignment']
                       for name in (args.history.split(',') if args.history else [])]
            receipt = pool_cast(Path(args.romfs), Path(args.library), donors, args.seed, Path(args.out), history=history,
                                avoid_last=args.avoid_last, games=args.games.split(',') if args.games else None,
                                exclude={slug: args.exclude_reason for slug in (args.exclude or '').split(',') if slug})
            print(json.dumps({'assignment': receipt['assignment'],
                              'sha256': {key: row['written_sha256'] for key, row in receipt['slots'].items()}}))
        else:
            pairs = dict(item.split('=', 1) for item in args.assign.split(','))
            receipt = cast(Path(args.romfs), Path(args.library), pairs, Path(args.out))
            print(json.dumps({key: row['written_sha256'] for key, row in receipt['slots'].items()}))
    except (CastWriterError, ValueError) as exc:
        print(f'refused: {exc}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
