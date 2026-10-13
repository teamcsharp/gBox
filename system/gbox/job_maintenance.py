"""Retire abandoned, read-only frame requests without stopping a game."""
from __future__ import annotations

import json
import time


def retire_stalled_snapshots(store, *, now: float | None = None, timeout: int = 120) -> list[str]:
    now = time.time() if now is None else now
    retired = []
    with store.lock:
        rows = store.db.execute("SELECT id,body FROM docs WHERE kind='job' "
                                "AND json_extract(body,'$.state')='running' "
                                "AND json_extract(body,'$.tool')='get_frame'").fetchall()
        for jid, original in rows:
            job = json.loads(original)
            started = job.get('started') or job.get('created') or now
            if now - started <= timeout:
                continue
            reason = f'Frame capture timed out after {timeout}s; no screenshot was produced. The game was not stopped.'
            job.update(state='failed', finished=now, error=reason, cancel=True)
            # A separate worker may have just posted its result. Never overwrite
            # that result from an earlier snapshot of the document.
            changed = store.db.execute("UPDATE docs SET body=? WHERE kind='job' AND id=? AND body=?",
                                       (json.dumps(job), jid, original)).rowcount
            store.db.commit()
            if changed:
                retired.append(jid)
                store.audit('scheduler', 'job.failed', jid, {'reason': reason, 'read_only_capture': True})
    return retired


# Jobs that run as a thread inside the gBox server process itself (no worker
# claims them). A server restart ends the thread but leaves the job document
# "running" forever, and a cancel request has nothing left to stop it (#1297).
SERVER_TOOLS = ('session_swap', 'session_reset', 'session_reload', 'scene_relay', 'evidence_capture')
ORPHAN_REASON = ('Interrupted: the gBox server restarted while this was running, so nothing is still working on it. '
                 'Your games were not changed by this cleanup; start it again if you still want it.')
CANCELLED_REASON = ('cancelled by the operator (the gBox server had already restarted, so nothing was still '
                    'running for it)')


def is_orphaned_server_job(job: dict, live: set | frozenset) -> bool:
    return (job.get('state') == 'running' and job.get('tool') in SERVER_TOOLS
            and not job.get('worker_id') and job.get('id') not in live)


def retire_orphaned_server_jobs(store, live, *, now: float | None = None) -> list[str]:
    """Fail in-server jobs whose thread is not alive in this process (a previous server process ran them)."""
    now = time.time() if now is None else now
    retired = []
    with store.lock:
        live = frozenset(live)
        rows = store.db.execute("SELECT id,body FROM docs WHERE kind='job' "
                                "AND json_extract(body,'$.state')='running'").fetchall()
        for jid, original in rows:
            job = json.loads(original)
            job.setdefault('id', jid)
            if not is_orphaned_server_job(job, live):
                continue
            reason = CANCELLED_REASON if job.get('cancel') else ORPHAN_REASON
            job.update(state='failed', finished=now, error=reason)
            job['progress'] = {'pct': (job.get('progress') or {}).get('pct', 0), 'msg': reason, 'ts': now}
            changed = store.db.execute("UPDATE docs SET body=? WHERE kind='job' AND id=? AND body=?",
                                       (json.dumps(job), jid, original)).rowcount
            store.db.commit()
            if changed:
                retired.append(jid)
                store.audit('scheduler', 'job.failed', jid, {'reason': reason, 'orphaned_server_job': True})
    return retired
