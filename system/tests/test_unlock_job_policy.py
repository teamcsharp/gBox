"""Persisted idle unlock constraints cannot be escaped through job wrappers."""
from types import SimpleNamespace
import time

import pytest
from fastapi.testclient import TestClient

from gbox import unlock_job_policy as P
from gbox.config import Config
from gbox.server import create_app
from tests.test_build_quarantine import Memory
from tests.test_live_request_agent import make_agent


LIMITS = {'custom_build_unlocks': 'g', 'idle_only': True,
          'no_automatic_launch': True, 'no_rom_copy': True}


@pytest.mark.parametrize('name,args', [
    ('@launch', {'game_id': 'g'}), ('launch_game', {'game_id': 'g'}),
    ('evidence_capture', {'game_id': 'g'}), ('scene_capture', {'session_id': 'w-s'}),
    ('file_mod', {'op': 'build', 'game_id': 'g'}), ('cast_swap', {'game_id': 'g'}),
    ('re_executable', {'source': 'auto', 'game_id': 'g'}),
    ('re_executable', {'source': 'path', 'game_id': 'g', 'path': 'huge.iso'}),
    ('re_study', {'source': 'disc'}), ('ghidra_script', {'script': 'arbitrary.py'}),
    ('ghidra_bridge', {'op': 'run_script', 'script': 'arbitrary.py'}),
    ('ghidra_bridge', {'op': 'open', 'binary_path': 'huge.iso'}),
    ('analyze_binary', {'binary_path': 'huge.iso'}),
    ('rea_capture_native_ui_scenario', {}), ('rea_open_binary', {'path': 'huge.iso'}),
    ('unknown_future_builder', {}),
])
def test_restricted_job_or_wrapper_is_refused(name, args):
    assert P.reason(LIMITS, name, args)
    assert P.reason(LIMITS, 'run_tool', {'name': name, 'input': args})
    assert not P.reason({}, name, args), 'ordinary operator/build workflows are unchanged'


@pytest.mark.parametrize('name,args', [
    ('re_executable', {'game_id': 'g', 'source': 'ram', 'session_id': 'w-s'}),
    ('analyze_binary', {'binary_path': '/analysis/exact.elf'}),
    ('ghidra_bridge', {'op': 'open', 'binary_path': 'C:\\analysis\\exact.elf'}),
    ('ghidra_bridge', {'op': 'decompile', 'target': '0x1651a5'}),
    ('rea_open_binary', {'path': '/analysis/exact.elf'}),
    ('rea_procedure_pseudo_code', {}), ('read_rea_result', {'sha256': 'a' * 64}),
])
def test_bounded_existing_analysis_is_allowed(name, args):
    assert not P.reason(LIMITS, name, args)
    assert P.reason(LIMITS, 're_executable', {'source': 'ram', 'game_id': 'another'})


def test_legacy_builds_keep_writer_contract_but_need_fresh_idle_hook():
    store, app = Memory(), SimpleNamespace(state=SimpleNamespace())
    store.put('request', 'r', {'context': {'idle_only': True}})
    assert not P.reason({'idle_only': True}, 'file_mod', {'op': 'build'})
    assert 'unavailable' in P.admit(store, app, 'r', 'file_mod', {'op': 'build'})
    app.state.custom_build_unlock_job_admission = lambda rid: 'PC input is active'
    assert 'active' in P.admit(store, app, 'r', 'file_mod', {'op': 'build'})
    app.state.custom_build_unlock_job_admission = lambda rid: ''
    assert not P.admit(store, app, 'r', 'file_mod', {'op': 'build'})
    def broken(rid): raise RuntimeError('incomplete inventory')
    app.state.custom_build_unlock_job_admission = broken
    assert 'could not be verified' in P.admit(store, app, 'r', 'file_mod', {'op': 'build'})


def test_http_submit_uses_persisted_context_before_launch_or_staging(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.put('request', 'r', {'context': LIMITS})
    app.state.custom_build_unlock_job_admission = lambda rid: ''
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    for name, args in [('@launch', {'game_id': 'g'}), ('re_executable', {'game_id': 'g'}),
                       ('evidence_capture', {'game_id': 'g'}), ('file_mod', {'game_id': 'g', 'op': 'build'})]:
        result = client.post('/api/jobs', json={'tool': name, 'input': args, 'parent_request_id': 'r'})
        assert result.status_code == 409, result.text
    assert not store.all('job')
    assert not store.all('session')


def test_queued_job_rechecks_idle_before_claim_and_resumes_later(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    store.put('request', 'r', {'context': LIMITS})
    store.put('worker', 'w', {'id': 'w', 'name': 'fixture', 'os': 'linux',
                            'tools': ['re_executable'], 'last_seen': time.time()})
    reason = ['']
    app.state.custom_build_unlock_job_admission = lambda rid: reason[0]
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    result = client.post('/api/jobs', json={'tool': 're_executable', 'parent_request_id': 'r',
        'input': {'game_id': 'g', 'source': 'ram', 'session_id': 'w-s'}})
    assert result.status_code == 200, result.text
    jid = result.json()['id']
    assert store.get('job', jid)['state'] == 'queued'
    reason[0] = 'Operator is playing'
    assert client.post('/api/workers/w/claim', json={'idle_seconds': 0}).status_code == 204
    assert store.get('job', jid)['state'] == 'queued'
    assert store.get('job', jid)['admission_wait']['reason'] == reason[0]
    reason[0] = ''
    store.put('request', 'r', {'context': {}})
    assert client.post('/api/workers/w/claim', json={'idle_seconds': 1000}).status_code == 204
    assert 'scope changed' in store.get('job', jid)['admission_wait']['reason']
    store.put('request', 'r', {'context': LIMITS})
    claim = client.post('/api/workers/w/claim', json={'idle_seconds': 1000})
    assert claim.status_code == 200, claim.text
    assert claim.json()['id'] == jid and claim.json()['state'] == 'running'
    assert 'admission_wait' not in claim.json()


def test_offline_agent_wrappers_recipes_and_rpc_enforce_constraints(monkeypatch):
    agent, requests = make_agent(monkeypatch)
    agent.research_constraints = LIMITS
    for call in [lambda: agent.launch_game('g'),
                 lambda: agent.re_study('g'),
                 lambda: agent.run_tool('file_mod', {'game_id': 'g', 'op': 'build'}),
                 lambda: agent._run_recipe({'name': 'bad', 'steps': [
                     {'tool': 'run_tool', 'args': {'name': 'launch_game', 'input': {'game_id': 'g'}}}]}, {}, {}),
                 lambda: agent._rpc('w-s', 'reset')]:
        with pytest.raises(ValueError): call()
    assert not requests
    assert not P.reason(LIMITS, 'web_search', {}, agent=True)
    agent.run([{'role': 'user', 'content': 'hello'}], lambda _: None, {})
    assert not any(agent.research_constraints.values()), 'a new operator turn clears background constraints'
