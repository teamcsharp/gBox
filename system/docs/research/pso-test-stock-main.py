"""Test whether my `main.js` console patch broke the worker handshake.

The app is healthy after a machine reboot but its worker still never sends `ready`, so the cause is a persistent condition rather than transient state. The one
change in `main.js` on this machine is mine - the commit that made the server output readable added:

* `CONSOLE_FILE` and an `appendFileSync` inside `logPush`;
* a `teeChild` call (already disabled and ruled out);
* **a wrapper around `console.log/warn/error`**.

Wrapping `console` in an Electron main process is exactly the kind of change that can disturb a handshake that logs as it proceeds, so this restores the version of
`main.js` from **before that commit** (`ec73b7a6^`), restarts the app, and reports whether the worker registers.

The current file is backed up first, so nothing is lost either way.
"""
import json
import pathlib
import shutil
import subprocess
import time
import urllib.request

TARGET = pathlib.Path(r"C:\_tools\gBox\system\clients\desktop\main.js")
REPO = pathlib.Path(r"C:\_tools\gBox\.tmp\main-repo")
BACKUP = TARGET.with_suffix(".js.bak-prepatch-test")
TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()


def call(path, timeout=10):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception:                                              # noqa: BLE001
        return {}


def workers():
    rows = call("/api/workers")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    return [(row.get("name"), row.get("online")) for row in rows]


if __name__ == "__main__":
    shutil.copy2(TARGET, BACKUP)
    print("backed up the patched main.js to", BACKUP.name)

    # the commit that added the console patch is ec73b7a6; take its parent
    result = subprocess.run(
        ["git", "-C", str(REPO), "show", "ec73b7a6^:system/clients/desktop/main.js"],
        capture_output=True, timeout=120)
    if result.returncode != 0:
        raise SystemExit("git show failed: " + result.stderr.decode("utf-8", "replace")[:200])
    stock = result.stdout
    print("pre-patch main.js:", len(stock), "bytes")

    TARGET.write_bytes(stock)
    check = subprocess.run(["node", "--check", str(TARGET)], capture_output=True, text=True, timeout=120)
    print("node check:", "OK" if check.returncode == 0 else check.stderr[:200])
    print("console hooks present:", b"console[lv] =" in stock or b'console[lv]' in stock)
    print("CONSOLE_FILE present:", b"CONSOLE_FILE" in stock)

    print("\nrestarting the app with the pre-patch file...")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Start-ScheduledTask -TaskName 'gbox-desktop-launch'"],
                   capture_output=True, text=True, timeout=90)

    for index in range(22):
        time.sleep(5)
        health = call("/api/health", timeout=5)
        state = workers()
        print(f"  +{(index + 1) * 5:3d}s health={bool(health.get('ok'))} workers={state}")
        if any(online for _, online in state):
            print("\nVERDICT: the worker registers with the pre-patch main.js - my console patch was the cause")
            break
    else:
        print("\nVERDICT: still no worker with the pre-patch main.js - the patch is not the cause")
        shutil.copy2(BACKUP, TARGET)
        print("restored the patched main.js")
