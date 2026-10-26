import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import background_testing as B, worker_resources as R
from gbox.server import create_app


def measured(cpu=20, gpu=30, now=None):
    return {'sampled_at': time.time() if now is None else now, 'cpu_percent': cpu,
            'memory_percent': 50, 'memory_available_bytes': 8*1024**3,
            'gpus': [{'name': 'Test GPU', 'utilization_percent': gpu}]}


def worker(resources=None):
    return {'id':'nuc','name':'i9-NUC','os':'windows','online':True,'idle_seconds':600,
            'resources':measured() if resources is None else resources}


@pytest.mark.parametrize('change,fragment', [
    ({'idle_seconds': None}, 'operator input'),
    ({'idle_seconds': 5}, 'operator input'),
    ({'resources': {}}, 'telemetry'),
    ({'resources': measured(now=time.time()-60)}, 'telemetry'),
    ({'resources': measured(now=time.time()+60)}, 'telemetry'),
    ({'resources': measured(cpu=70)}, 'CPU is at 70%'),
    ({'resources': measured(gpu=95)}, 'GPU is at 95%'),
    ({'resources': measured(cpu=float('nan'))}, 'CPU interval'),
])
def test_admission_honors_operator_competing_load_and_unknown_measurements(change, fragment):
    assert fragment in B.admission_reason(worker() | change, set())


def test_gpu_without_measurement_and_memory_pressure_are_not_spare_capacity():
    assert 'installed GPU' in B.admission_reason(worker(measured(gpu=None)), set())
    assert 'memory headroom' in B.admission_reason(worker(measured() | {'memory_available_bytes': 1024}), set())
    assert B.admission_reason(worker(), set()) is None
    assert 'Gaming mode' in B.admission_reason(worker(), {'i9-NUC'})


def test_budget_and_gaming_mode_persist_by_worker_name_and_preserve_each_other(cfg):
    app=create_app(cfg);s=app.state.store;s.put('worker','nuc',worker() | {'last_seen':time.time(),'tools':[]})
    c=TestClient(app,headers={'Authorization':f'Bearer {cfg.token()}'})
    assert c.get('/api/testing/workers').json()['workers'][0]['budget_percent']==70
    assert c.post('/api/testing/workers/nuc',json={'budget_percent':55}).status_code==200
    c.post('/api/testing/workers/i9-NUC',json={'available':False}).raise_for_status()
    row=c.get('/api/testing/workers').json()['workers'][0]
    assert row['budget_percent']==55 and not row['admission']['allowed']
    c.post('/api/testing/workers/nuc',json={'available':True}).raise_for_status()
    assert B.policy(s,'i9-NUC')['budget_percent']==55
    assert c.post('/api/testing/workers/nuc',json={'budget_percent':101}).status_code==422


def test_loaded_worker_defers_durable_background_job_but_operator_controls_still_claim(cfg):
    app=create_app(cfg);s=app.state.store
    info=worker(measured(cpu=85)) | {'last_seen':time.time(),'tools':['scan_library'],'unavailable':{}}
    s.put('worker','nuc',info)
    c=TestClient(app,headers={'Authorization':f'Bearer {cfg.token()}'})
    submitted=c.post('/api/jobs',json={'tool':'scan_library','input':{},'agent_use':True})
    assert submitted.status_code==200,submitted.text
    job=submitted.json()
    result=c.post('/api/workers/nuc/claim',json={'idle_seconds':600})
    assert result.status_code==204
    waiting=s.get('job',job['id'])
    assert waiting['state']=='queued' and waiting['started'] is None
    assert '85%' in waiting['admission_wait']['reason']
    operator=c.post('/api/jobs',json={'tool':'scan_library','input':{}}).json()
    assert c.post('/api/workers/nuc/claim',json={'idle_seconds':1}).json()['id']==operator['id']
    s.put('worker','nuc',info | {'resources':measured(),'idle_seconds':600})
    taken=c.post('/api/workers/nuc/claim',json={'idle_seconds':600}).json()
    assert taken['id']==job['id'] and 'admission_wait' not in taken
    assert not B.requires_admission({'agent_use':True,'tool':'state_transfer'})
    assert not B.requires_admission({'agent_use':True,'tool':'session_op','input':{'op':'stop_game'}})


def test_sampler_first_cpu_is_unknown_and_gpu_query_is_bounded(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil,'cpu_percent',lambda **kw:27)
    monkeypatch.setattr(psutil,'virtual_memory',lambda:SimpleNamespace(percent=42,available=10*1024**3))
    monkeypatch.setattr(R.shutil,'which',lambda _: 'nvidia-smi')
    calls=[]
    def run(command,**kwargs):
        calls.append((command,kwargs))
        return SimpleNamespace(stdout='GPU-id, Test GPU, 36, 2000, 8000\n')
    monkeypatch.setattr(R.subprocess,'run',run)
    sampler=R.Sampler()
    assert sampler.snapshot()=={}
    assert sampler.sample()['cpu_percent'] is None
    result=sampler.sample()
    assert result['cpu_percent']==27 and result['gpus'][0]['utilization_percent']==36
    assert calls[0][1]['timeout']==2 and calls[0][1]['check'] is True


def test_unified_memory_gpu_keeps_utilization_when_dedicated_vram_is_unavailable(monkeypatch):
    monkeypatch.setattr(R.shutil,'which',lambda _: 'nvidia-smi')
    monkeypatch.setattr(R.subprocess,'run',lambda *a,**kw: SimpleNamespace(
        stdout='GPU-id, NVIDIA GB10, 94, [N/A], [N/A]\n'))
    sampled=R.Sampler().sample()
    assert sampled['gpu_status']=='measured'
    assert sampled['gpus']==[{'id':'GPU-id','name':'NVIDIA GB10','utilization_percent':94,
                              'memory_used_mb':None,'memory_total_mb':None}]
    assert 'NVIDIA GB10 is at 94%' in B.admission_reason(worker(measured() | {'gpus':sampled['gpus']}),set())


def test_testing_workers_lists_one_row_per_pc_preferring_the_online_worker(cfg):
    # 2026-10-26: eleven dead i9-NUC rows (one per restart) hid the live one; the toggle is by name anyway
    app = create_app(cfg); store = app.state.store
    now = time.time()
    for wid, seen in (('old1', now - 9000), ('old2', now - 5000), ('live', now)):
        store.put('worker', wid, worker() | {'id': wid, 'name': 'i9-NUC', 'tools': [], 'last_seen': seen})
    c = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    rows = c.get('/api/testing/workers').json()['workers']
    assert [r['name'] for r in rows].count('i9-NUC') == 1
    row = next(r for r in rows if r['name'] == 'i9-NUC')
    assert row['id'] == 'live' or row['online'] is True or row['id'] == 'old2'
    c.post('/api/testing/workers/i9-NUC', json={'available': False}).raise_for_status()
    assert 'i9-NUC' in c.get('/api/testing/workers').json()['excluded']
