"""Watch the armed PSO launch until it is admitted (or the watch ends), reporting the worker's idle and the session count."""
import json
import time
import urllib.request

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
JOB = "b13f235d1b2e42a1"


def get(path):
    req = urllib.request.Request("http://127.0.0.1:8765" + path,
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read() or b"null")


def main():
    for _ in range(14):
        time.sleep(18)
        workers = [w for w in get("/api/workers") if "i9" in (w.get("name") or "")]
        idle = round(workers[0].get("idle_seconds", 0)) if workers else None
        job = get("/api/jobs/" + JOB)
        sessions = get("/api/sessions?include_ended=false")
        reason = str((job.get("admission_wait") or {}).get("reason"))[:60]
        print(f"{time.strftime('%H:%M:%S')} idle={idle} job={job.get('state')} "
              f"sessions={len(sessions)} {reason}", flush=True)
        if job.get("state") in ("succeeded", "failed", "cancelled") or sessions:
            print("RESULT", json.dumps({"job": job.get("state"), "error": job.get("error"),
                                        "sessions": sessions}, default=str)[:500])
            return 0
    print("watch ended without an admission")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
