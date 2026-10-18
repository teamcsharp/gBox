"""The Spark's GPU model is Hermes's last-resort route: chosen only when every paid route is out, left at once when
one recovers, never a paid route's fallback, and the CPU llama.cpp route stays excluded (docs/hermes-local-fallback.md)."""
import json
import re
from types import SimpleNamespace

import pytest

from gbox import hermes_feedback, hermes_local, hermes_quota
from gbox.config import HermesLocalConfig

OPUS = 'anthropic/claude-opus-5.5'
NOUS, ROUTER = {'provider': 'nous', 'model': OPUS}, {'provider': 'openrouter', 'model': OPUS}
LOCAL = {'provider': 'spark-local', 'model': 'gpt-oss:20b'}
S = HermesLocalConfig(proxy_url='http://127.0.0.1:8765/api/llm/local/v1')


def test_paid_routes_first_and_local_only_when_every_paid_route_is_out():
    pick = hermes_local.choose([NOUS, ROUTER], {}, 1000, primary=NOUS, s=S, only_local=False)
    assert pick['mode'] == 'paid' and pick['route'] == NOUS and pick['fallbacks'] == [ROUTER]
    assert LOCAL not in pick['fallbacks']                      # never a paid route's fallback
    cooling = {'nous/' + OPUS: 5000, 'openrouter/' + OPUS: 4000}
    pick = hermes_local.choose([NOUS, ROUTER], cooling, 1000, primary=NOUS, s=S, only_local=False)
    assert pick['mode'] == 'local' and pick['route'] == LOCAL and pick['fallbacks'] == []
    assert pick['next_paid_at'] == 4000 and 'out of credit' in pick['reason']


def test_rotates_back_as_soon_as_a_paid_route_recovers():
    cooling = {'nous/' + OPUS: 5000}                           # openrouter's cooldown ended
    pick = hermes_local.choose([NOUS, ROUTER, LOCAL], cooling, 1000, primary=LOCAL, s=S, only_local=False)
    assert pick['mode'] == 'paid' and pick['route'] == ROUTER and pick['fallbacks'] == []
    assert 'rotated back' in pick['reason']


def test_operator_local_only_and_disabled_local_route(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    assert not hermes_local.local_only(S)
    hermes_local.set_local_only(True)
    assert hermes_local.local_only(S)
    pick = hermes_local.choose([NOUS, ROUTER], {}, 1000, primary=NOUS, s=S)
    assert pick['mode'] == 'local' and pick['reason'] == 'The operator set Hermes to local only'
    hermes_local.set_local_only(False)
    off = S.model_copy(update={'enabled': False})
    pick = hermes_local.choose([NOUS], {'nous/' + OPUS: 5000}, 1000, primary=NOUS, s=off, only_local=False)
    assert pick['mode'] == 'none' and pick['route'] is None


def test_cpu_llamacpp_stays_excluded_with_the_local_route(monkeypatch):
    monkeypatch.delenv('GBOX_HERMES_EXCLUDED_PROVIDERS', raising=False)
    config = {'cron': {'model_provider': 'spark-local', 'model': 'gpt-oss:20b'},
              'fallback_providers': [{'provider': 'llamacpp', 'model': 'Qwen3.6-35B-A3B-UD-Q4_K_M'}]}
    got = hermes_quota.routes(config, [{'provider': 'llamacpp', 'model': 'x'}, NOUS])
    assert {r['provider'] for r in got} == {'spark-local', 'nous'}


def test_provider_entry_has_no_secret_and_reuses_the_ehmbird_shape():
    existing = [{'name': 'EhmBird', 'base_url': 'http://localhost:11434/v1', 'api_key': 'secret-key',
                 'model': 'qwen3.8:27b-mtp-q4_K_M', 'api_mode': 'chat_completions'},
                {'name': 'Other', 'base_url': 'https://x.example/v1', 'api_key': 'k2', 'model': 'm'}]
    merged = hermes_local.merged_providers(existing, S)
    mine = merged[-1]
    assert mine == {'name': 'spark-local', 'base_url': S.proxy_url, 'api_key': 'gbox-local', 'model': 'gpt-oss:20b',
                    'api_mode': 'chat_completions'}
    assert merged[:2] == existing                              # other providers are kept untouched
    assert hermes_local.merged_providers(merged, S) is None    # nothing to change the second time
    moved = S.model_copy(update={'model': 'qwen3.8:27b-mtp-q4_K_M'})
    assert hermes_local.merged_providers(merged, moved)[-1]['model'] == 'qwen3.8:27b-mtp-q4_K_M'


def test_settings_come_from_gbox_toml(monkeypatch, tmp_path):
    toml = tmp_path / 'gbox.toml'
    toml.write_text('api_port = 9000\n[hermes.local]\nmodel = "qwen3.8:27b-mtp-q4_K_M"\ncontext_tokens = 32768\n')
    monkeypatch.setenv('GBOX_CONFIG', str(toml))
    s = hermes_local.settings()
    assert s.model == 'qwen3.8:27b-mtp-q4_K_M' and hermes_local.context_limit(s) == 32768
    assert s.proxy_url == 'http://127.0.0.1:9000/api/llm/local/v1'


def test_openrouter_credit_ends_a_scheduler_backoff_but_not_a_measured_reset():
    cooldowns = {'openrouter/' + OPUS: 5000, 'openrouter/other': 5000, 'nous/' + OPUS: 5000}
    details = {'openrouter/' + OPUS: {'category': 'quota', 'source': 'scheduler_backoff', 'observed_at': 900},
               'openrouter/other': {'category': 'quota', 'source': 'provider_retry_metadata', 'observed_at': 900},
               'nous/' + OPUS: {'category': 'quota', 'source': 'scheduler_backoff', 'observed_at': 900}}
    fresh = {'available': True, 'remaining_usd': 24.0, 'checked_at': 950}
    assert hermes_local.credit_recovered(cooldowns, details, fresh, 1000) == ['openrouter/' + OPUS]
    assert hermes_local.credit_recovered(cooldowns, details, fresh | {'remaining_usd': 0.2}, 1000) == []
    assert hermes_local.credit_recovered(cooldowns, details, fresh | {'checked_at': 800}, 1000) == []
    assert hermes_local.credit_recovered(cooldowns, details, fresh | {'stale': True}, 1000) == []


@pytest.fixture
def supervisor(monkeypatch, tmp_path):
    """adjust_routes against a real Hermes config.yaml; `hermes config set` is replaced by an edit of that file, and
    every command line the supervisor ran is kept in `argv` (no provider key may appear there)."""
    import yaml
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setenv('GBOX_CONFIG', str(tmp_path / 'missing.toml'))
    monkeypatch.setenv('GBOX_HERMES_HOME', str(tmp_path / 'hermes'))
    monkeypatch.delenv('GBOX_HERMES_EXCLUDED_PROVIDERS', raising=False)
    home = tmp_path / 'hermes'
    home.mkdir()
    config_path = home / 'config.yaml'
    (home / 'config-backups').mkdir()
    (home / 'config-backups' / 'config.yaml.earlier').write_text('older backup')
    # The Spark's shape (2026-10-13): name, base_url, model, models, models_discovered, api_key.
    config_path.write_text(yaml.safe_dump({
        'model': {'default': 'x'}, 'cron': {'model_provider': 'nous', 'model': OPUS}, 'fallback_providers': [ROUTER],
        'custom_providers': [
            {'name': 'EhmBird', 'base_url': 'http://localhost:11434/v1', 'model': 'gemma4:e4b',
             'models': ['gemma4:e4b', 'qwen3:8b'], 'models_discovered': True, 'api_key': 'sk-secret-ehmbird'},
            {'name': '10.89.1.246:11434', 'base_url': 'http://10.89.1.246:11434/v1', 'model': 'qwen3:8b',
             'models': ['qwen3:8b'], 'models_discovered': True, 'api_key': 'sk-secret-lan'}]}, sort_keys=False))
    data = {'routes': [NOUS, ROUTER], 'cooldowns': {}, 'cooldown_details': {}, 'new_lessons': 0}
    path = tmp_path / 'feedback.json'
    sets, argv = [], []

    def read():
        return yaml.safe_load(config_path.read_text())

    def scan():
        saved = json.loads(path.read_text()) if path.exists() else {}
        path.write_text(json.dumps(saved | {k: data[k] for k in ('routes', 'cooldowns', 'cooldown_details')}))
        return dict(data)

    def run(args, **_):
        argv.append(list(args))
        key, value = args[-2:]
        sets.append(key)
        config = read()
        if '.' in key:
            config['cron'][key.split('.')[1]] = value
        else:
            config[key] = json.loads(value)
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(hermes_feedback, 'scan', scan)
    for name in ('finalize_usage', 'finalize_merges', 'finalize_cap', 'finalize_summaries', 'finalize_cleanup'):
        monkeypatch.setattr(hermes_feedback, name, lambda: {})
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_config', read)
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_jobs', lambda: [])
    monkeypatch.setattr(hermes_feedback.subprocess, 'run', run)
    monkeypatch.setattr(hermes_feedback, '_lift_recovered_credit', lambda data: [])
    from gbox import hermes_recovery
    monkeypatch.setattr(hermes_recovery, 'recover', lambda saved: {'status': 'no_pending_recovery'})

    class View(SimpleNamespace):
        @property
        def config(self):
            return read()
    return View(data=data, path=path, sets=sets, argv=argv, config_path=config_path)


def test_supervisor_switches_to_local_and_back(supervisor):
    sv = supervisor
    sv.data['cooldowns'] = {'nous/' + OPUS: 9e12, 'openrouter/' + OPUS: 9e12}
    original = sv.config_path.read_bytes()
    out = hermes_feedback.adjust_routes()
    backups = sorted((sv.config_path.parent / 'config-backups').glob('config.yaml.before-spark-local-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == original           # the original, byte for byte
    assert re.fullmatch(r'config\.yaml\.before-spark-local-\d{8}T\d{6}Z', backups[0].name)
    assert backups[0].stat().st_mode & 0o777 == sv.config_path.stat().st_mode & 0o777
    assert (sv.config_path.parent / 'config-backups' / 'config.yaml.earlier').read_text() == 'older backup'
    assert out['mode'] == 'local' and out['route'] == LOCAL
    assert sv.config['cron'] == {'model_provider': 'spark-local', 'model': 'gpt-oss:20b'}
    assert sv.config['fallback_providers'] == []
    assert out['local_provider_registered'] is True
    providers = sv.config['custom_providers']
    assert [p['name'] for p in providers] == ['EhmBird', '10.89.1.246:11434', 'spark-local']
    assert providers[0]['api_key'] == 'sk-secret-ehmbird' and providers[1]['api_key'] == 'sk-secret-lan'  # kept
    assert providers[2] == {'name': 'spark-local', 'base_url': 'http://127.0.0.1:8765/api/llm/local/v1',
                            'model': 'gpt-oss:20b', 'models': ['gpt-oss:20b'], 'api_key': 'gbox-local'}
    assert 'custom_providers' not in sv.sets                    # never through `hermes config set` ...
    assert not any('sk-secret' in arg for args in sv.argv for arg in args)   # ... so no key on a command line
    assert sv.config['model'] == {'default': 'x'}               # the rest of config.yaml is unchanged
    saved = json.loads(sv.path.read_text())
    assert saved['local_mode']['active'] and saved['current_route'] == LOCAL
    assert LOCAL in saved['routes']                             # listed for the Providers view
    since = saved['local_mode']['since']
    sv.sets.clear()
    mtime = sv.config_path.stat().st_mtime_ns
    assert hermes_feedback.adjust_routes()['local_provider_registered'] is False   # steady: nothing re-set
    assert sv.sets == [] and json.loads(sv.path.read_text())['local_mode']['since'] == since
    assert sv.config_path.stat().st_mtime_ns == mtime
    assert len(list((sv.config_path.parent / 'config-backups').glob('*before-spark-local*'))) == 1   # no write, no copy
    sv.data['cooldowns'] = {'nous/' + OPUS: 9e12}               # OpenRouter recovered
    out = hermes_feedback.adjust_routes()
    assert out['mode'] == 'paid' and out['route'] == ROUTER
    assert sv.config['cron'] == {'model_provider': 'openrouter', 'model': OPUS}
    assert sv.config['fallback_providers'] == []                # nous still cooling; the local route is never added
    assert not json.loads(sv.path.read_text())['local_mode']['active']
    sv.data['cooldowns'] = {}
    hermes_feedback.adjust_routes()
    assert sv.config['fallback_providers'] == [NOUS]


def test_supervisor_keeps_a_running_local_run_on_its_route(supervisor, monkeypatch):
    sv = supervisor
    sv.data['cooldowns'] = {'nous/' + OPUS: 9e12, 'openrouter/' + OPUS: 9e12}
    hermes_feedback.adjust_routes()
    sv.data['cooldowns'] = {}
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_jobs', lambda: [{'id': 'run'}])
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_active', lambda _: True)
    held = hermes_feedback.adjust_routes()
    assert held['agent_busy'] and sv.config['cron']['model_provider'] == 'spark-local'


def test_recovered_credit_is_lifted_from_feedback(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    data = {'cooldowns': {'openrouter/' + OPUS: 9e12},
            'cooldown_details': {'openrouter/' + OPUS: {'category': 'quota', 'source': 'scheduler_backoff',
                                                        'observed_at': 100}}}
    (tmp_path / 'feedback.json').write_text(json.dumps(data))
    lifted = hermes_feedback._lift_recovered_credit(data, balance={'available': True, 'remaining_usd': 20,
                                                                   'checked_at': 200}, now=300)
    assert lifted == ['openrouter/' + OPUS] and data['cooldowns'] == {}
    assert json.loads((tmp_path / 'feedback.json').read_text())['cooldowns'] == {}


def test_providers_view_shows_the_local_route_and_what_it_served(monkeypatch, tmp_path):
    import time
    from gbox import hermes_providers
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'state'))
    monkeypatch.setenv('GBOX_HERMES_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('GBOX_CONFIG', str(tmp_path / 'missing.toml'))
    state = tmp_path / 'state'
    state.mkdir()
    now = time.time()
    (state / 'feedback.json').write_text(json.dumps({
        'routes': [NOUS, LOCAL], 'current_route': LOCAL, 'cooldowns': {'nous/' + OPUS: now + 3600},
        'local_mode': {'active': True, 'reason': 'Every paid route is cooling down or out of credit', 'since': now - 60}}))
    calls = [{'ts': now - 30, 'status': 'ok', 'prompt_tokens': 900, 'completion_tokens': 100, 'total_tokens': 1000,
              'duration_s': 4.0, 'fixes': ['added_user_turn']},
             {'ts': now - 20, 'status': 'gated', 'error': 'Local model paused'},
             {'ts': now - 10, 'status': 'ok', 'prompt_tokens': 50, 'completion_tokens': 5, 'total_tokens': 55,
              'duration_s': 1.0, 'dropped': 4}]
    (state / 'local-llm-calls.jsonl').write_text('\n'.join(json.dumps(c) for c in calls) + '\n')
    data = hermes_providers.summary('today', now=now)
    row = next(r for r in data['routes'] if r['provider'] == 'spark-local')
    assert row['local'] and row['current'] and row['model'] == 'gpt-oss:20b'
    local = data['local']
    assert local['active'] and local['model'] == 'gpt-oss:20b' and 'out of credit' in local['reason']
    assert local['calls_ok'] == 2 and local['tokens'] == 1055 and local['refused_while_playing'] == 1
    assert local['fixed_calls'] == 1 and local['trimmed_calls'] == 1


def test_failed_paid_runs_are_never_resumed_on_the_local_route(monkeypatch, tmp_path):
    from gbox import hermes_recovery
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setenv('GBOX_CONFIG', str(tmp_path / 'missing.toml'))
    monkeypatch.setattr(hermes_recovery.hermes_task_mode, '_jobs', lambda: [{'id': 'job', 'name': 'gBox x'}])
    monkeypatch.setattr(hermes_recovery.hermes_task_mode, '_config',
                        lambda: {'cron': {'model_provider': 'spark-local', 'model': 'gpt-oss:20b'}})
    monkeypatch.setattr(hermes_recovery.hermes_task_mode, '_active', lambda _: False)
    monkeypatch.setattr(hermes_recovery, '_active_requests', lambda: set())
    monkeypatch.setattr(hermes_recovery, '_latest_run', lambda _: 'run1')
    hermes_recovery._save({'schema_version': 1, 'jobs': {'job': {
        'job_id': 'job', 'failed_run_id': 'run1', 'request_ids': ['a' * 16], 'checkpoint_at': 1,
        'resumes': [], 'status': 'pending'}}})
    feedback = {'routes': [NOUS], 'cooldowns': {'nous/' + OPUS: 9e12}}
    assert hermes_recovery.recover(feedback, now=1000) == {'status': 'waiting_provider'}


def _executions(home, *runs):
    import sqlite3
    (home / 'cron').mkdir(exist_ok=True)
    with sqlite3.connect(home / 'cron' / 'executions.db') as db:
        db.execute('CREATE TABLE IF NOT EXISTS executions (id TEXT,job_id TEXT,status TEXT,started_at TEXT,'
                   'finished_at TEXT,error TEXT)')
        db.executemany('INSERT INTO executions VALUES (?,?,?,?,NULL,NULL)', runs)


def test_a_run_past_its_deadline_no_longer_holds_the_switch_to_local(supervisor, monkeypatch):
    """2026-10-13: three runs fell through to the CPU llama.cpp model and crawled for 2-3 hours. They kept the
    supervisor 'busy', so it never left Nous or rewrote the fallback chain that still listed llama.cpp and EhmBird."""
    import datetime as dt
    import yaml
    sv = supervisor
    config = yaml.safe_load(sv.config_path.read_text())
    config['fallback_providers'] = [{'provider': 'ollama-cloud', 'model': 'kimi-k2.7-code'},
                                    {'provider': 'llamacpp', 'model': 'Qwen3.6-35B-A3B-UD-Q4_K_M'},
                                    {'provider': 'EhmBird', 'model': 'qwen3.8:27b-mtp-q4_K_M'}]
    sv.config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    sv.data['cooldowns'] = {'nous/' + OPUS: 9e12, 'openrouter/' + OPUS: 9e12, 'ollama-cloud/kimi-k2.7-code': 9e12}
    now = dt.datetime.now(dt.timezone.utc)
    home = sv.config_path.parent
    _executions(home, ('e-new', 'fresh', 'running', (now - dt.timedelta(minutes=10)).isoformat()))
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_jobs', lambda: [{'id': 'fresh'}, {'id': 'stuck'}])
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_active', lambda _: True)
    held = hermes_feedback.adjust_routes()                     # a run 10 minutes in: rotation waits, as before
    assert held['agent_busy'] and held['overdue_runs'] == [] and sv.config['cron']['model_provider'] == 'nous'
    assert [x['provider'] for x in held['excluded_fallbacks']] == ['llamacpp', 'EhmBird']
    _executions(home, ('e-old', 'stuck', 'running', (now - dt.timedelta(hours=3)).isoformat()))
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_active', lambda job: job == 'stuck')
    out = hermes_feedback.adjust_routes()                      # only the 3-hour run is left: it does not hold
    assert out['mode'] == 'local' and not out['agent_busy']
    assert [(o['job_id'], o['execution_id']) for o in out['overdue_runs']] == [('stuck', 'e-old')]
    assert out['overdue_runs'][0]['age_s'] >= 3 * 3600 - 5
    assert sv.config['cron'] == {'model_provider': 'spark-local', 'model': 'gpt-oss:20b'}
    assert sv.config['fallback_providers'] == []               # llama.cpp and EhmBird are gone from Hermes's chain
    assert json.loads(sv.path.read_text())['overdue_runs'][0]['job_id'] == 'stuck'
    monkeypatch.setenv('GBOX_HERMES_RUN_DEADLINE_S', str(4 * 3600))
    assert hermes_feedback.overdue_runs(['stuck'], home=home) == []


@pytest.mark.parametrize('primary', [NOUS, ROUTER, LOCAL])
def test_operator_preference_stays_selected_across_completed_runs(primary):
    preferred = {'provider': 'zai', 'model': 'glm-5.3'}
    result = hermes_local.choose([NOUS, preferred, ROUTER], {}, 1000,
        primary=primary, preferred=preferred, rotation_pending=True, s=S, only_local=False)
    assert result['route'] == preferred
    assert result['fallbacks'] == [NOUS, ROUTER]
    assert 'preferred' in result['reason']


def test_preference_does_not_override_quota_or_add_an_unconfigured_route():
    preferred = {'provider': 'zai', 'model': 'glm-5.3'}
    cooling = {'zai/glm-5.3': 2000}
    result = hermes_local.choose([preferred, NOUS], cooling, 1000,
        primary=preferred, preferred=preferred, s=S, only_local=False)
    assert result['route'] == NOUS and result['fallbacks'] == []
    result = hermes_local.choose([NOUS], {}, 1000,
        primary=NOUS, preferred=preferred, s=S, only_local=False)
    assert result['route'] == NOUS
    result = hermes_local.choose([preferred], cooling, 1000,
        primary=preferred, preferred=preferred, s=S, only_local=False)
    assert result['mode'] == 'local'


def test_local_only_switch_still_overrides_paid_preference():
    result = hermes_local.choose([NOUS, ROUTER], {}, 1000,
        primary=NOUS, preferred=ROUTER, s=S, only_local=True)
    assert result['mode'] == 'local' and result['route'] == LOCAL


@pytest.mark.parametrize('busy', [False, True])
def test_supervisor_reads_preference_but_preserves_active_runs(supervisor, monkeypatch, busy):
    import yaml
    sv = supervisor
    preferred = {'provider': 'zai', 'model': 'glm-5.3'}
    config = sv.config
    config['cron'].update(preferred_provider='zai', preferred_model='glm-5.3')
    sv.config_path.write_text(yaml.safe_dump(config))
    sv.data['routes'].append(preferred)
    sv.data['rotation_pending'] = True
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_jobs', lambda: [{'id': 'active'}] if busy else [])
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_active', lambda _: busy)
    monkeypatch.setattr(hermes_feedback, 'overdue_runs', lambda _: [])
    result = hermes_feedback.adjust_routes()
    assert result['route'] == (NOUS if busy else preferred)
    if busy:
        assert not sv.sets
    else:
        assert sv.config['cron']['model_provider'] == 'zai'
        assert sv.config['cron']['preferred_provider'] == 'zai'
