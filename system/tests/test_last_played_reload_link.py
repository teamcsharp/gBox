"""Historical reload continuity is tied to one accepted launch, game/build and worker."""
import copy

import pytest

from gbox import last_played as LP
from gbox.store import Store


@pytest.fixture
def reload_case(tmp_path):
    store = Store(tmp_path)
    old = {'session_id': 'w-old', 'game_id': 're5', 'state': 'ended', 'adapter': 'rpcs3',
           'started': 10., 'ended': 20., 'mod': 'bow', 'collection_mod': 'bow',
           'launch_mod': 'bow~pinned', 'checkpoint': 'saved-state', 'exit': {'via': 'stop'}}
    game = {'game_id': 're5', 'title': 'RE5', 'platform': 'ps3', 'serial': 'BLUS30491',
            'hashes': {'sha256': 'a' * 64}, 'launch': {'path': 'PS3_GAME/USRDIR/EBOOT.BIN'},
            'format': 'folder', 'source_paths': ['RE5']}
    launch = {'game': game, 'mod': 'bow~pinned', 'jump': True, 'pad': 'keyboard'}
    origin = {'via': 'session_reload', 'from_session': 'w-old', 'reload_id': 'reload-nonce'}
    new = {'session_id': 'w-new', 'game_id': 're5', 'state': 'running', 'adapter': 'rpcs3',
           'started': 30., 'mod': 'bow', 'launch_mod': 'bow~pinned'}
    job = {'id': 'new', 'tool': 'launch_game', 'state': 'succeeded', 'worker_id': 'w', 'require_worker': 'w',
           'origin': origin, 'input': launch, 'output': {'session_id': 'w-new'}}
    store.put('session', old['session_id'], old)
    store.put('session', new['session_id'], new)
    store.put('job', 'new', job)
    yield store, old, launch, origin
    store.db.close()


def link(case):
    store, old, launch, origin = case
    return LP.link_reload(store, old, 'w-new', 'w', launch, origin, 'operator', 40.)


def test_exact_reload_links_history_without_losing_exit_or_checkpoint(reload_case):
    store, old, _, _ = reload_case
    link(reload_case)
    updated = store.get('session', 'w-old')
    assert updated['replaced_by'] == 'w-new'
    assert updated['checkpoint'] == old['checkpoint'] and updated['exit'] == old['exit']
    assert updated['ended'] == 20. and updated['state'] == 'ended'
    assert updated['reload_replacement']['launch_job'] == 'new'
    assert store.get('session', 'w-new')['reloaded_from'] == 'w-old'
    assert store.get(LP.DISMISS_KIND, 'w-old')['reloaded'] == 'w-new'
    with pytest.raises(ValueError, match='already has a replacement'):
        link(reload_case)


@pytest.mark.parametrize('mutation', [
    'different_game', 'different_adapter', 'different_build', 'ended_successor', 'newer_replacement',
    'old_running', 'changed_old_build', 'wrong_worker', 'wrong_pin', 'wrong_output', 'unrelated_job',
    'failed_job', 'wrong_origin', 'wrong_parent', 'wrong_nonce', 'wrong_game_hash', 'wrong_serial',
    'wrong_launch_build', 'lost_jump', 'lost_pad', 'successor_already_replaced', 'another_predecessor',
])
def test_unrelated_or_superseded_session_is_never_linked(reload_case, mutation):
    store, _, _, _ = reload_case
    old, new, job = (store.get('session', 'w-old'), store.get('session', 'w-new'), store.get('job', 'new'))
    if mutation == 'different_game': new['game_id'] = 're6'
    if mutation == 'different_adapter': new['adapter'] = 'xenia'
    if mutation == 'different_build': new['launch_mod'] = 'bow~newer'
    if mutation == 'ended_successor': new['state'] = 'ended'
    if mutation == 'newer_replacement': old['replaced_by'] = 'w-newer'
    if mutation == 'old_running': old['state'] = 'running'
    if mutation == 'changed_old_build': old['launch_mod'] = 'bow~newer'
    if mutation == 'wrong_worker': job['worker_id'] = 'other'
    if mutation == 'wrong_pin': job['require_worker'] = 'other'
    if mutation == 'wrong_output': job['output']['session_id'] = 'w-unrelated'
    if mutation == 'unrelated_job': job['tool'] = 'session_swap'
    if mutation == 'failed_job': job['state'] = 'failed'
    if mutation == 'wrong_origin': job['origin']['via'] = 'launch_game'
    if mutation == 'wrong_parent': job['origin']['from_session'] = 'w-unrelated'
    if mutation == 'wrong_nonce': job['origin']['reload_id'] = 'another-reload'
    if mutation == 'wrong_game_hash': job['input']['game']['hashes']['sha256'] = 'b' * 64
    if mutation == 'wrong_serial': job['input']['game']['serial'] = 'BLES00812'
    if mutation == 'wrong_launch_build': job['input']['mod'] = 'bow~newer'
    if mutation == 'lost_jump': job['input']['jump'] = False
    if mutation == 'lost_pad': job['input']['pad'] = ''
    if mutation == 'successor_already_replaced': new['replaced_by'] = 'w-latest'
    if mutation == 'another_predecessor': new['reloaded_from'] = 'w-unrelated'
    store.put('session', 'w-old', old)
    store.put('session', 'w-new', new)
    store.put('job', 'new', job)
    with pytest.raises(ValueError):
        link(reload_case)
    assert store.get('session', 'w-old') == old
    assert store.get('session', 'w-new') == new
    assert store.get(LP.DISMISS_KIND, 'w-old') is None
    assert store.db.execute('SELECT COUNT(*) FROM audit').fetchone()[0] == 0


def test_only_an_explicit_same_host_worker_alias_permits_old_worker_id(reload_case):
    store, old, launch, origin = reload_case
    old = old | {'session_id': 'previous-old'}
    origin = origin | {'from_session': old['session_id']}
    store.put('session', old['session_id'], old)
    job = store.get('job', 'new')
    store.put('job', 'new', job | {'origin': origin})
    with pytest.raises(ValueError, match='worker'):
        LP.link_reload(store, old, 'w-new', 'w', launch, origin, 'operator', 40.)
    LP.link_reload(store, old, 'w-new', 'w', launch, origin, 'operator', 40., lambda wid: {'previous': 'w'}.get(wid, wid))
    assert store.get('session', old['session_id'])['replaced_by'] == 'w-new'


def test_accepted_original_recipe_preserves_game_jump_pad_and_exact_staged_build(reload_case):
    store, old, launch, _ = reload_case
    original = copy.deepcopy(launch)
    store.put('job', 'old', {'tool': 'launch_game', 'state': 'succeeded', 'input': original,
                             'output': {'session_id': 'w-old'}})
    changed_catalog = original['game'] | {'hashes': {'sha256': 'new-catalog-hash'}}
    assert LP.reload_input(store, old, changed_catalog) == launch
    store.put('job', 'old', {'tool': 'launch_game', 'state': 'succeeded', 'input': original,
                             'output': {'session_id': 'w-unrelated'}})
    fallback = LP.reload_input(store, old, changed_catalog)
    assert fallback == {'game': changed_catalog, 'mod': 'bow~pinned'}
