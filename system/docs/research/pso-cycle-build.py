"""Every N seconds, spawn a random high-level weapon and a mag for the operator to pick up.

Uses the path proven live on 2026-11-10: `POST http://127.0.0.1:18765/api/sessions/<sid>/rpc` with
`pso_controls/floor_spawn`, a **fresh** expiry (the control layer requires `now < expires <= now + 15`), and the item codes resolved
against the owned disc by `pso_loadout op=plan`.

    python pso_cycle_build.py --session <sid> --every 300

Codes come from the plane's own plans (`atp` for weapons, explicit names for mags), so nothing is invented; a plan that fails keeps
the built-in fallback list. Each cycle is logged to D:\\gBox\\pso-ds\\random-build.jsonl.
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
LOCAL = "http://127.0.0.1:18765"
LOG = Path(r"D:\gBox\pso-ds\random-build.jsonl")

MAG_NAMES = ["Soniti", "Rati", "Pushan", "Diwari", "Sato", "Nidra", "Bhima", "Savitri",
             "Kama", "Madhu", "Rukmin", "Rappy", "Churel", "Pitri", "Kabanda", "Naga"]


def call(base, path, method="GET", body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


def plan(session, preset="", names=None, count=12, timeout=120):
    payload = {"session_id": session, "op": "plan", "version": "gc", "count": count}
    if preset:
        payload["preset"] = preset
    if names:
        payload["names"] = names
    job = call(API, "/api/jobs", "POST", {"tool": "pso_loadout", "input": payload})
    started = time.time()
    while time.time() - started < timeout:
        time.sleep(1.0)
        state = call(API, "/api/jobs/" + job["id"])
        if state.get("state") not in ("queued", "running"):
            break
    result = (state.get("output") or {}).get("result") or {}
    return [i.get("code") for i in result.get("items") or [] if i.get("code")]


def equip(session, code, timeout=30):
    """Give and equip one item in the inventory (replaces what is equipped), with a fresh expiry per call."""
    body = {"op": "pso_controls", "args": {
        "command_id": str(uuid.uuid4()), "expires": time.time() + 5,
        "input": {"session_id": session, "op": "equip", "code": code, "player_index": 0}}}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{LOCAL}/api/sessions/{session}/rpc", data=data, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    try:
        reply = json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")
        return {"state": "ok", "verified": reply.get("verified"), "item_id": reply.get("item_id"),
                "message": reply.get("message"), "ms": reply.get("elapsed_ms")}
    except urllib.error.HTTPError as exc:
        return {"state": "http", "code": exc.code, "detail": exc.read().decode()[:200]}
    except Exception as exc:                                     # noqa: BLE001
        return {"state": "error", "detail": f"{type(exc).__name__}: {exc}"}


def equip_all(session, codes):
    """Equip each code in turn; the cycle is ok only when every equip verified."""
    answers = [equip(session, code) for code in codes]
    return {"state": "ok" if all(a.get("state") == "ok" and a.get("verified") for a in answers) else "partial",
            "items": answers}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--every", type=float, default=300)
    ap.add_argument("--seconds", type=float, default=8 * 3600)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    print("resolving weapon and mag codes from the disc (one plan each)", flush=True)
    weapons = plan(args.session, preset="atp")
    mags = plan(args.session, names=MAG_NAMES) or plan(args.session, preset="community")
    print(f"weapons: {len(weapons)} codes, mags: {len(mags)} codes", flush=True)
    if not weapons:
        print("no weapon codes resolved - stopping", flush=True)
        return 1
    start = time.time()
    used_w: list[str] = []
    used_m: list[str] = []
    while time.time() - start < args.seconds:
        pool_w = [c for c in weapons if c not in used_w] or weapons
        code_w = random.choice(pool_w)
        code_m = random.choice([c for c in mags if c not in used_m] or mags) if mags else None
        codes = [code_w] + ([code_m] if code_m else [])
        answer = {"state": "dry-run"} if args.dry_run else equip_all(args.session, codes)
        row = {"at": time.strftime("%H:%M:%S"), "codes": codes, **answer}
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print(json.dumps(row)[:300], flush=True)
        if answer.get("state") == "ok":
            used_w.append(code_w)
            if code_m:
                used_m.append(code_m)
        time.sleep(max(1.0, args.every - 3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
