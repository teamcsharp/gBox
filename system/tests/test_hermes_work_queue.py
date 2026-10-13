import json
import pytest

from gbox import hermes_work_queue as q

G = 'a' * 16
R = 'b' * 16
P = 'c' * 16
SHA = 'd' * 64
ART = 'e' * 64


def favorite(gid=G, **kw):
    return {'game_id': gid, 'title': 'Game', 'platform': 'dreamcast', 'in_catalog': True, **kw}


def request(rid=R, **kw):
    return {'id': rid, 'number': 5, 'title': 'Fix it', 'status': 'in_progress', **kw}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    data = {'version': 1, 'items': {}, 'parent_request_id': P, 'last_lane': 'inbox'}
    q._save(data)
    return data


def test_all_favorites_survive_missing_catalog_and_removal(env):
    games = [favorite(f'{i:016x}', in_catalog=i != 2) for i in range(136)]
    q.sync(env, {'count': len(games), 'items': games}, [], now=10)
    assert len(env['items']) == 136
    assert len(q.candidates(env, [], [], set(), set(), now=11)) == 135
    games.pop()
    q.sync(env, {'count': len(games), 'items': games}, [], now=20)
    assert len(env['items']) == 136  # preserve old checkpoints
    assert sum(i['favorite'] for i in env['items'].values()) == 135


def test_incomplete_snapshot_never_silently_drops_titles(env):
    with pytest.raises(ValueError, match='Incomplete'):
        q.sync(env, {'count': 136, 'items': [favorite()]}, [], now=10)


def test_recover_lost_child_creation_from_durable_context(env):
    q.sync(env, {'count': 1, 'items': [favorite()]}, [], now=10)
    item = env['items']['favorite:' + G]
    item['request_uncertain'] = True
    child = request(context={'hermes_favorite_game': G}, automated=True, parent_request_id=P)
    q.sync(env, {'count': 1, 'items': [favorite()]}, [child], now=20)
    assert item['request_id'] == R and 'request_uncertain' not in item
    assert 'inbox:' + R not in env['items']


def test_pending_native_and_active_ownership_suppress_duplicates(env):
    child = request(context={'hermes_favorite_game': G})
    q.sync(env, {'count': 1, 'items': [favorite()]}, [child], now=1)
    assert not q.candidates(env, [child], [], {R}, set(), now=2)
    assert not q.candidates(env, [child], [{'input': {'game_id': G}}], set(), set(), now=2)
    assert not q.candidates(env, [child], [{'parent_request_id': R}], set(), set(), now=2)
    assert len(q.candidates(env, [child], [], set(), set(), now=2)) == 1


def test_fairness_and_merged_work_priority(env):
    reqs = [request(), request('f' * 16)]
    q.sync(env, {'count': 2, 'items': [favorite(), favorite('1' * 16)]}, reqs, now=1)
    choices = q.candidates(env, reqs, [], set(), {R}, now=2)
    selected = q.choose(choices, env)
    assert selected[1]['lane'] == 'favorite'
    selected[1]['last_dispatched'] = 2
    assert q.choose(choices, env)[0] != selected[0]
    env['last_lane'] = 'favorite'
    assert q.choose(choices, env)[1]['request_id'] == R
    env['items']['inbox:' + R]['last_dispatched'] = 2
    assert q.choose(choices, env)[1]['request_id'] == 'f' * 16


def test_automatic_repairs_and_manual_children_are_not_forgotten(env):
    reqs = [request(automated=True, context={'auto_report': True, 'game_id': G}),
            request('1' * 16, automated=True, source='gap', parent_request_id=P,
                    context={'character': 'amy', 'game_id': G}),
            request('2' * 16, parent_request_id=P, author='operator', source='gbox-chat', automated=True),
            request('3' * 16, automated=True, body='gBox request review')]
    q.sync(env, {'count': 1, 'items': [favorite()]}, reqs, now=1)
    options = q.candidates(env, reqs, [], set(), set(), now=2)
    assert {i['request_id'] for _, i in options} == {R, '1' * 16, '2' * 16}
    assert all(i['lane'] == 'inbox' for _, i in options)  # repair owns this favorite
    env['items']['inbox:' + R]['dispatch_state'] = 'queued'
    assert {i['request_id'] for _, i in q.candidates(env, reqs, [], set(), set(), now=2)} == {'2' * 16}


def test_explicit_pickwhip_has_first_pass_priority_without_starving_old_work(env):
    reqs = [request(created=1, automated=True, context={'auto_report': True}),
            request('1' * 16, created=99, automated=True,
                    context={'native_replacement': True, 'replacement_requested': True})]
    q.sync(env, {'count': 0, 'items': []}, reqs, now=100)
    options = q.candidates(env, reqs, [], set(), set(), now=100)
    selected = q.choose(options, env)
    assert selected[1]['request_id'] == '1' * 16
    selected[1]['last_dispatched'] = 100
    assert q.choose(options, env)[1]['request_id'] == R


def test_followup_acceptance_gets_a_turn_before_entire_backlog_is_visited(env):
    reqs = [request(), request('1' * 16, context={'native_replacement': True,
                                               'replacement_requested': True})]
    q.sync(env, {'count': 0, 'items': []}, reqs, now=100)
    env['items']['inbox:' + '1' * 16]['last_dispatched'] = 90
    options = q.candidates(env, reqs, [], set(), set(), now=100)
    env['last_inbox_kind'] = 'new'
    assert q.choose(options, env)[1]['request_id'] == '1' * 16
    env['last_inbox_kind'] = 'followup'
    assert q.choose(options, env)[1]['request_id'] == R


def test_favorite_analysis_continues_before_every_title_finishes_inventory(env):
    q.sync(env, {'count': 2, 'items': [favorite(), favorite('1' * 16)]}, [], now=100)
    env['items']['favorite:' + G].update(last_dispatched=90, stages={'inventory': {'status': 'verified'}})
    options = q.candidates(env, [], [], set(), set(), now=100)
    env['last_favorite_kind'] = 'new'
    assert q.choose(options, env)[1]['game_id'] == G
    env['last_favorite_kind'] = 'followup'
    assert q.choose(options, env)[1]['game_id'] == '1' * 16


def test_extraction_and_generic_tool_gaps_are_actionable_but_agent_messages_are_not(env):
    reqs = [request(source='characters', automated=True, context={'what': 'selected player', 'game_id': G}),
            request('1' * 16, source='gap', automated=True, context={'session_id': 's'}),
            request('2' * 16, source='gap', automated=True, body='<agent-message from="x">status</agent-message>')]
    q.sync(env, {'count': 0, 'items': []}, reqs, now=100)
    assert set(env['items']) == {'inbox:' + R, 'inbox:' + '1' * 16}
    assert env['items']['inbox:' + R]['repair']


def test_completed_occurrence_backoff_and_idempotence(env):
    q.sync(env, {'count': 1, 'items': [favorite()]}, [], now=10)
    item = env['items']['favorite:' + G]
    item.update(job_id='job', dispatch_state='queued', last_dispatched=100)
    run = {'id': 'run', 'started_at': '1970-01-01T00:01:40+00:00', 'status': 'completed'}
    q.reconcile(env, [{'id': 'job', 'enabled': False}], {'job': run}, set(), now=200)
    assert item['dispatch_state'] == 'finished' and item['retry_at'] == 500
    q.reconcile(env, [{'id': 'job', 'enabled': False}], {'job': run}, set(), now=300)
    assert item['no_progress_runs'] == 1 and item['retry_at'] == 500


def test_uncertain_launch_is_not_blindly_repeated(env):
    q.sync(env, {'count': 1, 'items': [favorite()]}, [], now=1)
    item = env['items']['favorite:' + G]
    item.update(dispatch_state='uncertain', job_name='specific')
    q.reconcile(env, [], {}, set(), now=2)
    assert not q.candidates(env, [], [], set(), set(), now=2)
    q.reconcile(env, [{'id': 'j', 'name': 'specific', 'enabled': True}], {}, set(), now=3)
    assert item['job_id'] == 'j' and item['dispatch_state'] == 'queued'


def test_verified_evidence_and_stage_order(env, monkeypatch):
    child = request(context={'hermes_favorite_game': G})
    q.sync(env, {'count': 1, 'items': [favorite()]}, [child], now=1)
    q._save(env)
    monkeypatch.setattr(q, '_api', lambda path: {'messages': [{'attachments': [{'sha256': ART}]}]}
                        if '/requests/' in path else {'media_type': 'text/plain'})
    with pytest.raises(ValueError, match='preceding'):
        q.checkpoint(G, R, 'writer', 'verified', 'tested', source_sha256=SHA, artifacts=[ART])
    assert q.checkpoint(G, R, 'inventory', 'verified', 'owned manifest', source_sha256=SHA, artifacts=[ART])['next_stage'] == 'analysis'
    for stage in ('analysis', 'reader', 'writer'):
        q.checkpoint(G, R, stage, 'verified', 'tested', source_sha256=SHA, artifacts=[ART])
    with pytest.raises(ValueError, match='gameplay screenshot'):
        q.checkpoint(G, R, 'runtime', 'verified', 'tested', source_sha256=SHA, artifacts=[ART])
    monkeypatch.setattr(q, '_api', lambda path: {'messages': [{'attachments': [{'sha256': ART}]}]}
                        if '/requests/' in path else {'media_type': 'image/png'})
    assert q.checkpoint(G, R, 'runtime', 'verified', 'donor/slot/build gameplay', source_sha256=SHA, artifacts=[ART])['ready']


def test_wrong_request_missing_artifact_and_changed_build_refused(env, monkeypatch):
    child = request(context={'hermes_favorite_game': G})
    q.sync(env, {'count': 1, 'items': [favorite()]}, [child], now=1)
    q._save(env)
    monkeypatch.setattr(q, '_api', lambda path: {'messages': []})
    with pytest.raises(ValueError, match='attached'):
        q.checkpoint(G, R, 'inventory', 'verified', 'invented', source_sha256=SHA, artifacts=[ART])
    with pytest.raises(ValueError, match='does not own'):
        q.checkpoint(G, P, 'inventory', 'partial', 'wrong request')
    q.checkpoint(G, R, 'inventory', 'partial', 'some work', source_sha256=SHA, now=10)
    q.checkpoint(G, R, 'inventory', 'partial', 'some work', source_sha256=SHA, now=20)
    assert q._read()['items']['favorite:' + G]['checkpoint_at'] == 10
    with pytest.raises(ValueError, match='Source build changed'):
        q.checkpoint(G, R, 'inventory', 'partial', 'wrong build', source_sha256='f' * 64)


def test_pump_reserves_capacity_and_repeated_tick_does_not_duplicate(env, monkeypatch):
    jobs = [{'id': 'controller', 'name': q.mode.NAME, 'enabled': True, 'no_agent': True}]
    reqs = [request(P), request(R, context={'resolution_chat_id': 'old-chat'}), request('f' * 16)]
    favorites = [favorite(f'{i:016x}') for i in range(5)]
    monkeypatch.setattr(q.mode, '_job', lambda: jobs[0])
    monkeypatch.setattr(q.mode, '_jobs', lambda: jobs)
    monkeypatch.setattr(q.mode, '_config', lambda: {'cron': {'model_provider': 'nous', 'model': 'opus', 'max_parallel_jobs': 4}})
    monkeypatch.setattr(q, '_executions', lambda: ({}, set()))
    monkeypatch.setattr(q, '_native_jobs', lambda: [])
    from gbox import hermes_recovery
    monkeypatch.setattr(hermes_recovery, '_active_requests', lambda: set())
    monkeypatch.setattr(q.mode, '_handoff', lambda: '')
    def api(path, body=None):
        if path == '/api/chat': return [{'id': 'old-chat', 'busy': False}]
        if path == '/api/favorites': return {'count': len(favorites), 'items': favorites}
        if path == '/api/requests' and body is None: return reqs
        if path == '/api/requests':
            child = request(f'{len(reqs)+100:016x}', **body)
            reqs.append(child)
            return child
        raise AssertionError(path)
    monkeypatch.setattr(q, '_api', api)
    calls = []
    def run(*args):
        calls.append(args)
        if args[0] == 'create':
            jobs.append({'id': 'j' + str(len(jobs)), 'name': args[args.index('--name')+1],
                         'enabled': True, 'schedule': {'kind': 'once'}})
    monkeypatch.setattr(q.mode, '_run', run)
    result = q.tick(now=1000)
    assert len(result['dispatched']) == 4
    assert sum(d['lane'] == 'favorite' for d in result['dispatched']) == 2
    assert q.tick(now=1060)['dispatched'] == []
    assert len(calls) == 4
    jobs[0]['enabled'] = False
    assert q.tick(now=1120)['status'] == 'disabled_or_legacy_controller'


def test_quota_primary_never_dispatches(env, monkeypatch):
    monkeypatch.setattr(q.mode, '_job', lambda: {'enabled': True, 'no_agent': True})
    monkeypatch.setattr(q.mode, '_jobs', lambda: [])
    monkeypatch.setattr(q, '_executions', lambda: ({}, set()))
    monkeypatch.setattr(q, '_api', lambda path: [] if path == '/api/requests' else {'count': 0, 'items': []})
    monkeypatch.setattr(q.mode, '_config', lambda: {'cron': {'model_provider': 'zai', 'model': 'glm'}})
    (q.delivery.state_dir() / 'feedback.json').write_text(json.dumps({'cooldowns': {'zai/glm': 9999}}))
    assert q.tick(now=1000)['status'] == 'waiting_for_route_supervisor'


def test_heavy_native_backpressure_preserves_independent_writer_work(env):
    games = [favorite(), favorite('1' * 16)]
    q.sync(env, {'count': 2, 'items': games}, [], now=1)
    second = env['items']['favorite:' + '1' * 16]
    second['stages'] = {stage: {'status': 'verified'} for stage in ('inventory', 'analysis', 'reader')}
    native = [{'tool': 'analyze_binary'}, {'tool': 'ghidra_script'}]
    selected = q.candidates(env, [], native, set(), set(), now=2)
    assert len(selected) == 1 and selected[0][1] is second


def test_pausing_pending_work_can_resume_without_stranding_claims(env, monkeypatch):
    q.sync(env, {'count': 1, 'items': [favorite()]}, [], now=1)
    item = env['items']['favorite:' + G]
    item.update(job_id='job', dispatch_state='queued')
    q._save(env)
    monkeypatch.setattr(q.mode, '_jobs', lambda: [{'id': 'job', 'name': q.PREFIX+'favorite '+G, 'enabled': True}])
    monkeypatch.setattr(q.mode, '_active', lambda _: False)
    calls = []
    monkeypatch.setattr(q.mode, '_run', lambda *args: calls.append(args))
    q.pause_pending()
    assert calls == [('pause', 'job')]
    assert q._read()['items']['favorite:' + G]['dispatch_state'] == 'paused'
    assert q.candidates(q._read(), [], [], set(), set(), now=2)


def test_mcp_queue_checkpoint_roundtrip(env, monkeypatch):
    import asyncio
    import httpx
    from mcp.client import Client
    from gbox.mcp_server import build
    child = request(context={'hermes_favorite_game': G})
    q.sync(env, {'count': 1, 'items': [favorite()]}, [child], now=1)
    q._save(env)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda *a, **kw: original(*a, **kw,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'tools': []}))))
    async def check():
        async with Client(build('http://fixture', 'fixture')) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {'get_game_work_queue', 'record_game_work'} <= names
            result = await client.call_tool('record_game_work', {'game_id': G, 'request_id': R,
                'stage': 'inventory', 'status': 'partial', 'note': 'Located owned executable',
                'next_step': 'Hash and inspect the asset table'})
            assert not result.is_error
            snapshot = await client.call_tool('get_game_work_queue', {'game_id': G})
            game = json.loads(snapshot.content[0].text)['games'][0]
            assert game['stages']['inventory']['next_step'] == 'Hash and inspect the asset table'
    asyncio.run(check())


def test_operator_priority_puts_listed_games_and_requests_first(env):
    reqs = [request(created=1), request('f' * 16, created=2)]
    q.sync(env, {'count': 2, 'items': [favorite(), favorite('1' * 16)]}, reqs, now=3)
    options = q.candidates(env, reqs, [], set(), set(), now=4)
    env['last_lane'] = 'inbox'                                   # favourite lane is next
    default = q.choose(options, env)[1]['game_id']
    other = '1' * 16 if default == G else G
    assert q.set_priority([other]) == [other]
    env = q._read() | {'items': env['items'], 'last_lane': 'inbox'}
    assert q.choose(options, env)[1]['game_id'] == other         # listed game first, whatever the default tie-break
    env['last_lane'] = 'favorite'                                # inbox lane is next
    assert q.choose(options, env)[1]['request_id'] == R
    env['priority'] = ['f' * 16]
    assert q.choose(options, env)[1]['request_id'] == 'f' * 16   # listed request first
    assert q.priority_rank({'number': 5}, {'priority': ['5']}) == 0
    assert q.priority_rank({'game_id': 'zz'}, {'priority': ['a', 'b']}) == 2
    assert q.get_priority() == [other]


# --- docs/stream-stability.md: the operator plays on the Spark (DOA2, 2026-10-13) while a Hermes sandbox ran its own
# Dolphin at 300% CPU on the same machine.

def test_operator_gate_defers_emulator_work_and_caps_dispatch():
    runtime = favorite(lane='favorite', favorite=True,
                       stages={s: {'status': 'verified'} for s in ('inventory', 'analysis', 'reader', 'writer')})
    reader = favorite('1' * 16, lane='favorite', favorite=True)
    repair = {'lane': 'inbox', 'request_id': R, 'repair': True}
    plain = {'lane': 'inbox', 'request_id': P}
    options = [('favorite:a', runtime), ('favorite:1', reader), ('inbox:r', repair), ('inbox:p', plain)]
    assert q.operator_gate(options, []) == (options, None, None)
    kept, cap, report = q.operator_gate(options, [{'session_id': 'spark-1', 'title': 'Dead or Alive 2'}],
                                        {'throttled': [12]})
    assert [k for k, _ in kept] == ['favorite:1', 'inbox:p'] and cap == 1
    assert report == {'games': ['Dead or Alive 2'], 'deferred': ['favorite:a', 'inbox:r'],
                      'sandboxes': {'throttled': [12]}}


def test_tick_throttles_sandboxes_and_warns_agents_while_the_operator_plays(env, monkeypatch):
    jobs = [{'id': 'controller', 'name': q.mode.NAME, 'enabled': True, 'no_agent': True}]
    reqs = [request(P), request(R)]
    monkeypatch.setattr(q.mode, '_job', lambda: jobs[0])
    monkeypatch.setattr(q.mode, '_jobs', lambda: jobs)
    monkeypatch.setattr(q.mode, '_config', lambda: {'cron': {'model_provider': 'nous', 'model': 'opus', 'max_parallel_jobs': 4}})
    monkeypatch.setattr(q, '_executions', lambda: ({}, set()))
    monkeypatch.setattr(q, '_native_jobs', lambda: [])
    from gbox import hermes_recovery, operator_guard
    monkeypatch.setattr(hermes_recovery, '_active_requests', lambda: set())
    monkeypatch.setattr(q.mode, '_handoff', lambda: '')
    throttled = []
    monkeypatch.setattr(operator_guard, 'throttle_agent_sandboxes', lambda: throttled.append(1) or {'throttled': [7]})
    favorites = [favorite(f'{i:016x}') for i in range(3)]

    def api(path, body=None):
        if path == '/api/sessions?include_ended=false':
            return [{'session_id': 'spark-x', 'state': 'running', 'title': 'Dead or Alive 2'}]
        if path == '/api/workers': return [{'id': 'spark', 'os': 'linux', 'online': True}]
        if path == '/api/chat': return []
        if path == '/api/favorites': return {'count': len(favorites), 'items': favorites}
        if path == '/api/requests' and body is None: return reqs
        if path == '/api/requests':
            child = request(f'{len(reqs)+100:016x}', **body)
            reqs.append(child)
            return child
        raise AssertionError(path)
    monkeypatch.setattr(q, '_api', api)
    prompts = []

    def run(*args):
        if args[0] == 'create':
            prompts.append(args[2])
            jobs.append({'id': 'j' + str(len(jobs)), 'name': args[args.index('--name')+1],
                         'enabled': True, 'schedule': {'kind': 'once'}})
    monkeypatch.setattr(q.mode, '_run', run)
    # The Spark session id is "spark-x" but the worker is "spark": the worker prefix decides the machine.
    result = q.tick(now=1000)
    assert throttled == [1] and result['capacity'] == 1 and len(result['dispatched']) == 1
    assert result['operator_playing']['games'] == ['Dead or Alive 2']
    assert 'The operator is playing Dead or Alive 2 on this machine right now' in prompts[0]
    # Throttling runs even when the dispatcher itself is switched off.
    jobs[0]['enabled'] = False
    assert q.tick(now=1060)['status'] == 'disabled_or_legacy_controller' and throttled == [1, 1]
