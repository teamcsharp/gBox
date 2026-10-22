from types import SimpleNamespace

import pytest

from gbox import char_coverage as CC, game_capabilities as GC, game_unlocks as GU
from gbox import favorite_capabilities as FC
from gbox.character_collection import AutoCollection
from gbox.store import Store


def game(gid='fixture', **kwargs):
    return {'game_id': gid, 'title': gid, 'platform': 'dreamcast', 'library': 'owned', 'favorite': True, **kwargs}


def proof(**kwargs):
    return {'result': 'passed', 'source_sha256': 'a' * 64, 'artifact_sha256': ['b' * 64],
            'scope': 'Kasumi costume 00 core', **kwargs}


def test_registered_roster_is_never_full_source_or_universal_swap():
    entries = [{'slug': 'hero', 'model': 'hero.glb', 'source': {'game_id': 'fixture'}, 'rig': {'roles': {'hip': 'hips'}}}]
    row = GC.describe(game(), entries, extractor='fixture', roster=[{'slug': 'hero'}],
                      writer={'routed': True, 'writer': 'fixture', 'slots': ['hero'], 'replaces': 'hero only'})
    assert not row['complete_source_verified'] and not row['any_character_to_any_slot_verified']
    assert row['operations']['characters']['missing_registered'] == []
    assert row['operations']['characters']['scope'] == 'registered_roster_subset'
    assert row['operations']['stages']['status'] == 'unknown'
    assert row['operations']['native_reimport']['status'] == 'implemented_unverified'
    assert {t['operation'] for t in GC.backlog(row)} == set(GC.OPERATIONS)


@pytest.mark.parametrize('change', [
    {'artifact_sha256': []}, {'source_sha256': 'unknown'}, {'scope': ''}, {'scope': ['not-a-bounded-string']},
    {'runtime_verified': False}, {'result': 'failed'},
])
def test_reimport_verification_needs_identity_artifacts_scope_and_runtime(change):
    assert not GC.verified_evidence(proof(runtime_verified=True) | change, 'native_reimport')


def test_partial_verified_extraction_keeps_full_source_backlog():
    p = proof()
    row = GC.describe(game(), evidence={'characters': p})
    assert row['operations']['characters']['status'] == 'verified'
    assert not row['complete_source_verified']
    assert 'characters' in {t['operation'] for t in GC.backlog(row)}
    for expected in (0, True, 2):
        assert not GC.verified_evidence(proof(scope='full_source', expected=expected, verified=1,
                                            inventory_authoritative=True), 'characters')
    full = proof(scope='full_source', expected=2, verified=2, inventory_authoritative=True)
    row = GC.describe(game(), evidence={k: full for k in ('source_inventory', 'characters', 'costumes', 'stages')})
    assert row['complete_source_verified']
    assert not ({'source_inventory', 'characters', 'costumes', 'stages'} & {t['operation'] for t in GC.backlog(row)})


def test_catalog_scan_crosses_pages_and_has_no_ui_filters():
    favorites = [game(str(i), platform='psx' if i % 2 else 'dreamcast') for i in range(6)]
    calls = []
    def fetch(params):
        calls.append(params)
        off = params['offset']
        # Server intentionally caps the requested page size to two rows.
        return {'total': 6, 'offset': off, 'items': favorites[off:off + 2]}
    result, meta = FC.paginate_favorites(fetch, page_size=500)
    assert result == favorites and meta['pagination_complete']
    assert [p['offset'] for p in calls] == [0, 2, 4]
    assert all(not p[k] for p in calls for k in ('platform', 'library', 'local', 'exclude_platforms', 'system', 'q'))
    ctx = SimpleNamespace(server='http://user:secret@localhost:8765/?token=secret')
    _items, catalog = FC.read_favorites(ctx, lambda *args, **kwargs: fetch(kwargs['params']))
    assert catalog['control_url'] == 'http://localhost:8765/'
    assert catalog['platform_counts'] == {'dreamcast': 3, 'psx': 3}
    assert catalog['library_counts'] == {'owned': 6}


@pytest.mark.parametrize('mode', ['repeated', 'empty', 'changed', 'nonfavorite', 'badtotal', 'exception'])
def test_inconsistent_or_stalled_scan_never_claims_complete(mode):
    def fetch(params):
        off = params['offset']
        if not off:
            return {'total': 3, 'offset': 0, 'items': [game('first')]}
        if mode == 'exception':
            raise OSError('offline')
        return {'total': 4 if mode == 'changed' else 'bad' if mode == 'badtotal' else 3,
                'offset': off, 'items': [] if mode == 'empty' else
                [game('first')] if mode == 'repeated' else [game('second', favorite=mode != 'nonfavorite'), game('third')]}
    _games, meta = FC.paginate_favorites(fetch, page_size=1)
    assert not meta['pagination_complete'] and meta['errors']
    assert len(meta['pages']) <= 3


def test_empty_catalog_is_complete_but_old_list_without_total_is_not():
    assert FC.paginate_favorites(lambda p: {'total': 0, 'items': [], 'offset': 0})[1]['pagination_complete']
    assert not FC.paginate_favorites(lambda p: [game()])[1]['pagination_complete']


def test_scan_defaults_read_only_and_does_not_guess_re5_unlocks(monkeypatch):
    monkeypatch.setattr(CC, 'extractor_for', lambda g: (None, []))
    monkeypatch.setattr(CC, 'writer_for', lambda g: None)
    calls = []
    def api(ctx, method, path, **kw):
        calls.append((method, path))
        assert method == 'GET'
        if path == '/api/catalog':
            return {'items': [game('re5', title='Resident Evil 5', platform='xbox360')], 'total': 1, 'offset': 0}
        assert path == '/api/characters'
        return []
    report = FC.scan(SimpleNamespace(server='http://control'), api)
    assert report['summary']['favorites'] == 1 and report['summary']['backlog_items'] == 8
    assert report['games'][0]['operations']['unlocks']['status'] == 'unsupported'
    assert report['collection_jobs'] == [] and len(calls) == 2


def test_optional_scan_queues_only_new_supported_collection_and_deduplicates(monkeypatch):
    games = [game('new'), game('running'), game('failed'), game('unknown')]
    monkeypatch.setattr(CC, 'extractor_for', lambda g: ('native', [{'slug': 'hero'}]) if g['game_id'] != 'unknown' else (None, []))
    monkeypatch.setattr(CC, 'writer_for', lambda g: None)
    post = []
    def api(ctx, method, path, **kw):
        if path == '/api/catalog':
            return {'items': games, 'total': len(games), 'offset': 0}
        if path == '/api/characters':
            return []
        if path == '/api/character-collection/policy':
            return {'enabled': True}
        gid = path.split('/')[3]
        if path.endswith('/roster'):
            return {'collection': {'state': {'new': 'not_started', 'running': 'running', 'failed': 'failed'}[gid]}}
        assert method == 'POST' and path.endswith('/favorite')
        post.append(gid)
        return {'collection': {'state': 'queued', 'job_id': gid + '-job'}}
    report = FC.scan(SimpleNamespace(server='http://control'), api, schedule_collection=True)
    assert post == ['new'] and report['collection_jobs'][0]['scope'] == 'registered_roster_subset'
    post.clear()
    FC.scan(SimpleNamespace(server='http://control'), api, schedule_collection=True, retry_failed=True)
    assert post == ['new', 'failed']


def test_verified_unlock_is_checksum_pinned_and_opt_in():
    re6 = game(GU.RE6_ID, platform='xbox360')
    profile = GU.profile_for(re6)
    assert profile['verified'] and profile['template_sha256'] == GU.RE6_TEMPLATE_SHA256
    assert profile['exclusions'] and not GU.profile_for(game('re5'))['verified']
    worker = {'id': 'jay', 'name': 'JAYBUILTFINALE'}
    unsupported = GU.launch_plan(game('re5'), worker, enable_unlock=True, allow_save_upgrade=True)
    assert unsupported['status'] == 'unsupported_unlock' and not unsupported['jobs']
    needs = GU.launch_plan(re6, worker, enable_unlock=True)
    assert needs['status'] == 'save_upgrade_opt_in_required' and not needs['jobs']
    plan = GU.launch_plan(re6, worker, enable_unlock=True, allow_save_upgrade=True)
    assert not plan['executed'] and len(plan['jobs']) == 1
    assert plan['jobs'][0]['tool'] == 'launch_game' and plan['jobs'][0]['agent_use'] is True
    assert plan['jobs'][0]['require_worker'] == 'jay' and plan['unlock_after_launch']
    live = GU.launch_plan(re6, worker, enable_unlock=True, allow_save_upgrade=True, session_id='jay-live')
    assert live['jobs'][0]['input'] == {'op': 'unlock_all', 'on': True, 'session_id': 'jay-live'}
    assert GU.launch_plan(re6, worker, session_id='jay-live')['jobs'] == []
    assert not GU.profile_for(game(GU.RE6_ID, platform='psx'))['verified']
    with pytest.raises(ValueError, match='JAYBUILTFINALE'):
        GU.launch_plan(re6, {'id': 'i9', 'name': 'i9-NUC'})
    with pytest.raises(ValueError, match='session'):
        GU.launch_plan(re6, worker, session_id='i9-live')


def test_changed_unlock_template_fails_closed(monkeypatch):
    monkeypatch.setattr(GU, 'RE6_TEMPLATE_SHA256', '0' * 64)
    profile = GU.profile_for(game(GU.RE6_ID, platform='xbox360'))
    assert profile['status'] == 'unverified' and not profile['verified']


def test_favorite_tracks_backlog_when_automatic_collection_disabled(monkeypatch, tmp_path):
    from gbox import characters as C
    monkeypatch.setattr(C, 'list_all', lambda _: [])
    monkeypatch.setattr(CC, 'extractor_for', lambda _: (None, []))
    monkeypatch.setattr(CC, 'writer_for', lambda _: None)
    store = Store(tmp_path)
    store.put('setting', 'auto_character_collection', {'enabled': False})
    auto = AutoCollection(store, None)
    auto.after_favorite(game(), lambda _: pytest.fail('disabled collector must not queue'))
    status = auto.status('fixture')
    assert status['state'] == 'not_started'
    assert len(status['backlog']) == 8 and not status['capabilities']['complete_source_verified']
    assert not store.all('request') and not store.all('job')
    store.upsert_catalog([game(), game('other', platform='psx')])
    report = auto.scan_favorites()
    assert report['catalog']['pagination_complete'] and len(report['games']) == 2
    assert {row['platform'] for row in report['games']} == {'psx', 'dreamcast'}


def test_coverage_includes_favorites_absent_from_static_supported_games(monkeypatch):
    from gbox import characters as C
    monkeypatch.setattr(CC, 'WRITERS', [])
    monkeypatch.setattr(CC, 'DISCUSSED', [])
    monkeypatch.setattr(CC, 'extractor_for', lambda _: (None, []))
    monkeypatch.setattr(CC, 'writer_for', lambda _: None)
    monkeypatch.setattr(C, 'RE4GC', {})
    monkeypatch.setattr(C, 'RE4WII', {})
    def api(ctx, method, path, **kw):
        return [] if path == '/api/characters' else {'total': 1, 'offset': 0, 'items': [game('unsupported-favorite')]}
    result = CC.coverage(SimpleNamespace(server='http://control'), api)
    assert result['games'][0]['game_id'] == 'unsupported-favorite'
    assert len(result['games'][0]['backlog']) == 8
    assert result['summary']['favorites'] == 1 and result['favorite_catalog']['pagination_complete']


def test_mgs_writer_scope_names_every_figure_and_stays_unverified():
    writer = CC.writer_for(game('f55555ee6513391b', title='Metal Gear Solid - VR Missions', platform='psx'))
    assert writer['routed'] and writer['writer'] == 'gbox.mgs_vr_swap'
    assert {'player', 'enemy:soldier', 'enemy:ninja'} <= set(writer['slots'])
    assert 'any collection character' in writer['replaces'] and 'unverified in game' in writer['replaces']


def test_doa_available_source_exports_are_verified_separately_from_collection_and_stages():
    g = game('1de2e7634f3161ff', title='Dead or Alive 2 - Limited Edition (Japan)')
    row = GC.describe(g, extractor='doa2', roster=[{'slug': 'kasumi'}])
    source = row['verified_fighter_costume_source']
    assert source['verified'] == source['expected'] == 79 and source['native_declared'] == 80
    assert source['unavailable_native_sources'][0]['stem'] == 'BAY02'
    assert row['operations']['characters']['in_collection'] == []
    assert row['operations']['characters']['missing_registered'] == ['kasumi']
    assert row['operations']['costumes']['status'] == 'verified'
    assert row['operations']['stages']['status'] == 'unknown' and not row['complete_source_verified']
    assert not source['runtime_verified'] and not row['any_character_to_any_slot_verified']
    assert row['operations']['native_reimport']['runtime_verified']
    assert row['operations']['mod_launch']['runtime_verified']
    assert len(row['operations']['native_reimport']['evidence']['cases']) == 2
    tasks = {t['operation'] for t in GC.backlog(row)}
    assert 'costumes' not in tasks and {'source_inventory', 'characters', 'stages', 'mod_launch'} <= tasks
    assert 'native_reimport' in tasks


def test_mgsvr_profile_is_exact_manual_trigger_and_plans_mgs_vr_job():
    mg = game(GU.MGSVR_ID, platform='psx')
    profile = GU.profile_for(mg)
    assert profile['verified'] and profile['auto_on_load'] is False and len(profile['exe_sha256']) == 64
    assert profile['exclusions'] and 'running' in profile['trigger']
    worker = {'id': 'jay', 'name': 'JAYBUILTFINALE'}
    assert GU.launch_plan(mg, worker, enable_unlock=True)['status'] == 'save_upgrade_opt_in_required'
    live = GU.launch_plan(mg, worker, enable_unlock=True, allow_save_upgrade=True, session_id='jay-live')
    assert live['jobs'][0]['tool'] == 'mgs_vr' and live['jobs'][0]['input'] == {'op': 'unlock_all', 'session_id': 'jay-live'}
    assert GU.pre_launch(mg, None)['state'] == 'needs_running_mission'
