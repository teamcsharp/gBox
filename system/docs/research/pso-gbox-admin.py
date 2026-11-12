"""gbox_admin - close, relaunch, reload and update gBox without asking anyone.

The operator's requirement: *"you should be able to close and reload and update gbox and able to resolve any issues with it to keep this task moving"*.

Four capabilities, each using what the installation actually provides:

* **status**   - health, workers, live sessions, active jobs, in one call.
* **restart**  - stop the desktop app's processes and start `gBox.exe` again, then wait for `/api/health` to answer. This is the "close and reload" that also
                 makes a `server.py` change take effect.
* **reload**   - `POST /api/workers/{name}/bot-reload`: bot modules reload in place while games keep running, so a bot fix lands without a full restart.
* **update**   - the `repo_update` tool pulls the repo, `rebuild_node` rebuilds the node; both exist on the worker (`tools` contains all three).

The admin HTTP route (`/api/workers/{wid}/admin`) needs a paired recovery supervisor that is not installed here, so restart goes through the OS instead - which is
simpler, needs no federation, and is the same thing the supervisor would do.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

TOKEN_PATH = Path(r"C:\_tools\gBox\system\gbox-data\api_token")
EXE = Path(r"C:\Users\maste\AppData\Local\gbox\app\gBox.exe")
BASE = "http://127.0.0.1:18765"


def _token() -> str:
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def call(path: str, payload=None, method: str = "GET", timeout: float = 40):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + _token(), "x-gbox-actor": "agent",
                 "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        try:
            return {"err": type(exc).__name__, "code": exc.code,
                    "body": exc.read()[:240].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__, "detail": str(exc)[:140]}


def status() -> dict:
    health = call("/api/health", timeout=6)
    workers = call("/api/workers")
    workers = workers if isinstance(workers, list) else (workers.get("items") or [])
    sessions = call("/api/sessions")
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    jobs = call("/api/jobs?state=queued,running")
    jobs = jobs if isinstance(jobs, list) else (jobs.get("items") or [])
    return {
        "health": bool(isinstance(health, dict) and health.get("ok")),
        "workers": [(w.get("name"), w.get("online")) for w in workers],
        "live_sessions": [s.get("session_id") for s in sessions
                          if s.get("state") in ("running", "starting")],
        "active_jobs": [(j.get("tool"), j.get("state")) for j in jobs],
    }


def _pids() -> list[int]:
    script = ("Get-Process -Name 'gBox' -ErrorAction SilentlyContinue | "
              "Where-Object { $_.Path -like '*\\gbox\\app\\gBox.exe' } | Select-Object -ExpandProperty Id")
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                            capture_output=True, text=True, timeout=60)
    return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]


LAUNCH_TASK = "gbox-desktop-launch"


def restart(wait_s: float = 150.0, verbose: bool = True) -> dict:
    """Stop the desktop app and start it again through its own launcher task.

    `Start-Process gBox.exe` does **not** work: the app exits with code 0 immediately, because it is launched by a scheduled task
    (`gbox-desktop-launch` -> `powershell -File C:\\gbox_portal_ok\\launch_gbox.ps1`) whose environment and session the process needs. Starting the task is the
    mechanism that actually brings it up - measured: seven gBox processes, port 18765 listening, `/api/health` answering, ~25 s after the task ran.
    """
    pids = _pids()
    if verbose:
        print(f"  stopping {len(pids)} gBox process(es): {pids}")
    for pid in pids:
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"],
                       capture_output=True, text=True, timeout=60)
    for _ in range(40):
        if not _pids():
            break
        time.sleep(0.5)
    if verbose:
        print("  remaining gBox processes:", _pids())

    start = subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"Start-ScheduledTask -TaskName '{LAUNCH_TASK}'"],
        capture_output=True, text=True, timeout=60)
    if verbose:
        print(f"  Start-ScheduledTask {LAUNCH_TASK}: {start.returncode} {start.stderr.strip()[:80]}")

    started = time.time()
    for _ in range(int(wait_s / 2)):
        time.sleep(2)
        health = call("/api/health", timeout=5)
        if isinstance(health, dict) and health.get("ok"):
            elapsed = time.time() - started
            if verbose:
                print(f"  health answered after {elapsed:.0f}s with {len(_pids())} processes")
            return {"ok": True, "seconds": round(elapsed, 1), "pids": _pids(), "via": LAUNCH_TASK}
    return {"ok": False, "error": f"no health answer within {wait_s:.0f}s", "via": LAUNCH_TASK}


def reload_bots(worker: str = "", modules: list[str] | None = None) -> dict:
    workers = call("/api/workers")
    workers = workers if isinstance(workers, list) else (workers.get("items") or [])
    name = worker or next((w.get("name") for w in workers if w.get("online")), "")
    if not name:
        return {"ok": False, "error": "no online worker"}
    body = {"modules": modules or [], "settle_s": 2.0, "wait_s": 60}
    answer = call(f"/api/workers/{name}/bot-reload", body, "POST", timeout=90)
    return {"ok": "err" not in answer if isinstance(answer, dict) else False, "answer": answer}


def update(rebuild: bool = False) -> dict:
    """The worker's own `repo_update` (and optionally `rebuild_node`) tools."""
    workers = call("/api/workers")
    workers = workers if isinstance(workers, list) else (workers.get("items") or [])
    worker = next((w for w in workers if w.get("online")), None)
    if not worker:
        return {"ok": False, "error": "no online worker"}
    out = {}
    for tool in (["repo_update", "rebuild_node"] if rebuild else ["repo_update"]):
        job = call("/api/jobs", {"tool": tool, "input": {}, "require_worker": worker["id"]}, "POST")
        job_id = job.get("id") if isinstance(job, dict) else None
        out[tool] = {"job": job_id, "submitted": bool(job_id)}
        if not job_id:
            out[tool]["answer"] = job
    return {"ok": True, "tools": out}


if __name__ == "__main__":
    import sys

    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "status":
        print(json.dumps(status(), indent=1)[:900])
    elif action == "restart":
        print(json.dumps(restart(), indent=1)[:400])
    elif action == "reload":
        print(json.dumps(reload_bots(), indent=1)[:500])
    elif action == "update":
        print(json.dumps(update(), indent=1)[:500])
    else:
        print(__doc__)
