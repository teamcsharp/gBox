"""No network or input: native vision shape, capability and timing regressions."""
import base64
import json

import httpx
import pytest

from gbox import pso_campaign as P
from gbox.registry import Unsupported


@pytest.fixture
def provider():
    state = {'native': True, 'calls': [], 'capabilities': ['completion', 'vision'],
             'thinking': {'values': [False, True], 'default': True},
             'models': [{'name': 'observed-model', 'context_length': 16384}],
             'answer': {'screen': 'menu', 'actions': []}}
    def handler(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        state['calls'].append((path, body))
        if callback := state.get('on_request'):
            callback(path)
        if path == '/api/version':
            return httpx.Response(200 if state['native'] else 404, json={'version': '0.35.1'})
        if path == '/api/show':
            return httpx.Response(200, json={'capabilities': state['capabilities'], 'thinking': state['thinking']})
        if path == '/api/ps':
            if state.get('ps_fails'):
                raise httpx.ReadTimeout('metadata unavailable')
            return httpx.Response(200, json={'models': state['models']})
        if path == '/v1/models':
            return httpx.Response(200, json={'data': [{'id': 'observed-model'}]})
        if path == '/api/chat':
            return httpx.Response(200, json={'message': {'content': json.dumps(state['answer'])}})
        if path == '/v1/chat/completions':
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(state['answer'])}}]})
        pytest.fail('Unconfigured provider endpoint: ' + str(request.url))
    planner = P.Planner.__new__(P.Planner)
    planner.model = 'observed-model'
    planner.api = httpx.Client(base_url='http://configured-provider:9999/v1', transport=httpx.MockTransport(handler))
    state['planner'] = planner
    yield state
    planner.close()


def test_native_vision_keeps_model_frame_and_exact_resident_context(provider):
    planner = provider['planner']
    assert planner.preflight()['vision_capability_verified']
    assert planner(b'actual-image-bytes', {'floor': 0}) == provider['answer']
    body = provider['calls'][-1][1]
    assert provider['calls'][-1][0] == '/api/chat'
    assert body['model'] == 'observed-model' and body['think'] is False
    assert body['options'] == {'temperature': .1, 'num_predict': 1800, 'num_ctx': 16384}
    assert body['messages'][0]['images'] == [base64.b64encode(b'actual-image-bytes').decode()]
    assert '"floor": 0' in body['messages'][0]['content']
    assert all('actual-image-bytes' not in str(body) for path, body in provider['calls'][:-1])


def test_non_ollama_preserves_configured_compatibility_endpoint(provider):
    provider['native'] = False
    assert provider['planner'].preflight()['model'] == 'observed-model'
    provider['planner'](b'frame', {})
    assert [p for p, _ in provider['calls']] == ['/api/version', '/v1/models', '/v1/chat/completions']
    image = provider['calls'][-1][1]['messages'][0]['content'][1]
    assert image['image_url']['url'] == 'data:image/png;base64,' + base64.b64encode(b'frame').decode()


@pytest.mark.parametrize('capabilities', [None, [], ['completion'], 'not-vision'])
def test_native_preflight_refuses_unverified_vision_model(provider, capabilities):
    provider['capabilities'] = capabilities
    with pytest.raises(Unsupported, match='vision capability'):
        provider['planner'].preflight()
    assert not any(p.endswith('/api/chat') for p, _ in provider['calls'])


@pytest.mark.parametrize('thinking', [None, {}, {'values': [0, True]}, {'values': ['low', 'high']}])
def test_no_guessed_thinking_flag(provider, thinking):
    provider['thinking'] = thinking
    provider['planner'](b'frame', {})
    assert 'think' not in provider['calls'][-1][1]


@pytest.mark.parametrize('models', [[], [{'name': 'different-model', 'context_length': 16384}],
    [{'name': 'observed-model', 'context_length': True}],
    [{'name': 'observed-model', 'context_length': '16384'}],
    [{'name': 'observed-model', 'context_length': 1_048_577}],
    [{'name': 'observed-model', 'context_length': 16384}, {'name': 'observed-model', 'context_length': 8192}]])
def test_no_inferred_or_resized_native_context(provider, models):
    provider['models'] = models
    provider['planner'](b'frame', {})
    assert 'num_ctx' not in provider['calls'][-1][1]['options']


def test_optional_residency_failure_keeps_context_default(provider):
    provider['ps_fails'] = True
    provider['planner'](b'frame', {})
    assert 'num_ctx' not in provider['calls'][-1][1]['options']


def test_native_discovery_shares_the_request_budget(provider, monkeypatch):
    clock = [0]
    monkeypatch.setattr(P.time, 'monotonic', lambda: clock[0])
    provider['on_request'] = lambda path: clock.__setitem__(0, 36) if path == '/api/ps' else None
    with pytest.raises(TimeoutError, match='budget'):
        provider['planner'](b'frame', {})
    assert not any(p == '/api/chat' for p, _ in provider['calls'])


def test_late_provider_response_cannot_authorize_input(provider, monkeypatch):
    clock = [0]
    monkeypatch.setattr(P.time, 'monotonic', lambda: clock[0])
    provider['on_request'] = lambda path: clock.__setitem__(0, 36) if path == '/api/chat' else None
    with pytest.raises(TimeoutError, match='budget'):
        provider['planner'](b'frame', {})
