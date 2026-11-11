"""Every N seconds, give the operator a different high-level weapon and mag.

Uses gBox's own `pso_loadout` tool (`op=drop`), which resolves names against the owned disc's item database and applies them through
the verified live PSO channel - so nothing here invents item codes; an unknown name is refused by the plane, not equipped.

    python pso_random_build.py --session <sid> --every 300            # apply
    python pso_random_build.py --session <sid> --every 300 --dry-run  # only plan and log

Each cycle picks a weapon and a mag it has not used recently, logs the choice with the tool's answer to
`D:\\gBox\\pso-ds\\random-build.jsonl`, and never retries a failed mutation inside the same cycle.
"""
import argparse
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
BASE = "http://127.0.0.1:8765"
LOG = Path(r"D:\gBox\pso-ds\random-build.jsonl")

# GameCube-legal, high-tier equipment. The plane validates every name against the owned disc; anything it refuses is simply not
# equipped, so this list is a menu of candidates rather than a promise.
WEAPONS = [
    "Red Sword", "Chain Sawd", "Tsumikiri J-Sword", "Sealed J-Sword", "Frozen Shooter",
    "Spread Needle", "Holy Ray", "Bringer's Rifle", "Yasminkov 7000V", "Yasminkov 3000R",
    "Meteor Cudgel", "Monkey King Bar", "Black King Bar", "Double Cannon", "Girasole",
    "Lavis Cannon", "Sange & Yasha", "Demolition Comet", "Rainbow Baton", "Vjaya",
]
MAGS = [
    "Soniti", "Rati", "Pushan", "Diwari", "Sato", "Nidra", "Bhima", "Savitri",
    "Kama", "Madhu", "Rukmin", "Rappy", "Churel", "Pitri", "Kabanda", "Naga",
]


def call(path, method="GET", body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")


def pick(pool, used, count):
    fresh = [x for x in pool if x not in used] or list(pool)
    random.shuffle(fresh)
    return fresh[:count]


def drop(session, names, dry_run):
    job = call("/api/jobs", "POST", {"tool": "pso_loadout",
                                     "input": {"session_id": session, "op": "plan" if dry_run else "drop",
                                               "version": "gc", "names": names}})
    for _ in range(30):
        time.sleep(1.5)
        state = call("/api/jobs/" + job["id"])
        if state.get("state") not in ("queued", "running"):
            return state
    return {"state": "timeout"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--every", type=float, default=300)
    ap.add_argument("--per-cycle", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seconds", type=float, default=6 * 3600)
    args = ap.parse_args()
    used_weapons: list[str] = []
    used_mags: list[str] = []
    LOG.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    print(f"cycler up: every {args.every:.0f}s, {'DRY RUN' if args.dry_run else 'applying'}, session {args.session}", flush=True)
    while time.time() - start < args.seconds:
        weapons = pick(WEAPONS, used_weapons, args.per_cycle)
        mags = pick(MAGS, used_mags, args.per_cycle)
        names = [n for n in weapons + mags]
        started = time.time()
        answer = {}
        try:
            answer = drop(args.session, names, args.dry_run)
        except Exception as exc:                                  # noqa: BLE001
            answer = {"state": "error", "error": f"{type(exc).__name__}: {exc}"}
        row = {"at": time.strftime("%H:%M:%S"), "names": names, "dry_run": args.dry_run,
               "state": answer.get("state"), "error": str(answer.get("error"))[:200],
               "seconds": round(time.time() - started, 1)}
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        print(json.dumps(row)[:300], flush=True)
        if answer.get("state") == "succeeded":
            used_weapons.extend(weapons)
            used_mags.extend(mags)
            if len(used_weapons) > len(WEAPONS) - args.per_cycle:
                used_weapons.clear()
            if len(used_mags) > len(MAGS) - args.per_cycle:
                used_mags.clear()
        time.sleep(max(1.0, args.every - (time.time() - started)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
