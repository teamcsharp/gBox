import json

import pytest

from gbox import hermes_availability, hermes_feedback, hermes_quota as quota


def test_retry_after_and_reset_are_observed_not_five_hour_estimates():
    observed = quota.failure_wait({'error': {'code': '1308', 'reset_at': 1800},
                                   'headers': {'Retry-After': '30'}}, 'quota', 1000)
    assert observed['until'] == 1810 and observed['source'] == 'provider_retry_metadata'
    assert not observed['quota_balance_known']
    assert quota.failure_wait('Usage limit reached for 5 hours', 'quota', 1000)['until'] == 1300
    assert quota.failure_wait('Usage limit reached', 'quota', 1000, attempt=20)['until'] == 4600


def test_retry_after_http_date_and_epoch_millisecond_reset():
    assert quota.retry_after('Thu, 01 Jan 1970 00:30:00 GMT', 1000) == 1800
    assert quota.failure_wait({'nextResetTime': 1500000}, 'quota', 1000)['until'] == 1510
    assert quota.reset_at('2026-10-10T16:48:00') is None


@pytest.mark.parametrize('value', [True, float('inf'), float('nan'), {}, None, 'not a timestamp'])
def test_malformed_metadata_cannot_create_an_unbounded_wait(value):
    result = quota.failure_wait({'reset_at': value, 'retry_after': value}, 'quota', 1000)
    assert result['until'] == 1300 and result['source'] == 'scheduler_backoff'


@pytest.mark.parametrize('code', ['1113', '1308', '1310', '1316', '1317', '1318', '1319', '1320', '1321'])
def test_zai_quota_codes_distinct_from_transient_429(code):
    assert quota.provider_failure(json.dumps({'error': {'code': code}})) == 'quota'
    assert quota.provider_failure('HTTP 429 rate_limit_exceeded') == 'rate_limit'
    assert quota.provider_failure('HTTP 400 invalid request: wrong tool schema') is None


def test_saved_routes_merge_new_services_without_secrets_or_duplicates():
    current = {'provider': 'openrouter', 'model': 'a', 'api_key': 'private'}
    result = quota.routes({'cron': {'model_provider': 'deepseek', 'model': 'b'},
                           'fallback_providers': [current, current, {}, None]},
                          [{'provider': 'zai', 'model': 'glm'}])
    assert result == [{'provider': 'deepseek', 'model': 'b'},
                      {'provider': 'openrouter', 'model': 'a'}, {'provider': 'zai', 'model': 'glm'}]
    assert 'private' not in json.dumps(result)


def test_invalid_quota_windows_remain_unknown_and_do_not_leak_opaque_fields():
    for payload in ({'success': True, 'data': []}, [], None):
        assert hermes_availability.quota_status(payload, 1000)['status'] == 'unknown'
    result = hermes_availability.quota_status({'success': True, 'data': {'limits': [None,
        {'type': 'CREDIT_LIMIT', 'remaining': {'token': 'private'}, 'percentage': 'bad'}]}}, 1000)
    assert result['status'] == 'unknown'
    assert 'private' not in json.dumps(result)


def test_provider_display_keeps_account_windows_and_unknown_others_separate(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    (tmp_path / 'zai-availability.json').write_text(json.dumps({'checked_at': 1000,
        'windows': [{'type': 'CREDIT_LIMIT', 'remaining': 12}]}))
    monkeypatch.setattr(hermes_feedback.time, 'time', lambda: 1100)
    config = {'cron': {'model_provider': 'zai', 'model': 'glm-5.3'},
              'fallback_providers': [{'provider': 'deepseek', 'model': 'v4'}]}
    result = hermes_feedback.provider_status({}, config)
    assert result[0]['quota_balance_known'] and result[0]['quota_windows'][0]['remaining'] == 12
    assert not result[0]['quota_observation_stale']
    assert not result[1]['quota_balance_known'] and 'quota_windows' not in result[1]


def test_recorded_usage_includes_cache_and_keeps_cost_estimates_separate(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_home', lambda: tmp_path)
    with sqlite3.connect(tmp_path / 'state.db') as db:
        db.execute('CREATE TABLE sessions (started_at REAL,model TEXT,billing_provider TEXT,input_tokens INT,'
            'output_tokens INT,cache_read_tokens INT,cache_write_tokens INT,api_call_count INT,'
            'actual_cost_usd REAL,estimated_cost_usd REAL,cost_status TEXT)')
        db.executemany('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)', [
            (1000, 'v4', 'deepseek', 100, 7, 300, 20, 4, None, 0.1, 'estimated'),
            (1001, 'v4', 'deepseek', 50, 4, 10, 0, 1, 0.2, None, 'actual'),
            (1002, 'v4', None, 999999, 9999, 0, 0, 1, 0, 0, 'unknown')])
    totals = hermes_feedback._recorded_usage(1100)['deepseek/v4']
    assert totals['tokens_in'] == 480 and totals['tokens_out'] == 11
    assert totals['cache_read_tokens'] == 310 and totals['api_call_count'] == 5
    assert totals['actual_cost_usd'] == 0.2 and totals['estimated_cost_usd'] == 0.1
    assert totals['sessions'] == 2 and totals['actual_cost_sessions'] == 1 and totals['estimated_cost_sessions'] == 1


def test_migration_discards_unobserved_five_hour_guesses(tmp_path, monkeypatch):
    import sqlite3
    home = tmp_path / 'home'
    (home / 'cron').mkdir(parents=True)
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    (tmp_path / 'feedback.json').write_text(json.dumps({'schema_version': 3, 'processed': [], 'lessons': [],
        'cooldowns': {'deepseek/guessed': 19000, 'zai/glm-5.3': 19000}}))
    (tmp_path / 'zai-availability.json').write_text(json.dumps({'status': 'quota_wait',
        'next_check_at': 2000, 'windows': [{'type': 'CREDIT_LIMIT', 'remaining': 0}]}))
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT,job_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT)')
    result = hermes_feedback.scan(home=home, now=1000)
    assert result['cooldowns'] == {'zai/glm-5.3': 2000}
    assert result['cooldown_details']['zai/glm-5.3']['source'] == 'provider_account_endpoint'


def test_provider_usage_uses_route_deltas_after_fallback_without_double_counting(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_home', lambda: tmp_path)
    with sqlite3.connect(tmp_path / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT,started_at REAL,model TEXT,billing_provider TEXT,'
            'input_tokens INT,output_tokens INT,cache_read_tokens INT,api_call_count INT,estimated_cost_usd REAL)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)',
            ('mixed', 1000, 'backup', 'deepseek', 150, 8, 20, 3, 0.3))
        db.execute('CREATE TABLE session_model_usage (session_id TEXT,model TEXT,billing_provider TEXT,'
            'input_tokens INT,output_tokens INT,cache_read_tokens INT,api_call_count INT,estimated_cost_usd REAL)')
        db.executemany('INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?)', [
            ('mixed', 'original', 'zai', 100, 5, 10, 2, 0.1),
            ('mixed', 'backup', 'deepseek', 50, 3, 10, 1, 0.2)])
    totals = hermes_feedback._recorded_usage(1100)
    assert totals['zai/original']['tokens_in'] == 110
    assert totals['deepseek/backup']['tokens_in'] == 60
    assert totals['zai/original']['api_call_count'] == 2 and totals['deepseek/backup']['api_call_count'] == 1
    assert totals['zai/original']['sessions'] == 1 and totals['deepseek/backup']['sessions'] == 1
    assert all(x['legacy_residual_tokens_in'] == 0 and x['legacy_residual_api_calls'] == 0 for x in totals.values())
    assert all(x['source'] == 'hermes_route_usage_ledger' for x in totals.values())


def test_usage_reconciles_missing_legacy_deltas_and_labels_the_residual(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_home', lambda: tmp_path)
    with sqlite3.connect(tmp_path / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT,started_at REAL,model TEXT,billing_provider TEXT,'
            'input_tokens INT,output_tokens INT,cache_read_tokens INT,api_call_count INT)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)', ('partial', 1000, 'glm', 'zai', 100, 8, 20, 3))
        db.execute('CREATE TABLE session_model_usage (session_id TEXT,model TEXT,billing_provider TEXT,'
            'input_tokens INT,output_tokens INT,cache_read_tokens INT,api_call_count INT)')
        db.execute('INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?)', ('partial', 'glm', 'zai', 80, 6, 15, 2))
    total = hermes_feedback._recorded_usage(1100)['zai/glm']
    assert total['tokens_in'] == 120 and total['tokens_out'] == 8 and total['api_call_count'] == 3
    assert total['legacy_residual_tokens_in'] == 25 and total['legacy_residual_tokens_out'] == 2
    assert total['legacy_residual_api_calls'] == 1 and total['source'] == 'hermes_route_usage_with_legacy_residual'
    assert total['sessions'] == 1


def test_default_zero_actual_cost_is_not_a_provider_billing_observation(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_home', lambda: tmp_path)
    with sqlite3.connect(tmp_path / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT,started_at REAL,model TEXT,billing_provider TEXT,input_tokens INT)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', ('s', 1000, 'model', 'provider', 10))
        db.execute('CREATE TABLE session_model_usage (session_id TEXT,model TEXT,billing_provider TEXT,'
                   'input_tokens INT,actual_cost_usd REAL,estimated_cost_usd REAL,cost_status TEXT)')
        db.execute('INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?)', ('s', 'model', 'provider', 10, 0, 0.1, 'estimated'))
    total = hermes_feedback._recorded_usage(1100)['provider/model']
    assert total['actual_cost_usd'] is None and total['actual_cost_sessions'] == 0
    assert total['estimated_cost_usd'] == 0.1 and total['estimated_cost_sessions'] == 1
