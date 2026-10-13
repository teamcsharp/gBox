"""Session agents say what they are trying to do, what they still need and how the operator can help.

Operator, 2026-10-13 (007 Agent Under Fire on Dolphin, panel showing only "waiting_for_frame"): "If the session
is analyzing the display for something, I need it to tell me what it's trying to do so that I can try to do it."
"""
import itertools

from fastapi.testclient import TestClient
import pytest

from gbox.config import Config
from gbox.server import create_app
from gbox.session_observers import STAGE_GOALS, SessionObservers, agent_goals
from gbox.store import Store

AUF = '007 Agent Under Fire'
KEYS = ('goal', 'doing', 'seeking', 'you_can_help', 'blocked_by')


def view(**fields):
    return {'session_id': 'w-1', 'game_id': 'auf', 'title': AUF, 'state': 'attached', 'enabled': True,
            'service_online': True, 'gameplay_state': 'watching', 'models': {'state': 'unsupported'}} | fields


def queue(stage, **fields):
    order = list(STAGE_GOALS)
    stages = {s: {'status': 'verified'} for s in order[:order.index(stage)]} if stage else \
        {s: {'status': 'verified'} for s in order}
    return {'game_id': 'auf', 'title': AUF, 'number': 41, 'request_id': 'r41', 'dispatch_state': 'queued',
            'stages': stages, 'next_stage': stage} | fields


def agents(result):
    return {a['agent']: a for a in result['agents']}


def test_auf_waiting_for_frame_without_a_reader_explains_every_agent():
    result = agent_goals(view(gameplay_state='waiting_for_frame', error='Waiting for a fresh game frame'), now=0)
    a = agents(result)
    assert list(a) == ['gameplay', 'models', 'hermes']
    assert AUF in a['gameplay']['goal'] and 'who is on screen' in a['gameplay']['goal']
    assert a['gameplay']['doing'].startswith('Waiting for a fresh frame from your game window')
    assert a['gameplay']['blocked_by'] == ''
    assert a['models']['blocked_by'].startswith(f'no native model reader for {AUF} yet')
    assert a['models']['you_can_help'] == 'Favorite this game so Hermes queues the reader work.'
    assert a['hermes']['state'] == 'not_queued'
    assert result['ask'] == {'agent': 'models', 'name': 'Model collector',
                             'text': 'Favorite this game so Hermes queues the reader work.'}


@pytest.mark.parametrize('stage', list(STAGE_GOALS))
def test_each_work_queue_stage_has_its_own_goal_seeking_and_help(stage):
    a = agents(agent_goals(view(), queue=queue(stage), now=0))
    hermes = a['hermes']
    assert hermes['stage'] == stage
    assert hermes['goal'] == STAGE_GOALS[stage]['goal'].format(title=AUF)
    assert hermes['seeking'].startswith(STAGE_GOALS[stage]['seeking'])
    assert hermes['stages_verified'] == list(STAGE_GOALS)[:list(STAGE_GOALS).index(stage)]
    wants_characters = stage in ('reader', 'writer', 'runtime')
    assert ('characters clearly visible' in a['gameplay']['seeking']) is wants_characters
    assert ('Done, look now' in a['gameplay']['you_can_help']) is wants_characters
    assert a['models']['you_can_help'].startswith('Nothing in-game; Hermes is working on it')
    if stage == 'runtime':
        assert 'inbox request #41' in hermes['you_can_help']


def test_reader_stage_asks_the_operator_to_put_a_character_on_screen():
    result = agent_goals(view(gameplay_state='waiting_for_frame'), queue=queue('reader'), now=0)
    assert result['ask']['agent'] == 'gameplay'
    assert result['ask']['text'].startswith('Stand still facing a character for a few seconds')


def test_writer_without_collection_characters_is_blocked_on_them():
    hermes = agents(agent_goals(view(), queue=queue('writer'), now=0))['hermes']
    assert hermes['blocked_by'] == f'no collection characters of {AUF} in the library yet, so its writer has no slot to fill'
    models = {'state': 'succeeded', 'result': {'status': 'complete', 'collected': 3, 'total': 3},
              'capabilities': {'operations': {'characters': {'in_collection': ['bond', 'griffin', 'zoe']}}}}
    assert agents(agent_goals(view(models=models), queue=queue('writer'), now=0))['hermes']['blocked_by'] == ''


def test_blocked_stage_retry_and_paused_dispatch_name_the_blocker():
    blocked = queue('analysis', stages={'inventory': {'status': 'verified'},
                                        'analysis': {'status': 'blocked', 'note': 'XBE loader is encrypted',
                                                     'next_step': 'dump the decrypted XBE'}})
    hermes = agents(agent_goals(view(), queue=blocked, now=0))['hermes']
    assert hermes['blocked_by'] == 'stage blocked: XBE loader is encrypted'
    assert hermes['seeking'].endswith('; next step: dump the decrypted XBE')
    later = agents(agent_goals(view(), queue=queue('reader', retry_at=1200), now=0))['hermes']
    assert later['blocked_by'] == 'waiting about 20 min before its next attempt'
    paused = agents(agent_goals(view(), queue=queue('reader', dispatch_state='paused'), now=0))['hermes']
    assert paused['blocked_by'] == 'Hermes task mode is off' and paused['doing'].startswith('Paused')


def test_all_stages_verified_is_done():
    hermes = agents(agent_goals(view(), queue=queue(None), now=0))['hermes']
    assert hermes['state'] == 'done' and hermes['seeking'] == 'nothing more'


def test_character_request_says_what_it_is_putting_in_and_what_blocks_it():
    request = {'id': 'r7', 'number': 7, 'title': 'Pick whip Bond onto the guard', 'status': 'open',
               'context': {'game_id': 'auf', 'character': 'Bond', 'target': 'the guard'}}
    result = agent_goals(view(), requests=[request], jobs=[{'id': 'j', 'tool': 'characters', 'input': {'op': 'collect'},
                                                            'state': 'running'}], now=0)
    hermes = agents(result)['hermes']
    assert hermes['requests'][0]['goal'] == f'put Bond into {AUF} in place of the guard'
    assert f'for inbox #7: put Bond into {AUF} in place of the guard and see it on screen' in hermes['seeking']
    assert f'no collection characters available for the {AUF} writer yet' in hermes['blocked_by']
    assert hermes['doing'] == 'Running now: characters collect.'
    assert 'characters clearly visible' in agents(result)['gameplay']['seeking']


GAMEPLAY = {
    'paused': (dict(enabled=False, state='paused'), 'you paused the observers', 'Resume observers'),
    'offline': (dict(state='offline'), 'the PC running this game is not connected to gBox', 'gBox worker'),
    'service': (dict(service_online=False, service_error='boom'), 'the observer service is not running on the gBox server: boom', ''),
    'no_window': (dict(gameplay_state='no_window'), 'the game window is closed or minimised', 'Reopen'),
    'covered': (dict(gameplay_state='covered'), 'the game window is covered by another window', 'front'),
    'backing_off': (dict(gameplay_state='backing_off', timeouts=3), 'vision model busy or not answering (3 timeouts in a row)', 'Done, look now'),
    'blocked': (dict(gameplay_state='blocked', failures=4, error='HTTP 500', observation_request_id='r9'),
                'capture or vision failed 4 times: HTTP 500 (repair tracked in inbox r9)', 'repairs'),
    'slow_capture': (dict(gameplay_state='waiting_for_frame', error='Capture job has not completed: j1'),
                     'the capture of your game window is slow: Capture job has not completed: j1', ''),
}


@pytest.mark.parametrize('case', list(GAMEPLAY))
def test_gameplay_observer_states_name_their_blocker(case):
    fields, blocked, helps = GAMEPLAY[case]
    gameplay = agents(agent_goals(view(**fields), now=0))['gameplay']
    assert gameplay['blocked_by'].startswith(blocked)
    assert helps in gameplay['you_can_help']


MODELS = {
    'not_started': ({'state': 'not_started'}, '', 'its first collection run'),
    'queued': ({'state': 'queued', 'job_id': 'j1'}, 'waiting for a Linux worker', 'a free Linux worker to run the collection'),
    'running': ({'state': 'running'}, '', 'the collection job to finish'),
    'failed': ({'state': 'failed', 'error': 'bad ISO'}, 'collection failed: bad ISO', 'a collection run that succeeds'),
    'partial': ({'state': 'succeeded', 'request_id': 'r3', 'result': {'status': 'partial', 'collected': 2, 'total': 4,
                 'entries': [{'name': 'Bond', 'verified': True}, {'name': 'Griffin'}, {'slug': 'zoe', 'verified': False}]}},
                'the reader cannot read them yet (repair tracked in inbox r3)',
                'the 2 roster characters it could not read yet: Griffin, zoe'),
    'done': ({'state': 'succeeded', 'result': {'status': 'complete', 'collected': 4, 'total': 4}}, '', 'nothing more'),
}


@pytest.mark.parametrize('case', list(MODELS))
def test_model_collector_states(case):
    models, blocked, seeking = MODELS[case]
    agent = agents(agent_goals(view(models=models), now=0))['models']
    assert agent['blocked_by'] == blocked and agent['seeking'] == seeking
    if case == 'failed':
        assert agent['you_can_help'] == 'Favorite the game again to retry the collection.' and agent['needs_you']


def test_every_agent_in_every_combination_has_plain_goal_fields():
    states = ['waiting_for_frame', 'analyzing', 'watching', 'unchanged', 'no_window', 'covered', 'stopped',
              'backing_off', 'blocked', None]
    stages = [None, *STAGE_GOALS, 'missing']
    for gs, stage, (models, _, _) in itertools.product(states, stages, MODELS.values()):
        q = None if stage == 'missing' else queue(stage)
        result = agent_goals(view(gameplay_state=gs, models=models), queue=q, now=0)
        for agent in result['agents']:
            assert all(isinstance(agent[k], str) for k in KEYS), agent
            assert agent['goal'] and agent['doing'], agent


@pytest.fixture
def app(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.put('session', 'w-1', {'session_id': 'w-1', 'state': 'running', 'game_id': 'auf', 'title': AUF})
    store.put('session_observer', 'w-1', {'session_id': 'w-1', 'game_id': 'auf', 'title': AUF, 'state': 'attached',
                                          'gameplay_state': 'unchanged', 'frame_digest': 'abc', 'next_sample': 9e9,
                                          'models': {'state': 'unsupported'}, 'models_checked': 5})
    store.put('request', 'r7', {'id': 'r7', 'number': 7, 'title': 'Pick whip Bond', 'status': 'open', 'image_b64': 'x' * 10,
                                'context': {'game_id': 'auf', 'character': 'Bond'}})
    store.put('request', 'r8', {'id': 'r8', 'number': 8, 'title': 'Done one', 'status': 'done', 'context': {'game_id': 'auf'}})
    store.put('request', 'r9', {'id': 'r9', 'number': 9, 'title': 'Other game', 'status': 'open', 'context': {'game_id': 'x'}})
    client = TestClient(app)
    client.headers['Authorization'] = 'Bearer ' + cfg.token()
    with client:
        yield app, client


def test_observer_route_returns_goals_and_open_requests_for_the_game(app):
    _, client = app
    data = client.get('/api/sessions/w-1/observers').json()
    hermes = next(a for a in data['goals']['agents'] if a['agent'] == 'hermes')
    assert [r['number'] for r in hermes['requests']] == [7]
    assert 'image_b64' not in str(data['goals'])
    assert data['goals']['agents'][0]['goal'].startswith(f'Look at {AUF}')


def test_look_now_schedules_an_immediate_fresh_sample(app):
    application, client = app
    assert client.post('/api/sessions/missing/observers/look').status_code == 404
    data = client.post('/api/sessions/w-1/observers/look').json()
    row = application.state.store.get('session_observer', 'w-1')
    assert row['look_requested'] and row['next_sample'] == 0 and row['frame_digest'] is None and row['models_checked'] == 0
    assert data['goals']['look_requested'] == row['look_requested']
    assert 'enabled' not in row and row['state'] == 'attached'   # look never pauses or resumes anything


def test_sample_after_look_analyzes_even_an_identical_frame_and_records_the_answer(tmp_path):
    from tests.test_session_observers import png
    store = Store(tmp_path)
    session = {'session_id': 'w-1', 'game_id': 'auf', 'title': AUF, 'state': 'running', 'last_frame_age': 1}
    store.put('session', 'w-1', session)
    seen = []
    o = SessionObservers(store, Config(data_dir=tmp_path), lambda path, body=None, binary=False: png(),
                         clock=lambda: 1000, observe=lambda *a: seen.append(1) or {'summary': 'Bond faces a guard'})
    try:
        o.sample(session)
        digest = store.get('session_observer', 'w-1')['frame_digest']
        o._put('w-1', look_requested=999, frame_digest=None)
        o.sample(session)
        row = store.get('session_observer', 'w-1')
        assert len(seen) == 2 and row['frame_digest'] == digest
        assert row['look_requested'] is None and row['last_look'] == {'requested': 999, 'answered': 1000}
    finally:
        o.close()


def test_game_requests_reads_only_unfinished_requests_for_the_game(tmp_path):
    store = Store(tmp_path)
    store.put('request', 'a', {'id': 'a', 'number': 1, 'title': 'A', 'status': 'open', 'context': {'game_id': 'g'}})
    store.put('request', 'b', {'id': 'b', 'number': 2, 'title': 'B', 'status': 'in_progress',
                               'context': {'hermes_favorite_game': 'g'}})
    store.put('request', 'c', {'id': 'c', 'number': 3, 'title': 'C', 'status': 'done', 'context': {'game_id': 'g'}})
    store.put('request', 'd', {'id': 'd', 'number': 4, 'title': 'D', 'status': 'open'})
    assert [r['id'] for r in store.game_requests('g')] == ['b', 'a']
