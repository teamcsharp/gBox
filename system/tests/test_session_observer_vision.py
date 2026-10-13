"""#1374: the passive observer keeps vision replies whose list items are objects, not strings."""
import io
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from gbox import session_observers as module
from gbox.config import Config
from gbox.session_observers import SessionObservers, analyze, parse_observation
from gbox.store import Store

# qwen2.5vl:7b's verbatim reply for a Def Jam Vendetta (GDTE69 rev 0) attract frame, artifact
# 9d93f1f2878d2251262eb6d0f78b494507de4f5e5f06ff570497d9a6ac8e6d01, on agent session 706fd7cb46f34f55-30eab9c8dd7640b4. The pre-#1374
# parser rejected it as "Vision model returned invalid actors", as on operator session
# 9c93c9ba1ab84eb1-dd80e5910e5a4169.
DEF_JAM_REPLY = '```json\n{\n  "summary": "A character is performing a breakdancing move, possibly a handstand or a similar pose, in a dance battle setting. Another character is observing or reacting to the move.",\n  "actors": [\n    {\n      "name": "Dancer",\n      "role": "Executing a breakdancing move"\n    },\n    {\n      "name": "Observer",\n      "role": "Watching the dancer\'s move"\n    }\n  ],\n  "changes": [\n    "The scene has transitioned from a title screen to an in-game action scene."\n  ],\n  "hud": [\n    "No HUD elements are visible in this screenshot."\n  ],\n  "mechanics_hypotheses": [\n    "The game likely involves breakdancing or dance battles, as suggested by the character\'s pose and the setting."\n  ],\n  "uncertainties": [\n    "The specific mechanics of the game, such as how the dance moves are executed or judged, are not discernible from this screenshot."\n  ]\n}\n```'
DEF_JAM_ACTORS = ['Dancer (Executing a breakdancing move)', "Observer (Watching the dancer's move)"]


def client(content, sent):
    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def post(self, url, **kwargs):
            sent.append(kwargs['json'])
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {'choices': [{'message': {'content': content}}]})
    return Client


def png():
    out = io.BytesIO()
    Image.new('RGB', (40, 40), 'red').save(out, 'PNG')
    return out.getvalue()


def test_real_def_jam_reply_with_object_actors_is_kept(monkeypatch):
    sent = []
    monkeypatch.setattr(module.httpx, 'Client', client(DEF_JAM_REPLY, sent))
    result = analyze(Config(), png(), None)
    assert result['actors'] == DEF_JAM_ACTORS
    assert result['summary'].startswith('A character is performing a breakdancing move')
    assert 'actors' in result['normalized_fields'] and result['model'] == 'qwen2.5vl:7b'
    prompt = sent[0]['messages'][0]['content'][0]['text']
    assert 'never an object' in prompt and 'tools' not in sent[0]


def test_observer_records_object_actor_reply_without_a_repair_request(monkeypatch, tmp_path):
    monkeypatch.setattr(module.httpx, 'Client', client(DEF_JAM_REPLY, []))
    store = Store(tmp_path)
    session = {'session_id': 'worker-launch', 'game_id': '8b37766f557e1f5f',
               'title': 'Def Jam - Vendetta (USA)', 'state': 'running', 'last_frame_age': 1}
    store.put('session', session['session_id'], session)
    posted = []
    def api(path, body=None, *, binary=False):
        if binary and path.endswith('/frame.jpg'):
            return png()
        posted.append(path)
        raise AssertionError(path)
    observers = SessionObservers(store, Config(data_dir=tmp_path), api, clock=lambda: 1000)
    try:
        observers.sample(session)
    finally:
        observers.close()
    row = store.get('session_observer', 'worker-launch')
    assert row['gameplay_state'] == 'watching' and row['failures'] == 0 and row['error'] is None
    assert row['latest']['actors'] == DEF_JAM_ACTORS and row['samples'] == 1
    assert posted == [] and not store.all('request')


def test_object_mapping_and_scalar_fields_become_text():
    raw = json.dumps({
        'summary': 'Two fighters face each other in a club.',
        'actors': [{'name': 'Fighter in white tank top', 'role': 'player 1'},
                   {'name': 'Fighter in red jacket', 'role': 'opponent', 'position': 'right'}],
        'changes': {'arena': 'appeared after the black loading screen'},
        'hud': [{'label': 'P1 health', 'value': 'full'}, {'label': 'Timer', 'value': 99}],
        'mechanics_hypotheses': 'Health bars drain when hit',
        'uncertainties': None})
    assert parse_observation('Observation:\n```json\n' + raw + '\n```\nDone.') == {
        'summary': 'Two fighters face each other in a club.',
        'actors': ['Fighter in white tank top (player 1)', 'Fighter in red jacket (opponent): position: right'],
        'changes': ['arena: appeared after the black loading screen'],
        'hud': ['P1 health: full', 'Timer: 99'],
        'mechanics_hypotheses': ['Health bars drain when hit'],
        'uncertainties': [],
        'normalized_fields': ['actors', 'changes', 'hud', 'mechanics_hypotheses']}


def test_plain_string_lists_are_unchanged_and_bounded():
    result = parse_observation(json.dumps({'summary': 'Title screen', 'hud': ['PRESS START'],
                                           'actors': ['a' * 600] + [f'x{i}' for i in range(30)]}))
    assert result['actors'][0] == 'a' * 500 and len(result['actors']) == 20
    assert result['hud'] == ['PRESS START'] and 'normalized_fields' not in result


@pytest.mark.parametrize('raw, message', [
    ('no json here', 'no JSON observation'),
    ('{"summary": "s", "actors": [', 'malformed JSON'),
    ('{"actors": ["a"]}', 'no usable observation'),
    ('{"summary": "   "}', 'no usable observation'),
    ('[1, 2]', 'no usable observation'),
])
def test_unusable_replies_still_fail(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_observation(raw)


def test_def_jam_ring_crowd_and_hud_shapes_are_kept():
    """#1374 follow-up: the fight frames of Def Jam Vendetta (two fighters in a ring, a crowd, health/momentum HUD)
    draw other small-model shapes than the attract frame: a crowd count, booleans, nested HUD maps. None of them may
    discard an observation that has a summary (that is what filed the "invalid actors" repair)."""
    raw = json.dumps({
        'summary': 'Two fighters trade blows in a ring surrounded by a cheering crowd.',
        'actors': {'player': {'name': 'Fighter in white tank top', 'role': 'player 1', 'health': 0.8},
                   'opponent': {'name': 'Fighter in red jacket', 'role': 'CPU'}, 'crowd': 40, 'referee': False},
        'changes': False,
        'hud': {'health_bars': [0.8, 0.45], 'momentum': 'BLAZIN', 'timer': None},
        'mechanics_hypotheses': True,
        'uncertainties': ['crowd size is an estimate']})
    r = parse_observation(raw)
    assert r['summary'].startswith('Two fighters')
    assert r['actors'] == ['player: Fighter in white tank top (player 1): health: 0.8',
                           'opponent: Fighter in red jacket (CPU)', 'crowd: 40', 'referee: false']
    assert r['changes'] == [] and r['mechanics_hypotheses'] == []
    assert r['hud'] == ['health_bars: 0.8, 0.45', 'momentum: BLAZIN', 'timer']
    assert r['normalized_fields'] == ['actors', 'changes', 'hud', 'mechanics_hypotheses']
    assert parse_observation('{"summary": "Empty ring", "actors": true}')['actors'] == []
