"""List the jobs the plane knows about, newest first, with their progress line."""
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

jobs = S._call('/api/jobs')
jobs = jobs if isinstance(jobs, list) else (jobs.get('items') or [])
print("total jobs:", len(jobs))
for job in jobs[:8]:
    progress = job.get('progress') or {}
    print("  ", str(job.get('id'))[:12], "|", job.get('tool'), "|", job.get('state'),
          "|", progress.get('pct'), str(progress.get('msg'))[:70])
    if job.get('error'):
        print("       error:", str(job.get('error'))[:160])
