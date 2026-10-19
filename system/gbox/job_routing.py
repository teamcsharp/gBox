"""Reject impossible routing and repair one unclaimed analysis job explicitly."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sqlite3
import time

from .store import append_audit


def conflict(required_os, worker):
    actual = (worker or {}).get('os')
    if required_os and actual in ('linux', 'windows') and required_os != actual:
        return (f"Worker {worker.get('name') or worker.get('id')} runs {actual}, but require_os is {required_os}. "
                "Choose compatible explicit constraints; this job was not queued.")
    return None


def repair_analysis_os(db, job_id, *, expected_worker, expected_os, target_os=None,
                       apply=False, now=None, actor='operator-maintenance'):
    """Correct only the OS of one queued analyze_binary job, with atomic evidence.

    The caller owns the connection (and its thread lock, when shared). An explicit
    target_os is required for apply. No worker selection, submission or lease
    mutation occurs; ordinary worker admission must still accept the job.
    """
    now = time.time() if now is None else now
    if expected_os not in ('windows', 'linux') or target_os not in (None, 'windows', 'linux'):
        raise ValueError('OS constraints must be windows or linux')
    if not isinstance(job_id, str) or not job_id or not isinstance(expected_worker, str) or not expected_worker:
        raise ValueError('Exact job and worker IDs are required')
    if apply and target_os is None:
        raise ValueError('Applying requires an explicit target_os')
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError('Invalid observation time')
    if db.in_transaction:
        raise ValueError('Correction requires its own transaction')
    db.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
    try:
        row = db.execute("SELECT body FROM docs WHERE kind='job' AND id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError('Job does not exist')
        original = row[0]
        before = json.loads(original)
        if (before.get('id') != job_id or before.get('tool') != 'analyze_binary'
                or before.get('state') != 'queued' or before.get('worker_id') is not None
                or before.get('started') is not None or before.get('finished') is not None
                or before.get('receipt_id') is not None or before.get('output') is not None
                or before.get('cancel') or (before.get('origin') or {}).get('inspection_run')):
            raise ValueError('Only an unclaimed queued analyze_binary job can be corrected')
        if before.get('require_worker') != expected_worker or before.get('require_os') != expected_os:
            raise ValueError('Expected routing no longer matches; reread the job')
        row = db.execute("SELECT body FROM docs WHERE kind='worker' AND id=?", (expected_worker,)).fetchone()
        worker = json.loads(row[0]) if row else {}
        seen = worker.get('last_seen')
        if (worker.get('id') != expected_worker or worker.get('os') not in ('linux', 'windows')
                or type(seen) not in (int, float) or not math.isfinite(seen)
                or not -5 <= now - seen <= 30 or 'analyze_binary' not in (worker.get('tools') or [])):
            raise ValueError('Pinned worker needs a fresh identity and analyze_binary capability')
        if not conflict(expected_os, worker):
            raise ValueError('Routing is already compatible; no correction is needed')
        if target_os is not None and target_os != worker['os']:
            raise ValueError('Explicit target_os does not match the pinned worker')
        after = before | {'require_os': worker['os']}
        evidence = {'before': before, 'after': after,
                    'worker': {k: worker.get(k) for k in ('id', 'name', 'os', 'last_seen')},
                    'reason': 'Align analysis OS with the explicitly pinned worker; preserve all other job fields',
                    'observed_at': now}
        result = {'applied': False, 'job_id': job_id, 'audit_seq': None, **evidence}
        if apply:
            changed = db.execute("UPDATE docs SET body=? WHERE kind='job' AND id=? AND body=?",
                                 (json.dumps(after), job_id, original)).rowcount
            if changed != 1:
                raise ValueError('Job changed during correction; reread it')
            result['audit_seq'] = append_audit(db, actor, 'job.analysis_os_corrected', job_id, evidence, ts=now)
            db.commit()
            result['applied'] = True
        else:
            db.rollback()
        return result
    except BaseException:
        db.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True, help='Existing gbox.sqlite3; never creates or migrates it')
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--expected-worker', required=True, help='Exact current require_worker ID')
    parser.add_argument('--expected-os', choices=('windows', 'linux'), required=True)
    parser.add_argument('--target-os', choices=('windows', 'linux'), help='Must match the same worker; required with --apply')
    parser.add_argument('--apply', action='store_true', help='Apply only this correction and record atomic before/after audit evidence')
    args = parser.parse_args(argv)
    mode = 'rw' if args.apply else 'ro'
    db = sqlite3.connect(args.database.resolve().as_uri() + '?mode=' + mode, uri=True, timeout=5)
    try:
        if not args.apply:
            db.execute('PRAGMA query_only=ON')
        result = repair_analysis_os(db, args.job_id, expected_worker=args.expected_worker,
                                    expected_os=args.expected_os, target_os=args.target_os, apply=args.apply)
    finally:
        db.close()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()


def requester_worker(workers, remote: str | None, require_os: str | None = None, tool: str = "launch_game"):
    """The online worker at the address a request came from, when it can run `tool` and matches `require_os`.

    #2386: the operator pressed Play on the NUC and the game booted on the other PC because the launch named only
    an OS. A launch that does not name a PC boots on the PC it was asked from, never on another one."""
    if not remote:
        return None
    for w in workers or ():
        if (w.get("address") == remote and w.get("online") and tool in (w.get("tools") or ())
                and (not require_os or w.get("os") == require_os)):
            return w
    return None
