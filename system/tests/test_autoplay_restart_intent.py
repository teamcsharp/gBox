"""A no-op Start keeps live settings and updates the recovery/takeover intent together."""
from types import SimpleNamespace

import pytest

from gbox import autoplay_resume as A, tools
from gbox.store import Store


@pytest.mark.parametrize('continuous', [False, True])
def test_repeated_start_preserves_settings_and_attributes_later_takeover_to_latest_intent(monkeypatch, tmp_path, continuous):
    alive, packets, threads = [True], [], []
    original = tools.AutoplayIn(session_id='w-live', op='start', mode='playbook', owns_keyboard=True,
                                style={'pace': 1.25}, continuous=not continuous)
    run = {'sid': 'w-live', 'mission': 'playbook: mercs_bot', 'inp': original,
           'driver': SimpleNamespace(stopped=False), 'thread': SimpleNamespace(is_alive=lambda: alive[0])}
    ctx = SimpleNamespace(server='http://test', headers={}, job_id='first')
    monkeypatch.setitem(tools.AUTOPLAY, 'w-live', run)
    monkeypatch.setattr(tools, '_session_game_id', lambda *a: 're5')

    class Thread:
        def __init__(self, target, **kwargs):
            threads.append(target)
        def start(self):
            pass
    monkeypatch.setattr(tools.threading, 'Thread', Thread)
    monkeypatch.setattr(tools.time, 'sleep', lambda _: None)
    monkeypatch.setattr(tools.httpx, 'post', lambda *a, **kw: packets.append(kw['json']))
    tools._telemetry(run, ctx)  # the live telemetry loop captured the first Start's context

    request = tools.AutoplayIn(session_id='w-live', op='start', continuous=continuous)
    output = tools.autoplay(request, SimpleNamespace(job_id='second'))
    assert output['result']['already_running'] == run['mission']
    assert run['inp'] is original and original.continuous is continuous
    effective = output['result']['effective_input']
    assert effective['mode'] == 'playbook' and effective['owns_keyboard'] and effective['style'] == {'pace': 1.25}

    store = Store(tmp_path / 'store')
    try:
        store.put('job', 'second', {'id': 'second', 'tool': 'autoplay', 'state': 'succeeded', 'created': 20,
                                   'input': request.model_dump(), 'output': output})
        assert A.continuous(store, 'w-live') is continuous
        assert A.snapshot(store, 'w-live', {'running': True, 'age_s': 0})['input'] == effective

        run['took_over'], alive[0] = True, False
        threads[0]()
        assert packets[-1]['autoplay_taken_over']
        assert packets[-1]['source_autoplay_job_id'] == 'second'
        assert A.note_handoff(store, 'w-live', packets[-1]['source_autoplay_job_id'])
        assert not A.continuous(store, 'w-live')
        assert A.snapshot(store, 'w-live', {'running': True, 'age_s': 0}) is None
    finally:
        store.db.close()


def test_start_does_not_claim_a_bot_that_is_still_stopping(monkeypatch):
    run = {'mission': 'playbook: mercs_bot', 'driver': SimpleNamespace(stopped=True),
           'thread': SimpleNamespace(is_alive=lambda: True), 'source_autoplay_job_id': 'first'}
    monkeypatch.setitem(tools.AUTOPLAY, 'w-live', run)
    monkeypatch.setattr(tools, '_session_game_id', lambda *a: 're5')
    with pytest.raises(ValueError, match='is stopping'):
        tools.autoplay(tools.AutoplayIn(session_id='w-live', op='start', continuous=True), SimpleNamespace(job_id='second'))
    assert run['source_autoplay_job_id'] == 'first'
