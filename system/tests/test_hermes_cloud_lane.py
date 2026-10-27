"""Cloud slots stay bounded without counting proven pinned local jobs twice."""
import copy
import pytest

from gbox import hermes_work_queue as q, hermes_local as local, hermes_pool as pool
from gbox.config import HermesLocalConfig


@pytest.fixture
def lane(monkeypatch, tmp_path):
    from gbox import hermes_recovery
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    settings = HermesLocalConfig(provider='prime', model='small',
        proxy_url='http://127.0.0.1:8765/api/llm/local/v1',
        nodes={'second': {'provider': 'second', 'model': 'large'}})
    monkeypatch.setattr(local, 'settings', lambda: settings)
    node = pool.node_settings(settings)['second']
    config = {'cron': {'model_provider': 'zai', 'model': 'glm', 'max_parallel_jobs': 26},
        'custom_providers': [dict(name=s.provider, model=s.model, base_url=s.proxy_url)
                             for s in (settings, node)]}
    jobs = [dict(id='controller', enabled=True, no_agent=True)]
    active = {'controller'}
    reqs = [dict(id=f'{i:016x}', number=i, title='Fix label', status='open') for i in range(10, 20)]
    q._save({'version': 1, 'items': {}, 'last_lane': 'inbox'})
    monkeypatch.setattr(q.mode, '_job', lambda: jobs[0])
    monkeypatch.setattr(q.mode, '_jobs', lambda: jobs)
    monkeypatch.setattr(q.mode, '_config', lambda: config)
    monkeypatch.setattr(q.mode, '_handoff', lambda: '')
    monkeypatch.setattr(q, '_executions', lambda: ({}, active))
    monkeypatch.setattr(q, '_native_jobs', lambda: [])
    monkeypatch.setattr(q, '_operator_playing', lambda: [])
    monkeypatch.setattr(q, 'throttle_sandboxes', lambda playing: 0)
    monkeypatch.setattr(q, '_on_main', lambda: set())
    monkeypatch.setattr(hermes_recovery, '_active_requests', lambda: set())
    monkeypatch.setattr(q.hermes_quota, 'routes', lambda *a: [dict(provider='zai', model='glm')])
    def api(path, body=None):
        if path == '/api/requests?lite=1': return reqs                  # the tick's listing (gbox.inbox.lite)
        if path == '/api/favorites': return {'count': 0, 'items': []}
        raise AssertionError(path)
    monkeypatch.setattr(q, '_api', api)
    calls = []
    def run(*args):
        calls.append(args)
        assert args[0] == 'create'
        jobs.append(dict(id='created-' + str(len(calls)), enabled=True,
                         name=args[args.index('--name') + 1], schedule={'kind': 'once'}))
    monkeypatch.setattr(q.mode, '_run', run)
    def reserve(count, **overrides):
        for _ in range(count):
            job = dict(id='local-' + str(len(jobs)), name='preexisting', enabled=True,
                       schedule={'kind': 'once'}, provider=node.provider, model=node.model)
            job.update(overrides); jobs.append(job); active.add(job['id'])
    return settings, config, jobs, active, calls, reserve


@pytest.mark.parametrize('count,expected', [(0, 4), (20, 4), (24, 2), (25, 1), (26, 0), (27, 0)])
def test_local_pins_leave_cloud_slots_but_obey_global_limit(lane, count, expected):
    settings, config, jobs, active, calls, reserve = lane
    reserve(count)
    before = copy.deepcopy(config)
    result = q.tick(now=1000)
    assert len(result['dispatched']) == expected
    assert result['active_or_queued'] == count + expected  # active + enabled once is one reservation
    assert result['capacity'] == 4 and result['global_capacity'] == 26
    assert result['cloud_active_or_queued'] == expected
    assert config == before
    assert all('--provider' not in c and '--model' not in c for c in calls)
    assert q.tick(now=1060)['dispatched'] == []


@pytest.mark.parametrize('pin', [
    {'provider': None}, {'model': None}, {'provider': 'unknown'}, {'model': 'unconfigured'},
    {'provider': 'zai', 'model': 'glm'}, {'base_url': 'https://remote.invalid/v1'},
])
def test_unknown_or_incomplete_pins_conservatively_consume_cloud(lane, pin):
    _, _, _, _, _, reserve = lane
    reserve(20); reserve(3, **pin)
    result = q.tick(now=1000)
    assert len(result['dispatched']) == 1
    assert result['cloud_active_or_queued'] == 4 and result['active_or_queued'] == 24


@pytest.mark.parametrize('registration', ['absent', 'remote', 'duplicate'])
def test_local_label_without_unique_registered_endpoint_is_not_proof(lane, registration):
    _, config, _, _, _, reserve = lane
    reserve(4)
    if registration == 'absent': config['custom_providers'].pop()
    elif registration == 'remote': config['custom_providers'][-1]['base_url'] = 'https://remote.invalid/v1'
    else: config['custom_providers'].append(dict(config['custom_providers'][-1]))
    result = q.tick(now=1000)
    assert result['dispatched'] == [] and result['cloud_active_or_queued'] == 4


def test_orphan_active_and_queue_history_do_not_prove_local_routing(lane):
    _, _, jobs, active, _, reserve = lane
    reserve(2, provider=None, model=None)
    data = q._read()
    data['items']['legacy'] = dict(lane='inbox', job_id=jobs[-1]['id'], local=True,
        route=dict(provider='second', model='large'), inference_node='second')
    q._save(data)
    active.update({'missing-one', 'missing-two'})
    result = q.tick(now=1000)
    assert result['dispatched'] == [] and result['cloud_active_or_queued'] == 4


def test_enabled_once_reserves_without_execution_and_recurring_idle_does_not(lane):
    _, _, jobs, active, _, reserve = lane
    reserve(25)
    active.clear()
    jobs.append(dict(id='idle-recurring', enabled=True, schedule={'kind': 'interval'}))
    result = q.tick(now=1000)
    assert len(result['dispatched']) == 1 and result['active_or_queued'] == 26


def test_explicit_matching_endpoint_is_still_a_local_pin(lane):
    _, config, _, _, _, reserve = lane
    reserve(25, base_url=config['custom_providers'][-1]['base_url'] + '/')
    assert len(q.tick(now=1000)['dispatched']) == 1


def test_operator_global_cap_still_counts_local_runs(lane, monkeypatch):
    _, _, _, _, _, reserve = lane
    reserve(1)
    monkeypatch.setattr(q, 'operator_gate', lambda options, *a: (options, 1, {'games': []}))
    result = q.tick(now=1000)
    assert result['dispatched'] == [] and result['global_capacity'] == 1


def test_duplicate_job_identity_remains_unknown(lane):
    settings, config, jobs, active, _, reserve = lane
    reserve(1)
    jobs.append(dict(jobs[-1]))
    assert q._pinned_local_reservations(jobs, active, config, settings) == set()

