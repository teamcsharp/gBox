"""The recurring launch stall, identified: a `characters` job with no worker and empty inputs.

The stuck job's own record:

```
tool: characters | state: queued
worker: None
input: {"op": "cast_swap", "character": "", "session_id": "", "game_id": "", "game": "", ...}
```

**No worker is assigned**, so nothing will ever dequeue it, and **every field is empty** - it is not a job anyone asked for. It sits at the head of the queue, and
the launch waits for the queue, so the bar freezes at about 25% and the game never starts. Cancelling it clears the queue and the launch proceeds
immediately - which is what happened twice now.

So the fix is a guard: **cancel agent-irrelevant orphan jobs that have no worker.** A job with `require_worker: None` cannot be picked up by anyone; keeping it
only blocks what is behind it. The guard checks every few seconds and cancels queued jobs in that state, naming them in its log so the recurrence is visible.

Run beside the app or the play loop: `python orphan_guard.py`.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

LOG = r"D:\gBox\pso-ds\orphan_guard.log"
POLL = 5.0
GRACE = 8.0                     # let a freshly created job pick up its worker


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    try:
        open(LOG, "a", encoding="utf-8").write(text + "\n")
    except Exception:                                             # noqa: BLE001
        pass


def active():
    try:
        rows = S._call("/api/jobs?state=queued,running")
    except Exception:                                             # noqa: BLE001
        return []
    return rows if isinstance(rows, list) else (rows.get("items") or [])


if __name__ == "__main__":
    log("orphan guard starting")
    first_seen = {}
    while True:
        try:
            for job in active():
                job_id = job.get("id")
                worker = job.get("require_worker")
                tool = job.get("tool")
                if worker:
                    first_seen.pop(job_id, None)
                    continue
                if job.get("state") != "queued":
                    continue
                seen = first_seen.setdefault(job_id, time.time())
                if time.time() - seen < GRACE:
                    continue
                cancelled = False
                for path, method in ((f"/api/jobs/{job_id}/cancel", "POST"), (f"/api/jobs/{job_id}", "DELETE")):
                    try:
                        S._call(path, method)
                        cancelled = True
                        break
                    except Exception:                             # noqa: BLE001
                        continue
                log(f"orphan {tool} {str(job_id)[:10]} has no worker - {'cancelled' if cancelled else 'could not cancel'}")
                first_seen.pop(job_id, None)
        except Exception as exc:                                  # noqa: BLE001
            log(f"guard error: {str(exc)[:80]}")
        time.sleep(POLL)
