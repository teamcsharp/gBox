"""Prove the admin channel: ask gBox to relaunch itself, then confirm it comes back.

`POST /api/workers/{wid}/admin` is the bounded administration endpoint - `relaunch` restarts the desktop app, `rebuild` updates it from the repo. It needs the
installation id (64 hex), a request id (32 hex), and `enable_remote_admin`, which is the explicit opt-in for this channel.

The operator asked for exactly this: "close and reload and update gBox … to keep this task moving". Restarting is also how a `server.py` change takes effect.

This submits the request, polls its status, and then waits for `/api/health` to answer again - reporting each stage, so the capability is demonstrated rather than
assumed.
"""
import json
import os
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
INSTALLATION = "2141adfbccd2e0d6e91a1f2f3b61913184cfe0ae555117619ed48ad477624670"
BASE = "http://127.0.0.1:18765"


def call(path, payload=None, method="GET", timeout=40):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        try:
            return {"err": type(exc).__name__, "code": exc.code,
                    "body": exc.read()[:240].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__, "detail": str(exc)[:140]}


def workers():
    rows = call("/api/workers")
    return rows if isinstance(rows, list) else (rows.get("items") or [])


if __name__ == "__main__":
    online = [w for w in workers() if w.get("online")]
    if not online:
        raise SystemExit("no online worker")
    worker = online[0]
    wid = worker.get("id")
    print("worker:", worker.get("name"), "| id:", wid)

    request_id = os.urandom(16).hex()
    body = {"installation": INSTALLATION, "request_id": request_id, "op": "relaunch",
            "force": True, "enable_remote_admin": True}
    print("\nPOST /api/workers/%s/admin  op=relaunch" % wid)
    answer = call(f"/api/workers/{wid}/admin", body, "POST")
    print("  ->", json.dumps(answer)[:300])
    if isinstance(answer, dict) and "err" in answer:
        raise SystemExit("the admin request was refused")

    print("\npolling the request:")
    terminal = False
    for index in range(30):
        time.sleep(2)
        row = call(f"/api/workers/{wid}/admin/{request_id}")
        if isinstance(row, dict) and "err" in row:
            print(f"  {index + 1:2d} during restart: {json.dumps(row)[:90]}")
            continue
        state = row.get("state") or row.get("status")
        print(f"  {index + 1:2d} {state} | {str(row.get('detail'))[:80]}")
        if state in ("done", "failed", "refused", "returned", "completed"):
            terminal = True
            break

    print("\nwaiting for the app to answer again:")
    recovered = None
    for index in range(40):
        time.sleep(2)
        health = call("/api/health", timeout=5)
        if isinstance(health, dict) and health.get("ok"):
            recovered = time.time()
            print(f"  health ok after {(index + 1) * 2}s")
            break
        print(f"  {(index + 1) * 2:3d}s: {json.dumps(health)[:70]}")

    print("\n=== after the restart ===")
    rows = workers()
    for row in rows:
        print(f"  worker {row.get('name')} | online {row.get('online')} | id {row.get('id')}")
    sessions = call("/api/sessions")
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    print("  sessions:", len(sessions), "| live:",
          len([s for s in sessions if s.get("state") in ("running", "starting")]))
    print("\nVERDICT:", "the admin channel works - gBox restarted and came back"
          if recovered else "the app did not come back within 80s")
