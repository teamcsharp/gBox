"""F5 keeps the autobot driving, F3 starts it from any PC (gbox/bot_control.py). Synthetic workers: no game.

Operator 2026-10-26: "When i reload the stream via F5 because the bot got stuck or the stream freezes, bring it back up
with the bot active and in control." / "Allow me to start the Autobot on any game session by pressing the F3 key, even if
I'm on a different computer using G Box."
"""
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gbox import bot_control as B, screensaver as S
from gbox.models import Job
from gbox.store import Store

SID = 'w1-launch'


@pytest.fixture(autouse=True)
def clean_telemetry():
    S.TELEMETRY.clear()
    yield
    S.TELEMETRY.clear()


def make_store(tmp_path, *, game='re5', adapter='rpcs3', online=True):
    store = Store(tmp_path / 'data')
    store.put('worker', 'w1', {'id': 'w1', 'name': 'lilspark', 'os': 'linux', 'tools': ['autoplay', 're5_mods'],
                               'last_seen': time.time() if online else 0})
    store.put('session', SID, {'session_id': SID, 'game_id': game, 'title': 'Resident Evil 5', 'state': 'running',
                               'adapter': adapter, 'started': time.time() - 600})
    return store


def control(store, *, op='start', state='succeeded', actor='operator', agent_use=False, ident='start', at=10.0,
            sid=SID, **extra):
    store.put('job', ident, {'id': ident, 'tool': 'autoplay', 'state': state, 'created': at, 'actor': actor,
                             'agent_use': agent_use, 'input': {'session_id': sid, 'op': op, **extra}})


def telemetry(running=True, age=1.0, **extra):
    S.TELEMETRY[SID] = {'running': running, 'mode': 'playbook', 'stats': {}, 'at': time.time() - age, **extra}


class Rig:
    """BotControl over a real store with a scripted worker: every submitted job finishes at once (or stays queued)."""

    def __init__(self, store, answer=None, queued=False):
        self.store, self.jobs, self.clock = store, [], time.time()     # telemetry ages are wall-clock ages
        self.answer = answer or (lambda tool, inp: {'result': {'running': False}} if inp.get('op') == 'status'
                                 else {'result': {'started': 'playbook: mercs_bot', 'mode': 'playbook'}})
        self.queued = queued
        self.forced = []
        self.ctl = B.BotControl(store, submit=self.submit, workers=self.workers, wid=lambda w: w,
                                saver=None, prefs=self, clock=lambda: self.clock, sleep=self.sleep,
                                spawn=lambda fn: fn())

    def force(self, sid):
        self.forced.append(sid)

    def sleep(self, s):
        self.clock += s

    def workers(self):
        return [w | {'online': time.time() - w['last_seen'] < 30} for w in self.store.all('worker')]

    def submit(self, req, actor, origin):
        job = Job(tool=req.tool, input=req.input, require_worker=req.require_worker, agent_use=req.agent_use,
                  actor=actor, origin=origin or {})
        rec = job.model_dump(mode='json')
        self.jobs.append(rec)
        if not self.queued:
            try:
                rec |= {'state': 'succeeded', 'output': self.answer(req.tool, req.input)}
            except HTTPException as exc:
                rec |= {'state': 'failed', 'error': exc.detail}
        self.store.put('job', job.id, rec)
        return job

    def ops(self):
        return [(j['tool'], j['input'].get('op'), j['actor'], j['agent_use']) for j in self.jobs]

    def finished(self, job):
        return self.store.get('job', job['id'])


# --- who may get a bot back ---

def test_operators_own_game_without_a_bot_is_never_given_one(tmp_path):
    store = make_store(tmp_path)
    decision = B.intent(store, SID, {})
    assert decision['kind'] is None and 'leaves your game' in decision['reason']
    rig = Rig(store)
    out = rig.finished(rig.ctl.ensure(SID, 'operator'))
    assert out['state'] == 'succeeded' and out['output']['action'] == 'none'
    assert rig.jobs == [], 'no status, no start: the operator keeps their own game'
    assert rig.forced == [SID], 'F5 still re-applies the saved menu settings'


def test_a_bot_started_and_never_stopped_comes_back_with_its_settings(tmp_path):
    store = make_store(tmp_path)
    control(store, mode='replay', reset=True, continuous=True, style={'pace': 1.2}, screensaver=True, assist=True)
    d = B.intent(store, SID, {})
    assert d['kind'] == 'autoplay' and d['actor'] == 'operator' and d['agent_use'] is False
    assert d['start'] == {'session_id': SID, 'op': 'start', 'mode': 'replay', 'reset': False, 'continuous': True,
                          'style': {'pace': 1.2}, 'assist': True}, 'never a reset, never screensaver mode'


@pytest.mark.parametrize('why', ['stop', 'takeover', 'telemetry_takeover'])
def test_a_stop_or_a_controller_takeover_keeps_the_bot_off(tmp_path, why):
    store = make_store(tmp_path)
    control(store, continuous=True)
    if why == 'stop':
        control(store, op='stop', ident='stop', at=20)
    elif why == 'takeover':
        store.put('autoplay_handoff', SID, {'source_job_id': 'start', 'at': 30})
    t = {'running': True, 'age_s': 40, 'autoplay_taken_over': True} if why == 'telemetry_takeover' else {}
    assert B.intent(store, SID, t)['kind'] is None


def test_bot_demo_restarts_as_a_demo_and_owns_the_keyboard_on_a_bot_pc(tmp_path):
    store = make_store(tmp_path)
    S.autoplay_on_launch(store, 'launch', 'game', actor='operator', agent=False)
    d = B.intent(store, SID, {}, bot_pcs=['lilspark'], worker_name='lilspark')
    assert d['kind'] == 'bot_demo' and d['actor'] == S.DEMO_ACTOR and d['agent_use'] is False
    assert d['start'] == {'session_id': SID, 'op': 'start', 'mode': 'auto', 'demo': True, 'owns_keyboard': True}
    control(store, continuous=True, mode='learned', style={'pace': 2})          # F3 later started it as a plain start
    d = B.intent(store, SID, {}, bot_pcs=[], worker_name='lilspark')
    assert d['start'] == {'session_id': SID, 'op': 'start', 'mode': 'learned', 'continuous': True, 'style': {'pace': 2},
                          'reset': False, 'demo': True}, 'still a bot demo: polite input'


def test_a_bot_started_on_the_pad_after_an_old_stop_still_counts(tmp_path):
    store = make_store(tmp_path)
    control(store, op='stop', ident='stop', at=time.time() - 600)
    store.put('job', 'stop', store.get('job', 'stop') | {'finished': time.time() - 590})
    assert B.intent(store, SID, {'running': True, 'age_s': 30})['kind'] == 'telemetry'
    store.put('job', 'stop', store.get('job', 'stop') | {'finished': time.time() - 35})
    assert B.intent(store, SID, {'running': True, 'age_s': 30})['kind'] is None, 'its last report around the Stop'


def test_mercmode_run_is_restarted_by_its_scheduler_and_waits_while_it_starts(tmp_path):
    store = make_store(tmp_path)
    run = {'worker': 'lilspark', 'worker_id': 'w1', 'session_id': SID, 'phase': 'playing', 'game_id': 're5',
           'mercmode': {'title': 're5'}}
    assert B.intent(store, SID, {}, runs=[run])['kind'] == 'mercmode'
    starting = B.intent(store, SID, {}, runs=[run | {'phase': 'starting'}])
    assert starting['kind'] is None and starting['pending']
    assert B.intent(store, SID, {}, runs=[run | {'mercmode_rotate_requested': True}])['pending']
    store.put('slabel', SID, {'session_id': SID, 'owner': 'agent', 'warm': True})
    assert B.intent(store, SID, {}, runs=[run])['kind'] is None, 'a parked warm game never gets a bot'


def test_a_bot_from_the_pad_chord_counts_and_an_agent_session_keeps_its_owner(tmp_path):
    store = make_store(tmp_path)
    assert B.intent(store, SID, {'running': True, 'age_s': 50})['kind'] == 'telemetry'
    store.put('slabel', SID, {'session_id': SID, 'owner': 'agent'})
    control(store, actor='hermes', agent_use=True)
    d = B.intent(store, SID, {})
    assert (d['kind'], d['actor'], d['agent_use']) == ('autoplay', 'hermes', True)


def test_relaunch_in_flight_and_start_on_its_way_are_left_alone(tmp_path):
    store = make_store(tmp_path)
    control(store, continuous=True)
    store.put('job', 'reset', {'id': 'reset', 'tool': 'session_reset', 'state': 'running',
                               'input': {'session_id': SID, 'mode': 'restart'}})
    assert B.intent(store, SID, {})['pending']
    store.delete('job', 'reset')
    control(store, state='queued', ident='again', at=time.time())
    assert B.intent(store, SID, {})['pending']


def test_liveness_thresholds():
    assert B.liveness({}) == 'unknown'
    assert B.liveness({'running': True, 'age_s': 3}) == 'driving'
    assert B.liveness({'running': True, 'age_s': 17}) == 'unknown'
    assert B.liveness({'running': True, 'age_s': 25}) == 'stuck'
    assert B.liveness({'running': True, 'age_s': 2, 'stats': {'hung': True}}) == 'stuck'
    assert B.liveness({'running': False, 'age_s': 2}) == 'stopped'


# --- F5 ---

def test_f5_leaves_a_driving_bot_alone(tmp_path):
    store = make_store(tmp_path)
    control(store, continuous=True)
    telemetry(age=2)
    rig = Rig(store)
    out = rig.finished(rig.ctl.ensure(SID, 'operator'))
    assert out['output']['action'] == 'driving' and rig.jobs == []
    assert out['output']['message'].startswith('The autobot is driving Resident Evil 5')


def test_f5_starts_a_bot_that_stopped_as_the_operator(tmp_path):
    store = make_store(tmp_path)
    control(store, continuous=True, mode='auto')
    telemetry(running=False, age=4)
    rig = Rig(store)
    out = rig.finished(rig.ctl.ensure(SID, 'operator'))
    assert out['state'] == 'succeeded', out
    assert out['output']['action'] == 'started' and 'back in control' in out['output']['message']
    assert rig.ops() == [('autoplay', 'status', 'operator', False), ('autoplay', 'start', 'operator', False)]
    start = rig.jobs[-1]
    assert start['input']['continuous'] is True and start['require_worker'] == 'w1'
    assert start['origin']['via'] == 'F5 recovery' and start['origin']['requested_by'] == 'operator'


def test_f5_restarts_a_bot_whose_telemetry_went_stale(tmp_path):
    store = make_store(tmp_path)
    control(store, continuous=True)
    telemetry(age=60)                                 # still "running" a minute ago: stuck
    reads = iter([True, False])                       # status: running, then stopped after our stop

    def answer(tool, inp):
        if inp['op'] == 'status':
            return {'result': {'running': next(reads)}}
        return {'result': {'stopped': True} if inp['op'] == 'stop' else {'started': 'playbook: mercs_bot'}}
    rig = Rig(store, answer)
    out = rig.finished(rig.ctl.ensure(SID, 'operator'))
    assert out['output']['action'] == 'restarted', out
    assert [op for _, op, _, _ in rig.ops()] == ['status', 'stop', 'status', 'start']
    assert 'restarted it' in out['output']['message']


def test_f5_on_a_stale_mercmode_bot_restarts_it_through_the_scheduler(tmp_path):
    store = make_store(tmp_path)
    run = {'worker': 'lilspark', 'worker_id': 'w1', 'session_id': SID, 'phase': 'playing', 'game_id': 're5',
           'title': 'Resident Evil 5', 'started': 1, 'autoplay_job': 'old', 'knobs': {'pace': 1.0},
           'mercmode': {'title': 're5'}}
    store.put(S.STATE, 'lilspark', run)
    control(store, actor=S.ACTOR, agent_use=True, ident='old', screensaver=True)
    telemetry(age=90)
    reads = iter([True, False])

    def answer(tool, inp):
        if inp['op'] == 'status':
            return {'result': {'running': next(reads)}}
        return {'result': {'stopped': True} if inp['op'] == 'stop' else {'started': 'playbook: mercs_bot'}}
    rig = Rig(store, answer)
    saver = S.Screensaver(store, None, lambda req, actor, origin: rig.submit(req, actor, origin), rig.workers)
    rig.ctl.saver = saver
    out = rig.finished(rig.ctl.ensure(SID, 'operator'))
    assert out['output']['action'] == 'restarted', out
    stop, start = rig.jobs[1], rig.jobs[-1]
    assert (stop['actor'], stop['agent_use'], stop['input']['op']) == (S.ACTOR, True, 'stop')
    assert (start['actor'], start['agent_use']) == (S.ACTOR, True), 'MercMode keeps owning its run'
    assert start['input'] == {'session_id': SID, 'op': 'start', 'mode': 'auto', 'screensaver': True,
                              'style': {'pace': 1.0}}
    assert store.get(S.STATE, 'lilspark')['autoplay_job'] == start['id']
    assert start['origin']['requested_by'] == 'operator'


def test_f5_follows_a_relaunched_session_to_the_game_running_now(tmp_path):
    store = make_store(tmp_path)
    store.put('session', 'w1-old', {'session_id': 'w1-old', 'game_id': 're5', 'state': 'ended', 'replaced_by': SID})
    control(store, continuous=True)
    rig = Rig(store)
    out = rig.finished(rig.ctl.ensure('w1-old', 'operator'))
    assert out['input']['session_id'] == SID and out['output']['action'] == 'started'
    store.put('session', 'w1-other', {'session_id': 'w1-other', 'game_id': 're4', 'state': 'ended',
                                      'replaced_by': SID})
    assert B.follow(store, 'w1-other')[0] == 'w1-other', 'never a different game without a MercMode receipt'


def test_f5_twice_joins_the_request_in_flight(tmp_path):
    store = make_store(tmp_path)
    control(store, continuous=True)
    rig = Rig(store)
    rig.ctl.spawn = lambda fn: None                    # the first request is still running
    first = rig.ctl.ensure(SID, 'operator')
    assert rig.ctl.ensure(SID, 'operator')['id'] == first['id']


def test_a_stop_that_lands_while_f5_works_wins(tmp_path):
    store = make_store(tmp_path)
    control(store, continuous=True)
    telemetry(running=False, age=3)

    def answer(tool, inp):
        if inp['op'] == 'status':
            control(store, op='stop', ident='operator-stop', at=50)     # the operator pressed Stop meanwhile
            return {'result': {'running': False}}
        pytest.fail('no start after a Stop')
    rig = Rig(store, answer)
    out = rig.finished(rig.ctl.ensure(SID, 'operator'))
    assert out['output']['action'] == 'none' and 'stays off' in out['output']['reason']


# --- F3 ---

def test_f3_starts_continuous_autoplay_on_the_shown_session_as_the_operator(tmp_path):
    store = make_store(tmp_path)
    rig = Rig(store)
    out = rig.finished(rig.ctl.toggle(SID, B.ToggleIn(), 'operator', {'client': 'desktop'}))
    assert out['state'] == 'succeeded' and out['actor'] == 'operator'
    assert rig.ops() == [('autoplay', 'status', 'operator', False), ('autoplay', 'start', 'operator', False)]
    assert rig.jobs[-1]['input'] == {'session_id': SID, 'op': 'start', 'mode': 'auto', 'continuous': True,
                                     'assist': False}
    assert all(j['require_worker'] == 'w1' for j in rig.jobs), 'sent to the PC that runs the game'
    assert out['output']['message'] == 'Autobot started on Resident Evil 5 (lilspark): playbook: mercs_bot.'


def test_f3_on_a_running_bot_hands_control_back(tmp_path):
    store = make_store(tmp_path)
    rig = Rig(store, lambda tool, inp: {'result': {'running': True}} if inp['op'] == 'status'
              else {'result': {'stopped': True}})
    out = rig.finished(rig.ctl.toggle(SID, B.ToggleIn(), 'operator'))
    assert [op for _, op, _, _ in rig.ops()] == ['status', 'stop']
    assert out['output']['action'] == 'stopped' and out['output']['message'].startswith('Autobot stopped')
    start = rig.finished(rig.ctl.toggle(SID, B.ToggleIn(op='start'), 'operator'))
    assert start['output']['action'] == 'already_running'


def test_f3_errors_are_words_the_operator_can_act_on(tmp_path):
    store = make_store(tmp_path, online=False)
    rig = Rig(store)
    with pytest.raises(HTTPException) as offline:
        rig.ctl.toggle(SID, B.ToggleIn(), 'operator')
    assert offline.value.status_code == 409 and 'lilspark' in offline.value.detail and 'offline' in offline.value.detail
    store.put('worker', 'w1', store.get('worker', 'w1') | {'last_seen': time.time()})
    busy = Rig(store, queued=True)
    out = busy.finished(busy.ctl.toggle(SID, B.ToggleIn(), 'operator'))
    assert out['state'] == 'failed' and 'did not answer' in out['error'] and 'Nothing was changed' in out['error']
    refused = Rig(store, lambda tool, inp: {'result': {'running': False}} if inp['op'] == 'status'
                  else {'result': {'error': 'no playbook plays this game here'}})
    out = refused.finished(refused.ctl.toggle(SID, B.ToggleIn(), 'operator'))
    assert out['state'] == 'failed' and 'no playbook' in out['error']
    store.put('session', SID, store.get('session', SID) | {'state': 'ended'})
    with pytest.raises(HTTPException, match='has ended'):
        rig.ctl.toggle(SID, B.ToggleIn(), 'operator')


def test_f3_never_lets_automation_drive_the_operators_game_or_a_parked_one(tmp_path):
    store = make_store(tmp_path)
    rig = Rig(store)
    with pytest.raises(HTTPException, match="operator's session"):
        rig.ctl.toggle(SID, B.ToggleIn(), 'hermes', automated=True)
    store.put('slabel', SID, {'session_id': SID, 'owner': 'agent'})
    assert rig.finished(rig.ctl.toggle(SID, B.ToggleIn(), 'hermes', automated=True))['state'] == 'succeeded'
    store.put('slabel', SID, {'session_id': SID, 'owner': 'agent', 'warm': True})
    with pytest.raises(HTTPException, match='waits paused'):
        rig.ctl.toggle(SID, B.ToggleIn(), 'operator')


# --- routes: the desktop's requests are the operator's ---

@pytest.fixture
def app(tmp_path):
    from gbox import server
    from gbox.config import Config
    cfg = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    application = server.create_app(cfg)
    store = application.state.store
    store.put('worker', 'w1', {'id': 'w1', 'name': 'i9-NUC', 'os': 'windows', 'tools': ['autoplay'],
                               'last_seen': time.time()})
    store.put('session', SID, {'session_id': SID, 'game_id': 're4', 'title': 'Resident Evil 4', 'state': 'running',
                               'adapter': 'dolphin', 'started': time.time() - 300})
    return cfg, application


def test_the_routes_record_the_operator_and_refuse_automation(app):
    cfg, application = app
    ctl = application.state.bot_control
    ctl.spawn = lambda fn: None                         # no worker here: check the request record and guards only
    with TestClient(application, headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        toggle = client.post(f'/api/sessions/{SID}/autoplay', json={'op': 'toggle', 'source': 'F3'})
        assert toggle.status_code == 200, toggle.text
        job = toggle.json()
        assert (job['tool'], job['state'], job['actor']) == ('autoplay_toggle', 'running', 'operator')
        assert job['input'] == {'session_id': SID, 'game_id': 're4', 'op': 'toggle', 'source': 'F3'}
        assert client.get('/api/jobs/' + job['id']).json()['state'] == 'running', 'not retired as an orphan'
        hermes = client.post(f'/api/sessions/{SID}/autoplay', json={'op': 'start'}, headers={'x-gbox-actor': 'hermes'})
        assert hermes.status_code == 409
        ensure = client.post(f'/api/sessions/{SID}/autoplay/ensure', json={'reason': 'F5'})
        assert ensure.status_code == 200 and ensure.json()['output']['action'] == 'none'
        assert client.post(f'/api/sessions/{SID}/autoplay/ensure', json={},
                           headers={'x-gbox-actor': 'agent'}).status_code == 409
        assert client.post('/api/sessions/nope-x/autoplay', json={}).status_code == 404
