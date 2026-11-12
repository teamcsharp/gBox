"""Launch with the worker named, then report the vpad trace and the pad binding.

The virtual pad was disabled by a persistent User environment variable `GBOX_DOLPHIN_VPAD=off`, which the trace made visible:

```
10:30:47 setup_vpad entered gecko='GPOE8P' capture=None flag='off'
10:30:47 _want_vpad() is False - keyboard ini used
```

It is now `on`. This clears any queued job (they do not dispatch with `require_worker: None`), launches with the worker named, and reports:

* `vpad_trace.log` - whether `_setup_vpad` ran and what slot the pad took;
* the `Device =` line in `GCPadNew.ini` - `XInput/<slot>` proves the pad is bound.
"""
import json
import pathlib
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
GAME = "436e0bb84d5337d1"
TRACE = pathlib.Path(r"D:\gBox\pso-ds\vpad_trace.log")
INI = pathlib.Path(r"D:\gBox\runtime\dolphin\Dolphin-x64\User\Config\GCPadNew.ini")


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
                    "body": exc.read()[:180].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__}


if __name__ == "__main__":
    TRACE.unlink(missing_ok=True)

    queued = call("/api/jobs?state=queued,running")
    queued = queued if isinstance(queued, list) else (queued.get("items") or [])
    for job in queued:
        call("/api/jobs/%s/cancel" % job["id"], {}, "POST")
        print("cancelled", job.get("id"), job.get("tool"))
    time.sleep(2)

    workers = call("/api/workers")
    workers = workers if isinstance(workers, list) else (workers.get("items") or [])
    worker = next((w for w in workers if w.get("online")), None)
    if not worker:
        raise SystemExit("no online worker")
    print("worker:", worker.get("name"), worker.get("id"))

    game = call("/api/catalog/" + GAME)
    if not isinstance(game, dict) or "game_id" not in game:
        raise SystemExit("catalog lookup failed: %s" % json.dumps(game)[:150])

    job = call("/api/jobs", {"tool": "launch_game", "input": {"game": game},
                             "require_worker": worker["id"]}, "POST")
    job_id = job.get("id") if isinstance(job, dict) else None
    print("launch job:", job_id, "|", json.dumps(job)[:90])
    for _ in range(25):
        time.sleep(3)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("launch:", row.get("state"), "|", str(row.get("error"))[:90])
            break

    print("\n=== vpad_trace.log ===")
    if TRACE.is_file():
        for line in TRACE.read_text(encoding="utf-8").splitlines()[-10:]:
            print("  ", line)
    else:
        print("   not created - _setup_vpad never ran")

    print("\n=== GCPadNew.ini ===")
    if INI.is_file():
        for line in INI.read_text(encoding="utf-8").splitlines():
            if line.startswith("Device =") or line.startswith("Options/Always"):
                print("  ", line)
                if "GCPad2" in line:
                    break
