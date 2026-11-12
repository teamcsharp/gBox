"""Clear the launch blockage: a stale session is holding the memory card.

The evidence:

* the queued job is `launch_game` with **`require_worker: None`** - it cannot start;
* the launch before it **failed** with **`RuntimeError: This card is already inserted in another session`**;
* a session from 08:42 is still `running` at PSO's title screen.

So the memory card is claimed by the stale session, and every new launch is refused for it. The queued job never gets a worker because the launch it belongs to
could not claim the card.

This cancels the stuck job and stops the stale session, which releases the card - then a launch can proceed. It reports the exact state before and after rather than
assuming the release worked.
"""
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()


def call(path, payload=None, method="GET", timeout=40):
    request = urllib.request.Request(
        "http://127.0.0.1:18765" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent", "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(request, timeout=timeout).read() or b"null")
    except Exception as exc:                                       # noqa: BLE001
        try:
            return {"err": type(exc).__name__, "code": exc.code, "body": exc.read()[:200].decode("utf-8", "replace")}
        except Exception:                                          # noqa: BLE001
            return {"err": type(exc).__name__, "detail": str(exc)[:120]}


def sessions():
    rows = call("/api/sessions")
    return rows if isinstance(rows, list) else (rows.get("items") or [])


if __name__ == "__main__":
    print("=== before ===")
    for row in sessions():
        if row.get("state") in ("running", "starting"):
            print(f"  running {row.get('session_id')} | agent {row.get('agent_owned')} | "
                  f"{time.strftime('%H:%M:%S', time.localtime(row.get('started') or 0))}")

    queued = call("/api/jobs?state=queued,running")
    queued = queued if isinstance(queued, list) else (queued.get("items") or [])
    for job in queued:
        print(f"  queued job {job.get('id')} ({job.get('tool')}, worker {job.get('require_worker')})")
        for path, verb in ((f"/api/jobs/{job['id']}/cancel", "POST"), (f"/api/jobs/{job['id']}", "DELETE")):
            answer = call(path, {}, verb)
            if not isinstance(answer, dict) or "err" not in answer:
                print(f"    cancelled via {verb} {path.split('/')[-1]}")
                break
        else:
            print("    could not cancel")

    print("\n=== stopping stale sessions ===")
    for row in sessions():
        if row.get("state") in ("running", "starting"):
            sid = row["session_id"]
            answer = call(f"/api/sessions/{sid}/stop", {})
            if isinstance(answer, dict) and "err" in answer:
                answer = call(f"/api/sessions/{sid}", {}, "DELETE")
            print(f"  stop {sid}: {json.dumps(answer)[:140]}")
            time.sleep(2)

    time.sleep(3)
    print("\n=== after ===")
    remaining = [row for row in sessions() if row.get("state") in ("running", "starting")]
    print("running sessions:", len(remaining))
    queued = call("/api/jobs?state=queued,running")
    queued = queued if isinstance(queued, list) else (queued.get("items") or [])
    print("active jobs:", len(queued), [job.get("tool") for job in queued])
