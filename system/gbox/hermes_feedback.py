"""Learn from durable executions without mistaking model usage for delivery."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sqlite3
import subprocess
import time

from . import hermes_delivery, hermes_task_mode, hermes_quota


ADVICE = {
    'quota': 'Use an available connected provider; preserve the patch and wait for the exhausted model cooldown.',
    'rate_limit': 'Back off this model and use another connected route; do not repeat the same throttled request.',
    'vision_history': 'Use auxiliary vision returning text. Do not append native image/model history to the failing route.',
    'worker_timeout': 'Check worker health once. Use start_job/get_job and keep the same job ID; continue Git source work while the worker is unavailable.',
    'permission': 'Check current task capabilities: historical cron denials do not describe current policy. Use prepare_task_workspace/publish_task_changes for tracked source delivery. Record any remaining exact permission or dependency failure and correct its cause before retrying.',
    'scheduler_claim': 'Use a finite genuine one-shot dispatched by the gateway. Preserve the prior execution; do not run the same occurrence from two launchers.',
    'turn_budget': 'Resume the saved patch at validation/publication. Use high reasoning, focused tests and a 45-tool-call work budget, reserving the final 10 calls for handoff.',
    'no_publication': 'Use a tracked task workspace, validate its patch and publish a draft PR. A canonical-share edit alone is not GitHub delivery.',
    'workspace_state': 'Use the canonical gBox MCP process with Python -P and the shared GBOX_HERMES_DISPATCH_STATE. Reuse the saved workspace record instead of creating another branch.',
    'capture_occlusion': 'The capture was blocked by a covered or unavailable emulator window, not proof of a black or frozen game. Refresh the current session and PID once. On the authorized idle test PC, present only that owned game window or use its current GPU capture surface, then capture once more. Do not change the operator PC, disable occlusion validation, or substitute desktop pixels as gameplay evidence. If capture is still unavailable, retain that failure and leave visual acceptance pending.',
    'checkpoint_container': 'Preserve the rejected or unfinished checkpoint and its hash. Verify the full bounded container before import or export; never bypass validation, overwrite the original, or call an older checkpoint the same reported moment. If the owned test session is still live, obtain a separate completed native save, validate it and test load/frame advance/reload. Otherwise report the precise missing state evidence and continue source work.',
    'other': 'Read the prior failure and saved patch; change the failed step before retrying and report an observable result.',
}


def _save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


def classify(error: str) -> str:
    text = error.lower()
    if 'filenotfounderror' in text and 'hermes-dispatch' in text:
        return 'workspace_state'
    if category := hermes_quota.provider_failure(error):
        return category
    if 'model turn' in text or 'http 400' in text:
        return 'vision_history'
    if 'claim ownership' in text or 'restart-safe cron worker' in text:
        return 'scheduler_claim'
    if ('game window is covered by another app' in text or
            'game window isn\'t open' in text or
            ('notreadableerror' in text and ('video' in text or 'capture' in text))):
        return 'capture_occlusion'
    if ('saved checkpoint container could not be validated' in text or
            'saved checkpoint container exceeds inspection budget' in text or
            'saved checkpoint contains no core state' in text or
            'saved checkpoint is empty' in text):
        return 'checkpoint_container'
    if 'timed out' in text or 'worker is unavailable' in text or 'worker is saturated' in text:
        return 'worker_timeout'
    if 'denied' in text or 'blocked without approvals' in text or 'permission' in text:
        return 'permission'
    return 'other'


def _stamp(text):
    try:
        return dt.datetime.fromisoformat(text).timestamp()
    except (ValueError, TypeError):
        return 0


def tool_error(content: str) -> str:
    """Extract failures, not quotations inside successful inbox/source reads."""
    if content.startswith('<untrusted_tool_result'):
        content = content.split('\n\n', 1)[-1]
    try:
        result, _ = json.JSONDecoder().raw_decode(content.lstrip())
    except (ValueError, TypeError):
        return ''
    if not isinstance(result, dict):
        return ''
    if isinstance(result.get('error'), str):
        # Hermes sometimes wraps an MCP error's JSON as an error string.
        return tool_error(result['error']) or result['error']
    if result.get('isError'):
        return ' '.join(c.get('text', '') for c in result.get('content', []) if isinstance(c, dict))
    return ''


def scan(*, home: Path | None = None, now: float | None = None) -> dict:
    home, now = home or hermes_task_mode._home(), time.time() if now is None else now
    target = hermes_delivery.state_dir() / 'feedback.json'
    with hermes_delivery.locked('feedback'):
        data = json.loads(target.read_text()) if target.exists() else {'processed': [], 'lessons': [], 'cooldowns': {}}
        if data.get('schema_version') != 4:
            # Retire unlabelled guessed waits, keeping waits with provenance.
            data['cooldowns'] = {k: v for k, v in data.get('cooldowns', {}).items()
                                 if k in data.get('cooldown_details', {})}
            quota_path = hermes_delivery.state_dir() / 'zai-availability.json'
            if quota_path.exists():
                try:
                    observed = json.loads(quota_path.read_text())
                    if observed.get('windows') and observed.get('status') == 'quota_wait':
                        data['cooldowns']['zai/glm-5.3'] = observed.get('next_check_at', now)
                        data.setdefault('cooldown_details', {})['zai/glm-5.3'] = {
                            'source': 'provider_account_endpoint', 'quota_balance_known': True}
                except (OSError, ValueError):
                    pass
            # Recompute derived lessons under the corrected retry policy.
            data.update(schema_version=4, processed=[], lessons=[])
        data.setdefault('cooldowns', {})
        data.setdefault('cooldown_details', {})
        path = home / 'cron/executions.db'
        if not path.exists():
            return data
        db = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True); db.row_factory = sqlite3.Row
        runs = db.execute("SELECT id,job_id,status,started_at,finished_at,error FROM executions "
                          "WHERE status IN ('completed','failed','unknown') ORDER BY started_at DESC LIMIT 100").fetchall()
        state_path = home / 'state.db'
        state = sqlite3.connect(f'file:{state_path.as_posix()}?mode=ro', uri=True) if state_path.exists() else None
        if state:
            state.row_factory = sqlite3.Row
        jobs_path = home / 'cron/jobs.json'
        jobs = {j['id']: j for j in json.loads(jobs_path.read_text()).get('jobs', [])} if jobs_path.exists() else {}
        added = []
        for run in reversed(runs):
            if run['id'] in data['processed']:
                continue
            data['processed'].append(run['id'])
            job, session = jobs.get(run['job_id'], {}), None
            if state and run['started_at']:
                session = hermes_task_mode_session(state, run['job_id'], _stamp(run['started_at']))
            error = run['error'] or ''
            provider_error = hermes_quota.provider_failure(error) if run['status'] == 'failed' else None
            provider = (session['billing_provider'] if session and 'billing_provider' in session.keys() else None) or job.get('provider')
            model = (session['model'] if session else None) or job.get('model')
            category = classify(error) if run['status'] != 'completed' else None
            if session:
                messages = state.execute("SELECT content,tool_name FROM messages WHERE session_id=? AND role='tool'", (session['id'],)).fetchall()
                failures = [kind for m in messages if (tool_failure := tool_error(m['content'] or ''))
                            and (kind := classify(tool_failure)) != 'other']
                if failures and category in (None, 'other'):
                    category = max(set(failures), key=failures.count)
                if (session['output_tokens'] or 0) > 50000 or (session['api_call_count'] or 0) >= 140:
                    category = category or 'turn_budget'
                wrote_code = any(m['tool_name'] in ('patch', 'write_file') for m in messages)
                published = any((m['tool_name'] or '').endswith('publish_task_changes') and
                                'github.com/' in (m['content'] or '') for m in messages)
                if not category and wrote_code and not published:
                    category = 'no_publication'
            if session:
                data['rotation_pending'] = True
            if not category:
                continue  # successful script-only maintenance consumes no inference
            lesson = {'run_id': run['id'], 'job_id': run['job_id'], 'provider': provider, 'model': model,
                      'category': category, 'advice': ADVICE[category], 'observed_at': _stamp(run['finished_at']) or now}
            data['lessons'].append(lesson); added.append(lesson)
            # A tool quota (e.g. a remote operation) is not the LLM provider's
            # billing quota. Only a failed inference execution cools that route.
            if provider and model and provider_error:
                key = provider + '/' + model
                previous = data['cooldown_details'].get(key, {})
                attempt = previous.get('failures', 0) + 1 if now - previous.get('observed_at', 0) < 86400 else 1
                wait = hermes_quota.failure_wait(error, provider_error, lesson['observed_at'], attempt=attempt)
                prior_until = data['cooldowns'].get(key, 0)
                data['cooldowns'][key] = max(prior_until, wait['until'])
                if wait['until'] >= prior_until:
                    data['cooldown_details'][key] = wait | {'category': provider_error, 'failures': attempt,
                                                           'observed_at': lesson['observed_at']}
                else:
                    # A shorter policy backoff cannot relabel a measured account
                    # reset that is still controlling the actual route deadline.
                    data['cooldown_details'][key] = previous | {'failures': attempt,
                                                               'last_failure_at': lesson['observed_at']}
                if now - lesson['observed_at'] <= 86400 and session:
                    from . import hermes_recovery, hermes_tasks
                    hermes_recovery.checkpoint(run, job, session,
                        hermes_tasks._owned_requests(state, session['id']), now=now)
        db.close()
        if state:
            state.close()
        data['processed'] = data['processed'][-512:]
        data['lessons'] = data['lessons'][-100:]
        data['cooldowns'] = {k: v for k, v in data['cooldowns'].items() if v > now}
        data['cooldown_details'] = {k: v for k, v in data['cooldown_details'].items() if k in data['cooldowns']}
        data['updated_at'] = now
        data['new_lessons'] = len(added)
        _save(target, data)
        return data


def hermes_task_mode_session(state, job_id, started):
    from .hermes_tasks import _session
    return _session(state, job_id, started)


def brief() -> str:
    path = hermes_delivery.state_dir() / 'feedback.json'
    if not path.exists():
        return ''
    data = json.loads(path.read_text())
    categories = {x['category'] for x in data.get('lessons', [])[-20:]}
    return '\nLessons from actual previous runs: ' + ' '.join(ADVICE[c] for c in sorted(categories))


def canonical_mcp(config):
    mcp = (config.get('mcp_servers') or {}).get('gbox')
    if not mcp or not Path(mcp.get('command', '')).name.lower().startswith('python'):
        return None
    args = list(mcp.get('args') or [])
    if not any(args[i:i + 2] == ['-m', 'gbox'] for i in range(len(args))):
        return None
    if '-P' not in args:
        args.insert(0, '-P')
    env = dict(mcp.get('env') or {})
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]),
               GBOX_HERMES_DISPATCH_STATE=str(hermes_delivery.state_dir()))
    fixed = mcp | {'args': args, 'env': env}
    return fixed if fixed != mcp else None


def finalize_usage() -> dict:
    """Reconcile ended inbox runs independently of route availability or live work."""
    from . import hermes_accounting
    from .hermes_availability import _api
    try:
        results = hermes_accounting.reconcile_completed(api=_api, home=hermes_task_mode._home(), limit=10)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        # Accounting must not interrupt quota monitoring; exception text can
        # contain private transport details, so retain its class only.
        return {'status': 'deferred', 'error_type': type(error).__name__}
    return {'checked_runs': len(results), 'runs': results,
            'tokens_in_added': sum(item.get('tokens_in_added', 0) for item in results),
            'tokens_out_added': sum(item.get('tokens_out_added', 0) for item in results)}


def finalize_merges() -> dict:
    """Post merged/closed PR outcomes on their requests (#1300); never block routing."""
    from . import hermes_merges
    from .hermes_availability import _api
    out = {}
    for key, step in (('pulls', hermes_merges.reconcile), ('branches', hermes_merges.reconcile_branches)):
        try:
            out[key] = step(_api)
        except Exception as error:  # GitHub or the inbox may be unreachable
            out[key] = {'status': 'deferred', 'error_type': type(error).__name__}
    return out


def finalize_cap() -> dict:
    """Block a ticket the inbox job keeps taking and ask the operator (#1300); never block routing."""
    from . import hermes_summaries
    from .hermes_availability import _api
    try:
        return hermes_summaries.enforce_cap(_api)
    except Exception as error:
        return {'status': 'deferred', 'error_type': type(error).__name__}


def finalize_summaries() -> dict:
    """Post each ended run's outcome on the tickets it worked on (#1300); never block routing."""
    from . import hermes_summaries
    from .hermes_availability import _api
    try:
        return hermes_summaries.reconcile(_api, home=hermes_task_mode._home())
    except Exception as error:  # the inbox or Hermes's databases may be unavailable
        return {'status': 'deferred', 'error_type': type(error).__name__}


def finalize_cleanup() -> dict:
    """Stop servers ended task runs left in their worktrees (#1304); never block routing."""
    from . import hermes_cleanup
    from .hermes_availability import _api
    try:
        return hermes_cleanup.sweep(_api, home=hermes_task_mode._home())
    except Exception as error:  # /proc, Hermes's databases or the inbox may be unavailable
        return {'status': 'deferred', 'error_type': type(error).__name__}


def adjust_routes() -> dict:
    accounting = finalize_usage()
    merges = finalize_merges()
    summaries = finalize_summaries()
    capped = finalize_cap()
    cleanup = finalize_cleanup()
    data, config = scan(), hermes_task_mode._config()
    cli = str(hermes_task_mode._cli())
    repaired = canonical_mcp(config)
    if repaired:
        result = subprocess.run([cli, 'config', 'set', 'mcp_servers.gbox', json.dumps(repaired)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError('Hermes canonical MCP configuration update failed')
    cron = config.get('cron') or {}
    from . import hermes_local
    local = hermes_local.settings()
    routes = hermes_quota.routes(config, data.get('routes') or [])
    primary = {'provider': cron.get('model_provider'), 'model': cron.get('model')}
    if (primary not in routes and all(primary.values()) and primary['provider'].casefold() not in hermes_quota.excluded_providers()
            and not hermes_local.is_local(primary, local)):
        routes.insert(0, primary)
    # The local route is never a paid route's fallback: it is chosen alone, only when no paid route is left.
    paid = [r for r in routes if not hermes_local.is_local(r, local)]
    lifted = _lift_recovered_credit(data)
    # Rotation is done only between agent runs. Never mutate an in-flight route.
    busy = any(hermes_task_mode._active(j['id']) and not j.get('no_agent') for j in hermes_task_mode._jobs())
    pick = hermes_local.choose(paid, data['cooldowns'], time.time(), primary=primary,
                               rotation_pending=bool(data.get('rotation_pending')), busy=busy, s=local)
    shown = paid + ([hermes_local.route(local)] if local.enabled else [])   # the Providers view lists the local route
    if busy or pick['mode'] == 'none':
        path = hermes_delivery.state_dir() / 'feedback.json'
        with hermes_delivery.locked('feedback'):
            saved = json.loads(path.read_text())
            saved['routes'] = shown
            saved['completed_usage'] = accounting
            _save(path, saved)
        return {'changed': False, 'reason': 'Agent run is active' if busy else 'All connected routes are cooling down',
                'route': primary, 'agent_busy': busy, 'cooldowns': data['cooldowns'],
                'new_lessons': data['new_lessons'], 'providers': provider_status(data, config),
                'completed_usage': accounting, 'credit_recovered': lifted}
    chosen = pick['route']
    changes = {}
    if pick['mode'] == 'local':
        providers = hermes_local.merged_providers(config.get('custom_providers'), local)
        if providers is not None:
            changes['custom_providers'] = providers
    changes.update({'cron.model_provider': chosen['provider'], 'cron.model': chosen['model'],
                    'fallback_providers': pick['fallbacks']})
    for key, value in changes.items():
        old = config.get(key) if '.' not in key else cron.get(key.split('.')[1])
        if old != value:
            result = subprocess.run([cli, 'config', 'set', key, json.dumps(value) if isinstance(value, list) else value],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError('Hermes route update failed: ' + key)
    path = hermes_delivery.state_dir() / 'feedback.json'
    with hermes_delivery.locked('feedback'):
        saved = json.loads(path.read_text())
        saved.update(routes=shown, current_route=chosen, completed_usage=accounting)
        previous = saved.get('local_mode') or {}
        now = time.time()
        if pick['mode'] == 'local':
            saved['local_mode'] = {'active': True, 'reason': pick['reason'], 'next_paid_at': pick['next_paid_at'],
                                   'since': previous.get('since') if previous.get('active') else now}
        else:
            saved['local_mode'] = {'active': False, 'reason': pick['reason'], 'next_paid_at': None,
                                   'since': previous.get('since') if previous and not previous.get('active') else now}
        if chosen != primary or not busy:
            saved['rotation_pending'] = False
        _save(path, saved)
    from .hermes_recovery import recover
    return {'route': chosen, 'mode': pick['mode'], 'mode_reason': pick['reason'],
            'cooldowns': data['cooldowns'], 'new_lessons': data['new_lessons'], 'agent_busy': busy,
            'providers': provider_status(saved, config), 'recovery': recover(saved),
            'completed_usage': accounting, 'merges': merges, 'summaries': summaries,
            'capped': capped, 'cleanup': cleanup, 'credit_recovered': lifted,
            'repairs': ['canonical_mcp_workspace'] if repaired else []}


def _lift_recovered_credit(data, *, balance=None, now=None) -> list[str]:
    """End an OpenRouter quota cooldown early when its account shows credit again (the operator topped it up)."""
    from . import hermes_local
    now = time.time() if now is None else now
    if not any(v > now and k.startswith('openrouter/') for k, v in data.get('cooldowns', {}).items()):
        return []
    if balance is None:
        try:
            from .hermes_providers import openrouter_balance
            balance = openrouter_balance(wait=True)
        except Exception:                      # noqa: BLE001 - a balance check never blocks route supervision
            return []
    keys = hermes_local.credit_recovered(data['cooldowns'], data.get('cooldown_details', {}), balance, now)
    if not keys:
        return []
    path = hermes_delivery.state_dir() / 'feedback.json'
    with hermes_delivery.locked('feedback'):
        saved = json.loads(path.read_text()) if path.exists() else {}
        for target in (data, saved):
            for key in keys:
                target.get('cooldowns', {}).pop(key, None)
                target.get('cooldown_details', {}).pop(key, None)
        _save(path, saved)
    return keys


def _recorded_usage(now):
    """Recorded session counters are distinct from account remaining allowance."""
    from . import hermes_tasks
    db = hermes_tasks._db(hermes_task_mode._home() / 'state.db')
    if not db:
        return {}
    totals, attributed, session_ids, actual_ids, estimated_ids = {}, {}, {}, {}, {}
    token_keys = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'api_call_count')

    def value(row, key):
        return row[key] or 0 if key in row.keys() else 0

    def accumulate(row, sid, *, legacy, complete):
        provider, model = value(row, 'billing_provider'), value(row, 'model')
        if not provider or not model:
            return  # Unknown attribution is never filled from today's route.
        key = provider + '/' + model
        total = totals.setdefault(key, {'source': 'hermes_route_usage_ledger', 'window_start': now - 86400,
            'window_scope': 'sessions_started_last_24h', 'observed_at': now,
            'sessions': 0, 'tokens_in': 0, 'tokens_out': 0, 'cache_read_tokens': 0,
            'cache_write_tokens': 0, 'api_call_count': 0, 'actual_cost_usd': 0,
            'actual_cost_sessions': 0, 'estimated_cost_usd': 0, 'estimated_cost_sessions': 0,
            'complete_window': complete, 'legacy_residual_tokens_in': 0,
            'legacy_residual_tokens_out': 0, 'legacy_residual_api_calls': 0})
        session_ids.setdefault(key, set()).add(sid)
        usage = hermes_tasks._usage(row)
        for field in ('tokens_in', 'tokens_out'):
            total[field] += usage[field]
            if legacy:
                total['legacy_residual_' + field] += usage[field]
        if legacy:
            total['source'] = 'hermes_route_usage_with_legacy_residual'
            total['legacy_residual_api_calls'] += usage['tokens_detail']['api_call_count']
        for field in ('cache_read_tokens', 'cache_write_tokens', 'api_call_count'):
            total[field] += usage['tokens_detail'][field]
        for kind, ids in (('actual', actual_ids), ('estimated', estimated_ids)):
            cost = usage['tokens_detail'][kind + '_cost_usd']
            if kind == 'actual' and cost == 0 and value(row, 'cost_status') != 'actual':
                continue  # The ledger initializes unknown actual cost to zero.
            if hermes_quota.number(cost) is not None:
                total[kind + '_cost_usd'] += float(cost)
                ids.setdefault(key, set()).add(sid)

    try:
        rows = db.execute('SELECT * FROM sessions WHERE started_at>=? ORDER BY started_at DESC LIMIT 1001',
                          (now - 86400,)).fetchall()
        has_ledger = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_model_usage'").fetchone()
        ledger = db.execute('SELECT * FROM session_model_usage WHERE session_id IN '
            '(SELECT id FROM sessions WHERE started_at>=? ORDER BY started_at DESC LIMIT 1000) LIMIT 10001',
            (now - 86400,)).fetchall() if has_ledger else []
        complete = len(rows) <= 1000 and len(ledger) <= 10000
        for record in ledger[:10000]:
            sid = record['session_id']
            previous = attributed.setdefault(sid, dict.fromkeys(token_keys + ('actual_cost_usd', 'estimated_cost_usd'), 0))
            for field in previous:
                previous[field] += value(record, field)
            accumulate(record, sid, legacy=False, complete=complete)
        for index, session in enumerate(rows[:1000]):
            sid = session['id'] if 'id' in session.keys() else 'legacy_' + str(index)
            prior = attributed.get(sid, {})
            residual = {field: max(0, value(session, field) - prior.get(field, 0)) for field in token_keys}
            residual.update(model=value(session, 'model'), billing_provider=value(session, 'billing_provider'),
                            cost_status=value(session, 'cost_status'))
            for field in ('actual_cost_usd', 'estimated_cost_usd'):
                cost = session[field] if field in session.keys() else None
                residual[field] = max(0, cost - prior.get(field, 0)) if cost is not None else None
            # Do not manufacture residual attribution after a truncated ledger.
            if len(ledger) <= 10000 and (any(residual[field] for field in token_keys)
                    or any(residual[field] for field in ('actual_cost_usd', 'estimated_cost_usd'))):
                accumulate(residual, sid, legacy=True, complete=complete)
        for key, total in totals.items():
            total['sessions'] = len(session_ids[key])
            total['actual_cost_sessions'] = len(actual_ids.get(key, set()))
            total['estimated_cost_sessions'] = len(estimated_ids.get(key, set()))
            for kind in ('actual', 'estimated'):
                if not total[kind + '_cost_sessions']:
                    total[kind + '_cost_usd'] = None
        return totals
    except sqlite3.Error:
        return {}
    finally:
        db.close()


def provider_status(data=None, config=None):
    """Public status: unknown allowance is never converted from session tokens."""
    if data is None:
        path = hermes_delivery.state_dir() / 'feedback.json'
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, ValueError):
            data = {}
    config = hermes_task_mode._config() if config is None else config
    now = time.time()
    usage = _recorded_usage(now)
    observed = {}
    path = hermes_delivery.state_dir() / 'zai-availability.json'
    if path.exists():
        try:
            observed = json.loads(path.read_text())
        except (ValueError, OSError):
            pass
    result = []
    for item in hermes_quota.routes(config, data.get('routes') or []):
        key = item['provider'] + '/' + item['model']
        until = data.get('cooldowns', {}).get(key, 0)
        entry = item | {'availability': 'cooling_down' if until > now else 'not_observed',
                        'quota_balance_known': False, 'retry_at': until if until > now else None,
                        'retry_source': (data.get('cooldown_details', {}).get(key) or {}).get('source')}
        if key in usage:
            entry['recorded_usage'] = usage[key]
        if (item['provider'] == 'zai' and item['model'] == 'glm-5.3' and observed.get('windows')
                and observed.get('quota_balance_known', True)):
            entry.update(quota_balance_known=True, quota_source='provider_account_endpoint',
                         quota_observed_at=observed.get('checked_at'), quota_windows=observed['windows'],
                         quota_observation_stale=now - observed.get('checked_at', 0) > 600)
        result.append(entry)
    return result
