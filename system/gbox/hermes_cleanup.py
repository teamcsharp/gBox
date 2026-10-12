"""Stop servers that ended Hermes task runs left running (#1300, #1304).

A task run often starts a throwaway HTTP server from its request worktree to
check a client change, and nothing stopped it when the run ended (the #1301
audit found `python3 -m http.server 8124` still serving #1175's worktree a day
later). This sweep finds listening processes whose working directory or
command-line paths sit inside the task worktree root, keeps anything started
while a Hermes run is still running, and stops the rest. Each stop is reported
on the ticket that owns the worktree.

Only Linux `/proc` is read; elsewhere the sweep finds nothing.
"""
from __future__ import annotations

import json
import os
import re
import signal
import time
from pathlib import Path

from . import hermes_delivery, hermes_tasks

INTERVAL = 600      # seconds between sweeps
MIN_AGE = 600       # never touch a server younger than this
GRACE = 5.0         # seconds between SIGTERM and SIGKILL
MARKER = 'Stopped leftover server'
_REQUEST = re.compile(r'^[0-9a-f]{16}$')


def task_root() -> Path:
    return Path(os.environ.get('GBOX_HERMES_TASKS') or hermes_delivery.repository().parent / 'gbox-hermes-tasks')


def _boot_time(proc: Path) -> float:
    for line in (proc / 'stat').read_text().splitlines():
        if line.startswith('btime '):
            return float(line.split()[1])
    raise ValueError('no btime')


def _started(proc: Path, pid: int, btime: float) -> float:
    stat = (proc / str(pid) / 'stat').read_text()
    fields = stat.rsplit(')', 1)[1].split()   # the command name may contain spaces
    return btime + int(fields[19]) / (os.sysconf('SC_CLK_TCK') if hasattr(os, 'sysconf') else 100)


def _listening_inodes(proc: Path) -> dict[str, int]:
    inodes = {}
    for name in ('tcp', 'tcp6'):
        try:
            lines = (proc / 'net' / name).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) > 9 and parts[3] == '0A':   # TCP_LISTEN
                inodes[parts[9]] = int(parts[1].rsplit(':', 1)[1], 16)
    return inodes


def listeners(proc='/proc') -> list[dict]:
    """Every process of this user that holds a listening TCP socket."""
    proc = Path(proc)
    try:
        inodes = _listening_inodes(proc)
        btime = _boot_time(proc)
    except (OSError, ValueError):
        return []
    out = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            ports = set()
            for fd in (entry / 'fd').iterdir():
                link = os.readlink(fd)
                if link.startswith('socket:['):
                    port = inodes.get(link[8:-1])
                    if port is not None:
                        ports.add(port)
            if not ports:
                continue
            out.append({'pid': pid, 'ports': sorted(ports), 'cwd': os.readlink(entry / 'cwd'),
                        'cmdline': [a for a in (entry / 'cmdline').read_bytes().decode(errors='replace').split('\0') if a],
                        'started': _started(proc, pid, btime)})
        except (OSError, ValueError, IndexError):
            continue   # another user's process, or it exited meanwhile
    return out


def _inside(path: str, root: str) -> str | None:
    """The request id when `path` lies inside the task root, '' for the root's other files."""
    if not path.startswith('/'):
        return None
    norm = os.path.normpath(path)
    if norm != root and not norm.startswith(root + '/'):
        return None
    first = norm[len(root):].lstrip('/').split('/', 1)[0]
    return first if _REQUEST.match(first) else ''


def owner(process: dict, root) -> str | None:
    """Which task worktree a process belongs to: its request id, '' if unknown, None if none."""
    root = os.path.normpath(str(root))
    found = None
    for arg in [process.get('cwd') or ''] + list(process.get('cmdline') or []):
        for piece in arg.split('='):
            rid = _inside(piece, root)
            if rid:
                return rid
            if rid == '':
                found = ''
    return found


def leftovers(processes, root, *, running_since, now, min_age=MIN_AGE) -> list[dict]:
    """The servers to stop. Pure: callers supply the processes and run state.

    A server started at or after the oldest still-running Hermes run may belong
    to that run, so it is kept; so is anything younger than `min_age`.
    """
    picked = []
    for p in processes:
        rid = owner(p, root)
        if rid is None or p.get('pid') == os.getpid():
            continue
        started = p.get('started') or now
        if now - started < min_age:
            continue
        if running_since is not None and started >= running_since - 60:
            continue
        picked.append(p | {'request_id': rid or None})
    return picked


def running_since(home=None) -> float | None:
    """When the oldest still-running Hermes cron run began, or None when none is running."""
    db = hermes_tasks._db(Path(home or hermes_tasks._home()) / 'cron' / 'executions.db')
    if not db:
        return None
    with db:
        rows = db.execute("SELECT started_at FROM executions WHERE status IN ('claimed','running')").fetchall()
    db.close()
    stamps = [s for s in (hermes_tasks._stamp(r['started_at']) for r in rows) if s]
    return min(stamps) if stamps else None


def stop(process, *, grace=GRACE, proc='/proc', kill=os.kill, sleep=time.sleep) -> str:
    """SIGTERM, then SIGKILL after `grace`. Refuses if the pid now names another process."""
    pid = process['pid']

    def same():
        try:
            return abs(_started(Path(proc), pid, _boot_time(Path(proc))) - process['started']) < 2
        except (OSError, ValueError, IndexError):
            return False

    if not same():
        return 'gone'
    try:
        kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return 'gone'
    waited = 0.0
    while waited < grace:
        sleep(0.25)
        waited += 0.25
        if not same():
            return 'terminated'
    try:
        kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return 'terminated'
    return 'killed'


def _describe(p, how, now):
    cmd = ' '.join(p.get('cmdline') or [])[:200]
    age_h = (now - p['started']) / 3600
    ports = ', '.join(str(x) for x in p['ports'])
    return (f"{MARKER} from this ticket's task worktree: pid {p['pid']}, port {ports}, "
            f"running {age_h:.1f} h ({how}). Command: `{cmd}`. No Hermes run that was still "
            f"running could have started it, so it was left over from an ended run.")


def sweep(api=None, *, home=None, root=None, now=None, force=False, dry_run=False,
          proc='/proc', kill=os.kill, sleep=time.sleep) -> dict:
    """Stop leftover task servers and report each on its ticket; at most every INTERVAL s."""
    now = time.time() if now is None else now
    path = hermes_delivery.state_dir() / 'cleanup.json'
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        saved = {}
    if not force and not dry_run and now - saved.get('checked_at', 0) < INTERVAL:
        return {'status': 'skipped', 'next_in': int(INTERVAL - (now - saved.get('checked_at', 0)))}
    root = Path(root or task_root())
    since = running_since(home)
    found = leftovers(listeners(proc), root, running_since=since, now=now)
    if dry_run:
        return {'status': 'dry_run', 'running_since': since, 'leftovers': found}
    stopped, errors = [], []
    for p in found:
        how = stop(p, proc=proc, kill=kill, sleep=sleep)
        item = {'pid': p['pid'], 'ports': p['ports'], 'request_id': p['request_id'], 'result': how}
        stopped.append(item)
        if how == 'gone' or not p['request_id'] or api is None:
            continue
        try:
            api(f"/api/requests/{p['request_id']}/messages", {'author': 'agent', 'text': _describe(p, how, now),
                'task_step': {'action': 'stop leftover task server', 'attempt': '1',
                              'result': f"pid {p['pid']} port {','.join(map(str, p['ports']))} {how}",
                              'status': 'finished'}})
        except Exception as error:   # the stop already happened; a failed report must not undo the sweep
            errors.append(f"{p['request_id']}: {type(error).__name__}")
    saved['checked_at'] = now
    saved['stopped'] = (saved.get('stopped', []) + [s | {'at': now} for s in stopped])[-200:]
    with hermes_delivery.locked('cleanup'):
        path.write_text(json.dumps(saved, indent=2))
    return {'status': 'swept', 'stopped': stopped, 'errors': errors}
