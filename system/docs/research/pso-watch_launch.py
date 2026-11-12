"""Watch the launch transition: staging -> emulator -> session, and report each change.

The app shows the launch mid-pipeline ("Staged to cache (reused)" with no emulator yet), so this polls sessions and jobs together and prints a line only
when something changes - the launch job's progress message, or a session appearing in a live state. That turns "it is taking a long time" into a record of
which stage it is in and how long each takes.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

LIVE = {"running", "starting", "launching", "pending"}


def snapshot():
    try:
        rows = S._call('/api/sessions')
        rows = rows if isinstance(rows, list) else (rows.get('items') or [])
    except Exception:                                            # noqa: BLE001
        rows = []
    try:
        jobs = S._call('/api/jobs')
        jobs = jobs if isinstance(jobs, list) else (jobs.get('items') or [])
    except Exception:                                            # noqa: BLE001
        jobs = []
    live = [row for row in rows if row.get('state') in LIVE]
    active = [job for job in jobs if job.get('state') in ('running', 'queued')]
    return live, active


if __name__ == "__main__":
    last = None
    for step in range(18):
        live, active = snapshot()
        parts = []
        for row in live[:2]:
            parts.append(f"LIVE {row.get('session_id')} state={row.get('state')} owned={row.get('agent_owned')}")
        for job in active[:2]:
            progress = job.get('progress') or {}
            parts.append(f"job {job.get('tool')} {progress.get('pct')}% {str(progress.get('msg'))[:60]}")
        line = " | ".join(parts) or "nothing running"
        if line != last:
            print(f"t+{step * 10:3d}s  {line}", flush=True)
            last = line
        if live:
            print("session appeared", flush=True)
            break
        time.sleep(10)
