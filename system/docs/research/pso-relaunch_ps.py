"""Launch PSO through the app's own route and watch it to completion."""
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
GAME = "436e0bb84d5337d1"


def call(path, payload=None, method="POST", timeout=90):
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
                    "body": exc.read()[:250].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__, "detail": str(exc)[:150]}


if __name__ == "__main__":
    answer = call(f"/api/games/{GAME}/launch?node=auto", {})
    print("launch response:", json.dumps(answer)[:240])
    job_id = answer.get("id") if isinstance(answer, dict) else None
    if not job_id:
        raise SystemExit("no job id")

    started = time.time()
    for index in range(30):
        time.sleep(3)
        row = call("/api/jobs/" + job_id, method="GET")
        state = row.get("state")
        progress = row.get("progress") or {}
        pct = progress.get("pct")
        message = str(progress.get("msg") or "")[:60]
        error = str(row.get("error") or "")[:80]
        print(f"  {index + 1:2d} {state:9s} pct={pct} {message} {error}")
        if state in ("succeeded", "failed", "cancelled"):
            print(f"\nduration: {time.time() - started:.1f}s")
            break

    rows = call("/api/sessions", method="GET")
    rows = rows if isinstance(rows, list) else (rows.get("items") or [])
    live = [row for row in rows if row.get("state") in ("running", "starting")]
    print("live sessions:", len(live),
          [(row.get("session_id"), row.get("agent_owned")) for row in live[:2]])
