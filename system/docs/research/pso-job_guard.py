"""A job-queue guard: cancel the backlog before it becomes a hung worker.

Round 23's failure was a runaway queue, and round 24 showed the consequence: once jobs are `running` and stuck, cancelling the queued ones does not free the
worker, and input dies until a restart. So the useful moment to act is **before** the queue forms.

The guard watches `/api/jobs` and, when more than `LIMIT` input jobs are outstanding for longer than `PATIENCE` seconds, cancels the ones that are still
`queued` (never the `running` one, which cannot be cancelled anyway) and prints what it did. It is meant to run beside the play loop: the loop keeps its
input rate in step, and this catches the case where something else - a stuck frame job, a slow worker - builds a backlog the loop cannot see.

Run it standalone:  python job_guard.py
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

LIMIT = 8
PATIENCE = 45.0
POLL = 5.0


def active_input_jobs():
    try:
        jobs = S._call("/api/jobs")
    except Exception:                                             # noqa: BLE001
        return [], []
    jobs = jobs if isinstance(jobs, list) else (jobs.get("items") or [])
    active = [job for job in jobs if job.get("state") in ("queued", "running")
              and job.get("tool") in ("session_op", "get_frame", "read_memory")]
    queued = [job for job in active if job.get("state") == "queued"]
    return active, queued


def cancel(job_id):
    for path, method in ((f"/api/jobs/{job_id}/cancel", "POST"), (f"/api/jobs/{job_id}", "DELETE")):
        try:
            S._call(path, method)
            return True
        except Exception:                                         # noqa: BLE001
            continue
    return False


if __name__ == "__main__":
    print(f"guard: limit {LIMIT} jobs, patience {PATIENCE:.0f}s, polling every {POLL:.0f}s")
    over_since = None
    while True:
        active, queued = active_input_jobs()
        print(f"{time.strftime('%H:%M:%S')} active={len(active)} queued={len(queued)}", flush=True)
        if len(active) > LIMIT:
            over_since = over_since or time.time()
            if time.time() - over_since > PATIENCE and queued:
                removed = sum(1 for job in queued if cancel(job.get("id")))
                print(f"  backlog for {time.time() - over_since:.0f}s - cancelled {removed} queued job(s)", flush=True)
                over_since = None
        else:
            over_since = None
        time.sleep(POLL)
