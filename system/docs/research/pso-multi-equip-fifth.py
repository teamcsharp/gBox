import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S


def inv():
    reply = S.controls("list", {}, timeout=40)
    return (reply.get("inventory") if isinstance(reply, dict) else reply) or []


for slot in ("8",):
    try:
        reply = S.controls("multi_equip", {"target": slot, "on": True}, timeout=60)
        print("multi_equip slot", slot, "->", json.dumps(reply)[:170])
    except Exception as exc:                                      # noqa: BLE001
        print("slot", slot, "refused", str(exc)[:90])
    time.sleep(0.5)

rows = inv()
equipped = [row for row in rows if row.get("equipped")]
weapons = [row for row in equipped if str(row.get("code", "")).startswith("00")]
print()
print("equipped total:", len(equipped), "| equipped WEAPONS:", len(weapons))
for row in rows:
    print(("  [E] " if row.get("equipped") else "  [ ] ") + f"slot {row.get('slot')} {row.get('name')}")
