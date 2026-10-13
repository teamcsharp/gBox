"""A paid route whose account is out of credit or at its usage limit is unavailable to the route supervisor, even when
Hermes skipped it silently (2026-10-13).

Nous answered every call with HTTP 404 "requires available credits ... balance is too low" and Ollama Cloud with
HTTP 429 "monthly usage limit". Hermes fell through its fallback chain, so each run ended on the last fallback's error
(EhmBird's HTTP 500) or kept running on the CPU llama.cpp model. hermes_feedback.scan cooled a route only from a run's
final error, so neither provider was ever cooled, choose() kept routing to Nous, and the local route never took over.
Now the agent log's per-call errors cool every route of an exhausted provider (hermes_feedback.apply_exhaustion).
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from gbox import hermes_feedback, hermes_local, hermes_providers as hp, hermes_quota
from gbox.config import HermesLocalConfig

OPUS = 'anthropic/claude-opus-5.5'
KIMI = 'kimi-k2.7-code'
NOUS, OLLAMA = {'provider': 'nous', 'model': OPUS}, {'provider': 'ollama-cloud', 'model': KIMI}
ROUTER = {'provider': 'openrouter', 'model': OPUS}
LOCAL = {'provider': 'spark-local', 'model': 'gpt-oss:20b'}
S = HermesLocalConfig(proxy_url='http://127.0.0.1:8765/api/llm/local/v1')
NOUS_404 = ("HTTP 404: Model 'anthropic/claude-opus-5.5' requires available credits. Your account balance is too low "
            "to use paid models — add credits at https://portal.nousresearch.com or pick a free model.")
OLLAMA_429 = ('HTTP 429: you (gbox) have reached your monthly usage limit, upgrade for higher limits: '
              'https://ollama.com/upgrade or add usage credits: https://ollama.com/settings')
H = 3600


def health(*items):
    """provider_health() rows: (provider, last_ok, error_ts, text)."""
    out = {}
    for provider, ok, ts, text in items:
        err = None if ts is None else {'ts': ts, 'text': text, 'code': None, 'kind': hp.error_kind(text),
                                        'model': None}
        out[provider] = {'last_ok': ok, 'last_error': err}
    return out


def test_out_of_credit_404_and_monthly_limit_are_classified():
    assert hp.error_kind(NOUS_404) == 'out_of_credit'           # a 404, but it says the balance is too low
    assert hp.error_kind(OLLAMA_429) == 'usage_limit'           # a 429, but not a throttle
    assert hp.error_kind('HTTP 429: Too Many Requests') == 'rate_limited'
    assert hp.error_kind('HTTP 404: model not found') == 'failing'
    for text in (NOUS_404, OLLAMA_429, 'HTTP 404: requires available credits',
                 'Your account balance is too low to use paid models', 'HTTP 402: Insufficient Balance'):
        assert hermes_quota.provider_failure(text) == 'quota', text
        assert hermes_feedback.classify(text) == 'quota', text
    assert hermes_quota.provider_failure('HTTP 429: Too Many Requests') == 'rate_limit'


def test_exhaustion_waits_are_long_and_double_to_a_cap():
    wait = lambda kind, text, n: hermes_quota.exhaustion_wait(kind, text, 0, failures=n)['until']
    assert [wait('out_of_credit', NOUS_404, n) / H for n in (1, 2, 3, 4, 9)] == [3, 6, 12, 12, 12]
    assert [wait('usage_limit', OLLAMA_429, n) / H for n in (1, 2, 3, 9)] == [6, 12, 24, 24]
    assert [wait('usage_limit', 'HTTP 429: usage limit reached', n) / H for n in (1, 2, 3, 4)] == [1, 2, 4, 6]
    assert hermes_quota.exhaustion_wait('out_of_credit', '', 0)['source'] == hermes_quota.EXHAUSTED_SOURCE


def test_paid_routes_out_of_credit_without_cooldowns_move_choose_to_local():
    now = 100 * H
    data = {'routes': [NOUS, OLLAMA, ROUTER], 'current_route': NOUS, 'cooldowns': {'openrouter/' + OPUS: now + 40 * H},
            'cooldown_details': {'openrouter/' + OPUS: {'source': 'provider_account_endpoint', 'category': 'quota'}}}
    # Before: nothing cools Nous or Ollama Cloud, so choose() stays on Nous.
    assert hermes_local.choose([NOUS, OLLAMA, ROUTER], data['cooldowns'], now, primary=NOUS, s=S,
                               only_local=False)['route'] == NOUS
    seen = health(('nous', now - 4 * H, now - H, NOUS_404), ('ollama-cloud', now - 12 * H, now - 2 * H, OLLAMA_429),
                  ('ehmbird', now - 3 * H, now - H, 'HTTP 500: no user query found in messages'),
                  ('spark-local', None, now - H, 'HTTP 402: payment required'))       # never the local route
    hermes_feedback.apply_exhaustion(data, seen, now, local_provider='spark-local')
    assert data['cooldowns']['nous/' + OPUS] == now - H + 3 * H
    assert data['cooldowns']['ollama-cloud/' + KIMI] == now - 2 * H + 6 * H
    assert data['cooldowns']['openrouter/' + OPUS] == now + 40 * H                   # a longer measured wait stays
    assert data['cooldown_details']['nous/' + OPUS]['source'] == 'provider_exhausted_backoff'
    assert set(data['exhausted']) == {'nous', 'ollama-cloud'}
    pick = hermes_local.choose([NOUS, OLLAMA, ROUTER], data['cooldowns'], now, primary=NOUS, s=S, only_local=False)
    assert pick['mode'] == 'local' and pick['route'] == LOCAL and pick['fallbacks'] == []
    assert pick['next_paid_at'] == now + 2 * H                                      # Nous is probed first


def test_recovery_probe_then_backoff_then_rotation_back_when_credit_returns():
    t0 = 100 * H
    data = {'routes': [NOUS], 'cooldowns': {}, 'cooldown_details': {}}
    hermes_feedback.apply_exhaustion(data, health(('nous', t0 - H, t0, NOUS_404)), t0 + 60, local_provider='spark-local')
    assert data['cooldowns'] == {'nous/' + OPUS: t0 + 3 * H}
    # The same error seen again does not restart or lengthen the wait.
    hermes_feedback.apply_exhaustion(data, health(('nous', t0 - H, t0, NOUS_404)), t0 + H, local_provider='spark-local')
    assert data['exhausted']['nous']['failures'] == 1 and data['cooldowns']['nous/' + OPUS] == t0 + 3 * H
    # After the wait the route is eligible again: the next run on it is the probe, so the supervisor rotates back.
    later = t0 + 3 * H + 60
    data['cooldowns'] = {k: v for k, v in data['cooldowns'].items() if v > later}        # what scan() drops
    hermes_feedback.apply_exhaustion(data, health(('nous', t0 - H, t0, NOUS_404)), later, local_provider='spark-local')
    assert data['cooldowns'] == {}
    pick = hermes_local.choose([NOUS], data['cooldowns'], later, primary=LOCAL, s=S, only_local=False)
    assert pick['mode'] == 'paid' and pick['route'] == NOUS and 'rotated back' in pick['reason']
    # The probe failed the same way: the wait doubles.
    probe = later + 30
    hermes_feedback.apply_exhaustion(data, health(('nous', t0 - H, probe, NOUS_404)), probe + 5,
                                     local_provider='spark-local')
    assert data['exhausted']['nous']['failures'] == 2 and data['cooldowns']['nous/' + OPUS] == probe + 6 * H
    assert hermes_local.choose([NOUS], data['cooldowns'], probe + 5, primary=NOUS, s=S, only_local=False)['mode'] == 'local'
    # Credit was added and a call worked (an interactive Hermes chat, say): the route is back at once.
    hermes_feedback.apply_exhaustion(data, health(('nous', probe + 600, probe, NOUS_404)), probe + 700,
                                     local_provider='spark-local')
    assert data['exhausted'] == {} and data['cooldowns'] == {} and data['cooldown_details'] == {}
    pick = hermes_local.choose([NOUS], data['cooldowns'], probe + 700, primary=LOCAL, s=S, only_local=False)
    assert pick['mode'] == 'paid' and pick['route'] == NOUS


def test_openrouter_balance_lifts_the_out_of_credit_wait_and_the_same_error_does_not_reapply_it(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    now = 100 * H
    seen = health(('openrouter', now - 5 * H, now - H, "HTTP 402: This request's maximum cost exceeds your available "
                                                       'credits. Add credits, or lower max_tokens or prompt size.'))
    data = {'routes': [ROUTER], 'cooldowns': {}, 'cooldown_details': {}}
    hermes_feedback.apply_exhaustion(data, seen, now, local_provider='spark-local')
    assert data['cooldowns'] == {'openrouter/' + OPUS: now + 2 * H}
    (tmp_path / 'feedback.json').write_text(json.dumps(data))
    lifted = hermes_feedback._lift_recovered_credit(
        data, balance={'available': True, 'remaining_usd': 20.0, 'checked_at': now - 60}, now=now)
    assert lifted == ['openrouter/' + OPUS] and data['cooldowns'] == {}
    hermes_feedback.apply_exhaustion(data, seen, now + 300, local_provider='spark-local')
    assert data['cooldowns'] == {}                                   # lifted stays lifted for that error
    saved = json.loads((tmp_path / 'feedback.json').read_text())
    assert saved['cooldowns'] == {} and saved['exhausted']['openrouter']['until'] == now


def _log_line(t, msg, tag=None, level='INFO'):
    return f"{t:%Y-%m-%d %H:%M:%S},000 {level}{f' [{tag}]' if tag else ''} run_agent: {msg}\n"


def test_scan_cools_providers_hermes_fell_through_from_its_agent_log(monkeypatch, tmp_path):
    """The real path: the run's final error is EhmBird's 500 (category 'other'), Nous and Ollama Cloud failed only
    on calls inside the run, and scan() still cools them."""
    hp._SCANNERS.clear()
    home, state = tmp_path / '.hermes', tmp_path / 'dispatch'
    (home / 'logs').mkdir(parents=True); (home / 'cron').mkdir(); state.mkdir()
    monkeypatch.setenv('GBOX_HERMES_HOME', str(home))
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(state))
    monkeypatch.setenv('GBOX_HERMES_LOG_TZ', '+00:00')
    monkeypatch.setenv('GBOX_CONFIG', str(tmp_path / 'missing.toml'))
    monkeypatch.delenv('GBOX_HERMES_AGENT_LOG', raising=False)
    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=30)
    tag = f'cron_job1_{start:%Y%m%d_%H%M%S}'
    ctx = lambda p, m, u: f'thread=Thread-9 (<lambda>):1 provider={p} base_url={u} model={m}'
    fail = lambda t, p, m, u, text: _log_line(t, f'API call failed (attempt 1/3) error_type=APIStatusError '
                                                 f'{ctx(p, m, u)} summary={text}', tag, 'WARNING')
    created = lambda t, p, m, u: _log_line(t, f'OpenAI client created (chat_completion_stream_request, shared=False) '
                                              f'{ctx(p, m, u)}', tag)
    s = lambda sec: start + timedelta(seconds=sec)
    nous, ollama, bird = 'https://inference-api.nousresearch.com/v1', 'https://ollama.com/v1', 'http://localhost:11434/v1'
    (home / 'logs' / 'agent.log').write_text(''.join([
        created(s(1), 'nous', OPUS, nous), fail(s(2), 'nous', OPUS, nous, NOUS_404),
        created(s(3), 'ollama-cloud', KIMI, ollama), fail(s(4), 'ollama-cloud', KIMI, ollama, OLLAMA_429),
        created(s(5), 'ehmbird', 'qwen3.8:27b', bird),
        fail(s(6), 'ehmbird', 'qwen3.8:27b', bird, 'HTTP 500: no user query found in messages')]), encoding='utf-8')
    with sqlite3.connect(home / 'cron' / 'executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT,job_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)', ('run1', 'job1', 'failed', s(0).isoformat(),
                   s(7).isoformat(), 'RuntimeError: HTTP 500: no user query found in messages'))
    (home / 'cron' / 'jobs.json').write_text(json.dumps({'jobs': [{'id': 'job1', 'provider': 'nous', 'model': OPUS}]}))
    (state / 'feedback.json').write_text(json.dumps({'schema_version': 4, 'processed': [], 'lessons': [],
                                                     'cooldowns': {}, 'cooldown_details': {},
                                                     'routes': [NOUS, OLLAMA], 'current_route': NOUS}))
    data = hermes_feedback.scan(home=home, now=s(60).timestamp())
    assert data['lessons'][-1]['category'] == 'other'               # the run's own error cools nothing ...
    assert set(data['cooldowns']) == {'nous/' + OPUS, 'ollama-cloud/' + KIMI}   # ... the agent log does
    assert data['cooldowns']['nous/' + OPUS] == pytest.approx(s(2).timestamp() + 3 * H)
    assert data['exhausted']['ollama-cloud']['kind'] == 'usage_limit'
    assert json.loads((state / 'feedback.json').read_text())['cooldowns'] == data['cooldowns']
    pick = hermes_local.choose([NOUS, OLLAMA], data['cooldowns'], s(60).timestamp(), primary=NOUS, s=S, only_local=False)
    assert pick['mode'] == 'local' and pick['route'] == LOCAL
    hp._SCANNERS.clear()
