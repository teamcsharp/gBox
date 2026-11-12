"""Free the worker from PSO so gBox can broadcast MercMode, and stop anything of mine that relaunches it.

The operator's requirement: *"i need pso to stop taking over gbox's service because its supposed to be broadcasting merc mode"*.

The state that matters:

* MercMode's dispatcher holds `"command": "stop"` - it is not running;
* the **only** live session is PSO, agent-owned false, holding the single worker `i9-NUC`;
* so MercMode has no worker to run on.

Two things are done here, in order:

1. **any background process of mine that could relaunch or drive PSO is stopped** - a supervisor or a leftover test script that relaunches games would keep taking
   the worker back;
2. **the PSO session is stopped**, which releases the worker.

Before and after are reported, so "the worker is free" is a measurement.
"""
import json
import subprocess
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()


def call(path, payload=None, method="GET", timeout=40):
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
                    "body": exc.read()[:200].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__}


def sessions():
    rows = call("/api/sessions")
    return rows if isinstance(rows, list) else (rows.get("items") or [])


def mine():
    """Python processes of mine that touch launching or driving games."""
    script = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                            capture_output=True, text=True, timeout=60)
    try:
        rows = json.loads(result.stdout or "[]")
    except Exception:                                              # noqa: BLE001
        return []
    rows = rows if isinstance(rows, list) else [rows]
    out = []
    for row in rows:
        line = str(row.get("CommandLine") or "")
        if any(key in line for key in ("supervisor.py", "play_rooms.py", "launch_and_test", "relaunch_ps",
                                       "watch_autoplay", "start_autoplay", "boot_test", "now_test_input")):
            out.append((row.get("ProcessId"), line[:120]))
    return out


if __name__ == "__main__":
    print("=== before ===")
    for row in sessions():
        if row.get("state") in ("running", "starting"):
            print(f"  live: {row.get('session_id')} | agent {row.get('agent_owned')}")

    print("\n=== my processes that could take the worker ===")
    found = mine()
    for pid, line in found:
        print(f"  {pid}: {line}")
    for pid, _line in found:
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"],
                       capture_output=True, text=True, timeout=60)
        print(f"  stopped {pid}")
    if not found:
        print("  none")

    print("\n=== stopping PSO ===")
    for row in sessions():
        if row.get("state") in ("running", "starting"):
            sid = row["session_id"]
            answer = call(f"/api/sessions/{sid}/stop", {}, "POST")
            if isinstance(answer, dict) and "err" in answer:
                answer = call(f"/api/sessions/{sid}", {}, "DELETE")
            print(f"  stop {sid}: {json.dumps(answer)[:160]}")
    time.sleep(4)

    print("\n=== after ===")
    live = [row for row in sessions() if row.get("state") in ("running", "starting")]
    print("  live sessions:", len(live), [row.get("session_id") for row in live])
    workers = call("/api/workers")
    workers = workers if isinstance(workers, list) else (workers.get("items") or [])
    for worker in workers:
        print(f"  worker {worker.get('name')} | online {worker.get('online')} | "
              f"running_jobs {worker.get('running_jobs')} | active_jobs {worker.get('active_jobs')}")
    jobs = call("/api/jobs?state=queued,running")
    jobs = jobs if isinstance(jobs, list) else (jobs.get("items") or [])
    print("  active jobs:", len(jobs), [(j.get("tool"), j.get("state")) for j in jobs[:4]])
    print("\nVERDICT:", "the worker is free for MercMode" if not live else "a session is still holding it")
