"""Clear the stale native-ownership records that are holding worker activation.

`worker.py:303` refuses to activate:

```python
if outbox.protected_sessions(_builtin._running_file(config)):
    raise RuntimeError('Worker activation held: a delivered native launch still has an owned PID record; no emulator was stopped')
```

and `protected_sessions` marks a session protected when `_pid_alive(record['pid'])` is true. `D:\\gBox\\runtime\\gbox-running.json` holds **15** records, the most recent
written at 15:39 - before every session since then ended. **Windows reuses PIDs**, so a long-dead emulator's PID can now belong to any unrelated process, which makes the
record look alive forever and the worker permanently refuse to start.

This reports which recorded PIDs currently answer, and - only when the answer cannot be a live emulator (no emulator process exists at all) - moves the manifest aside so
activation can proceed. The file is **renamed, not deleted**, so the record set is recoverable.
"""
import json
import subprocess
import time
from pathlib import Path

RUNNING = Path(r"D:\gBox\runtime\gbox-running.json")
QUARANTINE = Path(r"D:\gBox\runtime\gbox-running.json.bak-1600")


def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ 'yes' }} else {{ 'no' }}"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        return out == "yes"
    except Exception:                                              # noqa: BLE001
        return False


def emulators() -> list:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process | Where-Object { $_.ProcessName -match 'dolphin|eden|retroarch|pcsx2|citra|ryujinx' } | "
         "Select-Object -ExpandProperty ProcessName"],
        capture_output=True, text=True, timeout=60).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


if __name__ == "__main__":
    if not RUNNING.is_file():
        print("no running manifest:", RUNNING)
        raise SystemExit(0)

    records = json.loads(RUNNING.read_text(encoding="utf-8"))
    print(f"records: {len(records)}")
    alive = []
    for sid, record in records.items():
        pid = (record or {}).get("pid")
        live = pid_alive(pid)
        stamp = time.strftime("%H:%M:%S", time.localtime((record or {}).get("ts") or 0))
        print(f"  {sid[:24]:24s} pid={pid!s:8s} recorded {stamp}  alive now: {live}")
        if live:
            alive.append((sid, pid))

    print("\nemulator processes running:", emulators() or "none")
    print("recorded PIDs that answer:", [pid for _sid, pid in alive] or "none")

    if emulators():
        print("\nAn emulator is running - NOT touching the manifest.")
    else:
        if QUARANTINE.exists():
            QUARANTINE.unlink()
        RUNNING.rename(QUARANTINE)
        print(f"\nno emulator is running, so no recorded PID can be one - manifest moved to {QUARANTINE.name}")
        print("worker activation should now proceed; restart gBox to let it register")
