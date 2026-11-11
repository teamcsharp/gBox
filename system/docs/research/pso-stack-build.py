"""Operator build: unlimited TP, then stack EVERY weapon/armor/shield/unit with multi_equip so the character effectively has all of
them equipped at once (stats stack; PSO still draws one active weapon).

multi_equip runs an item's own on-equip path without unequipping the slot's current item, so calling it for every compatible item leaves
them all in the equipped set. Verified by counting equipped items before/after and reading the stacked ATP/ATA/DFP.
"""
import json
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import pso_unlimited as unlimited                                  # noqa: E402

TOKEN = open(r"C:\_tools\gBox\system\gbox-data\api_token").read().strip()
API = "http://127.0.0.1:8765"
SID = "e731ee594dde4a89-cae9dad929a34d17"


def controls(op, fields, timeout=90):
    body = {"op": "pso_controls", "args": {"command_id": str(uuid.uuid4()), "expires": time.time() + 5,
                                          "input": {"session_id": SID, "op": op, **fields}}}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}/api/sessions/{SID}/rpc", data=data, method="POST",
                                 headers={"authorization": "Bearer " + TOKEN, "x-gbox-actor": "agent",
                                          "content-type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")
    except Exception as exc:                                     # noqa: BLE001
        return {"error": str(exc)[:200]}


def inventory():
    result = controls("list", {})
    return result.get("inventory") or result.get("items") or []


def status():
    result = controls("status", {})
    return result.get("stats") or {}


def main():
    print("=== unlimited TP")
    print(json.dumps(unlimited.apply(), indent=1))
    print("\n=== stacking every equippable item")
    rows = inventory()
    print(f"inventory items: {len(rows)}")
    for row in rows:
        print(f"  slot {row.get('slot')} {row.get('code')} {row.get('name')} equipped={row.get('equipped')}")
    before = status()
    print("stats before:", before)
    targets = []
    for row in rows:
        code = str(row.get("code") or "")
        name = str(row.get("name") or "")
        slot = row.get("slot")
        if row.get("equipped"):
            continue
        # weapons, frames, barriers, units and mags can all stack through their own on-equip path
        if any(token in name.upper() for token in ("SABER", "KNUCKLE", "SWORD", "RIFLE", "GUN", "HANDGUN", "CLAW", "DAGGER",
                                                   "PARTISAN", "ROD", "WAND", "CANE", "SHOT", "MECH", "LAUNCHER", "CARD")):
            targets.append(slot)
        elif row.get("equipped") is False and row.get("name") not in (None, ""):
            targets.append(slot)
    print("targets to stack:", targets)
    for slot in targets:
        result = controls("multi_equip", {"target": slot, "on": True})
        summary = {k: result.get(k) for k in ("changed", "atp", "ata", "dfp", "verified", "error")}
        equipped_count = len(result.get("equipped_now") or [])
        print(f"  slot {slot}: equipped_now={equipped_count} {summary}")
    after = status()
    print("stats after:", after)
    final = inventory()
    equipped = [r for r in final if r.get("equipped")]
    print(f"\nequipped items now: {len(equipped)}")
    for row in equipped:
        print(f"  {row.get('code')} {row.get('name')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
