"""A stalled solo rotation recovers, and queued overlays reach a real cold launch."""
import pytest

from gbox import mercmode as M, screensaver as S
from tests.test_mercmode import boundary, owned, playing


def finish_session(store, run):
    sid = run['session_id']
    store.put('session', sid, store.get('session', sid) | {'state': 'ended'})


def test_single_title_without_a_boundary_restarts_instead_of_staying_stuck():
    store, w, saver, calls, now, tick, run, job = playing()
    M.configure(store, w['name'], {'titles': [run['mercmode']['title']]})
    tick(S.NO_PROGRESS_S + 1)
    assert calls[-1]['input'] == {'session_id': run['session_id'], 'op': 'stop_game', 'args': {}}
    assert store.get(S.STATE, w['name']) is None
    assert store.all(S.LOG)[-1]['mercmode_no_progress']['idle_s'] >= S.NO_PROGRESS_S
    finish_session(store, run)
    tick(1)
    assert calls[-1]['tool'] == 'launch_game'
    assert calls[-1]['input']['game']['game_id'] == run['game_id']


def test_no_progress_never_keeps_the_stalled_game_warm():
    store, w, saver, calls, now, tick, run, job = playing()
    w['features'] = [M.WARM_FEATURE]
    M.configure(store, w['name'], {'keep_warm': 1})
    tick(S.NO_PROGRESS_S + 1)
    assert calls[-1]['input']['op'] == 'stop_game'
    assert not M.warm_pool(store, w['name'])


def native_stats(run, **patch):
    return {'screen': 'playing', 'source_session_id': run['session_id'],
        'source_autoplay_job_id': run['autoplay_job'], 'round_evidence_id': 'active-round',
        'kills': 1, 'score': 100, **patch}


def test_a_long_healthy_single_title_round_survives_but_stalled_counters_recover():
    store, w, saver, calls, now, tick, run, job = playing()
    M.configure(store, w['name'], {'titles': [run['mercmode']['title']]})
    # A pre-existing round can already be older than the watchdog when the server upgrades.
    for n in range(8):
        after = S.NO_PROGRESS_S + 1 if not n else S.NO_PROGRESS_S / 2
        S.telemetry_put(run['session_id'], {'running': True, 'stats': native_stats(run, kills=n+1, score=100*(n+1))},
                        now=now[0] + after)
        tick(after)
        assert store.get(S.STATE, w['name'])['session_id'] == run['session_id']
    last_progress = now[0]
    # Fresh, busy telemetry with unchanged native counters cannot extend the deadline.
    for n in range(4):
        after = S.NO_PROGRESS_S / 4 + 1
        S.telemetry_put(run['session_id'], {'running': True,
            'stats': native_stats(run, kills=8, score=800, menu_presses=n+1, ram_progress=n+1)}, now=now[0]+after)
        tick(after)
    assert store.get(S.STATE, w['name']) is None
    assert store.all(S.LOG)[-1]['mercmode_no_progress']['since'] == last_progress
    assert calls[-1]['input']['op'] == 'stop_game'


@pytest.mark.parametrize('patch,age', [({'screen': 'results'}, 0), ({'screen': 'dead'}, 0),
    ({'source_session_id': 'other'}, 0), ({'source_autoplay_job_id': 'superseded'}, 0),
    ({'kills': True, 'score': float('nan')}, 0), ({}, 20)])
def test_only_fresh_playing_exact_native_counters_can_hold_watchdog(patch, age):
    store, w, saver, calls, now, tick, run, job = playing()
    at = now[0] + S.NO_PROGRESS_S + 1
    S.telemetry_put(run['session_id'], {'running': True, 'stats': native_stats(run, **patch)}, now=at-age)
    tick(S.NO_PROGRESS_S + 1)
    assert store.get(S.STATE, w['name']) is None
    assert calls[-1]['input']['op'] == 'stop_game'


def test_new_round_counter_reset_does_not_refresh_stalled_progress():
    store, w, saver, calls, now, tick, run, job = playing()
    S.telemetry_put(run['session_id'], {'running': True, 'stats': native_stats(run)}, now=now[0])
    tick()
    at = now[0] + S.NO_PROGRESS_S + 1
    S.telemetry_put(run['session_id'], {'running': True,
        'stats': native_stats(run, round_evidence_id='new-round', kills=0, score=0)}, now=at)
    tick(S.NO_PROGRESS_S + 1)
    assert store.get(S.STATE, w['name']) is None


def test_fresh_icon_panel_loop_holds_the_watchdog_but_a_stale_loop_does_not():
    store, w, saver, calls, now, tick, run, job = playing()
    M.configure(store, w['name'], {'titles': [run['mercmode']['title']]})
    held_at = now[0] + S.NO_PROGRESS_S + 1
    S.telemetry_put(run['session_id'], {'running': True, 'stats': {
        'icon_panel_holds_title': True, 'screen': 'select_stage', 'source_session_id': run['session_id'],
        'source_autoplay_job_id': run['autoplay_job']}}, now=held_at)
    tick(S.NO_PROGRESS_S + 1)
    assert store.get(S.STATE, w['name'])['mercmode_last_hold'] == held_at
    tick(S.NO_PROGRESS_S - 1)
    assert store.get(S.STATE, w['name']) is not None
    tick(2)
    assert store.get(S.STATE, w['name']) is None
    assert calls[-1]['input']['op'] == 'stop_game'


@pytest.mark.parametrize('identity', [
    {}, {'source_session_id': 'foreign-session'}, {'source_autoplay_job_id': 'superseded-job'},
])
def test_fresh_icon_panel_hold_from_missing_or_foreign_owner_does_not_hold_watchdog(identity):
    store, w, saver, calls, now, tick, run, job = playing()
    stats = {'source_session_id': run['session_id'], 'source_autoplay_job_id': run['autoplay_job']}
    stats = (stats | identity) if identity else {}
    stats.update(icon_panel_holds_title=True, screen='select_stage')
    S.telemetry_put(run['session_id'], {'running': True, 'stats': stats}, now=now[0] + S.NO_PROGRESS_S + 1)
    tick(S.NO_PROGRESS_S + 1)
    assert store.get(S.STATE, w['name']) is None
    assert calls[-1]['input']['op'] == 'stop_game'


def test_disabling_mercmode_pins_a_random_skin_round_past_its_timer():
    store, w, saver, calls, now, tick, run, job = playing()
    M.configure(store, w['name'], {'enabled': False, 'skin_swap': 'random'})
    tick(M.SKIN_ROTATE_S + S.NO_PROGRESS_S)
    current = store.get(S.STATE, w['name'])
    assert current['mercmode_pinned'] and not current['mercmode_rotate_requested']
    assert not [c for c in calls if c['tool'] == 'session_op']


def test_native_single_title_skin_boundary_closes_instead_of_parking():
    store, w, saver, calls, now, tick, run, job = playing()
    w['features'] = [M.WARM_FEATURE]
    M.configure(store, w['name'], {'titles': [run['mercmode']['title']], 'keep_warm': 1, 'skin_swap': 'random'})
    assert saver.round_boundary(boundary(run, now[0]), job, now[0])['rotate_requested']
    assert store.get(S.STATE, w['name'])['mercmode_skin_rotate']
    tick(1)
    assert calls[-1]['input']['op'] == 'stop_game'
    assert not M.warm_pool(store, w['name'])


def test_same_title_queued_build_is_consumed_only_by_its_cold_launch():
    store, w, saver, calls, now, tick, run, job = playing()
    w['features'] = [M.WARM_FEATURE]
    entry = {'title': run['mercmode']['title'], 'mod': 'replacement-candidate'}
    M.configure(store, w['name'], {'titles': [entry['title']], 'keep_warm': 1, 'queue': [entry]})
    assert saver.round_boundary(boundary(run, now[0]), job, now[0])['rotate_requested']
    assert M.settings(store, w['name'])['queue'][0]['mod'] == entry['mod']
    assert store.get(S.STATE, w['name'])['mercmode_mod_rotate']
    tick(1)
    assert calls[-1]['input']['op'] == 'stop_game'
    finish_session(store, run)
    tick(1)
    assert calls[-1]['tool'] == 'launch_game'
    assert calls[-1]['input']['mod'] == entry['mod'] and calls[-1]['input']['local_build_ok']
    assert not M.settings(store, w['name'])['queue']


@pytest.mark.parametrize('disabled,pinned', [(True, False), (False, True)])
def test_a_queued_build_cannot_rotate_a_disabled_or_pinned_round(disabled, pinned):
    store, w, saver, calls, now, tick, run, job = playing()
    M.configure(store, w['name'], {'enabled': not disabled, 'skin_swap': 'random',
        'titles': [run['mercmode']['title']], 'queue': [{'title': run['mercmode']['title'], 'mod': 'new-cast'}]})
    store.put(S.STATE, w['name'], run | {'mercmode_pinned': pinned})
    before = len(calls)
    assert not saver.round_boundary(boundary(run, now[0]), job, now[0])['rotate_requested']
    assert M.settings(store, w['name'])['queue'][0]['mod'] == 'new-cast'
    assert len(calls) == before


def test_another_title_queued_build_is_preserved_in_a_cold_promise():
    store, w, saver, calls, now, tick, run, job = playing()
    w['features'] = [M.WARM_FEATURE]
    other = 're5' if run['mercmode']['title'] == 're4' else 're4'
    cfg = M.configure(store, w['name'], {'keep_warm': 1, 'queue': [
        {'title': other, 'mod': 'new-cast'}, {'title': other, 'mod': 'following-cast'}]})
    before = len(calls)
    result = saver._prelaunch(w, run, cfg, now[0])
    assert 'cold switch' in result
    ahead = store.get(M.NEXT, w['name'])
    assert ahead['cold'] and ahead['queued'] and ahead['selection']['mod'] == 'new-cast'
    assert len(calls) == before
    finish_session(store, run)
    store.delete(S.STATE, w['name'])
    saver._start(w, S.settings(store), now[0])
    assert calls[-1]['tool'] == 'launch_game' and calls[-1]['input']['mod'] == 'new-cast'
    assert M.settings(store, w['name'])['queue'][0]['mod'] == 'following-cast'


def test_a_consumed_queued_promise_plays_before_the_following_current_title_build():
    store, w, saver, calls, now, tick, run, job = playing()
    w['features'] = [M.WARM_FEATURE]
    current = run['mercmode']['title']
    other = 're5' if current == 're4' else 're4'
    cfg = M.configure(store, w['name'], {'keep_warm': 1, 'queue': [
        {'title': other, 'mod': 'first-cast'}, {'title': current, 'mod': 'second-cast'}]})
    saver._prelaunch(w, run, cfg, now[0])
    assert saver.round_boundary(boundary(run, now[0]), job, now[0])['rotate_requested']
    assert store.get(M.NEXT, w['name'])['selection']['mod'] == 'first-cast'
    assert M.settings(store, w['name'])['queue'][0]['mod'] == 'second-cast'
    tick(1)
    finish_session(store, run)
    tick(1)
    assert calls[-1]['tool'] == 'launch_game' and calls[-1]['input']['mod'] == 'first-cast'
    assert M.settings(store, w['name'])['queue'][0]['mod'] == 'second-cast'


@pytest.mark.parametrize('patch,selection', [({}, {'mod': 'new-cast'}), ({'skin_swap': 'random'}, {}),
                                            ({'cast_swap': 'on'}, {})])
def test_a_replacement_pick_releases_a_stock_warm_copy(patch, selection):
    store, w, saver, calls, now, tick, run, job = playing()
    w['features'] = [M.WARM_FEATURE]
    other = 're5' if run['mercmode']['title'] == 're4' else 're4'
    cfg = M.configure(store, w['name'], {'keep_warm': 1, **patch})
    sid = owned(store, w, other, 'stock-warm', now[0])
    pick = next(row for row in M.inventory(store, w, cfg) if row['title'] == other) | {'selection': selection}
    assert saver._resume_warm(w, pick, cfg, now[0]) is None
    assert calls[-1]['input']['op'] == 'stop_game' and calls[-1]['input']['session_id'] == sid
    assert other not in M.warm_pool(store, w['name'])


def test_replacement_waits_for_an_inflight_stock_preload_without_losing_its_queue_entry():
    store, w, saver, calls, now, tick, run, job = playing()
    w['features'] = [M.WARM_FEATURE]
    other = 're5' if run['mercmode']['title'] == 're4' else 're4'
    cfg = M.configure(store, w['name'], {'keep_warm': 1, 'queue': [{'title': other, 'mod': 'new-cast'}]})
    pick = M.choose(store, w, saver.rng, cfg)
    store.put('job', 'loading', {'id': 'loading', 'state': 'running'})
    M.keep_warm(store, w['name'], other, {'session_id': None, 'job': 'loading', 'state': 'prelaunch',
        'game_id': pick['game_id'], 'worker_id': w['id'], 'at': now[0]})
    before = len(calls)
    assert 'waiting' in saver._resume_warm(w, pick, cfg, now[0])
    assert len(calls) == before
    assert M.warm_pool(store, w['name'])[other]['state'] == 'releasing'
    resumed_pick = M.choose(store, w, saver.rng)
    assert resumed_pick['_queue_pending'] and resumed_pick['selection']['mod'] == 'new-cast'
    assert M.settings(store, w['name'])['queue'][0]['mod'] == 'new-cast'
