"""Compatibility sweep: launch real games from every platform on a node, verify they run AND draw, record results.

    python scripts/compat_sweep.py --server http://10.89.1.246:8765 [--per-platform 2] [--platform n64] [--seconds 25]

For each platform with a core: pick games from the catalog, launch through the API (same path as the UI), wait,
grab a frame (get_frame -> artifact + mean brightness), stop the session, and set the game's status with the frame
artifact as evidence. Writes a JSON report. A game passes only if the core reports PLAYING and the frame isn't black.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

BLACK = 4.0          # mean luma below this = black screen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://10.89.1.246:8765")
    ap.add_argument("--token", default=os.environ.get("GBOX_TOKEN"))
    ap.add_argument("--token-file", default=str(Path(__file__).resolve().parent.parent / "gbox-data" / "api_token"))
    ap.add_argument("--per-platform", type=int, default=1)
    ap.add_argument("--platform", action="append")
    ap.add_argument("--seconds", type=int, default=25)
    ap.add_argument("--node", default="linux")
    ap.add_argument("--report", default="compat_report.json")
    ap.add_argument("--resume", action="store_true", help="keep results already in --report and skip those platforms")
    a = ap.parse_args()
    tok = a.token or Path(a.token_file).read_text().strip()
    raw = httpx.Client(base_url=a.server, headers={"authorization": f"Bearer {tok}"}, timeout=60)

    class Resilient:                                  # the control plane may restart (update & relaunch): wait it out
        def __getattr__(self, verb):
            def call(*args, **kw):
                for attempt in range(60):
                    try:
                        return getattr(raw, verb)(*args, **kw)
                    except httpx.TransportError:
                        time.sleep(5)
                raise RuntimeError("control plane unreachable for 5 minutes")
            return call
    c = Resilient()

    def job(body, limit=900):
        j = c.post("/api/jobs", json=body).json()
        t = time.time()
        while j["state"] in ("queued", "running") and time.time() - t < limit:
            time.sleep(1)
            j = c.get(f"/api/jobs/{j['id']}").json()
        return j

    facets = c.get("/api/catalog/facets").json()["platforms"]
    results = json.loads(Path(a.report).read_text()) if a.resume and Path(a.report).exists() else []
    done_plats = {r["platform"] for r in results}
    for plat in sorted(a.platform or facets):
        if plat in done_plats:
            continue
        items = c.get("/api/catalog", params={"platform": plat, "limit": 200}).json()["items"]
        picks = [g for g in items if g.get("core") and not g.get("clone_of") and g["format"] != "dir"][:a.per_platform]
        if not picks:
            results.append({"platform": plat, "result": "skipped", "reason": "no core on linux (Windows node) or no files"})
            print(f"{plat:16} skipped", flush=True)
            continue
        for g in picks:
            t0 = time.time()
            r = {"platform": plat, "game_id": g["game_id"], "title": g["title"], "core": g["core"]}
            lj = c.post(f"/api/games/{g['game_id']}/launch", params={"node": a.node}).json()
            while lj["state"] in ("queued", "running"):
                time.sleep(1)
                lj = c.get(f"/api/jobs/{lj['id']}").json()
            if lj["state"] != "succeeded":
                r |= {"result": "launch_failed", "error": (lj.get("error") or "")[:400]}
            else:
                sid = lj["output"]["session_id"]
                r["renderer"] = lj["output"]["detail"].get("renderer")
                time.sleep(a.seconds)
                fj = job({"tool": "get_frame", "input": {"session_id": sid}})
                q = job({"tool": "session_op", "input": {"session_id": sid, "op": "query_runtime"}})
                luma = (fj.get("output") or {}).get("mean_luma")
                state = ((q.get("output") or {}).get("result") or {}).get("state")
                evidence = []
                if fj.get("receipt_id"):
                    evidence = [x["sha256"] for x in c.get(f"/api/receipts/{fj['receipt_id']}").json()["artifacts"]]
                ok = state in ("PLAYING", "PAUSED") and luma is not None and luma > BLACK
                r |= {"result": "pass" if ok else ("black_screen" if state == "PLAYING" else f"state_{state}"),
                      "mean_luma": luma, "evidence": evidence}
                job({"tool": "session_op", "input": {"session_id": sid, "op": "stop_game"}})
                c.post(f"/api/catalog/{g['game_id']}/status",
                       json={"playable": "verified: runs + draws" if ok else f"sweep: {r['result']}", "evidence": evidence})
            r["seconds"] = round(time.time() - t0, 1)
            results.append(r)
            print(f"{plat:16} {r['result']:14} {g['title'][:40]:40} {r.get('mean_luma', '')} {r.get('error', '')[:120]}", flush=True)
            Path(a.report).write_text(json.dumps(results, indent=1))
    passed = sum(1 for r in results if r["result"] == "pass")
    tested = sum(1 for r in results if r["result"] != "skipped")
    print(f"\n{passed}/{tested} launched games verified; report: {a.report}")
    sys.exit(0 if passed == tested else 1)


if __name__ == "__main__":
    main()
