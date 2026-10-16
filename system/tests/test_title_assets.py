from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import pytest
import zipfile

from gbox import title_assets as T
from gbox.config import Config, Library
from gbox.registry import Ctx
from gbox.store import Store

GID = 'b8edf7040116f3aa'
OTHER = '1111111111111111'
RID = '2222222222222222'
from gbox.doa3_native import XBE_SHA256
SOURCE = {'archive_sha256': 'a' * 64, 'xbe_sha256': XBE_SHA256}
CAPS = {'raw': True, 'decoded': False, 'writable': False, 'reimportable': False,
        'full_character_replacement': False}


def game(gid=GID, **fields):
    return {'game_id': gid, 'title': 'Dead or Alive 3 (USA)', 'platform': 'xbox',
            'library': 'owned', 'rel_path': 'doa3.7z', 'source_paths': ['doa3.7z'],
            'format': '7z', 'profile_id': gid, **fields}


@pytest.fixture
def manager(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / 'data', libraries=[Library(id='owned', paths={'windows': str(tmp_path), 'linux': str(tmp_path)})])
    store = Store(cfg.data_dir)
    store.upsert_catalog([game(), game(OTHER)])
    store.put('request', RID, {'id': RID, 'context': {'game_id': GID}})
    workers = [{'id': 'office', 'name': 'Office', 'online': True, 'os': 'windows', 'tools': ['title_assets', 'characters']},
               {'id': 'spark', 'name': 'Spark', 'online': True, 'os': 'linux', 'tools': ['title_assets', 'characters']}]
    sent = []
    def submit(body, actor):
        job = body | {'id': f'job-{len(sent)}', 'state': 'queued'}
        sent.append(job)
        store.put('job', job['id'], job)
        return job
    from gbox import char_coverage as C
    monkeypatch.setattr(C, 'extractor_for', lambda g: (None, []))
    monkeypatch.setattr(C, 'writer_for', lambda g: None)
    monkeypatch.setattr(T, 'native_reader', lambda g: g['game_id'] == GID)
    m = T.TitleAssets(store, cfg, lambda: workers, submit)
    m.sent, m.worker_rows = sent, workers
    return m


def finish(m, index, result):
    job = m.store.get('job', f'job-{index}')
    if job['tool'] == 'title_assets':
        result = {'game_id': job['input']['game_id'], 'catalog_key': job['input']['expected_catalog_key'],
                  'worker_id': job['require_worker'], **result}
    m.store.put('job', job['id'], job | {'state': 'succeeded', 'output': {'result': result}})


def test_requests_share_one_durable_inventory_even_concurrent(manager):
    inp = T.CollectIn(parent_request_id=RID)
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: manager.collect(GID, inp, 'operator'), range(8)))
    assert len(manager.sent) == 1
    j = manager.sent[0]
    assert j['tool'] == 'title_assets' and j['input']['op'] == 'inventory'
    assert j['require_worker'] == 'office' and j['require_os'] == 'windows'
    assert j['agent_use'] and j['low_priority'] and j['parent_request_id'] == RID
    assert j['input']['expected_catalog_key'] == T.catalog_key(game())
    assert rows[-1]['request_ids'] == [RID]
    assert not manager.store.all('session')
    # Dedupe is durable across a new coordinator instance, not just its lock.
    replacement = T.TitleAssets(manager.store, manager.config, manager.workers, manager.submit)
    replacement.collect(GID, inp, 'operator')
    assert len(manager.sent) == 1


def test_inventory_then_bounded_exports_stays_pending_decoding(manager):
    manager.collect(GID, T.CollectIn(), 'operator')
    members = [{'index': i, 'size': 2 * 1024**2} for i in range(70)]
    inventory = {'source': SOURCE, 'members': members, 'worker_id': 'office'}
    finish(manager, 0, inventory)
    manager.collect(GID, T.CollectIn(), 'operator')
    chosen = manager.sent[1]['input']['entry_ids']
    assert chosen == list(range(12))  # at most24 MiB, independent of total AFS size
    assert manager.sent[1]['input']['expected_source'] == SOURCE
    manager.collect(GID, T.CollectIn(), 'operator')
    assert len(manager.sent) == 2  # pending chunk never duplicates
    finish(manager, 1, {'source': SOURCE, 'members': members[:12], 'bundle_sha256': 'f' * 64})
    status = manager.collect(GID, T.CollectIn(), 'operator')
    assert manager.sent[2]['input']['entry_ids'] == list(range(12, 24))
    # Finish the remaining chunks through exactly the same explicit admission path.
    while manager.sent[-1]['state'] == 'queued':
        idx = len(manager.sent) - 1
        chosen = manager.sent[idx]['input']['entry_ids']
        finish(manager, idx, {'source': SOURCE, 'members': [members[i] for i in chosen], 'bundle_sha256': 'f' * 64})
        previous = len(manager.sent)
        status = manager.collect(GID, T.CollectIn(), 'operator')
        if len(manager.sent) == previous:
            break
    status = manager.collect(GID, T.CollectIn(), 'operator')
    assert len(manager.sent) == 7
    assert len(status['exports']) == 6 and not status['playable_build_verified']
    assert status['raw_coverage'] == {'scope': 'non-placeholder loadfile.afs members', 'expected': 70, 'exported': 70, 'complete': True, 'oversized_members': []}
    assert status['exports'][0]['bundle_url'] == '/api/artifacts/' + 'f' * 64
    assert all(c['state'] == 'pending_reader' and not c['full_source_verified'] for c in status['categories'].values())


def test_exact_title_and_catalog_revision_do_not_borrow_results(manager):
    manager.collect(GID, T.CollectIn(), 'operator')
    finish(manager, 0, {'source': SOURCE, 'members': [], 'worker_id': 'office'})
    assert manager.status(OTHER)['inventory'] is None  # same name, different title id
    updated = game(hashes={'sha1': 'c' * 40})
    manager.store.upsert_catalog([updated])
    assert manager.status(GID)['inventory'] is None
    manager.collect(GID, T.CollectIn(), 'operator')
    assert len(manager.sent) == 2 and manager.sent[-1]['input']['op'] == 'inventory'


def test_failed_work_requires_explicit_retry(manager):
    manager.collect(GID, T.CollectIn(), 'operator')
    job = manager.store.get('job', 'job-0')
    manager.store.put('job', job['id'], job | {'state': 'failed', 'error': 'bad archive'})
    manager.collect(GID, T.CollectIn(), 'operator')
    assert len(manager.sent) == 1
    assert manager.status(GID)['tasks'][0]['error'] == 'bad archive'
    manager.collect(GID, T.CollectIn(retry_failed=True), 'operator')
    assert len(manager.sent) == 2


def test_refresh_inventory_recovers_source_mutation_without_borrowing_old_coverage(manager):
    manager.collect(GID, T.CollectIn(), 'operator')
    old_members = [{'index': 1, 'size': 100}, {'index': 2, 'size': 100}]
    finish(manager, 0, {'source': SOURCE, 'members': old_members})
    manager.collect(GID, T.CollectIn(), 'operator')
    finish(manager, 1, {'source': SOURCE, 'members': old_members[:1], 'bundle_sha256': 'f' * 64})
    manager.collect(GID, T.CollectIn(), 'operator')
    failed = manager.store.get('job', 'job-2')
    manager.store.put('job', failed['id'], failed | {'state': 'failed', 'error': 'Native source changed since inventory'})
    manager.collect(GID, T.CollectIn(retry_failed=True), 'operator')
    assert manager.sent[-1]['input']['expected_source'] == SOURCE
    retry = manager.store.get('job', manager.sent[-1]['id'])
    manager.store.put('job', retry['id'], retry | {'state': 'failed', 'error': 'Native source changed since inventory'})
    refreshed = manager.collect(GID, T.CollectIn(refresh_inventory=True), 'operator')
    assert refreshed['inventory_epoch'] == 1 and refreshed['inventory'] is None
    assert refreshed['exports'] == [] and refreshed['raw_coverage']['exported'] == 0
    assert refreshed['historical_tasks_count'] >= 3
    assert manager.sent[-1]['input']['op'] == 'inventory'
    new_source = SOURCE | {'archive_sha256': 'd' * 64}
    finish(manager, len(manager.sent) - 1, {'source': new_source, 'members': [{'index': 5, 'size': 123}]})
    updated = manager.collect(GID, T.CollectIn(), 'operator')
    assert manager.sent[-1]['input']['expected_source'] == new_source
    assert manager.sent[-1]['input']['entry_ids'] == [5]
    assert updated['exports'] == [] and updated['raw_coverage']['exported'] == 0
    assert len(manager.store.get('title_asset_pipeline', GID)['tasks']) >= 5


def test_refresh_inventory_refuses_active_title_jobs_even_across_catalog_revisions(manager):
    manager.collect(GID, T.CollectIn(), 'operator')
    manager.store.upsert_catalog([game(hashes={'sha1': 'c' * 40})])
    with pytest.raises(ValueError, match='queued or running'):
        manager.collect(GID, T.CollectIn(refresh_inventory=True), 'operator')
    assert len(manager.sent) == 1 and manager.store.get('title_asset_pipeline', GID).get('inventory_epoch', 0) == 0


def test_small_native_metadata_is_not_assumed_placeholder():
    inventory = {'members': [{'index': 0, 'size': 4, 'kind': 'unknown'},
                             {'index': 1, 'size': 4, 'kind': 'placeholder'},
                             {'index': 2, 'size': 0, 'placeholder': True}]}
    assert T.TitleAssets._next_chunk(inventory, []) == [0]


def test_wrong_job_output_cannot_become_title_inventory(manager):
    manager.collect(GID, T.CollectIn(), 'operator')
    finish(manager, 0, {'game_id': OTHER, 'source': SOURCE, 'members': []})
    assert manager.status(GID)['inventory'] is None


def test_export_stays_on_inventory_worker_and_unavailable_does_not_substitute(manager):
    manager.collect(GID, T.CollectIn(), 'operator')
    finish(manager, 0, {'source': SOURCE, 'members': [{'index': 1, 'size': 100}], 'worker_id': 'office'})
    manager.worker_rows[0]['online'] = False
    with pytest.raises(ValueError, match='No online worker'):
        manager.collect(GID, T.CollectIn(), 'operator')
    assert len(manager.sent) == 1
    assert manager.status(GID)['blocked_reason']


def test_known_readers_preserve_central_linux_collection(manager, monkeypatch):
    from gbox import char_coverage as C
    monkeypatch.setattr(C, 'extractor_for', lambda g: ('sm64', [{'slug': 'mario'}]))
    status = manager.collect(OTHER, T.CollectIn(categories=['characters']), 'operator')
    assert manager.sent[0]['tool'] == 'characters'
    assert manager.sent[0]['require_os'] == 'linux' and manager.sent[0]['require_worker'] == 'spark'
    assert status['categories']['props']['state'] == 'pending_reader'
    assert status['categories']['characters']['state'] == 'registered_subset'


def test_unknown_reader_and_missing_dependency_never_queue(manager):
    status = manager.collect(OTHER, T.CollectIn(), 'operator')
    assert not manager.sent and not status['playable_build_verified']
    assert all(c['state'] == 'pending_reader' for c in status['categories'].values())
    with pytest.raises(ValueError, match='existing request_id'):
        manager.collect(GID, T.CollectIn(request_ids=['3' * 16]), 'operator')
    assert not manager.sent


def test_native_tool_pins_catalog_and_source_before_export(tmp_path, monkeypatch):
    import sys
    from gbox import characters
    fake = SimpleNamespace(inventory=lambda *a, **k: {'source': SOURCE, 'members': [{'index': 1, 'size': 18}]})
    calls = []
    folder = tmp_path / 'native-bundle'
    (folder / 'members').mkdir(parents=True)
    content = b'native model bytes'
    member = {'path': 'members/000001_KAS00.xpr', 'index': 1, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    (folder / member['path']).write_bytes(content)
    native = {'game_id': GID, 'schema': 'gbox-doa3-native-assets-v1', 'source': SOURCE, 'capabilities': CAPS, 'members': [member]}
    (folder / 'manifest.json').write_text(json.dumps(native))
    fake.export_selected = lambda *a, **k: calls.append(k) or (native | {'bundle_dir': str(folder)})
    monkeypatch.setitem(sys.modules, 'gbox.doa3_assets', fake)
    import gbox
    monkeypatch.setattr(gbox, 'doa3_assets', fake, raising=False)
    monkeypatch.setattr(characters, '_api', lambda *a, **k: game())
    monkeypatch.setattr(T, 'source_directory', lambda *a, **k: (tmp_path, 'validated_native_play_disc'))
    ctx = Ctx(Config(data_dir=tmp_path), 'job', 'office')
    inp = T.TitleAssetsIn(op='export', game_id=GID, entry_ids=[1], expected_source={'archive_sha256': 'd' * 64})
    with pytest.raises(ValueError, match='changed since inventory'):
        T.title_assets(inp, ctx)
    assert not calls and not ctx.artifacts
    with pytest.raises(ValueError, match='Catalog source changed'):
        T.title_assets(T.TitleAssetsIn(game_id=GID, expected_catalog_key='e' * 64), ctx)
    fake.inventory = lambda *a, **k: {'source': SOURCE, 'members': [{'index': 1, 'size': T.CHUNK_BYTES + 1}]}
    with pytest.raises(ValueError, match='bounded artifact budget'):
        T.title_assets(T.TitleAssetsIn(op='export', game_id=GID, entry_ids=[1], expected_source=SOURCE), ctx)
    assert not calls and not ctx.artifacts
    fake.inventory = lambda *a, **k: {'source': SOURCE, 'members': [{'index': 1, 'size': 18}]}
    result = T.title_assets(T.TitleAssetsIn(op='export', game_id=GID, entry_ids=[1], expected_source=SOURCE), ctx)
    assert result['result']['worker_id'] == 'office' and result['result']['job_id'] == 'job'
    assert calls[0]['entry_ids'] == [1]
    arts = {row[0]: row[1] for row in ctx.artifacts}
    assert not T._validate(T.TitleAssetsOut(**result), arts)
    arts[T.BUNDLE] += b'changed'
    assert T._validate(T.TitleAssetsOut(**result), arts) == ['Portable native bundle artifact is missing or changed']


def test_oversized_members_remain_explicit_pending(manager):
    manager.collect(GID, T.CollectIn(), 'operator')
    finish(manager, 0, {'source': SOURCE, 'members': [{'index': 1, 'size': T.CHUNK_BYTES + 1}]})
    status = manager.collect(GID, T.CollectIn(), 'operator')
    assert len(manager.sent) == 1
    assert status['raw_coverage']['oversized_members'] == [1] and not status['raw_coverage']['complete']


def test_validator_refuses_raw_export_claiming_decoded_replacements():
    result = {'game_id': GID, 'worker_id': 'office', 'source': SOURCE, 'capabilities': CAPS | {'decoded': True}}
    data = json.dumps(result).encode()
    out = T.TitleAssetsOut(result=result, manifest_sha256=hashlib.sha256(data).hexdigest())
    assert T._validate(out, {T.ARTIFACT: data}) == ['Raw native exports cannot claim decoded or replacement capabilities']
    assert T._validate(out, {T.ARTIFACT: data + b' '})


@pytest.mark.parametrize('unsafe_path,wrong_bytes', [(False, True), (True, False)])
def test_independent_zip_validation_checks_paths_and_member_hashes(unsafe_path, wrong_bytes):
    native = b'original native data'
    path = '../escaped.xpr' if unsafe_path else 'members/000001_KAS00.xpr'
    member = {'index': 1, 'path': path, 'size': len(native), 'sha256': hashlib.sha256(native).hexdigest()}
    result = {'schema': 'gbox-doa3-native-assets-v1', 'game_id': GID, 'worker_id': 'office', 'source': SOURCE,
              'capabilities': CAPS, 'members': [member], 'op': 'export'}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(result))
        archive.writestr(path, b'altered native bytes' if wrong_bytes else native)
    payload = stream.getvalue()
    result['bundle_sha256'] = hashlib.sha256(payload).hexdigest()
    data = json.dumps(result).encode()
    out = T.TitleAssetsOut(result=result, manifest_sha256=hashlib.sha256(data).hexdigest())
    assert T._validate(out, {T.ARTIFACT: data, T.BUNDLE: payload}) == ['Portable native bundle contents failed independent validation']


def test_owned_play_view_reuses_only_required_verified_files(tmp_path):
    cfg = SimpleNamespace(runtime=tmp_path)
    home = tmp_path / 'xbox' / 'doa3-native-play' / GID
    disc = home / 'disc'
    disc.mkdir(parents=True)
    files = []
    for name in ('default.xbe', 'loadfile.afs'):
        content = ('owned-' + name).encode()
        (disc / name).write_bytes(content)
        files.append({'name': name, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    (disc / '.recomp-storage').mkdir()
    save = disc / '.recomp-storage' / 'save.bin'
    save.write_bytes(b'save untouched')
    (home / 'disc-receipt.json').write_text(json.dumps({'format': 1, 'game_id': GID, 'files': files}))
    found, kind = T.source_directory(game(), cfg)
    assert found == disc and kind == 'validated_native_play_disc' and save.read_bytes() == b'save untouched'
    (disc / 'loadfile.afs').write_bytes(b'changed archive')
    with pytest.raises(ValueError, match='differs from its receipt'):
        T.source_directory(game(), cfg)


@pytest.mark.parametrize('fields', [{'op': 'export'}, {'op': 'inventory', 'entry_ids': [1]},
                                    {'op': 'export', 'entry_ids': [-1]}, {'op': 'export', 'entry_ids': [1, 1]},
                                    {'op': 'export', 'entry_ids': [True]}, {'op': 'export', 'entry_ids': ['1']}])
def test_selection_contract_is_bounded(fields):
    with pytest.raises(ValueError):
        T.TitleAssetsIn(game_id=GID, **fields)


def test_routes_auth_and_exact_status(manager):
    app = FastAPI()
    def auth(authorization: str = Header(default='')):
        if authorization != 'Bearer test':
            raise HTTPException(401)
        return 'operator'
    T.routes(app, manager.store, manager.config, auth, manager.workers, manager.submit)
    client = TestClient(app)
    assert client.get(f'/api/title-assets/{GID}').status_code == 401
    client.headers['Authorization'] = 'Bearer test'
    assert client.get('/api/title-assets/missing').status_code == 404
    assert client.get(f'/api/title-assets/{GID}').json()['game_id'] == GID
    queued = client.post(f'/api/title-assets/{GID}/collect', json={'parent_request_id': RID})
    assert queued.status_code == 200 and queued.json()['tasks'][0]['state'] == 'queued'
    assert not manager.store.all('session')
