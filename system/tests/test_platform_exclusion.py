"""excluded_platforms: a PC never runs a platform its gbox.toml excludes (operator 2026-11-10, of the Spark: "i only want
builds related to the switch version of RE on the spark. No more xbox or ps3 work on the spark.")."""
import platform
import random
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import config as C, platform_exclusion as PX
from gbox.config import Config
from gbox.models import Job, WorkerInfo
from gbox.server import create_app

SPARK_OUT = ['ps3', 'xbox', 'xbox360']
RE5_PS3, RE6_X360, DOA3_XBOX, SWITCH, NES = 'e7ca89bbeb67360d', '0871eee3b68cdea3', 'b8edf7040116f3aa', \
    'a' * 16, 'c' * 16
REQUEST = 'f' * 16


def entry(gid, plat, **kw):
    return {'game_id': gid, 'title': f'{plat} game {gid[:4]}', 'platform': plat, 'source_paths': [f'{gid}.iso'],
            'format': 'iso', 'profile_id': gid, 'launch': {'kind': 'emulator', 'path': f'{gid}.iso'}, **kw}


# an older catalog row of an original Xbox game: platform windows_native, its physical collection says Xbox
DOA3 = entry(DOA3_XBOX, 'windows_native', launch={'kind': 'emulator', 'rel_path': 'collections/Microsoft Xbox/DOA3/default.xbe'})


# ------------------------------------------------------------------------------------------------ the config key

def test_the_key_is_per_os_or_host_and_a_node_excludes_every_entry_naming_it():
    table = {'lilspark': ['PS3', 'Xbox 360', 'xbox'], 'linux': ['psp'], 'windows': ['ps4'], 'i9-NUC': ['ps2']}
    assert PX.for_node(table, os_name='linux', host='lilspark') == ['ps3', 'psp', 'xbox', 'xbox360']
    assert PX.for_node(table, os_name='linux', host='LILSPARK.local') == ['ps3', 'psp', 'xbox', 'xbox360']
    assert PX.for_node(table, os_name='linux', host='lilspark2') == ['psp']        # another Linux PC: its OS only
    assert PX.for_node(table, 'i9-nuc', os_name='windows', host='DESKTOP-1') == ['ps2', 'ps4']   # by worker name
    assert PX.for_node({}, os_name='linux', host='lilspark') == []
    assert Config().excluded_platforms == {} and Config().excluded_platforms_for('lilspark') == []
    # forgiving shapes, so a hand edit never stops the service: one platform as a string, a bare list (every node
    # that reads the file: a host's own gbox.local-<host>.toml)
    assert Config(excluded_platforms={'lilspark': 'PS3'}).excluded_platforms_for('lilspark') == ['ps3']
    assert Config(excluded_platforms=['xbox', 'ps3']).excluded_platforms_for() == ['ps3', 'xbox']


def test_the_key_loads_from_gbox_toml_and_the_host_overlay(tmp_path):
    base = tmp_path / 'gbox.toml'
    base.write_text('excluded_platforms = { windows = ["ps4"] }\n')
    C.local_overlay(base).write_text('excluded_platforms = { lilspark = ["ps3", "xbox", "xbox360"] }\n')
    cfg = C.load(base)
    assert cfg.excluded_platforms == {'windows': ['ps4'], 'lilspark': SPARK_OUT}
    assert set(cfg.excluded_platforms_for('lilspark')) >= set(SPARK_OUT)
    assert 'ps3' not in cfg.excluded_platforms_for('i9-NUC') or platform.node().casefold() == 'lilspark'


def test_the_worker_reports_its_exclusions_in_its_registration(cfg, monkeypatch):
    from gbox import ollama_assist, worker
    monkeypatch.setattr(ollama_assist, 'inventory', lambda: {})
    cfg.excluded_platforms = {'lilspark': SPARK_OUT}
    assert worker.describe(cfg, 'lilspark').excluded_platforms == SPARK_OUT
    assert worker.describe(cfg, 'i9-NUC').excluded_platforms == ([] if platform.node().casefold() != 'lilspark'
                                                                 else SPARK_OUT)


def test_a_game_platform_reads_old_xbox_rows_as_xbox():
    assert PX.game_platform(entry(RE5_PS3, 'PS3')) == 'ps3'
    assert PX.game_platform(DOA3) == 'xbox'
    assert PX.game_platform(entry(NES, 'windows_native')) == 'windows_native'


# ------------------------------------------------------------------------------------------------ routing

@pytest.fixture
def lab(cfg):
    app = create_app(cfg)
    store = app.state.store
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    tools = ['launch_game', 'autoplay', 'session_op', 'ghidra_script', 'get_frame']
    spark = WorkerInfo(id='spark', name='lilspark', os='linux', tools=tools, excluded_platforms=SPARK_OUT)
    nuc = WorkerInfo(id='nuc', name='i9-NUC', os='windows', tools=tools, features=['two_percent_audio'],
                     idle_seconds=3600)
    for w in (spark, nuc):
        assert client.post('/api/workers/register', json=w.model_dump()).status_code == 200
    store.upsert_catalog([entry(RE5_PS3, 'ps3'), entry(RE6_X360, 'xbox360'), DOA3, entry(SWITCH, 'switch'),
                          entry(NES, 'nes')])
    yield client, store
    client.close()


def queue(client, tool, inp, **kw):
    response = client.post('/api/jobs', json={'tool': tool, 'input': inp, **kw})
    assert response.status_code == 200, response.text
    return response.json()


def test_registration_shows_the_exclusions(lab):
    client, _ = lab
    rows = {w['name']: w for w in client.get('/api/workers').json()}
    assert rows['lilspark']['excluded_platforms'] == SPARK_OUT and rows['i9-NUC']['excluded_platforms'] == []
    status = client.get('/api/background/workers/lilspark/status')
    if status.status_code == 200:
        assert status.json()['worker']['excluded_platforms'] == SPARK_OUT


@pytest.mark.parametrize('gid,what', [(RE5_PS3, 'PS3'), (RE6_X360, 'Xbox 360'), (DOA3_XBOX, 'Xbox')])
def test_a_launch_pinned_to_the_spark_is_rejected_with_the_named_error(lab, gid, what):
    client, store = lab
    job = client.post(f'/api/games/{gid}/launch', params={'node': 'lilspark'}).json()
    assert job['state'] == 'rejected' and job['require_worker'] == 'spark'
    assert job['error'].startswith(f'PlatformExcluded: lilspark does not run {what} work')
    assert client.post('/api/workers/spark/claim').status_code == 204


def test_a_linux_launch_that_only_the_spark_could_take_is_rejected(lab):
    client, _ = lab
    job = client.post(f'/api/games/{RE5_PS3}/launch', params={'node': 'linux'}).json()
    assert job['state'] == 'rejected'
    assert job['error'].startswith('PlatformExcluded: no online PC that could take this job runs PS3 work: lilspark')
    x360 = queue(client, 'launch_game', {'game': entry(RE6_X360, 'xbox360')}, require_os='linux')
    assert x360['state'] == 'rejected' and 'Xbox 360' in x360['error']


def test_switch_work_still_goes_to_the_spark_and_ps3_to_the_other_pc(lab):
    client, _ = lab
    switch = client.post(f'/api/games/{SWITCH}/launch', params={'node': 'lilspark'}).json()
    assert switch['state'] == 'queued' and switch['require_worker'] == 'spark'
    claimed = client.post('/api/workers/spark/claim')
    assert claimed.status_code == 200 and claimed.json()['id'] == switch['id']
    assert claimed.json()['game_platforms'] == ['switch']        # handed over for the worker's own refusal
    ps3 = client.post(f'/api/games/{RE5_PS3}/launch').json()      # automatic play: a Windows PC
    assert ps3['state'] == 'queued' and ps3['require_worker'] in (None, 'nuc') and ps3['require_os'] in (None, 'windows')
    nuc = client.post(f'/api/games/{RE5_PS3}/launch', params={'node': 'i9-NUC'}).json()
    assert nuc['state'] == 'queued' and nuc['require_worker'] == 'nuc'


def test_the_spark_never_claims_an_unpinned_ps3_job_and_the_other_pc_does(lab):
    client, store = lab
    job = queue(client, 'launch_game', {'game': entry(RE5_PS3, 'ps3')})
    assert job['state'] == 'queued' and job['require_worker'] is None
    assert client.post('/api/workers/spark/claim').status_code == 204
    wait = store.get('job', job['id'])['admission_wait']
    assert wait['code'] == 'platform_excluded' and wait['worker'] == 'lilspark' and 'PS3' in wait['reason']
    claimed = client.post('/api/workers/nuc/claim')
    assert claimed.status_code == 200 and claimed.json()['id'] == job['id'] and 'admission_wait' not in claimed.json()


def test_an_agent_launch_never_picks_the_spark_as_its_candidate(lab):
    client, store = lab
    job = queue(client, 'launch_game', {'game': entry(RE5_PS3, 'ps3')}, agent_use=True)
    assert job['state'] == 'queued' and job['require_worker'] in (None, 'nuc')


@pytest.mark.parametrize('pinned', [{'require_worker': 'spark'}, {'require_worker': 'lilspark'}, {'require_os': 'linux'}])
def test_a_queued_job_from_before_the_setting_fails_at_claim_when_only_the_spark_could_take_it(lab, pinned):
    client, store = lab
    old = Job(tool='launch_game', input={'game': entry(RE5_PS3, 'ps3')}, **pinned).model_dump(mode='json')
    store.put('job', old['id'], old)
    assert client.post('/api/workers/spark/claim').status_code == 204
    failed = store.get('job', old['id'])
    assert failed['state'] == 'failed' and failed['error'].startswith('PlatformExcluded: lilspark does not run PS3 work')
    assert 'admission_wait' not in failed


def test_session_jobs_follow_the_session_game_and_wind_down_is_never_refused(lab):
    client, store = lab
    sid = 'spark-old'                                # a PS3 game that was running when the setting arrived
    store.put('session', sid, {'session_id': sid, 'game_id': RE5_PS3, 'state': 'running', 'started': 1})
    play = queue(client, 'autoplay', {'session_id': sid, 'op': 'start'})
    assert play['state'] == 'rejected' and play['error'].startswith('PlatformExcluded: lilspark')
    stop = queue(client, 'session_op', {'session_id': sid, 'op': 'stop_game', 'args': {}})
    assert stop['state'] == 'queued'
    claimed = client.post('/api/workers/spark/claim')
    assert claimed.status_code == 200 and claimed.json()['id'] == stop['id']


def test_a_job_without_its_own_game_follows_its_parent_request(lab):
    client, store = lab
    store.put('request', REQUEST, {'id': REQUEST, 'number': 7, 'title': 'RE5 PS3 analysis', 'status': 'open',
                                   'context': {'game_id': RE5_PS3}})
    job = queue(client, 'ghidra_script', {'binary_path': '/x/EBOOT.ELF', 'script': 'X.java'},
                require_worker='lilspark', parent_request_id=REQUEST)
    assert job['state'] == 'rejected' and 'PS3' in job['error']
    other = queue(client, 'ghidra_script', {'binary_path': '/x/EBOOT.ELF', 'script': 'X.java'}, require_worker='nuc',
                  parent_request_id=REQUEST)
    assert other['state'] == 'queued'
    plain = queue(client, 'ghidra_script', {'binary_path': '/x/main.nso', 'script': 'X.java'}, require_worker='lilspark')
    assert plain['state'] == 'queued'


def test_a_worker_without_exclusions_is_unchanged(lab):
    client, store = lab
    for gid in (RE5_PS3, RE6_X360, DOA3_XBOX, NES):
        job = client.post(f'/api/games/{gid}/launch', params={'node': 'i9-NUC'}).json()
        assert job['state'] == 'queued', job


# ------------------------------------------------------------------------------------------------ the worker refuses

def test_the_worker_refuses_a_job_on_an_excluded_platform_before_running_it(monkeypatch, tmp_path):
    from gbox import worker as W
    ran, delivered = [], []
    monkeypatch.setattr(W, 'execute', lambda name, inp, ctx: ran.append(name) or {})
    monkeypatch.setattr(W, '_deliver_finished', lambda *a: delivered.append(a[3]))
    cfg = Config(data_dir=tmp_path, runtime_dirs={'linux': str(tmp_path), 'windows': str(tmp_path)})
    job = {'id': 'j1', 'tool': 'launch_game', 'input': {'game': entry(RE5_PS3, 'ps3')}}
    W._run_job(job, cfg, 'spark', 'http://control', {}, None, set(), set(), set(), None,
               excluded=SPARK_OUT, name='lilspark')
    assert not ran and delivered[0]['ok'] is False
    assert delivered[0]['error'].startswith('PlatformExcluded: lilspark does not run PS3 work')
    # the platform the control plane stamped at claim, and a session this worker runs
    assert PX.local_reason(SPARK_OUT, {'tool': 'characters', 'input': {}, 'game_platforms': ['xbox360']}, {}, 'lilspark')
    sessions = {'spark-1': (object(), entry(RE5_PS3, 'ps3'))}
    assert PX.local_reason(SPARK_OUT, {'tool': 'autoplay', 'input': {'session_id': 'spark-1'}}, sessions, 'lilspark')
    assert PX.local_reason(SPARK_OUT, {'tool': 'session_op', 'input': {'session_id': 'spark-1', 'op': 'stop_game'}},
                           sessions, 'lilspark') is None
    delivered.clear()
    W._run_job(job | {'input': {'game': entry(SWITCH, 'switch')}}, cfg, 'spark', 'http://control', {}, None,
               set(), set(), set(), None, excluded=SPARK_OUT, name='lilspark')
    assert ran == ['launch_game'] and delivered[0]['ok'] is True


def test_the_adapter_chooser_refuses_an_excluded_platform():
    from gbox import adapters
    cfg = Config(excluded_platforms={platform.node(): ['ps3', 'xbox']})
    with pytest.raises(PX.PlatformExcluded, match='does not run PS3 work'):
        adapters.for_game(entry(RE5_PS3, 'ps3'), cfg)
    with pytest.raises(PX.PlatformExcluded, match='does not run Xbox work'):
        adapters.for_game(DOA3, cfg)


# ------------------------------------------------------------------------------------------------ MercMode

def spark_rig():
    from tests.test_mercmode import rig
    store, w, saver, calls, now, tick = rig()          # lilspark: RE4 (GameCube) and RE5 (PS3) both verified there
    w['excluded_platforms'] = list(SPARK_OUT)
    return store, w, saver, calls, now, tick


def test_mercmode_titles_on_an_excluded_platform_are_unavailable_on_that_pc_only():
    from gbox import mercmode as M
    store, w, *_ = spark_rig()
    rows = {r['title']: r for r in M.inventory(store, w)}
    assert not rows['re5']['playable'] and 'lilspark does not run PS3 work' in rows['re5']['reason']
    assert rows['re4']['playable']
    other = {r['title']: r for r in M.inventory(store, dict(w, excluded_platforms=[]))}
    assert other['re5']['playable']                    # usable on a PC that runs PS3
    with pytest.raises(LookupError, match='does not run PS3 work'):
        M.plan_dispatch(store, w, {}, command='switch', title='re5', operator=True)


def test_mercmode_skips_an_excluded_title_instead_of_launching_it():
    from gbox import mercmode as M, screensaver as S
    store, w, saver, calls, now, tick = spark_rig()
    M.configure(store, w['name'], {'enabled': True, 'keep_warm': 0, 'titles': ['re4', 're5']})
    tick()
    assert [c['input']['game']['game_id'] for c in calls if c['tool'] == 'launch_game'] == [M.TITLES['re4']['game_ids'][0]]
    store, w, saver, calls, now, tick = spark_rig()
    M.configure(store, w['name'], {'enabled': True, 'keep_warm': 0, 'titles': ['re5']})
    out = tick()
    assert not calls and 'does not run PS3 work' in out[w['name']]


# ------------------------------------------------------------------------------------------------ screensaver / roulette

@pytest.mark.parametrize('seed', range(4))
def test_the_screensaver_plays_only_games_the_pc_runs(seed):
    from tests.test_screensaver import rig
    s, w, saver, calls, tick = rig()
    saver.rng = random.Random(seed)
    platforms = {'pso': 'ps3', 'sc': 'gamecube'}         # PSO is by far the most played: it would come up first
    s.catalog_get = lambda gid: {'game_id': gid, 'title': gid, 'platform': platforms.get(gid, 'nes')}
    w['excluded_platforms'] = ['ps3']
    tick()
    assert calls[0]['input']['game']['game_id'] == 'sc'
    w['excluded_platforms'] = ['ps3', 'gamecube']
    assert saver._runnable(w, [{'game_id': 'pso'}, {'game_id': 'sc'}]) == []


def test_the_roulette_builder_skips_targets_no_build_node_runs(monkeypatch):
    from gbox import roulette
    monkeypatch.setattr(roulette, 'writer_ok', lambda game: True)
    platforms = {'a': 'ps3', 'b': 'gamecube'}
    store = SimpleNamespace(catalog_get=lambda gid: {'game_id': gid, 'title': gid, 'platform': platforms[gid]},
                            all=lambda kind: [])
    skip = lambda game: 'excluded' if PX.game_platform(game) in SPARK_OUT else None
    b = roulette.Builder(store, None, lambda gid: [], lambda: [{'game_id': 'a'}, {'game_id': 'b'}], skip=skip)
    assert [t['game_id'] for t in b.targets()] == ['b']


# ------------------------------------------------------------------------------------------------ favorite unlocks

def test_favorite_unlock_research_skips_a_platform_every_research_worker_excludes(lab):
    client, store = lab
    hold = client.app.state.custom_build_unlocks_platform_hold
    assert hold(RE5_PS3).startswith('Skipped: lilspark does not run PS3 work')
    assert hold(DOA3_XBOX).startswith('Skipped: lilspark does not run Xbox work')
    assert hold(SWITCH) == ''
    spare = WorkerInfo(id='spare', name='lilspark2', os='linux', tools=['ghidra_script'])
    client.post('/api/workers/register', json=spare.model_dump())
    assert hold(RE5_PS3) == ''                       # another Linux research worker runs PS3


# ------------------------------------------------------------------------------------------------ Hermes queue

def test_hermes_holds_items_on_platforms_this_machine_never_runs(monkeypatch):
    from gbox import hermes_work_queue as q
    favorites = [{'game_id': g, 'title': g, 'platform': p, 'in_catalog': True}
                 for g, p in ((RE5_PS3, 'ps3'), (SWITCH, 'switch'))]
    data = {'version': 1, 'items': {}}
    q.sync(data, {'count': 2, 'items': favorites}, [], now=1000)
    picked = lambda excluded: sorted(i['game_id'] for _k, i in q.candidates(data, [], [], set(), set(), now=1001,
                                                                            excluded=excluded))
    assert picked(frozenset()) == sorted([RE5_PS3, SWITCH])
    assert picked(frozenset(SPARK_OUT)) == [SWITCH]
    hold = data['items']['favorite:' + RE5_PS3]['platform_hold']
    assert hold.startswith('skipped: ') and 'does not run PS3 work' in hold
    assert picked(frozenset()) == sorted([RE5_PS3, SWITCH])     # the setting lifted: dispatched again
    assert 'platform_hold' not in data['items']['favorite:' + RE5_PS3]


def test_hermes_looks_an_inbox_tickets_platform_up_once_and_reads_this_hosts_registration(monkeypatch):
    from gbox import hermes_work_queue as q
    data = {'version': 1, 'items': {'inbox:' + REQUEST: {'lane': 'inbox', 'request_id': REQUEST, 'game_id': RE6_X360}}}
    asked = []
    monkeypatch.setattr(q, '_api', lambda path: asked.append(path) or {'game_id': RE6_X360, 'platform': 'xbox360'})
    q._fill_platforms(data)
    q._fill_platforms(data)
    assert asked == ['/api/catalog/' + RE6_X360] and q.item_platform(data['items']['inbox:' + REQUEST]) == 'xbox360'
    assert q.platform_hold(data['items']['inbox:' + REQUEST], frozenset(SPARK_OUT))
    workers = [{'id': 's', 'name': 'lilspark', 'os': 'linux', 'excluded_platforms': SPARK_OUT},
               {'id': 'n', 'name': 'i9-NUC', 'os': 'windows', 'excluded_platforms': ['nes']}]
    monkeypatch.setattr(q, '_api', lambda path: workers)
    assert PX.host_exclusions(workers, host='lilspark') == frozenset(SPARK_OUT)
    assert PX.host_exclusions(workers, host='some-other-linux-box') == frozenset(SPARK_OUT)   # the Linux worker
    assert PX.host_exclusions(workers, host='i9-NUC') == frozenset({'nes'})
    monkeypatch.setattr(q, '_api', lambda path: (_ for _ in ()).throw(RuntimeError('offline')))
    assert q._host_exclusions() == frozenset()


# ------------------------------------------------------------------------------------------------ the Spark helper

def test_the_spark_helper_chores_skip_excluded_games():
    from gbox import spark_grunt as G
    ps3 = {'lane': 'favorite', 'game_id': RE5_PS3, 'platform': 'ps3'}
    switch = {'lane': 'favorite', 'game_id': SWITCH, 'platform': 'switch'}
    runs = []
    ctx = SimpleNamespace(queue_favorites=lambda: [ps3, switch],
                          run_job=lambda tool, inp, gw, timeout_s: runs.append(inp['game_id']) or {'state': 'failed'},
                          excluded_game=lambda g, excluded=None: (g.get('platform') if isinstance(g, dict) else g)
                          in ('ps3', RE5_PS3))
    G.fingerprints(ctx, lambda: None)
    assert runs == [SWITCH]
    catalog = {RE5_PS3: entry(RE5_PS3, 'ps3'), SWITCH: entry(SWITCH, 'switch')}
    store = SimpleNamespace(catalog_get=catalog.get)
    spark = {'id': 's', 'name': 'lilspark', 'os': 'linux', 'excluded_platforms': SPARK_OUT}
    svc = G.ServiceContext(store=store, config=Config(), submit=None, cancel=lambda j: None, workers=lambda: [spark])
    assert svc.excluded_here() == frozenset(SPARK_OUT)
    assert svc.excluded_game(RE5_PS3) and svc.excluded_game(ps3) and svc.excluded_game(catalog[RE5_PS3])
    assert not svc.excluded_game(SWITCH) and not svc.excluded_game(switch)
    assert svc.excluded_game(DOA3) and not svc.excluded_game(RE5_PS3, excluded=['xbox'])


def test_the_spark_helper_never_verifies_a_launch_on_a_node_that_excludes_its_game():
    import time as _time
    from gbox import spark_grunt as G
    from tests.test_spark_grunt import FakeCtx, req
    now = _time.time()
    done = req('d' * 16, 'Auto report: launch failed in RE5', now - 100, status='done', completed=now - 50,
               context={'game_id': RE5_PS3})
    runs = []
    ctx = FakeCtx(requests=lambda: [done], verify_node=lambda: {'name': 'lilspark', 'excluded_platforms': SPARK_OUT},
                  run_job=lambda tool, inp, gw, timeout_s: runs.append(inp) or {'state': 'succeeded', 'output': {}})
    ctx.excluded_game = lambda g, excluded=None: g == RE5_PS3 and 'ps3' in (excluded or ())
    out = G.verify_launch_fixes(ctx, lambda: None)
    assert not runs and 'lilspark excludes' in out['waiting']


def test_the_sonic_showcase_skips_a_title_no_build_node_runs(cfg):
    from gbox import sonic_showcase
    spark = {'id': 's', 'name': 'lilspark', 'os': 'linux', 'online': True, 'excluded_platforms': SPARK_OUT}
    svc = sonic_showcase.Showcase(SimpleNamespace(), cfg, workers=lambda: [spark])
    assert svc.platform_hold(entry(RE6_X360, 'xbox360')).startswith('skipped: lilspark does not run Xbox 360 work')
    assert svc.platform_hold(entry(SWITCH, 'switch')) == ''
    svc.workers = lambda: [spark, {'id': 'x', 'name': 'other', 'os': 'linux', 'online': True}]
    assert svc.platform_hold(entry(RE6_X360, 'xbox360')) == ''
