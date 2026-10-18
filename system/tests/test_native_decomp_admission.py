import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import background_testing as admission
from gbox import native_decomp as nd, native_decomp_runtime as rt
from gbox.server import create_app

ENGINES = ('decomp_pipeline', 'xenonrecomp', 'rexglue')


def worker(engine, reason):
    return {'id': 'w', 'name': 'fixture-worker', 'os': 'windows',
            'tools': [engine], 'unavailable': {}, 'last_seen': time.time(),
            'idle_seconds': 600, 'active_jobs': 0,
            'resources': {'sampled_at': time.time(),
                'cpu_percent': 84 if reason == 'cpu' else 20,
                'memory_percent': 50, 'memory_available_bytes': 8 * 1024**3,
                'gpus': [{'name': 'fixture GPU', 'utilization_percent': 94 if reason == 'gpu' else 20}]}}


def plane(cfg, engine, reason):
    app = create_app(cfg)
    store = app.state.store
    store.put('worker', 'w', worker(engine, reason))
    if reason == 'excluded':
        admission.set_available(store, 'fixture-worker', False)
    return store, TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})


def submit(client, engine, op, **priority):
    response = client.post('/api/jobs', json={
        'tool': engine, 'input': {'op': op}, 'require_worker': 'w', **priority})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('engine', ENGINES)
@pytest.mark.parametrize('reason,fragment', [('cpu', '84%'), ('gpu', '94%'), ('excluded', 'disabled')])
def test_real_claim_allows_explicit_status_but_keeps_earlier_init_queued(cfg, engine, reason, fragment):
    store, client = plane(cfg, engine, reason)
    heavy = submit(client, engine, 'init', agent_use=True)
    diagnostic = submit(client, engine, 'status', agent_use=True)
    # A queued status from the old classification becomes claimable without
    # resubmission, and the obsolete admission reason is removed on claim.
    store.put('job', diagnostic['id'], diagnostic | {'admission_wait': {'reason': 'old GPU gate'}})
    response = client.post('/api/workers/w/claim', json={'idle_seconds': 600, 'active_jobs': 0})
    assert response.status_code == 200, response.text
    taken = response.json()
    assert taken['id'] == diagnostic['id'] and taken['worker_id'] == 'w'
    assert 'admission_wait' not in taken and taken['state'] == 'running'
    waiting = store.get('job', heavy['id'])
    assert waiting['state'] == 'queued' and waiting['started'] is None
    assert fragment in waiting['admission_wait']['reason']
    assert client.post('/api/workers/w/claim', json={'idle_seconds': 600, 'active_jobs': 1}).status_code == 204


@pytest.mark.parametrize('engine', ENGINES)
def test_api_default_is_normalized_to_status_before_admission(cfg, engine):
    store, client = plane(cfg, engine, 'excluded')
    response = client.post('/api/jobs', json={
        'tool': engine, 'input': {}, 'require_worker': 'w', 'agent_use': True})
    assert response.status_code == 200, response.text
    job = response.json()
    assert store.get('job', job['id'])['input']['op'] == 'status'
    response = client.post('/api/workers/w/claim', json={'idle_seconds': 0})
    assert response.status_code == 200 and response.json()['id'] == job['id']


@pytest.mark.parametrize('engine,op', [(engine, op) for engine in ENGINES for op in nd.OPS[engine] if op != 'status'])
def test_every_nonstatus_operation_stays_queued_on_busy_worker(cfg, engine, op):
    store, client = plane(cfg, engine, 'gpu')
    job = submit(client, engine, op, agent_use=True)
    assert client.post('/api/workers/w/claim', json={'idle_seconds': 600}).status_code == 204
    waiting = store.get('job', job['id'])
    assert waiting['state'] == 'queued' and waiting['started'] is None
    assert '94%' in waiting['admission_wait']['reason']


@pytest.mark.parametrize('engine', ENGINES)
def test_low_priority_status_uses_same_narrow_diagnostic_classification(cfg, engine):
    store, client = plane(cfg, engine, 'excluded')
    heavy = submit(client, engine, 'init', low_priority=True)
    status = submit(client, engine, 'status', low_priority=True)
    response = client.post('/api/workers/w/claim', json={'idle_seconds': 0})
    assert response.status_code == 200 and response.json()['id'] == status['id']
    assert store.get('job', heavy['id'])['state'] == 'queued'


@pytest.mark.parametrize('tool,inp', [
    ('decomp_pipeline', {}), ('xenonrecomp', {'op': 'STATUS'}),
    ('rexglue', {'op': 'status '}), ('rexglue', {'op': None}),
    ('native_decomp', {'op': 'status'}), ('unreviewed_tool', {'op': 'status'}),
])
def test_raw_missing_or_lookalike_status_never_inherits_exemption(tool, inp):
    assert admission.requires_admission({'tool': tool, 'input': inp, 'agent_use': True})
    assert admission.requires_admission({'tool': tool, 'input': inp, 'low_priority': True})


@pytest.mark.parametrize('engine', ENGINES)
def test_worker_pin_and_advertised_tools_still_apply_to_status(cfg, engine):
    store, client = plane(cfg, engine, 'excluded')
    job = submit(client, engine, 'status', agent_use=True)
    store.put('worker', 'other', worker(engine, 'cpu') | {'id': 'other', 'name': 'other'})
    assert client.post('/api/workers/other/claim', json={'idle_seconds': 600}).status_code == 204
    own = store.get('worker', 'w'); own['tools'] = []
    store.put('worker', 'w', own)
    assert client.post('/api/workers/w/claim', json={'idle_seconds': 600}).status_code == 204
    assert store.get('job', job['id'])['state'] == 'queued'


@pytest.mark.parametrize('engine', ENGINES)
@pytest.mark.parametrize('installed', [False, True])
def test_actual_status_wrapper_performs_no_process_or_project_writes(cfg, tmp_path, monkeypatch, engine, installed):
    root = tmp_path / 'upstream'
    root.mkdir()
    names = {'decomp_pipeline': ['decomp.py'], 'xenonrecomp': ['XenonAnalyse', 'XenonRecomp'], 'rexglue': ['rexglue']}[engine]
    if installed:
        for name in names:
            suffix = '.exe' if os.name == 'nt' and name != 'decomp.py' else ''
            (root / (name + suffix)).write_text('fixture; must never execute')
    cfg.native_decomp = {engine: {'home': str(root)}}
    for name in ENGINES:
        monkeypatch.delenv('GBOX_' + name.upper() + '_HOME', raising=False)
    local = Path(cfg.runtime) / 'decomp-tools/gbox-local.json'
    local.parent.mkdir(parents=True)
    local.write_text(json.dumps({engine: {'home': str(root)}}))
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    def forbidden(*args, **kwargs):
        raise AssertionError('status attempted a process, project operation or write')
    for name in ('execute', 'project', 'locked', 'write_json', 'inventory', 'sha'):
        monkeypatch.setattr(rt, name, forbidden)
    monkeypatch.setattr(nd, 'initialize', forbidden)
    monkeypatch.setattr(rt.subprocess, 'run', forbidden)
    monkeypatch.setattr(rt.subprocess, 'Popen', forbidden)
    for name in ('mkdir', 'write_bytes', 'write_text'):
        monkeypatch.setattr(Path, name, forbidden)
    original_open = Path.open
    reads = []
    class ReadOnly:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): self.stream.close()
        def read(self, count=-1):
            assert 0 <= count <= (2 << 20) + 1
            reads.append(count)
            return self.stream.read(count)
    def opened(path, mode='r', *args, **kwargs):
        assert not any(c in mode for c in 'wax+')
        assert path == local
        return ReadOnly(original_open(path, mode, *args, **kwargs))
    monkeypatch.setattr(Path, 'open', opened)
    ctx = SimpleNamespace(config=cfg, artifact=forbidden, progress=forbidden)
    result = getattr(nd, engine)(nd.NativeDecompIn(op='status', work_id='../ignored', binary_path='unused'), ctx)
    assert result['op'] == 'status' and result['result']['installed'] is installed
    assert result['result']['readiness'].startswith('Program discovery only')
    assert reads and all(n == (2 << 20) + 1 for n in reads)
    monkeypatch.setattr(Path, 'open', original_open)
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert after == before
    assert not (Path(cfg.runtime) / 'native-decomp').exists()
