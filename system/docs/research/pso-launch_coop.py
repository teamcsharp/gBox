"""Launch a PSO buddy (co-op) session: two virtual pads, its own memory card, no focus needed.

This is the mode CP19 is specified against. The plane's co-op stack (`pso_coop`, 308 KB) drives "two real controllers for offline PSO Plus, with native
observation on each step", and `pso_coop_setup` writes a **private pad map** for those two players - virtual controllers rather than the operator's
keyboard. Input through a virtual pad does not depend on which window has focus, which is exactly the background-play property that the keyboard path
cannot provide.

The launch has hard requirements, enforced by the plane itself:
  * `pso_coop: True`;
  * **no `memory_cards`, no `jump`, no `capture_for`** - "a buddy launch uses its own card and cannot borrow a card, jump state or capture session";
  * `agent_use: False`, so the session is not treated as agent-owned.

It prints the session id and the first error if it refuses, so a failure is diagnosable rather than silent.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

KEEP = ("game", "mod", "keep_session", "keep_sessions", "boot_timeout_s", "debug", "examine", "local_build_ok")


def online_worker():
    rows = S._call("/api/workers")
    rows = [row for row in (rows if isinstance(rows, list) else rows.get("items") or [])
            if row.get("name") == "i9-NUC" and row.get("online")]
    rows.sort(key=lambda row: row.get("last_seen") or 0, reverse=True)
    return rows[0]["id"] if rows else None


def main():
    worker = online_worker()
    print("worker:", worker)
    if not worker:
        return 2
    rows = S._call("/api/jobs")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    launches = [row for row in rows if row.get("tool") == "launch_game" and row.get("state") == "succeeded"]
    if not launches:
        print("no successful launch_game job to copy a payload from")
        return 3
    source = launches[0]
    original = dict(source.get("input") or {})
    payload = {key: original[key] for key in KEEP if key in original}
    payload["pso_coop"] = True
    print("payload keys:", sorted(payload))
    body = {"tool": "launch_game", "input": payload, "require_worker": worker, "agent_use": False}
    try:
        created = S._call("/api/jobs", "POST", body)
    except Exception as exc:                                      # noqa: BLE001
        print("launch refused:", str(exc)[:200])
        return 4
    job_id = created.get("id")
    print("job:", job_id, created.get("state"))
    deadline = time.time() + 300
    while time.time() < deadline:
        job = S._call(f"/api/jobs/{job_id}")
        state = job.get("state")
        if state in ("succeeded", "failed"):
            print("result:", state)
            if job.get("error"):
                print("error:", str(job["error"])[:300])
            output = job.get("output") or {}
            print("session:", output.get("session_id"), "| keys:", sorted(output)[:10])
            return 0 if state == "succeeded" else 5
        time.sleep(3)
    print("timed out waiting for the launch")
    return 6


if __name__ == "__main__":
    raise SystemExit(main())
