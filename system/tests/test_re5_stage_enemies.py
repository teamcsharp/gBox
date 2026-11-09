"""Enemy classes per Mercenaries stage, read from synthetic XFS layouts (no game file is read)."""
import json
import struct
import zlib

import pytest

from gbox import mt_arc, re5_stage_enemies as S

U32, S32, BOOL, STRING, VECTOR, OBJECT = 6, 10, 3, 14, 20, 2
LAYOUT = [('mQuality', U32), ('mSetInfos', OBJECT)]
SET = [('mID', S32), ('mInfoClass', STRING), ('mUnitClass', STRING), ('mpInfo', OBJECT)]
INFO = [('mName', STRING), ('mPosition', VECTOR), ('mModelType', U32), ('mMontageNo', U32), ('mIsFindPL', BOOL)]
ITEM = [('mName', STRING), ('mItemNo', U32)]


def xfs(rows, classes=(LAYOUT, SET, INFO, ITEM)):
    """One layout in the measured 64-bit XFS layout; `rows` = (unit class, info class, model type, montage)."""
    names = bytearray()
    blocks = []
    for properties in classes:
        block = bytearray(struct.pack('<QQ', 0x1234, len(properties)))
        for name, kind in properties:
            block += struct.pack('<QBBH', len(names), kind, 0, 8) + bytes(68)      # the name offset is fixed up below
            names += name.encode() + b'\0'
        blocks.append(block)
    table = 8 * len(classes)
    starts, cursor = [], table
    for block in blocks:
        starts.append(cursor)
        cursor += len(block)
    names_at = cursor
    for block in blocks:
        for i in range(struct.unpack_from('<Q', block, 8)[0]):
            at = 16 + 80 * i
            struct.pack_into('<Q', block, at, names_at + struct.unpack_from('<Q', block, at)[0])
    definitions = struct.pack(f'<{len(classes)}Q', *starts) + b''.join(blocks) + bytes(names)

    def obj(index, serial, body):
        return struct.pack('<hHQ', index * 2 + 1, serial, len(body) + 8) + body

    def one(fmt, *values):
        return struct.pack('<I', 1) + struct.pack(fmt, *values)
    sets = b''
    for serial, (unit, info, model_type, montage) in enumerate(rows):
        if info == 'cSetInfoItem':
            inner = obj(3, serial, struct.pack('<I', 1) + b'box\0' + one('<I', 7))
        elif info is None:
            inner = struct.pack('<hH', -2, 0)                                      # an empty reference
        else:
            inner = obj(2, serial, struct.pack('<I', 1) + b'\0' + one('<4f', 1., 2., 3., 0.) + one('<I', model_type)
                        + one('<I', montage) + one('<?', True))
        sets += obj(1, serial, one('<i', serial) + struct.pack('<I', 1) + (info or 'cSetInfoEnemy').encode() + b'\0'
                    + struct.pack('<I', 1) + unit.encode() + b'\0' + struct.pack('<I', 1) + inner)
    root = obj(0, 0, one('<I', 2) + struct.pack('<I', len(rows)) + sets)
    total = sum(len(c) for c in classes)
    return b'XFS\0' + struct.pack('<HHIIII', 16, 4, total, 0, len(classes), len(definitions)) + definitions + root


TOWN = [('uEm10', 'cSetInfoEm10', 0, S.RANDOM_MONTAGE), ('uEm10', 'cSetInfoEm10', 0, S.RANDOM_MONTAGE),
        ('uEm11', 'cSetInfoEm10', 0, 1), ('uEm11', 'cSetInfoEm10', 0, S.RANDOM_MONTAGE)]
BOSS = [('uEm20', 'cSetInfoEnemy', 0, 0), ('uEm20', None, 0, 0)]
ITEMS = [('uWp06', 'cSetInfoItem', 0, 0), ('uOm0886', 'cSetInfoEm10', 0, 0)]


def test_read_xfs_decodes_the_whole_tree_and_refuses_anything_else():
    raw = xfs(TOWN)
    tree = S.read_xfs(raw)
    assert tree['mQuality'] == 2 and len(tree['mSetInfos']) == 4 and tree['__class'] == 0
    first = tree['mSetInfos'][0]
    assert (first['mID'], first['mInfoClass'], first['mUnitClass']) == (0, 'cSetInfoEm10', 'uEm10')
    assert first['mpInfo'] == {'__class': 2, 'mName': '', 'mPosition': (1., 2., 3., 0.), 'mModelType': 0,
                               'mMontageNo': S.RANDOM_MONTAGE, 'mIsFindPL': True}
    assert S.read_xfs(xfs(BOSS))['mSetInfos'][1]['mpInfo'] is None                 # an empty reference is no object
    for broken in (raw[:20], b'ARC\0' + raw[4:], raw + b'\0', raw[:-3], raw[:4] + struct.pack('<H', 15) + raw[6:]):
        with pytest.raises(S.XfsError):
            S.read_xfs(broken)
    with pytest.raises(S.XfsError, match='not measured'):
        S.read_xfs(xfs(TOWN, classes=(LAYOUT, SET, [(n, 99 if n == 'mModelType' else k) for n, k in INFO], ITEM)))
    size_at = raw.index(b'\x01\x00\x00\x00', 0x18 + struct.unpack_from('<I', raw, 0x14)[0]) + 4
    longer = bytearray(raw)
    struct.pack_into('<Q', longer, size_at, struct.unpack_from('<Q', raw, size_at)[0] + 4)
    with pytest.raises(S.XfsError):
        S.read_xfs(bytes(longer))


def test_spawns_lists_enemies_only_with_their_model_type_and_montage():
    assert S.spawns(xfs(TOWN)) == [
        {'class': 'uEm10', 'info_class': 'cSetInfoEm10', 'model_type': 0, 'montage': S.RANDOM_MONTAGE},
        {'class': 'uEm10', 'info_class': 'cSetInfoEm10', 'model_type': 0, 'montage': S.RANDOM_MONTAGE},
        {'class': 'uEm11', 'info_class': 'cSetInfoEm10', 'model_type': 0, 'montage': 1},
        {'class': 'uEm11', 'info_class': 'cSetInfoEm10', 'model_type': 0, 'montage': S.RANDOM_MONTAGE}]
    assert S.spawns(xfs(ITEMS)) == []                                              # weapons and objects are not enemies
    assert S.spawns(xfs(BOSS)) == [{'class': 'uEm20', 'info_class': 'cSetInfoEnemy', 'model_type': 0, 'montage': 0},
                                   {'class': 'uEm20', 'info_class': 'cSetInfoEnemy', 'model_type': None, 'montage': None}]
    assert S.spawns(xfs([])) == []


def test_census_counts_classes_per_mode_and_names_the_archives_a_build_must_replace():
    layouts = {'merceex': {'s400_em01': xfs(TOWN), 's400_em02': xfs(TOWN[:3]), 's400_em09': xfs(BOSS)},
               'merce': {'s400_em01': xfs(TOWN[:1])}}
    counted = S.census(layouts)
    assert list(counted) == ['merce', 'merceex'] and list(counted['merceex']) == ['uEm10', 'uEm11', 'uEm20']
    assert counted['merceex']['uEm10'] == {'count': 4, 'layouts': ['s400_em01', 's400_em02'],
                                           'info_classes': ['cSetInfoEm10'], 'model_types': [0],
                                           'montages': [S.RANDOM_MONTAGE], 'random_montage': True}
    assert counted['merceex']['uEm11']['montages'] == [1, S.RANDOM_MONTAGE] and counted['merceex']['uEm11']['count'] == 3
    assert counted['merceex']['uEm20'] == counted['merceex']['uEm20'] | {'count': 2, 'montages': [0, None],
                                                                        'random_montage': False}
    assert S.archives_needed(counted, 'merceex') == ['uEm10.arc', 'uEm11.arc', 'uEm20.arc']
    assert S.archives_needed(counted, 'merce') == ['uEm10.arc'] and S.archives_needed(counted, 'vss') == []


def test_stage_layouts_takes_the_enemy_layouts_of_each_mode_from_a_stage_archive(tmp_path, capsys):
    def entry(name, data, kind=S.LAYOUT_HASH):
        return mt_arc.Entry(name=name, hash=kind, tag=0x40000000 | len(data), size=0, offset=0, data=zlib.compress(data))
    archive = mt_arc.build(mt_arc.Arc(7, [
        entry('stage\\s400\\soft\\merce\\s400_em00', xfs(TOWN)),
        entry('stage\\s400\\soft\\merceex\\s400_em00', xfs(TOWN + BOSS)),
        entry('stage\\s400\\soft\\merceex\\s400_em09', xfs(BOSS)),
        entry('stage\\s400\\soft\\merceex\\s400_Item', xfs(ITEMS)),                 # an item layout, not an enemy one
        entry('stage\\s400\\soft\\merceex\\fsm\\EmSetArea0', b'fsm', 0x25F4D5AD),
        entry('stage\\s400\\soft\\merceex\\s400_em10', b'not a layout', 0x241F5DEB),  # the name alone is not enough
        entry('stage\\s401\\soft\\merce\\s400_em00', xfs(BOSS))]))                  # another stage's folder
    layouts = S.stage_layouts(archive)
    assert {mode: sorted(names) for mode, names in layouts.items()} == {'merce': ['s400_em00'],
                                                                         'merceex': ['s400_em00', 's400_em09']}
    assert S.census(layouts)['merceex']['uEm20']['count'] == 4
    assert list(S.STAGES) == [f's40{i}' for i in range(8)] and S.STAGES['s400'] == 'Public Assembly'
    path = tmp_path / 's400.arc'
    path.write_bytes(archive)
    assert S.main([str(path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['s400']['name'] == 'Public Assembly' and printed['s400']['modes']['merce']['uEm11']['count'] == 2
    folder = tmp_path / 's407' / 'merce'
    folder.mkdir(parents=True)
    (folder / 's407_em03.lot').write_bytes(xfs(BOSS))
    assert S.main([str(tmp_path / 's407')]) == 0
    assert json.loads(capsys.readouterr().out)['s407']['modes']['merce']['uEm20']['count'] == 2
