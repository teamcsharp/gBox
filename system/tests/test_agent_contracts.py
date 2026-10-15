import copy
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from gbox.agent import Agent, ChatHub
from gbox.agent_contracts import native_swap_outcome, resolve_read_session
from gbox.characters import CharIn
from gbox.tools import CheatIn


@pytest.mark.parametrize('name', ['pso_face', 'gta3_items', 'auf_live', 'game_live_controls'])
def test_native_face_and_inventory_jobs_stay_on_the_session_worker(name):
    agent = object.__new__(Agent)
    agent._live_session = lambda _: None
    sent = []
    agent.api = SimpleNamespace(post=lambda path, json: (
        sent.append((path, json)) or SimpleNamespace(json=lambda: {'state': 'succeeded'})))
    op = 'inspect' if name in ('auf_live', 'game_live_controls') else 'list'
    agent._job(name, {'session_id': 'worker-session', 'op': op})
    assert sent == [('/api/jobs', {'tool': name, 'input': {'session_id': 'worker-session', 'op': op}, 'require_worker': 'worker'})]


@pytest.mark.parametrize('name,op', [('auf_live', 'noclip'), ('game_live_controls', 'apply')])
def test_live_mod_requests_get_short_deadlines_without_extending_expired_commands(name, op):
    import time
    agent = object.__new__(Agent)
    agent._live_session = lambda _: None
    sent = []
    agent.api = SimpleNamespace(post=lambda path, json: (
        sent.append(json) or SimpleNamespace(json=lambda: {'state': 'succeeded'})))
    before = time.time()
    original = {'session_id': 'worker-session', 'op': op}
    agent._job(name, original)
    assert before < sent[0]['input']['expires'] <= time.time() + 15
    assert len(sent[0]['input']['command_id']) >= 16
    assert 'expires' not in original
    agent._job(name, original | {'command_id': 'original-command', 'expires': 1})
    assert sent[1]['input']['expires'] == 1
    assert sent[1]['input']['command_id'] == 'original-command'


def test_missing_character_is_rejected_before_any_job_or_session_lookup():
    agent = object.__new__(Agent)
    agent._job = agent._live_session = lambda *_a, **_k: pytest.fail('no dispatch expected')
    with pytest.raises(ValueError, match='requires character'):
        agent.characters(op='use', session_id='live', x=.5, y=.52)


@pytest.mark.parametrize('op', ['use', 'live_use', 'overlay', 'place'])
def test_generic_character_tool_requires_the_requested_name(op):
    with pytest.raises(ValidationError, match='requires character'):
        CharIn.model_validate({'op': op, 'session_id': 'live', 'character': ' '})
    inp = CharIn.model_validate({'op': op, 'session_id': 'live', 'character': 'aya_tshirt_jeans'})
    assert inp.character == 'aya_tshirt_jeans'


@pytest.mark.parametrize('op', ['list', 'get', 'collect', 'extract', 'add', 'blender', 'environments',
                               'coverage', 'unplace', 'swap', 'match', 'mgs_vr_decode'])
def test_other_character_operations_keep_their_existing_optional_name_contract(op):
    inp = CharIn.model_validate({'op': op, 'game_id': 'game',
                                'pairs': [{'character': 'Aya', 'slot': 'Kokiri boy'}]})
    assert inp.character == '' and inp.op == op


@pytest.mark.parametrize('tool_name,raw', [('characters', {'op': 'use', 'session_id': 'live'}),
                                       ('cheats', {'op': 'enable', 'session_id': 'live',
                                                   'codes': ['800E556C 1000']})])
def test_generic_worker_rejects_bad_arguments_before_calling_the_tool(monkeypatch, tool_name, raw):
    from gbox.registry import Ctx, REGISTRY, execute
    registered = REGISTRY[tool_name]
    monkeypatch.setattr(registered, 'fn', lambda *_: pytest.fail('tool body must not run'))
    monkeypatch.setattr(registered, 'unavailable_reason', lambda _: None)
    with pytest.raises(ValidationError):
        execute(tool_name, raw, Ctx(SimpleNamespace()))


@pytest.mark.parametrize('raw', [{'op': 'enable', 'codes': ['800E556C 1000']},
                                {'op': 'enable', 'index': -1}, {'op': 'disable', 'index': True},
                                {'op': 'enable', 'index': 0, 'codes': ['800E556C 1000']},
                                {'op': 'add'}, {'op': 'add', 'codes': ['   ']}])
def test_generic_cheat_tool_rejects_malformed_toggle_or_new_code(raw):
    with pytest.raises(ValidationError):
        CheatIn.model_validate({'session_id': 'live', **raw})


@pytest.mark.parametrize('raw', [{'op': 'enable', 'index': 0}, {'op': 'disable', 'index': 3},
                                {'op': 'add', 'codes': ['800E556C 1000']}, {'op': 'list'},
                                {'op': 'search', 'query': 'mission'}])
def test_generic_cheat_tool_preserves_valid_operations(raw):
    inp = CheatIn.model_validate({'session_id': 'live', **raw})
    assert inp.model_dump()['op'] == raw['op']
    if raw['op'] == 'add':
        assert inp.codes == ['800E556C 1000']


def test_generic_tool_schemas_explain_conditional_arguments_to_llms():
    assert 'Required for use' in CharIn.model_json_schema()['properties']['character']['description']
    props = CheatIn.model_json_schema()['properties']
    assert 'enable/disable' in props['index']['description']
    assert 'Add enables' in props['codes']['description']


def test_invalid_character_session_is_not_silently_changed_to_a_game_launch():
    agent = object.__new__(Agent)
    agent.context_game = 'some-game'
    agent._live_session = lambda _: {'error': 'copy the complete live session ID'}
    agent._job = lambda *_a, **_k: pytest.fail('do not launch a different target')
    assert agent.characters(op='use', character='aya_tshirt_jeans', session_id='short')['error']


def test_character_slug_is_preserved_and_overlay_does_not_claim_native_verification():
    agent = object.__new__(Agent)
    agent._live_session = lambda _: None
    dispatched = []
    def job(name, inp, **kw):
        dispatched.append((name, inp))
        return {'state': 'succeeded', 'output': {'result': {'status': 'overlay', 'verified': True}}}
    agent._job = job
    result = agent.characters(op='use', character='aya_tshirt_jeans', session_id='live', x=.5, y=.52)
    assert dispatched[0][1]['character'] == 'aya_tshirt_jeans'
    assert result['native_swap_verified'] is False
    assert 'pending' in result['next']


def test_character_caller_does_not_drop_failed_job_metadata_around_a_stale_result():
    agent = object.__new__(Agent)
    agent._live_session = lambda _: None
    agent._job = lambda *_a, **_k: {'state': 'failed', 'error': 'worker disconnected',
                                  'output': {'result': {'status': 'in_engine', 'verified': True}}}
    result = agent.characters(op='use', character='aya', session_id='live')
    assert result['native_swap_verified'] is False
    assert native_swap_outcome(native_events(result))['verified'] is False


def test_cheat_enable_with_code_lines_fails_with_correct_operation_before_dispatch():
    agent = object.__new__(Agent)
    with pytest.raises(ValueError, match='op=add'):
        agent.cheats('live', op='enable', codes=['800E556C 1000'])


@pytest.mark.parametrize('kwargs', [dict(op='enable', index=-1), dict(op='enable', index=True),
                                   dict(op='enable', index=0, codes=['800E556C 1000']),
                                   dict(op='add', codes=[]), dict(op='add', codes=[''])])
def test_invalid_cheat_calls_never_dispatch(kwargs):
    with pytest.raises(ValueError):
        object.__new__(Agent).cheats('live', **kwargs)


def test_valid_cheat_index_and_new_code_use_distinct_wire_operations():
    posted = []
    agent = object.__new__(Agent)
    def post(path, json):
        posted.append((path, json))
        return SimpleNamespace(json=lambda: {'state': 'succeeded', 'output': {'result': {'enabled': True}}})
    agent.api = SimpleNamespace(post=post)
    assert agent.cheats('worker-live', op='enable', index=0)['enabled']
    assert agent.cheats('worker-live', op='add', codes=['800E556C 1000'])['enabled']
    assert posted[0][1]['input']['op'] == 'enable' and posted[0][1]['input']['index'] == 0
    assert posted[1][1]['input']['op'] == 'add' and posted[1][1]['input']['codes'] == ['800E556C 1000']


def test_read_session_prefix_requires_unique_live_match_for_the_same_game():
    sessions = [{'session_id': 'worker-abcdef0123456789', 'game_id': 're5', 'state': 'running'},
                {'session_id': 'other-abcdef0123456789', 'game_id': 'mgs', 'state': 'running'}]
    assert resolve_read_session('worker-abc', 're5', sessions) == 'worker-abcdef0123456789'
    assert resolve_read_session('worker-abc', 'mgs', sessions) == 'worker-abc'
    assert resolve_read_session('worker-abc', '', sessions) == 'worker-abc'
    assert resolve_read_session('worker', 're5', sessions) == 'worker'
    sessions.append({'session_id': 'worker-abcdef9999999999', 'game_id': 're5', 'state': 'running'})
    assert resolve_read_session('worker-abc', 're5', sessions) == 'worker-abc'
    sessions[-1]['ended'] = 1
    assert resolve_read_session('worker-abc', 're5', sessions) == 'worker-abcdef0123456789'


def test_read_only_ram_study_dispatches_complete_sid_and_exact_game():
    sid = '0a226f781ccb4347-9d269fda4fbd48a7'
    sessions = [{'session_id': sid, 'game_id': 're5', 'state': 'running'}]
    agent = object.__new__(Agent)
    agent._re_gid = lambda _: 're5'
    agent.context_session_id = sid
    agent._live_session = lambda value: None if value == sid else {'error': 'wrong ID'}
    posts = []
    def get(path):
        return SimpleNamespace(json=lambda: sessions if path == '/api/sessions' else {})
    agent.api = SimpleNamespace(get=get, post=lambda *a, **kw: posts.append((a, kw)))
    dispatched = []
    def job(name, inp, **kw):
        dispatched.append((name, inp))
        return {'state': 'succeeded', 'output': {'elf_path': '/private/re5.elf', 'sha256': 'owned'}}
    agent._job = job
    agent.re_study('RE5', source='ram', session_id='0a226f781ccb4347-9d269fda4f8', analyze=False)
    assert dispatched == [('re_executable', {'game_id': 're5', 'source': 'ram', 'session_id': sid})]


def test_mistyped_short_read_id_requires_exact_live_context_binding():
    sessions = [{'session_id': 'worker-abcdef0123456789', 'game_id': 're5', 'state': 'running'}]
    wrong = 'worker-abc9'
    assert resolve_read_session(wrong, 're5', sessions) == wrong
    assert resolve_read_session(wrong, 're5', sessions, 'worker-abcdef0123456789') == 'worker-abcdef0123456789'
    assert resolve_read_session(wrong, 're5', sessions, 'other-abcdef0123456789') == wrong
    assert resolve_read_session(wrong, 'mgs', sessions, 'worker-abcdef0123456789') == wrong
    assert resolve_read_session('worker-abcdef9999999999', 're5', sessions, 'worker-abcdef0123456789') == 'worker-abcdef9999999999'
    with pytest.raises(ValueError, match='different game'):
        resolve_read_session('worker-abcdef0123456789', 'mgs', sessions)


def native_events(result, op='use'):
    return [{'type': 'tool_call', 'name': 'characters', 'args': {'op': op, 'character': 'aya'}},
            {'type': 'tool_result', 'name': 'characters', 'text': json.dumps(result)}]


@pytest.mark.parametrize('result', [{'status': 'overlay', 'verified': True},
                                  {'status': 'missing', 'overlay_error': 'session ended'},
                                  {'status': 'launched'}, {'state': 'queued'}, {'error': 'missing character'},
                                  {'state': 'failed', 'result': {'verified': True}},
                                  {'error': 'worker disconnected', 'result': {'verified': True}}])
def test_native_swap_requires_actual_native_verification(result):
    outcome = native_swap_outcome(native_events(result))
    assert outcome['required'] is True and outcome['verified'] is False


def test_native_retry_can_verify_but_overlay_retry_cannot_complete_rom_swap():
    failed = native_events({'status': 'missing'})
    assert native_swap_outcome(failed + native_events({'verified': True}, op='overlay'))['verified'] is False
    assert native_swap_outcome(failed + native_events({'status': 'in_engine', 'verified': True}))['verified'] is True


@pytest.mark.parametrize('result,expected', [({'status': 'overlay'}, 'in_progress'),
                                          ({'status': 'missing', 'overlay_error': 'ended'}, 'in_progress'),
                                          ({'status': 'launched'}, 'in_progress'),
                                          ({'status': 'in_engine', 'verified': True}, 'done')])
@pytest.mark.parametrize('reuse', [False, True])
def test_real_chat_hub_does_not_close_unverified_native_swap(result, expected, reuse):
    class Store:
        def __init__(self):
            self.chat = {'id': 'chat', 'events': [], 'messages': [], 'busy': True, 'model': None, 'queue': []}
        def get(self, kind, identifier):
            return copy.deepcopy(self.chat)
        def put(self, kind, identifier, value):
            self.chat = copy.deepcopy(value)
    class FakeAgent:
        def run(self, messages, emit, context):
            for event in native_events(result):
                emit(event)
            emit({'type': 'assistant', 'text': 'Here is the attempted result.'})
            return {'usage': {'in': 10, 'out': 4}, 'tools': {'characters': 1}}
    actions = []
    def api_requests(action, data):
        actions.append((action, data))
        return 'request'
    hub = ChatHub(Store(), lambda _: FakeAgent())
    hub._gap_report = lambda *_: None
    context = {'resolve_auto_report': True, 'request_id': 'original'} if reuse else {}
    hub._turn('chat', 'Replace fighter with Aya in the game', context, api_requests)
    statuses = [data for action, data in actions if action == 'status']
    if reuse and expected == 'done':
        assert not statuses  # a successful auto-attempt does not close its existing parent request
        return
    status = statuses[-1]
    assert status['status'] == expected
    if expected == 'in_progress':
        assert 'verif' in status['note'].lower()
