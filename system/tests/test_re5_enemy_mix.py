"""Several donors on one enemy model: the montage table, the carriers and the mix writer, on synthetic fixtures.

The fixture is the Majini-shaped archive of `test_re5_enemy_writer` with what a mix needs added: an `MTG` montage
resource, and a selection category (the two head groups) whose groups draw two different albedo textures - one
sampled by a single material, one by two materials, as measured on the em1000 pants.
"""
import hashlib
import json
import struct
import zlib

import pytest
from PIL import Image

from gbox import mt_arc, mt_model, mtf_author, mtf_mrl, re5_enemy_writer as W
from tests.test_re5_enemy_writer import MODEL, donor, enemy_mod, one_mesh, skeleton, tex  # noqa: F401  (donor: fixture)

HEAD, BODY, FEET = 1, 2, 3                                     # montage categories of the fixture


def montage(parts, rows):
    """MTG version 2: 8 bytes per part (group, category, mask), 20 per montage (16 values and a float)."""
    raw = b'MTG\0' + struct.pack('<IIIQQ', 2, len(parts), len(rows), 32, 32 + 8 * len(parts))
    raw += b''.join(struct.pack('<HHI', *part) for part in parts)
    for values, scale in rows:
        record = bytearray(16)
        for category, value in values.items():
            record[category] = value
        raw += bytes(record) + struct.pack('<f', scale)
    return raw


PARTS = [(1, HEAD, 1), (11, HEAD, 2), (2, BODY, 1), (7, FEET, 1), (21, HEAD, 4)]      # 21 is another model's group
ROWS = [({}, 1.), ({HEAD: 1}, 1.02), ({HEAD: 1, FEET: 5}, 1.02), ({HEAD: 0x1F, BODY: 0x1F, FEET: 0x1F}, 1.)]


def mix_mrl():
    """Three materials: `skin` samples a_BM alone, `sandal` and `cloth` both sample b_BM; all bind one NM and MM."""
    paths = [MODEL + 'n_NM', MODEL + 'a_BM', MODEL + 'm_MM', MODEL + 'b_BM']
    binds = {'skin': 2, 'sandal': 4, 'cloth': 4}
    table = 40 + len(paths) * 88
    cursor = (table + 72 * len(binds) + 15) & ~15
    raw = bytearray(cursor + 72 * len(binds))
    struct.pack_into('<4sIIIQQQ', raw, 0, b'MRL\0', 34, len(binds), len(paths), mtf_mrl.RE5_SHADER_VERSION, 40, table)
    for i, path in enumerate(paths):
        raw[40 + i * 88 + 24:40 + i * 88 + 24 + len(path)] = path.encode()
    for i, (name, albedo) in enumerate(binds.items()):
        struct.pack_into('<QII', raw, table + 72 * i, mtf_mrl.MATERIAL_STD, zlib.crc32(name.encode()) ^ 0xFFFFFFFF, 72)
        struct.pack_into('<I', raw, table + 72 * i + 28, 3)
        struct.pack_into('<Q', raw, table + 72 * i + 56, cursor)
        for value, shader in ((1, W.NORMAL_HASH), (albedo, mtf_mrl.ALBEDO_HASH), (3, W.MASK_HASH)):
            struct.pack_into('<IIQQ', raw, cursor, 3, 0xCDCDCDCD, value, shader << 12 | 0x375)
            cursor += 24
    return bytes(raw)


def mix_arc(rows=ROWS, parts=PARTS):
    """(archive, reviewed set, mix table) for the two head groups as carriers."""
    contents = [(MODEL + 'a_BM', tex(0x30)), (MODEL + 'b_BM', tex(0x30)), (MODEL + 'n_NM', tex(0x1F)),
                (MODEL + 'm_MM', tex(0x19)), (MODEL + 'body', mix_mrl()), (MODEL + 'body_low', mix_mrl()),
                ('untouched', b'\x02\0\0\0preserved'), (MODEL + 'body', enemy_mod(skeleton())),
                (MODEL + 'body_low', enemy_mod(skeleton(helper=True))), (MODEL + 'body', montage(parts, rows))]
    entries = [mt_arc.Entry(name=name, hash=0x241F5DEB, tag=0x40000000 | len(data), size=0, offset=0,
                            data=zlib.compress(data)) for name, data in contents]
    target = W.EnemySet(name='body', models=((MODEL + 'body', 7, 4), (MODEL + 'body_low', 8, 5)),
                        groups=(('head', (1, 11)), ('body', (2,)), ('feet', (7,))),
                        albedo=(0, MODEL + 'a_BM'), normal=(2, MODEL + 'n_NM'), mask=(3, MODEL + 'm_MM'))
    secondary = ((2, MODEL + 'n_NM'), (3, MODEL + 'm_MM'))
    mix = W.MixTable(name='body-head', target='body', montage=(9, MODEL + 'body'), category=HEAD, slot='head',
                     carriers=(W.Carrier((11,), (1, MODEL + 'b_BM'), *secondary),
                               W.Carrier((1,), (0, MODEL + 'a_BM'), *secondary)))
    return mt_arc.build(mt_arc.Arc(7, entries)), target, mix


def test_reviewed_mix_tables_cover_the_whole_category_with_distinct_textures():
    pants = W.EM1000_PANTS
    assert sorted(g for c in pants.carriers for g in c.groups) == sorted(dict(W.EM1000.groups)['pants'])
    assert len({c.albedo[0] for c in pants.carriers}) == len(pants.carriers) == 10 and pants.montage[0] == 763
    assert pants.category == 11 and W.MIXES['uEm10'] is pants and pants.target == 'em1000'
    shirt = W.EM1100_SHIRT
    assert sorted(g for c in shirt.carriers for g in c.groups) == sorted(dict(W.EM1100.groups)['shirt'])
    assert (shirt.montage[0], shirt.category, shirt.target) == (383, 2, 'em1100') and W.MIXES['uEm11'] is shirt
    for table in (pants, shirt):                       # a carrier never reuses an entry of the model or its MRL
        used = {i for c in table.carriers for i in (c.albedo[0], c.normal[0], c.mask[0])}
        assert not used & {i for _, mod, mrl in W.SETS[table.target].models for i in (mod, mrl)}
    assert set(W.MONTAGE_READING) == {'measured', 'inferred', 'unknown'}        # the receipt says which is which


def test_parse_montage_reads_parts_and_montages_and_refuses_another_layout():
    raw = montage(PARTS, ROWS)
    table = W.parse_montage(raw)
    assert table['parts'] == PARTS and len(table['montages']) == 4
    assert table['montages'][1][0][HEAD] == 1 and table['montages'][1][1] == pytest.approx(1.02)
    present = {1, 2, 7, 11}
    assert W.montage_groups(table, 0, present) == {HEAD: [1], BODY: [2], FEET: [7]}      # the base outfit
    assert W.montage_groups(table, 1, present) == {HEAD: [11], BODY: [2], FEET: [7]}
    assert W.montage_groups(table, 2, present) == {HEAD: [11], BODY: [2]}                # a value with no part: none
    assert W.montage_groups(table, 3, present) == {}                                     # 0x1F everywhere: empty
    assert W.montage_groups(table, 0, {21}) == {}                                        # absent groups never draw
    for broken in (raw[:31], b'XFS\0' + raw[4:], raw + b'\0', raw[:4] + struct.pack('<I', 3) + raw[8:],
                   montage([(1, 16, 1)], ROWS), montage([(1, HEAD, 0)], ROWS), montage(PARTS, [])):
        with pytest.raises(W.EnemyWriterError):
            W.parse_montage(broken)


def test_a_mix_needs_exactly_one_carrier_in_every_drawn_montage():
    archive, target, mix = mix_arc()
    model = mt_model.parse_mod(enemy_mod(skeleton()))
    counted = W.account_mix(model, W.parse_montage(montage(PARTS, ROWS)), mix)
    assert counted == {'shares': {0: [1, 2], 1: [0]}, 'empty_montages': [3], 'drawn_montages': 3}
    headless = ROWS + [({HEAD: 9}, 1.)]                               # draws a body and feet but no head group
    with pytest.raises(W.EnemyWriterError, match='montage 4 draws 0 head groups'):
        W.account_mix(model, W.parse_montage(montage(PARTS, headless)), mix)
    both = [(1, HEAD, 1), (11, HEAD, 3), (2, BODY, 1), (7, FEET, 1)]  # value 0 selects both head groups
    with pytest.raises(W.EnemyWriterError, match='montage 0 draws 2 head groups'):
        W.account_mix(model, W.parse_montage(montage(both, ROWS)), mix)
    partial = W.MixTable('x', 'body', mix.montage, HEAD, 'head', mix.carriers[:1])
    with pytest.raises(W.EnemyWriterError, match='not exactly the head groups'):
        W.account_mix(model, W.parse_montage(montage(PARTS, ROWS)), partial)


def test_graft_pieces_adds_each_donor_to_its_own_groups_through_its_own_material():
    raw = enemy_mod(skeleton())
    native = mt_model.parse_mod(raw)
    first, second = one_mesh(native, 11), one_mesh(native, 3)
    wide = {'min': {'x': -40., 'y': 0., 'z': 0.}, 'max': {'x': 20., 'y': 200., 'z': 30.},
            'sphere': {'x': -10., 'y': 100., 'z': 15., 'r': 110.}}
    second = mt_model.parse_mod(mt_model.rebuild_mod(second, bounds=wide))
    result, report = W.graft_pieces(native, [(first, [11], 1), (second, [1, 7], 0)])
    model = mt_model.parse_mod(result)
    records = model.meshes()
    added = [r for r in records if r['level_of_detail'] == 0xFF]
    assert [(r['group_index'], r['material_index'], r['mesh_id']) for r in added] == [(1, 0, 10), (7, 0, 11), (11, 1, 9)]
    assert [r['material_index'] for r in records] == sorted(r['material_index'] for r in records)
    assert sorted(r['mesh_id'] for r in records) == list(range(1, 12))
    assert report == report | {'native_records': 8, 'donor_records': 3, 'mesh_records': 11, 'envelope_count': 11}
    assert [p['groups'] for p in report['pieces']] == [[11], [1, 7]]
    by_group = {r['group_index']: r['index'] for r in added}
    assert model.mesh_bytes(by_group[11])[0] == first.mesh_bytes(0)[0]
    assert model.mesh_bytes(by_group[1])[0] == model.mesh_bytes(by_group[7])[0] == second.mesh_bytes(0)[0]
    assert all(mtf_author.mesh_triangles(model, r['index']) == [] for r in records if r['level_of_detail'] != 0xFF)
    box = model.bounds()                                              # one box around both donors
    assert (box['min']['x'], box['max']['x'], box['max']['y']) == (-40., 20., 200.) and box['sphere']['r'] >= 110.
    assert W.graft(native, first, groups=[1, 11, 2, 7], material_index=1)[0] == W.graft_pieces(
        native, [(first, [1, 11, 2, 7], 1)])[0]                       # one donor is the proven shape, byte for byte
    with pytest.raises(W.EnemyWriterError, match='distinct option groups'):
        W.graft_pieces(native, [(first, [1], 1), (second, [1], 0)])   # a spawn would draw both
    with pytest.raises(W.EnemyWriterError, match='at least one option group'):
        W.graft_pieces(native, [(first, [1], 1), (second, [], 0)])


def riders(source, fit=W.PROPORTIONAL):
    return [(source, dict(W.SOURCE_ROLES), fit, 'first'), (source, dict(W.SOURCE_ROLES), fit, 'second')]


def test_author_mix_draws_one_donor_per_carrier_group_and_nothing_else(donor):
    archive, target, mix = mix_arc()
    output, receipt = W.author_mix(archive, riders(donor), target, mix)
    before, after = mt_arc.parse(archive), mt_arc.parse(output)
    changed = [i for i, (a, b) in enumerate(zip(before.entries, after.entries)) if a.data != b.data]
    assert changed == [0, 1, 2, 3, 7, 8] == receipt['checks']['changed_entries']        # two atlases, NM, MM, two MODs
    assert before.entries[9].data == after.entries[9].data and receipt['montage_table']['untouched'] is True
    assert W.author_mix(archive, riders(donor), target, mix)[0] == output              # deterministic
    for index, name in ((7, 'body'), (8, 'body_low')):
        model = mt_model.parse_mod(zlib.decompress(after.entries[index].data))
        records = model.meshes()
        carried = {r['group_index']: r for r in records if r['level_of_detail'] == 0xFF}
        assert sorted(carried) == [1, 11] and len(records) == 10                       # groups 2 and 7 carry nothing
        assert (carried[1]['material_index'], carried[11]['material_index']) == (0, 1)  # a_BM alone; first of b_BM's two
        assert all(mtf_author.mesh_triangles(model, r['index']) == [] for r in records if r['level_of_detail'] != 0xFF)
        assert all(len(mtf_author.mesh_triangles(model, r['index'])) == 19 for r in carried.values())
        assert receipt['models'][name]['donor_records'] == 2 and receipt['models'][name]['native_records'] == 8
    assert [(c['groups'], c['donor']['name'], c['montages'], c['share_if_montages_are_uniform'])
            for c in receipt['carriers']] == [([11], 'first', [1, 2], '2 of 3'), ([1], 'second', [0], '1 of 3')]
    assert receipt['montage_table'] == receipt['montage_table'] | {'entry': 9, 'drawn_montages': 3, 'empty_montages': [3]}
    groups = receipt['option_groups']['groups']
    assert groups['11']['donor_record'] == 'carrier 0: first' and groups['2']['donor_record'] == 'none'
    assert receipt['option_groups']['choice'] == 'carry_in_one_category' and receipt['counts']['native_records_blanked'] == 16
    assert receipt['live_verified'] is False and receipt['recipe'] == 're5_enemy_writer.mix'
    # the written file is re-read against what the mix promised
    expect = {name: {11: (1, 0), 1: (0, 1)} for name in ('body', 'body_low')}
    assert W.verify(archive, output, target, textures=[0, 1, 2, 3], expect=expect)['models']['body']['donor_records'] == 2
    with pytest.raises(W.EnemyWriterError, match='carrying option group'):
        W.verify(archive, output, target, textures=[0, 1, 2, 3], expect={n: {11: (1, 0), 2: (0, 1)} for n in expect})
    with pytest.raises(W.EnemyWriterError, match='mesh count'):
        W.verify(archive, output, target, textures=[0, 1, 2, 3], expect={n: {11: (1, 0)} for n in expect})
    with pytest.raises(W.EnemyWriterError, match='donor record shape'):
        W.verify(archive, output, target, textures=[0, 1, 2, 3], expect={n: {11: (2, 0), 1: (0, 1)} for n in expect})
    with pytest.raises(W.EnemyWriterError, match='outside the reviewed indices'):
        W.verify(archive, output, target, textures=[0, 2, 3], expect=expect)
    # each donor is fitted on its own: another fit for one carrier changes only that donor
    mixed = [riders(donor)[0], (donor, dict(W.SOURCE_ROLES), W.NATIVE_HEIGHT, 'second')]
    other, second = W.author_mix(archive, mixed, target, mix)
    assert second['carriers'][0]['fit'] == receipt['carriers'][0]['fit'] != second['carriers'][1]['fit']
    assert other != output


def test_author_mix_refuses_what_it_cannot_promise(donor):
    archive, target, mix = mix_arc()
    with pytest.raises(W.EnemyWriterError, match='one donor for each of its 2 carriers'):
        W.author_mix(archive, riders(donor)[:1], target, mix)
    with pytest.raises(W.EnemyWriterError, match='fifteen'):
        W.author_mix(archive, [riders(donor)[0], (donor, {'hip': 'skl_root'}, W.PROPORTIONAL, 'stub')], target, mix)
    headless, _, _ = mix_arc(rows=ROWS + [({HEAD: 9}, 1.)])
    with pytest.raises(W.EnemyWriterError, match='draws 0 head groups'):
        W.author_mix(headless, riders(donor), target, mix)
    wrong = W.MixTable(mix.name, 'body', (6, 'untouched'), HEAD, 'head', mix.carriers)
    with pytest.raises(W.EnemyWriterError, match='MTG resource'):
        W.author_mix(archive, riders(donor), target, wrong)
    lone = W.Carrier((1,), (0, MODEL + 'a_BM'), (3, MODEL + 'm_MM'), (2, MODEL + 'n_NM'))     # maps swapped
    with pytest.raises(W.EnemyWriterError):
        W.author_mix(archive, riders(donor), target, W.MixTable('x', 'body', mix.montage, HEAD, 'head',
                                                                (mix.carriers[0], lone)))


def test_build_mix_deals_library_donors_over_the_carriers(donor, tmp_path, monkeypatch):
    archive, target, mix = mix_arc()
    monkeypatch.setitem(W.SETS, 'body', target)
    enemy = W.EnemyArchive('uSyn', 'nativeNXx64/ImgNX/Archive/uSyn.arc', hashlib.sha256(archive).hexdigest(),
                           ('body',), ('body',), (9, 2, (1.,)), ())
    monkeypatch.setitem(W.MIXES, 'uSyn', mix)

    def library(slug):
        entry = tmp_path / slug
        entry.mkdir()
        (entry / 'model.glb').write_bytes(b'donor ' + slug.encode())
        (entry / 'meta.json').write_text(json.dumps({'slug': slug, 'name': slug.title(), 'model': 'model.glb',
                                                     'rig': {'roles': W.SOURCE_ROLES}}), encoding='utf-8')
        return W.load_donor(entry)
    alpha, beta, gamma = library('alpha'), library('beta'), library('gamma')
    output, receipt = W.build_mix(archive, [alpha, beta], enemy, fits=[W.PROPORTIONAL, W.PROPORTIONAL])
    assert [c['donor']['slug'] for c in receipt['carriers']] == ['alpha', 'beta']
    assert [(d['slug'], d['groups'], d['share_if_montages_are_uniform']) for d in receipt['donors']] == [
        ('alpha', [11], '2 of 3'), ('beta', [1], '1 of 3')]
    assert receipt['target']['class'] == 'uSyn' and receipt['replacement_scope']['complete'] is False
    solo, one = W.build_mix(archive, [gamma], enemy)                  # one donor rides on every carrier
    assert [c['donor']['slug'] for c in one['carriers']] == ['gamma', 'gamma']
    assert one['donors'][0]['groups'] == [11, 1] and one['donors'][0]['share_if_montages_are_uniform'] == '3 of 3'
    high, narrow = W.build_mix(archive, [alpha, beta], enemy, models=('body',))
    assert narrow['target']['models'] == ['body'] and narrow['checks']['changed_entries'] == [0, 1, 2, 3, 7]
    with pytest.raises(W.EnemyWriterError, match='one to 2 donors'):
        W.build_mix(archive, [alpha, beta, gamma], enemy)
    with pytest.raises(W.EnemyWriterError, match='each donor once'):
        W.build_mix(archive, [alpha, alpha], enemy)
    with pytest.raises(W.EnemyWriterError, match='exact measured original'):
        W.build_mix(archive + b'x', [alpha], enemy)
    monkeypatch.delitem(W.MIXES, 'uSyn')
    with pytest.raises(W.EnemyWriterError, match='no reviewed mix table'):
        W.build_mix(archive, [alpha], enemy)


def test_previews_show_the_donor_of_one_carrier(donor, tmp_path, monkeypatch):
    archive, target, mix = mix_arc()
    output, _ = W.author_mix(archive, riders(donor), target, mix)
    monkeypatch.undo()                                  # the preview reads its own glTF through the real loader
    for number, carrier in enumerate(mix.carriers):
        report = W.preview(output, tmp_path / f'{number}.png', target=target, size=48, carrier=carrier,
                           backdrop=(54, 60, 72))
        model = mt_model.parse_mod(zlib.decompress(mt_arc.parse(output).entries[7].data))
        assert model.meshes()[report['record']]['group_index'] == carrier.groups[0] and report['triangles'] == 19
        picture = Image.open(tmp_path / f'{number}.png')
        assert picture.size == (144, 48) and picture.getpixel((0, 0)) == (54, 60, 72)   # empty space is the backdrop
    with pytest.raises(W.EnemyWriterError, match='no donor record'):
        W.preview(output, tmp_path / 'none.png', target=target,
                  carrier=W.Carrier((2,), mix.carriers[0].albedo, mix.carriers[0].normal, mix.carriers[0].mask))
