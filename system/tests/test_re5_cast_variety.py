"""More donors per round: wide mix tables, the other Majini classes' skeleton and LOD shapes, and the build series.

Synthetic fixtures only (the Majini-shaped archive of `test_re5_enemy_writer` with what the other classes add: a
detached root bone, a native record with LOD mask 255, an option group 0, an all-zero montage part, a mask map in a
texture format the codec cannot rewrite). The real class archives are only read by the opt-in test at the end.
"""
import hashlib
import json
import os
import struct
import zlib
from pathlib import Path

import pytest

from gbox import mt_arc, mt_model, mtf_author, re5_cast_series as S, re5_cast_writer as P, re5_donor_pool as pool
from gbox import re5_enemy_cast as C, re5_enemy_writer as W
from tests.test_re5_enemy_mix import HEAD, BODY, FEET, PARTS, ROWS, mix_mrl, montage
from tests.test_re5_enemy_writer import FULL, MODEL, ONE, bone_block, donor, pack, parts, skeleton, tex  # noqa: F401


def variety_mod(bones, *, rows=None, groups=(1, 2, 7, 11), materials=('skin', 'sandal', 'cloth')):
    """`enemy_mod` with the record list open: extra rows may use any LOD mask, mesh ids stay 1..count."""
    rows = rows if rows is not None else parts(bones)
    records, vertices, words, envelopes = b'', b'', [], b''
    offset = index = 0
    for number, row in enumerate(rows):
        stride = 28 if row['fmt'] == FULL else 20
        data = pack(row['fmt'], row['points'], row['bone'])
        if row.get('shared'):
            index += len(rows[number - 1]['points'])
        else:
            offset, index = len(vertices), 0
        vertices += data
        strip = []
        for k, part in enumerate(row['strips']):
            strip += ([0xFFFF] if k else []) + [v + index for v in part]
        record = bytearray(56)
        struct.pack_into('<HHI', record, 0, row['kind'], len(row['points']),
                         row['group'] | row['material'] << 12 | row['lod'] << 24)
        record[8:12] = bytes((row['flags'], number, stride, row['mode']))
        struct.pack_into('<II', record, 0x0C, index, offset)
        struct.pack_into('>I', record, 0x14, row['fmt'])
        struct.pack_into('<III', record, 0x18, len(words), len(strip), 0)
        record[0x25] = 1
        struct.pack_into('<HHH', record, 0x26, number + 1, index, index + len(row['points']) - 1)
        record[0x2C:0x38] = bytes([0xA0 + number]) * 12
        records += record
        words += strip + [0xFFFF]
        envelopes += mtf_author.pack_weight_bound(row['bone'], row['points'])
    indices = struct.pack(f'<{len(words)}H', *words) + bytes((2 * len(words)) % 4)
    tail = struct.pack('<12f', 0, 90, 0, 120, -80, 0, -20, 0, 80, 190, 20, 0) + struct.pack('<5I', 500, 1000, 3, 0,
                                                                                         len(rows))
    group_block = b''.join(struct.pack('<I12x4f', group, 0, 10, 0, 30) for group in groups)
    material_block = b''.join(name.encode().ljust(128, b'\0') for name in materials)
    blocks = (bone_block(bones), group_block, material_block, records + envelopes, vertices, indices)
    offsets = [0x28 + 56 + len(tail)]
    for block in blocks:
        offsets.append(offsets[-1] + len(block))
    out = mt_model.MOD_MAGIC + bytes((211, 0)) + struct.pack('<3H', len(bones), len(rows), len(materials))
    out += struct.pack('<3I2I2I', sum(len(r['points']) for r in rows), len(words), 9, len(vertices), 0, len(groups), 0)
    out += struct.pack('<7Q', *offsets) + tail + b''.join(blocks) + bytes(4)
    return out


def class_rows(bones, *, lod_255=True, group_zero=False):
    """The fixture's native records plus what em1200/em1400 add: a tongue with mask 255 and an option group 0."""
    b = {name: i for i, (name, *_) in enumerate(bones)}
    rows = parts(bones)
    if lod_255:
        rows.append(dict(group=1, material=0, lod=255, kind=0xFFFF, mode=4, fmt=ONE, flags=9, bone=b['head'],
                         points=[(-1., 160., 4.), (1., 160., 4.), (0., 158., 6.)], strips=[[0, 1, 2]]))
    if group_zero:
        rows.append(dict(group=0, material=0, lod=1, kind=0xFFFF, mode=4, fmt=ONE, flags=9, bone=b['head'],
                         points=[(-2., 168., 6.), (2., 168., 6.), (0., 172., 7.)], strips=[[0, 1, 2]]))
    return sorted(rows, key=lambda row: row['material'])


def detached(bones):
    """The skeleton with em1200's extra root: a childless, unskinned bone at the origin with animation id 250."""
    return bones + [('attach', 250, None, (0, 0, 0))]


def test_measure_roles_lists_a_detached_root_and_still_refuses_a_second_root_with_children():
    bones = detached(skeleton())
    model = mt_model.parse_mod(variety_mod(bones))
    roles, extra = W.role_map(model)
    assert extra['skeleton']['detached_bones'] == [len(bones) - 1] and roles['head'] == len(bones) - 2
    assert W.measure_roles(mt_model.parse_mod(variety_mod(skeleton())))[1].get('detached_bones') is None
    second = skeleton() + [('other_root', 250, None, (0, 0, 0)), ('other_child', 251, 'other_root', (0, 5, 0))]
    with pytest.raises(W.EnemyWriterError, match='one root with children'):
        W.measure_roles(mt_model.parse_mod(variety_mod(second)))
    assert set(W.LOD_MASK_READING) == {'bits', 'measured_on', 'evidence'}


def test_account_groups_takes_the_declared_lod_masks_and_a_group_zero_and_refuses_the_rest():
    bones = skeleton()
    model = mt_model.parse_mod(variety_mod(bones, rows=class_rows(bones, group_zero=True), groups=(0, 1, 2, 7, 11)))
    target = W.EnemySet('body', ((MODEL + 'body', 7, 4),), (('face', (0,)), ('head', (1, 11)), ('body', (2,)),
                                                              ('feet', (7,))),
                        (0, MODEL + 'sandal_BM'), (2, MODEL + 'sandal_NM'), (1, MODEL + 'sandal_MM'),
                        lod_masks=(1, 2, 252, 255))
    accounted = W.account_groups(model, target)
    assert accounted[0]['slot'] == 'face' and accounted[1]['native_lod_masks'] == [1, 2, 252, 255]
    plain = W.EnemySet('body', target.models, target.groups, target.albedo, target.normal, target.mask)
    with pytest.raises(W.EnemyWriterError, match=r'masks \[1, 2, 252, 255\]; reviewed \[1, 2, 252\]'):
        W.account_groups(model, plain)
    for enemy_set in (W.EM1200, W.EM1300, W.EM1400, W.EM2100):     # the reviewed classes declare their masks
        assert set(enemy_set.lod_masks) >= {1, 2, 252} and enemy_set.name in W.SETS
    assert 0 in W.EM1400.group_ids() and 0 not in W.EM1200.group_ids()
    for enemy in ('uEm12', 'uEm13', 'uEm14', 'uEm21'):
        archive = W.ARCHIVES[enemy]
        assert archive.default_sets == archive.sets and len(archive.sha256) == 64 and archive.pose[1] == 105
        assert W.STAGE_COVERAGE[enemy]
    assert W.STAGE_COVERAGE['uEm12'] == {'s402': 325, 's403': 386}


def test_parse_montage_keeps_an_all_zero_part_row_and_refuses_a_part_without_a_mask():
    table = W.parse_montage(montage(PARTS + [(0, 0, 0)], ROWS))
    assert table['empty_parts'] == [len(PARTS)] and len(table['parts']) == len(PARTS) + 1
    assert W.montage_groups(table, 0, {1, 2, 7, 11}) == {HEAD: [1], BODY: [2], FEET: [7]}
    with pytest.raises(W.EnemyWriterError):
        W.parse_montage(montage(PARTS + [(1, HEAD, 0)], ROWS))
    assert W.parse_montage(montage(PARTS, ROWS))['empty_parts'] == []


def mixed_arc(*, lod_255=True, mask_fmt=0x19):
    """The mix fixture with a native LOD-255 record in both models and, on request, an undecodable mask map."""
    mask = tex(mask_fmt) if mask_fmt in (0x19, 0x1F, 0x30) else (
        b'TEX\0\xa1\x80\0\x20' + struct.pack('<3I', 1 | 32 << 6 | 32 << 19, 0x10001 | mask_fmt << 8, 64)
        + struct.pack('<I', 0) + bytes(64))
    high, low = skeleton(), skeleton(helper=True)
    contents = [(MODEL + 'a_BM', tex(0x30)), (MODEL + 'b_BM', tex(0x30)), (MODEL + 'n_NM', tex(0x1F)),
                (MODEL + 'm_MM', mask), (MODEL + 'body', mix_mrl()), (MODEL + 'body_low', mix_mrl()),
                ('untouched', b'\x02\0\0\0preserved'),
                (MODEL + 'body', variety_mod(high, rows=class_rows(high, lod_255=lod_255))),
                (MODEL + 'body_low', variety_mod(low, rows=class_rows(low, lod_255=lod_255))),
                (MODEL + 'body', montage(PARTS, ROWS))]
    entries = [mt_arc.Entry(name=name, hash=0x241F5DEB, tag=0x40000000 | len(data), size=0, offset=0,
                            data=zlib.compress(data)) for name, data in contents]
    target = W.EnemySet(name='body', models=((MODEL + 'body', 7, 4), (MODEL + 'body_low', 8, 5)),
                        groups=(('head', (1, 11)), ('body', (2,)), ('feet', (7,))),
                        albedo=(0, MODEL + 'a_BM'), normal=(2, MODEL + 'n_NM'), mask=(3, MODEL + 'm_MM'),
                        lod_masks=(1, 2, 252, 255) if lod_255 else W.NATIVE_LOD_MASKS)
    secondary = ((2, MODEL + 'n_NM'), (3, MODEL + 'm_MM'))
    mix = W.MixTable(name='body-head', target='body', montage=(9, MODEL + 'body'), category=HEAD, slot='head',
                     carriers=(W.Carrier((11,), (1, MODEL + 'b_BM'), *secondary),
                               W.Carrier((1,), (0, MODEL + 'a_BM'), *secondary)))
    return mt_arc.build(mt_arc.Arc(7, entries)), target, mix


def test_donor_records_are_told_by_mesh_id_where_a_native_record_uses_lod_255(donor, tmp_path, monkeypatch):
    archive, target, mix = mixed_arc()
    riders = [(donor, dict(W.SOURCE_ROLES), W.NATIVE_HEIGHT, 'first'), (donor, dict(W.SOURCE_ROLES), W.PROPORTIONAL,
                                                                        'second', 'ccw')]
    output, receipt = W.author_mix(archive, riders, target, mix)
    for short, mod_index in (('body', 7), ('body_low', 8)):
        natives = mt_model.parse_mod(zlib.decompress(mt_arc.parse(archive).entries[mod_index].data)).meshes()
        written = mt_model.parse_mod(zlib.decompress(mt_arc.parse(output).entries[mod_index].data))
        records = written.meshes()
        assert sum(r['level_of_detail'] == 255 for r in natives) == 1          # the tongue is native and stays
        donors = [r for r in records if r['mesh_id'] > len(natives)]
        assert sorted(r['group_index'] for r in donors) == [1, 11] and all(r['level_of_detail'] == 255 for r in donors)
        kept = [r for r in records if r['mesh_id'] <= len(natives) and r['level_of_detail'] == 255]
        assert len(kept) == 1 and mtf_author.mesh_triangles(written, records.index(kept[0])) == []
        assert receipt['checks']['models'][short]['donor_records'] == 2
    # the previews find the donor record through the original's record count, not through the LOD mask
    monkeypatch.undo()                                  # the preview reads its own glTF through the real loader
    pictures = W.preview(output, tmp_path / 'rest.png', target=target, carrier=mix.carriers[1], original=archive)
    assert pictures['triangles'] == 19 and pictures['record'] == 6 and (tmp_path / 'rest.png').is_file()
    assert receipt['montage_table']['exact_cover'].startswith('every drawn montage') and receipt['carriers'][1]['winding_reversed'] is False
    assert receipt['appearance']['secondary_maps_kept_native'] == []


def test_an_undecodable_mask_map_stays_native_and_is_named_in_the_receipt(donor):
    archive, target, mix = mixed_arc(mask_fmt=0x13)
    riders = [(donor, dict(W.SOURCE_ROLES), W.NATIVE_HEIGHT, 'first'), (donor, dict(W.SOURCE_ROLES), W.NATIVE_HEIGHT,
                                                                        'second')]
    output, receipt = W.author_mix(archive, riders, target, mix)
    before, after = mt_arc.parse(archive), mt_arc.parse(output)
    assert after.entries[3].data == before.entries[3].data                      # the 0x13 mask is byte-identical
    assert after.entries[2].data != before.entries[2].data                      # the BC5 normal was flattened
    assert receipt['appearance']['secondary_maps_kept_native'] == ['m_MM']
    assert 3 not in receipt['checks']['changed_entries'] and 2 in receipt['checks']['changed_entries']
    with pytest.raises(W.EnemyWriterError, match='not a secondary map the writer can neutralise'):
        W._neutral(before, [((0, MODEL + 'a_BM'), (0,))], {}, [])            # a BC7 albedo is not silently kept


def test_a_clockwise_donor_has_its_triangles_turned_on_the_way_in(donor, monkeypatch):
    archive, target, mix = mixed_arc()
    seen = []
    real = W.re5_mesh_import.build_archive

    def spy(*args, **options):
        seen.append(options.get('reverse_winding'))
        return real(*args, **options)
    monkeypatch.setattr(W.re5_mesh_import, 'build_archive', spy)
    riders = [(donor, dict(W.SOURCE_ROLES), W.NATIVE_HEIGHT, 'first', 'cw'),
              (donor, dict(W.SOURCE_ROLES), W.NATIVE_HEIGHT, 'second', 'ccw')]
    _, receipt = W.author_mix(archive, riders, target, mix)
    assert seen == [True, False, True, False] and [c['winding_reversed'] for c in receipt['carriers']] == [True, False]
    with pytest.raises(W.EnemyWriterError, match="'cw' or 'ccw'"):
        W.author_mix(archive, [riders[0], (donor, dict(W.SOURCE_ROLES), W.NATIVE_HEIGHT, 'second', 'flipped')], target,
                     mix)
    whole = W.Donor('d', 'D', Path(donor), hashlib.sha256(Path(donor).read_bytes()).hexdigest(), dict(W.SOURCE_ROLES),
                    winding='cw')
    seen.clear()
    _, one = W.author(archive, donor, target, source_roles=whole.roles, fit=W.NATIVE_HEIGHT, reverse_winding=True)
    assert seen == [True, True] and one['appearance']['winding_reversed'] is True


def test_the_label_table_and_the_class_tables_are_what_the_series_reads():
    assert P.LABEL_ARCHIVES['Chris (Safari)'] == 'uPl00ChrisCos2' and P.LABEL_ARCHIVES['Chris (STARS)'] == 'uPl00ChrisCos1'
    assert S.enemy_slots() == {'uEm10': 16, 'uEm11': 2, 'uEm12': 4, 'uEm13': 2, 'uEm14': 9, 'uEm21': 1}
    assert S.enemy_slots(['uEm10'], {'uEm10': 'em1000-pants'}) == {'uEm10': 10}
    assert S.enemy_slots(['uEm10'], {'uEm10': 'em1000-shirts'}) == {'uEm10': 15}
    assert S.PLAYER_SLOTS == tuple(P.SLOTS) and len(S.PLAYER_SLOTS) == 6
    assert set(S.ROTATION) == {'today', 'with_hotswap', 'ordering', 'players'}


def pool_donor(slug, franchise='Sonic', game=None):
    return pool.Donor(slug=slug, name=slug.title(), game=game or franchise, franchise=franchise, platform='test',
                      model=f'{slug}.glb', sha256=hashlib.sha256(slug.encode()).hexdigest(),
                      roles=tuple((role, f'{slug}_{role}') for role in pool.ROLES), roles_from='test',
                      provenance='test')


def many_donors(count=100):
    franchises = ['Sonic', 'Mario', 'Metal Gear', 'Wrestling', 'Dead or Alive', 'Shenmue', '007']
    return [pool_donor(f'd{i:03d}', franchises[i % len(franchises)] if i % 11 else 'Wrestling') for i in range(count)]


def test_plan_series_covers_every_donor_once_before_any_twice_and_is_a_pure_function():
    donors = many_donors(100)
    sizes = {'uEm10': 16, 'uEm11': 2}
    slugs = {d.slug for d in donors}
    builds = S.plan_series('s', donors, enemy_pool=slugs, sizes=sizes)
    again = S.plan_series('s', list(reversed(donors)), enemy_pool=set(slugs), sizes=dict(sizes))
    assert [b.slugs() for b in builds] == [b.slugs() for b in again]
    per_build = 6 + 18
    assert len(builds) == -(-100 // per_build) == 5
    for build in builds:
        used = build.slugs()
        assert len(used) == len(set(used)) == per_build                       # no donor twice in a build
        assert set(build.players) == set(S.PLAYER_SLOTS) and {k: len(v) for k, v in build.enemies.items()} == sizes
    counts = {}
    for build in builds:
        for slug in build.slugs():
            counts[slug] = counts.get(slug, 0) + 1
    assert set(counts) == slugs and max(counts.values()) == 2 and sum(len(b.first_time) for b in builds) == 100
    assert [len(b.first_time) for b in builds] == [24, 24, 24, 24, 4]
    assert all(set(b.first_time) <= set(b.slugs()) for b in builds)
    # franchises in turn: the players of the first build are not all wrestlers although wrestlers are the most
    assert len({d.franchise for d in donors if d.slug in builds[0].players.values()}) >= 4
    other = S.plan_series('t', donors, enemy_pool=slugs, sizes=sizes)
    assert other[0].slugs() != builds[0].slugs()


def test_plan_series_honours_refusals_eligibility_and_fixed_builds():
    donors = many_donors(60)
    slugs = {d.slug for d in donors}
    sizes = {'uEm10': 4}
    only_players = {'d001', 'd002'}
    builds = S.plan_series('s', donors, enemy_pool=slugs - only_players, sizes=sizes,
                           refusals={'d003': {'player': 'no'}, 'd004': {'enemy': 'no'}})
    for build in builds:
        enemy_slugs = {s for v in build.enemies.values() for s in v}
        assert not enemy_slugs & (only_players | {'d004'}) and 'd003' not in build.players.values()
    dealt = {s for b in builds for s in b.slugs()}
    assert only_players <= dealt and {'d003', 'd004'} <= dealt            # still covered, in the other role
    fixed = builds[:2]
    again = S.plan_series('s', donors, enemy_pool=slugs - only_players, sizes=sizes,
                          refusals={'d003': {'player': 'no'}, 'd004': {'enemy': 'no'}}, fixed=fixed)
    assert again[:2] == fixed and len(again) == len(builds)
    with pytest.raises(S.SeriesError, match='cannot fill'):
        S.plan_series('s', donors, enemy_pool=set(), sizes=sizes)
    with pytest.raises(S.SeriesError, match='still unseen'):
        S.plan_series('s', donors, enemy_pool=slugs, sizes=sizes, limit=1)


def test_substitute_is_deterministic_prefers_an_unseen_donor_of_the_franchise_and_never_repeats_the_build():
    donors = many_donors(40)
    franchise_of = {d.slug: d.franchise for d in donors}
    build = S.Build(3, 's-03', {'chris_bsaa': 'd000'}, {'uEm10': ['d001', 'd002', 'd003']})
    pool_ = {d.slug for d in donors}
    seen = {f'd{i:03d}' for i in range(4, 30)}
    first = S.substitute(build, 'uEm10', 'd002', candidates=pool_, seen=seen, franchise_of=franchise_of)
    again = S.substitute(build, 'uEm10', 'd002', candidates=set(pool_), seen=set(seen), franchise_of=franchise_of)
    assert first == again and first not in build.slugs() and first not in seen
    assert franchise_of[first] == franchise_of['d002']                      # an unseen donor of the same franchise
    everyone_seen = S.substitute(build, 'uEm10', 'd002', candidates=pool_, seen=pool_, franchise_of=franchise_of)
    assert everyone_seen not in build.slugs() and franchise_of[everyone_seen] == franchise_of['d002']
    with pytest.raises(S.SeriesError, match='no donor is left'):
        S.substitute(build, 'uEm10', 'd002', candidates=set(build.slugs()), seen=set(), franchise_of=franchise_of)


def test_refused_slug_is_read_from_both_writers_messages():
    slugs = ['sonic', 'sa2_shadow', 'sonic_x']
    assert S._refused_slug('build-01: chris_bsaa <- sonic_x: sonic_x is not a usable donor (rig_refused): ...', slugs) == 'sonic_x'
    assert S._refused_slug('uEm10 <- sonic+sa2_shadow+sonic_x: sa2_shadow cannot be fitted on em1000: collapsed', slugs) == 'sa2_shadow'
    assert S._refused_slug('uEm10 <- sonic+sa2_shadow: sonic has an incomplete rig: no feet', slugs) == 'sonic'
    assert S._refused_slug('uEm10 <- sonic+sa2_shadow: the models of one set must share one atlas', slugs) is None


def test_build_series_writes_builds_sets_refused_donors_aside_and_keeps_the_manifest_true(tmp_path, monkeypatch):
    donors = many_donors(30)
    report = {'library_entries': 30, 'entries': {
        d.slug: {'usable': True, 'donor': d.__dict__ | {'roles': dict(d.roles)},
                 'rig': {'winding': 'cw' if d.slug == 'd005' else 'ccw'}} for d in donors}}
    survey = tmp_path / 'survey.json'
    survey.write_text(json.dumps(report), encoding='utf-8')
    enemy_rows = [{'slug': d.slug, 'usable': d.slug != 'd007', 'reason': 'd007 does not fit the Majini skeleton well'}
                  for d in donors]
    enemy_survey = tmp_path / 'enemy.json'
    enemy_survey.write_text(json.dumps(enemy_rows), encoding='utf-8')
    archives_dir = tmp_path / 'originals'
    archives_dir.mkdir()
    for enemy in ('uEm10', 'uEm11'):
        (archives_dir / f'{enemy}.arc').write_bytes(b'ARC' + enemy.encode())
    monkeypatch.setattr(S, 'enemy_slots', lambda tables=None: {'uEm10': 3, 'uEm11': 2})
    windings_seen, refused_once, cast_calls = {}, [], []

    def fake_cast(romfs, library, assignment, out, *, plan=None):
        cast_calls.append(json.dumps(assignment, sort_keys=True))
        if 'd002' in assignment.values() and not refused_once:                 # one player refusal, once
            refused_once.append('d002')
            key = next(k for k, v in assignment.items() if v == 'd002')
            raise P.CastWriterError(f'{key} <- d002: d002 is not a usable donor (rig_refused): sides swapped')
        slots = {}
        for key, slug in assignment.items():
            path = out / 'romfs' / P.SLOTS[key].archive
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f'player {slug}'.encode())
            slots[key] = {'donor': slug, 'output': {'path': 'romfs/' + P.SLOTS[key].archive, 'bytes': path.stat().st_size,
                                                    'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
        receipt = {'slots': slots, 'assignment': assignment}
        (out / 'receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        (out / 'contact-sheet.png').write_bytes(b'png')
        return receipt

    def fake_build_cast(name, assignments, archives, out, *, previews=True, secondary='neutral'):
        rows = {}
        assert len(assignments) == 1 and set(archives) == {assignments[0].enemy}      # one class at a time
        for a in assignments:
            assert a.mix and len(a.donors) == {'uEm10': 3, 'uEm11': 2}[a.enemy] and a.table is None
            for d in a.donors:
                windings_seen[d.slug] = d.winding
            if any(d.slug == 'd009' for d in a.donors) and 'd009' not in [r for r in refused_once]:
                refused_once.append('d009')
                raise C.CastError(f'{a.enemy} <- {"+".join(d.slug for d in a.donors)}: d009 cannot be fitted on '
                                  f'em1000: retarget collapsed a source triangle')
            path = out / 'romfs' / W.ARCHIVES[a.enemy].path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('enemy ' + '+'.join(d.slug for d in a.donors)).encode())
            rows[a.enemy] = {'archive': 'romfs/' + W.ARCHIVES[a.enemy].path, 'donors': [{'slug': d.slug} for d in a.donors],
                             'mix': 'test', 'output_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                             'output_bytes': path.stat().st_size}
        (out / 'receipt.json').write_text('{}', encoding='utf-8')
        (out / 'preview.png').write_bytes(b'png')
        (out / 'preview-posed.png').write_bytes(b'png')
        return {'archives': rows}
    monkeypatch.setattr(S.players, 'cast', fake_cast)
    monkeypatch.setattr(S.enemies, 'build_cast', fake_build_cast)
    out = tmp_path / 'series'
    messages = []
    manifest = S.build_series('seed', survey_path=survey, enemy_survey_path=enemy_survey, romfs=tmp_path,
                              archives_dir=archives_dir, library=tmp_path, out=out, count=2, progress=messages.append)
    assert manifest['built'] == 2 and manifest['build_count'] >= 3 and manifest['coverage']['donors_dealt'] == 30
    assert manifest['refusals']['d007'] == {'enemy': 'd007 does not fit the Majini skeleton well'}
    assert 'player' in manifest['refusals']['d002'] and 'enemy' in manifest['refusals']['d009']
    assert any('set aside for the player role: d002' in m for m in messages)
    assert any('set aside for the enemy role: d009' in m and 'takes its carrier' in m for m in messages)
    # an enemy refusal gives the carrier to a substitute inside the build: the player deal is built once per deal
    assert len(cast_calls) == len(set(cast_calls)) and len(cast_calls) < len(messages)
    swapped = [row for row in manifest['builds'] if row['substitutions']]
    assert len(swapped) == 1 and swapped[0]['substitutions'][0]['refused'] == 'd009'
    taker = swapped[0]['substitutions'][0]['substitute']
    assert taker in {s for v in swapped[0]['enemies'].values() for s in v} and taker not in ('d007', 'd009')
    assert swapped[0]['built'] and swapped[0]['files']
    for row in manifest['builds']:
        enemy_slugs = {s for v in row['enemies'].values() for s in v}
        assert not enemy_slugs & {'d007', 'd009'} and 'd002' not in {v['donor'] for v in row['players'].values()}
        assert row['players']['chris_safari']['archive'] == 'uPl00ChrisCos2'
        assert len({v["donor"] for v in row["players"].values()} | enemy_slugs) == row["donors"]   # no donor twice
    # the written builds agree with the manifest and their receipts, file by file
    for row in manifest['builds'][:2]:
        folder = out / row['folder']
        receipt = json.loads((folder / 'receipt.json').read_text(encoding='utf-8'))
        assert set(receipt['files']) == set(row['files']) and receipt['live_verified'] is False
        for path, info in row['files'].items():
            data = (folder / path).read_bytes()
            assert hashlib.sha256(data).hexdigest() == info['sha256'] and len(data) == info['bytes']
        assert (folder / 'receipt-players.json').is_file() and (folder / 'receipt-uEm10.json').is_file()
        assert (folder / 'preview-uEm11.png').is_file() and not (folder / 'preview.png').exists()
        assert receipt['receipts']['enemies'] == {'uEm10': 'receipt-uEm10.json', 'uEm11': 'receipt-uEm11.json'}
        assert receipt['label_table']['archives']['Chris (Safari)'] == 'uPl00ChrisCos2'
        assert receipt['what_must_be_seen'] and receipt['failure_signs']
    assert windings_seen.get('d005', 'ccw') == ('cw' if 'd005' in windings_seen else 'ccw')
    assert manifest['rotation'] is S.ROTATION or manifest['rotation'] == S.ROTATION
    assert (out / 'manifest.json').is_file() and manifest['live_verified'] is False


CLASS_DIR = os.environ.get('GBOX_RE5_CLASS_ARCHIVES')


@pytest.mark.skipif(not CLASS_DIR, reason='set GBOX_RE5_CLASS_ARCHIVES to a folder holding the original class archives')
def test_the_reviewed_tables_hold_on_the_measured_class_archives():
    """Opt-in: every reviewed set's groups and role map, and every mix table's exact cover, on the real archives."""
    for enemy, archive in W.ARCHIVES.items():
        path = Path(CLASS_DIR) / Path(archive.path).name
        if not path.is_file():
            continue
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == archive.sha256, enemy
        parsed = mt_arc.parse(data)
        for name in archive.sets:
            target = W.SETS[name]
            for model_name, mod_index, mrl_index in target.models:
                model = mt_model.parse_mod(W._entry(parsed, mod_index, model_name, b'MOD\0'))
                mrl = W._entry(parsed, mrl_index, model_name, b'MRL\0')
                assert len(W.account_groups(model, target)) == len(target.group_ids())
                roles, _ = W.role_map(model)
                assert len(roles) == 15
                for table in W.MIX_TABLES.values():
                    if table.target == name:
                        mtg = W.parse_montage(W._entry(parsed, *table.montage, b'MTG\0'))
                        counted = W.account_mix(model, mtg, table)
                        assert sum(len(v) for v in counted['shares'].values()) == counted['drawn_montages']
                        for carrier in table.carriers:
                            W._material(mrl, model, carrier, unique=False)
