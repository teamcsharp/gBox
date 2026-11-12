"""Recover the worker: kill every competing control-plane process, then let the app spawn exactly one.

The evidence:

* the last `GBOX_CLIENT_CONTROL ... "event": "ready"` was at **16:30:26** - before the restarts that followed;
* after that the worker only logs `desktop-local-config` and a FastAPI deprecation, and **never sends `ready`**, which is what marks it online;
* **two** `desktop_local` processes exist, both started 10:36:35, and a manual `python -m gbox serve` of mine is holding 8765.

Two workers contending for the same ports and config is exactly how `ready` fails to arrive. So: stop my manual `serve`, stop every `desktop_local`, confirm both
ports are free, restart the app through its launcher task, and watch for the `ready` line plus `/api/workers` going online.
"""
import json
import subprocess
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()


def call(path, timeout=10):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception:                                              # noqa: BLE001
        return {}


def pids_matching(pattern: str) -> list[int]:
    script = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -match '%s' } | Select-Object -ExpandProperty ProcessId" % pattern)
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                            capture_output=True, text=True, timeout=90)
    return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]


def ports() -> dict:
    out = {}
    for port in (18765, 8765):
        script = f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count"
        result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                capture_output=True, text=True, timeout=60)
        out[port] = result.stdout.strip() not in ("", "0")
    return out


if __name__ == "__main__":
    print("before:", ports())

    for label, pattern in (("manual serve", "gbox.*serve"), ("desktop_local", "desktop_local")):
        found = pids_matching(pattern)
        print(f"  {label}: {found}")
        for pid in found:
            subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"],
                           capture_output=True, text=True, timeout=60)
    time.sleep(4)
    print("after the kills:", ports())
    print("  remaining desktop_local:", pids_matching("desktop_local"))

    print("\nrestarting the app through its launcher task...")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Start-ScheduledTask -TaskName 'gbox-desktop-launch'"],
                   capture_output=True, text=True, timeout=90)

    for index in range(20):
        time.sleep(5)
        workers = call("/api/workers")
        workers = workers if isinstance(workers, list) else (workers.get("items") or [])
        online = [(w.get("name"), w.get("online")) for w in workers]
        print(f"  +{(index + 1) * 5:3d}s ports={ports()} workers={online}")
        if any(w.get("online") for w in workers):
            print("\nVERDICT: the worker is online again")
            break
    else:
        print("\nVERDICT: the worker still has not registered")
