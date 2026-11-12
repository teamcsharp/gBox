"""Try to clear the stuck session_op jobs so the worker can process input again.

The queue held 41 jobs and some were marked `running` indefinitely - a stuck job can occupy the worker's slot and block everything behind it. This posts a
cancel for each queued or running `session_op` and reports what the API says, without touching any other kind of job.

If cancelling is not supported the answer will say so and the worker needs a restart instead; either way the result is recorded rather than assumed.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

jobs = S._call("/api/jobs")
jobs = jobs if isinstance(jobs, list) else (jobs.get("items") or [])
active = [job for job in jobs if job.get("state") in ("queued", "running") and job.get("tool") == "session_op"]
print("active session_op jobs:", len(active))

cancelled, refused = 0, 0
for job in active[:50]:
    job_id = job.get("id")
    for path, method in ((f"/api/jobs/{job_id}/cancel", "POST"),
                         (f"/api/jobs/{job_id}", "DELETE")):
        try:
            S._call(path, method)
            cancelled += 1
            break
        except Exception as exc:                                  # noqa: BLE001
            message = str(exc)
            if "404" in message or "405" in message:
                continue
            refused += 1
            print("  cancel failed:", job_id, message[:80])
            break

print(f"cancelled: {cancelled} | refused: {refused}")
time.sleep(3)
jobs = S._call("/api/jobs")
jobs = jobs if isinstance(jobs, list) else (jobs.get("items") or [])
still = [job for job in jobs if job.get("state") in ("queued", "running")]
print("active jobs remaining:", len(still))
for job in still[:5]:
    print("  ", job.get("tool"), job.get("state"))
