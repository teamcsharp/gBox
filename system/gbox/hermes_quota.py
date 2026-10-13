"""Observed provider limits and conservative retry policy, without balance guesses."""
from __future__ import annotations

import datetime as dt
from email.utils import parsedate_to_datetime
import json
import math
import re


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def route(item):
    """Persist only public provider/model identifiers, never route credentials."""
    if not isinstance(item, dict):
        return None
    values = [item.get(k) for k in ('provider', 'model')]
    if not all(isinstance(v, str) and v.strip() and len(v) <= 200 for v in values):
        return None
    return dict(zip(('provider', 'model'), (v.strip() for v in values)))


# Providers Hermes must never run cron work on. The CPU-only llama.cpp model pins the Spark (load ~40) and slows every
# build; EhmBird answered every call with HTTP 500. Routes are a union of the Hermes config and the saved list, so
# removing one from the config alone never sticks: it has to be filtered here. GBOX_HERMES_EXCLUDED_PROVIDERS
# (comma list, "" for none) overrides the default.
EXCLUDED_PROVIDERS = ('llamacpp', 'EhmBird')


def excluded_providers():
    import os
    raw = os.environ.get('GBOX_HERMES_EXCLUDED_PROVIDERS')
    names = EXCLUDED_PROVIDERS if raw is None else [x for x in raw.split(',')]
    return {n.strip().casefold() for n in names if n.strip()}


def routes(config, saved=()):
    cron = config.get('cron') or {}
    candidates = [{'provider': cron.get('model_provider'), 'model': cron.get('model')},
                  *(config.get('fallback_providers') or []), *saved]
    skip = excluded_providers()
    result = []
    for item in candidates:
        clean = route(item)
        if clean and clean not in result and clean['provider'].casefold() not in skip:
            result.append(clean)
    return result


def retry_after(value, now):
    delay = number(value)
    if delay is not None:
        return now + max(0, delay)
    if isinstance(value, str):
        try:
            return parsedate_to_datetime(value).timestamp()
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def reset_at(value):
    stamp = number(value)
    if stamp is not None:
        return stamp / 1000 if stamp > 100_000_000_000 else stamp
    if isinstance(value, str):
        try:
            when = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            return when.timestamp() if when.tzinfo else None
        except (ValueError, OverflowError):
            pass
    return None


def failure_wait(error, category, now, *, attempt=1):
    """Use structured reset/Retry-After only; 'five hour limit' is not a reset."""
    payload = error if isinstance(error, dict) else None
    if isinstance(error, str):
        try:
            payload = json.loads(error)
        except ValueError:
            # Hermes can deliver a bounded context after a leading exception name.
            offset = error.find('{')
            if offset >= 0:
                try:
                    payload, _ = json.JSONDecoder().raw_decode(error[offset:])
                except ValueError:
                    pass
    times = []
    if isinstance(payload, dict):
        containers = [payload]
        containers += [payload[k] for k in ('error', 'context', 'headers') if isinstance(payload.get(k), dict)]
        for part in containers:
            for key in ('reset_at', 'resets_at', 'nextResetTime', 'x-ratelimit-reset'):
                value = part.get(key)
                stamp = number(value) / 1000 if key == 'nextResetTime' and number(value) is not None else reset_at(value)
                if stamp is not None and now <= stamp <= now + 31 * 86400:
                    times.append(stamp + 10)
            for key in ('retry_after', 'Retry-After', 'retry-after'):
                stamp = retry_after(part.get(key), now)
                if stamp is not None and now <= stamp <= now + 31 * 86400:
                    times.append(stamp + 1)
    if times:
        return {'until': max(times), 'source': 'provider_retry_metadata', 'quota_balance_known': False}
    # Bounded scheduler backoff is policy, not the subscription reset time.
    base = 300 if category == 'quota' else 60
    delay = min(base * 2 ** min(max(int(attempt) - 1, 0), 4), 3600)
    return {'until': now + delay, 'source': 'scheduler_backoff', 'quota_balance_known': False}


def provider_failure(error):
    text = str(error or '').lower()
    if any(word in text for word in ('insufficient_quota', 'usage limit', 'usage_limit',
                                    'quota exceeded', 'quota exhausted', 'quota limit',
                                    'insufficient credits', 'insufficient available credits', 'credit balance',
                                    'add credits', 'limit_remaining', 'payment required',
                                    # Nous answers an empty account with HTTP 404, not 402.
                                    'requires available credits', 'balance is too low', 'insufficient balance',
                                    'exceeds your available credits')) or re.search(
            '(^|[^0-9a-z])402([^0-9]|$)', text) or re.search(
            r'["\'](?:error_code|code)["\']\s*:\s*["\']?(?:1113|1308|1310|131[6-9]|132[01])\b', text):
        return 'quota'
    if re.search(r'\b429\b', text) or any(word in text for word in ('rate limit', 'rate_limit', 'too many requests')):
        return 'rate_limit'
    return None


# An exhausted account (no credit, or a plan's usage cap) does not come back in minutes the way a throttle does, so a
# route seen exhausted waits hours, doubling while it stays exhausted. The first call after the wait is the probe: if
# it fails the same way the wait doubles, if it works the route is back. OpenRouter's balance endpoint ends an
# out-of-credit wait early (hermes_local.credit_recovered).
EXHAUSTED_KINDS = ('out_of_credit', 'usage_limit')
EXHAUSTED_SOURCE = 'provider_exhausted_backoff'


def exhaustion_wait(kind, text, error_at, *, failures=1):
    """{'until', 'source', 'quota_balance_known'} for a route whose latest call failed out of credit or at its usage
    limit. Out of credit: 3 h, then 6 h, then every 12 h. A monthly or weekly usage limit: 6 h, 12 h, then every 24 h.
    Another usage limit (hourly or daily windows): 1 h doubling to 6 h."""
    t = str(text or '').lower()
    if kind == 'out_of_credit':
        base, cap = 3 * 3600, 12 * 3600
    elif 'month' in t or 'week' in t:
        base, cap = 6 * 3600, 24 * 3600
    else:
        base, cap = 3600, 6 * 3600
    delay = min(base * 2 ** min(max(int(failures) - 1, 0), 6), cap)
    return {'until': error_at + delay, 'source': EXHAUSTED_SOURCE, 'quota_balance_known': False}
