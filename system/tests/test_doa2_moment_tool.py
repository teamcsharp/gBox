"""Exercise the actual typed tool route with synthetic immutable native bytes."""
import hashlib
import json
import struct
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from test_doa2_context import native, rastate, rzip
from gbox import characters as C, doa2_context as D, doa2_lab as L, doa2_swap as S, gdrom


GAME = '1de2e7634f3161ff'
RID = '6d70500464914684'


@pytest.fixture
def route(native, monkeypatch, tmp_path):
    ram, exe, chr_data, base, decoded = native
    raw = rzip(rastate(struct.pack('<I', 854) + ram))
    digest = hashlib.sha256(raw).hexdigest()
    bodies = {'1ST_READ.BIN': exe, 'DOA2/KTE01.CHR': chr_data}
    disc = SimpleNamespace(files=bodies, read=bodies.__getitem__)
    monkeypatch.setattr(gdrom, 'GDRom', lambda _: disc)
    monkeypatch.setattr(C, '_dc_gdi', lambda *a: 'owned-test.gdi')
    monkeypatch.setattr(S, 'EXECUTABLE_SHA256', hashlib.sha256(exe).hexdigest())
    calls, artifacts = [], {}
    refs = {digest: {'sha256': digest, 'size': len(raw), 'name': 'owned.state44',
                     'media_type': 'application/octet-stream',
                     'provenance': {'game': GAME, 'session': 'original-native-session', 'slot': 44}}}
    payloads = {digest: raw}
    report = {'id': RID, 'context': {'game_id': GAME, 'state_artifact': digest}, 'messages': []}
    catalog = {'game_id': GAME}

    def api(ctx, method, url, **kwargs):
        assert method == 'GET', 'Diagnostic must never control, post or save a state'
        calls.append(url)
        if url == '/api/catalog/' + GAME:
            return catalog
        if url == '/api/requests/' + RID:
            return report
        if url.startswith('/api/artifacts/'):
            requested = url.split('/')[3]
            return refs[requested] if url.endswith('/meta') else payloads[requested]
        raise AssertionError('Unexpected diagnostic route ' + url)

    monkeypatch.setattr(C, '_api', api)
    monkeypatch.setattr(L, 'selected_costumes', lambda *a: pytest.fail('Moment route must not select default fighter'))
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path), progress=lambda *a: None,
                          artifact=lambda name, data, *a, **kw: artifacts.update({name: data}))
    return SimpleNamespace(ctx=ctx, ram=ram, exe=exe, chr=chr_data, base=base, decoded=decoded,
                           raw=raw, digest=digest, report=report, refs=refs, payloads=payloads,
                           catalog=catalog, bodies=bodies, calls=calls, artifacts=artifacts, tmp=tmp_path)


def run(r, **kwargs):
    return L.doa2_assets(L.Doa2In(op='moment_context', actor_index=0, state_artifact=r.digest, **kwargs), r.ctx)['result']


def test_actual_tool_maps_native_actor_and_preserves_input_and_provenance(route):
    r = route
    before = {k: hashlib.sha256(v).hexdigest() for k, v in r.payloads.items()}
    result = run(r)
    assert result['diagnostic_only'] is True
    assert result['actor']['resource_filenames']['geometry'] == 'kte01.chr'
    assert (result['actor']['render_slot'], result['actor']['render_costume']) == (3, 0)
    assert result['actor']['source_structure_uv_verified'] is True
    assert result['state_artifact'] == r.refs[r.digest]
    assert result['source']['origin'] == 'owned_disc'
    assert result['actor']['source_chr_sha256'] == hashlib.sha256(r.chr).hexdigest()
    for name in ('state_loaded', 'operator_actor_verified', 'donor_identity_verified', 'native_reimport_verified', 'gameplay_verified'):
        assert result[name] is False
    assert result['actor']['full_cache_bytes_verified'] is False
    assert json.loads(r.artifacts['doa2-report.json']) == result
    assert json.loads(r.artifacts['doa2-details.json']) == result
    assert L._validate(L.Doa2Out(result=result), r.artifacts) == []
    assert before == {k: hashlib.sha256(v).hexdigest() for k, v in r.payloads.items()}
    assert list(r.tmp.iterdir()) == []


def test_default_report_retains_long_state_and_source_provenance_verbatim(route):
    r = route
    r.refs[r.digest]['provenance']['files'] = [{'name': f'state-evidence-{i}'} for i in range(24)]
    source_sha = hashlib.sha256(r.chr).hexdigest()
    r.payloads[source_sha] = r.chr
    source_meta = {'sha256': source_sha, 'size': len(r.chr), 'name': 'KTE01.CHR',
                   'provenance': {'game': GAME, 'files': [{'name': f'source-{i}'} for i in range(24)]}}
    r.refs[source_sha] = source_meta
    result = run(r, source_chr_artifact=source_sha, source_chr_name='KTE01.CHR')
    assert result['state_artifact'] == r.refs[r.digest]
    assert result['source']['artifact'] == source_meta
    for name in ('doa2-report.json', 'doa2-details.json'):
        saved = json.loads(r.artifacts[name])
        assert saved == result
        assert saved['state_artifact']['provenance']['files'] == r.refs[r.digest]['provenance']['files']
        assert saved['source']['artifact']['provenance']['files'] == source_meta['provenance']['files']


@pytest.mark.parametrize('catalog', [{'game_id': 'another-game'}, {}, None])
def test_catalog_identity_refusal_precedes_owned_disc_discovery(route, monkeypatch, catalog):
    r = route
    api = C._api
    monkeypatch.setattr(C, '_api', lambda ctx, method, path, **kw:
                        catalog if path == '/api/catalog/' + GAME else api(ctx, method, path, **kw))
    monkeypatch.setattr(C, '_dc_gdi', lambda *a: pytest.fail('Wrong catalog must not reach disc discovery'))
    with pytest.raises(ValueError, match='Catalog response'):
        run(r)
    assert not r.artifacts


def test_exact_reported_moment_can_resolve_state_digest_without_session_or_state_write(route):
    r = route
    result = L.doa2_assets(L.Doa2In(op='moment_context', actor_index=0, request_id=RID), r.ctx)['result']
    assert result['request_id'] == RID
    assert result['request_snapshot_sha256'] == hashlib.sha256(json.dumps(r.report, sort_keys=True,
        separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    assert result['state']['state_sha256'] == r.digest
    assert not any('/sessions/' in path or '/jobs/' in path for path in r.calls)


def test_explicit_checkpoint_must_be_linked_to_report_when_context_has_no_saved_digest(route):
    r = route
    r.report['context'].pop('state_artifact')
    r.report['messages'] = [{'attachments': [{'sha256': r.digest, 'name': 'captured.state44'}]}]
    result = run(r, request_id=RID)
    assert result['state']['state_sha256'] == r.digest
    assert result['request_id'] == RID


def test_legacy_missing_game_tag_uses_executable_evidence_without_inventing_provenance(route):
    r = route
    del r.refs[r.digest]['provenance']['game']
    result = run(r)
    assert 'game' not in result['state_artifact']['provenance']
    assert result['state']['executable_sha256'] == hashlib.sha256(r.exe).hexdigest()
    assert result['diagnostic_only'] is True


@pytest.mark.parametrize('kind', ['other_game', 'other_request', 'other_state', 'missing_moment', 'unlinked_state'])
def test_request_state_ownership_refusals_before_consuming_checkpoint(route, kind):
    r = route
    inp = {'request_id': RID}
    if kind == 'other_game': r.report['context']['game_id'] = 'other-game'
    if kind == 'other_request': r.report['id'] = 'another-request'
    if kind == 'other_state': r.report['context']['state_artifact'] = 'f' * 64
    if kind == 'missing_moment': inp['state_artifact'] = ''; r.report['context'].pop('state_artifact')
    if kind == 'unlinked_state': r.report['context'].pop('state_artifact')
    with pytest.raises(ValueError): run(r, **inp) if 'state_artifact' not in inp else L.doa2_assets(
        L.Doa2In(op='moment_context', actor_index=0, **inp), r.ctx)
    assert not any(path.startswith('/api/artifacts/') for path in r.calls)
    assert not r.artifacts


@pytest.mark.parametrize('kind', ['wrong_digest', 'changed_size', 'different_game', 'missing_provenance', 'bad_bytes'])
def test_actual_artifact_metadata_and_bytes_must_match(route, kind):
    r = route
    if kind == 'wrong_digest': r.refs[r.digest]['sha256'] = 'f' * 64
    if kind == 'changed_size': r.refs[r.digest]['size'] += 1
    if kind == 'different_game': r.refs[r.digest]['provenance']['game'] = 'other'
    if kind == 'missing_provenance': r.refs[r.digest]['provenance'] = None
    if kind == 'bad_bytes': r.payloads[r.digest] = bytes(len(r.raw))
    with pytest.raises(ValueError): run(r)
    assert not r.artifacts


def test_explicit_modified_chr_compares_exact_supplied_bytes_and_does_not_assert_donor_residency(route):
    r = route
    changed = bytearray(r.chr)
    record = r.decoded['models'][0]['meshes'][0]['records'][0]
    struct.pack_into('<f', changed, record['offset'] + 24, .375)
    r.ram[r.base + record['offset'] + 24:r.base + record['offset'] + 28] = changed[record['offset'] + 24:record['offset'] + 28]
    raw = rzip(rastate(struct.pack('<I', 854) + r.ram))
    digest = hashlib.sha256(raw).hexdigest()
    r.refs[digest] = {**r.refs[r.digest], 'sha256': digest, 'size': len(raw)}
    r.payloads[digest] = raw; r.digest = digest
    with pytest.raises(ValueError, match='UV bytes differ'):
        run(r)
    source_sha = hashlib.sha256(changed).hexdigest()
    r.payloads[source_sha] = bytes(changed)
    r.refs[source_sha] = {'sha256': source_sha, 'name': 'modified-KTE01.CHR', 'size': len(changed),
                         'media_type': 'application/octet-stream', 'provenance': {'game': GAME, 'source': 'synthetic-donor'}}
    result = run(r, source_chr_artifact=source_sha, source_chr_name='KTE01.CHR')
    assert result['source']['artifact'] == r.refs[source_sha]
    assert result['actor']['source_chr_sha256'] == source_sha
    assert result['actor']['source_structure_uv_verified'] is True
    assert result['donor_identity_verified'] is False
    with pytest.raises(ValueError, match='filename disagrees'):
        run(r, source_chr_artifact=source_sha, source_chr_name='KTE00.CHR')


@pytest.mark.parametrize('change', ['pointer', 'fingerprint', 'draw_gate'])
def test_public_tool_refuses_invalid_native_cache_state(route, change):
    r = route
    if change == 'pointer': struct.pack_into('<I', r.ram, D.RESOURCE_TABLE, D.RAM_BASE + r.base + 1)
    if change == 'fingerprint': r.ram[0x10000 + D.FINGERPRINTS[-1]] ^= 1
    if change == 'draw_gate': r.ram[D.ACTOR_BASE + 0x53] = 0
    raw = rzip(rastate(struct.pack('<I', 854) + r.ram)); digest = hashlib.sha256(raw).hexdigest()
    r.refs[digest] = {**r.refs[r.digest], 'sha256': digest, 'size': len(raw)}
    r.payloads[digest] = raw; r.digest = digest
    with pytest.raises(ValueError): run(r)
    assert not r.artifacts


@pytest.mark.parametrize('fields', [dict(), {'actor_index': 0}, {'state_artifact': 'a'*64},
    {'actor_index': True, 'state_artifact': 'a'*64}, {'actor_index': 2, 'state_artifact': 'a'*64},
    {'actor_index': 0, 'state_artifact': '../outside'},
    {'actor_index': 0, 'state_artifact': 'a'*64, 'source_chr_name': 'KTE01.CHR'},
    {'actor_index': 0, 'state_artifact': 'a'*64, 'source_chr_artifact': 'b'*64}])
def test_typed_tool_requires_explicit_valid_actor_and_digest_or_report(fields):
    with pytest.raises(ValidationError): L.Doa2In(op='moment_context', **fields)


def test_old_tool_schema_defaults_remain_usable():
    assert L.Doa2In().op == 'inspect'
    assert L.Doa2In(op='motions').actor_index is None
    assert L.Doa2In(op='build', fighter='Ein', character='donor').costume == '00'


def test_registered_worker_tool_advertises_callable_diagnostic_and_exact_inputs():
    from gbox.registry import REGISTRY
    info = REGISTRY['doa2_assets'].info()
    assert info.version == '1.4'
    assert REGISTRY['doa2_assets'].fn is L.doa2_assets
    fields = info.input_schema['properties']
    assert {'moment_context', 'motion_clips'} <= set(fields['op']['enum'])
    assert {'state_artifact', 'request_id', 'actor_index', 'source_chr_artifact', 'source_chr_name'} <= fields.keys()
    assert 'no state is saved, loaded or rewritten' in info.description
