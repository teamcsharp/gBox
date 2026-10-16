"""Hermes pre-tool attribution for exact managed favorite unlock executions.

The callback uses core-supplied task identity, never a model-supplied request ID.
Installing this module does not activate it in an already running gateway.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from urllib.parse import quote

NAME = 'gbox-unlock-guard'
FORMAT = 'gbox-hermes-unlock-guard-v1'
SYSTEM = Path(__file__).resolve().parents[1]
LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
TASK = re.compile(r'^cron:([A-Za-z0-9_-]{1,64}):([A-Za-z0-9_-]{1,128})$')
REQUEST = re.compile(r'^gBox queue inbox ([0-9a-f]{16})$')
READS = {'get_request', 'get_job', 'list_games', 'list_workers', 'list_sessions',
         'get_build_feedback', 'get_dispatch_feedback', 'get_game_work_queue',
         'read_request_artifact', 'kb_search', 'list_recipes', 'reply_request',
         'record_request_metrics', 'set_request_status'}
SCOPE_KEYS = ('custom_build_unlocks', 'idle_only', 'no_rom_copy', 'no_automatic_launch')


def dispatch_scope(request, dispatched_at):
    """Freeze one occurrence before create/resume; sync never rewrites this lease."""
    context = request.get('context') or {}
    return {'request_id': request['id'], 'dispatched_at': dispatched_at,
            'context': {key: context.get(key) for key in SCOPE_KEYS},
            'release': json.loads(json.dumps(context.get('unlock_dispatch')))}


def _json(path, limit=8 * 1024**2):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Guard inventory exceeds its bounded size')
    return json.loads(raw)


def _db(path):
    conn = sqlite3.connect('file:' + quote(Path(path).absolute().as_posix(), safe='/:') + '?mode=ro',
                           uri=True, timeout=1)
    conn.execute('PRAGMA query_only=ON')
    return conn


def _home():
    return Path(os.environ.get('GBOX_HERMES_HOME') or Path.home() / '.hermes')


def _control_db():
    from .config import load
    return load(SYSTEM / 'gbox.toml').data_dir / 'gbox.sqlite3'


def _queue():
    from .hermes_delivery import state_dir
    return state_dir() / 'work-queue.json'


def owner(task_id, home):
    """None means an ordinary run; an uncertain managed run raises and blocks."""
    if not isinstance(task_id, str) or not task_id.startswith('cron:'):
        return None
    match = TASK.fullmatch(task_id)
    if not match:
        raise ValueError('Malformed core cron task identity')
    job_id, execution_id = match.groups()
    jobs = _json(home / 'cron/jobs.json').get('jobs')
    if not isinstance(jobs, list) or len(jobs) > 1000:
        raise ValueError('Canonical cron jobs are unavailable')
    rows = [job for job in jobs if isinstance(job, dict) and job.get('id') == job_id]
    if len(rows) != 1:
        raise ValueError('Exact canonical cron job is unavailable')
    assigned = REQUEST.fullmatch(str(rows[0].get('name', '')))
    if not assigned:
        return None
    rid = assigned[1]
    item = (_json(_queue()).get('items') or {}).get('inbox:' + rid) or {}
    scope = item.get('unlock_scope')
    with _db(_control_db()) as db:
        row = db.execute("SELECT body FROM docs WHERE kind='request' AND id=?", (rid,)).fetchone()
    request = json.loads(row[0]) if row else {}
    context = request.get('context') or {}
    restricted = bool(context.get('custom_build_unlocks') and
                      (context.get('no_rom_copy') or context.get('no_automatic_launch')))
    if not scope and not restricted and item.get('unlock_work') is not True:
        return None
    if not isinstance(scope, dict):
        raise ValueError('Managed unlock execution has no frozen dispatch scope')
    with _db(home / 'cron/executions.db') as db:
        claim = db.execute('SELECT job_id,status,started_at,claimed_at FROM executions WHERE id=?', (execution_id,)).fetchone()
    if not claim or claim[0] != job_id or claim[1] not in ('running', 'claimed'):
        raise ValueError('This exact managed execution has no active canonical claim')
    started = datetime.fromisoformat(claim[2] or claim[3])
    stamp = scope.get('dispatched_at')
    if (started.tzinfo is None or type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= 0
            or started.timestamp() < stamp):
        raise ValueError('An older execution cannot inherit a later dispatch scope')
    if (item.get('request_id') != rid or item.get('job_id') != job_id
            or item.get('dispatch_state') not in ('queued', 'uncertain') or item.get('unlock_work') is not True):
        raise ValueError('Managed queue ownership differs from this execution')
    if (scope.get('request_id') != rid or scope.get('context') != {key: context.get(key) for key in SCOPE_KEYS}
            or not isinstance(scope.get('release'), dict) or scope['release'] != context.get('unlock_dispatch')):
        raise ValueError('The request flags or release differ from this occurrence scope')
    if request.get('status') not in ('open', 'in_progress'):
        raise ValueError('The managed favorite request is no longer active')
    return (rid, context) if restricted else None


def pre_tool_call(*, tool_name, args, task_id='', session_id='', home=None, **_):
    """Hermes's modify/block contract runs before its registry/MCP dispatch."""
    try:
        bound = owner(task_id, Path(home) if home else _home())
        if bound is None:
            return None
        rid, context = bound
        if not isinstance(args, dict):
            raise ValueError('Typed tool arguments are required')
        if not tool_name.startswith('mcp_gbox_'):
            raise ValueError('Favorite research permits scoped gBox analysis only; shell, browser execution and delegation are disabled')
        tool = tool_name.removeprefix('mcp_gbox_')
        if tool == 'favorite_unlocks':
            if args.get('request_id') != rid or args.get('game_id') != context['custom_build_unlocks']:
                raise ValueError('Favorite publication must preserve the exact request and game')
            return None  # The typed convenience permits only evidence/profile metadata APIs.
        if tool in {'start_job', 'submit_job'}:
            name, values = args.get('tool'), args.get('input') or {}
        elif tool.startswith('job_'):
            name = tool.removeprefix('job_')
            values = args.get('input', {}) if name.startswith('rea_') else args
        elif tool in READS:
            if 'request_id' in args and args['request_id'] != rid:
                raise ValueError('This managed call belongs to another request')
            return None
        else:
            raise ValueError('This convenience can escape scoped analysis; use an attributed read-only job')
        from .unlock_job_policy import reason
        if why := reason(context, name, values):
            raise ValueError(why)
        # Override omitted or model-supplied ownership. The server then repeats
        # tool policy and current idle admission using this persisted parent.
        return {'action': 'modify', 'args': {'parent_request_id': rid}}
    except Exception as error:
        return {'action': 'block', 'message': 'Favorite research guard: ' + str(error)[:300]}


def _payload():
    paths = [Path(__file__), Path(__file__).with_name('unlock_job_policy.py'),
             SYSTEM / 'hermes' / NAME / '__init__.py', SYSTEM / 'hermes' / NAME / 'plugin.yaml']
    return {path.relative_to(SYSTEM).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _gateway(home):
    import psutil
    row = _json(home / 'gateway.pid', 4096)
    if (type(row.get('pid')) is not int or row['pid'] <= 0 or row.get('kind') != 'hermes-gateway'
            or Path(row.get('hermes_home') or '').resolve() != home.resolve()):
        raise ValueError('Canonical Hermes gateway identity is unavailable')
    process = psutil.Process(row['pid'])
    born = process.create_time()
    if not math.isfinite(born) or born <= 0 or not process.is_running() or 'gateway' not in process.cmdline():
        raise ValueError('Canonical gateway process is not running')
    return row['pid'], born


def readiness_reason(home=None):
    """A current gateway must actually have registered this exact payload."""
    home = Path(home) if home else _home()
    try:
        if not _installed(home):
            raise ValueError('the repo-owned plugin is not installed')
        receipt = _json(home / NAME / 'loaded.json', 16384)
        pid, born = _gateway(home)
        if (receipt.get('format') != FORMAT or receipt.get('active') is not True or receipt.get('payload') != _payload()
                or receipt.get('pid') != pid or receipt.get('process_created') != born):
            raise ValueError('the current gateway has not loaded the current guard')
        return ''
    except Exception:
        return 'Favorite idle research waits for the current Hermes attribution guard to be installed and loaded'


def _installed(home):
    installed = home / 'plugins' / NAME
    return installed.is_symlink() and installed.resolve() == (SYSTEM / 'hermes' / NAME).resolve()


def _mark_loaded(home, payload, registration, *, active=True):
    """Record this loaded callback, including when plugin load precedes gateway.pid."""
    pid, born = _gateway(home)
    if os.getpid() != pid:
        return
    folder = home / NAME
    target = folder / 'loaded.json'
    old = _json(target, 16384) if target.exists() else {}
    if not active and old.get('registration') != registration:
        return  # Unloading an old registration cannot revoke its replacement.
    if (old.get('registration') == registration and old.get('active') is active
            and old.get('pid') == pid and old.get('process_created') == born):
        return
    folder.mkdir(exist_ok=True)
    temporary = folder / f'loaded.{pid}.{registration}.tmp'
    temporary.write_text(json.dumps({'format': FORMAT, 'active': active, 'registration': registration,
                                     'pid': pid, 'process_created': born, 'payload': payload,
                                     'registered_at': time.time()}), encoding='utf-8')
    temporary.replace(target)


def register(ctx, *, bootstrap=None):
    """Directory-plugin entry point, with a receipt only from the real gateway."""
    from hermes_cli import plugins
    details = inspect.getsource(plugins._get_pre_tool_call_directive_details)
    dispatch = inspect.getsource(plugins._dispatch_pre_tool_call_hooks)
    if 'action == "modify"' not in details or 'details.modified_args' not in dispatch:
        raise RuntimeError('Hermes does not support the required pre-tool modify/block contract')
    from hermes_constants import get_hermes_home
    home = Path(get_hermes_home())
    from . import unlock_job_policy
    payload, registration = _payload(), uuid.uuid4().hex
    payload['gbox/hermes_unlock_guard.py'] = LOADED_SOURCE_SHA256
    payload['gbox/unlock_job_policy.py'] = getattr(unlock_job_policy, 'LOADED_SOURCE_SHA256', None)
    if not isinstance(bootstrap, dict) or set(bootstrap) != {'__init__.py', 'plugin.yaml'}:
        raise RuntimeError('The loaded plugin bootstrap identity is required')
    for name, digest in bootstrap.items():
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise RuntimeError('The loaded plugin bootstrap identity is invalid')
        payload[f'hermes/{NAME}/{name}'] = digest

    def record(active=True):
        try:
            _mark_loaded(home, payload, registration, active=active)
        except Exception:
            pass  # Missing evidence keeps admission closed; it never opts in.

    lock, active = threading.RLock(), [True]

    def callback(**kw):
        with lock:
            if not active[0]:
                return {'action': 'block', 'message': 'Favorite research guard registration was unloaded'}
            record()
        return pre_tool_call(home=home, **kw)

    def unload():
        with lock:
            active[0] = False
            record(False)

    ctx.register_hook('pre_tool_call', callback)
    ctx.on_unload(unload)
    record()


def install(home=None, *, apply=False):
    """Dry-run by default; add only the fixed plugin symlink, never replace data."""
    home = (Path(home) if home else _home()).absolute()
    source, target = SYSTEM / 'hermes' / NAME, home / 'plugins' / NAME
    if not (source / 'plugin.yaml').is_file() or not (source / '__init__.py').is_file():
        raise ValueError('The complete repo-owned plugin payload is unavailable')
    if target.is_symlink() and target.resolve() == source.resolve():
        action = 'already_installed'
    elif target.exists() or target.is_symlink():
        raise ValueError('An existing plugin at the fixed target must be reviewed; it will not be replaced')
    else:
        action = 'create_symlink'
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source.resolve(), target_is_directory=True)
    return {'action': action, 'applied': apply, 'source': str(source), 'target': str(target),
            'readiness': readiness_reason(home), 'next': 'Load the plugin through the normal guarded Hermes gateway refresh; no automatic restart is performed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply and not args.install:
        parser.error('--apply requires --install')
    print(json.dumps(install(args.home, apply=args.apply) if args.install else
                     {'ready': not bool(why := readiness_reason(args.home)), 'reason': why}, indent=2))


if __name__ == '__main__':
    main()
