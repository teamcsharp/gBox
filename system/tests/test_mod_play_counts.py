from gbox.built_mods import play_counts, gallery
from tests.test_built_mods import fixture


def test_player_counts_aliases_deduplicates_and_excludes_failed_agent_and_stock(tmp_path):
    cfg, app, store, _ = fixture(tmp_path)
    sessions = [
        {'session_id': 'w-player', 'game_id': 'pso', 'mod': 'cast_pso_ult~one', 'state': 'ended', 'started': 1},
        {'session_id': 'w-copy', 'game_id': 'pso', 'mod': 'unrelated-copy', 'collection_mod': 'cast_pso_ult', 'state': 'running', 'started': 9},
        {'session_id': 'w-failed', 'game_id': 'pso', 'mod': 'cast_pso_ult', 'state': 'failed', 'started': 10},
        {'session_id': 'w-test', 'game_id': 'pso', 'mod': 'cast_pso_ult', 'state': 'ended', 'started': 11},
        {'session_id': 'w-claimed', 'game_id': 'pso', 'mod': 'cast_pso_ult', 'state': 'running', 'started': 12},
        {'session_id': 'w-stock', 'game_id': 'pso', 'mod': '', 'state': 'ended', 'started': 13},
    ]
    store.put('job', 'test', {'id': 'test', 'tool': 'launch_game', 'agent_use': True, 'output': {'session_id': 'w-test'}})
    store.put('job', 'claimed', {'id': 'claimed', 'tool': 'launch_game', 'agent_use': True})
    store.put('slabel', 'w-claimed', {'session_id': 'w-claimed', 'owner': 'you'})
    assert play_counts(store, sessions + sessions[:1]) == {('pso', 'cast_pso_ult'): {'play_count': 3, 'last_played': 12}}


def test_gallery_counts_refresh_from_actual_sessions(tmp_path):
    cfg, app, store, _ = fixture(tmp_path)
    before = gallery(store, cfg, register=False)['items']
    assert next(m for m in before if m['key'] == 'pso/cast_pso_ult')['play_count'] == 0
    store.put('session', 'w-play', {'session_id': 'w-play', 'game_id': 'pso', 'mod': 'cast_pso_ult', 'started': 100, 'state': 'running'})
    after = {m['key']: m for m in gallery(store, cfg, register=False)['items']}
    assert after['pso/cast_pso_ult']['play_count'] == 1
    assert after['pso/cast_pso_ult']['last_played'] == 100
