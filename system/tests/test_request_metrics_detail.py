from fastapi.testclient import TestClient

from gbox.server import create_app


def test_metric_details_accept_sdk_metadata_and_only_accumulate_numeric_counters(cfg):
    client = TestClient(create_app(cfg), headers={'Authorization': 'Bearer ' + cfg.token()})
    report = client.post('/api/requests', json={'title': 'SDK usage verification'}).json()
    endpoint = '/api/requests/' + report['id'] + '/metrics'
    first = client.post(endpoint, json={'tokens_in': 100, 'tokens_out': 5,
        'tokens_detail': {'input_tokens': 100, 'source': 'first run', 'actual_cost_usd': 0.01,
                         'cost_status': 'actual', 'token_count_unavailable': False,
                         'metadata': {'run': 'a'}, 'unknown_cost': None}})
    assert first.status_code == 200, first.text
    second = client.post(endpoint, json={'tokens_in': 50, 'tokens_out': 2,
        'tokens_detail': {'input_tokens': 50, 'source': 'second run', 'actual_cost_usd': None,
                         'cost_status': 'actual', 'token_count_unavailable': True,
                         'metadata': {'run': 'b'}}})
    assert second.status_code == 200, second.text
    metrics = second.json()['metrics']
    assert (metrics['tokens_in'], metrics['tokens_out']) == (150, 7)
    detail = metrics['tokens_detail']
    assert detail['input_tokens'] == 150
    assert detail['source'] == 'second run'
    assert detail['actual_cost_usd'] == 0.01
    assert detail['cost_status'] == 'actual'
    assert detail['token_count_unavailable'] == 1
    assert detail['metadata'] == {'run': 'b'}
    assert detail['unknown_cost'] is None
    persisted = client.get('/api/requests/' + report['id']).json()
    assert persisted['metrics'] == metrics
