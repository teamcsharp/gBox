"""Exercise chat -> exact live target -> real job plan -> pending/verified lifecycle."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from gbox.agent import Agent, ChatHub
from gbox.live_research import investigate


SID, GID = 'worker-session', 'owned-game'
SESSION = {'session_id': SID, 'game_id': GID, 'title': 'SoulCalibur', 'mod': 'sonic-build',
           'worker_id': 'worker', 'state': 'running', 'adapter': 'retroarch'}


def make_agent(monkeypatch, sessions=None):
    agent = Agent('http://fixture', 'fixture', 'http://model', 'fixture', 'http://search')
    agent.api.close()
    requests = []
    def transport(req):
        requests.append((req.method, req.url.path))
        if req.url.path == '/api/sessions':
            data = sessions if sessions is not None else [SESSION]
        elif req.url.path == '/api/workers':
            data = [{'id': 'analysis-worker', 'os': 'linux', 'online': True, 'tools': ['re_executable', 'ghidra_bridge']}]
        elif req.url.path.endswith('/rpc'):
            data = {'game_id': GID, 'platform': 'dreamcast', 'core': 'flycast',
                    'runtime': {'running': True}, 'capabilities': {'read_memory': 'supported'}}
        elif req.url.path == '/api/recipes':
            data = []
        elif req.url.path.endswith('/live-controls'):
            data = {'profile': None}
        else:
            data = {}
        return httpx.Response(200, json=data)
    agent.api = httpx.Client(base_url='http://fixture', transport=httpx.MockTransport(transport))
    monkeypatch.setattr(agent, 'recall', lambda _: {'hits': []})
    monkeypatch.setattr(agent, '_learn', lambda *args: None)
    monkeypatch.setattr(agent, '_bookmark_state', lambda *args: None)
    return agent, requests


def context():
    return {'session_id': SID, 'game_id': GID, 'mod': 'sonic-build', 'worker_id': 'worker', 'live_edit': True}


def test_a_stale_request_never_retargets_the_other_game_on_its_worker(monkeypatch):
    agent, requests = make_agent(monkeypatch, [SESSION | {'session_id': 'worker-other', 'game_id': 'other'}])
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: pytest.fail('Model must not run against a substituted target'))
    with pytest.raises(ValueError, match='ended or changed'):
        agent.run([{'role': 'user', 'content': 'unlock all characters'}], lambda _: None, context())
    assert not any(path.endswith('/rpc') for _, path in requests)


def test_prose_only_completion_triggers_actual_research_once_and_stays_pending(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    researched = []
    def research(**args):
        researched.append(args)
        agent.live_researched = True
        return {'session_id': SID, 'error': 'No verified unlock routine yet'}
    monkeypatch.setattr(agent, 'live_research', research)
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: httpx.Response(200, json={
        'choices': [{'message': {'content': 'Everything is unlocked.'}}]}))
    events, ctx = [], context()
    messages = [{'role': 'user', 'content': 'unlock all characters and stages'}]
    agent.run(messages, events.append, ctx, max_steps=4)
    assert len(researched) == 1 and researched[0]['session_id'] == SID
    assert ('POST', f'/api/sessions/{SID}/rpc') in requests
    assert ctx['live_target']['mod'] == 'sonic-build'
    assert ctx['live_target']['platform'] == 'dreamcast'
    assert next(e for e in events if e['type'] == 'assistant')['text'].startswith('This live change is still in progress.')
    assert not any(e.get('phase') == 'completed' for e in events)
    assert not any('Everything is unlocked.' in str(m.get('content')) for m in messages)


def test_rpc_and_jobs_cannot_escape_the_attached_target(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    agent.live_target = {**context(), 'game_title': 'SoulCalibur'}
    with pytest.raises(ValueError, match='different live game'):
        agent._rpc('worker-other', 'read_memory', {})
    with pytest.raises(ValueError, match='another session'):
        agent._job('write_memory', {'session_id': 'worker-other', 'address': 0, 'hex_bytes': '01'})
    assert requests == []


@pytest.mark.parametrize('name,args', [
    ('cheats', {'session_id': 'worker-other', 'op': 'enable', 'index': 0}),
    ('launch_game', {'game_id': 'another-game'}),
    ('find_code_that_writes', {'session_id': 'worker-other', 'address': '0', 'label': 'health'}),
])
def test_direct_methods_and_recipe_steps_cannot_escape_the_target(monkeypatch, name, args):
    agent, requests = make_agent(monkeypatch)
    agent.live_target = {**context(), 'game_title': 'SoulCalibur'}
    with pytest.raises(ValueError, match='another session|restart or replace'):
        getattr(agent, name)(**args)
    with pytest.raises(ValueError, match='another session|restart or replace'):
        agent._run_recipe({'name': 'unsafe', 'steps': [{'tool': name, 'args': args}]}, {}, context())
    assert requests == []


def test_recipe_emits_native_step_evidence_in_the_current_turn(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    agent.live_target = {**context(), 'game_title': 'SoulCalibur'}
    events = []
    agent._live_emit = events.append
    agent.pso_mods = lambda **kw: {'verified': True, 'session_id': SID}
    result = agent._run_recipe({'name': 'native', 'steps': [{'tool': 'pso_mods',
        'args': {'session_id': '{session_id}', 'op': 'infinite_hp'}}]}, {}, context())
    assert result['steps'][0]['result']['verified'] is True
    assert [e['type'] for e in events] == ['tool_call', 'live_request', 'tool_result']
    assert events[0]['name'] == 'pso_mods' and events[0]['args']['session_id'] == SID


def test_live_ghidra_queries_carry_the_captured_image_pins(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    agent.live_target = {**context(), 'game_title': 'SoulCalibur'}
    agent.live_analysis_executable = {'elf_path': '/private/guest.elf', 'sha256': 'a' * 64}
    agent.live_analysis_worker = 'analysis-worker'
    jobs = []
    agent._job = lambda name, inp, **kw: jobs.append((name, inp, kw)) or {'state': 'succeeded', 'output': {}}
    agent.run_tool('ghidra_bridge', {'op': 'decompile', 'target': '0x8c000000'})
    assert jobs[0][1]['expected_binary_path'] == '/private/guest.elf'
    assert jobs[0][1]['expected_sha256'] == 'a' * 64
    assert jobs[0][2]['worker'] == 'analysis-worker'
    with pytest.raises(ValueError, match='captured guest image'):
        agent.run_tool('ghidra_bridge', {'op': 'open', 'binary_path': '/host/retroarch.exe'})
    with pytest.raises(ValueError, match='does not forward'):
        agent.run_tool('re_agent', {'op': 'reverse', 'target': '0x8c000000'})


def test_sh4_research_uses_guest_ram_and_ghidra_not_the_emulator_executable(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    agent.live_target = {**context(), 'game_title': 'SoulCalibur'}
    agent._live_phase = lambda *a, **k: None
    jobs, rea = [], []
    ex = {'session_id': SID, 'game_id': GID, 'mod': 'sonic-build', 'elf_path': '/private/guest.elf',
          'sha256': 'a' * 64, 'source_sha256': 'b' * 64, 'processor': 'SuperH4:LE:32:default', 'cpu': 'sh4'}
    def job(name, inp, **kwargs):
        jobs.append((name, inp, kwargs))
        return {'state': 'succeeded', 'worker_id': 'analysis-worker',
                'output': ex if name == 're_executable' else {'result': {'opened': True}}}
    agent._job = job
    agent.run_tool = lambda name, inp, **kw: rea.append((name, inp, kw)) or {'state': 'succeeded'}
    result = investigate(agent, SID, 'unlock all characters')
    assert jobs[0][0:2] == ('re_executable', {'game_id': GID, 'source': 'ram', 'session_id': SID})
    assert jobs[1][1]['processor'] == 'SuperH4:LE:32:default'
    assert jobs[1][1]['binary_path'] == '/private/guest.elf'
    assert jobs[1][2]['worker'] == 'analysis-worker'
    assert rea == [('rea_binary_session', {}, {'worker_id': 'analysis-worker'})]
    assert result['rea']['guest_attached'] is False and result['verified'] is False
    assert not any(path.endswith('/study') for _, path in requests)
    again = investigate(agent, SID, 'unlock costumes too')
    assert again['reused_analysis'] is True and len(jobs) == 3 and len(rea) == 1
    assert jobs[-1][1] == {'op': 'info', 'expected_binary_path': ex['elf_path'], 'expected_sha256': ex['sha256']}
    # A shared bridge can change programs between requests. Reopen the captured
    # ELF instead of recapturing RAM or falling back to a disc extraction.
    def changed_program(name, inp, **kwargs):
        if inp.get('op') == 'info':
            jobs.append((name, inp, kwargs))
            return {'state': 'failed', 'error': 'The loaded executable changed'}
        return job(name, inp, **kwargs)
    agent._job = changed_program
    reopened = investigate(agent, SID, 'unlock stages too')
    assert reopened['ghidra']['state'] == 'succeeded' and 'reused_analysis' not in reopened
    assert sum(name == 're_executable' for name, _, _ in jobs) == 1
    assert jobs[-1][1]['binary_path'] == '/private/guest.elf'


def test_a_reused_agent_clears_previous_live_program_pins(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    agent.live_analysis_executable = {'elf_path': '/previous/guest.elf', 'sha256': 'a'*64}
    agent.live_analysis_worker = agent.rea_worker = 'retired-worker'
    monkeypatch.setattr(httpx, 'post', lambda *a, **k: httpx.Response(200, json={
        'choices': [{'message': {'content': 'Hello'}}]}))
    agent.run([{'role': 'user', 'content': 'hello'}], lambda _: None, {}, max_steps=1)
    assert agent.live_analysis_executable is agent.live_analysis_worker is agent.rea_worker is None


@pytest.mark.parametrize('method,args', [
    ('re_executable', {'game_id': GID, 'source': 'disc'}),
    ('re_executable', {'game_id': GID, 'source': 'auto', 'session_id': SID}),
    ('re_executable', {'game_id': GID, 'source': 'path', 'path': '/host/runner.exe'}),
    ('re_study', {'source': 'auto', 'session_id': SID}),
])
def test_live_request_rejects_disc_fallback_before_a_worker_job(monkeypatch, method, args):
    agent, requests = make_agent(monkeypatch)
    agent.live_target = context()
    with pytest.raises(ValueError, match='does not copy or unpack'):
        agent._guard_live_call(method, args)
    assert requests == []
    with pytest.raises(ValueError, match='does not copy or unpack'):
        agent._guard_live_call('run_tool', {'name': method, 'input': args})
    assert requests == []


def test_direct_live_study_cannot_bypass_the_no_rom_copy_guard(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    agent.live_target = context()
    agent._re_gid = lambda _: pytest.fail('Must refuse before resolving or staging a ROM')
    with pytest.raises(ValueError, match='does not copy or unpack'):
        agent.re_study(GID)
    assert requests == []


def test_unsupported_native_capture_is_reported_before_any_analysis_job(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    agent.live_target = context()
    agent._live_phase = lambda *a, **kw: None
    agent._rpc = lambda *a: {'game_id': GID, 'platform': 'xbox',
        'runtime': {'running': True}, 'capabilities': {'read_memory': 'unsupported'}}
    agent._job = lambda *a, **kw: pytest.fail('Unsupported RAM must not queue extraction')
    result = investigate(agent, SID, 'unlock everything')
    assert result['state'] == 'blocked' and result['rom_copy'] is False and result['verified'] is False
    assert not any(path.endswith('/study') for _, path in requests)


def test_ram_study_does_not_replace_the_base_title_executable(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    agent._re_gid = lambda _: GID
    agent.context_session_id = SID
    agent._job = lambda *a, **k: {'state': 'succeeded', 'output': {
        'elf_path': '/private/live.elf', 'sha256': 'a' * 64, 'source': 'ram'}}
    result = agent.re_study(GID, source='ram', session_id=SID, analyze=False)
    assert result['scope'] == 'live_snapshot'
    assert not any(method == 'POST' and path.endswith('/study') for method, path in requests)


def test_hub_keeps_an_unfulfilled_live_goal_pending_even_if_model_says_done():
    class Store:
        value = {'id': 'chat', 'messages': [], 'events': [], 'busy': True}
        def get(self, *args): return copy.deepcopy(self.value)
        def put(self, kind, cid, value): self.value = copy.deepcopy(value)
    class ProseAgent:
        def run(self, messages, emit, ctx):
            emit({'type': 'assistant', 'text': 'Done, everything is unlocked.'})
            return {'usage': {'in': 1, 'out': 1}, 'tools': {}}
    actions = []
    hub = ChatHub(Store(), lambda _: ProseAgent())
    hub._gap_report = lambda *args: None
    hub._turn('chat', 'unlock all characters and stages', context(),
              lambda op, body: actions.append((op, body)) or 'request')
    assert next(body for op, body in actions if op == 'status')['status'] == 'in_progress'
    assert hub.get('chat')['events'][-1]['phase'] == 'pending'
