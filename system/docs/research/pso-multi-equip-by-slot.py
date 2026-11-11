"""Try multi_equip with target as the SLOT of an unequipped copy, then report what the inventory actually shows."""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S


def inventory():
    reply = S.controls("list", {}, timeout=40)
    if isinstance(reply, dict):
        return reply.get("inventory") or []
    return reply if isinstance(reply, list) else []


def report(label):
    rows = inventory()
    equipped = [row for row in rows if row.get("equipped")]
    weapons = [row for row in rows if str(row.get("code", "")).startswith("00")]
    print(f"{label}: {len(rows)} rows | equipped {len(equipped)} | weapons {len(weapons)} "
          f"(equipped weapons {len([w for w in weapons if w.get('equipped')])})")
    for row in rows[:10]:
        mark = "E" if row.get("equipped") else " "
        print(f"   [{mark}] slot {row.get('slot')} {row.get('name')!r} {row.get('code')}")
    return rows


report("start")
for slot in ("5", "6", "7"):
    try:
        reply = S.controls("multi_equip", {"target": slot, "on": True}, timeout=60)
        text = json.dumps(reply)[:200]
    except Exception as exc:                                      # noqa: BLE001
        text = f"refused {str(exc)[:90]}"
    print(f"\nmulti_equip target={slot}: {text}")
    time.sleep(0.5)
    rows = inventory()
    equipped_weapons = [r for r in rows if r.get("equipped") and str(r.get("code", "")).startswith("00")]
    print(f"   -> equipped weapons now: {len(equipped_weapons)}")
    if len(equipped_weapons) >= 5:
        print("   FIVE OR MORE WEAPONS EQUIPPED")
        break
report("end")
