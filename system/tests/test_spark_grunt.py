"""The Spark helper: a registry of LLM-free chores, one at a time, with cooldowns, that gives way to the operator."""
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import spark_grunt as G
from gbox.config import Config


class Clock:
    def __init__(self, t=10_000.0):
        self.t = t

    def __call__(self):
        return self.t


def registry(chores, gate=lambda: None, clock=None, **kw):
    return G.Registry(chores, gate, SimpleNamespace(), clock=clock or Clock(), **kw)


def test_one_chore_per_tick_oldest_first_with_cooldowns(tmp_path):
    ran, clock = [], Clock()
    chores = [G.Chore('a', 'A', 100, lambda ctx, gw: ran.append('a') or {'n': 1}),
              G.Chore('b', 'B', 1000, lambda ctx, gw: ran.append('b'))]
    reg = registry(chores, clock=clock, state_path=tmp_path / 'grunt.json')
    assert reg.tick()['ran'] == 'a' and reg.tick()['ran'] == 'b' and reg.tick() == {'idle': True}
    clock.t += 150
    assert reg.tick()['ran'] == 'a' and reg.tick() == {'idle': True}
    assert ran == ['a', 'b', 'a']
    again = registry(chores, clock=clock, state_path=tmp_path / 'grunt.json')    # state survives a restart
    assert again.tick() == {'idle': True}
    again.force('b')
    assert again.tick()['ran'] == 'b'
    with pytest.raises(KeyError):
        again.force('nope')


def test_gate_stops_the_helper_and_a_running_chore_gives_way():
    busy = [None]
    seen = {}

    def long_chore(ctx, give_way):
        seen['label'] = reg.status()['label']
        busy[0] = 'the operator is playing Soulcalibur on the Spark'
        give_way()
        raise AssertionError('should have yielded')
    reg = registry([G.Chore('long', 'Long', 60, long_chore, 'doing the long thing')], gate=lambda: busy[0])
    out = reg.tick()
    assert seen['label'] == 'Spark helper: doing the long thing'
    assert out['result'] == {'yielded': 'the operator is playing Soulcalibur on the Spark'}
    assert reg.tick() == {'waiting': 'the operator is playing Soulcalibur on the Spark'}
    assert reg.status()['label'] == 'Spark helper waiting: the operator is playing Soulcalibur on the Spark'
    busy[0] = None
    assert reg.due()[0].name == 'long'                         # a chore that gave way is due again at once


def test_errors_are_recorded_and_disabled_chores_never_run():
    def broken(ctx, gw):
        raise RuntimeError('boom')
    reg = registry([G.Chore('x', 'X', 60, broken), G.Chore('off', 'Off', 60, lambda c, g: 1 / 0)], disabled={'off'})
    assert reg.tick()['result'] == {'error': 'RuntimeError: boom'}
    assert reg.tick() == {'idle': True}
    status = {c['name']: c for c in reg.status()['chores']}
    assert status['x']['errors'] == 1 and status['x']['last_status'] == 'error'
    assert status['off']['enabled'] is False and status['off']['next_run_at'] is None
    reg.set_enabled(False)
    assert reg.tick() == {'waiting': 'paused by the operator'}


def test_builds_and_operator_sessions_gate_but_agent_tests_do_not():
    assert G.is_build({'tool': 'characters', 'input': {'op': 'use', 'game_id': 'g'}})
    assert G.is_build({'tool': 'pso_mods_tool', 'input': {}})
    assert not G.is_build({'tool': 'launch_game', 'input': {}})
    assert not G.is_build({'tool': 'characters', 'input': {'op': 'live_use', 'session_id': 's'}})
    assert not G.is_build({'tool': 'characters', 'input': {'op': 'collect'}})
    workers = [{'id': 'sp', 'name': 'lilspark', 'os': 'linux'}, {'id': 'pc', 'name': 'JAYBUILTFINALE', 'os': 'windows'}]
    spark = G.spark_workers(workers, local_name='lilspark')
    assert spark == {'sp'}
    sessions = [{'session_id': 'pc-1', 'state': 'running'}, {'session_id': 'sp-2', 'state': 'running'},
                {'session_id': 'sp-3', 'state': 'ended'}]
    labels = {'sp-2': {'label': 'Evidence capture: x', 'owner': 'agent'}}
    assert G.operator_session_on(sessions, labels, spark) is None
    assert G.operator_session_on(sessions, {}, spark)['session_id'] == 'sp-2'


class FakeCtx(SimpleNamespace):
    def __init__(self, **kw):
        super().__init__(posted=[], prioritized=[], comments=[], **kw)
        self._mem = {}

    def memory(self, name):
        return self._mem.setdefault(name, {})

    def post(self, rid, text):
        self.posted.append((rid, text))

    def prioritize(self, ids):
        self.prioritized += list(ids)

    def comment_pull(self, number, text):
        self.comments.append((number, text))


def req(rid, title, created, status='open', **kw):
    return {'id': rid, 'number': int(created) % 1000, 'title': title, 'body': '', 'created': created,
            'status': status, **kw}


def test_triage_classifies_dedupes_attaches_and_prioritizes():
    now = time.time()
    old = req('a' * 16, 'Soulcalibur fails to launch on Dolphin', now - 5000, context={'game_id': 'g1'})
    ctx = FakeCtx(requests=lambda: [old], failed_jobs=lambda gid, since: [])
    assert G.triage_inbox(ctx, lambda: None) == {'primed': 1}       # the backlog is not re-noted
    new = req('b' * 16, 'Soulcalibur fails to launch on Dolphin again', now - 10, context={'game_id': 'g1'})
    ui = req('c' * 16, 'Move the dock button', now - 5)
    ctx.requests = lambda: [old, new, ui]
    ctx.failed_jobs = lambda gid, since: [{'id': 'job9', 'tool': 'launch_game', 'error': 'dolphin exited 3'}]
    out = G.triage_inbox(ctx, lambda: None)
    assert out['triaged'] == 2 and out['kinds'] == {'launch_failure': 1, 'ui': 1}
    assert ctx.prioritized == ['b' * 16]
    (rid, text), = ctx.posted
    assert rid == 'b' * 16 and 'Possible duplicate of' in text and 'job9' in text
    assert G.triage_inbox(ctx, lambda: None)['triaged'] == 0      # never triaged twice


def test_draft_pr_tests_run_once_per_head_and_report_without_merging(tmp_path):
    body = 'gBox request #12 (0123456789abcdef).\n\nFix'
    pulls = [{'number': 7, 'headRefName': 'hermes/request-12-1', 'headRefOid': 'a' * 40, 'isDraft': True, 'body': body},
             {'number': 8, 'headRefName': 'feature/x', 'headRefOid': 'b' * 40, 'isDraft': True, 'body': ''},
             {'number': 9, 'headRefName': 'hermes/request-13-1', 'headRefOid': 'c' * 40, 'isDraft': False, 'body': ''}]
    tested = []
    ctx = FakeCtx(draft_pulls=lambda: pulls,
                  test_pull=lambda p, gw: tested.append(p['number']) or {'summary': '3 passed', 'tests': ['tests/test_x.py']})
    out = G.draft_pr_tests(ctx, lambda: None)
    assert out == {'pr': 7, 'summary': '3 passed', 'request_id': '0123456789abcdef'} and tested == [7]
    assert ctx.comments[0][0] == 7 and '3 passed' in ctx.comments[0][1] and 'no merge' in ctx.comments[0][1]
    assert ctx.posted[0][0] == '0123456789abcdef'
    assert G.draft_pr_tests(ctx, lambda: None) == {'open_drafts': 3, 'tested': 0}
    pulls[0]['headRefOid'] = 'd' * 40                              # a new push is tested again
    assert G.draft_pr_tests(ctx, lambda: None)['pr'] == 7


def test_focused_test_selection_and_summary(tmp_path):
    (tmp_path / 'tests').mkdir()
    for name in ('test_hermes_local.py', 'test_hermes_local_route.py', 'test_other.py'):
        (tmp_path / 'tests' / name).write_text('')
    changed = ['system/gbox/hermes_local.py', 'system/tests/test_other.py', 'system/docs/x.md']
    assert G.select_tests(changed, tmp_path) == ['tests/test_other.py', 'tests/test_hermes_local.py',
                                                 'tests/test_hermes_local_route.py']
    assert G.pytest_summary('=== 3 passed, 1 failed in 2s ===') == '3 passed, 1 failed'
    assert G.pytest_summary('') == 'no pytest summary'


class FakeStore:
    def __init__(self, sessions=(), excluded=()):
        self.sessions, self.excluded, self.jobs_db = list(sessions), list(excluded), {}
        self.lock = __import__('threading').RLock()

    def all(self, kind):
        return self.sessions if kind == 'session' else []

    def get(self, kind, key):
        if kind == 'setting':
            return {'excluded': self.excluded}
        return self.jobs_db.get(key) if kind == 'job' else None


def service(workers, store=None, **cfg):
    config = Config()
    config.hermes.grunt = config.hermes.grunt.model_copy(update=cfg)
    return G.ServiceContext(store=store or FakeStore(), config=config, submit=None, cancel=lambda j: None,
                            workers=lambda: workers)


def test_verification_launches_only_on_allowed_idle_nodes_never_jaybuiltfinale(monkeypatch):
    monkeypatch.delenv('GBOX_OPERATOR_WORKER', raising=False)
    jay = {'id': 'j', 'name': 'JAYBUILTFINALE', 'os': 'windows', 'online': True, 'idle_seconds': 99999}
    nuc = {'id': 'n', 'name': 'i9-NUC', 'os': 'windows', 'online': True, 'idle_seconds': 60}
    spark = {'id': 's', 'name': 'lilspark', 'os': 'linux', 'online': True, 'idle_seconds': None}
    assert service([jay], verify_nodes=['JAYBUILTFINALE']).verify_node() is None   # never, even when listed
    assert service([jay, nuc]).verify_node() is None                                # the NUC is in use
    nuc['idle_seconds'] = 3600
    assert service([jay, nuc]).verify_node()['name'] == 'i9-NUC'
    assert service([jay, nuc], store=FakeStore(excluded=['i9-NUC'])).verify_node() is None   # unticked in Tasks
    assert service([nuc, spark], store=FakeStore(sessions=[{'session_id': 'n-1', 'state': 'running'}])
                   ).verify_node()['name'] == 'lilspark'
    monkeypatch.setenv('GBOX_OPERATOR_WORKER', 'i9-NUC')
    assert service([nuc]).verify_node() is None


def test_verify_launch_fixes_posts_the_evidence_result():
    now = time.time()
    done = req('d' * 16, 'Auto report: launch failed in Crazy Taxi', now - 100, status='done',
               completed=now - 50, context={'game_id': 'ct'})
    runs = []
    ctx = FakeCtx(requests=lambda: [done], verify_node=lambda: {'name': 'i9-NUC'},
                  run_job=lambda tool, inp, gw, timeout_s: runs.append((tool, inp)) or {
                      'id': 'ev1', 'state': 'succeeded',
                      'output': {'runs': [{'reached': True}], 'frames': [{'sha256': 'f' * 64}]}})
    out = G.verify_launch_fixes(ctx, lambda: None)
    assert out == {'request': done['number'], 'node': 'i9-NUC', 'reached': True, 'state': 'succeeded'}
    assert runs == [('evidence_capture', {'game_id': 'ct', 'node': 'i9-NUC'})]
    assert 'reached gameplay' in ctx.posted[0][1]
    assert G.verify_launch_fixes(ctx, lambda: None) == {'tickets': 0}


def test_waiting_for_a_job_cancels_it_when_the_spark_gets_busy():
    store = FakeStore()
    store.jobs_db['j1'] = {'id': 'j1', 'state': 'running'}
    cancelled = []
    ctx = G.ServiceContext(store=store, config=Config(), submit=lambda t, i: {'id': 'j1', 'state': 'running'},
                           cancel=cancelled.append, workers=lambda: [], poll_s=0)

    def give_way():
        raise G.Yielded('a build is running (characters use)')
    with pytest.raises(G.Yielded):
        ctx.run_job('characters', {'op': 'readiness'}, give_way)
    assert cancelled == ['j1'] and 'j1' in ctx.jobs_started


def test_fingerprint_chore_stores_the_compact_result():
    saved = {}
    ctx = FakeCtx(queue_favorites=lambda: [{'game_id': 'g1', 'fingerprint': {'source': 'error'}}, {'game_id': 'g2'}],
                  run_job=lambda tool, inp, gw, timeout_s: {'state': 'succeeded', 'output': {'result': {
                      'game_id': inp['game_id'], 'summary': 'Criterion RenderWare', 'engines': []}}},
                  save_fingerprint=lambda gid, fp: saved.update({gid: fp}))
    out = G.fingerprints(ctx, lambda: None)
    assert out['game_id'] == 'g1' and out['missing_left'] == 1 and 'g1' in saved


def test_mod_manifests_hash_once_per_marker(tmp_path):
    config = Config(data_dir=tmp_path / 'data', cache_dir=tmp_path / 'cache')
    mod = tmp_path / 'cache' / 'mods' / ('a' * 16) / 'my-mod'
    mod.mkdir(parents=True)
    (mod / '.gbox-mod.json').write_text('{"writer": "x"}')
    (mod / 'disc.iso').write_bytes(b'x' * 1000)
    ctx = SimpleNamespace(config=config)
    out = G.mod_manifests(ctx, lambda: None)
    assert out['hashed'] == 1 and out['bytes'] == 1015
    manifest = tmp_path / 'data' / 'built_mod_manifests' / ('a' * 16) / 'my-mod.json'
    assert len(__import__('json').loads(manifest.read_text())['files']['disc.iso']['sha256']) == 64
    assert G.mod_manifests(ctx, lambda: None)['hashed'] == 0


def test_grunt_endpoint_lists_chores_and_controls_the_helper(cfg, monkeypatch, tmp_path):
    from gbox.server import create_app
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'state'))
    app = create_app(cfg)
    client = TestClient(app, headers={'authorization': f'Bearer {cfg.token()}'})
    data = client.get('/api/grunt').json()
    assert {c['name'] for c in data['chores']} == {c.name for c in G.CHORES}
    assert data['alive'] is False                                  # never started in tests / on Windows
    assert client.post('/api/grunt', json={'run': 'warm_indexes'}).status_code == 200
    assert client.post('/api/grunt', json={'run': 'nope'}).status_code == 404
    assert client.post('/api/grunt', json={'enabled': False}).json()['enabled'] is False
    assert TestClient(app).get('/api/grunt').status_code == 401
    store = app.state.store
    store.put('worker', 'sp', {'id': 'sp', 'name': 'lilspark', 'os': 'linux', 'tools': [], 'last_seen': 9e12})
    store.put('job', 'b1', {'id': 'b1', 'tool': 'characters', 'state': 'running', 'input': {'op': 'cast_swap'}})
    app.state.grunt.set_enabled(True)
    assert app.state.grunt.tick() == {'waiting': 'a build is running (characters cast_swap)'}
    providers = client.get('/api/hermes/providers').json()
    assert providers['grunt']['label'].startswith('Spark helper')
    local = client.get('/api/hermes/local').json()
    assert local['model'] == 'gpt-oss:20b' and local['active'] is False
    assert client.post('/api/hermes/local', json={'local_only': True}).json()['local_only'] is True
    assert Path(tmp_path / 'state' / 'local-mode.json').exists()
