import concurrent.futures
import copy
import socket
from types import SimpleNamespace

import pytest

from gbox import level_strategy as S
from gbox import level_strategy_web as W
from gbox.mercs.titles import merc3d_strategy as M


def context():
    return {'game_id': 'game', 'build': 'verified-build', 'mod': '', 'level': '2-2',
            'title': 'Example game', 'platform': '3ds', 'actions': ['defeat_enemies', 'verify_result'], 'targets': {}}


def sources():
    return [{'id': 's1', 'url': 'https://example.com/guide', 'access': 'fetched', 'sha256': 'a'*64,
             'title': 'Guide', 'retrieved_at': 12, 'kind': 'guide'}]


def proposal(action='defeat_enemies', target='remaining enemies'):
    return {'summary': 'Finish the objective and verify the result.', 'objectives': [
        {'action': action, 'target': target, 'reason': 'Complete the observed objective.', 'source_ids': ['s1']},
        {'action': 'verify_result', 'target': 'result', 'source_ids': ['s1']}], 'route': ['Courtyard'], 'uncertainties': []}


def test_plan_keeps_citations_but_never_claims_completion():
    plan = S.validate_plan(proposal(), context(), sources())
    assert plan['objectives'][0]['executable']
    assert plan['sources'][0]['url'] == sources()[0]['url']
    assert plan['completion_verified'] is False


@pytest.mark.parametrize('change', [
    lambda p: p.update(buttons=['a']),
    lambda p: p['objectives'][0].update(source_ids=['invented']),
    lambda p: p['objectives'][0].update(address=0x123),
    lambda p: p.update(route=[{'x': 12, 'z': 80}]),
    lambda p: p['objectives'][0].update(action='execute_shell'),
    lambda p: p['objectives'].pop(),
])
def test_untrusted_plan_cannot_supply_controls_or_citations(change):
    p = proposal(); change(p)
    with pytest.raises(ValueError): S.validate_plan(p, context(), sources())


def test_search_snippet_is_not_fetched_evidence():
    src = sources(); src[0]['access'] = 'indexed'
    with pytest.raises(ValueError): S.validate_plan(proposal(), context(), src)


def test_unknown_target_is_explicitly_blocked_and_tutorial_cannot_be_combat():
    ctx = M.context({'mission_id': 0, 'enemies': []})
    with pytest.raises(ValueError, match='objective'):
        S.validate_plan(proposal(), ctx, sources())
    plan = S.validate_plan(proposal('follow_markers', 'active marker'), ctx, sources())
    assert not plan['objectives'][0]['executable']
    assert 'adapter' in plan['objectives'][0]['blocker']


@pytest.mark.parametrize('field,value', [('build','other'),('mod','modified'),('level','2-3'),('game_id','another')])
def test_store_isolates_game_build_mod_and_level(tmp_path, field, value):
    ctx = context(); store = S.Store(tmp_path)
    store.save(ctx, S.validate_plan(proposal(), ctx, sources()))
    assert store.plan(ctx)
    assert store.plan(dict(ctx, **{field: value})) is None


def test_survival_empty_enemy_list_and_timer_zero_do_not_complete():
    clock = [10.0]; monitor = S.Progress(lambda: clock[0], 20)
    monitor.observe(context(), {'enemies': [], 'score': 0, 'timer': 50})
    clock[0] += 25
    result = monitor.observe(context(), {'enemies': [], 'score': 0, 'timer': 0})
    assert result['stalled'] and result['replan']
    assert not result['completion_verified'] and not result['unlock_verified']
    result = monitor.observe(context(), {'native_objective_end': True})
    assert result['objective_ended'] and not result['mission_cleared']


def test_progress_requires_same_target_and_replans_are_rate_limited():
    clock = [1.0]; m = S.Progress(lambda: clock[0], 10)
    m.observe(context(), {'enemies': [{'ptr': 1, 'hp': 100}], 'score': 0})
    clock[0] = 8
    assert m.observe(context(), {'enemies': [{'ptr': 1, 'hp': 50}], 'score': 0})['progress_evidence'] == 'target_hp_decrease'
    clock[0] = 20
    assert m.observe(context(), {'enemies': [{'ptr': 2, 'hp': 10}], 'score': 0})['replan']
    clock[0] = 30
    assert not m.observe(context(), {'enemies': [{'ptr': 2, 'hp': 10}], 'score': 0})['replan']


def test_elapsed_restart_does_not_attribute_reused_actor_hp_drop():
    clock = [10.0]; m = S.Progress(lambda: clock[0])
    m.observe(context(), {'enemies': [{'ptr': 1, 'hp': 100}], 'elapsed': 80})
    clock[0] = 40
    result = m.observe(context(), {'enemies': [{'ptr': 1, 'hp': 50}], 'elapsed': 1})
    assert result['progress_evidence'] is None and not result['stalled']


def test_late_plan_from_previous_mission_is_not_activated(tmp_path):
    store = S.Store(tmp_path); ctx = context(); store.configure('game', True, {})
    future = concurrent.futures.Future()
    runtime = S.Runtime(lambda _: ctx, store=store, clock=lambda: 0)
    runtime.pending = (S.key(ctx), future)
    old = copy.deepcopy(ctx)
    ctx['level'] = '2-3'
    runtime.observe({})
    future.set_result(S.validate_plan(proposal(), old, sources()))
    runtime.last_request = 0
    assert runtime.observe({}) is None
    assert store.plan(ctx) is None


def test_failed_future_clears_and_does_not_repeat_immediately(tmp_path):
    ctx = context(); store = S.Store(tmp_path); store.configure('game', True, {})
    rt = S.Runtime(lambda _: ctx, store=store, clock=lambda: 5)
    future = concurrent.futures.Future(); future.set_exception(RuntimeError('provider offline'))
    rt.pending = (S.key(ctx), future); rt.last_request = 5
    assert rt.observe({}) is None and rt.pending is None
    assert rt.receipt['research_error'] == 'provider offline'
    assert rt.observe({}) is None and rt.pending is None


def test_disable_prevents_cached_plan_actuation(tmp_path):
    ctx = context(); store = S.Store(tmp_path)
    store.save(ctx, S.validate_plan(proposal(), ctx, sources()))
    store.configure('game', False, {})
    rt = S.Runtime(lambda _: ctx, store=store)
    assert rt.instruction({}) is None and not rt.receipt['enabled']


@pytest.mark.parametrize('url', ['file:///private/save','http://127.0.0.1/admin','http://user:secret@example.com/',
                               'http://example.com:18765/'])
def test_web_rejects_local_or_credentialed_urls(monkeypatch, url):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2,1,6,'',('127.0.0.1',80))])
    with pytest.raises(ValueError): W.public_url(url)


def test_research_queries_exact_level_fetches_and_sanitizes_live_data():
    ctx = context() | {'source_urls': ['https://example.com/guide'], 'ram_address': 12345,
                       'player': {'pos': [1,2,3]}, 'targets': {}}
    calls = []
    def search(query): calls.append(query); return []
    def fetcher(url): return sources()[0] | {'text': 'A readable source about this level. '*20}
    def synthesize(prompt):
        assert '12345' not in prompt and 'player' not in prompt
        assert 's1' in prompt
        return proposal()
    result = W.research(ctx, {}, search=search, fetcher=fetcher, synthesize=synthesize)
    assert 'Example game 3ds level 2-2' in calls[0]
    assert result['sources'][0]['access'] == 'fetched' and not result['live_verified']


def test_no_fetchable_sources_never_calls_model():
    with pytest.raises(ValueError, match='No readable'):
        W.research(context(), {}, search=lambda _: [{'url': 'https://example.com/guide'}],
                   fetcher=lambda _: (_ for _ in ()).throw(ValueError('blocked')),
                   synthesize=lambda _: pytest.fail('No evidence must not call model'))


def test_merc3d_labels_use_native_level_tab_not_hex_string():
    ctx = M.context({'mission_id': 0x0101})
    assert ctx['level'] == '2-2' and '20 Town Majini' in ctx['objective']
    assert M.context({'mission_id': None}) is None


def test_default_merc3d_sources_keep_fetched_fallback_after_manual_and_guide_fail():
    ctx = M.context({'mission_id': 0x0101, 'enemies': []})
    assert len(ctx['source_urls']) <= 4  # Worker transport and fetch budget.
    requested = []
    def fetcher(url):
        requested.append(url)
        if url in (W.MANUAL, W.GUIDE):
            raise ValueError('Source unavailable')
        assert url == 'https://tasvideos.org/Forum/Topics/23732'
        return sources()[0] | {'url': url, 'text': 'Mission 2-2 requires defeating all20 enemies. '*5}
    plan = W.research(ctx, {}, search=lambda _: [], fetcher=fetcher, synthesize=lambda _: proposal())
    assert requested == ctx['source_urls']
    assert plan['sources'][0]['url'] == ctx['source_urls'][2]
    assert plan['objectives'][0]['source_ids'] == ['s1']
    assert len(plan['research_errors']) == 2
    assert not plan['completion_verified'] and not plan['live_verified']


def test_boss_instruction_changes_target_but_does_not_override_crowd_guard():
    from gbox.mercs.titles.merc3d_bot import Bot
    class Strategy:
        receipt = {}
        def instruction(self, _):
            return {'action': 'defeat_boss', 'executable': True, 'binding': {'enemy_class': 'Boss'}}
    bot = Bot(strategy=Strategy(), clock=lambda: 10)
    enemies = [{'ptr': 1, 'class': 'Grunt', 'hp': 100, 'pos': (0,0,500)},
               {'ptr': 2, 'class': 'Boss', 'hp': 1000, 'pos': (0,0,1000)}]
    bot.tick({'player': {'pos': (0,0,0), 'rot': 0, 'hp':100}, 'enemies': enemies})
    assert bot.target == 2
    crowd = [dict(e, ptr=i+3, pos=(i*20,0,100)) for i,e in enumerate(enemies*2)]
    bot.tick({'player': {'pos': (0,0,0), 'rot':0,'hp':100}, 'enemies': crowd})
    assert bot.doing == 'kite'


def test_missing_tutorial_targets_surface_blocker_without_random_movement():
    from gbox.mercs.titles.merc3d_bot import Bot
    strategy = SimpleNamespace(receipt={}, instruction=lambda _: {'action':'follow_markers', 'executable':False})
    bot = Bot(strategy=strategy)
    assert bot.tick({'player':{'pos':(0,0,0),'rot':0,'hp':100},'enemies':[]}) == {'hold': ()}
    assert bot.doing == 'objective_blocked'


@pytest.mark.parametrize('native', [True, False])
def test_model_transport_uses_provider_capability_not_port(monkeypatch, native):
    import httpx
    import json
    calls = []
    monkeypatch.setattr(httpx, 'get', lambda url, **kw: httpx.Response(
        200 if native else 404, json={'version':'0.9'} if native else {}, request=httpx.Request('GET',url)))
    def post(url, **kwargs):
        calls.append((url, kwargs))
        content = json.dumps(proposal())
        return httpx.Response(200, json={'message':{'content':content}} if native else
                              {'choices':[{'message':{'content':content}}]}, request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx, 'post', post)
    assert W.model_plan('evidence', {'llm_url':'http://provider:9999/v1','model':'text'}) == proposal()
    chat = [call for call in calls if not call[0].endswith('/api/show')]
    assert chat[0][0].endswith('/api/chat' if native else '/v1/chat/completions')
    assert len(chat) == 1


@pytest.fixture
def native_model_http(monkeypatch):
    import httpx
    import json
    state = {'models': [{'name': 'text', 'context_length': 16384}],
             'thinking': {'values': [False, True], 'default': True}, 'calls': []}
    def request(method, url, **kwargs):
        state['calls'].append((url, kwargs))
        if url.endswith('/api/version'):
            data = {'version': '0.35.1'}
        elif url.endswith('/api/ps'):
            data = {'models': state['models']}
        elif url.endswith('/api/show'):
            data = {'thinking': state['thinking']}
        elif url.endswith('/api/chat'):
            data = {'message': {'content': json.dumps(proposal())}}
        else:
            pytest.fail('Unexpected provider route: ' + url)
        if url.endswith(state.get('error_path', '/never')):
            raise httpx.ReadTimeout('metadata unavailable')
        return httpx.Response(200, json=data, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx, 'get', lambda url, **kw: request('GET', url, **kw))
    monkeypatch.setattr(httpx, 'post', lambda url, **kw: request('POST', url, **kw))
    return state


def test_native_plan_preserves_exact_resident_context_and_supported_no_thinking(native_model_http):
    assert W.model_plan('evidence', {'llm_url': 'http://provider/v1', 'model': 'text'}) == proposal()
    body = native_model_http['calls'][-1][1]['json']
    assert body['model'] == 'text' and body['think'] is False
    assert body['options'] == {'temperature': 0, 'num_predict': 1800, 'num_ctx': 16384}
    assert all(call[1]['timeout'] <= 4 for call in native_model_http['calls'][:-1])


@pytest.mark.parametrize('models', [[], [{'name': 'other', 'context_length': 16384}],
    [{'name': 'text', 'context_length': True}], [{'name': 'text', 'context_length': '16384'}],
    [{'name': 'text', 'context_length': 0}], [{'name': 'text', 'context_length': 1_048_577}],
    [{'name': 'text', 'context_length': 16384}, {'name': 'text', 'context_length': 8192}]])
def test_native_plan_does_not_guess_or_resize_unverified_context(native_model_http, models):
    native_model_http['models'] = models
    W.model_plan('evidence', {'llm_url': 'http://provider', 'model': 'text'})
    assert 'num_ctx' not in native_model_http['calls'][-1][1]['json']['options']


@pytest.mark.parametrize('thinking', [None, {}, {'values': [0, True]}, {'values': [True]},
                                     {'values': ['low', 'medium', 'high']}, {'values': 'false'}])
def test_native_plan_requires_literal_advertised_false(native_model_http, thinking):
    native_model_http['thinking'] = thinking
    W.model_plan('evidence', {'llm_url': 'http://provider', 'model': 'text'})
    assert 'think' not in native_model_http['calls'][-1][1]['json']


@pytest.mark.parametrize('path,missing', [('/api/ps', 'num_ctx'), ('/api/show', 'think')])
def test_optional_native_metadata_failure_keeps_provider_defaults(native_model_http, path, missing):
    native_model_http['error_path'] = path
    assert W.model_plan('evidence', {'llm_url': 'http://provider', 'model': 'text'}) == proposal()
    body = native_model_http['calls'][-1][1]['json']
    assert missing not in (body['options'] if missing == 'num_ctx' else body)


@pytest.mark.parametrize('last_allowed', ['/api/ps', '/api/show'])
def test_native_metadata_cannot_bypass_revoked_network_permission(native_model_http, last_allowed):
    allowed = lambda: not any(url.endswith(last_allowed) for url, _ in native_model_http['calls'])
    with pytest.raises(PermissionError):
        W.model_plan('evidence', {'llm_url': 'http://provider', 'model': 'text'}, allowed)
    assert not any(url.endswith('/api/chat') for url, _ in native_model_http['calls'])


def test_native_metadata_shares_elapsed_time_budget(native_model_http, monkeypatch):
    monkeypatch.setattr(W.time, 'monotonic', lambda: 10 if any(
        url.endswith('/api/ps') for url, _ in native_model_http['calls']) else 0)
    with pytest.raises(TimeoutError, match='budget'):
        W.model_plan('evidence', {'llm_url': 'http://provider', 'model': 'text'}, deadline=5)
    assert not any(url.endswith('/api/chat') for url, _ in native_model_http['calls'])


def test_generic_game_requires_verified_native_level_and_accepts_level_zero(monkeypatch):
    from gbox import level_strategy_tool as T, tools
    game = {'game_id':'other','title':'Other game','platform':'nes','_profile':{'id':'known'}}
    monkeypatch.setattr(tools, '_semantic_state', lambda *a: {'profile':'known','verified':True,'globals':{'level':0}})
    ctx, _ = T.current(object(), game)
    assert ctx['level'] == '0' and ctx['actions'] == []
    monkeypatch.setattr(tools, '_semantic_state', lambda *a: {'profile':'known','verified':False,'globals':{'level':0}})
    with pytest.raises(T.Unsupported): T.current(object(), game)


def test_tool_does_not_activate_research_after_mission_changes(tmp_path, monkeypatch):
    from gbox import level_strategy_tool as T, tools
    from gbox import level_strategy_service as V
    ctx = context(); game = {'game_id':'game'}
    ad = SimpleNamespace(query_runtime=lambda:{'running':True})
    monkeypatch.setitem(tools.SESSIONS, 'worker-session', (ad, game))
    calls = [ctx, dict(ctx, level='3-1')]
    monkeypatch.setattr(T, 'current', lambda *a: (calls.pop(0), {}))
    monkeypatch.setattr(V, 'transport', lambda *a, **k: lambda *a: S.validate_plan(proposal(), ctx, sources()))
    job = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path, agent={}), progress=lambda *a:None,
                          server='http://authority', headers={},
                          artifact=lambda *a, **k:pytest.fail('Stale plan must not be published'))
    with pytest.raises(T.Unsupported, match='changed'):
        T.run(T.StrategyIn(session_id='worker-session'), job)
    assert S.Store(tmp_path/'level-strategy').plan(ctx) is None


def test_tool_publishes_scoped_plan_and_enables_future_research_without_input(tmp_path, monkeypatch):
    from gbox import level_strategy_tool as T, tools
    from gbox import level_strategy_service as V
    ctx = context(); game = {'game_id':'game'}
    ad = SimpleNamespace(query_runtime=lambda:{'running':True})
    monkeypatch.setitem(tools.SESSIONS, 'worker-session', (ad, game))
    monkeypatch.setattr(T, 'current', lambda *a: (dict(ctx), {}))
    monkeypatch.setattr(V, 'transport', lambda *a, **k: lambda *a: S.validate_plan(proposal(), ctx, sources()))
    artifacts = []
    job = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path, agent={}), progress=lambda *a:None,
                          server='http://authority', headers={},
                          artifact=lambda *a, **k:artifacts.append(a))
    result = T.run(T.StrategyIn(session_id='worker-session'), job)['result']
    assert result['enabled'] and result['inputs_sent'] is False
    assert artifacts and S.Store(tmp_path/'level-strategy').plan(ctx)


def test_network_permission_revocation_prevents_background_refresh(tmp_path):
    ctx = context(); store = S.Store(tmp_path); store.configure('game', True, {})
    runtime = S.Runtime(lambda _:ctx, store=store, network_allowed=lambda:False,
                        research=lambda *a:pytest.fail('Network-revoked runtime must not submit research'))
    runtime.observe({})
    assert runtime.pending is None and runtime.receipt['network_allowed'] is False


def test_network_revocation_stops_research_between_search_and_fetch():
    permitted = [True]
    def search(_): permitted[0] = False; return [{'url':'https://example.com'}]
    with pytest.raises(PermissionError):
        W.research(context(), {}, search=search, fetcher=lambda _:pytest.fail('No fetch after revocation'),
                   network_allowed=lambda:permitted[0])


@pytest.mark.parametrize('url', ['http://user:secret@host/v1','https://host/v1?api_key=secret','file:///secrets'])
def test_settings_never_persist_endpoint_credentials(tmp_path, url):
    store = S.Store(tmp_path)
    with pytest.raises(ValueError): store.configure('game', True, {'llm_url':url})
    assert not list(tmp_path.iterdir())


def service(monkeypatch, network=True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gbox import level_strategy_service as V
    app = FastAPI()
    row = {'state':'running','game_id':'game','mod':'','worker_id':'worker','started':1}
    app.state.store = SimpleNamespace(get=lambda kind, sid:row)
    cfg = SimpleNamespace(agent={}, granted_permissions=['network'] if network else [])
    monkeypatch.setattr(W, 'research', lambda ctx, *a, **k: S.validate_plan(proposal(), ctx, sources()))
    V.install(app, cfg, lambda:'operator')
    return app, TestClient(app), row, cfg, V


def test_service_uses_central_model_and_never_accepts_raw_snapshots(monkeypatch):
    app, client, row, cfg, V = service(monkeypatch)
    body = V.payload('worker-session', context() | {'player':{'pos':[1,2,3]}, 'ram_address':0x123})
    assert 'player' not in body['context'] and 'ram_address' not in body['context']
    result = client.post('/api/level-strategy/research', json=body)
    assert result.status_code == 200 and result.json()['inputs_sent'] is False
    body['context']['save_bytes'] = 'secret'
    assert client.post('/api/level-strategy/research', json=body).status_code == 422


def test_service_rechecks_session_and_network(monkeypatch):
    app, client, row, cfg, V = service(monkeypatch, network=False)
    body = V.payload('worker-session', context())
    assert client.post('/api/level-strategy/research', json=body).status_code == 403
    cfg.granted_permissions = ['network']; row['mod'] = 'different'
    assert client.post('/api/level-strategy/research', json=body).status_code == 409


def test_local_service_forwards_only_to_existing_paired_authority(monkeypatch):
    import threading, httpx
    app, client, row, cfg, V = service(monkeypatch)
    app.state.desktop_bridge = SimpleNamespace(lock=threading.RLock(), remote='https://paired.example',
        token='paired-secret', state={'connected':True})
    calls = []
    def post(url, **kw):
        calls.append((url,kw))
        return httpx.Response(200,json={'plan':S.validate_plan(proposal(),context(),sources())},
                              request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx, 'post', post)
    body = V.payload('worker-session',context())
    result = client.post('/api/level-strategy/research',json=body)
    assert result.status_code == 200
    assert calls[0][0] == 'https://paired.example/api/level-strategy/research'
    assert calls[0][1]['headers']['Authorization'] == 'Bearer paired-secret'
    assert 'paired-secret' not in str(calls[0][1]['json'])
    app.state.desktop_bridge.state['connected'] = False
    assert client.post('/api/level-strategy/research',json=body).status_code == 503
    assert len(calls) == 1


def test_service_discards_result_after_worker_changes(monkeypatch):
    import threading, httpx
    app, client, row, cfg, V = service(monkeypatch)
    app.state.desktop_bridge = SimpleNamespace(lock=threading.RLock(), remote='https://paired.example',
        token='secret', state={'connected':True})
    def post(url, **kw):
        row['worker_id'] = 'replacement'
        return httpx.Response(200,json={'plan':S.validate_plan(proposal(),context(),sources())},
                              request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    assert client.post('/api/level-strategy/research',json=V.payload('worker-session',context())).status_code == 409


def test_research_budget_exhaustion_prevents_model_call(monkeypatch):
    now = [0]
    monkeypatch.setattr(W.time, 'monotonic', lambda:now[0])
    def search(_): now[0] = 16; return [{'url':'https://example.com'}]
    with pytest.raises(TimeoutError, match='budget'):
        W.research(context(), {'strategy_timeout_seconds':15}, search=search,
                   fetcher=lambda _:pytest.fail('No fetch after deadline'),
                   synthesize=lambda _:pytest.fail('No model after deadline'))


def test_research_rejects_model_response_after_its_budget(monkeypatch):
    now = [0]
    monkeypatch.setattr(W.time, 'monotonic', lambda:now[0])
    def synthesize(_): now[0] = 16; return proposal()
    with pytest.raises(TimeoutError, match='budget'):
        W.research(context(), {'strategy_timeout_seconds':15}, search=lambda _:[{'url':'https://example.com'}],
                   fetcher=lambda _:sources()[0] | {'text':'Useful source material ' * 10},
                   synthesize=synthesize)


def test_prior_boss_instruction_is_cleared_when_current_strategy_context_fails():
    from gbox.mercs.titles.merc3d_bot import Bot
    calls = [0]
    class Strategy:
        receipt = {}
        def instruction(self, _):
            calls[0] += 1
            if calls[0] > 1: raise ValueError('Context unavailable')
            return {'action':'defeat_boss', 'executable':True, 'binding':{'enemy_class':'Boss'}}
    bot = Bot(strategy=Strategy(), clock=lambda:10)
    snap = {'player':{'pos':(0,0,0), 'rot':0, 'hp':100}, 'enemies':[]}
    bot.tick(snap)
    assert bot.instruction and bot.stats['level_objective']
    bot.tick(snap)
    assert bot.instruction is None and 'level_objective' not in bot.stats
    assert not bot.stats['level_strategy']['context_available']


def test_runtime_clears_prior_progress_and_pending_binding_on_context_loss(tmp_path):
    ctx = [context()]; store = S.Store(tmp_path); store.configure('game', True, {})
    runtime = S.Runtime(lambda _:ctx[0], store=store, clock=lambda:0)
    runtime.observe({})
    future = concurrent.futures.Future(); runtime.pending = (S.key(ctx[0]), future)
    ctx[0] = None
    assert runtime.instruction({}) is None
    assert not runtime.receipt['context_available'] and runtime.pending[0] is None
    assert 'progress_evidence' not in runtime.receipt


def test_merc3d_runtime_binds_actual_registered_mod_and_refuses_ambiguous_adapter(tmp_path, monkeypatch):
    from gbox import tools
    from gbox.mercs.titles import merc3d_3ds as D
    ad = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path, granted_permissions=[]))
    memory = SimpleNamespace(adapter=ad, rd=lambda *a:D.CODE_SIGNATURE)
    monkeypatch.setattr(tools, 'SESSIONS', {'current':(ad, {'game_id':M.GAME_ID, 'mod':'custom'})})
    rt = M.runtime(memory, lambda:0)
    assert rt.context_factory({'mission_id':0x101})['mod'] == 'custom'
    tools.SESSIONS['other'] = (ad, {'game_id':M.GAME_ID, 'mod':''})
    assert rt.context_factory({'mission_id':0x101}) is None


def test_source_allowlist_rejects_arbitrary_dns_owner_before_lookup(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k:pytest.fail('Untrusted host must not resolve'))
    with pytest.raises(ValueError, match='vetted'):
        W.public_url('https://attacker.example/walkthrough')


def test_vetted_source_still_refuses_private_resolution(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError, match='Private'):
        W.public_url(W.MANUAL)
