"""Ask the emulator itself: is fast-forward on, and does it report a higher rate?

The previous measurement was inconclusive for a concrete reason: the only counter found ran at a steady 43.7 kHz, which is real time, not game time - it cannot
rise with the game's speed. `session_rpc("info")` returns `runtime: ad.query_runtime()` and `fast_forward: rewind.fast_forward_status(...)`, which are the
emulator's own answers about its own pacing.

So: read `info` at 1x, enable fast-forward, read `info` again, and compare. If Dolphin reports a higher speed or FPS, that is a measurement; if it reports the same,
then the lane key is not reaching the emulator and that is the finding.
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()


def rpc(sid, op, args, timeout=40):
    request = urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions/%s/rpc" % sid,
        data=json.dumps({"op": op, "args": args}).encode(), method="POST",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {str(exc)[:140]}"}


def service(sid, op, args):
    body = {"tool": "session_op", "input": {"session_id": sid, "op": op, "args": args}, "require_worker": sid.split("-")[0]}
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
            return {"state": row.get("state"), "error": str(row.get("error") or "")[:200], "result": row.get("result")}
    return {"state": "timeout"}


def snapshot(sid, label):
    info = rpc(sid, "info", {})
    if "_error" in info:
        print(f"  {label}: info failed {info['_error']}")
        return None
    runtime = info.get("runtime") or {}
    ff = info.get("fast_forward") or {}
    keys = [k for k in runtime if any(word in k.lower() for word in ("fps", "speed", "rate", "frame", "vps"))]
    picked = {k: runtime[k] for k in keys} if keys else runtime
    print(f"  {label}: fast_forward={json.dumps(ff)[:120]}")
    print(f"            runtime={json.dumps(picked, default=str)[:300]}")
    return runtime


if __name__ == "__main__":
    sessions = json.loads(urllib.request.urlopen(urllib.request.Request(
        "http://127.0.0.1:18765/api/sessions",
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"}), timeout=20).read())
    sessions = sessions if isinstance(sessions, list) else (sessions.get("items") or [])
    sid = next(row["session_id"] for row in sessions if row.get("state") in ("running", "starting"))
    print("session:", sid)

    print("\n=== at 1x ===")
    before = snapshot(sid, "before")

    print("\n=== enable fast-forward ===")
    print(" ", json.dumps(service(sid, "fast_forward", {"on": True}), default=str)[:200])
    time.sleep(2.0)

    print("\n=== with fast-forward on ===")
    during = snapshot(sid, "during")

    print("\n=== restore ===")
    print(" ", json.dumps(service(sid, "fast_forward", {"on": False}), default=str)[:200])

    if before and during:
        changed = {k: (before.get(k), during.get(k)) for k in set(before) | set(during) if before.get(k) != during.get(k)}
        print("\nfields that changed:")
        for key, (a, b) in list(changed.items())[:10]:
            print(f"  {key}: {a} -> {b}")
        if not changed:
            print("  none - the emulator reports the same runtime with fast-forward on")
