"""Which Hermes provider did the work, and which can still do it: the Tasks window's Providers view.

Everything here is read-only and optional. Hermes owns its logs and databases; a missing or
unreadable file (a Windows or test machine has none of them) leaves its part of the view empty.

Sources, all on the Spark where the control plane runs:
- ``<hermes home>/logs/agent.log`` and its rotations ``.1 .2 .3``. Lines carry a session tag
  (``[cron_<job>_<YYYYmmdd_HHMMSS>]`` for scheduled runs) and ``provider=<p> ... model=<m>``.
  "OpenAI client created (chat_completion_stream_request" starts a model call,
  "OpenAI client closed (stream_error_cleanup" on the same provider ends one in failure,
  "API call #N: model=.. provider=.. in=.. out=.." is a call that returned, and
  "API call failed (attempt ..) .. summary=HTTP 402: .." gives the provider's error.
  Timestamps are the Spark's local time, not UTC (``GBOX_HERMES_LOG_TZ`` overrides).
- ``<hermes home>/cron/usage_audit.jsonl``: one record per fire (UTC ``ts``, ``job_id``,
  ``model``, ``total_tokens``, ``duration_ms``, ``error``).
- ``<hermes home>/cron/jobs.json`` (names), ``executions.db`` (status), ``state.db`` (recorded cost).
- ``gbox-data/hermes-dispatch/feedback.json``: routes, ``current_route`` and cooldowns.
- OpenRouter's account endpoints, with ``OPENROUTER_API_KEY`` from ``<hermes home>/.env``.
  The key goes only to openrouter.ai; it is never returned, logged or put in an error.

A run falls through its routes in order, so it is attributed to the provider whose call
succeeded last, not to every provider it tried. Logs are parsed incrementally (file offsets
are remembered per inode), so the Tasks window's 5 s poll only reads what was appended.
"""
from __future__ import annotations

import bisect
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import hermes_delivery

WINDOWS = {'today': 'Today', '7d': '7 days'}
KEEP = 8 * 86400                 # parsed history kept in memory (the 7 day window plus a margin)
BALANCE_TTL, BALANCE_RETRY = 300, 60
DB_TTL = 30
PAIR_S = 10                      # a stream cleanup and its "API call failed" line are one failure
LOCAL_NAMES = {'spark-local', 'llamacpp', 'llama-cpp', 'llama.cpp', 'lmstudio', 'lm-studio', 'local', 'vllm', 'ollama',
               'ollama-local', 'koboldcpp', 'tabbyapi', 'textgen'}
BALANCE_NOTES = {'nous': 'Balance not available (Nous has no balance API); status is read from its latest errors',
                 'ollama-cloud': 'Balance not available (Ollama Cloud has no balance API); status is read from its '
                                 'latest errors'}

_LINE = re.compile(r'^(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d:\d\d)(?:[,.](\d{1,6}))?\s+(?:-\s+)?(?:(\S+)\s+-\s+)?'
                   r'([A-Z]+)(?:\s+\[([^\]\s]+)\])?\s+(?:-\s+)?(.*)$')
_CRON_TAG = re.compile(r'cron_(.+)_(\d{8}_\d{6})\Z')
_KV = re.compile(r'\b(provider|model|base_url)=(\S+)')
_CREATED = re.compile(r'OpenAI client created \(chat_completion(?:_stream)?_request\b')
_CLEANUP = re.compile(r'OpenAI client closed \(stream_error_cleanup\b')
_OK = re.compile(r'API call #\d+: model=(\S+) provider=(\S+) in=(\d+|\?) out=(\d+|\?)')
_ATTEMPT = re.compile(r'API call failed \(attempt[^)]*\).*?summary=(.*)$')
_FINAL = re.compile(r'API call failed after \d+ retries\.\s*(.*?)\s*\|\s*provider=(\S+) model=(\S+)')
_HTTP = re.compile(r'\b(?:HTTP|Error code:?|status(?:_code)?[=:]?)\s*([1-5]\d\d)\b')
_SECRET = re.compile(r'(sk-[A-Za-z0-9_\-]{6,}|Bearer\s+\S+|(?:api[_-]?key|token|authorization)["\']?\s*[:=]\s*\S+)',
                     re.IGNORECASE)


def _home() -> Path:
    return Path(os.environ.get('GBOX_HERMES_HOME') or Path.home() / '.hermes')


def _log_path(home: Path) -> Path:
    return Path(os.environ.get('GBOX_HERMES_AGENT_LOG') or home / 'logs' / 'agent.log')


def _audit_path(home: Path) -> Path:
    return Path(os.environ.get('GBOX_HERMES_USAGE_AUDIT') or home / 'cron' / 'usage_audit.jsonl')


def _env_path(home: Path) -> Path:
    return Path(os.environ.get('GBOX_HERMES_ENV_FILE') or home / '.env')


def _tz():
    """The Spark's log timezone: an IANA name or a fixed ±HH:MM offset; unset means this machine's."""
    name = (os.environ.get('GBOX_HERMES_LOG_TZ') or '').strip()
    if not name:
        return None
    match = re.fullmatch(r'(?:UTC)?([+-])(\d{1,2}):?(\d\d)?', name)
    if match:
        delta = dt.timedelta(hours=int(match[2]), minutes=int(match[3] or 0))
        return dt.timezone(-delta if match[1] == '-' else delta)
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except (ImportError, ValueError, KeyError, OSError):
        return None


def _local(stamp: dt.datetime, tz) -> float:
    return stamp.replace(tzinfo=tz).timestamp() if tz else time.mktime(stamp.timetuple()) + stamp.microsecond / 1e6


def window_start(window: str, now: float, tz=None) -> float:
    if window == '7d':
        return now - 7 * 86400
    today = (dt.datetime.fromtimestamp(now, tz) if tz else dt.datetime.fromtimestamp(now)).date()
    return _local(dt.datetime.combine(today, dt.time()), tz)


def redact(text: str) -> str:
    return _SECRET.sub('[redacted]', str(text or ''))[:400]


def _error_text(message: str) -> str:
    """An error line without its logger name and client context (thread, provider, base_url, model)."""
    text = re.sub(r'^[\w.]+:\s+', '', message)
    text = re.sub(r'\s*\bthread=.*?(?=\s+provider=|$)', '', text)
    text = re.sub(r'\s*\b(?:provider|base_url|model)=\S+', '', text)
    return redact(text.strip())


def error_kind(text: str, code: int | None = None) -> str:
    """What an error says about the provider: no credit, a plan's usage cap, throttling or a failure."""
    t = str(text or '').lower()
    if code is None:
        found = _HTTP.search(text or '')
        code = int(found[1]) if found else None
    if 'usage limit' in t or 'usage_limit' in t or ('monthly' in t and 'limit' in t) or 'quota' in t:
        return 'usage_limit'
    if (code == 402 or 'insufficient' in t or 'credit' in t or 'payment required' in t
            or 'key limit' in t or 'balance' in t):
        return 'out_of_credit'
    if code == 429 or 'rate limit' in t or 'too many requests' in t:
        return 'rate_limited'
    return 'failing'


def inference_provider(provider, model, base_url=None):
    """Name a custom local route only when its model AND observed endpoint match."""
    if provider != 'custom' or not base_url:
        return provider
    s = _local_settings()
    if s is not None:
        from . import hermes_pool
        for candidate in [s, *hermes_pool.node_settings().values()] if s.nodes else [s]:
            if model == candidate.model and base_url.rstrip('/') in {
                    (candidate.proxy_url or '').rstrip('/'), candidate.upstream.rstrip('/')}:
                return candidate.provider
    return provider


def is_local(provider: str, base_url: str | None = None) -> bool:
    extra = {p.strip().lower() for p in (os.environ.get('GBOX_HERMES_LOCAL_PROVIDERS') or '').split(',') if p.strip()}
    if (provider or '').lower() in LOCAL_NAMES | extra:
        return True
    local = _local_settings()
    if local is not None and (provider or '').casefold() == local.provider.casefold():
        return True
    if local is not None and local.nodes:
        from . import hermes_pool
        if any((provider or '').casefold() == s.provider.casefold() for s in hermes_pool.node_settings().values()):
            return True
    host = urllib.parse.urlsplit(base_url or '').hostname or ''
    if host in ('localhost',) or host.endswith('.local') or host.endswith('.lan'):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback
    except ValueError:
        return False


class _Tail:
    """Incremental reader: remembers how far each file (by inode) was read."""

    def __init__(self):
        self.offsets: dict = {}

    @staticmethod
    def _key(path: Path, st):
        return (st.st_dev, st.st_ino) if st.st_ino else (str(path), st.st_ctime)

    def read(self, paths):
        """Yield new complete lines, oldest file first; a rotated file keeps its offset."""
        seen = {}
        for path in paths:
            try:
                st = path.stat()
            except OSError:
                continue
            key = self._key(path, st)
            offset = self.offsets.get(key, 0)
            if st.st_size < offset:      # truncated in place
                offset = 0
            seen[key] = offset
            if st.st_size == offset:
                continue
            try:
                with path.open('rb') as stream:
                    stream.seek(offset)
                    data = stream.read()
            except OSError:
                continue
            end = data.rfind(b'\n') + 1
            seen[key] = offset + end
            for raw in data[:end].splitlines():
                yield raw.decode('utf-8', 'replace')
        self.offsets = seen


class Scanner:
    """Model calls, provider errors and per-session call chains parsed from the agent log."""

    def __init__(self, log: Path, audit: Path):
        self.log, self.audit = log, audit
        self.log_tail, self.audit_tail = _Tail(), _Tail()
        self.events: list[dict] = []          # call / ok / fail / error events, chronological
        self.sessions: dict[str, dict] = {}   # session tag -> {job_id, start, calls, last}
        self.audits: list[dict] = []
        self.base_urls: dict[str, str] = {}
        self.has_ok_lines = False
        self.minutes: dict = {}               # (day, HH:MM) -> epoch, so each line costs no date parsing
        self.lock = threading.Lock()

    # -- agent.log --------------------------------------------------------------------------------
    def _session(self, tag, ts, tz):
        session = self.sessions.get(tag)
        if session is None:
            match = _CRON_TAG.match(tag)
            start = ts
            if match:
                try:
                    start = _local(dt.datetime.strptime(match[2], '%Y%m%d_%H%M%S'), tz)
                except ValueError:
                    pass
            session = self.sessions[tag] = {'id': tag, 'job_id': match[1] if match else None, 'cron': bool(match),
                                            'start': start, 'calls': [], 'last': ts}
        session['last'] = max(session['last'], ts)
        return session

    def _fail(self, event):
        """Count a stream cleanup and the matching "API call failed" warning as one failed call."""
        for prior in reversed(self.events[-200:]):
            if event['ts'] - prior['ts'] > PAIR_S:
                break
            if (prior['kind'] == 'fail' and not prior.get('paired') and prior['provider'] == event['provider']
                    and prior['via'] != event['via']):
                prior['paired'] = event['paired'] = True
                if event.get('text') and not prior.get('text'):
                    prior.update(text=event['text'], code=event.get('code'))
                return False
        return True

    @staticmethod
    def _mark_failed(session, provider):
        for call in reversed(session['calls'][-12:]):
            if call['provider'] == provider and call['state'] == 'open':
                call['state'] = 'failed'
                return True
        return False

    def _stamp(self, day, clock, fraction, tz):
        minute = self.minutes.get((day, clock[:5]))
        if minute is None:
            if len(self.minutes) > 20000:
                self.minutes.clear()
            stamp = dt.datetime(int(day[:4]), int(day[5:7]), int(day[8:10]), int(clock[:2]), int(clock[3:5]))
            minute = self.minutes[(day, clock[:5])] = _local(stamp, tz)
        return minute + int(clock[6:8]) + int((fraction or '0').ljust(6, '0')[:6]) / 1e6

    def _line(self, line, tz):
        # Most lines are tool and gateway chatter; only provider context and HTTP errors matter here.
        if 'provider=' not in line and 'HTTP' not in line and 'Error code' not in line and 'status' not in line:
            return
        match = _LINE.match(line)
        if not match:
            return
        ts = self._stamp(match[1], match[2], match[3], tz)
        level, tag, message = match[5], match[6], match[7]
        kv = dict(_KV.findall(message))
        provider, model = kv.get('provider'), kv.get('model')
        session = self._session(tag, ts, tz) if tag else None
        observed_url = kv.get('base_url')
        if provider == 'custom' and not observed_url and session:
            observed_url = next((c.get('base_url') for c in reversed(session['calls'])
                                 if c.get('model') == model and c.get('base_url')), None)
        provider = inference_provider(provider, model, observed_url)
        if provider and kv.get('base_url'):
            self.base_urls[provider] = kv['base_url']
        if _CREATED.search(message) and provider:
            self.events.append({'ts': ts, 'kind': 'call', 'provider': provider, 'model': model, 'tag': tag})
            if session:
                session['calls'].append({'provider': provider, 'model': model, 'ts': ts, 'state': 'open',
                                         'tokens': 0, 'base_url': observed_url})
            return
        ok = _OK.search(message)
        if ok:
            self.has_ok_lines = True
            model, provider = ok[1], inference_provider(ok[2], ok[1], observed_url)
            tokens = sum(int(x) for x in (ok[3], ok[4]) if x.isdigit())
            self.events.append({'ts': ts, 'kind': 'ok', 'provider': provider, 'model': model, 'tag': tag,
                                'tokens': tokens})
            if session:
                for call in reversed(session['calls'][-12:]):
                    if call['state'] == 'open' and call['provider'] == provider:
                        call.update(state='ok', tokens=tokens, model=model)
                        break
                else:
                    session['calls'].append({'provider': provider, 'model': model, 'ts': ts, 'state': 'ok',
                                             'tokens': tokens})
            return
        cleanup = _CLEANUP.search(message)
        attempt = _ATTEMPT.search(message)
        if (cleanup or attempt) and provider:
            text = redact(attempt[1]) if attempt else ''
            code = _HTTP.search(text)
            event = {'ts': ts, 'kind': 'fail', 'provider': provider, 'model': model, 'tag': tag,
                     'via': 'cleanup' if cleanup else 'attempt', 'text': text, 'code': int(code[1]) if code else None}
            event['counted'] = self._fail(event)
            self.events.append(event)
            if text:
                self.events.append({'ts': ts, 'kind': 'error', 'provider': provider, 'model': model, 'tag': tag,
                                    'text': text, 'code': event['code']})
            if session:
                if not self._mark_failed(session, provider) and attempt:
                    session['calls'].append({'provider': provider, 'model': model, 'ts': ts, 'state': 'failed',
                                             'tokens': 0})
            elif cleanup:
                # Stream threads log without the session tag: tie it to the one session waiting on that provider.
                waiting = [s for s in self.sessions.values() if s['calls'] and s['calls'][-1]['state'] == 'open'
                           and s['calls'][-1]['provider'] == provider and ts - s['calls'][-1]['ts'] < 1800]
                if len(waiting) == 1:
                    waiting[0]['calls'][-1]['state'] = 'failed'
            return
        final = _FINAL.search(message)
        if final:
            text = redact(final[1])
            code = _HTTP.search(text)
            self.events.append({'ts': ts, 'kind': 'error', 'provider': final[2], 'model': final[3], 'tag': tag,
                                'text': text, 'code': int(code[1]) if code else None})
            return
        if level in ('WARNING', 'ERROR', 'CRITICAL'):
            code = _HTTP.search(message)
            if not code or int(code[1]) < 400:
                return
            if not provider:
                # A tagged API error without provider= belongs to the provider the session last called.
                if not session or not session['calls'] or re.search(r'\btool\b|mcp', message, re.IGNORECASE):
                    return
                provider, model = session['calls'][-1]['provider'], session['calls'][-1]['model']
            self.events.append({'ts': ts, 'kind': 'error', 'provider': provider, 'model': model, 'tag': tag,
                                'text': _error_text(message), 'code': int(code[1])})

    # -- usage_audit.jsonl ----------------------------------------------------------------------
    @staticmethod
    def _audit_ts(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value) / (1000 if value > 1e11 else 1)
        if isinstance(value, str):
            try:
                stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                return None
            return (stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)).timestamp()
        return None

    def _audit_line(self, line):
        try:
            record = json.loads(line)
        except ValueError:
            return
        if not isinstance(record, dict):
            return
        ts = self._audit_ts(record.get('ts'))
        if ts is None or not record.get('job_id'):
            return
        number = lambda key: record[key] if isinstance(record.get(key), (int, float)) and not isinstance(record.get(key), bool) else 0
        self.audits.append({'ts': ts, 'job_id': str(record['job_id']), 'model': record.get('model'),
                            'tokens': int(number('total_tokens')), 'duration_s': number('duration_ms') / 1000,
                            'error': redact(record['error']) if record.get('error') else None})

    def refresh(self, now, tz):
        with self.lock:
            rotated = [self.log.with_name(f'{self.log.name}.{i}') for i in (3, 2, 1)]
            for line in self.log_tail.read(rotated + [self.log]):
                try:
                    self._line(line, tz)
                except (ValueError, TypeError, KeyError, IndexError, OverflowError):
                    continue  # one odd line must not stall the reader or make it re-read the file
            for line in self.audit_tail.read([self.audit]):
                self._audit_line(line)
            cutoff = now - KEEP
            if self.events and self.events[0]['ts'] < cutoff:
                self.events = [e for e in self.events if e['ts'] >= cutoff]
            if self.audits and self.audits[0]['ts'] < cutoff:
                self.audits = [a for a in self.audits if a['ts'] >= cutoff]
            for tag in [t for t, s in self.sessions.items() if s['last'] < cutoff]:
                del self.sessions[tag]


_SCANNERS: dict[tuple, Scanner] = {}
_SCANNERS_LOCK = threading.Lock()


def scanner(home: Path | None = None) -> Scanner:
    home = home or _home()
    key = (str(_log_path(home)), str(_audit_path(home)))
    with _SCANNERS_LOCK:
        if key not in _SCANNERS:
            _SCANNERS[key] = Scanner(_log_path(home), _audit_path(home))
        return _SCANNERS[key]


def served_by(session: dict) -> dict | None:
    """The provider whose call succeeded last in a run (its fallbacks before that do not count)."""
    calls = session.get('calls') or []
    for state, how in (('ok', 'log'), ('open', 'log_inferred')):
        for call in reversed(calls):
            if call['state'] == state:
                return {'provider': call['provider'], 'model': call['model'], 'attribution': how}
    return None


def session_providers(now: float | None = None) -> dict[str, dict]:
    """``{session id: {provider, model}}`` for the Tasks run list; empty when there is no log."""
    now = time.time() if now is None else now
    scan = scanner()
    try:
        scan.refresh(now, _tz())
    except (OSError, ValueError):
        return {}
    with scan.lock:
        return {tag: who for tag, s in scan.sessions.items() if (who := served_by(s))}


def _note(e: dict, has_ok_lines: bool, last_ok: dict, last_error: dict) -> None:
    """Fold one log event into the provider's latest success and latest error."""
    provider = e['provider']
    if e['kind'] == 'ok' or (e['kind'] == 'call' and not has_ok_lines):
        # Older logs only mark starts and failures: a started call counts as a sign of life.
        last_ok[provider] = max(last_ok.get(provider, 0), e['ts'])
    elif e['kind'] == 'error' or (e['kind'] == 'fail' and e.get('text')):
        if e['ts'] >= last_error.get(provider, {}).get('ts', 0):
            last_error[provider] = {'ts': e['ts'], 'text': e['text'], 'code': e.get('code'),
                                    'kind': error_kind(e['text'], e.get('code')), 'model': e.get('model')}


def provider_health(home: Path | None = None, now: float | None = None) -> dict[str, dict]:
    """``{provider: {'last_ok': ts | None, 'last_error': {ts, text, code, kind, model} | None}}`` from every model
    call in Hermes's agent log, including calls a run made before it fell through to its next fallback. The route
    supervisor reads this: a run's final error names only the last provider it tried, so an out-of-credit primary
    that Hermes silently skipped would otherwise never be seen (hermes_feedback.apply_exhaustion)."""
    now = time.time() if now is None else now
    scan = scanner(home)
    scan.refresh(now, _tz())
    with scan.lock:
        events, has_ok_lines = list(scan.events), scan.has_ok_lines
    last_ok, last_error = {}, {}
    for e in events:
        _note(e, has_ok_lines, last_ok, last_error)
    return {p: {'last_ok': last_ok.get(p), 'last_error': last_error.get(p)} for p in set(last_ok) | set(last_error)}


# -- control files ---------------------------------------------------------------------------------
def _feedback() -> dict:
    try:
        data = json.loads((hermes_delivery.state_dir() / 'feedback.json').read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _jobs(home: Path) -> dict[str, str]:
    try:
        data = json.loads((home / 'cron' / 'jobs.json').read_text(encoding='utf-8'))
        return {j['id']: j.get('name') or j['id'] for j in data.get('jobs', []) if isinstance(j, dict) and j.get('id')}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


_DB_CACHE: dict = {}


def _cached(key, now, compute):
    hit = _DB_CACHE.get(key)
    if hit and now - hit[0] < DB_TTL:
        return hit[1]
    value = compute()
    _DB_CACHE[key] = (now, value)
    return value


def _open(path: Path):
    if not path.is_file():
        return None
    db = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    return db


def _executions(home: Path, since: float) -> list[dict]:
    from .hermes_tasks import _stamp
    try:
        db = _open(home / 'cron' / 'executions.db')
        if not db:
            return []
        try:
            # ISO stamps sort by date first; two days of margin covers any UTC offset.
            floor = dt.datetime.fromtimestamp(since - 2 * 86400, dt.timezone.utc).strftime('%Y-%m-%d')
            rows = db.execute('SELECT job_id,status,started_at,finished_at FROM executions WHERE started_at >= ? '
                              'ORDER BY started_at DESC LIMIT 20000', (floor,)).fetchall()
        finally:
            db.close()
        out = []
        for row in rows:
            started = _stamp(row['started_at'])
            if started is None:
                continue
            if started < since - 86400:
                continue
            out.append({'job_id': row['job_id'], 'status': row['status'], 'started': started,
                        'finished': _stamp(row['finished_at'])})
        return out
    except (sqlite3.Error, OSError, ValueError):
        return []


def _spend(home: Path, since: float) -> dict[str, float]:
    """Recorded session cost per billing provider since ``since`` (actual when known, else estimated)."""
    try:
        db = _open(home / 'state.db')
        if not db:
            return {}
        try:
            rows = db.execute(
                'SELECT billing_provider AS p, SUM(CASE WHEN actual_cost_usd > 0 THEN actual_cost_usd '
                'ELSE COALESCE(estimated_cost_usd, 0) END) AS usd FROM sessions WHERE started_at >= ? '
                'GROUP BY billing_provider', (since,)).fetchall()
        finally:
            db.close()
        return {row['p']: float(row['usd'] or 0) for row in rows if row['p']}
    except (sqlite3.Error, OSError, ValueError):
        return {}


# -- OpenRouter balance ---------------------------------------------------------------------------
def _env_value(name: str, home: Path) -> str | None:
    try:
        text = _env_path(home).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('export '):
            line = line[7:].lstrip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key.strip() == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            return value or None
    return None


def _http_get(url: str, key: str):
    """GET a JSON document. Returns (status, body or None); errors carry only the status, never the key."""
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _openrouter(home: Path, now: float) -> dict:
    key = _env_value('OPENROUTER_API_KEY', home)
    if not key:
        return {'available': False, 'note': 'No OpenRouter key on the server', 'checked_at': now}
    status, credits = _http_get('https://openrouter.ai/api/v1/credits', key)
    key_status, info = _http_get('https://openrouter.ai/api/v1/key', key)
    if key_status == 404:
        key_status, info = _http_get('https://openrouter.ai/api/v1/auth/key', key)
    del key
    credit = (credits or {}).get('data') if isinstance(credits, dict) else None
    detail = (info or {}).get('data') if isinstance(info, dict) else None
    out = {'available': False, 'checked_at': now, 'source': 'openrouter.ai/api/v1/credits'}
    if isinstance(credit, dict) and _num(credit.get('total_credits')) is not None:
        total, used = _num(credit.get('total_credits')), _num(credit.get('total_usage')) or 0.0
        out.update(available=True, total_credits=total, total_usage=used, credits_remaining=round(total - used, 4))
    if isinstance(detail, dict):
        for field in ('usage', 'usage_daily', 'usage_weekly', 'usage_monthly'):
            if _num(detail.get(field)) is not None:
                out[field] = _num(detail[field])
        if _num(detail.get('limit')) is not None:
            out['key_limit'] = _num(detail['limit'])
            if _num(detail.get('limit_remaining')) is not None:
                out['key_limit_remaining'] = _num(detail['limit_remaining'])
        out['available'] = out['available'] or any(f in out for f in ('usage', 'key_limit'))
    left = [out[f] for f in ('credits_remaining', 'key_limit_remaining') if f in out]
    if left:
        out['remaining_usd'] = round(min(left), 4)
    if not out['available']:
        out['note'] = f'OpenRouter balance unavailable (HTTP {status or key_status or "no answer"})'
        out['http_status'] = status or key_status or None
    return out


_BALANCE = {'at': 0.0, 'data': None, 'busy': False, 'home': None}
_BALANCE_LOCK = threading.Lock()


def openrouter_balance(home: Path | None = None, now: float | None = None, wait: bool = False) -> dict:
    """OpenRouter credit, cached for five minutes; refreshed in the background so a poll never waits."""
    home = home or _home()
    now = time.time() if now is None else now
    with _BALANCE_LOCK:
        data, age = _BALANCE['data'], now - _BALANCE['at']
        if _BALANCE['home'] != str(home):
            data, age = None, float('inf')
        ttl = BALANCE_TTL if data and data.get('available') else BALANCE_RETRY
        if data is not None and age < ttl:
            return data | {'cached': True}
        if _BALANCE['busy'] and not wait:
            return (data or {'available': False, 'note': 'Checking OpenRouter balance…'}) | {'stale': True}
        _BALANCE['busy'] = True

    def refresh():
        try:
            result = _openrouter(home, now)
        except Exception as exc:  # never let a balance check take down the view; no exception text (may echo headers)
            result = {'available': False, 'note': f'OpenRouter balance check failed ({type(exc).__name__})',
                      'checked_at': now}
        with _BALANCE_LOCK:
            _BALANCE.update(at=now, data=result, busy=False, home=str(home))
        return result

    if wait:
        return refresh()
    threading.Thread(target=refresh, name='openrouter-balance', daemon=True).start()
    return (data or {'available': False, 'note': 'Checking OpenRouter balance…'}) | {'stale': True}


# -- assembly ------------------------------------------------------------------------------------
def _clock(ts: float, tz) -> str:
    stamp = dt.datetime.fromtimestamp(ts, tz) if tz else dt.datetime.fromtimestamp(ts)
    return stamp.strftime('%a %H:%M') if abs(time.time() - ts) > 20 * 3600 else stamp.strftime('%H:%M')


def _status(cooldown, last_ok, last_error, balance, now, tz) -> dict:
    if cooldown and cooldown['until'] > now:
        until = _clock(cooldown['until'], tz)
        if cooldown.get('category') == 'quota':
            kind = 'usage_limit' if last_error and last_error['kind'] == 'usage_limit' else 'out_of_credit'
            words = 'Usage limit' if kind == 'usage_limit' else 'Out of credit'
            return {'state': kind, 'label': f'{words} · cooling until {until}', 'until': cooldown['until']}
        return {'state': 'cooling', 'label': f'Cooling until {until}', 'until': cooldown['until']}
    if balance and balance.get('available') and balance.get('remaining_usd') is not None and balance['remaining_usd'] <= 0.01:
        return {'state': 'out_of_credit', 'label': 'Out of credit'}
    if last_error and (not last_ok or last_error['ts'] > last_ok):
        kind = last_error['kind']
        label = {'out_of_credit': 'Out of credit', 'usage_limit': 'Usage limit reached',
                 'rate_limited': 'Rate limited'}.get(kind, 'Failing')
        if kind == 'failing':
            label += ': ' + last_error['text'][:120]
        return {'state': kind, 'label': label}
    if last_ok:
        return {'state': 'working', 'label': 'Working'}
    return {'state': 'idle', 'label': 'No calls seen'}


def summary(window: str = 'today', now: float | None = None, *, wait_balance: bool = False) -> dict:
    if window not in WINDOWS:
        raise ValueError('window must be one of ' + ', '.join(WINDOWS))
    now = time.time() if now is None else now
    home, tz = _home(), _tz()
    since = window_start(window, now, tz)
    scan = scanner(home)
    try:
        scan.refresh(now, tz)
    except (OSError, ValueError):
        pass
    feedback = _feedback()
    names = _jobs(home)
    executions = _cached(('exec', str(home), window), now, lambda: _executions(home, since))
    recorded = _cached(('spend', str(home), window), now, lambda: _spend(home, since))

    with scan.lock:
        events = list(scan.events)
        sessions = [dict(s, calls=list(s['calls'])) for s in scan.sessions.values()]
        audits = list(scan.audits)
        base_urls = dict(scan.base_urls)
        has_ok_lines = scan.has_ok_lines

    # Routes: Hermes's configured order first, then anything else that did work recently.
    routes, seen = [], set()
    for item in feedback.get('routes') or []:
        if isinstance(item, dict) and item.get('provider') and item.get('model'):
            key = f"{item['provider']}/{item['model']}"
            if key not in seen:
                seen.add(key)
                routes.append({'provider': item['provider'], 'model': item['model'], 'key': key, 'in_routes': True})
    current = feedback.get('current_route') if isinstance(feedback.get('current_route'), dict) else None
    for e in events:
        key = f"{e['provider']}/{e.get('model')}"
        if e['kind'] in ('call', 'ok') and e.get('model') and key not in seen and e['ts'] >= since:
            seen.add(key)
            routes.append({'provider': e['provider'], 'model': e['model'], 'key': key, 'in_routes': False})
    if current and current.get('provider') and current.get('model'):
        key = f"{current['provider']}/{current['model']}"
        if key not in seen:
            seen.add(key)
            routes.insert(0, {'provider': current['provider'], 'model': current['model'], 'key': key, 'in_routes': False})
    local_cfg = _local_settings()
    if local_cfg is not None and local_cfg.enabled and feedback:
        key = f'{local_cfg.provider}/{local_cfg.model}'       # the last-resort route is always listed
        if key not in seen:
            seen.add(key)
            routes.append({'provider': local_cfg.provider, 'model': local_cfg.model, 'key': key, 'in_routes': True})

    stats = {r['key']: {'runs_completed': 0, 'runs_failed': 0, 'runs_running': 0, 'calls_started': 0, 'calls_ok': 0,
                        'calls_failed': 0, 'tokens': 0, 'wall_s': 0.0} for r in routes}
    last_ok, last_error = {}, {}

    def bucket(provider, model):
        key = f'{provider}/{model}'
        if key not in stats:
            stats[key] = {'runs_completed': 0, 'runs_failed': 0, 'runs_running': 0, 'calls_started': 0,
                          'calls_ok': 0, 'calls_failed': 0, 'tokens': 0, 'wall_s': 0.0}
        return stats[key]

    for e in events:
        provider = e['provider']
        _note(e, has_ok_lines, last_ok, last_error)
        if e['ts'] < since:
            continue
        b = bucket(provider, e.get('model'))
        if e['kind'] == 'call':
            b['calls_started'] += 1
        elif e['kind'] == 'ok':
            b['calls_ok'] += 1
            b['tokens'] += e.get('tokens') or 0
        elif e['kind'] == 'fail' and e.get('counted'):
            b['calls_failed'] += 1
    if not has_ok_lines:
        # Older logs only mark starts and failures: a started call that did not fail returned.
        for b in stats.values():
            b['calls_ok'] = max(0, b['calls_started'] - b['calls_failed'])

    # Runs: scheduled sessions, joined to their usage audit record and execution status.
    # Only runs that started in the window (an hour of margin for audit records written at the end).
    cron = sorted((s for s in sessions if s['cron'] and s['start'] >= since - 3600), key=lambda s: s['start'])
    by_job: dict[str, list] = {}
    for s in cron:
        by_job.setdefault(s['job_id'], []).append(s)
    starts = {job: [s['start'] for s in items] for job, items in by_job.items()}

    def near(items, keys, t, limit):
        lo, hi = bisect.bisect_left(keys, t - limit), bisect.bisect_right(keys, t + limit)
        return items[lo:hi]

    matched: dict[str, dict] = {}
    loose = []
    for a in (a for a in audits if a['ts'] >= since - 3600):
        best, gap = None, 600.0
        items, keys = by_job.get(a['job_id'], []), starts.get(a['job_id'], [])
        for s in near(items, keys, a['ts'], 600) + near(items, keys, a['ts'] - a['duration_s'], 600):
            distance = min(abs(s['start'] - a['ts']), abs(s['start'] - (a['ts'] - a['duration_s'])))
            if distance < gap:
                best, gap = s, distance
        if best is None:
            loose.append(a)
        elif best['id'] not in matched or gap < matched[best['id']]['gap']:
            if best['id'] in matched:
                loose.append(matched[best['id']]['audit'])
            matched[best['id']] = {'audit': a, 'gap': gap}
        else:
            loose.append(a)
    by_model = {}
    for r in routes:
        by_model.setdefault(r['model'], set()).add(r['provider'])
    by_exec: dict[str, list] = {}
    for x in sorted(executions, key=lambda x: x['started']):
        by_exec.setdefault(x['job_id'], []).append(x)
    exec_starts = {job: [x['started'] for x in items] for job, items in by_exec.items()}
    runs = []
    for s in cron:
        audit = (matched.get(s['id']) or {}).get('audit')
        execution = min((x for x in near(by_exec.get(s['job_id'], []), exec_starts.get(s['job_id'], []), s['start'], 119.9)),
                        key=lambda x: abs(x['started'] - s['start']), default=None)
        who = served_by(s)
        tried = s['calls'][-1] if s['calls'] else None
        if execution and execution['status'] in ('completed', 'failed', 'unknown', 'running', 'claimed'):
            status = {'completed': 'completed', 'running': 'running', 'claimed': 'running'}.get(execution['status'], 'failed')
        elif audit:
            status = 'failed' if audit['error'] else 'completed'
        else:
            status = 'running' if now - s['last'] < 1800 else 'unknown'
        wall = audit['duration_s'] if audit and audit['duration_s'] else (
            (execution['finished'] - execution['started']) if execution and execution.get('finished') else
            max(0.0, s['last'] - s['start']))
        log_tokens = sum(c['tokens'] for c in s['calls'] if c['state'] == 'ok')
        runs.append({'session_id': s['id'], 'job_id': s['job_id'], 'name': names.get(s['job_id'], s['job_id']),
                     'start': s['start'], 'status': status,
                     'provider': (who or {}).get('provider'), 'model': (who or {}).get('model'),
                     'attribution': (who or {}).get('attribution'),
                     'tried': [f"{c['provider']}/{c['model']}" for c in s['calls'] if c['state'] == 'failed'][-6:],
                     'last_tried': f"{tried['provider']}/{tried['model']}" if tried else None,
                     'tokens': (audit or {}).get('tokens') or log_tokens, 'log_tokens': log_tokens,
                     'wall_s': round(wall, 1), 'error': (audit or {}).get('error')})
    for a in loose:
        providers = by_model.get(a['model']) or set()
        provider = next(iter(providers)) if len(providers) == 1 else None
        runs.append({'session_id': None, 'job_id': a['job_id'], 'name': names.get(a['job_id'], a['job_id']),
                     'start': a['ts'] - a['duration_s'], 'status': 'failed' if a['error'] else 'completed',
                     'provider': provider, 'model': a['model'] if provider else None,
                     'attribution': 'audit_model' if provider else None, 'tried': [], 'last_tried': None,
                     'tokens': a['tokens'], 'log_tokens': 0, 'wall_s': round(a['duration_s'], 1), 'error': a['error']})
        # A fire the log no longer covers still says why its provider failed (e.g. a 402 balance error).
        if (provider and a['error'] and (_HTTP.search(a['error']) or error_kind(a['error']) != 'failing')
                and a['ts'] >= last_error.get(provider, {}).get('ts', 0)):
            code = _HTTP.search(a['error'])
            last_error[provider] = {'ts': a['ts'], 'text': a['error'], 'code': int(code[1]) if code else None,
                                    'kind': error_kind(a['error']), 'model': a['model']}
    runs.sort(key=lambda r: r['start'], reverse=True)
    window_runs = [r for r in runs if r['start'] >= since]
    unattributed = 0
    for r in window_runs:
        if not r['provider']:
            unattributed += 1
            if r['last_tried'] and r['status'] == 'failed':
                provider, model = r['last_tried'].split('/', 1)
                bucket(provider, model)['runs_failed'] += 1
            continue
        b = bucket(r['provider'], r['model'])
        b[{'completed': 'runs_completed', 'running': 'runs_running'}.get(r['status'], 'runs_failed')] += 1
        b['wall_s'] += r['wall_s']
        if not r['log_tokens']:
            b['tokens'] += r['tokens']   # audit total for a run whose log had no per-call token counts

    # Provider credit/balance.
    providers = sorted({k.split('/', 1)[0] for k in stats} | {r['provider'] for r in routes})
    balances = {}
    for provider in providers:
        local = is_local(provider, base_urls.get(provider))
        if local:
            balances[provider] = {'available': False, 'note': 'Local model: no credit needed'}
        elif provider == 'openrouter':
            balances[provider] = openrouter_balance(home, now, wait=wait_balance)
        else:
            balances[provider] = {'available': False,
                                  'note': BALANCE_NOTES.get(provider, 'Balance not available: status is read from its latest errors')}

    cooldowns = feedback.get('cooldowns') if isinstance(feedback.get('cooldowns'), dict) else {}
    details = feedback.get('cooldown_details') if isinstance(feedback.get('cooldown_details'), dict) else {}

    def cooldown_for(key):
        until = _num(cooldowns.get(key))
        if until is None or until <= now:
            return None
        detail = details.get(key) if isinstance(details.get(key), dict) else {}
        return {'until': until, 'category': detail.get('category'), 'source': detail.get('source')}

    def spend_for(provider):
        bal = balances.get(provider) or {}
        field = 'usage_daily' if window == 'today' else 'usage_weekly'
        if provider == 'openrouter' and bal.get(field) is not None:
            return bal[field], 'OpenRouter account'
        if provider in recorded:
            return recorded[provider], 'Hermes recorded cost'
        return None, None

    route_rows = []
    for key in list(dict.fromkeys([r['key'] for r in routes] + list(stats))):
        provider, model = key.split('/', 1)
        meta = next((r for r in routes if r['key'] == key), {'in_routes': False})
        b = stats.get(key) or bucket(provider, model)
        if not meta.get('in_routes') and not any(b[f] for f in ('calls_started', 'calls_ok', 'calls_failed',
                                                                'runs_completed', 'runs_failed', 'runs_running')) \
                and not (current and f"{current.get('provider')}/{current.get('model')}" == key):
            continue
        cooldown = cooldown_for(key)
        err = last_error.get(provider)
        route_rows.append({'provider': provider, 'model': model, 'key': key,
                           'current': bool(current and current.get('provider') == provider and current.get('model') == model),
                           'in_routes': bool(meta.get('in_routes')), 'local': is_local(provider, base_urls.get(provider)),
                           'cooldown': cooldown,
                           'status': _status(cooldown, last_ok.get(provider), err, balances.get(provider), now, tz),
                           'last_error': err, 'last_ok': last_ok.get(provider),
                           **{k: (round(v, 1) if isinstance(v, float) else v) for k, v in b.items()}})

    provider_rows = []
    for provider in providers:
        rows = [r for r in route_rows if r['provider'] == provider]
        if not rows:
            continue
        total = {f: sum(r[f] for r in rows) for f in ('runs_completed', 'runs_failed', 'runs_running', 'calls_ok',
                                                     'calls_failed', 'tokens', 'wall_s')}
        cooling = [r['cooldown'] for r in rows if r['cooldown']]
        cooldown = max(cooling, key=lambda c: c['until']) if cooling and len(cooling) == len(rows) else None
        spend, spend_source = spend_for(provider)
        provider_rows.append({'provider': provider, 'local': rows[0]['local'], 'routes': [r['key'] for r in rows],
                              'status': _status(cooldown, last_ok.get(provider), last_error.get(provider),
                                                balances.get(provider), now, tz),
                              'last_error': last_error.get(provider), 'last_ok': last_ok.get(provider),
                              'balance': balances.get(provider), 'spend_usd': spend, 'spend_source': spend_source,
                              'per_run_usd': round(spend / total['runs_completed'], 3)
                              if spend and total['runs_completed'] else None, **total})
    for r in route_rows:
        r['balance'] = balances.get(r['provider'])

    exhausted = []
    for p in provider_rows:
        if p['status']['state'] in ('out_of_credit', 'usage_limit'):
            exhausted.append({'provider': p['provider'], 'state': p['status']['state'], 'label': p['status']['label']})
        else:
            for r in route_rows:
                if r['provider'] == p['provider'] and r['status']['state'] in ('out_of_credit', 'usage_limit'):
                    exhausted.append({'provider': r['key'], 'state': r['status']['state'], 'label': r['status']['label']})
    return {'window': window, 'window_label': WINDOWS[window], 'window_start': since, 'generated_at': now,
            'current_route': current, 'routes': route_rows, 'providers': provider_rows,
            'runs': window_runs[:30], 'runs_total': len(window_runs), 'runs_unattributed': unattributed,
            'exhausted': exhausted, 'recommendation': recommend(provider_rows, exhausted, WINDOWS[window]),
            'local': local_summary(local_cfg, feedback, route_rows, since),
            'sources': {'agent_log': scan.log.is_file(), 'usage_audit': scan.audit.is_file(),
                        'feedback': bool(feedback), 'executions': bool(executions)}}


def _local_settings():
    try:
        from . import hermes_local
        return hermes_local.settings()
    except Exception:  # noqa: BLE001 - the Providers view never fails on the local route's config
        return None


def local_summary(s, feedback: dict, route_rows: list[dict], since: float) -> dict | None:
    """The local route for the Tasks window: model, whether Hermes is on it now and why, and what it served (model
    calls and runs from Hermes's log, tokens and refusals from gBox's proxy log)."""
    if s is None:
        return None
    from . import llm_proxy
    mode = feedback.get('local_mode') if isinstance(feedback.get('local_mode'), dict) else {}
    current = feedback.get('current_route') if isinstance(feedback.get('current_route'), dict) else {}
    row = next((r for r in route_rows if r['provider'].casefold() == s.provider.casefold()), None) or {}
    try:
        records = [r for r in llm_proxy.read_log(since)
                   if (r.get('provider') == s.provider and r.get('model') == s.model)
                   or (not r.get('provider') and s.provider == 'spark-local' and r.get('model') in (None, s.model))]
        proxy = llm_proxy.summarize(records)
    except Exception:  # noqa: BLE001
        proxy = {}
    return {'enabled': s.enabled, 'provider': s.provider, 'model': s.model,
            'host_name': s.host_name, 'upstream': s.upstream, 'api_format': s.api_format,
            'capacity': s.max_parallel_jobs, 'allow_large_tasks': s.allow_large_tasks,
            'active': str(current.get('provider') or '').casefold() == s.provider.casefold(),
            'reason': mode.get('reason'), 'since': mode.get('since'), 'next_paid_at': mode.get('next_paid_at'),
            'runs_completed': row.get('runs_completed', 0), 'runs_failed': row.get('runs_failed', 0),
            'calls_ok': max(row.get('calls_ok', 0), proxy.get('calls_ok', 0)),
            'calls_failed': max(row.get('calls_failed', 0), proxy.get('calls_failed', 0)),
            'tokens': max(row.get('tokens', 0), proxy.get('tokens', 0)),
            'prompt_tokens': proxy.get('prompt_tokens', 0), 'completion_tokens': proxy.get('completion_tokens', 0),
            'refused_while_playing': proxy.get('refused_while_playing', 0),
            'trimmed_calls': proxy.get('trimmed_calls', 0), 'fixed_calls': proxy.get('fixed_calls', 0),
            'last_call_at': proxy.get('last_call_at')}


def recommend(providers: list[dict], exhausted: list[dict], label: str = 'Today') -> str:
    """One line: the paid provider with the most completed work per dollar, and what is exhausted."""
    paid = [p for p in providers if not p['local'] and p['runs_completed']]
    priced = [p for p in paid if p.get('spend_usd')]
    if priced:
        best = max(priced, key=lambda p: (p['runs_completed'] / p['spend_usd'], p['runs_completed']))
        n = best['runs_completed']
        head = (f"{best['provider']} did the most completed work per dollar ({label.lower()}): {n} run{'s' * (n != 1)} "
                f"for ${best['spend_usd']:.2f}, ${best['spend_usd'] / n:.2f} a run.")
    elif paid:
        best = max(paid, key=lambda p: p['runs_completed'])
        n = best['runs_completed']
        head = f"{best['provider']} completed the most runs ({label.lower()}): {n}; its cost is not known."
    else:
        head = f'No paid provider completed a run ({label.lower()}).'
    if exhausted:
        words = {'out_of_credit': 'out of credit', 'usage_limit': 'usage limit'}
        tail = ' Exhausted: ' + ', '.join(f"{e['provider']} ({words.get(e['state'], e['state'])})" for e in exhausted) + '.'
    else:
        tail = ' No route is exhausted.'
    return head + tail
