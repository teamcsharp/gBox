"""Break the village room's own archive and see whether the game notices.

The FST says `St1/r100.das` is at some offset. If the game reads that file there, overwriting its first 4 KB with 0xFF
cannot leave the village playable - the archive header, its table or its first model is gone, so the stage either fails to
load or the emulator crashes. If the village still plays, the offsets in `gbox.gcdisc` are not the ones the game uses and
the problem is the parser rather than any mod.

One build, one launch, one observation: the round either starts or it does not.
"""
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.expanduser("~/gBox/system"))
from gbox.gcdisc import GCDisc

HOME = os.path.expanduser("~")
TOKEN = open(f"{HOME}/gBox/system/gbox-data/api_token").read().strip()
BASE = "http://127.0.0.1:8765"
HEADERS = {"authorization": "Bearer " + TOKEN, "content-type": "application/json", "x-gbox-actor": "agent"}
GC = "78ab9efa2e310db4"
BUILD = "re4gc-stagebreak"
TARGET = "St1/r100.das"
SRC = f"{HOME}/gBox_alt/re4-lab/gc/re4-d1.iso"
OUT = f"{HOME}/gBox_alt/gbox-cache/mods/{GC}/{BUILD}"
PINS = {"re4": {"platform": "switch", "mode": "mercenaries", "title_id": "010099A00BC1E000"},
        "re5": {"platform": "switch", "mode": "no_mercy", "title_id": "010018100CD46000"}}


def api(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {"detail": exc.read()[:300].decode("utf-8", "replace")}
    except Exception as exc:                                    # noqa: BLE001
        return None, {"detail": str(exc)[:200]}


def rows(body, key):
    return body if isinstance(body, list) else (body.get(key) or []) if isinstance(body, dict) else []


def running():
    return [r for r in rows(api("GET", "/api/sessions")[1], "sessions") if r.get("state") == "running"]


def jobs_running():
    return [r for r in rows(api("GET", "/api/jobs?limit=8")[1], "jobs") if r.get("state") == "running"]


def pause_and_wait():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": False})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    for _ in range(30):
        time.sleep(4)
        if not running() and not jobs_running():
            return True
    return False


def restore():
    api("POST", "/api/mercmode", {"op": "configure", "host": "lilspark", "enabled": True, "titles": ["re4", "re5"],
                                  "rounds_per_title": 1, "keep_warm": 0, "preferred_editions": PINS})
    for row in running():
        api("POST", "/api/jobs", {"tool": "session_op", "input": {
            "session_id": row.get("session_id") or row.get("id"), "op": "stop_game", "args": {}}})
    print("MARK rotation restored", flush=True)


def build() -> int:
    disc = GCDisc(SRC)
    if TARGET not in disc.files:
        print(f"{TARGET}: not on the disc")
        return 1
    offset, size = disc.files[TARGET]
    print(f"{TARGET}: offset {offset} size {size}")
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, "re4-d1.iso")
    if not os.path.isfile(target) or os.path.getsize(target) != os.path.getsize(SRC):
        print("copying the disc (1.4 GB)...", flush=True)
        shutil.copyfile(SRC, target)
    with open(target, "r+b") as handle:
        handle.seek(offset)
        handle.write(b"\xff" * 4096)
    print("broke the first 4096 bytes of the room archive")
    with open(os.path.join(OUT, ".gbox-mod.json"), "w", encoding="utf-8") as handle:
        json.dump({"name": BUILD, "note": f"{TARGET} first 4 KB overwritten - does the game read this file?",
                   "built": str(time.time()), "game_id": GC, "kind": "file", "launchable": True,
                   "image": "re4-d1.iso", "changes": {TARGET: "first 4 KB destroyed"}}, handle, indent=1)
    return 0


if build() != 0:
    raise SystemExit(1)

session = None
try:
    print("MARK host idle:", pause_and_wait(), flush=True)
    status, body = api("POST", f"/api/games/{GC}/launch?node=lilspark&mod={BUILD}", {})
    job = body.get("id") if isinstance(body, dict) else None
    print("MARK launch", status, job, flush=True)
    for _ in range(36):
        time.sleep(5)
        for row in running():
            if row.get("game_id") == GC:
                session = row.get("session_id") or row.get("id")
        if session:
            break
    print("MARK session", session, flush=True)
    if not session and job:
        _, detail = api("GET", f"/api/jobs/{job}")
        print("MARK launch failed:", str(detail.get("error"))[:240], flush=True)
    from io import BytesIO

    from PIL import Image
    import statistics
    for step in range(14):
        time.sleep(12)
        if not session:
            break
        try:
            url = f"{BASE}/api/sessions/{session}/frame.jpg"
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
                raw = response.read()
        except Exception:                                        # noqa: BLE001
            print("MARK no frame at", step, flush=True)
            continue
        path = f"{HOME}/gBox_alt/re4-lab/stagebreak_{step:02d}.jpg"
        with open(path, "wb") as handle:
            handle.write(raw)
        grey = Image.open(BytesIO(raw)).convert("L")
        print("MARK frame %02d mean %.1f -> %s" % (step, statistics.fmean(list(grey.getdata())), path), flush=True)
finally:
    restore()
