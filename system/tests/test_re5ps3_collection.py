import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from gbox import characters as C, char_coverage as CC, character_collection as AC
from gbox import re5ps3_collection as R, replacement_readiness as RR, rom_archives as RA
from gbox.config import Config
from gbox.re5ps3_arc import sha
from test_re5ps3_models import glb

GAME = {'game_id': R.GAME_ID, 'title': 'Resident Evil 5 - Gold Edition (USA) (En,Ja,Fr,De,Es,It) (v02.00)',
        'platform': 'ps3'}


def context(tmp_path, monkeypatch, source):
    root = tmp_path / 'characters'; root.mkdir(parents=True)
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    monkeypatch.setenv('GBOX_CHARACTERS', str(root))
    monkeypatch.setattr(C, '_rom', lambda *a: Path(source))
    monkeypatch.setattr(C, '_game', lambda *a: GAME)
    return SimpleNamespace(config=cfg, progress=lambda *a: None), root


@pytest.fixture
def owned():
    base = Path(os.environ.get('GBOX_RE5_EVIDENCE', str(Path.home() / 'gbox-pr-audit-20261017/re-export-evidence')))
    paths = list(base.glob('re5/**/PS3_GAME/PARAM.SFO'))
    if not paths:
        pytest.skip('owned RE5 PS3 source evidence unavailable')
    assert len(paths) == 1
    return paths[0].parent.parent


def copy_owned(source, dest):
    for member in R.FILES:
        out = dest / member
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / member, out)
    return dest


def test_registered_roster_exact_identity_and_no_writer(tmp_path, monkeypatch):
    rows = R.roster()
    assert len(rows) == len({r['slug'] for r in rows}) == 2
    assert {r['key'] for r in rows} == {R.CHRIS, R.SHEVA}
    assert CC.extractor_for(GAME)[0] == 're5ps3' and AC.registered(GAME)
    assert C.reader_version('re5ps3') == R.READER_VERSION
    assert not CC.writer_for(GAME)
    ctx, root = context(tmp_path, monkeypatch, tmp_path)
    monkeypatch.setattr(C, '_rom', lambda *a: pytest.fail('guard must reject before source access'))
    for bad in (GAME | {'game_id': '0' * 16}, GAME | {'platform': 'xbox360'}):
        assert CC.extractor_for(bad)[0] != 're5ps3'
        assert not AC.registered(bad)
        assert C.extract_dedicated(ctx, bad, 'Chris', root) is None
        monkeypatch.setattr(C, '_game', lambda *a: bad)
        assert C.collect(ctx, None)['status'] == 'unsupported'
        with pytest.raises(ValueError, match='exact PS3'):
            R.extract_run(ctx, bad, rows[0], tmp_path)
    with pytest.raises(ValueError, match='unknown RE5'):
        R.extract_run(ctx, GAME, rows[0] | {'key': '../other'}, tmp_path)


def test_numeric_joint_policy_skips_guessing_but_keeps_explicit_mapping(tmp_path, monkeypatch):
    from test_replacement_readiness import glb as figure, entry
    model = figure(tmp_path / 'figure.glb')
    meta = entry(tmp_path, 'numeric', model, role_mapping_policy='explicit_only')
    monkeypatch.setattr(RR, 'auto_roles', lambda *a: pytest.fail('must not guess native semantics'))
    monkeypatch.setattr(RR, 'reader_roles', lambda *a: pytest.fail('must not backfill unproved native semantics'))
    new, fixed = RR.compute(tmp_path, meta)
    assert not new['rig'].get('roles') and not new['readiness']['ready']
    assert any('explicit verification' in s for s in new['readiness']['missing'])
    meta['rig']['roles'] = {'hip': 'j_hip'}
    new, fixed = RR.compute(tmp_path, meta)
    assert new['rig']['roles'] == {'hip': 'j_hip'}
    assert not new['rig'].get('roles_guessed')


def test_explicit_role_policy_invalidates_cached_readiness(tmp_path):
    from test_replacement_readiness import glb as figure, entry
    meta = entry(tmp_path, 'roles', figure(tmp_path / 'figure.glb'))
    computed, _ = RR.compute(tmp_path, meta, fix=False)
    assert not RR.stale(tmp_path, computed)
    computed['role_mapping_policy'] = 'explicit_only'
    assert RR.stale(tmp_path, computed)


@pytest.mark.parametrize('member', [R.SFO, R.EBOOT, R.CHRIS])
def test_wrong_owned_bytes_create_no_model(tmp_path, monkeypatch, owned, member):
    source = copy_owned(owned, tmp_path / 'source')
    p = source / member
    with p.open('r+b') as f:
        b = f.read(1); f.seek(0); f.write(bytes([b[0] ^ 1]))
    ctx, _root = context(tmp_path, monkeypatch, source)
    work = tmp_path / 'work'; work.mkdir()
    with pytest.raises(ValueError, match='SHA256 differs'):
        R.extract_run(ctx, GAME, R.roster()[0], work)
    assert not list(work.iterdir())


def test_folder_member_cannot_escape_source(tmp_path):
    root = tmp_path / 'PS3_GAME'; root.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    try:
        (root / 'USRDIR').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError, match='escapes'):
        R._folder(root, R.EBOOT)


def test_owned_normal_collection_has_real_models_provenance_and_partial_scope(tmp_path, monkeypatch, owned):
    before = {m: sha((owned / m).read_bytes()) for m in R.FILES}
    ctx, root = context(tmp_path, monkeypatch, owned / 'PS3_GAME' / 'USRDIR' / 'EBOOT.BIN')
    result = C.collect(ctx, None)
    assert (result['status'], result['collected'], result['total'], result['retargetable']) == ('partial', 2, 2, 2), result
    assert result['scope'] == R.collection_scope() and result['scope']['full_cast'] is False
    assert result['roster_complete'] is True
    assert not result['slots']
    for row, bones, triangles in zip(R.roster(), (130, 147), (18633, 18070)):
        meta = C.get(root, row['slug'])
        assert C.verify_entry(root, meta)['ok']
        assert meta['source']['game_id'] == GAME['game_id'] and meta['source']['platform'] == 'ps3'
        assert meta['re5ps3_reader'] == R.READER_VERSION
        assert C.reader_status(meta)['stale'] is False
        assert meta['role_mapping_policy'] == 'explicit_only' and len(meta['rig']['roles']) == 18
        assert not meta['rig'].get('roles_guessed')
        assert meta['native_coverage'] == result['scope']
        ev = meta['native_evidence']
        assert ev['source_files_sha256'] == {m: before[m] for m in (R.SFO, R.EBOOT, row['key'])}
        assert ev['archive_member'] == row['key'] and ev['title_id'] == R.TITLE_ID
        assert ev['bones'] == bones and ev['triangles'] == triangles
        assert ev['gameplay_verified'] is False
        assert ev['role_evidence']['roles'] == meta['rig']['roles']
        assert ev['role_evidence']['animation_compatibility_verified'] is False
        doc, _binary, _acc = glb(root / row['slug'] / meta['model'])
        assert len(doc['skins'][0]['joints']) == bones and doc['images']
        assert all(doc['nodes'][j]['name'].startswith('j') for j in doc['skins'][0]['joints'])
    # Normal refresh must preserve coverage, and repeat collection reuses verified entries.
    refreshed = C.refresh_collection(root, result)
    assert refreshed['scope'] == result['scope'] and refreshed['retargetable'] == 2
    assert refreshed['status'] == 'partial' and refreshed['roster_complete'] is True
    monkeypatch.setattr(C, '_rom', lambda *a: pytest.fail('verified entries should be reused'))
    assert {r['status'] for r in C.collect(ctx, None)['entries']} == {'in_collection'}
    assert {m: sha((owned / m).read_bytes()) for m in R.FILES} == before


def test_verified_legacy_entry_cannot_bypass_exact_source_reader(tmp_path, monkeypatch, owned):
    ctx, root = context(tmp_path, monkeypatch, owned)
    row = R.roster()[0]
    first = C.extract_dedicated(ctx, GAME, 'Chris', root)['entry']
    assert not R.needs_refresh(first)
    for key, value in [('re5ps3_reader', None), ('native_evidence', {}), ('role_mapping_policy', None),
                       ('native_coverage', {}), ('rig', first['rig'] | {'roles_guessed': True}),
                       ('slug', R.roster()[1]['slug']), ('native_evidence', ['malformed'])]:
        assert R.needs_refresh(first | {key: value})
    assert not R.needs_refresh(first | {'slug': first['slug'] + '_' + R.GAME_ID})
    for broken in ({}, {'version': 1, 'source_model_sha256': R.SHEVA_MODEL},
                   first['native_evidence']['role_evidence'] | {'native_joint_ids': {'head': 23}}):
        assert R.needs_refresh(first | {'native_evidence': first['native_evidence'] | {'role_evidence': broken}})
    legacy = first.copy()
    for key in ('re5ps3_reader', 'native_evidence', 'role_mapping_policy'):
        legacy.pop(key)
    (root / row['slug'] / 'meta.json').write_text(json.dumps(legacy))
    assert C.verify_entry(root, legacy)['ok'] and C.reader_status(legacy)['stale']
    accesses = []
    monkeypatch.setattr(C, '_rom', lambda *a: accesses.append(True) or owned)
    result = C.extract_dedicated(ctx, GAME, 'Chris', root)
    assert result['status'] == 'extracted' and len(accesses) == 1
    assert not R.needs_refresh(result['entry']) and len(result['entry']['rig']['roles']) == 18


def test_missing_target_is_reported_without_hiding_successful_target(tmp_path, monkeypatch, owned):
    source = copy_owned(owned, tmp_path / 'source')
    (source / R.SHEVA).unlink()
    ctx, root = context(tmp_path, monkeypatch, source)
    result = C.collect(ctx, None)
    assert result['status'] == 'partial' and result['collected'] == 1 and result['total'] == 2, result
    assert result['entries'][0]['verified'] is True
    assert result['entries'][1]['status'] == 'failed' and R.SHEVA in result['entries'][1]['error']
    assert not (root / R.roster()[1]['slug'] / 'meta.json').exists()


def test_archive_selects_only_four_members_caches_and_rechecks_hashes(tmp_path, monkeypatch, owned):
    exe = RA.seven_zip()
    source = copy_owned(owned, tmp_path / 'input' / 'Owned')
    (source / 'unrelated.bin').write_bytes(b'not a target')
    archive = tmp_path / 'owned.7z'
    subprocess.run([exe, 'a', '-mx=0', str(archive), 'Owned'], cwd=source.parent,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=60)
    ctx, _root = context(tmp_path, monkeypatch, archive)
    work = tmp_path / 'out'; work.mkdir()
    first = R.extract_run(ctx, GAME, R.roster()[0], work)
    cache_root = Path(ctx.config.cache) / 're5ps3-native'
    caches = list(cache_root.iterdir()); assert len(caches) == 1
    cache = caches[0]
    assert {p.name for p in cache.iterdir()} == {Path(m).name for m in R.FILES} | {'source.json'}
    assert first['extra']['native_evidence']['source']['kind'] == '7z exact members'
    monkeypatch.setattr(RA, 'members', lambda *a: pytest.fail('cache must avoid extracting the solid archive again'))
    second = R.extract_run(ctx, GAME, R.roster()[1], work)
    assert second['extra']['native_evidence']['archive_sha256'] == R.FILES[R.SHEVA][1]
    p = cache / Path(R.CHRIS).name
    with p.open('r+b') as f:
        f.write(b'bad!')
    with pytest.raises(ValueError, match='SHA256 differs'):
        R.extract_run(ctx, GAME, R.roster()[0], tmp_path)
    assert not (tmp_path / 're5ps3_chris_normal.glb').exists()


@pytest.mark.parametrize('case', ['duplicate', 'identity_missing', 'wrong_size', 'ambiguous_root', 'listfile'])
def test_bad_archive_identity_is_rejected_before_extraction(tmp_path, monkeypatch, case):
    src = tmp_path / 'source.7z'; src.write_bytes(b'header')
    rows = [{'name': 'Owned/' + m, 'size': size} for m, (size, _h) in R.FILES.items()]
    if case == 'duplicate': rows.append(rows[0].copy())
    elif case == 'identity_missing': rows.pop(1)
    elif case == 'wrong_size': rows[0]['size'] += 1
    elif case == 'ambiguous_root': rows.append({'name': 'Other/' + R.SFO, 'size': R.FILES[R.SFO][0]})
    elif case == 'listfile':
        for row in rows:
            row['name'] = '@' + row['name']
    monkeypatch.setattr(RA, 'members', lambda *a: rows)
    monkeypatch.setattr(RA, 'seven_zip', lambda: pytest.fail('invalid identity must not extract'))
    with pytest.raises(ValueError):
        R._archive_cache(src, tmp_path / 'cache', lambda *a: None)
    assert not (tmp_path / 'cache').exists()


@pytest.mark.parametrize('mode', ['failed', 'timeout', 'short'])
def test_failed_extraction_cannot_publish_cache(tmp_path, monkeypatch, mode):
    src = tmp_path / 'source.7z'; src.write_bytes(b'header')
    rows = [{'name': 'Owned/' + m, 'size': size} for m, (size, _h) in R.FILES.items()]
    monkeypatch.setattr(RA, 'members', lambda *a: rows)
    monkeypatch.setattr(RA, 'seven_zip', lambda: '7z')
    def incomplete(args, **kwargs):
        assert '-ssc' in args and '-spd' in args  # Exact case/literal matching on Windows too.
        target = Path(next(a[2:] for a in args if a.startswith('-o')))
        (target / 'PARAM.SFO').write_bytes(b'incomplete')
        if mode == 'timeout':
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        return SimpleNamespace(returncode=2 if mode == 'failed' else 0)
    monkeypatch.setattr(R.subprocess, 'run', incomplete)
    with pytest.raises(ValueError):
        R._archive_cache(src, tmp_path / 'cache', lambda *a: None)
    assert list((tmp_path / 'cache' / 're5ps3-native').iterdir()) == []


def test_engineering_handoff_names_normal_collection():
    from gbox.native_engineering import TITLE_WORK
    title = TITLE_WORK[R.GAME_ID]
    assert title['collection_command'] == 'characters op=collect game_id=' + R.GAME_ID
    assert 'two-target partial coverage' in title['validated_scope']
    assert 'standalone CLI' not in ' '.join(title['separate_work'])
