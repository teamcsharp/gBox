"""Launch PSO on the server, using the full catalog entry LaunchIn requires.

`LaunchIn` fields: `game: CatalogEntry` (a whole entry, not an id), plus optional flags. This finds the catalog entry for PSO, submits `launch_game`, and
follows the job to its end so we learn whether the server can launch at all - which decides whether the client or the server is the broken side.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

GAME_ID = "436e0bb84d5337d1"

# find the catalog entry
entry = None
for path in ("/api/catalog", "/api/games", "/api/library"):
    try:
        data = S._call(path)
    except Exception:                                             # noqa: BLE001
        continue
    rows = data if isinstance(data, list) else (data.get("items") or data.get("games") or data.get("entries") or [])
    if not isinstance(rows, list):
        continue
    for row in rows:
        if str(row.get("game_id") or row.get("id") or "") == GAME_ID:
            entry = row
            break
    if entry:
        print("found the catalog entry in", path)
        break

if not entry:
    raise SystemExit("no catalog entry for PSO found")

print("entry keys:", sorted(entry)[:12])
print("title:", entry.get("title"), "| platform:", entry.get("platform"))

workers = S._call("/api/workers")
workers = workers if isinstance(workers, list) else (workers.get("items") or [])
online = [worker for worker in workers if worker.get("online")]
node = online[0].get("id") or online[0].get("worker")
print("worker:", node)

body = {"tool": "launch_game", "input": {"game": entry}, "require_worker": node, "agent_use": False}
try:
    job = S._call("/api/jobs", "POST", body)
except Exception as exc:                                          # noqa: BLE001
    print("SUBMIT FAILED:", type(exc).__name__, str(exc)[:400])
    raise SystemExit(1)

print("job:", job.get("id"))
for step in range(50):
    time.sleep(3)
    state = S._call(f"/api/jobs/{job.get('id')}")
    progress = state.get("progress") or {}
    print(f"  t+{step * 3:3d}s {state.get('state')} {progress.get('pct')}% {str(progress.get('msg'))[:60]}")
    if state.get("state") in ("succeeded", "failed"):
        print("FINAL:", state.get("state"), "| error:", str(state.get("error"))[:300])
        print("output:", json.dumps(state.get("output") or {})[:300])
        break
