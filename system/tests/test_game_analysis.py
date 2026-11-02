import json
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import game_analysis as A, ollama_assist as O
from gbox.models import Job
from gbox.store import Store


@pytest.fixture
def rig(tmp_path):
    store = Store(tmp_path)
    game = {'game_id': 'game', 'title': 'Exact title', 'platform': 'gamecube', 'hashes': {'sha256': 'disc-hash'}}
    with store.lock:
        store.db.execute('INSERT INTO catalog(game_id,body) VALUES(?,?)', ('game', json.dumps(game)))
        store.db.commit()
    now = [time.time()]
    session = {'session_id': 'w-launch', 'game_id': 'game', 'title': 'Exact title', 'worker_id': 'w',
               'started': 123, 'state': 'running', 'adapter': 'dolphin', 'detail': {'pid': 55}}
    store.put('session', 'w-launch', session)
    worker = dict(id='w', name='PC', os='windows', idle_seconds=0, active_jobs=1,
                  tools=['ollama_assist', 'autoplay', 'characters', 'pso_mods'], last_seen=now[0],
                  resources=dict(sampled_at=now[0], cpu_percent=20, memory_percent=40,
                                 memory_available_bytes=32*2**30, gpus=[dict(name='GPU', utilization_percent=10,
                                 memory_total_mb=16384, memory_used_mb=1000)]),
                  ollama=dict(available=True, sampled_at=now[0], models=[dict(name='coder:3b', size=2*2**30, digest='sha')]))
    store.put('worker', 'w', worker)
    store.put('setting', O.SETTING, {'nodes': {'PC': O.policy(dict(enabled=True, model='coder:3b'))}})
    submitted = []
    def submit(req, actor):
        submitted.append(req)
        job = Job(**req, actor=actor).model_dump(mode='json')
        store.put('job', job['id'], job)
        return job
    manager = A.Analysis(store, clock=lambda: now[0], telemetry=lambda sid: {'running': True, 'age_s': 1, 'stats': {'kills': 2}},
                         submit=submit, launch=False)
    r = SimpleNamespace(store=store, now=now, session=session, worker=worker, manager=manager, submitted=submitted)
    yield r
    for rid in list(manager.active):
        manager.finish(store.get('game_analysis', rid), 'cancelled', 'test cleanup')
    store.db.close()


def start(r, **kwargs):
    return r.manager.start(A.Start(session_id='w-launch', **({'local_model':False} | kwargs)), 'operator')


def test_read_only_run_real_counts_exact_jobs_and_immutable_crystal(rig):
    s = rig.store
    good = dict(id='good', tool='autoplay', input={'session_id':'w-launch'}, state='running', progress_log=['Observed two actors'])
    s.put('job','good',good)
    s.put('job','wrong',good | {'id':'wrong','input':{'session_id':'w-other'},'progress_log':['Unrelated secret']})
    s.put('session_observer','w-launch',{'latest':{'session_id':'w-launch','game_id':'game','captured':10,'summary':'Walking (visual)'}})
    run = start(rig)
    assert run['counts'] == dict(polls=1, observations=1, jobs=1, artifacts=0, console_lines=1)
    assert len(run['console']) == 1 and 'Unrelated' not in json.dumps(run)
    assert not rig.submitted and not run['mutation_enabled']
    blob = s.read_artifact(run['crystal']['sha256']); crystal = json.loads(blob)
    assert crystal['schema'] == A.SCHEMA and crystal['target']['hashes'] == {'sha256':'disc-hash'}
    assert crystal['semantics']['model'].startswith('Hypotheses')
    assert 'percentage' in crystal['semantics']['progress']
    rig.now[0] += 3
    again = rig.manager.sample(run['id'])
    assert again['counts']['observations'] == 1 and again['counts']['console_lines'] == 1
    assert again['counts']['polls'] == 2 and s.read_artifact(run['crystal']['sha256']) == blob


@pytest.mark.parametrize('change', [{'state':'ended'}, {'game_id':'replacement'}, {'started':124}, {'detail':{'pid':56}}, {'mod':'different'}])
def test_identity_replacement_or_stop_interrupts_without_following(rig, change):
    run = start(rig)
    rig.store.put('session','w-launch',rig.session | change)
    rig.store.put('session','w-new',rig.session | {'session_id':'w-new'})
    out = rig.manager.sample(run['id'])
    assert out['state'] == 'interrupted' and out['target']['session_id'] == 'w-launch'
    assert not rig.submitted and not rig.manager.active


def test_catalog_only_never_uses_any_running_instance(rig):
    run = rig.manager.start(A.Start(game_id='game', build='custom'), 'operator')
    assert run['target']['session_id'] is None and run['target']['mod'] == 'custom'
    assert run['evidence']['native_telemetry'] == 'unavailable'
    assert run['evidence']['autoplay'] == {} and not rig.submitted


def test_old_or_wrong_observer_never_attaches(rig):
    rig.store.put('session_observer','w-launch',{'latest':{'session_id':'w-old','game_id':'game','summary':'old'}})
    run = start(rig)
    assert run['counts']['observations'] == 0 and run['evidence']['observer']['latest'] is None


def test_elapsed_window_completes_and_repeat_start_deduplicates(rig):
    run = start(rig, duration_s=15)
    assert start(rig, duration_s=15)['id'] == run['id']
    rig.now[0] += 15
    done = rig.manager.sample(run['id'])
    assert done['state'] == 'completed' and not rig.manager.active
    assert done['crystal']['sha256'] != run['crystal']['sha256']


def test_known_receipt_artifacts_are_evidence_unproven_paths_are_not(rig):
    ref = rig.store.put_artifact(b'proof', 'native-map.json', 'application/json', {})
    rig.store.put('receipt','receipt',{'artifacts':[ref.model_dump(),{'sha256':'nonexistent','name':'guess'}]})
    rig.store.put('job','j',dict(id='j',tool='map_probe',input={'session_id':'w-launch'},state='succeeded',receipt_id='receipt'))
    run = start(rig)
    assert list(run['artifacts']) == [ref.sha256] and run['artifacts'][ref.sha256]['job_id'] == 'j'


def test_capability_requests_never_enable_mutations(rig):
    rig.store.put('analysis_preferences','game',{'requested':{'replacement':True,'inventory':True}})
    run = start(rig)
    rows = {x['feature']: x for x in run['capabilities']}
    assert rows['replacement']['requested'] and rows['inventory']['installed_hooks'] == ['pso_mods']
    assert all(not x['execution_enabled'] for x in rows.values())
    assert rows['replacement']['state'] == 'adapter_verification_required'
    with pytest.raises(ValueError): A.Preferences(requested={'arbitrary_tool':True})


def model(r):
    run = start(r)
    job = r.manager.model(run['id'], A.ModelRequest(worker_id='w', allow_during_gameplay=True), 'operator')
    return r.store.get('game_analysis',run['id']), job


def test_explicit_local_coexist_preserves_resource_limits_and_no_tools(rig):
    run, job = model(rig)
    assert rig.submitted[0]['tool'] == 'ollama_assist' and rig.submitted[0]['low_priority']
    assert A.model_reason(rig.store, rig.worker, job, now=rig.now[0]) is None
    assert O.reason(rig.store, rig.worker, job) is None
    assert job['input']['analysis_run_id'] == run['id'] and 'tools' not in job['input']
    assert 'Task' not in job['input'].get('purpose','')


@pytest.mark.parametrize('change,match', [
    ({'resources': {'sampled_at':0}}, 'telemetry'),
    ({'resources': {'cpu_percent':95}}, 'CPU'),
    ({'resources': {'memory_available_bytes':1}}, 'memory'),
    ({'resources': {'gpus':[{'name':'GPU','utilization_percent':90}]}}, 'GPU'),
    ({'last_seen':0}, 'offline'),
])
def test_model_coexist_fails_closed_on_pressure_unknown_and_offline(rig, change, match):
    run, job = model(rig)
    w = rig.worker | change
    if 'resources' in change:w['resources'] = rig.worker['resources'] | change['resources']
    assert match in A.model_reason(rig.store,w,job,now=rig.now[0])


def test_forged_run_job_or_worker_cannot_bypass_idle(rig):
    run, job = model(rig)
    assert 'exact job' in A.model_reason(rig.store, rig.worker, job | {'id':'forged'})
    assert 'exact job' in A.model_reason(rig.store, rig.worker | {'id':'other'}, job)
    assert 'expired' in A.model_reason(rig.store, rig.worker, job, now=run['deadline'])


def test_no_coexist_default_still_requires_idle(rig):
    run = start(rig)
    job = rig.manager.model(run['id'], A.ModelRequest(worker_id='w'), 'operator')
    why = A.model_reason(rig.store,rig.worker,job,now=rig.now[0])
    assert 'Human gameplay' in why or 'input' in why


def test_coexist_does_not_cover_another_human_session(rig):
    run, job = model(rig)
    rig.store.put('session','w-other',rig.session | {'session_id':'w-other'})
    assert 'Another human' in A.model_reason(rig.store,rig.worker,job,now=rig.now[0])


def test_operator_stop_revokes_only_own_model_job(rig):
    run, job = model(rig)
    rig.store.put('job','unrelated',{'id':'unrelated','state':'running','tool':'autoplay','input':{'session_id':'w-launch'}})
    rig.manager.finish(run,'cancelled','stop')
    assert rig.store.get('job',job['id'])['cancel'] is True
    assert rig.store.get('job',job['id'])['state'] == 'failed'
    assert 'cancel' not in rig.store.get('job','unrelated')
    assert A.model_reason(rig.store,rig.worker,job,now=rig.now[0])


def test_server_restart_interrupts_prior_run_and_model(rig):
    run, job = model(rig)
    A.Analysis(rig.store,launch=False)
    assert rig.store.get('game_analysis',run['id'])['state'] == 'interrupted'
    assert rig.store.get('job',job['id'])['cancel']


def test_agents_cannot_enable_live_compute(rig):
    run = start(rig)
    with pytest.raises(ValueError,match='operator'):
        rig.manager.model(run['id'],A.ModelRequest(worker_id='w',allow_during_gameplay=True),'mcp')
    assert not rig.submitted


def test_bound_model_result_remains_hypothesis(rig):
    run, job = model(rig)
    rig.store.put('job',job['id'],job | {'state':'succeeded','output':{'result':{'status':'hypothesis','text':'May be a gate','usage':{'eval_count':8}}}})
    out = rig.manager.sample(run['id'])
    assert out['model_hypothesis']['status'] == 'hypothesis' and not out['mutation_enabled']


def test_running_permit_rechecks_stop_and_memory_reserve(rig):
    run, job = model(rig)
    job.update(state='running',worker_id='w');rig.store.put('job',job['id'],job)
    app = FastAPI();O.install(app,rig.store,lambda:'operator');c=TestClient(app)
    url='/api/ollama-assist/permit/w?job_id='+job['id']
    assert c.get(url).json()['allow_during_gameplay'] is True
    w=rig.worker | {'resources': rig.worker['resources'] | {'memory_available_bytes':4*2**30}}
    rig.store.put('worker','w',w)
    result=c.get(url).json();assert result['reason'] and result['allow_during_gameplay'] is False
    rig.manager.finish(run,'cancelled','stop')
    assert c.get(url).json()['reason']


def test_source_evidence_and_console_have_hard_bounds(rig):
    rig.manager.telemetry=lambda sid:{'blob':'x'*100000}
    rig.store.put('job','j',dict(id='j',tool='test',input={'session_id':'w-launch'},state='running',progress_log=['x'*2000]*201))
    run=start(rig)
    assert run['evidence']['autoplay']['truncated'] and len(run['console'])==50
    assert all(len(x['line'])<=1500 for x in run['console'])


def test_nonfinite_native_values_remain_unavailable_and_valid_json(rig):
    rig.manager.telemetry=lambda sid:{'stats':{'hp':float('nan'),'x':float('inf'),'kills':2}}
    run=start(rig)
    assert run['evidence']['autoplay']['stats'] == {'hp':None,'x':None,'kills':2}
    json.dumps(run,allow_nan=False)


def test_live_analysis_automatically_uses_only_configured_exact_worker(rig):
    run=start(rig,local_model=True)
    assert run['model_worker_id']=='w' and run['allow_during_gameplay'] is True
    assert run['automatic_model']['model']=='coder:3b' and len(rig.submitted)==1


def test_automatic_local_model_missing_inventory_stays_unavailable_no_fallback(rig):
    rig.store.put('worker','w',rig.worker | {'ollama':{}})
    rig.store.put('worker','other',rig.worker | {'id':'other'})
    run=start(rig,local_model=True)
    assert not rig.submitted and 'inventory' in run['automatic_model']['reason']


def test_stored_opt_out_prevents_automatic_local_compute(rig):
    rig.store.put('analysis_preferences','game',{'local_model':False})
    run=rig.manager.start(A.Start(session_id='w-launch'),'operator')
    assert not rig.submitted and not run['model_job_id']


def test_catalog_hash_absence_is_explicitly_unverified(rig):
    rig.store.catalog_update('game',hashes={})
    run=start(rig)
    assert run['evidence']['build_verification'].startswith('unverified')
    assert run['target']['build_hash'] is None


def test_exact_pso_native_block_links_its_crystal_even_with_large_telemetry(rig):
    frame={'schema':'gbox.pso.run-frame/1','session_id':'w-launch','game_id':'game','run_id':'a'*32,'seq':7,'observed_at':123}
    rig.manager.telemetry=lambda sid:{'stats':{'pso_review':frame,'large':'x'*40000}}
    run=start(rig)
    source=run['evidence']['pso_review']
    assert source['seq']==7 and source['crystal_url'].endswith('a'*32)
    assert not source['navigation_authority'] and not source['room_clear_inference']
    frame['session_id']='other';run=rig.manager.sample(run['id'])
    assert 'pso_review' not in run['evidence']


def test_authenticated_routes_start_read_preference_and_stop(rig, monkeypatch):
    monkeypatch.setattr(A,'Analysis',lambda *a,**kw:rig.manager)
    app=FastAPI();A.install(app,rig.store,lambda:'operator',submit=rig.manager.submit);c=TestClient(app)
    assert c.post('/api/analysis',json={'session_id':'w-launch','local_model':False,'mutate':True}).status_code==422
    run=c.post('/api/analysis',json={'session_id':'w-launch','local_model':False}).json()
    assert c.get('/api/analysis/'+run['id']).json()['state']=='running'
    pref=c.put('/api/analysis-preferences/game',json={'requested':{'extraction':True},'local_model':False}).json()
    assert pref['execution_enabled'] is False and pref['local_model'] is False
    assert c.get('/api/analysis-crystals/game').json()[0]['crystal']['sha256']
    assert c.post('/api/analysis/'+run['id']+'/stop',json={}).json()['state']=='cancelled'


def test_start_invalid_target_and_input_authority(rig):
    for kwargs in ({'session_id':'absent'}, {'session_id':'w-launch','game_id':'wrong'}, {'game_id':'absent'}):
        with pytest.raises(ValueError):rig.manager.start(A.Start(**kwargs),'operator')
    with pytest.raises(ValueError):A.Start(game_id='game',write_memory=True)
    with pytest.raises(ValueError):A.ModelRequest(worker_id='w',allow_during_gameplay='yes')
