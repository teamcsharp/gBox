"""Compatibility matrix: run every PSO mod op against the live GAMECUBE session and record what works.

The Dreamcast module (pso_mods_tool, PLAYER_TBL 0x8C42D92C) does not apply to the GameCube build, so each op is exercised against the
running GC session and classified:
    ok            - the op answered with a result and no error
    unsupported   - the worker said the action is not implemented for this build
    error:<code>  - an HTTP error (validation/permission/state)
    skipped       - deliberately not run (destructive while the operator is playing)

Read-only ops run first; mutating ops run only when the operator is idle, so testing never fights the operator.
Usage: gc_mod_matrix.py [--include-destructive]
"""
import json
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import pso_operator                                                # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"
OUT = r"D:\gBox\pso-ds\gc-mod-matrix.json"

READ_ONLY = ["capabilities", "status", "list", "floor_list", "mag", "modes", "bosses", "adventure_status"]
BENIGN = ["crit", "pb", "survival", "walk_through", "always_hit", "equip_any", "autoplay_speed", "stat", "equip"]
DESTRUCTIVE = ["give", "discard", "multi_equip", "legendary", "randomized", "floor_spawn", "floor_rares", "floor_clear",
               "boss_warp", "floor_warp", "revive", "mag_set", "mag_feed", "enemy_drops", "rehook"]

# minimal, safe arguments for each op
ARGS = {
    "stat": {"name": "lck", "value": 10},
    "crit": {},
    "pb": {},
    "survival": {},
    "walk_through": {},
    "always_hit": {},
    "equip_any": {},
    "autoplay_speed": {},
    "modes": {},
    "give": {"code": "030100", "count": 1},
    "discard": {},
    "legendary": {},
    "randomized": {"on": False},
    "enemy_drops": {},
    "rehook": {},
    "boss_warp": {"target": "dragon"},
    "floor_warp": {"target": "1"},
    "floor_rares": {},
    "floor_spawn": {},
    "floor_clear": {},
    "revive": {},
    "mag_set": {},
    "mag_feed": {},
}


def controls(op, fields, timeout=90):
    body = {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 5,
                                          "input": {"session_id": SID, "op": op, **fields}}}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=data, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    started = time.time()
    try:
        result = json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")
        return {"status": "ok", "ms": round((time.time() - started) * 1000), "result": result}
    except Exception as exc:                                     # noqa: BLE001
        code = getattr(exc, "code", 0)
        detail = ""
        try:
            detail = exc.read().decode()[:300]
        except Exception:                                        # noqa: BLE001
            detail = str(exc)[:200]
        return {"status": "error:%s" % code if code else "error", "ms": round((time.time() - started) * 1000),
                "detail": detail}


def classify(op, outcome):
    if outcome["status"] != "ok":
        detail = outcome.get("detail", "")
        if "not been implemented" in detail or "Unsupported" in detail:
            return "unsupported"
        if "422" in outcome["status"]:
            return "rejected"
        return outcome["status"]
    result = outcome.get("result") or {}
    if isinstance(result, dict) and (result.get("error") or result.get("ok") is False):
        return "failed"
    return "ok"


def run(op, gate=True):
    if gate and op in BENIGN + DESTRUCTIVE and pso_operator.operator_active():
        return {"op": op, "classification": "skipped", "reason": "operator is playing"}
    outcome = controls(op, ARGS.get(op, {}))
    return {"op": op, "classification": classify(op, outcome), "ms": outcome.get("ms"),
            "detail": str(outcome.get("detail") or outcome.get("result"))[:400]}


def main():
    include_destructive = "--include-destructive" in sys.argv
    rows = []
    print("=== read-only ops")
    for op in READ_ONLY:
        row = run(op, gate=False)
        print(f"  {op:<20} {row['classification']:<12} {row.get('detail', '')[:110]}")
        rows.append(row)
    print("=== benign mutating ops")
    for op in BENIGN:
        row = run(op)
        print(f"  {op:<20} {row['classification']:<12} {row.get('detail', '')[:110]}")
        rows.append(row)
    if include_destructive:
        print("=== destructive ops (explicitly requested)")
        for op in DESTRUCTIVE:
            row = run(op)
            print(f"  {op:<20} {row['classification']:<12} {row.get('detail', '')[:110]}")
            rows.append(row)
            if op in ("floor_warp", "boss_warp") and row["classification"] == "ok":
                time.sleep(8)                                    # let the area load before the next op
    counts = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    print("\nsummary:", counts)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump({"session": SID, "rows": rows, "summary": counts}, handle, indent=1)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
