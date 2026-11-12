"""Is the 3.6x cap one saturated CPU core? Measure the emulator's own CPU use.

The refresh rate is 59 Hz so VSync is not the cap, and GPU use reads 5%, which rules out the GPU. Dolphin is strongly single-thread bound, and a task manager's
"9.7/20 cores" hides a single core at 100%.

`Get-Process.CPU` is cumulative processor seconds, so the delta over a wall interval is the number of cores the process used: ~1.0 means one core is saturated and
the ceiling is CPU; well under 1.0 means the cap is elsewhere.

The emulator's process is named **"gBox Dolphin"** (with a space) - a plain "Dolphin" lookup matches nothing and silently reports zero, which is what the first
attempt did.
"""
import json
import subprocess
import sys
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
PROCESS = "gBox Dolphin"


def service(sid, op, args):
    body = {"tool": "session_op", "input": {"session_id": sid, "op": op, "args": args},
            "require_worker": sid.split("-")[0]}
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/jobs", data=json.dumps(body).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    job = json.loads(urllib.request.urlopen(request, timeout=30).read() or b"null")
    job_id = job.get("id")
    for _ in range(30):
        time.sleep(1)
        row = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:18765/api/jobs/{job_id}",
            headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            return row.get("state")
    return "timeout"


def cpu_seconds():
    script = ('(Get-Process -Name "%s" -ErrorAction SilentlyContinue | '
              'Measure-Object -Property CPU -Sum).Sum' % PROCESS)
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                            capture_output=True, text=True, timeout=60)
    text = result.stdout.strip()
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))

    probe = cpu_seconds()
    print(f"process '{PROCESS}' cumulative CPU: {probe:.1f} s")
    if probe <= 0:
        raise SystemExit("process not found or CPU not readable")

    print("enabling fast-forward:", service(sid, "fast_forward", {"on": True}))
    time.sleep(1.5)

    started = time.time()
    a = cpu_seconds()
    time.sleep(4.0)
    b = cpu_seconds()
    elapsed = time.time() - started
    cores = (b - a) / elapsed
    print(f"\nused {b - a:.2f} CPU-seconds in {elapsed:.1f} s = {cores:.2f} cores of a "
          f"{__import__('os').cpu_count()}-thread machine")
    print("VERDICT:", "one core is saturated - the ceiling is single-thread CPU"
          if cores >= 0.85 else "CPU is not saturated - the cap is elsewhere")

    print("\nrestoring:", service(sid, "fast_forward", {"on": False}))
