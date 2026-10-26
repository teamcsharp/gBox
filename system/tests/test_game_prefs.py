"""Menu settings survive reloads, relaunches and restarts (gbox/game_prefs.py). Synthetic workers: no game.

Operator 2026-10-26: "when i set the settings in the right click menu for the mods / bot systems, retain those settings
across reloads."
"""
import time

import pytest
from fastapi.testclient import TestClient

from gbox import game_prefs as P, screensaver as S
from gbox.models import Job
from gbox.store import Store

RE5, RE4A, RE4B = P.RE5, P.RE4[0], P.RE4[1]


def store_with(tmp_path, *sessions):
    store = Store(tmp_path / 'data')
    store.put('worker', 'w1', {'id': 'w1', 'name': 'lilspark', 'os': 'linux', 'last_seen': time.time(),
                               'tools': ['re5_mods', 're_mods', 'mercs_team', 'autoplay']})
    for sid, game, adapter in sessions:
        store.put('session', sid, {'session_id': sid, 'game_id': game, 'adapter': adapter, 'state': 'running',
                                   'title': {RE5: 'Resident Evil 5'}.get(game, 'Resident Evil 4'),
                                   'started': time.time() - 300})
    return store


def job(tool, sid, inp, result, *, actor='operator', agent_use=False, via='http', ident=None):
    return {'id': ident or f'{tool}-{inp.get("op")}', 'tool': tool, 'actor': actor, 'agent_use': agent_use,
            'origin': {'via': via}, 'state': 'succeeded', 'input': {'session_id': sid, **inp},
            'output': {'result': result}}


# --- what is recorded ---

def test_discs_of_one_game_share_their_settings():
    assert P.key_for(RE4B) == RE4A and P.key_for(RE4A) == RE4A and P.key_for(RE5) == RE5
    assert P.key_for('somethingelse') == 'somethingelse'


def test_re5_menu_changes_become_this_games_settings():
    ok = {'verified': True}
    assert P.extract('re5_mods', {'op': 'unlimited_health', 'on': True}, ok) == {'unlimited_health': {'on': True}}
    assert P.extract('re5_mods', {'op': 'fire_rate', 'on': True, 'multiplier': 120}, ok) == {
        'fire_rate': {'on': True, 'multiplier': 120.0}}
    assert P.extract('re5_mods', {'op': 'fire_rate', 'on': False, 'multiplier': None}, ok) == {'fire_rate': {'on': False}}
    assert P.extract('re5_mods', {'op': 'turn_speed', 'on': True, 'multiplier': 'max'}, ok)['turn_speed']['multiplier'] == 'max'
    assert P.extract('re5_mods', {'op': 'fire_rate', 'on': True, 'multiplier': 5000}, ok) == {}, 'out of range'
    # the kill time switch keeps the seconds set earlier with the slider
    assert P.extract('re5_mods', {'op': 'kill_time', 'on': False, 'multiplier': None}, ok,
                     {'kill_time': {'on': True, 'multiplier': 7.0}}) == {'kill_time': {'on': False, 'multiplier': 7.0}}
    assert P.extract('re5_mods', {'op': 'mines', 'on': True, 'multiplier': 'only'}, ok) == {
        'mines': {'on': True, 'multiplier': 'only'}}
    assert P.extract('re5_mods', {'op': 'mines', 'on': True, 'multiplier': 30.0}, ok)['mines']['multiplier'] == 30.0
    assert P.extract('re5_mods', {'op': 'rotten_egg_only', 'on': True, 'multiplier': 8}, ok) == {
        'rotten_egg_only': {'on': True, 'multiplier': 8.0}}
    assert P.extract('re5_mods', {'op': 'weapon_override', 'on': True, 'weapon': 15, 'only': True}, ok) == {
        'weapon_override': {'on': True, 'weapon': 15, 'only': True}}
    assert P.extract('re5_mods', {'op': 'weapon_override', 'on': False}, ok) == {'weapon_override': {'on': False}}
    assert P.extract('re5_mods', {'op': 'revert_all'}, ok) == {'*': None}
    # one-shot actions and unverified changes are not settings
    for op in ('random_weapon', 'live_weapon', 'mercs_select', 'status', 'select_weapon'):
        assert P.extract('re5_mods', {'op': op, 'on': True}, ok) == {}
    assert P.extract('re5_mods', {'op': 'infinite_ammo', 'on': True}, {'verified': False}) == {}


def test_re4_and_team_changes_become_settings():
    ok = {'verified': True}
    assert P.extract('re_mods', {'op': 'combo_freeze', 'on': False}, ok | {'op': 'combo_freeze'}) == {
        'combo_freeze': {'on': False}}
    assert P.extract('re_mods', {'op': 'god', 'on': True}, ok | {'op': 'unlimited_health'}) == {
        'unlimited_health': {'on': True}}
    assert P.extract('re_mods', {'op': 'combo_time', 'on': True, 'multiplier': 4.5}, ok) == {
        'combo_time': {'on': True, 'multiplier': 4.5}}
    assert P.extract('re_mods', {'op': 'spawn_multiplier', 'on': True, 'count': 3}, ok) == {
        'spawn_multiplier': {'on': True, 'count': 3}}
    assert P.extract('re_mods', {'op': 'random_loadout', 'character': 'leon', 'damage': 99.9, 'on': True}, ok) == {
        'loadout': {'mode': 'random', 'character': 'leon', 'damage': 99.9}}
    assert P.extract('re_mods', {'op': 'merc_loadout', 'character': 'leon', 'reset': True}, ok) == {
        'loadout': {'mode': 'default', 'character': 'leon'}}
    assert P.extract('re_mods', {'op': 'give', 'item': 'handgun'}, ok) == {}
    team = {'configuration_verified': True, 'status': {'config': {'role': 'teammate_p2', 'training_profile': 'assisted',
                                                                  'auto_reduce_mods': True, 'selected_route_id': 'x'}}}
    assert P.extract('mercs_team', {'op': 'configure', 'role': 'teammate_p2'}, team) == {
        'team': {'role': 'teammate_p2', 'training_profile': 'assisted', 'auto_reduce_mods': True}}
    assert P.extract('mercs_team', {'op': 'status'}, team) == {}


def test_an_operator_change_is_kept_for_the_game_and_counts_as_applied_here(tmp_path):
    store = store_with(tmp_path, ('w1-a', RE5, 'rpcs3'))
    rec = P.observe(store, job('re5_mods', 'w1-a', {'op': 'fire_rate', 'on': True, 'multiplier': 120},
                               {'verified': True, 'op': 'fire_rate'}), 'succeeded')
    assert rec['rev'] == 1 and rec['panels']['re5_mods'] == {'fire_rate': {'on': True, 'multiplier': 120.0}}
    assert rec['title'] == 'Resident Evil 5' and rec['game_ids'] == [RE5]
    applied = store.get(P.APPLIED, 'w1-a')['ops']['re5_mods.fire_rate']
    assert applied['state'] == 'applied' and applied['value'] == {'on': True, 'multiplier': 120.0}
    P.observe(store, job('re5_mods', 'w1-a', {'op': 'fire_rate', 'on': True, 'multiplier': 120},
                         {'verified': True}, ident='again'), 'succeeded')
    assert store.get(P.KIND, RE5)['rev'] == 1, 'the same value again is not a new revision'
    P.observe(store, job('re5_mods', 'w1-a', {'op': 'revert_all'}, {'verified': True}), 'succeeded')
    assert 're5_mods' not in store.get(P.KIND, RE5)['panels']
    assert 're5_mods.fire_rate' not in store.get(P.APPLIED, 'w1-a')['ops']


@pytest.mark.parametrize('who', ['agent_use', 'hermes', 'chat_agent', 'bot', 'reapply', 'apply_saved', 'failed',
                                 'other_game'])
def test_automation_reapplies_and_failures_are_not_settings(tmp_path, who):
    store = store_with(tmp_path, ('w1-a', RE5, 'rpcs3'), ('w1-x', 'other', 'rpcs3'))
    kw, inp, sid, state = {}, {'op': 'infinite_ammo', 'on': False}, 'w1-a', 'succeeded'
    if who == 'agent_use':
        kw = {'agent_use': True, 'actor': S.ACTOR}
    elif who == 'hermes':
        kw = {'actor': 'hermes'}
    elif who == 'chat_agent':                         # the server marks the in-app chat agent's jobs agent_use
        kw = {'actor': 'gbox-agent', 'agent_use': True}
    elif who == 'bot':
        kw = {'actor': 'autoplay'}
    elif who == 'reapply':
        kw = {'actor': P.ACTOR, 'via': P.VIA}
    elif who == 'apply_saved':
        inp = {'op': 'apply_saved', 'ops': [{'name': 'infinite_ammo', 'op': 'infinite_ammo', 'on': False}]}
    elif who == 'failed':
        state = 'failed'
    else:
        sid = 'w1-x'
    assert P.observe(store, job('re5_mods', sid, inp, {'verified': True}, **kw), state) is None
    assert store.get(P.KIND, RE5) is None


def test_a_change_on_one_disc_is_kept_for_the_whole_game(tmp_path):
    store = store_with(tmp_path, ('w1-b', RE4B, 'dolphin'))
    P.observe(store, job('re_mods', 'w1-b', {'op': 'combo_freeze', 'on': False}, {'verified': True}), 'succeeded')
    assert store.get(P.KIND, RE4A)['panels']['re_mods'] == {'combo_freeze': {'on': False}}
    assert store.get(P.KIND, RE4A)['game_ids'] == [RE4B]


# --- re-applying ---

class Rig:
    def __init__(self, store, state='queued'):
        self.store, self.jobs, self.clock, self.state = store, [], time.time(), state
        self.r = P.Reapplier(store, submit=self.submit, workers=self.workers, wid=lambda w: w,
                             clock=lambda: self.clock, spawn=lambda fn: fn())

    def workers(self):
        return [w | {'online': True} for w in self.store.all('worker')]

    def submit(self, req, actor, origin):
        j = Job(tool=req.tool, input=req.input, require_worker=req.require_worker, agent_use=req.agent_use,
                actor=actor, origin=origin, state=self.state)
        self.store.put('job', j.id, j.model_dump(mode='json'))
        self.jobs.append(j.model_dump(mode='json'))
        return j

    def finish(self, results=None, state='succeeded', error=None, tool_result=None):
        last = self.jobs[-1]
        result = tool_result if tool_result is not None else {
            'results': {n: {'verified': ok, **({} if ok else {'reason': 'game still booting'})}
                        for n, ok in (results or {}).items()}}
        self.store.put('job', last['id'], last | {'state': state, 'error': error, 'output': {'result': result},
                                                  'finished': self.clock})

    def tick(self, advance=0, **kw):
        self.clock += advance
        return self.r.tick(**kw)


def save(store, key, panels, rev=1):
    store.put(P.KIND, key, {'key': key, 'game_ids': [key], 'title': 'game', 'rev': rev, 'panels': panels})


def test_a_new_session_gets_the_saved_settings_in_one_job_then_retries_what_was_not_ready(tmp_path):
    store = store_with(tmp_path, ('w1-new', RE5, 'rpcs3'))
    save(store, RE5, {'re5_mods': {'mines': {'on': True, 'multiplier': 30.0}, 'unlimited_health': {'on': True},
                                   'fire_rate': {'on': True, 'multiplier': 120.0}}, 'pip': {'save_slot': 3}})
    rig = Rig(store)
    assert rig.tick() == {'w1-new': {'re5_mods': ['fire_rate', 'mines', 'unlimited_health']}}
    sent = rig.jobs[-1]
    assert (sent['tool'], sent['actor'], sent['agent_use'], sent['require_worker']) == ('re5_mods', P.ACTOR, False, 'w1')
    assert sent['origin']['via'] == P.VIA
    assert sent['input'] == {'session_id': 'w1-new', 'op': 'apply_saved', 'ops': [
        {'name': 'unlimited_health', 'op': 'unlimited_health', 'on': True},
        {'name': 'fire_rate', 'op': 'fire_rate', 'on': True, 'multiplier': 120.0},
        {'name': 'mines', 'op': 'mines', 'on': True, 'multiplier': 30.0}]}
    assert rig.tick() == {} and len(rig.jobs) == 1, 'nothing more while it is on its way'
    rig.finish({'unlimited_health': True, 'fire_rate': False, 'mines': True})
    assert rig.tick() == {} and len(rig.jobs) == 1, 'a failed item waits before its retry'
    assert rig.tick(advance=31) == {'w1-new': {'re5_mods': ['fire_rate']}}
    assert [o['name'] for o in rig.jobs[-1]['input']['ops']] == ['fire_rate']
    rig.finish({'fire_rate': True})
    rig.tick()
    view = P.view(store, sid='w1-new')
    assert {n: v['state'] for n, v in view['applied']['re5_mods'].items()} == {
        'mines': 'applied', 'unlimited_health': 'applied', 'fire_rate': 'applied'}
    assert view['panels']['pip'] == {'save_slot': 3} and view['session_kind'] == 'operator'


def test_retries_stop_after_max_attempts_until_the_settings_change(tmp_path):
    store = store_with(tmp_path, ('w1-new', RE5, 'rpcs3'))
    save(store, RE5, {'re5_mods': {'infinite_ammo': {'on': False}}})
    rig = Rig(store)
    for _ in range(P.MAX_ATTEMPTS):
        assert rig.tick(advance=200)
        rig.finish(state='failed', error='Unsupported: re5_mods needs the running game\'s memory')
    assert rig.tick(advance=500) == {}
    assert P.view(store, sid='w1-new')['applied']['re5_mods']['infinite_ammo']['state'] == 'failed'
    save(store, RE5, {'re5_mods': {'infinite_ammo': {'on': True}}}, rev=2)
    assert rig.tick(advance=1) == {'w1-new': {'re5_mods': ['infinite_ammo']}}


def test_f5_forces_every_saved_setting_back_at_once(tmp_path):
    store = store_with(tmp_path, ('w1-new', RE5, 'rpcs3'))
    save(store, RE5, {'re5_mods': {'infinite_ammo': {'on': False}}})
    rig = Rig(store)
    rig.tick()
    rig.finish({'infinite_ammo': True})
    rig.tick()
    assert rig.tick(advance=100) == {}
    assert rig.r.force('w1-new') is True and len(rig.jobs) == 2
    assert rig.r.force('w1-new') is False, 'twice within a few seconds: once'


def test_who_gets_the_settings(tmp_path):
    store = store_with(tmp_path, ('w1-merc', RE5, 'rpcs3'), ('w1-test', RE5, 'rpcs3'), ('w1-warm', RE5, 'rpcs3'),
                       ('w1-mine', RE5, 'rpcs3'), ('w1-nuc', RE4B, 'dolphin'))
    save(store, RE5, {'re5_mods': {'infinite_ammo': {'on': False}},
                      'mercs_team': {'team': {'role': 'teammate_p2', 'training_profile': 'assisted',
                                              'auto_reduce_mods': False}}})
    store.put(S.STATE, 'lilspark', {'worker': 'lilspark', 'worker_id': 'w1', 'session_id': 'w1-merc', 'phase': 'playing'})
    store.put('slabel', 'w1-test', {'session_id': 'w1-test', 'owner': 'agent'})
    store.put('slabel', 'w1-warm', {'session_id': 'w1-warm', 'owner': 'agent', 'warm': True})
    rig = Rig(store)
    out = rig.tick()
    assert out == {'w1-merc': {'re5_mods': ['infinite_ammo']},
                   'w1-mine': {'re5_mods': ['infinite_ammo'], 'mercs_team': ['team']}}, \
        'MercMode gets the mods, never the co-op role; agent tests and paused warm games get nothing'
    team = next(j for j in rig.jobs if j['tool'] == 'mercs_team')
    assert team['input'] == {'session_id': 'w1-mine', 'op': 'configure', 'role': 'teammate_p2',
                             'training_profile': 'assisted', 'auto_reduce_mods': False}


def test_a_booting_session_and_a_worker_without_the_tool_wait(tmp_path):
    store = store_with(tmp_path, ('w1-new', RE5, 'rpcs3'))
    store.put('session', 'w1-new', store.get('session', 'w1-new') | {'started': time.time()})
    save(store, RE5, {'re5_mods': {'infinite_ammo': {'on': False}}})
    rig = Rig(store)
    assert rig.tick() == {}
    store.put('worker', 'w1', store.get('worker', 'w1') | {'tools': ['autoplay']})
    assert rig.tick(advance=60) == {}
    store.put('worker', 'w1', store.get('worker', 'w1') | {'tools': ['re5_mods']})
    assert rig.tick() == {'w1-new': {'re5_mods': ['infinite_ammo']}}


def test_the_operators_own_job_in_flight_goes_first(tmp_path):
    store = store_with(tmp_path, ('w1-new', RE4A, 'dolphin'))
    save(store, RE4A, {'re_mods': {'loadout': {'mode': 'default', 'character': 'leon'}, 'combo_freeze': {'on': False}}})
    store.put('job', 'mine', {'id': 'mine', 'tool': 're_mods', 'state': 'running',
                              'input': {'session_id': 'w1-new', 'op': 'combo_time'}})
    rig = Rig(store)
    assert rig.tick() == {}
    store.put('job', 'mine', store.get('job', 'mine') | {'state': 'succeeded'})
    assert rig.tick()
    assert rig.jobs[-1]['input']['ops'] == [{'name': 'combo_freeze', 'op': 'combo_freeze', 'on': False},
                                           {'name': 'loadout', 'op': 'merc_loadout', 'reset': True, 'character': 'leon'}]


# --- end to end through the control plane ---

@pytest.fixture
def app(tmp_path):
    from gbox import server
    from gbox.config import Config
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    application = server.create_app(cfg)
    store = application.state.store
    store.put('worker', 'w1', {'id': 'w1', 'name': 'lilspark', 'os': 'linux', 'tools': ['re5_mods'],
                               'last_seen': time.time()})
    store.put('session', 'w1-live', {'session_id': 'w1-live', 'game_id': RE5, 'title': 'Resident Evil 5',
                                     'state': 'running', 'adapter': 'rpcs3', 'started': time.time() - 300})
    return cfg, application


def test_a_worker_result_for_an_operator_change_is_kept_and_shown_by_the_menu_route(app):
    cfg, application = app
    store = application.state.store
    with TestClient(application, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        submitted = client.post('/api/jobs', json={'tool': 're5_mods', 'agent_use': False, 'require_worker': 'w1',
                                                   'input': {'session_id': 'w1-live', 'op': 'bullet_damage',
                                                             'on': True, 'multiplier': 25}})
        assert submitted.status_code == 200, submitted.text
        jid = submitted.json()['id']
        store.put('job', jid, store.get('job', jid) | {'state': 'running', 'worker_id': 'w1', 'started': time.time()})
        done = client.post('/api/workers/w1/result', json={'job_id': jid, 'ok': True, 'output': {
            'result': {'op': 'bullet_damage', 'verified': True, 'bullet_damage_x': 25.0}}})
        assert done.status_code == 200, done.text
        prefs = client.get('/api/sessions/w1-live/game-prefs').json()
        assert prefs['panels']['re5_mods'] == {'bullet_damage': {'on': True, 'multiplier': 25.0}}
        assert prefs['applied']['re5_mods']['bullet_damage']['state'] == 'applied'
        assert prefs['receives'] == {'re5_mods': True}
        slot = client.put(f'/api/game-prefs/{RE5}/pip', json={'settings': {'save_slot': 4}})
        assert slot.status_code == 200 and slot.json()['panels']['pip'] == {'save_slot': 4}
        assert client.put(f'/api/game-prefs/{RE5}/pip', json={'settings': {'save_slot': 12}}).status_code == 422
        assert client.put(f'/api/game-prefs/{RE5}/re5_mods', json={'settings': {'x': 1}}).status_code == 422
        forgot = client.delete(f'/api/game-prefs/{RE5}', params={'panel': 're5_mods', 'name': 'bullet_damage'})
        assert forgot.json()['panels'] == {'pip': {'save_slot': 4}}
        assert client.get('/api/game-prefs').json()[0]['key'] == RE5
