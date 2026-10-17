import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from gbox.config import Config
from gbox.server import create_app


@pytest.fixture
def client(tmp_path):
    cfg = Config(data_dir=tmp_path)
    with TestClient(create_app(cfg), headers={'Authorization': 'Bearer ' + cfg.token()}) as client:
        yield client


def test_verified_credit_survives_a_reopen_without_awarding_another_completion(client):
    rid = client.post('/api/requests', json={'title': 'Pause toggle', 'source': 'api'}).json()['id']
    solver = {'service': 'ollama-cloud', 'model': 'kimi-k2.7-code', 'system': 'Hermes',
              'verified_by': 'Codex', 'verification': '8 regression tests; live pause and resume confirmed'}
    bad = client.post(f'/api/requests/{rid}/status', json={'status': 'in_progress', 'solved_by': solver})
    assert bad.status_code == 422
    done = client.post(f'/api/requests/{rid}/status', json={'status': 'done', 'solved_by': solver}).json()
    assert done['solved_by']['verified_by'] == 'Codex'
    assert done['solved_by']['service'] == 'ollama-cloud'
    exported = client.get('/api/requests/export').text
    assert 'Solver: ollama-cloud' in exported
    assert 'Verified by: Codex' in exported
    reopened = client.post(f'/api/requests/{rid}/status', json={'status': 'in_progress'}).json()
    assert reopened['status'] == 'in_progress'
    assert reopened['solved_by']['model'] == 'kimi-k2.7-code'  # history, excluded by the UI
    completed_again = client.post(f'/api/requests/{rid}/status', json={'status': 'done'}).json()
    assert completed_again['solved_by'] is None  # do not reuse old implementation credit


def test_prompt_export_contains_original_and_followup_across_statuses(client):
    rid = client.post('/api/requests', json={'title': 'Export original', 'body': 'First full prompt', 'source': 'api'}).json()['id']
    client.post(f'/api/requests/{rid}/status', json={'status': 'done'})
    client.post(f'/api/requests/{rid}/messages', json={'author': 'operator', 'text': 'Later follow-up 日本語'})
    response = client.get('/api/requests/export?prompts_only=true&status=done')
    assert response.status_code == 200
    assert 'gbox-prompt-history.md' in response.headers['content-disposition']
    assert response.text.index('First full prompt') < response.text.index('Later follow-up 日本語')


def test_credit_requires_verification_and_usage_is_separated_by_provider(client):
    rid = client.post('/api/requests', json={'title': 'Model swap', 'source': 'api'}).json()['id']
    response = client.post(f'/api/requests/{rid}/status', json={'status': 'done', 'solved_by': {'service': 'nous'}})
    assert response.status_code == 422
    for provider, model, tokens in [('ollama-cloud', 'kimi-k2.7-code', 100), ('codex', 'GPT-6', 30), ('ollama-cloud', 'kimi-k2.7-code', 50)]:
        response = client.post(f'/api/requests/{rid}/metrics', json={'provider': provider, 'model': model,
            'system': 'Hermes' if provider != 'codex' else 'Codex', 'tokens_in': tokens, 'tokens_out': 2, 'duration_s': 10})
        assert response.status_code == 200
    metrics = response.json()['metrics']
    assert metrics['tokens_in'] == 180
    assert len(metrics['usage_by_solver']) == 2
    assert metrics['usage_by_solver'][0]['tokens_in'] == 150
    assert metrics['usage_by_solver'][0]['agent_seconds'] == 20
    assert metrics['usage_by_solver'][1]['tokens_in'] == 30


def test_metrics_ledger_only_zero_turns_preserves_default_and_explicit_counts(client):
    rid = client.post('/api/requests', json={'title': 'Usage reconciliation', 'source': 'api'}).json()['id']
    path = f'/api/requests/{rid}/metrics'
    # Reconciliation records actual usage without inventing an inference turn.
    response = client.post(path, json={'turns': 0, 'tools': {'ghidra': 3}})
    assert response.status_code == 200
    assert response.json()['metrics']['turns'] == 0
    assert response.json()['metrics']['tools']['ghidra'] == 3
    response = client.post(path, json={'tokens_in': 4})
    assert response.status_code == 200
    assert response.json()['metrics']['turns'] == 1  # Omitted still means one agent turn.
    response = client.post(path, json={'turns': 2})
    assert response.status_code == 200
    assert response.json()['metrics']['turns'] == 3
    response = client.post(path, json={'turns': None})
    assert response.status_code == 200
    assert response.json()['metrics']['turns'] == 4  # Preserve the existing nullable API default.


def test_mcp_forwards_solver_credit_and_provider_usage(monkeypatch):
    pytest.importorskip('mcp')
    from mcp.client import Client
    from gbox.mcp_server import build
    posted = []
    def handler(req):
        if req.url.path == '/api/registry':
            return httpx.Response(200, json={'tools': []})
        posted.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={'ok': True})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *args, **kwargs: original(*args, **kwargs, transport=httpx.MockTransport(handler)))
    solver = {'service': 'openrouter', 'model': 'google/gemini-3.8-flash', 'system': 'Hermes', 'verification': 'Live screenshot verified'}
    async def check():
        async with Client(build('http://fixture', 'fixture')) as client:
            result = await client.call_tool('set_request_status', {'request_id': 'req1', 'status': 'done', 'solved_by': solver})
            assert not result.is_error
            result = await client.call_tool('record_request_metrics', {'request_id': 'req1', 'provider': 'openrouter', 'system': 'Hermes', 'model': solver['model'], 'tokens_in': 20, 'tokens_out': 10})
            assert not result.is_error
    asyncio.run(check())
    assert posted[0][1]['solved_by'] == solver
    assert posted[1][1]['provider'] == 'openrouter'
