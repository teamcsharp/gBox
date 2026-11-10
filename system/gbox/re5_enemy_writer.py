"""Unregistered, bounded group-aware enemy writer: library donors onto the RE5 Switch Majini (`uEm10.arc`, `uEm11.arc`).

`build()` is the first recipe, SM64 DS Mario on `em1000`, kept byte for byte: its candidate is the one shape the game
has loaded and drawn. `build_donor()` is the same recipe for any library donor whose role metadata is complete, on any
archive that has a reviewed table in `ARCHIVES`.

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
import json
import struct
import zlib
from dataclasses import dataclass, field
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
NATIVE_LOD_MASKS = (1, 2, 252)                   # measured on all six em1000/em1001 models: near, middle, bits 2-7
#: The LOD mask is one bit per level of detail: bit 0 the near model, bit 1 the middle one, bits 2-7 the far ones.
#: em1000 only uses 1, 2 and 252. em1300 adds 3 (near and middle: its `gam_Eyes_LOD0_LOD1` material) and 254 (middle
#: and far: `gam_Mouth_LOD1_LOD2`), em1400 and em2100 add 254, em1200's `_low` / `_mid` models carry two tongue and eye
#: records with 255. Every native record keeps its mask; a donor record is told apart by its mesh id, never by the mask.
LOD_MASK_READING = {'bits': 'bit k = level of detail k; 1 near, 2 middle, 252 far (bits 2-7), 3 near+middle, '
                            '254 middle+far, 255 every level',
                    'measured_on': {'em1000': [1, 2, 252], 'em1100': [1, 2, 252], 'em1200': [1, 2, 252],
                                    'em1200_low / em1200_mid': [1, 2, 252, 255], 'em1300': [1, 2, 3, 252, 254],
                                    'em1400': [1, 2, 252, 254], 'em2100': [1, 2, 252, 254]},
                    'evidence': 'em1300 material names carry the levels their records draw: gam_Eyes_LOD0_LOD1 has '
                                'mask 3, gam_Mouth_LOD1_LOD2 has mask 254, the LOD2 body materials have 252'}


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
    lod_masks: tuple[int, ...] = NATIVE_LOD_MASKS        # the LOD masks its native records were measured to use
    roles_by_ids: bool = False                           # take the animation ids where the bind-pose measurement refuses
    shared_atlas: bool = False                           # the atlas may be sampled by several materials (all blanked)

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

_MODEL11 = 'pawn\\em\\em11\\model\\'
#: The second Majini class (the women), reviewed 2026-11-09 against uEm11.arc `a33ae046...`. One model, no `_mid` or
#: `_low` file: its three LODs are records of the same table (masks 1, 2, 252). Ten option groups and no group 0; the
#: last digit is again the slot. Each was confirmed from its vertices and material names: head (Head/Eye/Teeth, y
#: 138-181), arm and torso skin (`zof_body`, x to +-89), leg skin (y 0-117), shirt (`syatu`), skirt (`skart`), head
#: cloth (`head_nuno`, y 163-184), sandals (y -2..10).
#: The atlas goes to the head cloth of group 8: the only 512x256 albedo that exactly one `em1100` material samples
#: (the sandal albedo is 128x128, the body skin 1024x512 on a skin material). Its descriptor has the same blend, depth
#: and raster state and the same command list as the sandal material of `em1000` that the game has drawn a donor
#: with; one flag field differs (0x216 against 0x21A) and its constants are its own.
EM1100 = EnemySet(
    name='em1100',
    models=((_MODEL11 + 'em1100', 89, 69),),
    groups=(('head', (1,)), ('arm_skin', (2,)), ('leg_skin', (3,)), ('shirt', (5, 15)), ('skirt', (6, 16)),
            ('head_cloth', (8, 18)), ('sandals', (9,))),
    albedo=(45, _MODEL11 + 'gof01_08_BM'), normal=(47, _MODEL11 + 'gof01_08_NM'), mask=(46, _MODEL11 + 'gof01_08_MM'))
SETS['em1100'] = EM1100

_MODEL12, _MODEL13, _MODEL14 = 'pawn\\em\\em12\\model\\', 'pawn\\em\\em13\\model\\', 'pawn\\em\\em14\\model\\'
#: The Village / Ancient Ruins class, reviewed 2026-11-09 against uEm12.arc `4224faf2...`: three models (high, `_low`,
#: `_mid`), 19 option groups, no group 0. Slots from the material names and the montage categories: head (1, `em12_Head`,
#: four variants), body (2, `em12_Body`, four variants), leg (3), left hand (4, 14), right hand (5, 15), accessories (6,
#: 16, 26, 36; one material), waist cloth (7, 17). The skeleton is stored parents-first with ONE extra root: a childless,
#: unskinned bone at the origin with animation id 250 (bone 80 / 30 / 62), which `measure_roles` lists as detached. The
#: `_low` and `_mid` models carry a tongue (and an eye) record with LOD mask 255 in group 1. The atlas of the one-donor
#: route is the first body texture, 1024x2048, sampled by the three body materials of group 2 (Body1, Body2, plaga1).
EM1200 = EnemySet(
    name='em1200',
    models=((_MODEL12 + 'em1200', 93, 74), (_MODEL12 + 'em1200_low', 94, 75), (_MODEL12 + 'em1200_mid', 95, 76)),
    groups=(('head', (1, 11, 21, 31)), ('body', (2, 12, 22, 32)), ('leg', (3,)), ('l_hand', (4, 14)),
            ('r_hand', (5, 15)), ('accessory', (6, 16, 26, 36)), ('waist', (7, 17))),
    albedo=(22, _MODEL12 + 'em1200_01_BM'), normal=(24, _MODEL12 + 'em1200_01_NM'), mask=(23, _MODEL12 + 'em1200_01_MM'),
    lod_masks=(1, 2, 252, 255), shared_atlas=True)
SETS['em1200'] = EM1200
#: The Mines / Prison class, reviewed against uEm13.arc `1db1a79a...`: one model, 89 bones (a ground bone at the origin
#: above the body root, as em1100), four groups: head 1, body 2, pants 3 and 13. LOD masks 3 and 254 beside 1, 2, 252
#: (see LOD_MASK_READING). Its mask maps are `_CMM` textures in format 0x13, which the texture codec does not decode, so
#: they stay native (`Carrier.neutral` leaves them out). Atlas of the one-donor route: the first pants texture, 1024x512.
EM1300 = EnemySet(
    name='em1300', models=((_MODEL13 + 'em1300', 49, 39),),
    groups=(('head', (1,)), ('body', (2,)), ('pants', (3, 13))),
    albedo=(22, _MODEL13 + 'em1302_BM'), normal=(24, _MODEL13 + 'em1302_NM'), mask=(23, _MODEL13 + 'em1302_CMM'),
    lod_masks=(1, 2, 3, 252, 254))
SETS['em1300'] = EM1300
#: The Experimental Facility class, reviewed against uEm14.arc `52399b0b...`: three models, 41 option groups INCLUDING
#: group 0 (the first face), the same detached extra root as em1200, LOD mask 254 beside 1, 2, 252. Slots from the
#: material names; the montage categories are 1 headgear, 2 tops, 3 lower body and gear, 4 belts, 5 the dog tag.
EM1400 = EnemySet(
    name='em1400',
    models=((_MODEL14 + 'em1400', 124, 106), (_MODEL14 + 'em1400_low', 125, 107), (_MODEL14 + 'em1400_mid', 126, 108)),
    groups=(('face', (0, 5)), ('body', (1, 2, 3)), ('hands', (4,)), ('pants', (6, 7, 8, 9, 10, 11, 12)),
            ('boots', (13,)), ('jacket', (14, 15)), ('vest', (16,)), ('shirt', (17, 18, 19, 20, 21, 22)),
            ('goods', (23, 24, 25)), ('bomb', (26,)), ('gun_belt', (27, 28)), ('bandana', (29, 30)),
            ('cap', (31, 32, 33, 34, 35)), ('armor_mask', (36,)), ('armor_body', (37,)), ('armor_foot', (38,)),
            ('face_guard', (39,)), ('dog_tag', (40,))),
    albedo=(20, _MODEL14 + 'em1400_01_BM'), normal=(22, _MODEL14 + 'em1400_01_NM'), mask=(21, _MODEL14 + 'em1400_01_MM'),
    lod_masks=(1, 2, 252, 254))
SETS['em1400'] = EM1400
#: The second Public Assembly class, reviewed against uEm21.arc `3c01b16d...`: the archive holds `em2100` under the em10
#: model folder (the same name as the em2100 inside uEm10.arc). One model, 90 bones, 38 records, seven groups: head 101,
#: body 22, leg 23, sandals 7, shirt 254, pants 255 and group 4, which the montage table does not name and which holds
#: the shirt's far-LOD records (mask 252) alone. Its montages 1 and 2 draw no head (value 31). The one-donor atlas is the
#: shirt, 1024x1024, the only texture of this archive that uEm10.arc does not also carry (its pants are gam01_005_BM, the
#: em1000 pants carrier 5, and its leg maps are gam01_022; which archive's copy the game samples when both are loaded in
#: Public Assembly is not known).
EM2100 = EnemySet(
    name='em2100', models=((_MODEL + 'em2100', 26, 25),),
    groups=(('head', (101,)), ('body', (22,)), ('leg', (23,)), ('sandals', (7,)), ('shirt', (254,)),
            ('shirt_far', (4,)), ('pants', (255,))),
    albedo=(9, _MODEL + 'gam01_254_BM'), normal=(8, _MODEL + 'gam01_254_NM'), mask=(10, _MODEL + 'gam01_254_MM'),
    lod_masks=(1, 2, 252, 254))
SETS['em2100'] = EM2100

#: The seven boss and special classes whose skeletons are standing bipeds with the fifteen role ids at the Majini bind
#: positions (hip 0, 114, 0; head 0, 165, -2.34; wrists +-70.4; ankles +-9.2, 13.5 - em2300's legs are +-10.2 apart,
#: em3400 is the same figure 2.3 times taller: hip 186, hands +-185, top 436 cm). Their bind-pose hierarchy measurement
#: refuses them (the chest carries more branches than two arms and a neck: weapons, aprons, chains), so their role maps
#: come from the animation ids with `check_role_geometry` (`roles_by_ids`); em2300 measures outright. None has a
#: montage table that selects among several parts of a kind (uEm92's names one group per category), so each is
#: written as one donor on every option group, the shape the game has drawn. Their atlases are the largest BC7 albedo
#: whose samplers all bind the same maps; where several materials sample it (`shared_atlas`) every one is blanked.
#: Reviewed 2026-11-09 against the archives of the RomFS (SHA-256 in ARCHIVES below).
_MODEL20, _MODEL22, _MODEL23 = 'pawn\\em\\em20\\model\\', 'pawn\\em\\em22\\model\\', 'pawn\\em\\em23\\model\\'
_MODEL24, _MODEL26, _MODEL34, _MODEL92 = ('pawn\\em\\em24\\model\\', 'pawn\\em\\em26\\model\\', 'pawn\\em\\em34\\model\\',
                                          'pawn\\em\\em92\\model\\')
EM2000 = EnemySet(                      # uEm20: Public Assembly (6 No Mercy spawns); 120 bones, 59 records, one group
    name='em2000', models=((_MODEL20 + 'em2000', 59, 40),), groups=(('body', (0,)),),
    albedo=(23, _MODEL20 + 'em2000_02epu_BM'), normal=(25, _MODEL20 + 'em2000_02epu_NM'),
    mask=(24, _MODEL20 + 'em2000_02epu_MM'), lod_masks=(1, 2, 252, 254), roles_by_ids=True, shared_atlas=True)
EM2600 = EnemySet(                      # uEm26: Prison (5); the em20 skeleton (120 bones), 99 records, one group
    name='em2600', models=((_MODEL26 + 'em2600', 63, 44),), groups=(('body', (0,)),),
    albedo=(27, _MODEL26 + 'em2000_03zubon_BM'), normal=(29, _MODEL26 + 'em2000_03zubon_NM'),
    mask=(28, _MODEL26 + 'em2000_03zubon_MM'), lod_masks=(1, 2, 252), roles_by_ids=True, shared_atlas=True)
EM2200 = EnemySet(                      # uEm22: Ship Deck (14); 98 bones, 38 records, six groups, masks 254 and 255
    name='em2200', models=((_MODEL22 + 'em2200', 52, 40),),
    groups=(('head', (1,)), ('body', (2,)), ('leg', (3,)), ('pants', (5,)), ('wig', (6,)), ('key', (8,))),
    albedo=(25, _MODEL22 + 'em20_005_BM'), normal=(27, _MODEL22 + 'em20_005_NM'), mask=(26, _MODEL22 + 'em20_005_MM'),
    lod_masks=(1, 2, 252, 254, 255), roles_by_ids=True)
EM2400 = EnemySet(                      # uEm24: Village (8) and Ancient Ruins (13); 89 bones, 66 records, top 195.7 cm
    name='em2400', models=((_MODEL24 + 'em2400', 66, 50),), groups=(('head', (0,)), ('body', (1,)), ('leg', (2,))),
    albedo=(31, _MODEL24 + 'em2400_BM_01'), normal=(36, _MODEL24 + 'em2400_NM_01'), mask=(34, _MODEL24 + 'em2400_MM_01'),
    lod_masks=(1, 2, 252), roles_by_ids=True, shared_atlas=True)
EM2300 = EnemySet(                      # uEm23: Missile Area (6), Ship Deck Reunion (1); 93 bones, 81 records; its
    name='em2300', models=((_MODEL23 + 'em2300', 81, 63),),      # bind pose measures outright; _CMM masks stay native
    groups=(('body', (0,)), ('gear', (1,)), ('grass', (2,)), ('head', (3,)), ('gun', (4,)), ('cloth', (205,))),
    albedo=(16, _MODEL23 + 'em2300_BM'), normal=(18, _MODEL23 + 'em2300_NM'), mask=(17, _MODEL23 + 'em2300_CMM'),
    lod_masks=(1, 2, 3, 4, 252))
EM9200 = EnemySet(                      # uEm92: Public Assembly Reunion (1); 117 bones, 84 records, three groups
    name='em9200', models=((_MODEL92 + 'em9200', 43, 39),), groups=(('body', (0,)), ('hair', (1,)), ('head', (3,))),
    albedo=(11, _MODEL92 + 'em92_002_BM'), normal=(13, _MODEL92 + 'em92_002_NM'), mask=(12, _MODEL92 + 'em92_002_MM'),
    lod_masks=(1, 2, 252, 255), roles_by_ids=True, shared_atlas=True)
EM3400 = EnemySet(                      # uEm34: The Mines (7); 98 bones, 42 records, one group, 4.36 m tall
    name='em3400', models=((_MODEL34 + 'em3400', 71, 48),), groups=(('body', (0,)),),
    albedo=(19, _MODEL34 + 'em3400_00_BM'), normal=(22, _MODEL34 + 'em3400_00_NM'), mask=(21, _MODEL34 + 'em3400_00_MM'),
    lod_masks=(1, 2, 252), roles_by_ids=True, shared_atlas=True)
for _set in (EM2000, EM2600, EM2200, EM2400, EM2300, EM9200, EM3400):
    SETS[_set.name] = _set

#: Measured and deliberately not buildable: `em1101` (entry 90, 109 bones, 63 records in the same ten groups). Its role
#: map measures and agrees with the animation ids, but (a) its drawn records use formats 0x2270D877 / 0x1E5013A0 /
#: 0x1AC0F6CB and none is the donor's 0x2000D414, so there is no native record of the donor's shape; (b) three
#: materials (high, mid, low) sample every albedo, so no texture belongs to one material; (c) its legs have another
#: bind pose (thigh +-8.03 at y 104.9, ankle y 16.0). Every Mercenaries layout spawns `uEm11` with model type 0.
UNBUILT_MODELS = {'uEm11': {'em1101': 'no native record in the donor vertex format, three materials per albedo and '
                                       'another leg bind pose; no Mercenaries layout asks for model type 1'}}


@dataclass(frozen=True)
class EnemyArchive:
    """One enemy class archive of the measured RomFS: its hash, its reviewed sets and a native clip for the preview."""
    name: str                                   # the class the game spawns, also the archive stem
    path: str
    sha256: str
    sets: tuple[str, ...]                       # every reviewed set of this archive, in build order
    default_sets: tuple[str, ...]               # what a Mercenaries build replaces (model type 0)
    pose: tuple[int, int, tuple[float, ...]]    # (LMT entry index, clip index, frames) for the posed preview
    not_replaced: tuple[str, ...] = ()

    def targets(self, sets: tuple[str, ...] | None = None) -> list[EnemySet]:
        chosen = tuple(sets) if sets is not None else self.default_sets
        if (not chosen or len(set(chosen)) != len(chosen) or any(name not in self.sets for name in chosen)
                or [name for name in self.sets if name in chosen] != list(chosen)):
            raise EnemyWriterError(f'{self.name} has the reviewed sets {list(self.sets)}; build them in that order')
        return [SETS[name] for name in chosen]


ARCHIVES = {
    'uEm10': EnemyArchive('uEm10', ARCHIVE_PATH, ARCHIVE_SHA256, ('em1000', 'em1001'), ('em1000',),
                          (259, 3, (0., 30., 60.)), ('em2100',)),
    'uEm11': EnemyArchive('uEm11', 'nativeNXx64/ImgNX/Archive/uEm11.arc',
                          'a33ae046d908254053b9d8bb00cc3542057efb967986143c7990e3481b7f44dc', ('em1100',), ('em1100',),
                          (100, 105, (0., 30., 60.)), ('em1101', 'evf2300', 'evf2303', 'evf2304')),
    # The four classes below share the em10 motion set; the posed preview samples `em10_g06` clip 105 as uEm11 does.
    'uEm12': EnemyArchive('uEm12', 'nativeNXx64/ImgNX/Archive/uEm12.arc',
                          '4224faf2cc80d1b4ffdcb30e205925f7971fada0d8582be1faf3ddf78e37e70b', ('em1200',), ('em1200',),
                          (101, 105, (0., 30., 60.)), ()),
    'uEm13': EnemyArchive('uEm13', 'nativeNXx64/ImgNX/Archive/uEm13.arc',
                          '1db1a79a0b1421639f4a6d4c068e227fd68b0d6adfb49249d9cdd3a3e1633018', ('em1300',), ('em1300',),
                          (56, 105, (0., 30., 60.)), ()),
    'uEm14': EnemyArchive('uEm14', 'nativeNXx64/ImgNX/Archive/uEm14.arc',
                          '52399b0b7e189b5b481399cf5870c87790390da7926151c3670c7b1228963759', ('em1400',), ('em1400',),
                          (134, 105, (0., 30., 60.)), ()),
    'uEm21': EnemyArchive('uEm21', 'nativeNXx64/ImgNX/Archive/uEm21.arc',
                          '3c01b16d948a3dc831207e4828aad8aa3fc4dede895b46dce9caf547fb0635a3', ('em2100',), ('em2100',),
                          (33, 105, (0., 30., 60.)), ()),
    # The boss and special classes (one donor on every group). Their own motion sets pose the previews where they
    # carry no em10 set: `em20` clip 0 (491 frames), `em22` clip 0 (342), `em23_g23` clip 0 (170), `em34` clip 0 (420).
    'uEm20': EnemyArchive('uEm20', 'nativeNXx64/ImgNX/Archive/uEm20.arc',
                          '269559f2de336138a695b4b57f764a022525b3570723063d60cb3b3f2627a5f0', ('em2000',), ('em2000',),
                          (60, 0, (0., 30., 60.)), ()),
    'uEm22': EnemyArchive('uEm22', 'nativeNXx64/ImgNX/Archive/uEm22.arc',
                          '2020d20dababa0487df919213762f567788d737e78796399ca090d45c076e137', ('em2200',), ('em2200',),
                          (53, 0, (0., 30., 60.)), ()),
    'uEm23': EnemyArchive('uEm23', 'nativeNXx64/ImgNX/Archive/uEm23.arc',
                          '4441a22c2e43f54b9c5fec337bc9de6ea56632fd7542104f743668ccc8b17528', ('em2300',), ('em2300',),
                          (82, 0, (0., 30., 60.)), ()),
    'uEm24': EnemyArchive('uEm24', 'nativeNXx64/ImgNX/Archive/uEm24.arc',
                          '482172df0b734b0e2d7f660b314548fd83f9e258b4738a649e1b6c6508cff35f', ('em2400',), ('em2400',),
                          (72, 105, (0., 30., 60.)), ()),
    'uEm26': EnemyArchive('uEm26', 'nativeNXx64/ImgNX/Archive/uEm26.arc',
                          '31010f45f9c9a7d7d4f2ea7ca4397eb1e8c6e4e419093537b0185d5e2ba37472', ('em2600',), ('em2600',),
                          (64, 0, (0., 30., 60.)), ()),
    'uEm34': EnemyArchive('uEm34', 'nativeNXx64/ImgNX/Archive/uEm34.arc',
                          '6050bb8168d0e121a70d67551d19a5169ccc966b17936c829412c01f62ff617b', ('em3400',), ('em3400',),
                          (75, 0, (0., 30., 60.)), ('em3401', 'em3402', 'em3403')),
    'uEm92': EnemyArchive('uEm92', 'nativeNXx64/ImgNX/Archive/uEm92.arc',
                          '7da2e47838354ef3b43e5baf6df8ca50bab99f816b372aca925f51069684ea94', ('em9200',), ('em9200',),
                          (54, 105, (0., 30., 60.)), ('evf2800', 'evf2801', 'evf2803')),
}
#: Placed spawns per class in the No Mercy layouts of the eight stages (`re5_stage_enemies`, 2026-11-09): what a class
#: replacement covers. uEm10 is the horde of five stages; uEm12 Village and Ancient Ruins; uEm14 Experimental Facility.
#: Reunion-only classes carry their Reunion counts (`mercedc`).
STAGE_COVERAGE = {'uEm10': {'s400': 320, 's401': 369, 's405': 393, 's406': 385, 's407': 353},
                  'uEm11': {'s400': 72}, 'uEm12': {'s402': 325, 's403': 386}, 'uEm13': {'s401': 22, 's407': 28},
                  'uEm14': {'s404': 227}, 'uEm21': {'s400': 1},
                  'uEm20': {'s400': 6, 's407': 4}, 'uEm22': {'s406': 14}, 'uEm23': {'s405': 6, 's406 (Reunion)': 1},
                  'uEm24': {'s402': 8, 's403': 13}, 'uEm26': {'s407': 5}, 'uEm34': {'s401': 7},
                  'uEm92': {'s400 (Reunion)': 1}}
#: Classes the layouts place that no donor writer can take, with the measured reason (the archives were read):
#: the fifteen role animation ids exist on these skeletons but name bones whose bind pose is not a standing biped.
UNBUILDABLE_CLASSES = {
    'uEm32': {'spawns': {'s404': 172}, 'model': 'em3200 (83 bones, 16 records, one group) + _low/_mid',
              'sha256': '42ea8e01a4a7a07db4c68d001713a7e69ff14400930b14f465b330096672000c',
              'reason': 'a crawling body: the model is 27 cm tall at the bind pose, the pelvis and spine trunks cannot '
                        'be told apart, and the role ids put the left leg on -X and the feet level with the hips; a '
                        'standing donor fitted to those joints would lie on the floor in a knot'},
    'uEm0b': {'spawns': {'s402': 66, 's403 (Reunion)': 5, 's400 (Reunion)': 8},
              'model': 'em0b00 (70 bones, 21 records, one group)',
              'sha256': '01a2580b962fc43bea61188c3f5b2749ea56e57cffd0fd2fa2ca40c3f629a592',
              'reason': 'a quadruped 86 cm tall: the role ids name legs that rise instead of descending and hands below '
                        'the hips; no biped donor fits a four-legged bind pose'},
    'uEm62': {'spawns': {'s407': 10, 'every other stage': 1}, 'model': 'em6200 (20 bones, 60 records, two groups)',
              'sha256': '984fcb15141897644d8575035cf452f940edd6f62714a93aade74e6b2499c685',
              'reason': 'a flying body with 20 bones: the leg role ids are absent and no native record uses the '
                        "donor's vertex format (no template), so there is nothing to write a biped into"},
    'uEm30': {'spawns': {'s401 (Reunion)': 13}, 'model': 'em3000 (90 bones, 78 records, 7 groups), em3100 (94, 90, 2)',
              'sha256': 'b50b3208a4e05b401c55482dfd06e72e156f384a111e4fc920cdca6bc5b6db7b',
              'reason': 'the fifteen ids exist but sit on bones whose bind pose is no biped (hip at 16 cm beside the '
                        'left hand, the "legs" rising to 73 cm, left and right crossed), 119 cm tall; the montage '
                        'table (4 montages, 3 carriers) is readable but there is no body to fit a donor to'},
}


# --- donors -------------------------------------------------------------------------------------------------------

ROLES = tuple(ROLE_ANIMATION_IDS)


@dataclass(frozen=True)
class Donor:
    """A library character: its model file and the fifteen role joints its metadata names."""
    slug: str
    name: str
    model: Path
    sha256: str
    roles: dict = field(compare=False)
    provenance: dict = field(default_factory=dict, compare=False)
    winding: str = field(default='ccw', compare=False)     # 'cw' turns every triangle (the shared survey measures it)


def load_donor(entry: Path, *, sha256: str | None = None) -> Donor:
    """Read a library entry (`<slug>/meta.json` beside its model). Nothing is guessed: a rig whose metadata does not
    name all fifteen roles is refused with the missing roles, and `sha256` pins a reviewed model revision."""
    entry = Path(entry)
    try:
        meta = json.loads((entry / 'meta.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise EnemyWriterError(f'{entry.name} is not a library entry with a readable meta.json') from exc
    slug = str(meta.get('slug') or entry.name)
    rig = meta.get('rig') if isinstance(meta.get('rig'), dict) else {}
    named = rig.get('roles') if isinstance(rig.get('roles'), dict) else {}
    missing = [role for role in ROLES if not isinstance(named.get(role), str) or not named.get(role)]
    if missing:
        raise EnemyWriterError(f'{slug} has an incomplete rig: its metadata names no joint for {", ".join(missing)}')
    roles = {role: named[role] for role in ROLES}
    shared = sorted(role for role in ROLES if list(roles.values()).count(roles[role]) > 1)
    if shared:
        raise EnemyWriterError(f'{slug} has an incomplete rig: {", ".join(shared)} share a joint')
    name = meta.get('model')
    model = entry / name if isinstance(name, str) and name and Path(name).name == name else None
    if model is None or not model.is_file():
        raise EnemyWriterError(f'{slug} names no model file inside its library entry')
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    if sha256 is not None and digest != sha256:
        raise EnemyWriterError(f'{slug} is not the reviewed model revision {sha256[:12]}; this file is {digest[:12]}')
    source = meta.get('source') if isinstance(meta.get('source'), dict) else {}
    return Donor(slug=slug, name=str(meta.get('name') or slug), model=model, sha256=digest, roles=roles,
                 provenance={'game': source.get('game_title'), 'platform': source.get('platform'),
                             'files': source.get('files'), 'extraction_tool': meta.get('extraction_tool'),
                             'licence': meta.get('licence')})


def _donor_joints(gltf: dict, world, roles: dict[str, str], who: str) -> tuple[dict[str, int], dict[str, tuple]]:
    """({role: node}, {role: world position}); every named joint must exist exactly once."""
    nodes, wrong = {}, []
    for role, name in roles.items():
        found = [i for i, node in enumerate(gltf['nodes']) if node.get('name') == name]
        if len(found) != 1:
            wrong.append(f'{role} ({name!r}: {len(found)} joints)')
        else:
            nodes[role] = found[0]
    if wrong:
        raise EnemyWriterError(f'{who} needs exactly one joint named for every role; wrong: {", ".join(wrong)}')
    return nodes, {role: tuple(float(v) for v in world[node][:3, 3]) for role, node in nodes.items()}


ORPHAN_ROLE = 'hip'


def _role_owners(vertices: list[dict], gltf: dict, nodes: dict[str, int], orphans: set | None = None) -> list[set]:
    """The roles each vertex is carried by: every positive influence resolved to its nearest named ancestor.

    A joint with no role joint above it (a root above the hips, a prop hanging off the root) is carried by the hips;
    its node index is added to `orphans` so the build can say so.
    """
    parents = {child: i for i, node in enumerate(gltf['nodes']) for child in node.get('children', [])}
    by_node, cache = {node: role for role, node in nodes.items()}, {}

    def role_of(joint: int):
        chain, current = [], joint
        while current not in by_node and current not in cache:
            if current in chain or current not in parents:
                if orphans is not None:
                    orphans.add(joint)
                current = None
                break
            chain.append(current)
            current = parents[current]
        role = ORPHAN_ROLE if current is None else by_node[current] if current in by_node else cache[current]
        if current is not None:
            for seen in chain:
                cache[seen] = role
        return role
    return [{role_of(joint) for joint, weight in zip(vertex.get('source_joints', ()), vertex.get('source_weights', ()))
             if weight > 0} for vertex in vertices]


def check_rig(vertices: list[dict], owners: list[set], joints: dict[str, tuple], who: str) -> dict:
    """Refuse a donor whose named joints cannot be the roles they claim; return what was measured.

    Role metadata is trusted for which joint is which, never for whether the result is a body: the shoulders and the
    hips must be on opposite sides and agree with each other (a rig with its legs labelled the other way round would
    be built with crossed legs), every limb segment must have a length, the legs must descend, and the feet must show
    which way it faces. Where the arms point is a pose, not a fault: each limb is turned onto its native segment.
    """
    problems = []
    centre = joints['hip'][0]
    sides = {role: joints[role][0] - centre for role in ROLES if role[:2] in ('l_', 'r_')}
    left = 1. if sides['l_upper'] > sides['r_upper'] else -1.
    for part in ('upper', 'thigh'):
        if not sides[f'l_{part}'] * left > 0 > sides[f'r_{part}'] * left:
            problems.append(f'l_{part} and r_{part} are not on the sides the shoulders define')
    for side in 'lr':
        lengths = [float(np.linalg.norm(np.subtract(joints[a], joints[b]))) for a, b in (
            (f'{side}_upper', f'{side}_fore'), (f'{side}_fore', f'{side}_hand'),
            (f'{side}_thigh', f'{side}_shin'), (f'{side}_shin', f'{side}_foot'))]
        if min(lengths) < 1e-6:
            problems.append(f'a {side} limb segment has no length')
        if not joints[f'{side}_thigh'][1] > joints[f'{side}_shin'][1] > joints[f'{side}_foot'][1]:
            problems.append(f'the {side} leg does not descend thigh, shin, foot')
    if not joints['head'][1] > joints['chest'][1] >= joints['hip'][1] > joints['l_shin'][1]:
        problems.append('head, chest, hip and legs are not stacked upward')
    carried = {role: sum(role in owner for owner in owners) for role in ROLES}
    feet = [vertex['position'] for vertex, owner in zip(vertices, owners) if owner & {'l_foot', 'r_foot'}]
    forward = (float(np.mean([point[2] for point in feet])) - (joints['l_foot'][2] + joints['r_foot'][2]) / 2
               if feet else 0.)
    if not feet:
        problems.append('no vertex is carried by a foot, so nothing shows where the ground or the front is')
    elif forward * left <= 0:
        problems.append('the feet point away from the front that its left and right imply (a mirrored rig)')
    elif left < 0:
        problems.append('it faces -Z with its left on -X; the native skeleton faces +Z, and no half turn is applied')
    if problems:
        raise EnemyWriterError(f'{who} has an incomplete rig: ' + '; '.join(problems))
    return {'left_side': '+X', 'facing': '+Z', 'vertices_per_role': carried,
            'roles_without_vertices': [role for role in ROLES if not carried[role]]}


# --- fit ----------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Fit:
    """How a donor is sized on the native skeleton. Limbs always stretch to the native segment lengths and every role
    keeps its native joint; these are the cross-section scales of the parts between the joints.

    `limbs` (arms, legs, feet): None measures ground contact, so the soles land on model y 0.
    `torso` (hip and chest): None uses the limb scale; 'shoulders' puts the donor's shoulder joints on the native
    ones, so the arms meet the body however narrow or wide the donor is.
    `hands`: None uses the limb scale; 'torso_cap' keeps them from being larger than the torso scale.
    `head`: None uses the limb scale (the donor keeps its own head size). 'native_top' ends the head at `height`
    times the native model's top. A donor without a neck may then carry its head lower than the native head joint:
    when that gives the larger head, the head spans from the native shoulder height to that top and is moved down
    accordingly (it still turns on the native head joint). It is never larger than the torso or the limb scale.
    """
    name: str
    limbs: float | None = None
    torso: float | str | None = None
    head: float | str | None = None
    hands: float | str | None = None
    height: float = 1.


#: The first candidate's fit: one scale from ground contact. Live 2026-11-09 it drew SM64 DS Mario about 2.4 m tall.
PROPORTIONAL = Fit('proportional')
#: The donor at the native height: the head ends where the Majini's does, the torso spans the native shoulders.
NATIVE_HEIGHT = Fit('native_height', torso='shoulders', head='native_top', hands='torso_cap')
FITS = {'proportional': PROPORTIONAL, 'native_height': NATIVE_HEIGHT}
TORSO_ROLES, HEAD_ROLES, HAND_ROLES = ('hip', 'chest'), ('head',), ('l_hand', 'r_hand')
#: The role joints and the top of `em1000` as measured (cm). Only used to judge a donor's fit without an archive at
#: hand (the hole test of a library survey); every build measures its own model.
REFERENCE_BIND = {'hip': (0., 114., 0.), 'chest': (0., 132., -1.34), 'head': (0., 165., -2.34),
                  'l_upper': (17.2, 150.78, -3.44), 'l_fore': (43.6, 150.78, -3.44), 'l_hand': (70.4, 150.78, -3.44),
                  'r_upper': (-17.2, 150.78, -3.44), 'r_fore': (-43.6, 150.78, -3.44), 'r_hand': (-70.4, 150.78, -3.44),
                  'l_thigh': (9.2, 101., 0.), 'l_shin': (9.2, 57.45, 0.), 'l_foot': (9.2, 13.5, 0.),
                  'r_thigh': (-9.2, 101., 0.), 'r_shin': (-9.2, 57.45, 0.), 'r_foot': (-9.2, 13.5, 0.)}
REFERENCE_TOP = 185.64


def fit_scales(fit: Fit, vertices: list[dict], owners: list[set], joints: dict[str, tuple],
               native: dict[str, tuple], native_top: float) -> tuple[float, dict[str, float], dict[str, tuple], dict]:
    """(limb scale, {role: scale} where it differs, {role: offset}, what was measured) for one donor and bind pose."""
    for value in (fit.limbs, fit.torso, fit.head, fit.hands, fit.height):
        if isinstance(value, (int, float)) and not (np.isfinite(value) and value > 0):
            raise EnemyWriterError('fit scales must be finite and positive')
    measured, rule = _contact_scale(vertices, joints, native)
    limbs = float(fit.limbs) if fit.limbs is not None else measured
    report = {'fit': fit.name, 'limbs': limbs, 'ground_contact': rule,
              'limbs_source': 'caller' if fit.limbs is not None else 'measured ground contact'}
    torso = limbs
    if fit.torso == 'shoulders':
        donor_span = abs(joints['l_upper'][0] - joints['r_upper'][0])
        if donor_span <= 1e-6:
            raise EnemyWriterError('the donor shoulders do not span a width')
        torso = abs(native['l_upper'][0] - native['r_upper'][0]) / donor_span
        report['torso_rule'] = 'native shoulder span over donor shoulder span'
    elif fit.torso is not None:
        if isinstance(fit.torso, str):
            raise EnemyWriterError("the torso scale is a number, None or 'shoulders'")
        torso = float(fit.torso)
    hands = limbs
    if fit.hands == 'torso_cap':
        hands = min(limbs, torso)
        report['hands_rule'] = 'limb scale, never above the torso scale'
    elif fit.hands is not None:
        if isinstance(fit.hands, str):
            raise EnemyWriterError("the hand scale is a number, None or 'torso_cap'")
        hands = float(fit.hands)
    head, offsets = limbs, {}
    if fit.head == 'native_top':
        heights = [vertex['position'][1] for vertex, owner in zip(vertices, owners) if 'head' in owner]
        rise = (max(heights) - joints['head'][1]) if heights else 0.
        top = fit.height * native_top
        shoulder = (native['l_upper'][1] + native['r_upper'][1]) / 2
        if rise <= 1e-6 or top - native['head'][1] <= 1e-6 or top - shoulder <= 1e-6:
            raise EnemyWriterError('the donor head does not rise above its joint, so it cannot be fitted to a height')
        on_joint, sunk = (top - native['head'][1]) / rise, (top - shoulder) / (max(heights) - min(heights))
        limit = max(torso, limbs)
        head = min(max(on_joint, sunk), limit)
        drop = 0.
        if sunk > on_joint:                          # no neck: the head reaches down to the shoulder line
            drop = min(0., top - (native['head'][1] + head * rise))     # never lifted off its joint
            offsets = {role: (0., float(drop), 0.) for role in HEAD_ROLES} if abs(drop) > 1e-9 else {}
        report['head_rule'] = (f'top of the head at {fit.height:g} x the native top; '
                               + ('spanning down to the native shoulder height' if sunk > on_joint
                                  else 'standing on the native head joint')
                               + ('' if head < limit else '; kept at the body scale, so it ends lower'))
        report.update(native_top=float(native_top), head_drop=float(drop))
    elif fit.head is not None:
        if isinstance(fit.head, str):
            raise EnemyWriterError("the head scale is a number, None or 'native_top'")
        head = float(fit.head)
    report.update(torso=float(torso), head=float(head), hands=float(hands))
    report['shape'] = _fitted_shape(vertices, owners, joints, native, torso, head,
                                    offsets.get('head', (0., 0., 0.))[1])
    scales = {role: float(torso) for role in TORSO_ROLES if torso != limbs}
    scales.update({role: float(head) for role in HEAD_ROLES if head != limbs})
    scales.update({role: float(hands) for role in HAND_ROLES if hands != limbs})
    return limbs, scales, offsets, report

OPTION_GROUP_DECISION = {
    'choice': 'carry_in_every_group',
    'native_records': 'kept byte for byte; index words collapsed so each draws only degenerate triangles',
    'donor_records': 'one per option group, all LODs, the complete donor in each',
    'why': ('This shape does not depend on how a spawn selects its groups. A donor placed in one group would be '
            'invisible whenever that group is not selected or is hidden (a destroyed head); a donor split across '
            'slots would lose parts on a spawn that skips a slot (the montages with the bare-torso arm skin 222 '
            'select no shirt group). Every group therefore carries the whole donor, so any selection draws it. '
            'Copies drawn together are the same vertex bytes, bones and material and are expected to resolve to the '
            'same depth and colour. The game has loaded and drawn this shape (SM64 DS Mario, 2026-11-09); whether '
            'the copies shimmer could not be judged from the frame.'),
    'undetermined_offline': [
        'how the game picks a montage for a spawn whose layout says -1, and whether it hides groups during damage '
        'or death (the montage table of the archive lists the combinations; see MONTAGE_READING)',
        'which of the high / mid / low models an enemy draws at a distance (model type 0, the xx00 set, is what every '
        'Mercenaries layout asks for)',
        'whether the 32-byte group table spheres are used for culling (they are left native)',
        'whether a record without a native depth-only proxy (mesh type 0x1020) casts a shadow',
        'how the native atlas material shades this surface, and whether overlapping copies show under blending'],
}


def _extent(vertices: list[dict], owners: list[set], role: str) -> tuple[float, float] | None:
    heights = [vertex['position'][1] for vertex, owner in zip(vertices, owners) if role in owner]
    return (min(heights), max(heights)) if heights else None


def _fitted_shape(vertices, owners, joints, native, torso: float, head: float, drop: float) -> dict:
    """Where the fitted torso and head end up (cm): the highest chest vertex and the middle of the head. Recorded as
    a fact for the reviewer; a collar behind a head and a head inside a torso give the same numbers."""
    chest, skull = _extent(vertices, owners, 'chest'), _extent(vertices, owners, 'head')
    shape = {'torso_top': None, 'head_middle': None}
    if chest is not None:
        shape['torso_top'] = float(native['chest'][1] + torso * (chest[1] - joints['chest'][1]))
    if skull is not None:
        shape['head_middle'] = float(native['head'][1] + drop + head * ((skull[0] + skull[1]) / 2 - joints['head'][1]))
    return shape


def fitted_points(vertices: list[dict], gltf: dict, world, nodes: dict[str, int], native: dict[str, tuple],
                  limbs: float, role_scales: dict, role_offsets: dict, *, orphans: bool = False) -> list[tuple]:
    """The donor's vertices where a build would put them on the bind pose `native` (the transfer alone, no archive)."""
    from . import mtf_retarget
    parents = {child: i for i, node in enumerate(gltf['nodes']) for child in node.get('children', [])}
    points = {i: tuple(float(v) for v in matrix[:3, 3]) for i, matrix in enumerate(world)}
    order = list(ROLES)
    fitted, _ = mtf_retarget.transfer(
        vertices, points, parents, {k: tuple(native[role]) for k, role in enumerate(order)},
        {role: (nodes[role], k) for k, role in enumerate(order)}, dict(SEGMENTS), scale=limbs,
        role_scales=role_scales or None, role_offsets=role_offsets or None,
        orphan_role=ORPHAN_ROLE if orphans else None)
    return [vertex['position'] for vertex in fitted]


def vertical_holes(points: list[tuple], triangles: list[tuple], low: float, high: float,
                   least: float = 3.) -> list[tuple[float, float]]:
    """Heights between `low` and `high` that no triangle of the fitted donor spans, at least `least` cm tall: a body
    whose parts do not meet there (a chest floating above its hips, a head above its neck)."""
    spans = sorted((min(points[i][1] for i in face), max(points[i][1] for i in face)) for face in triangles)
    holes, reached = [], low
    for bottom, top in spans:
        if bottom > reached and min(bottom, high) - reached >= least:
            holes.append((float(reached), float(min(bottom, high))))
        reached = max(reached, top)
        if reached >= high:
            break
    if high - reached >= least:
        holes.append((float(reached), float(high)))
    return holes


# --- skeleton -----------------------------------------------------------------------------------------------------

def measure_roles(model: mt_model.ModFile) -> tuple[dict[str, int], dict]:
    """{role: bone index} read from the bind pose alone: the hierarchy and where each joint sits.

    No animation id is consulted. The root has two trunks, the one that reaches the floor (pelvis) and the one that
    reaches the top (spine). Legs are the pelvis' two deep branches; the chest is where the spine splits into two
    lateral arms and a midline neck; a hand is the last joint stacked on the wrist. Left is the +X side when the toes
    point to +Z.

    Two shapes measured on `uEm11.arc` are read the same way: a ground bone at the origin whose only chain is the
    body root (`em1100`, `em1101`), and helper chains as deep as the limb they hang from (the `em1101` skirt bones
    under each thigh). A tie in depth is settled by anatomy only - a leg continues through the child that reaches the
    floor, an arm through the child that reaches farthest from the midline - and stays an error when that is not
    unique. A third shape, measured on `uEm12.arc` and `uEm14.arc`: beside the body root the table holds a second
    root with no children (an unskinned attachment bone at the origin, animation id 250). Such detached bones are
    listed in the report and play no part; a second root WITH children is still refused.
    """
    table = model.bone_table()
    parents = [int(p) for p in table.get('parents', [])]
    points = {i: np.array((x, y, z), float) for i, x, y, z in model.bone_world()}
    count = len(parents)
    if not table.get('consistent') or not count or len(points) != count:
        raise EnemyWriterError('the enemy skeleton is incomplete')
    if any(parent != 255 and parent >= i for i, parent in enumerate(parents)):
        raise EnemyWriterError('the enemy skeleton needs parents stored before their children')
    roots = [i for i, parent in enumerate(parents) if parent == 255]
    detached = [i for i in roots if i not in parents]
    roots = [i for i in roots if i in parents]
    if len(roots) != 1:
        raise EnemyWriterError('the enemy skeleton needs one root with children')
    children = {i: [] for i in range(count)}
    depth, low, high = [1] * count, [points[i][1] for i in range(count)], [points[i][1] for i in range(count)]
    middle = points[roots[0]][0]
    wide = [abs(points[i][0] - middle) for i in range(count)]
    for i in range(count - 1, -1, -1):
        parent = parents[i]
        if parent != 255:
            children[parent].insert(0, i)
            depth[parent] = max(depth[parent], depth[i] + 1)
            low[parent], high[parent] = min(low[parent], low[i]), max(high[parent], high[i])
            wide[parent] = max(wide[parent], wide[i])

    def main(bone: int, what: str) -> int:
        best = max((depth[c] for c in children[bone]), default=0)
        picks = [c for c in children[bone] if depth[c] == best]
        if len(picks) > 1 and what in ('leg', 'toe', 'arm'):
            reach = (lambda c: -low[c]) if what in ('leg', 'toe') else (lambda c: wide[c])
            far = max(reach(c) for c in picks)
            picks = [c for c in picks if far - reach(c) < 1e-3]
        if len(picks) != 1:
            raise EnemyWriterError(f'the {what} chain is ambiguous at bone {bone}')
        return picks[0]

    root, ground = roots[0], []
    while True:
        trunks = [c for c in children[root] if depth[c] >= 3]
        if len(trunks) != 1:
            break
        ground.append(root)                # a bone whose only chain is the body below it (the origin bone of em1100)
        root = trunks[0]
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
    if ground:
        extra['ground_bones'] = ground
    if detached:
        extra['detached_bones'] = detached
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
            if len(stacked) > 1:          # em1100: a childless helper is stacked there too; the hand carries fingers
                stacked = [c for c in stacked if depth[c] > 1]
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


def check_role_geometry(model: mt_model.ModFile, roles: dict[str, int]) -> dict:
    """Hold a role map that came from the animation ids alone against the bind pose: fifteen distinct bones, the left
    side on +X, legs that descend thigh, shin, foot, arms that run outward upper, fore, hand, head above chest above
    the thighs and hips above the shins. Facing is not measured here (every RE5 pawn skeleton read so far faces +Z).
    Returns what was checked; anything else raises."""
    points = {i: np.array((x, y, z), float) for i, x, y, z in model.bone_world()}
    if len(set(roles.values())) != 15 or any(bone not in points for bone in roles.values()):
        raise EnemyWriterError('the animation ids do not name fifteen distinct bones of this skeleton')
    at = {role: points[bone] for role, bone in roles.items()}
    problems = []
    for part in ('upper', 'fore', 'hand', 'thigh', 'shin', 'foot'):
        if not at[f'l_{part}'][0] > at[f'r_{part}'][0]:
            problems.append(f'l_{part} is not on the +X side of r_{part}')
    for side in 'lr':
        if not at[f'{side}_thigh'][1] > at[f'{side}_shin'][1] > at[f'{side}_foot'][1]:
            problems.append(f'the {side} leg does not descend thigh, shin, foot')
        reach = [abs(at[f'{side}_{part}'][0] - at['hip'][0]) for part in ('upper', 'fore', 'hand')]
        if not reach[0] < reach[1] < reach[2]:
            problems.append(f'the {side} arm does not run outward upper, fore, hand')
    if not at['head'][1] > at['chest'][1] > at['l_thigh'][1] or not at['hip'][1] > at['l_shin'][1]:
        problems.append('head, chest, hips and legs are not stacked upward')
    if problems:
        raise EnemyWriterError('the animation ids name bones that cannot be the roles: ' + '; '.join(problems))
    return {'left_side': '+X', 'facing': 'assumed +Z (not measured by this path)', 'legs_descend': True,
            'arms_outward': True, 'stacked_upward': True}


def role_map(model: mt_model.ModFile, *, allow_ids: bool = False) -> tuple[dict[str, int], dict]:
    """The role map, accepted when the bind-pose measurement and the animation ids name the same bones.

    `allow_ids` takes the animation ids alone where the bind-pose measurement refuses the skeleton (the executioner's
    chest carries more than two arms' worth of branches, the giant's and the chainsaw men's likewise), provided
    `check_role_geometry` holds; the evidence then says so and names the refusal.
    """
    named = roles_by_animation_id(model)
    try:
        measured, extra = measure_roles(model)
    except EnemyWriterError as exc:
        if not allow_ids:
            raise
        extra = check_role_geometry(model, named) | {'bind_pose_measurement': f'refused: {exc}'}
        measured, method = named, ('RE5 animation ids, geometry-checked; the bind-pose hierarchy measurement refused '
                                   'this skeleton (see skeleton.bind_pose_measurement)')
    else:
        if measured != named:
            wrong = sorted(role for role in named if measured.get(role) != named[role])
            raise EnemyWriterError(f'the bind pose and the animation ids disagree on {wrong}')
        method = 'bind-pose hierarchy and joint positions, cross-checked against RE5 animation ids'
    points = {i: (x, y, z) for i, x, y, z in model.bone_world()}
    return measured, {'method': method,
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
    if len(set(reviewed)) != len(reviewed):
        raise EnemyWriterError('the reviewed option-group list must hold distinct ids')
    if sorted(table) != sorted(reviewed) or not used <= set(reviewed):
        raise EnemyWriterError(f'option groups differ from the reviewed list: unreviewed '
                               f'{sorted((set(table) | used) - set(reviewed))}, absent {sorted(set(reviewed) - set(table))}')
    slots = target.slot_of()
    out = {}
    for group in reviewed:
        own = [record for record in records if record['group_index'] == group]
        masks = sorted({record['level_of_detail'] for record in own})
        if not own or any(mask not in target.lod_masks for mask in masks):
            raise EnemyWriterError(f'option group {group} does not have the measured native LOD records '
                                   f'(masks {masks}; reviewed {list(target.lod_masks)})')
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


def _union_bounds(boxes: list[dict]) -> dict:
    """One box and sphere around several donors' bounds; a single donor keeps its own values bit for bit."""
    if all(box == boxes[0] for box in boxes):
        return boxes[0]
    low = {a: min(box['min'][a] for box in boxes) for a in 'xyz'}
    high = {a: max(box['max'][a] for box in boxes) for a in 'xyz'}
    centre = {a: (low[a] + high[a]) / 2 for a in 'xyz'}
    radius = max(float(np.linalg.norm([box['sphere'][a] - centre[a] for a in 'xyz'])) + box['sphere']['r']
                 for box in boxes)
    return {'min': low, 'max': high, 'sphere': centre | {'r': radius}}


def graft_pieces(native: mt_model.ModFile, pieces: list[tuple[mt_model.ModFile, list[int], int]], *,
                 template: int | None = None) -> tuple[bytes, dict]:
    """Add each one-mesh donor of `pieces` (donor, option groups, material index) to `native` once per group of its
    own, and make every native record draw nothing.

    The native table is not reshaped: each native record keeps its 56 bytes (group, material, LOD mask, mesh id,
    offsets), its vertex bytes and its envelope records. Only its index words change, to the record's own first vertex,
    so every strip is degenerate while restart markers and counts stay. A donor's vertex, index and envelope bytes
    are appended once per group as a new record (LOD mask 0xFF, ids after the native ones), inserted behind the last
    native record of the same material so the table stays sorted by material as shipped. No group may be given to two
    donors: a spawn that selects it would draw both.

    ``template`` names the native record whose opaque bytes the donor records start from; by default the first native
    four-weight record (`_template`, RE5's shape). RE6's records carry other mesh types (0xFDF7, 0x1020), so its writer
    passes the record its one-mesh donor was itself authored from (`re6_switch_enemies.template_mesh`).
    """
    header, records = native.header(), native.meshes()
    count, offsets = len(records), header['offsets']
    if not records or not native.split_valid() or native.position_transform() is None:
        raise EnemyWriterError('the native model needs a complete mesh table and skeleton')
    if sorted(record['mesh_id'] for record in records) != list(range(1, count + 1)):
        raise EnemyWriterError('native mesh ids are not the measured permutation of 1..count')
    if any(not record['vertex_index'] <= record['min_index'] <= record['max_index']
           <= record['vertex_index'] + record['vertex_count'] - 1 for record in records):
        raise EnemyWriterError('a native record does not address its own vertex window')
    every = [group for _, groups, _ in pieces for group in groups]
    if not pieces or not every or len(set(every)) != len(every) or count + len(every) > 0xFFFF:
        raise EnemyWriterError('choose distinct option groups for the donor records')
    if any(not groups for _, groups, _ in pieces):
        raise EnemyWriterError('every donor needs at least one option group')
    if any(not 0 <= material < header['material_count'] for _, _, material in pieces):
        raise EnemyWriterError('the donor material is outside the model')
    native_envelopes, words = _envelopes(native), _index_words(native)
    for record in records:
        span = words[record['face_index']:record['face_index'] + record['face_count']]
        real = span != 0xFFFF
        if real.any() and (span[real].min() < record['min_index'] or span[real].max() > record['max_index']):
            raise EnemyWriterError('a native record indexes outside its vertex window')
        span[real] = record['min_index']
    native_vertices = native.raw[offsets['vertex_buffer']:offsets['index_buffer']]
    if len(native_vertices) % 4:
        raise EnemyWriterError('vertex data must stay four-byte aligned')
    if template is None:
        template = _template(records)
    elif not 0 <= template < count:
        raise EnemyWriterError(f'template record {template} is outside the native table')
    faces = header['face_count']
    vertex_buffer, index_buffer = [native_vertices], [words.astype('<u2').tobytes()]
    vertex_at, face_at, serial = len(native_vertices), faces, 0
    added, reports, boxes, vertex_total, triangle_total = [], [], [], 0, 0
    for donor, groups, material_index in pieces:
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
        if len(vertices) % 4:
            raise EnemyWriterError('vertex data must stay four-byte aligned')
        fields = ({name: piece[name] for name, _, _ in mt_model.MOD_MESH_FIELDS}
                  | {'vertex_format': piece['vertex_format']})
        for group in groups:
            serial += 1
            added.append((fields | {'_template_index': template, 'group_index': group,
                                    'material_index': material_index, 'level_of_detail': ALL_LODS,
                                    'vertex_offset': vertex_at, 'face_index': face_at, 'mesh_id': count + serial},
                          envelopes))
            vertex_buffer.append(vertices)
            index_buffer.append(indices)
            vertex_at += len(vertices)
            face_at += piece['face_count'] + 1
        vertex_total += len(groups) * piece['vertex_count']
        triangle_total += len(groups) * triangles
        boxes.append(donor.bounds())
        reports.append({'groups': list(groups), 'material_index': material_index,
                        'donor_vertices_per_record': piece['vertex_count'], 'donor_triangles_per_record': triangles,
                        'donor_envelopes_per_record': piece['vertex_group_count'],
                        'inserted_at': next((i for i, record in enumerate(records)
                                             if record['material_index'] > material_index), count)})
    # the table stays sorted by material: natives first within a material, then the donor records in the order given
    rows = [((record['material_index'], 0, i), record, native_envelopes[i]) for i, record in enumerate(records)]
    rows += [((record['material_index'], 1, k), record, envelopes) for k, (record, envelopes) in enumerate(added)]
    if [row[0] for row in rows[:count]] != sorted(row[0] for row in rows[:count]):
        raise EnemyWriterError('the native mesh table is not sorted by material')
    rows.sort(key=lambda row: row[0])
    table, trailer = [row[1] for row in rows], b''.join(row[2] for row in rows)
    indices_out = b''.join(index_buffer)
    indices_out += bytes(len(indices_out) % 4)
    result = mt_model.rebuild_mod(
        native, vertex_buffer=b''.join(vertex_buffer), index_buffer=indices_out,
        mesh_records=table, mesh_count=len(table), vertex_count=header['vertex_count'] + vertex_total,
        face_count=face_at, edge_count=header['polygon_count'] + triangle_total, bounds=_union_bounds(boxes),
        mesh_trailer=trailer)
    return result, {'native_records': count, 'donor_records': len(added), 'mesh_records': len(table),
                    'envelope_count': len(trailer) // mt_model.MOD_WEIGHT_BOUND, 'template_record': template,
                    'native_index_words_collapsed': int(sum(record['face_count'] for record in records)),
                    'model_bytes': len(result), 'pieces': reports}


def graft(native: mt_model.ModFile, donor: mt_model.ModFile, *, groups: list[int],
          material_index: int) -> tuple[bytes, dict]:
    """Add the one-mesh `donor` to `native` once per option group and make every native record draw nothing
    (`graft_pieces` with one donor; this is the shape the game has loaded and drawn)."""
    result, report = graft_pieces(native, [(donor, list(groups), material_index)])
    piece = report.pop('pieces')[0]
    return result, report | {key: piece[key] for key in ('donor_vertices_per_record', 'donor_triangles_per_record',
                                                         'donor_envelopes_per_record', 'material_index',
                                                         'inserted_at')}


def _material(mrl: bytes, model: mt_model.ModFile, target, *, unique: bool = True) -> tuple[int, dict]:
    """The native material that samples the atlas texture, with its secondary maps confirmed.

    A set's one atlas must belong to exactly one material. A mix carrier (`unique=False`) may be sampled by several
    materials of the same part (its LOD materials): every native record is blanked there, so the first one in table
    order is taken and all of them must bind the same reviewed maps.
    """
    rows = [row for row in mtf_mrl.inspect_bindings(mrl, model)
            if any(b['shader_hash'] == mtf_mrl.ALBEDO_HASH and b['path'] == target.albedo[1] for b in row['bindings'])]
    if len(rows) != 1 and (unique or not rows):
        raise EnemyWriterError('exactly one native material must sample the reviewed atlas texture')
    for row in rows:
        paths = {b['shader_hash']: b['path'] for b in row['bindings']}
        if paths.get(NORMAL_HASH) != target.normal[1] or paths.get(MASK_HASH) != target.mask[1]:
            raise EnemyWriterError('the atlas material does not bind the reviewed normal and mask maps')
    return rows[0]['mod_index'], {'index': rows[0]['mod_index'], 'name': rows[0]['name'],
                                  'albedo': target.albedo[1], 'normal': target.normal[1], 'mask': target.mask[1],
                                  'materials_sampling_it': len(rows)}


def _neutral(parsed: mt_arc.Arc, maps: list[tuple[tuple[int, str], tuple[int, ...]]], payloads: dict[int, bytes],
             kept: list[str]) -> None:
    """Flatten the normal maps and zero the mask maps named in `maps` ((entry, name), channel values) into
    `payloads`. A map whose texture format the codec does not decode (em1300's `_CMM` masks, format 0x13) is left as
    shipped and its name appended to `kept`; nothing is guessed about such a texture."""
    tried: set[int] = set()
    for (index, name), value in maps:
        if index in payloads or index in tried:
            continue
        tried.add(index)
        raw = _entry(parsed, index, name, b'TEX\0')
        try:
            payloads[index] = mtf_secondary.constant_channels(raw, value)
        except ValueError as exc:
            if 'unsupported Switch TEX format' not in str(exc):
                raise EnemyWriterError(f'{name.rsplit(chr(92), 1)[-1]} is not a secondary map the writer can '
                                       f'neutralise: {exc}') from exc
            kept.append(name.rsplit('\\', 1)[-1])


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
           segments: dict[str, str] | None = None, scale: float | None = None, secondary: str = 'neutral',
           fit: Fit | None = None, who: str = 'the donor', reverse_winding: bool = False):
    """Return (archive, receipt) with every model of `target` carrying the donor; inputs are not hash-checked here.

    `fit` sizes the donor (see `Fit`). Left unset it is the first candidate's fit: one cross-section and extremity
    scale, `scale` when given and otherwise measured so the soles meet the ground; limbs always stretch to the native
    segment lengths. `secondary='neutral'` flattens the atlas material's normal map and zeroes its mask (its native
    detail would be sampled through unrelated atlas UVs); `'native'` leaves both maps as shipped. A map in a texture
    format the codec cannot rewrite stays native either way and is named in the receipt. `reverse_winding` turns each
    triangle of a donor exported with clockwise fronts (the shared donor survey measures the winding).
    """
    if secondary not in ('neutral', 'native'):
        raise EnemyWriterError("secondary maps are either 'neutral' or 'native'")
    if fit is not None and scale is not None:
        raise EnemyWriterError('give the scale inside the fit, not beside it')
    fit = fit if fit is not None else Fit('proportional', limbs=scale)
    source, source_roles, segments = Path(source), dict(source_roles or SOURCE_ROLES), dict(segments or SEGMENTS)
    if set(source_roles) != set(ROLE_ANIMATION_IDS):
        raise EnemyWriterError('the donor must name the fifteen measured roles')
    parsed = mt_arc.parse(archive)
    indices = [i for _, mod, mrl in target.models for i in (mod, mrl)] + [target.albedo[0], target.normal[0],
                                                                          target.mask[0]]
    if len(set(indices)) != len(indices) or not target.models:
        raise EnemyWriterError('the reviewed entry indices must be distinct')
    texture = _entry(parsed, *target.albedo, b'TEX\0')
    for maps in (target.normal, target.mask):              # the secondary maps must be the reviewed TEX entries
        _entry(parsed, *maps, b'TEX\0')
    surface = mtf_tex.parse(texture)
    vertices, triangles, _, appearance = mtf_materials.source_mesh(source, atlas_size=(surface.width, surface.height),
                                                                   strict_samplers='in_range')
    gltf, _, _, world = characters._load(source)
    nodes, joints = _donor_joints(gltf, world, source_roles, who)
    orphans: set = set()
    owners = _role_owners(vertices, gltf, nodes, orphans)
    rig = check_rig(vertices, owners, joints, who) | {
        'joints_outside_the_roles': sorted(str(gltf['nodes'][i].get('name', i)) for i in orphans),
        'carried_by': ORPHAN_ROLE if orphans else None}

    payloads: dict[int, bytes] = {}
    models, atlas_payload, fitted, groups, positions, top = {}, None, None, None, None, None
    for name, mod_index, mrl_index in target.models:
        native_raw, mrl = _entry(parsed, mod_index, name, b'MOD\0'), _entry(parsed, mrl_index, name, b'MRL\0')
        native, short = mt_model.parse_mod(native_raw), name.rsplit('\\', 1)[-1]
        accounted = account_groups(native, target)
        roles, evidence = role_map(native, allow_ids=target.roles_by_ids)
        material_index, material = _material(mrl, native, target, unique=not target.shared_atlas)
        template = _template(native.meshes())
        top = top if top is not None else float(native.bounds()['max']['y'])     # one head size for every LOD model
        used, role_scales, role_offsets, sizes = fit_scales(fit, vertices, owners, joints,
                                                            evidence['bind_position'], top)
        try:
            result, donor_raw, _, imported = re5_mesh_import.build_archive(
                archive, source, model_name=short, source_roles=source_roles, target_roles=roles,
                segments=segments, scale=used, material_index=material_index, template_index=template,
                pose_mode='native_segments', samplers_in_range=True, reverse_winding=reverse_winding,
                **({'role_scales': role_scales} if role_scales else {}),
                **({'role_offsets': role_offsets} if role_offsets else {}),
                **({'orphan_role': ORPHAN_ROLE} if orphans else {}))
        except EnemyWriterError:
            raise
        except ValueError as exc:
            raise EnemyWriterError(f'{who} cannot be fitted on {short}: {exc}') from exc
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
        this_fit = {'pose_mode': imported['pose_mode'], 'cross_section_scale': used,
                    'ground_contact': sizes['ground_contact'], 'scale_source': sizes['limbs_source'],
                    'bounds': imported['bounds'], 'native_bounds': imported['original_bounds'],
                    'height': imported['bounds']['max']['y'] - imported['bounds']['min']['y'],
                    'native_height': imported['original_bounds']['max']['y'] - imported['original_bounds']['min']['y'],
                    'name': fit.name, 'role_scales': role_scales,
                    'role_offsets': {role: list(offset) for role, offset in role_offsets.items()},
                    'scales': {'limbs': used, 'torso': sizes['torso'], 'head': sizes['head'], 'hands': sizes['hands']},
                    'rules': {key: sizes[key] for key in ('torso_rule', 'hands_rule', 'head_rule', 'native_top',
                                                          'head_drop') if key in sizes},
                    'shape': sizes['shape']}
        if fitted is not None and any(fitted[key] != this_fit[key] for key in ('cross_section_scale', 'role_scales',
                                                                              'role_offsets')):
            raise EnemyWriterError('the models of one set must be fitted with the same scales')
        fitted = fitted or this_fit
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
    kept_native: list[str] = []
    if secondary == 'neutral':
        _neutral(parsed, [(target.normal, (128, 128)), (target.mask, (0,))], payloads, kept_native)
    output = archive
    for index in sorted(payloads):                 # explicit index, never a name: MOD and MRL share names
        output = mtf_author.replace_archive_model(output, index, payloads[index])
    textures = [target.albedo[0]] + [index for index in (target.normal[0], target.mask[0]) if index in payloads]
    checks = verify(archive, output, target, secondary=secondary, textures=textures)
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
        'fit': fitted | {'segments': segments, 'bind_joints_moved': False, 'native_motion_edited': False},
        'donor_rig': rig,
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
            'secondary_maps_kept_native': kept_native, 'winding_reversed': bool(reverse_winding),
            'normals': 'recomputed from the fitted triangles; flat wherever the donor splits its vertices per face',
            'shared_texture_note': 'the atlas, normal and mask entries are also sampled by other models of this '
                                   'archive that are not replaced; the part that wears this material there shows '
                                   'the edited maps'},
        'checks': checks, 'live_verified': False, 'gameplay_verified': False, 'writer_registered': False}
    return output, receipt


# --- verification -------------------------------------------------------------------------------------------------

def _check_model(native_raw: bytes, raw: bytes, target: EnemySet, expect: dict | None = None) -> dict:
    """Re-parse one written model against its native original; every measured format rule must hold.

    `expect` is {option group: (material index, donor key)} for a mix: exactly those groups carry a donor record, a
    key's groups share one donor's bytes, and each record uses its carrier's material. Left unset, every reviewed
    group carries the same donor through one material.
    """
    def need(condition, message):
        if not condition:
            raise EnemyWriterError(f'written model check failed: {message}')

    native, model = mt_model.parse_mod(native_raw), mt_model.parse_mod(raw)
    before, header = native.header(), model.header()
    old, new = before['offsets'], header['offsets']
    originals, records = native.meshes(), model.meshes()
    reviewed, size = target.group_ids(), mt_model.MOD_MESH_RECORD_V211
    carried = sorted(expect) if expect is not None else sorted(reviewed)
    need(carried and set(carried) <= set(reviewed), 'carrier groups are reviewed option groups')
    need((header['version'], header['revision']) == (211, 0) and model.variant == 'model', 'MOD version')
    need(native.raw[old['bones']:old['meshes']] == model.raw[new['bones']:new['meshes']],
         'skeleton, group table and material names are native')
    need(native.raw[0x90:0xA0] == model.raw[0x90:0xA0] and raw[new['end']:] == native_raw[old['end']:],
         'LOD distances and file trailer are native')
    need(len(records) == header['mesh_count'] == len(originals) + len(carried), 'mesh count')
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
             and record['vertex_index'] <= record['min_index']
             and record['max_index'] - record['vertex_index'] <= record['vertex_count'] - 1
             and (record['mesh_id'] <= len(originals)
                  or record['max_index'] - record['min_index'] == record['vertex_count'] - 1),
             'indices inside the vertex window')
        need(mt_model.fvf_stride(record['vertex_format']) == record['vertex_stride'], 'vertex format stride')
        (donors if record['mesh_id'] > len(originals) else natives).append(i)     # donor ids follow the native ones
    need(len(natives) == len(originals) and all(records[i]['level_of_detail'] in target.lod_masks for i in natives)
         and all(records[i]['level_of_detail'] == ALL_LODS for i in donors), 'native records keep their LOD masks')
    native_vertices = native.raw[old['vertex_buffer']:old['index_buffer']]
    need(raw[new['vertex_buffer']:new['vertex_buffer'] + len(native_vertices)] == native_vertices,
         'native vertex bytes are untouched')
    native_words = np.frombuffer(native_raw[old['index_buffer']:old['index_buffer'] + 2 * before['face_count']], '<u2')
    need(np.array_equal(words[:len(native_words)] == 0xFFFF, native_words == 0xFFFF), 'native strip restarts are kept')
    old_envelopes, cursor, kept, drawn = _envelopes(native), new['meshes'] + size * len(records), 0, 0
    native_rows = set(natives)
    for i, record in enumerate(records):
        length = mt_model.MOD_WEIGHT_BOUND * record['vertex_group_count']
        if i in native_rows:
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
    need(sorted(records[i]['group_index'] for i in donors) == carried, 'one donor record per carrying option group')
    first = records[donors[0]]
    wanted = expect if expect is not None else {group: (first['material_index'], 0) for group in reviewed}
    need(all((records[i]['material_index'], records[i]['vertex_format'], records[i]['vertex_stride'],
              records[i]['mesh_type'], records[i]['vertex_index']) ==
             (wanted[records[i]['group_index']][0], DONOR_FORMAT, DONOR_STRIDE, 0xFFFF, 0) for i in donors),
         'donor record shape')
    need(sorted(records[i]['mesh_id'] for i in donors) == list(range(len(originals) + 1, len(records) + 1)),
         'donor mesh ids follow the native ids')
    by_key = {}
    for i in donors:
        data, record = model.mesh_bytes(i)
        by_key.setdefault(wanted[record['group_index']][1], []).append(
            (i, (data, words[record['face_index']:record['face_index'] + record['face_count']].tobytes())))
    need(all(len({blob for _, blob in rows}) == 1 for rows in by_key.values()),
         'every option group of one donor carries the same donor bytes')
    box = model.bounds()
    low, high = (np.array([box[k][a] for a in 'xyz']) for k in ('min', 'max'))
    need(box['sphere']['r'] > 0, 'written bounds')
    carried_donors = {}
    for key, rows in by_key.items():
        index = rows[0][0]
        points = np.asarray(model.positions(index), float)
        need(np.isfinite(points).all() and (points >= low - .01).all() and (points <= high + .01).all(),
             'donor vertices lie inside the written bounds')
        block = np.frombuffer(rows[0][1][0], np.uint8).reshape(-1, DONOR_STRIDE)
        joints = block[:, 16:20]
        first_weight = block[:, 6:8].copy().view('<i2')[:, 0] / 32767.
        others = block[:, 24:28].copy().view('<f2').astype(float)
        need(int(joints.max()) < header['bone_count'] and (first_weight >= 0).all() and (others >= 0).all()
             and (first_weight + others.sum(1) <= 1 + 1e-3).all(), 'donor skin bones and weights')
        triangles = len(mtf_author.mesh_triangles(model, index))
        need(triangles > 0, 'donor triangles')
        carried_donors[key] = {'groups': sorted(records[i]['group_index'] for i, _ in rows),
                               'material_index': records[index]['material_index'],
                               'vertices_per_record': records[index]['vertex_count'],
                               'triangles_per_record': triangles}
    one = carried_donors[wanted[first['group_index']][1]]
    report = {'mesh_records': len(records), 'native_records': len(natives), 'donor_records': len(donors),
              'envelope_count': envelopes, 'vertex_count': header['vertex_count'], 'face_count': faces,
              'donor_vertices_per_record': one['vertices_per_record'],
              'donor_triangles_per_record': one['triangles_per_record'],
              'bounds': box, 'native_drawn_triangles': drawn}
    if expect is not None:
        report['donors'] = {str(key): row for key, row in carried_donors.items()}
    return report


def verify(original: bytes, candidate: bytes, target: EnemySet, *, secondary: str = 'neutral',
           textures: list[int] | None = None, expect: dict | None = None) -> dict:
    """Re-parse a written archive against its original and return what was checked; any failure raises.

    `textures` and `expect` describe a mix: the texture entries its carriers may have rewritten, and per model short
    name the `_check_model` expectation. Left unset, the set's one atlas (and its secondary maps) is the scope.

    Entry table unchanged; every entry outside the reviewed indices byte-identical; replaced entries in the shipped
    zlib framing (wrapped stream, level 6, size tag); each model through `_check_model`; textures in their native
    containers. Every model of the set must have changed. A texture may be unchanged only because an earlier set of
    the same archive already wrote it.
    """
    before, after = mt_arc.parse(original), mt_arc.parse(candidate)
    mods = {mod: name for name, mod, _ in target.models}
    if textures is None:
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
        short = name.rsplit('\\', 1)[-1]
        models[short] = _check_model(zlib.decompress(before.entries[index].data),
                                     zlib.decompress(after.entries[index].data), target,
                                     None if expect is None else expect[short])
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
    reviewed = ARCHIVES['uEm10'].sets
    if sets[:1] != ('em1000',) or len(set(sets)) != len(sets) or any(name not in reviewed for name in sets):
        raise EnemyWriterError('build the reviewed em1000 set first; em1001 may only follow it')
    output, receipt = author(archive, source, EM1000, scale=scale, secondary=secondary)
    for name in sets[1:]:
        output, more = author(output, source, SETS[name], scale=scale, secondary=secondary)
        receipt.setdefault('additional_sets', {})[name] = more
        receipt.update(written_sha256=more['written_sha256'], written_bytes=more['written_bytes'])
    models = [name.rsplit('\\', 1)[-1] for key in sets for name, _, _ in SETS[key].models]
    native = [name.rsplit('\\', 1)[-1] for key in reviewed if key not in sets for name, _, _ in SETS[key].models]
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


def only_models(target: EnemySet, models: tuple[str, ...]) -> EnemySet:
    """The reviewed set narrowed to some of its models, by short name (the high model alone, to bisect a load)."""
    kept = tuple(row for row in target.models if row[0].rsplit('\\', 1)[-1] in models)
    if not models or len(kept) != len(set(models)):
        raise EnemyWriterError(f'{target.name} has no reviewed models named {list(models)}')
    return EnemySet(target.name, kept, target.groups, target.albedo, target.normal, target.mask)


def build_donor(archive: bytes, donor: Donor, enemy: EnemyArchive, *, sets: tuple[str, ...] | None = None,
                models: tuple[str, ...] | None = None, fit: Fit = NATIVE_HEIGHT, secondary: str = 'neutral'):
    """Return (complete enemy archive, receipt) with `donor` on the reviewed sets of `enemy`; nothing is written.

    Any library donor builds without a change here: its role joints come from its metadata (`load_donor`), the
    native role bones are measured on each model, and the option groups come from the reviewed table of the set. The
    archive must be the measured original. `models` narrows every chosen set to those model names.
    """
    if hashlib.sha256(archive).hexdigest() != enemy.sha256:
        raise EnemyWriterError(f'{enemy.name} needs the exact measured original {enemy.path.rsplit("/", 1)[-1]}')
    if hashlib.sha256(Path(donor.model).read_bytes()).hexdigest() != donor.sha256:
        raise EnemyWriterError(f'{donor.slug} changed on disk after it was loaded')
    targets = enemy.targets(sets)
    if models is not None:
        targets = [only_models(target, tuple(models)) for target in targets]
    output, receipt, steps = archive, None, {}
    for target in targets:
        output, step = author(output, donor.model, target, source_roles=donor.roles, fit=fit, secondary=secondary,
                              who=donor.slug, reverse_winding=donor.winding == 'cw')
        steps[target.name] = step
        if receipt is None:
            receipt = step
        else:
            receipt.setdefault('additional_sets', {})[target.name] = step
            receipt.update(written_sha256=step['written_sha256'], written_bytes=step['written_bytes'])
    written = [name.rsplit('\\', 1)[-1] for target in targets for name, _, _ in target.models]
    reviewed = [name.rsplit('\\', 1)[-1] for key in enemy.sets for name, _, _ in SETS[key].models]
    receipt.update(
        target_archive_sha256=enemy.sha256,
        source={'slug': donor.slug, 'name': donor.name, 'model': Path(donor.model).name, 'sha256': donor.sha256,
                'provenance': donor.provenance},
        target={'archive': enemy.path, 'sha256': enemy.sha256, 'class': enemy.name, 'models': written,
                'not_replaced': [name for name in reviewed if name not in written] + list(enemy.not_replaced),
                'unbuilt': dict(UNBUILT_MODELS.get(enemy.name, {}))},
        replacement_scope={'route': 'library_donor_enemy_mesh_recipe', 'complete': False, 'gameplay_verified': False,
                           'source_platform': donor.provenance.get('platform'), 'written_platform': 'switch',
                           'collection_model_used': True,
                           'requested_character': {'slug': donor.slug, 'name': donor.name},
                           'target_archive': enemy.path,
                           'notes': ['Offline candidate; this archive has not been booted',
                                     f'Only {", ".join(written)} of {enemy.name} carry the donor',
                                     'The title restarts to load the archive; a running round is not preserved']},
        acceptance='experimental; offline structural checks only')
    return output, receipt


# --- montage: which option groups a spawn draws, and several donors in one model ----------------------------------

@dataclass(frozen=True)
class Carrier:
    """Option groups that natively draw one albedo texture, and that texture's maps. In a mix one donor rides on
    them: its records sit in these groups and its atlas replaces this texture. The groups of one carrier may come
    from different montage categories (a shirt and a pair of pants) as long as the carriers of the table together
    are an exact cover of the drawn montages: every drawn montage draws exactly one carrier group."""
    groups: tuple[int, ...]
    albedo: tuple[int, str]
    normal: tuple[int, str]
    mask: tuple[int, str]


@dataclass(frozen=True)
class MixTable:
    """A reviewed way to draw several donors with one enemy model: the option groups that carry them.

    `category` names the MTG category (or categories) the carrier groups are taken from. The first tables used one
    category whose groups are drawn one per montage (the em1000 pants). A wider table takes groups of several
    categories, chosen so that every drawn montage still draws exactly one of them (`account_mix` proves it on the
    montage table of the archive being written; see EM1000_WIDE).
    """
    name: str
    target: str                                 # the reviewed set it applies to
    montage: tuple[int, str]                    # the MTG entry: index and exact name
    category: int | tuple[int, ...]             # the MTG category or categories the carriers are drawn from
    slot: str
    carriers: tuple[Carrier, ...]               # most drawn first (number of montages that select them)

    @property
    def categories(self) -> tuple[int, ...]:
        return tuple(self.category) if isinstance(self.category, tuple) else (self.category,)

    def groups(self) -> list[int]:
        return [group for carrier in self.carriers for group in carrier.groups]


#: Reviewed 2026-11-09 against uEm10.arc `1fa27189...`, entry 763 (`MTG`, 61 parts, 51 montages). Category 11 is the
#: pants: its 14 parts name the 12 pants groups of `em1000` plus 35 and 165, which only other models have. Every
#: montage that draws anything draws exactly one of the twelve (values 0-2 and 4-12; four montages are empty, value
#: 0x1F in every category), and nothing in the measured layouts removes pants. Ten albedo textures cover the twelve
#: groups: seven are sampled by one material each, three by the two LOD materials of the same pants (5/55, 15/65, 25).
#: The order is the number of montages that select the carrier: 13, 8, 7, 5, 4, 3, 3, 2, 1, 1 of 47.
EM1000_PANTS = MixTable(
    name='em1000-pants', target='em1000', montage=(763, _MODEL + 'em1000'), category=11, slot='pants',
    carriers=(
        Carrier((205,), (24, _MODEL + 'em1000_205_BM'), (27, _MODEL + 'em1000_205_NM_HQ'), (25, _MODEL + 'em1000_205_MM')),
        Carrier((215,), (28, _MODEL + 'em1000_215_BM'), (27, _MODEL + 'em1000_205_NM_HQ'), (25, _MODEL + 'em1000_205_MM')),
        Carrier((5, 55), (105, _MODEL + 'gam01_005_BM'), (107, _MODEL + 'gam01_005_NM'), (106, _MODEL + 'gam01_005_MM')),
        Carrier((125,), (160, _MODEL + 'gam01_125_BM'), (151, _MODEL + 'gam01_105_NM_HQ'), (149, _MODEL + 'gam01_105_MM')),
        Carrier((225,), (29, _MODEL + 'em1000_225_BM'), (27, _MODEL + 'em1000_205_NM_HQ'), (25, _MODEL + 'em1000_205_MM')),
        Carrier((115,), (156, _MODEL + 'gam01_115_BM'), (151, _MODEL + 'gam01_105_NM_HQ'), (149, _MODEL + 'gam01_105_MM')),
        Carrier((15, 65), (125, _MODEL + 'gam01_035_BM'), (107, _MODEL + 'gam01_005_NM'), (106, _MODEL + 'gam01_005_MM')),
        Carrier((135,), (161, _MODEL + 'gam01_135_BM'), (151, _MODEL + 'gam01_105_NM_HQ'), (149, _MODEL + 'gam01_105_MM')),
        Carrier((105,), (148, _MODEL + 'gam01_105_BM'), (151, _MODEL + 'gam01_105_NM_HQ'), (149, _MODEL + 'gam01_105_MM')),
        Carrier((25,), (122, _MODEL + 'gam01_025_BM'), (107, _MODEL + 'gam01_005_NM'), (106, _MODEL + 'gam01_005_MM')),
    ))
#: uEm11.arc entry 383 (`MTG`, 10 parts, 3 montages). Category 2 is the shirt: montage 0 draws group 5, montages 1
#: and 2 draw group 15, so the women can be two characters. Each shirt albedo is sampled by its two LOD materials.
EM1100_SHIRT = MixTable(
    name='em1100-shirt', target='em1100', montage=(383, _MODEL11 + 'em1100'), category=2, slot='shirt',
    carriers=(
        Carrier((15,), (36, _MODEL11 + 'gof01_05_2_BM'), (39, _MODEL11 + 'gof01_05_NM'), (38, _MODEL11 + 'gof01_05_MM')),
        Carrier((5,), (37, _MODEL11 + 'gof01_05_BM'), (39, _MODEL11 + 'gof01_05_NM'), (38, _MODEL11 + 'gof01_05_MM')),
    ))
#: Sixteen carriers on em1000, reviewed 2026-11-09 against the same MTG entry 763 by an exhaustive exact-cover search
#: over its 47 drawn montages (431 exact covers exist; 16 distinct albedo textures is the most any of them holds, and
#: only two reach it: this one, and the same with head group 131 in place of arm skin 222). The shirt category (10)
#: holds 14 groups with 14 textures but is not a cover by itself: montages 14 and 34 draw no shirt (bare torso: arm
#: skin 222, drawn in exactly those two), and shirts 4 and 14 are drawn in montages {0, 2, 6} and {1, 3}, which are
#: also exactly the montages of pants 5 {0, 1, 6}, 15 {2} and 25 {3}. So: the twelve other shirts, those three pants
#: and the bare-torso arm skin draw one and only one carrier in every drawn montage. Shares if montages are uniform:
#: 6, 5, 4, 4, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 1, 1 of 47 (the pants table: 13, 8, 7, 5, 4, 3, 3, 2, 1, 1 of 47). Every
#: albedo is sampled by one material or by the LOD0/LOD1 pair of the same part, all with the same normal and mask maps.
#: Pants 5 keep gam01_005_BM, which em2100 (the second Public Assembly class, in this archive and in uEm21.arc) also
#: wears as its pants; EM1000_SHIRTS below avoids every texture that uEm21.arc carries, at the price of one carrier.
EM1000_WIDE = MixTable(
    name='em1000-wide', target='em1000', montage=(763, _MODEL + 'em1000'), category=(10, 11, 2), slot='shirt/pants/skin',
    carriers=(
        Carrier((104,), (19, _MODEL + 'em1000_104_BM'), (21, _MODEL + 'em1000_104_NM_HQ'), (20, _MODEL + 'em1000_104_MM')),
        Carrier((184,), (165, _MODEL + 'gam01_184_BM'), (132, _MODEL + 'gam01_054_NM_HQ'), (130, _MODEL + 'gam01_054_MM')),
        Carrier((74,), (137, _MODEL + 'gam01_074_BM'), (132, _MODEL + 'gam01_054_NM_HQ'), (130, _MODEL + 'gam01_054_MM')),
        Carrier((114,), (22, _MODEL + 'em1000_114_BM'), (21, _MODEL + 'em1000_104_NM_HQ'), (20, _MODEL + 'em1000_104_MM')),
        Carrier((5,), (105, _MODEL + 'gam01_005_BM'), (107, _MODEL + 'gam01_005_NM'), (106, _MODEL + 'gam01_005_MM')),
        Carrier((54,), (129, _MODEL + 'gam01_054_BM'), (132, _MODEL + 'gam01_054_NM_HQ'), (130, _MODEL + 'gam01_054_MM')),
        Carrier((64,), (133, _MODEL + 'gam01_064_BM'), (132, _MODEL + 'gam01_054_NM_HQ'), (130, _MODEL + 'gam01_054_MM')),
        Carrier((124,), (23, _MODEL + 'em1000_124_BM'), (21, _MODEL + 'em1000_104_NM_HQ'), (20, _MODEL + 'em1000_104_MM')),
        Carrier((174,), (164, _MODEL + 'gam01_174_BM'), (132, _MODEL + 'gam01_054_NM_HQ'), (130, _MODEL + 'gam01_054_MM')),
        Carrier((194,), (166, _MODEL + 'gam01_194_BM'), (132, _MODEL + 'gam01_054_NM_HQ'), (130, _MODEL + 'gam01_054_MM')),
        Carrier((84,), (139, _MODEL + 'gam01_084_BM'), (132, _MODEL + 'gam01_054_NM_HQ'), (140, _MODEL + 'gam01_084_MM')),
        Carrier((154,), (162, _MODEL + 'gam01_154_BM'), (132, _MODEL + 'gam01_054_NM_HQ'), (130, _MODEL + 'gam01_054_MM')),
        Carrier((164,), (163, _MODEL + 'gam01_164_BM'), (132, _MODEL + 'gam01_054_NM_HQ'), (130, _MODEL + 'gam01_054_MM')),
        Carrier((222,), (123, _MODEL + 'gam01_032_BM'), (120, _MODEL + 'gam01_022_NM'), (119, _MODEL + 'gam01_022_MM')),
        Carrier((15,), (125, _MODEL + 'gam01_035_BM'), (107, _MODEL + 'gam01_005_NM'), (106, _MODEL + 'gam01_005_MM')),
        Carrier((25,), (122, _MODEL + 'gam01_025_BM'), (107, _MODEL + 'gam01_005_NM'), (106, _MODEL + 'gam01_005_MM')),
    ))
#: Fifteen carriers: all fourteen shirts and the bare-torso arm skin. The second-largest exact cover, and the one whose
#: textures uEm21.arc does not carry (shirts 4 and 14 replace pants 5, 15, 25). Shares: 6, 5, 4, 4, 3, 3, 3, 3, 3, 3,
#: 2, 2, 2, 2, 2 of 47.
EM1000_SHIRTS = MixTable(
    name='em1000-shirts', target='em1000', montage=(763, _MODEL + 'em1000'), category=(10, 2), slot='shirt/skin',
    carriers=EM1000_WIDE.carriers[:4] + (
        Carrier((4,), (100, _MODEL + 'gam01_004_BM'), (104, _MODEL + 'gam01_004_NM'), (103, _MODEL + 'gam01_004_MM')),
    ) + EM1000_WIDE.carriers[5:11] + (
        Carrier((14,), (116, _MODEL + 'gam01_014_BM'), (104, _MODEL + 'gam01_004_NM'), (103, _MODEL + 'gam01_004_MM')),
    ) + EM1000_WIDE.carriers[11:14])
#: uEm12.arc entry 606 (`MTG`, 24 parts of which one is an all-zero row, 16 montages, all drawn). Categories: 1 head
#: (four variants), 2 body (four), 3 leg (one present), 4 accessories (four groups, one texture), 5 waist (two), 8 left
#: hand and 9 right hand (two each, two textures). Head and body are each an exact cover of four textures; the body is
#: taken (a hidden head would take the whole donor with it) and its textures are 1024x2048. Four montages each.
EM1200_BODY = MixTable(
    name='em1200-body', target='em1200', montage=(606, _MODEL12 + 'em1200'), category=2, slot='body',
    carriers=(
        Carrier((2,), (22, _MODEL12 + 'em1200_01_BM'), (24, _MODEL12 + 'em1200_01_NM'), (23, _MODEL12 + 'em1200_01_MM')),
        Carrier((12,), (47, _MODEL12 + 'em1200_11_BM'), (49, _MODEL12 + 'em1200_11_NM'), (48, _MODEL12 + 'em1200_11_MM')),
        Carrier((22,), (53, _MODEL12 + 'em1200_21_BM'), (55, _MODEL12 + 'em1200_21_NM'), (54, _MODEL12 + 'em1200_21_MM')),
        Carrier((32,), (59, _MODEL12 + 'em1200_31_BM'), (61, _MODEL12 + 'em1200_31_NM'), (60, _MODEL12 + 'em1200_31_MM')),
    ))
#: uEm13.arc entry 123 (`MTG`, 4 parts, 2 montages): montage 0 draws pants 3, montage 1 pants 13; head and body are
#: drawn in both. Two carriers. The `_CMM` masks (format 0x13) are kept native, see EM1300.
EM1300_PANTS = MixTable(
    name='em1300-pants', target='em1300', montage=(123, _MODEL13 + 'em1300'), category=3, slot='pants',
    carriers=(
        Carrier((3,), (22, _MODEL13 + 'em1302_BM'), (24, _MODEL13 + 'em1302_NM'), (23, _MODEL13 + 'em1302_CMM')),
        Carrier((13,), (25, _MODEL13 + 'em1304_BM'), (28, _MODEL13 + 'em1304_NM'), (26, _MODEL13 + 'em1304_CMM')),
    ))
#: uEm14.arc entry 642 (`MTG`, 41 parts, 56 montages, all drawn). Its masks hold several bits, so a category value draws
#: several groups at once (the boots, group 13, in every montage; the body skin 1 in 26) and no single category is a
#: cover of one group per montage. The exhaustive search finds 26 exact covers; the largest holds nine textures, all of
#: category 2 (tops): body skin 1, jackets 14 and 15, shirts 17-22. Shares: 26, 5, 5, 5, 4, 3, 3, 3, 2 of 56. The Mercenaries
#: layouts of Experimental Facility name montages 22-25, 34, 40, 44-46 and 50 beside the random ones: those select
#: carriers 22, 22, 19, 19, 1, 20, 14, 1, 15, 1.
EM1400_TOPS = MixTable(
    name='em1400-tops', target='em1400', montage=(642, _MODEL14 + 'em1400'), category=2, slot='tops',
    carriers=(
        Carrier((1,), (20, _MODEL14 + 'em1400_01_BM'), (22, _MODEL14 + 'em1400_01_NM'), (21, _MODEL14 + 'em1400_01_MM')),
        Carrier((14,), (30, _MODEL14 + 'em1400_10_Jacket_BM'), (32, _MODEL14 + 'em1400_10_Jacket_NM'),
                (31, _MODEL14 + 'em1400_10_Jacket_MM')),
        Carrier((15,), (33, _MODEL14 + 'em1400_11_Jacket_BM'), (32, _MODEL14 + 'em1400_10_Jacket_NM'),
                (31, _MODEL14 + 'em1400_10_Jacket_MM')),
        Carrier((22,), (52, _MODEL14 + 'em1400_48_WhiteShirt_BM'), (46, _MODEL14 + 'em1400_41_BombShirt_NM'),
                (45, _MODEL14 + 'em1400_41_BombShirt_MM')),
        Carrier((20,), (50, _MODEL14 + 'em1400_45_PinkShirt_BM'), (46, _MODEL14 + 'em1400_41_BombShirt_NM'),
                (45, _MODEL14 + 'em1400_41_BombShirt_MM')),
        Carrier((17,), (47, _MODEL14 + 'em1400_42_BlackShirt_BM'), (46, _MODEL14 + 'em1400_41_BombShirt_NM'),
                (45, _MODEL14 + 'em1400_41_BombShirt_MM')),
        Carrier((18,), (48, _MODEL14 + 'em1400_43_GreenShirt_BM'), (46, _MODEL14 + 'em1400_41_BombShirt_NM'),
                (45, _MODEL14 + 'em1400_41_BombShirt_MM')),
        Carrier((21,), (51, _MODEL14 + 'em1400_46_RedShirt_BM'), (46, _MODEL14 + 'em1400_41_BombShirt_NM'),
                (45, _MODEL14 + 'em1400_41_BombShirt_MM')),
        Carrier((19,), (49, _MODEL14 + 'em1400_44_BombShirt_BM'), (46, _MODEL14 + 'em1400_41_BombShirt_NM'),
                (45, _MODEL14 + 'em1400_41_BombShirt_MM')),
    ))
#: uEm21.arc entry 139 (`MTG`, 8 parts, 3 montages). Shirt 254 and pants 255 are drawn in all three (montages 1 and 2
#: have no head and montage 1 names a body group the model lacks); one carrier, the shirt, whose texture no other
#: archive carries.
EM2100_SHIRT = MixTable(
    name='em2100-shirt', target='em2100', montage=(139, _MODEL + 'em2100'), category=10, slot='shirt',
    carriers=(Carrier((254,), (9, _MODEL + 'gam01_254_BM'), (8, _MODEL + 'gam01_254_NM'), (10, _MODEL + 'gam01_254_MM')),))
#: Every reviewed table by name, and the default table of each class (the one with the most carriers).
MIX_TABLES = {table.name: table for table in (EM1000_PANTS, EM1000_WIDE, EM1000_SHIRTS, EM1100_SHIRT, EM1200_BODY,
                                               EM1300_PANTS, EM1400_TOPS, EM2100_SHIRT)}
MIXES = {'uEm10': EM1000_WIDE, 'uEm11': EM1100_SHIRT, 'uEm12': EM1200_BODY, 'uEm13': EM1300_PANTS,
         'uEm14': EM1400_TOPS, 'uEm21': EM2100_SHIRT}

MONTAGE_READING = {
    'measured': 'MTG version 2: 32-byte header, 8 bytes per part (u16 option group, u16 category, u32 mask), 20 bytes '
                'per montage (16 bytes, one value per category index, and a float between 1.0 and 1.04)',
    'inferred': 'a montage draws, in each category, the parts whose mask holds bit `value`; a value with no part '
                'draws nothing there. It fits every measured row: montage 0 is the base outfit (groups 1, 2, 3, 4, '
                '5, 7), the montages whose arm skin is the bare torso (222) have a shirt value with no part, and the '
                'pants values are exactly the twelve pants groups of em1000',
    'unknown': ['how the game picks a montage when a layout says mMontageNo -1 (every uEm10 spawn of every '
                'Mercenaries layout does): uniformly, from a stage list, or not from this table at all',
                'whether code hides or swaps a category during damage or death',
                'what the float is (a body scale is the likely reading)'],
}


def parse_montage(raw: bytes) -> dict:
    """The `MTG` resource beside an enemy model: {'parts': [(group, category, mask)], 'montages': [(values, float)]}.
    Anything that is not the measured layout is refused."""
    if len(raw) < 32 or raw[:4] != b'MTG\0':
        raise EnemyWriterError('not an MTG montage table')
    version, parts, montages, parts_at, montages_at = struct.unpack_from('<IIIQQ', raw, 4)
    if (version != 2 or not parts or not montages or parts_at != 32 or montages_at != 32 + 8 * parts
            or len(raw) != montages_at + 20 * montages):
        raise EnemyWriterError('the montage table is not the measured version 2 layout')
    rows = [struct.unpack_from('<HHI', raw, parts_at + 8 * i) for i in range(parts)]
    empty = [i for i, row in enumerate(rows) if row == (0, 0, 0)]      # em1200's table carries one all-zero row
    if any(category >= 16 or not mask for i, (_, category, mask) in enumerate(rows) if i not in empty):
        raise EnemyWriterError('a montage part has no mask or a category outside the sixteen value bytes')
    table = []
    for i in range(montages):
        at = montages_at + 20 * i
        table.append((tuple(raw[at:at + 16]), struct.unpack_from('<f', raw, at + 16)[0]))
    return {'parts': rows, 'montages': table, 'empty_parts': empty}


def montage_groups(table: dict, index: int, present: set[int]) -> dict[int, list[int]]:
    """{category: [option groups]} montage `index` draws among the groups `present` in a model (the inferred reading:
    per category, the parts whose mask holds bit `value`)."""
    values, drawn = table['montages'][index][0], {}
    for group, category, mask in table['parts']:
        if group in present and values[category] < 32 and mask >> values[category] & 1:
            drawn.setdefault(category, []).append(group)
    return drawn


def account_mix(model: mt_model.ModFile, table: dict, mix: MixTable) -> dict:
    """Check that the carrier groups are an exact cover of the drawn montages - every drawn montage draws exactly one
    of them, in whichever category - and return {carrier index: [montages]}. The carriers must be groups the model
    has, each named once, all from the table's categories. A mix that could leave a spawn with no donor, or with
    two, is refused here."""
    present = set(group_table(model))
    carried = [group for carrier in mix.carriers for group in carrier.groups]
    categories = {group: kind for group, kind, mask in table['parts'] if mask}
    allowed = sorted(group for group, kind in categories.items() if kind in mix.categories and group in present)
    if len(set(carried)) != len(carried) or not set(carried) <= set(allowed):
        raise EnemyWriterError(f'the carriers of {mix.name} are not distinct {mix.slot} groups of the model: '
                               f'{sorted(set(carried) - set(allowed))} are not; the model offers {allowed}')
    owner = {group: index for index, carrier in enumerate(mix.carriers) for group in carrier.groups}
    shares, empty = {index: [] for index in range(len(mix.carriers))}, []
    for number in range(len(table['montages'])):
        drawn = montage_groups(table, number, present)
        hits = [group for groups in drawn.values() for group in groups if group in owner]
        if not drawn:
            empty.append(number)
        elif len(hits) != 1:
            raise EnemyWriterError(f'montage {number} draws {len(hits)} {mix.slot} carrier groups; a mix needs '
                                   f'exactly one')
        else:
            shares[owner[hits[0]]].append(number)
    return {'shares': shares, 'empty_montages': empty, 'drawn_montages': len(table['montages']) - len(empty)}


def uncarried_groups(model: mt_model.ModFile, table: dict, mix: MixTable) -> list[int]:
    """Groups of the mix's categories that the model has and no carrier takes (they are blanked like every other
    native record; listed so a receipt says which parts of the category were left out)."""
    present = set(group_table(model))
    owner = set(mix.groups())
    return sorted(group for group, kind, mask in table['parts']
                  if mask and kind in mix.categories and group in present and group not in owner)


def author_mix(archive: bytes, riders: list[tuple[Path, dict, Fit, str]], target: EnemySet, mix: MixTable, *,
               secondary: str = 'neutral'):
    """Return (archive, receipt) with one donor per carrier of `mix` on every model of `target`.

    `riders[i]` is (model file, role joints, fit, name[, winding]) for `mix.carriers[i]`; the same donor may ride on
    several carriers; `winding` is 'cw' for a donor exported with clockwise fronts, whose triangles are then turned.
    Every native record of every option group is blanked, and donor records exist only in the carrier groups, so a
    spawn draws the one donor of the carrier its montage selects, once. Inputs are not hash-checked here.
    """
    if secondary not in ('neutral', 'native'):
        raise EnemyWriterError("secondary maps are either 'neutral' or 'native'")
    if mix.target != target.name or len(riders) != len(mix.carriers) or not riders:
        raise EnemyWriterError(f'{mix.name} needs one donor for each of its {len(mix.carriers)} carriers')
    parsed = mt_arc.parse(archive)
    albedos = [carrier.albedo[0] for carrier in mix.carriers]
    seconds = sorted({index for carrier in mix.carriers for index in (carrier.normal[0], carrier.mask[0])})
    indices = [i for _, mod, mrl in target.models for i in (mod, mrl)] + albedos + seconds + [mix.montage[0]]
    if len(set(indices)) != len(indices):
        raise EnemyWriterError('the reviewed entry indices must be distinct')
    table = parse_montage(_entry(parsed, *mix.montage, b'MTG\0'))
    sources = []
    for rider, carrier in zip(riders, mix.carriers):
        source, roles, fit, who = rider[:4]
        winding = rider[4] if len(rider) > 4 else 'ccw'
        if winding not in ('cw', 'ccw'):
            raise EnemyWriterError(f"{who}: the winding is 'cw' or 'ccw'")
        source, roles = Path(source), dict(roles)
        if set(roles) != set(ROLE_ANIMATION_IDS):
            raise EnemyWriterError(f'{who} must name the fifteen measured roles')
        surface = mtf_tex.parse(_entry(parsed, *carrier.albedo, b'TEX\0'))
        vertices, triangles, _, appearance = mtf_materials.source_mesh(
            source, atlas_size=(surface.width, surface.height), strict_samplers='in_range')
        gltf, _, _, world = characters._load(source)
        nodes, joints = _donor_joints(gltf, world, roles, who)
        orphans: set = set()
        owners = _role_owners(vertices, gltf, nodes, orphans)
        sources.append({'source': source, 'roles': roles, 'fit': fit, 'who': who, 'vertices': vertices,
                        'triangles': len(triangles), 'owners': owners, 'joints': joints, 'appearance': appearance,
                        'orphans': bool(orphans), 'winding': winding,
                        'rig': check_rig(vertices, owners, joints, who) | {
                            'joints_outside_the_roles': sorted(str(gltf['nodes'][i].get('name', i)) for i in orphans),
                            'carried_by': ORPHAN_ROLE if orphans else None},
                        'atlas_size': [surface.width, surface.height],
                        'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})

    payloads: dict[int, bytes] = {}
    models, expect, positions, top, groups, shares = {}, {}, None, None, None, None
    fits, atlases = [None] * len(riders), [None] * len(riders)
    for name, mod_index, mrl_index in target.models:
        native_raw, mrl = _entry(parsed, mod_index, name, b'MOD\0'), _entry(parsed, mrl_index, name, b'MRL\0')
        native, short = mt_model.parse_mod(native_raw), name.rsplit('\\', 1)[-1]
        accounted = account_groups(native, target)
        counted = account_mix(native, table, mix)
        if shares not in (None, counted):
            raise EnemyWriterError('the models of one set must draw the same carriers for every montage')
        shares = counted
        roles, evidence = role_map(native, allow_ids=target.roles_by_ids)
        template = _template(native.meshes())
        top = top if top is not None else float(native.bounds()['max']['y'])
        positions = positions or evidence['bind_position']
        if evidence['bind_position'] != positions:
            raise EnemyWriterError('the models of one set must share one bind pose for the role joints')
        pieces, materials = [], []
        for number, (rider, carrier) in enumerate(zip(sources, mix.carriers)):
            material_index, material = _material(mrl, native, carrier, unique=False)
            used, role_scales, role_offsets, sizes = fit_scales(rider['fit'], rider['vertices'], rider['owners'],
                                                                rider['joints'], evidence['bind_position'], top)
            try:
                result, donor_raw, _, imported = re5_mesh_import.build_archive(
                    archive, rider['source'], model_name=short, source_roles=rider['roles'], target_roles=roles,
                    segments=dict(SEGMENTS), scale=used, material_index=material_index, template_index=template,
                    pose_mode='native_segments', samplers_in_range=True, reverse_winding=rider['winding'] == 'cw',
                    **({'role_scales': role_scales} if role_scales else {}),
                    **({'role_offsets': role_offsets} if role_offsets else {}),
                    **({'orphan_role': ORPHAN_ROLE} if rider['orphans'] else {}))
            except ValueError as exc:
                raise EnemyWriterError(f'{rider["who"]} cannot be fitted on {short}: {exc}') from exc
            after = mt_arc.parse(result)
            if (imported['changed_entry_indices'] != [mod_index, carrier.albedo[0]]
                    or len(after.entries) != len(parsed.entries)
                    or zlib.decompress(after.entries[mrl_index].data) != mrl):
                raise EnemyWriterError(f'the mesh import did not address the reviewed entries of {name!r}')
            atlas = zlib.decompress(after.entries[carrier.albedo[0]].data)
            this_fit = {'name': rider['fit'].name, 'cross_section_scale': used, 'role_scales': role_scales,
                        'role_offsets': {role: list(offset) for role, offset in role_offsets.items()},
                        'scales': {'limbs': used, 'torso': sizes['torso'], 'head': sizes['head'],
                                   'hands': sizes['hands']},
                        'rules': {key: sizes[key] for key in ('torso_rule', 'hands_rule', 'head_rule', 'native_top',
                                                              'head_drop') if key in sizes},
                        'shape': sizes['shape'],
                        'bounds': imported['bounds'],
                        'height': imported['bounds']['max']['y'] - imported['bounds']['min']['y'],
                        'native_height': imported['original_bounds']['max']['y'] - imported['original_bounds']['min']['y']}
            if atlases[number] not in (None, atlas) or (fits[number] is not None and any(
                    fits[number][key] != this_fit[key] for key in ('cross_section_scale', 'role_scales',
                                                                   'role_offsets'))):
                raise EnemyWriterError('the models of one set must share each donor atlas and fit')
            atlases[number], fits[number] = atlas, fits[number] or this_fit
            pieces.append((mt_model.parse_mod(donor_raw), list(carrier.groups), material_index))
            materials.append(material)
        grafted, report = graft_pieces(native, pieces)
        payloads[mod_index] = grafted
        expect[short] = {group: (material_index, number) for number, (_, carried, material_index) in enumerate(pieces)
                         for group in carried}
        groups = groups or {group: {'slot': row['slot'], 'native_lod_masks': row['native_lod_masks'],
                                    'native_records': {}, 'native_vertices': {}} for group, row in accounted.items()}
        for group, row in accounted.items():
            groups[group]['native_records'][short] = row['native_records']
            groups[group]['native_vertices'][short] = row['native_vertices']
        models[short] = report | {
            'mod_entry': mod_index, 'mrl_entry': mrl_index, 'bone_count': evidence['bone_count'], 'roles': roles,
            'skeleton': evidence['skeleton'], 'materials': materials,
            'native_sha256': hashlib.sha256(native_raw).hexdigest(), 'sha256': hashlib.sha256(grafted).hexdigest()}
    for number, carrier in enumerate(mix.carriers):
        payloads[carrier.albedo[0]] = atlases[number]
    kept_native: list[str] = []
    if secondary == 'neutral':
        _neutral(parsed, [(carrier.normal, (128, 128)) for carrier in mix.carriers]
                 + [(carrier.mask, (0,)) for carrier in mix.carriers], payloads, kept_native)
    output = archive
    for index in sorted(payloads):
        output = mtf_author.replace_archive_model(output, index, payloads[index])
    textures = albedos + ([index for index in seconds if index in payloads] if secondary == 'neutral' else [])
    checks = verify(archive, output, target, secondary=secondary, textures=textures, expect=expect)
    final = mt_arc.parse(output)
    drawn = shares['drawn_montages']
    owner = {group: number for number, carrier in enumerate(mix.carriers) for group in carrier.groups}
    first_model = mt_model.parse_mod(_entry(parsed, target.models[0][1], target.models[0][0], b'MOD\0'))
    left_out = uncarried_groups(first_model, table, mix)
    receipt = {
        'recipe': 're5_enemy_writer.mix', 'recipe_version': RECIPE_VERSION, 'enemy_set': target.name,
        'mix': mix.name, 'slot': mix.slot,
        'target_archive_sha256': hashlib.sha256(archive).hexdigest(),
        'written_sha256': hashlib.sha256(output).hexdigest(), 'written_bytes': len(output),
        'entries': len(final.entries),
        'entries_replaced': [{'index': index, 'name': final.entries[index].name,
                              'kind': payloads[index][:3].decode('ascii'),
                              'bytes_before': parsed.entries[index].tag & 0xFFFFFF, 'bytes_after': len(payloads[index]),
                              'sha256': hashlib.sha256(payloads[index]).hexdigest()} for index in sorted(payloads)],
        'montage_table': MONTAGE_READING | {
            'entry': mix.montage[0], 'name': mix.montage[1], 'untouched': True, 'category': mix.category,
            'categories': list(mix.categories), 'parts': len(table['parts']), 'empty_parts': table['empty_parts'],
            'montages': len(table['montages']), 'drawn_montages': drawn, 'empty_montages': shares['empty_montages'],
            'exact_cover': 'every drawn montage draws exactly one carrier group (checked on every model of the set)',
            'uncarried_groups_of_these_categories': left_out},
        'carriers': [{
            'carrier': number, 'groups': list(carrier.groups), 'albedo_entry': carrier.albedo[0],
            'albedo': carrier.albedo[1], 'atlas_size': rider['atlas_size'],
            'donor': {'name': rider['who'], 'model': rider['source'].name, 'sha256': rider['sha256']},
            'fit': fits[number], 'donor_rig': rider['rig'], 'atlas_source': rider['appearance'],
            'winding_reversed': rider['winding'] == 'cw',
            'source_vertices': len(rider['vertices']), 'source_triangles': rider['triangles'],
            'montages': shares['shares'][number],
            'share_if_montages_are_uniform': f'{len(shares["shares"][number])} of {drawn}'}
            for number, (rider, carrier) in enumerate(zip(sources, mix.carriers))],
        'option_groups': {
            'choice': 'carry_in_carrier_groups',
            'native_records': 'kept byte for byte in all groups; index words collapsed so each draws nothing',
            'donor_records': f'only in the {mix.slot} carrier groups: one record per group, all LODs, the whole donor '
                             'of that carrier',
            'count': len(groups), 'groups': {
                str(group): row | {'native_action': 'index words collapsed; records, vertices and envelopes kept',
                                   'donor_record': (f'carrier {owner[group]}: {sources[owner[group]]["who"]}'
                                                    if group in owner else 'none')}
                for group, row in groups.items()}},
        'role_map': {'method': evidence['method'], 'animation_ids': dict(ROLE_ANIMATION_IDS),
                     'bind_position': positions, 'bones': {model: row['roles'] for model, row in models.items()},
                     'source_roles': {rider['who']: rider['roles'] for rider in sources}},
        'models': models,
        'counts': {'donors': len({rider['sha256'] for rider in sources}), 'carriers': len(mix.carriers),
                   'donor_records_per_model': len(owner),
                   'native_records_blanked': sum(m['native_records'] for m in models.values())},
        'appearance': {'mrl_entries_changed': False, 'secondary_maps': secondary,
                       'secondary_maps_kept_native': kept_native,
                       'normals': 'recomputed from the fitted triangles'},
        'checks': checks, 'live_verified': False, 'gameplay_verified': False, 'writer_registered': False}
    return output, receipt


def build_mix(archive: bytes, donors: list[Donor], enemy: EnemyArchive, *, fits: list[Fit] | None = None,
              models: tuple[str, ...] | None = None, secondary: str = 'neutral', table: str | None = None):
    """Return (complete enemy archive, receipt) with several donors on one enemy model, one per montage carrier.

    The donors are dealt over the carriers in order, most drawn carrier first, and repeat from the start when there
    are fewer donors than carriers. The archive must be the measured original and has a reviewed table in `MIXES`;
    `table` names another reviewed table of the same class from `MIX_TABLES` (`em1000-pants`, `em1000-shirts`).
    """
    mix = MIXES.get(enemy.name) if table is None else MIX_TABLES.get(table)
    if mix is None or SETS[mix.target].name not in enemy.sets:
        raise EnemyWriterError(f'{enemy.name} has no reviewed mix table' + (f' named {table!r}' if table else ''))
    if hashlib.sha256(archive).hexdigest() != enemy.sha256:
        raise EnemyWriterError(f'{enemy.name} needs the exact measured original {enemy.path.rsplit("/", 1)[-1]}')
    fits = list(fits) if fits is not None else [NATIVE_HEIGHT] * len(donors)
    if not donors or len(donors) > len(mix.carriers) or len(fits) != len(donors):
        raise EnemyWriterError(f'{mix.name} takes one to {len(mix.carriers)} donors and one fit for each')
    if len({donor.sha256 for donor in donors}) != len(donors):
        raise EnemyWriterError('give each donor once; they are repeated over the carriers as needed')
    for donor in donors:
        if hashlib.sha256(Path(donor.model).read_bytes()).hexdigest() != donor.sha256:
            raise EnemyWriterError(f'{donor.slug} changed on disk after it was loaded')
    target = SETS[mix.target]
    if models is not None:
        target = only_models(target, tuple(models))
    dealt = [number % len(donors) for number in range(len(mix.carriers))]
    riders = [(donors[i].model, donors[i].roles, fits[i], donors[i].slug, donors[i].winding) for i in dealt]
    output, receipt = author_mix(archive, riders, target, mix, secondary=secondary)
    by_slug = {donor.slug: donor for donor in donors}
    for row in receipt['carriers']:
        donor = by_slug[row['donor']['name']]
        row['donor'] = {'slug': donor.slug, 'name': donor.name, 'model': Path(donor.model).name,
                        'sha256': donor.sha256, 'provenance': donor.provenance}
    drawn = receipt['montage_table']['drawn_montages']
    written = [name.rsplit('\\', 1)[-1] for name, _, _ in target.models]
    reviewed = [name.rsplit('\\', 1)[-1] for key in enemy.sets for name, _, _ in SETS[key].models]
    receipt.update(
        donors=[{'slug': donor.slug, 'name': donor.name, 'sha256': donor.sha256, 'fit': fit.name,
                 'carriers': [n for n, i in enumerate(dealt) if donors[i] is donor],
                 'groups': [g for n, i in enumerate(dealt) if donors[i] is donor for g in mix.carriers[n].groups],
                 'share_if_montages_are_uniform':
                     f'{sum(len(receipt["carriers"][n]["montages"]) for n, i in enumerate(dealt) if donors[i] is donor)}'
                     f' of {drawn}'} for donor, fit in zip(donors, fits)],
        target={'archive': enemy.path, 'sha256': enemy.sha256, 'class': enemy.name, 'models': written,
                'not_replaced': [name for name in reviewed if name not in written] + list(enemy.not_replaced),
                'unbuilt': dict(UNBUILT_MODELS.get(enemy.name, {}))},
        replacement_scope={'route': 'library_donor_enemy_mix_recipe', 'complete': False, 'gameplay_verified': False,
                           'written_platform': 'switch', 'collection_model_used': True,
                           'target_archive': enemy.path,
                           'notes': ['Offline candidate; this archive has not been booted',
                                     'Which donor a spawn shows follows from an inferred reading of the montage table',
                                     'The title restarts to load the archive; a running round is not preserved']},
        acceptance='experimental; offline structural checks only')
    return output, receipt


def _is_donor_record(record: dict, native_count: int | None) -> bool:
    """A written donor record: its mesh id follows the native ids when the native count is known; otherwise the
    one-mesh shape the writer authors (all LODs, the donor format, mesh type 0xFFFF, vertex index 0)."""
    if native_count is not None:
        return record['mesh_id'] > native_count
    return (record['level_of_detail'] == ALL_LODS and record['vertex_format'] == DONOR_FORMAT
            and record['mesh_type'] == 0xFFFF and record['vertex_index'] == 0)


def _native_count(original: bytes | None, target: EnemySet) -> int | None:
    if original is None:
        return None
    parsed = mt_arc.parse(original)
    name, mod_index, _ = target.models[0]
    return len(mt_model.parse_mod(_entry(parsed, mod_index, name, b'MOD\0')).meshes())


def _donor(archive: bytes, target: EnemySet, carrier: Carrier | None = None, native_count: int | None = None):
    """A written donor record of the set's first model and the atlas the archive holds for it: the first one, or in
    a mix the one that rides on `carrier`. `native_count` (the original model's record count) tells donor records
    apart by mesh id, which also works where native records use LOD mask 255 (em1200's `_low` and `_mid`)."""
    parsed = mt_arc.parse(archive)
    name, mod_index, _ = target.models[0]
    model = mt_model.parse_mod(_entry(parsed, mod_index, name, b'MOD\0'))
    index = next((i for i, record in enumerate(model.meshes()) if _is_donor_record(record, native_count)
                  and (carrier is None or record['group_index'] == carrier.groups[0])), None)
    if index is None:
        raise EnemyWriterError('the archive holds no donor record to preview')
    albedo = target.albedo if carrier is None else carrier.albedo
    atlas = np.asarray(mtf_tex.decode(_entry(parsed, *albedo, b'TEX\0')).convert('RGBA'), np.uint8)
    return model, index, atlas


def _sheet(poses, uvs, triangles, atlas, yaws, size: int, png: Path, backdrop=None) -> None:
    """One row of z-buffered CPU views, every pose under every yaw, shaded flat per triangle by the previewer.

    `backdrop` paints the empty space around the figure so a dark donor can be read. The figure's own pixels are found
    by drawing it a second time in white, so a black part of the donor is never mistaken for empty space.
    """
    import tempfile
    from PIL import Image
    from . import melee_models

    views = []
    white = np.full((4, 4, 4), 255, np.uint8)
    with tempfile.TemporaryDirectory() as folder:
        for number, points in enumerate(poses):
            count = len(points)
            prim = {'pos': np.asarray(points, np.float32), 'nrm': np.tile((0., 0., 1.), (count, 1)).astype(np.float32),
                    'uv': np.asarray(uvs, np.float32), 'tris': np.asarray(triangles, np.int64),
                    'J': np.zeros((count, 4), np.int64), 'W': np.eye(1, 4, dtype=np.float32).repeat(count, 0),
                    'color': (255, 255, 255, 255), 'tex': atlas}
            gltf = Path(folder) / f'pose{number}.gltf'
            melee_models.write_gltf(gltf, [{'parent': -1, 'world': np.eye(4)}], [prim], 1., 're5_enemy', ['root'])
            if backdrop is not None:
                solid = Path(folder) / f'solid{number}.gltf'
                melee_models.write_gltf(solid, [{'parent': -1, 'world': np.eye(4)}], [prim | {'tex': white}], 1.,
                                        're5_enemy', ['root'])
            for yaw in yaws:
                path = Path(folder) / f'view{len(views)}.png'
                characters.render_preview(gltf, path, size=size, yaw=yaw, depth=True)
                view = Image.open(path).convert('RGB')
                if backdrop is not None:
                    characters.render_preview(solid, path, size=size, yaw=yaw, depth=True)
                    covered = np.asarray(Image.open(path).convert('RGB')).any(axis=2)
                    pixels = np.asarray(view).copy()
                    pixels[~covered] = backdrop
                    view = Image.fromarray(pixels)
                views.append(view)
    sheet = Image.new('RGB', (size * len(views), size))
    for i, view in enumerate(views):
        sheet.paste(view, (size * i, 0))
    sheet.save(png)


def preview(archive: bytes, png: Path, *, target: EnemySet = EM1000, size: int = 384, backdrop=None,
            carrier: Carrier | None = None, original: bytes | None = None) -> dict:
    """Write a rest-pose picture (front, side, three-quarter) of the donor record the archive actually holds.

    The geometry is decoded from the written MOD and the colours from the written BC7 atlas, so the picture shows the
    candidate's own bytes in the native bind pose. It is not the game's shading, animation or camera. `original`
    (the archive before the write) lets the donor records be told apart by mesh id.
    """
    model, index, atlas = _donor(archive, target, carrier, _native_count(original, target))
    points, triangles = model.positions(index), mtf_author.mesh_triangles(model, index)
    _sheet([points], model.uvs(index), triangles, atlas, (0., -90., -30.), size, Path(png), backdrop)
    return {'preview': str(png), 'model': target.models[0][0].rsplit('\\', 1)[-1], 'record': index,
            'vertices': len(points), 'triangles': len(triangles), 'views': ['front', 'side', 'three-quarter'],
            'shows': 'written MOD geometry and written BC7 atlas in the native bind pose; not game shading or motion'}


def posed_preview(original: bytes, candidate: bytes, png: Path, *, motion_entry: int, clip: int, frames,
                  target: EnemySet = EM1000, size: int = 320, backdrop=None,
                  carrier: Carrier | None = None, sampled: dict | None = None) -> dict:
    """Write the donor record under frames of one native clip (three-quarter and side view per frame).

    The existing comparison sampler (`mtf_motion.sample_compare`) evaluates the clip on the native and on the written
    model: forward kinematics and linear skinning on the CPU. No engine IK, physics, clip layering or shading, so the
    picture shows whether the surface follows the native joints, never what the game draws. A mix draws several
    donors of one archive: pass the `sampled` a first call returned to sample the clip only once.
    """
    from . import mtf_motion

    entries, frames = mt_arc.parse(original).entries, [float(frame) for frame in frames]
    motion = zlib.decompress(entries[motion_entry].data) if 0 <= motion_entry < len(entries) else b''
    if motion[:4] != b'LMT\0':
        raise EnemyWriterError(f'entry {motion_entry} is not a native motion resource')
    native_count = _native_count(original, target)
    model, index, atlas = _donor(candidate, target, carrier, native_count)
    records = model.meshes()
    if sampled is None:
        sampled = mtf_motion.sample_compare(original, candidate, motion, animation_index=clip, frames=frames,
                                            model_name=target.models[0][0].rsplit('\\', 1)[-1], raw_fk=True)
    starts, cursor = {}, 0
    for i in sampled['candidate']['mesh_indices']:
        starts[i] = cursor
        cursor += records[i]['vertex_count']
    copies = [i for i in starts if _is_donor_record(records[i], native_count)
              and (carrier is None or records[i]['group_index'] in carrier.groups)]
    count, poses, spread = records[index]['vertex_count'], [], 0.
    for frame in sampled['candidate']['frames']:
        positions = np.asarray(frame['positions'], float).reshape(-1, 3)
        poses.append(positions[starts[index]:starts[index] + count])
        spread = max([spread] + [float(np.abs(positions[starts[i]:starts[i] + count] - poses[-1]).max()) for i in copies])
    moved = max((joint['distance_cm'] for row in sampled['diagnostics']['joint_displacements']
                 for joint in row['joints']), default=0.)
    _sheet(poses, model.uvs(index), mtf_author.mesh_triangles(model, index), atlas, (-30., -90.), size, Path(png),
           backdrop)
    return {'preview': str(png), 'motion_entry': motion_entry, 'motion': entries[motion_entry].name, 'clip': clip,
            'frames': frames, 'views': ['three-quarter', 'side'], 'evaluation_mode': sampled['evaluation_mode'],
            'skeleton_displacement_max_cm': moved, 'donor_copies': len(copies),
            'donor_copies_max_difference_cm': spread, 'limits': sampled['diagnostics']['limitations'],
            'shows': 'written donor record skinned on the CPU by one native clip; not the game pose, IK or shading',
            'sampled': sampled}


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
        posed = posed_preview(archive, output, out / 'preview-posed.png', motion_entry=int(entry), clip=int(clip),
                              frames=[float(frame) for frame in frames.split(',')])
        posed.pop('sampled', None)
        receipt['posed_preview'] = posed | {'preview': 'preview-posed.png'}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'archive': str(path), 'sha256': receipt['written_sha256'], 'receipt': str(out / 'receipt.json')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
