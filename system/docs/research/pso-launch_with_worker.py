"""Launch with the current worker named explicitly, instead of letting `auto` pick a stale one.

The job history makes the cause visible:

```
09:24:00  launch_game  queued   require_worker None                <- never dispatched
09:21:32  launch_game  failed   require_worker None
09:19:56  launch_game  failed   require_worker None
09:14:56  launch_game  failed   require_worker 12f466533ca34cbf    <- a worker id that is not the live one
08:41:57  launch_game  succeeded require_worker 0b1c2656706343d6   <- the live worker
08:38:47  launch_game  succeeded require_worker None
```

The app restarted its worker at 09:14:45, which produced a **new** worker id. Jobs submitted with `auto` now land with **no** `require_worker` and sit queued, and the one
that did carry a worker named the **old** id (`12f4...`), so it was refused for the memory card it could never claim.

So this asks for the live worker's id, fetches the full catalogue entry, and submits `launch_game` with `require_worker` set to that id - the shape that succeeded at
08:41.
"""
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
GAME = "436e0bb84d5337d1"


def call(path, payload=None, method="GET", timeout=120):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        try:
            return {"err": type(exc).__name__, "code": exc.code,
                    "body": exc.read()[:220].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__, "detail": str(exc)[:140]}


if __name__ == "__main__":
    workers = call("/api/workers")
    workers = workers if isinstance(workers, list) else (workers.get("items") or [])
    online = [w for w in workers if w.get("online")]
    if not online:
        raise SystemExit("no online worker")
    worker = online[0]
    worker_id = worker.get("id")
    print("worker:", worker.get("name"), "| id:", worker_id, "| tools:", len(worker.get("tools") or []))

    # a queued launch would block the card; clear anything active first
    active = call("/api/jobs?state=queued,running")
    active = active if isinstance(active, list) else (active.get("items") or [])
    for job in active:
        print("  cancelling", job.get("id"), job.get("tool"))
        call(f"/api/jobs/{job['id']}/cancel", {}, "POST")
    time.sleep(2)

    game = call(f"/api/catalog/{GAME}")
    if not isinstance(game, dict) or "game_id" not in game:
        raise SystemExit(f"catalog lookup failed: {json.dumps(game)[:200]}")
    print("game:", str(game.get("title"))[:50], "| has launch:", "launch" in game)

    body = {"tool": "launch_game", "input": {"game": game}, "require_worker": worker_id}
    job = call("/api/jobs", body, "POST")
    print("job:", json.dumps(job)[:160] if "id" in job else json.dumps(job)[:240])
    job_id = job.get("id")
    if not job_id:
        raise SystemExit("no job id")

    started = time.time()
    for index in range(30):
        time.sleep(3)
        row = call("/api/jobs/" + job_id)
        state = row.get("state")
        progress = row.get("progress") or {}
        print(f"  {index + 1:2d} {state:9s} pct={progress.get('pct')} "
              f"{str(progress.get('msg'))[:50]} {str(row.get('error'))[:70]}")
        if state in ("succeeded", "failed", "cancelled"):
            print(f"\nduration: {time.time() - started:.1f}s")
            break

    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    print("live sessions:", len(live),
          [(row.get("session_id"), row.get("agent_owned")) for row in live[:2]])
