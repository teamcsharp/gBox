"""The Spark's GPU model as Hermes's last-resort route, and what work a small local model is given.

Policy (docs/hermes-local-fallback.md):

* The local route (provider ``spark-local`` by default, an OpenAI-compatible endpoint served by gBox's proxy in front of
  Ollama, gbox/llm_proxy.py) is eligible only when every paid route is cooling down or out of credit, or when the
  operator sets "local only". It is never put in a paid route's fallback chain, so a paid run never silently finishes
  on the small model, and a local run never burns paid credit.
* As soon as a paid route recovers (its cooldown ends, or OpenRouter reports credit again) the supervisor rotates back.
* The CPU-only llama.cpp server stays excluded (hermes_quota.EXCLUDED_PROVIDERS); nothing here starts it.
* On the local route the queue dispatches only small, well-scoped tasks (dispatch_size) with a tighter prompt and tool
  budget (local_prompt); big multi-file tasks stay queued for the paid routes.

Everything reads gbox.toml's [hermes.local] (gbox.config.HermesLocalConfig) and two small state files under the
Hermes dispatch state dir: ``local-mode.json`` (the operator's local-only switch) and ``feedback.json`` (the current
route, written by the supervisor).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time

from . import hermes_delivery

_CACHE: dict = {'key': None, 'value': None}
FLAG = 'local-mode.json'
CONTINUE_PROMPT = 'Continue.'


# ---------------------------------------------------------------------------------------------- settings

def _config_path() -> Path:
    return Path(os.environ.get('GBOX_CONFIG') or Path(__file__).resolve().parents[1] / 'gbox.toml')


def settings():
    """[hermes.local] from gbox.toml (cached until the file changes). Hermes's cron scripts run outside the service,
    so this reads the file itself; a missing or broken file gives the defaults."""
    from .config import HermesLocalConfig, load
    path = _config_path()
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(path), None, None)
    if _CACHE['key'] != key:
        try:
            cfg = load(path)
            value = cfg.hermes.local
            if not value.proxy_url:
                value = value.model_copy(update={'proxy_url': f'http://127.0.0.1:{cfg.api_port}/api/llm/local/v1'})
        except Exception:                      # noqa: BLE001 - a broken toml must not stop route supervision
            value = HermesLocalConfig(proxy_url='http://127.0.0.1:8765/api/llm/local/v1')
        _CACHE.update(key=key, value=value)
    return _CACHE['value']


def context_limit(s=None, model: str | None = None) -> int:
    s = s or settings()
    return int(s.contexts.get(model or s.model) or s.context_tokens)


def route(s=None) -> dict:
    s = s or settings()
    return {'provider': s.provider, 'model': s.model}


def is_local(item, s=None) -> bool:
    s = s or settings()
    providers = {s.provider.casefold(), *(str(n.get('provider', '')).casefold() for n in s.nodes.values())}
    return isinstance(item, dict) and str(item.get('provider') or '').casefold() in providers


# ---------------------------------------------------------------------------------------------- operator switch

def _flag_path() -> Path:
    return hermes_delivery.state_dir() / FLAG


def local_only(s=None) -> bool:
    s = s or settings()
    if s.local_only:
        return True
    try:
        return bool(json.loads(_flag_path().read_text()).get('local_only'))
    except (OSError, ValueError, AttributeError):
        return False


def set_local_only(on: bool, *, now: float | None = None) -> dict:
    path = _flag_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'local_only': bool(on), 'changed_at': time.time() if now is None else now}))
    tmp.replace(path)
    return status()


# ---------------------------------------------------------------------------------------------- route choice

def choose(routes, cooldowns, now, *, primary, rotation_pending=False, busy=False, s=None, only_local=None, preferred=None, config=None) -> dict:
    """Pick the cron route. Paid routes first (rotating among those not cooling, as before); the local route only
    when none is left or the operator set local only. Returns {mode, route, fallbacks, reason, next_paid_at}.

    cooldowns are the live ones (hermes_feedback.scan drops expired entries): a listed route is cooling.
    mode: 'paid' | 'local' | 'none' (nothing eligible and the local route is switched off)."""
    s = s or settings()
    only_local = local_only(s) if only_local is None else only_local
    cooldowns = cooldowns or {}
    from . import hermes_provider_scope as scope
    policy = scope.read()
    config = config or {}
    paid = [r for r in routes if not is_local(r, s) and not scope.reason(r, config, policy=policy)]
    eligible = [r for r in paid if r['provider'] + '/' + r['model'] not in cooldowns]
    pending = [v for k, v in cooldowns.items() if v > now and k.split('/', 1)[0].casefold() != s.provider.casefold()]
    next_paid = min(pending) if pending and not eligible else None
    local = route(s)
    local_reason = scope.reason(local, config, policy=policy)
    local_enabled = s.enabled and not local_reason
    if local_enabled and only_local:
        return {'mode': 'local', 'route': local, 'fallbacks': [], 'reason': 'The operator set Hermes to local only',
                'next_paid_at': None}
    if only_local and local_reason:
        return {'mode': 'none', 'route': None, 'fallbacks': [],
                'reason': local_reason or 'Local route is disabled', 'next_paid_at': None}
    if eligible:
        preferred_available = preferred in eligible
        chosen = preferred if preferred_available else primary if primary in eligible else None
        if chosen is None or (rotation_pending and not busy and not preferred_available):
            index = eligible.index(primary) if primary in eligible else -1
            chosen = eligible[(index + 1) % len(eligible)]
        reason = ('Operator-preferred paid route available' if preferred_available else
                  'A paid route recovered; rotated back from the local model' if is_local(primary, s)
                  else 'Paid route available')
        return {'mode': 'paid', 'route': chosen, 'fallbacks': [r for r in eligible if r != chosen], 'reason': reason,
                'next_paid_at': None}
    if local_enabled:
        return {'mode': 'local', 'route': local, 'fallbacks': [],
                'reason': 'Every paid route is cooling down or out of credit', 'next_paid_at': next_paid}
    return {'mode': 'none', 'route': None, 'fallbacks': [], 'reason': local_reason or 'All connected routes are cooling down',
            'next_paid_at': next_paid}


LIFTABLE = ('scheduler_backoff', 'provider_exhausted_backoff')    # hermes_quota.EXHAUSTED_SOURCE


def credit_recovered(cooldowns: dict, details: dict, balance: dict | None, now: float) -> list[str]:
    """Cooled OpenRouter routes whose account shows credit again, observed after the route was cooled: their
    cooldown can end now instead of at the scheduler's backoff. Only a scheduler backoff is lifted (the run backoff or
    the long out-of-credit backoff; a measured reset time from the provider stays), and only on a fresh, positive
    balance."""
    if not balance or not balance.get('available') or balance.get('stale'):
        return []
    remaining = balance.get('remaining_usd')
    if remaining is None or remaining < 1.0:
        return []
    checked = balance.get('checked_at') or balance.get('observed_at') or now
    out = []
    for key, until in (cooldowns or {}).items():
        if until <= now or not key.startswith('openrouter/'):
            continue
        detail = (details or {}).get(key) or {}
        if detail.get('category') != 'quota' or detail.get('source') not in LIFTABLE:
            continue
        if checked > (detail.get('last_failure_at') or detail.get('observed_at') or 0):
            out.append(key)
    return out


# ---------------------------------------------------------------------------------------------- Hermes provider

def provider_entry(s=None, template: dict | None = None) -> dict:
    """The custom_providers entry Hermes needs for the local route (OpenAI-compatible, pointed at gBox's proxy).
    The proxy answers loopback clients without the gBox token, so no secret is written into Hermes's config."""
    s = s or settings()
    # The cron default can name a pool provider. Keep its node endpoint and
    # active model, rather than overwriting it with the legacy shared proxy.
    if s.nodes:
        from . import hermes_pool
        s = next((node for node in hermes_pool.node_settings(s).values()
                  if node.provider.casefold() == s.provider.casefold()), s)
    # Shape from the template (Hermes on the Spark: name, base_url, model, models, models_discovered, api_key), but
    # never its key or what Hermes discovered from the template's own server.
    entry = {k: v for k, v in (template or {}).items()
             if k not in ('api_key', 'key_env', 'api_key_env', 'models', 'models_discovered')}
    entry.update(name=s.provider, base_url=s.proxy_url, model=s.model)
    if template and 'models' in template:
        entry['models'] = [s.model]
    entry['api_key'] = 'gbox-local'
    return entry


def merged_providers(existing, s=None):
    """custom_providers with the local entry present and current; None when nothing has to change. Other entries are
    kept as they are (an EhmBird entry is used as the shape template for ours)."""
    s = s or settings()
    rows = [x for x in (existing or []) if isinstance(x, dict)]
    mine = next((x for x in rows if str(x.get('name', '')).casefold() == s.provider.casefold()), None)
    template = mine or next((x for x in rows if str(x.get('name', '')).casefold() == 'ehmbird'), None)
    want = provider_entry(s, template)
    if mine is not None and all(mine.get(k) == want[k] for k in ('name', 'base_url', 'model')) and mine.get('api_key'):
        return None
    out = [x for x in rows if x is not mine]
    out.append(want)
    return out


def register_provider(config_path: Path, s=None) -> bool:
    """Put the local entry into Hermes's custom_providers by editing config.yaml in this process (an atomic replace
    that keeps the file's mode), never through `hermes config set`: that would put every other provider's api_key on
    a command line. Re-reads the file first, so only custom_providers changes. True when the file was written."""
    import yaml
    s = s or settings()
    text = config_path.read_text(encoding='utf-8')
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise RuntimeError('Hermes config.yaml is not a mapping; the local provider was not registered')
    merged = merged_providers(data.get('custom_providers'), s)
    if merged is None:
        return False
    data['custom_providers'] = merged
    out = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    if (yaml.safe_load(out) or {}).get('custom_providers') != merged:
        raise RuntimeError('Hermes config.yaml round trip failed; the local provider was not registered')
    mode = config_path.stat().st_mode & 0o777
    # The original goes to config-backups/ first (with its mode: it holds provider keys), only when it is rewritten.
    backups = config_path.parent / 'config-backups'
    backups.mkdir(mode=0o700, exist_ok=True)
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    backup = backups / f'{config_path.name}.before-spark-local-{stamp}'
    n = 1
    while backup.exists():
        n += 1
        backup = backups / f'{config_path.name}.before-spark-local-{stamp}-{n}'
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode or 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(config_path.read_bytes())          # byte-for-byte copy of the original
    os.chmod(backup, mode or 0o600)
    tmp = config_path.with_name(config_path.name + '.gbox-tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode or 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(out)
        os.chmod(tmp, mode or 0o600)
        os.replace(tmp, config_path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return True


# ---------------------------------------------------------------------------------------------- dispatch size

LARGE_WORDS = ('replacement', 'replace ', 'writer', 'reader', 'reverse engineer', 'ghidra', 'decomp', 'pipeline',
               'rig', 'animation', 'retarget', 'skeleton', 'emulator', 'emulation', 'freeze', 'black screen',
               'multiplayer', 'netplay', 'renderdoc', 'port ', 'architecture', 'refactor', 'rewrite', 'cast swap',
               'model swap', 'whole cast', 'every game', 'all games', 'shader')
SMALL_WORDS = ('typo', 'label', 'rename', 'tooltip', 'wording', 'text ', 'docs', 'documentation', 'readme',
               'inventory', 'list ', 'test', 'flaky', 'log ', 'logging', 'icon', 'button', 'color', 'colour',
               'single file', 'one file', 'one-line', 'small fix', 'config', 'setting', 'default', 'count',
               'sort', 'filter', 'message', 'error message')
SMALL_STAGES = ('inventory',)
LONG_TICKET = 2500   # body characters; the queue's lite listing keeps an open body this long whole (inbox.LITE_OPEN_BODY)


def dispatch_size(item: dict, request: dict | None = None) -> dict:
    """{'size': 'small'|'large', 'reason'} for a queue item: what a ~20B local model can finish alone.

    Small: favorite inventories, and inbox tickets whose text names a narrow fix (one file, labels, docs, tests,
    inventories) without naming engine/reader/writer work. Large: native character replacement, session observers,
    analysis/reader/writer/runtime stages, long or multi-system tickets, and tickets that already needed several
    attempts. An operator can force either with request.context.hermes_size. `request` may be a lite listing row
    (GET /api/requests?lite=1): a body cut to its start carries body_chars, its whole length."""
    request = request or {}
    forced = str((request.get('context') or {}).get('hermes_size') or '').lower()
    if forced in ('small', 'large'):
        return {'size': forced, 'reason': 'set on the request (context.hermes_size)'}
    if item.get('lane') == 'favorite':
        from .hermes_work_queue import next_stage
        stage = next_stage(item)
        if stage in SMALL_STAGES:
            return {'size': 'small', 'reason': f'favorite {stage} stage'}
        return {'size': 'large', 'reason': f'favorite {stage} stage needs a paid model'}
    if item.get('repair') or item.get('session_observer') or item.get('operator_requested'):
        return {'size': 'large', 'reason': 'native character or session work'}
    if item.get('launch_failure'):
        return {'size': 'large', 'reason': 'launch failure investigation (gbox/launch_failures.py)'}
    if item.get('attempts', 0) >= 3:
        return {'size': 'large', 'reason': f"{item['attempts']} earlier attempts"}
    text = ' '.join(str(x or '') for x in (item.get('title'), request.get('title'), request.get('body'))).lower() + ' '
    if max(len(str(request.get('body') or '')), request.get('body_chars') or 0) > LONG_TICKET:
        return {'size': 'large', 'reason': 'long ticket'}
    files = set(re.findall(r'[\w/.-]+\.(?:py|js|html|md|toml|json)\b', text))
    if len(files) > 2:
        return {'size': 'large', 'reason': f'names {len(files)} files'}
    if hit := next((w.strip() for w in LARGE_WORDS if w in text), None):
        return {'size': 'large', 'reason': f'names {hit} work'}
    if hit := next((w.strip() for w in SMALL_WORDS if w in text), None):
        return {'size': 'small', 'reason': f'narrow fix ({hit})'}
    if len(files) == 1:
        return {'size': 'small', 'reason': 'single file'}
    return {'size': 'large', 'reason': 'scope not clearly narrow'}


def lane_budget(s=None, lane: str | None = None) -> int:
    """A run's tool budget. An inbox-lane run (an operator's ticket, a launch failure, a session observer) gets
    [hermes.local] tool_budget_inbox when that is set and larger (#2399: a 45-call run read for 23 turns and published
    nothing); favorites keep tool_budget. The proxy enforces the same number (llm_proxy reads the lane from the queue
    header), so the prompt never promises calls the proxy will refuse."""
    s = s or settings()
    base = max(6, int(s.tool_budget))
    inbox = int(getattr(s, 'tool_budget_inbox', 0) or 0)
    return max(base, inbox) if lane == 'inbox' and inbox > 0 else base


def local_prompt(prompt: str, s=None, lane: str | None = None) -> str:
    """Tighten a queue prompt for the local model: smaller tool budget, one file, bounded reads, and an explicit way
    out (record findings and stop) so a task that turns out large waits for a paid route instead of failing."""
    s = s or settings()
    budget = lane_budget(s, lane)
    reserve = max(3, min(6, budget // 3))
    prompt = re.sub(r'Use a \d+-tool-call work budget with the final \d+ calls',
                    f'Use a {budget}-tool-call work budget with the final {reserve} calls', prompt)
    if s.allow_large_tasks:
        return (f'LOCAL MODEL RUN ({s.provider} on {s.host_name}; {s.model}). '
                f'Use at most {budget} tool calls, reserving the last {reserve} for focused verification, '
                'publish_task_changes and a durable checkpoint. '
                'Work the assigned request through one concrete, reviewable milestone. After reading its latest '
                'replies and feedback, reuse prepare_task_workspace and inspect the existing patch, published '
                'commit and pending job IDs. Resume the first missing acceptance step; do not duplicate an active '
                'job or reimplement completed work. Before new exploration, identify the bounded deliverable and '
                'the exact check that will demonstrate it works. Use bounded searches and existing artifacts. '
                'Once the focused checks pass, publish changed source with explicit file paths and test-path '
                'strings before optional investigation. Keep the returned commit and PR receipt. For a research '
                'deliverable, preserve the actual evidence artifact and its verification. '
                'Use the reserved calls to save a checkpoint with what changed, actual check results, publication '
                'or artifact receipt, exact pending job IDs and the next acceptance step. If blocked, preserve '
                'the useful partial result and name the concrete dependency. '
                'A small request should finish in this run when its full acceptance checks pass. Call '
                'set_request_status done only after the full request is verified, with concise solver credit and '
                'actual verification evidence; keep partial work in_progress. A PR alone is not runtime acceptance. '
                'Protect operator gameplay and preserve original games and saves. ' + prompt)
    handoff = 'another enabled local host' if settings().nodes else 'a paid model'
    return (f'LOCAL MODEL RUN ({s.provider} · {s.model} on {s.host_name}; local task processing). '
            f'Keep this run small: at most {budget} tool calls, the last {reserve} for focused tests, '
            'publish_task_changes and the final reply. Change at most one source file plus its focused test. '
            'Read at most 80 lines per read and search before reading. Prefer inventories, single-file fixes and '
            'running existing tests. If the fix needs more than one source file, engine/reader/writer work or live '
            'emulation, do not start it: post your findings (files, functions, the failing check) on the request and '
            f'finish; it stays queued for {handoff}. A local run publishes a draft PR only, with its test summary. '
            + prompt)


# ---------------------------------------------------------------------------------------------- status

def _feedback() -> dict:
    path = hermes_delivery.state_dir() / 'feedback.json'
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def active(feedback: dict | None = None, s=None) -> bool:
    """Is Hermes on the local route right now (the supervisor's current route)?"""
    feedback = _feedback() if feedback is None else feedback
    return is_local(feedback.get('current_route') or {}, s)


def run_was_local(request_id: str, s=None) -> bool:
    """Did the queue dispatch this request's latest run on the local route (or is the local route current)?"""
    try:
        from .hermes_work_queue import _read
        items = _read().get('items', {})
    except (OSError, ValueError):
        items = {}
    for item in items.values():
        if item.get('request_id') == request_id and item.get('local'):
            return True
    return active(s=s)


def status(s=None) -> dict:
    s = s or settings()
    feedback = _feedback()
    mode = feedback.get('local_mode') or {}
    return {'enabled': s.enabled, 'provider': s.provider, 'model': s.model, 'proxy_url': s.proxy_url,
            'host_name': s.host_name, 'api_format': s.api_format, 'max_parallel_jobs': s.max_parallel_jobs,
            'allow_large_tasks': s.allow_large_tasks,
            'upstream': s.upstream, 'context_tokens': context_limit(s), 'local_only': local_only(s),
            'active': active(feedback, s), 'reason': mode.get('reason'), 'since': mode.get('since'),
            'next_paid_at': mode.get('next_paid_at'), 'current_route': feedback.get('current_route')}


def pr_note(checks: list[str], s=None) -> tuple[str, str]:
    """(headline, test summary) for a draft PR a local run published."""
    s = s or settings()
    text = '\n'.join(checks or [])
    found = re.findall(r'(\d+) (passed|failed|error|errors|skipped)', text)
    counts: dict[str, int] = {}
    for n, word in found:
        word = 'errors' if word == 'error' else word
        counts[word] = counts.get(word, 0) + int(n)
    summary = ', '.join(f'{v} {k}' for k, v in counts.items()) or ('no Python tests ran' if not text.strip() else 'see validation')
    if s.allow_large_tasks:
        return (f'Produced by Hermes using the local model {s.model} on {s.host_name} ({s.provider}). '
                'Review the recorded tests and acceptance evidence.', 'Test summary: ' + summary)
    head = (f'Produced by Hermes on the Spark\'s local model ({s.provider} · {s.model}) while the paid routes were '
            'out of credit. Review it as a draft from a small model.')
    return head, 'Test summary: ' + summary
