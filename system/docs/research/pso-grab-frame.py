"""Capture the game's own frame so the screen can be read instead of guessed.

`get_frame` is in the adapter's `supported` set, so `session_op` may call it (`op` in `adapters.OPS`). It returns the emulator's picture, which settles what PSO is
actually showing - a title screen, a memory-card prompt, an error dialog, or a still-loading black frame - and that decides what the bot would need to press.
"""
import base64
import json
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
OUT = r"D:\gBox\pso-ds\pso_screen.bin"


def call(path, payload=None, method="GET", timeout=90):
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


if __name__ == "__main__":
    rows = call("/api/sessions")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    if not live:
        raise SystemExit("no live session")
    sid = live[0]["session_id"]
    worker = sid.split("-")[0]
    print("session:", sid)

    body = {"tool": "session_op", "require_worker": worker,
            "input": {"session_id": sid, "op": "get_frame", "args": {}}}
    answer = call("/api/jobs", body, "POST")
    job_id = answer.get("id") if isinstance(answer, dict) else None
    print("job:", job_id, "|", json.dumps(answer)[:150])
    if not job_id:
        raise SystemExit("no job")

    import time
    for _ in range(15):
        time.sleep(2)
        row = call("/api/jobs/" + job_id)
        if row.get("state") in ("succeeded", "failed", "cancelled"):
            print("state:", row.get("state"), "|", str(row.get("error"))[:150])
            result = row.get("result") or row.get("output") or {}
            print("result type:", type(result).__name__)
            print("result preview:", json.dumps(result)[:300])
            if isinstance(result, dict):
                for key in ("image", "png", "jpeg", "data", "b64"):
                    value = result.get(key)
                    if isinstance(value, str) and len(value) > 500:
                        raw = base64.b64decode(value)
                        open(OUT, "wb").write(raw)
                        print(f"wrote {len(raw)} bytes to {OUT} (from {key})")
                        break
            break
