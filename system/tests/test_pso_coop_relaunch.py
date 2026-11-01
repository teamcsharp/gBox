"""The persistent buddy card must never be opened by two emulator processes."""
import pytest
from fastapi import HTTPException

from test_session_reset import enclosed, post, reset_route


def buddy_transport(reset_route, *, stop_output=None, frozen=False, stop_error=False):
    _, _, store, reset = reset_route
    store.put('session', 'w-live', store.get('session', 'w-live') | {
        'detail': {'pso_coop': {'players': 2, 'persistent': True}}})
    # The old jump flag must not boot a saved single-player state on the buddy card.
    store.put('job', 'live', {'input': {'pso_coop': True, 'jump': True}})
    calls = []

    def run(tool, inp, *args, **kwargs):
        calls.append((tool, dict(inp)))
        if tool == 'session_op' and inp['op'] == 'reset':
            raise HTTPException(409, 'session_op failed: running' if frozen else 'Unsupported: reset')
        if tool == 'state_transfer':
            assert inp == {'session_id': 'w-live', 'op': 'snapshot'}
            return {'result': {'artifact': 'm' * 64}}
        if tool == 'session_op' and inp['op'] == 'stop_game':
            assert inp['session_id'] == 'w-live'
            assert not store.get('session', 'w-new')
            if stop_error:
                raise HTTPException(409, 'session_op failed: running')
            return {'ended': True, 'session_id': 'w-live'} if stop_output is None else stop_output
        if tool == 'launch_game':
            assert inp['pso_coop'] is True
            assert not inp.get('jump')
            assert 'keep_session' not in inp
            assert 'w-live' not in inp.get('keep_sessions', [])
            store.put('session', 'w-new', {'session_id': 'w-new', 'game_id': 'ts',
                                          'state': 'running', 'adapter': 'dolphin'})
            return {'session_id': 'w-new'}
        pytest.fail('Unexpected tool: ' + tool)

    enclosed(reset, '_run_job').cell_contents = run
    return calls


@pytest.mark.parametrize('frozen', [False, True])
@pytest.mark.parametrize('output', [{}, {'ended': False, 'session_id': 'w-live'},
                                  {'ended': 1, 'session_id': 'w-live'}, {'ended': True},
                                  {'ended': True, 'session_id': 'other-live'}, 'unstructured'])
def test_unconfirmed_buddy_stop_never_reopens_card(reset_route, frozen, output):
    calls = buddy_transport(reset_route, frozen=frozen, stop_output=output)
    response = post(reset_route, mode='reset' if frozen else 'restart')
    assert response.status_code == 409, response.text
    assert 'PSO buddy card' in response.json()['detail']
    assert not any(tool == 'launch_game' for tool, _ in calls)
    assert reset_route[2].get('session', 'w-live')['state'] == 'running'


@pytest.mark.parametrize('frozen', [False, True])
def test_buddy_stop_error_never_reopens_card(reset_route, frozen):
    calls = buddy_transport(reset_route, frozen=frozen, stop_error=True)
    response = post(reset_route, mode='reset' if frozen else 'restart')
    assert response.status_code == 409, response.text
    assert not any(tool == 'launch_game' for tool, _ in calls)


@pytest.mark.parametrize('mode,frozen', [('restart', False), ('hard', False), ('reset', True)])
def test_buddy_relaunch_confirms_exact_stop_and_preserves_private_launch(reset_route, mode, frozen):
    calls = buddy_transport(reset_route, frozen=frozen)
    response = post(reset_route, mode=mode, **({'intent': 'hard_reset'} if mode == 'hard' else {}))
    assert response.status_code == 200, response.text
    assert [(tool, inp.get('op')) for tool, inp in calls][-2:] == [
        ('session_op', 'stop_game'), ('launch_game', None)]
    assert sum(inp.get('op') == 'stop_game' for _, inp in calls) == 1
    assert sum(tool == 'state_transfer' for tool, _ in calls) == (0 if frozen else 1)
    assert reset_route[2].get('session', 'w-live')['replaced_by'] == 'w-new'
