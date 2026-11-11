"""Fill EVERY weapon slot with one usable weapon.

The operator's rule: whatever weapon is given must end up in all five weapon slots, replacing the ones that were there. Two facts from the live
game drive this:

  * `multi_equip` takes the SLOT of a copy (an item id returns 422), so one call per copy equips it;
  * a weapon whose requirement the character cannot meet is useless when equipped - the AXE needs ATP 800 and the character has 410, which
    drops the effective ATP to 210 and shows "ATP Needed: 800" in red.

So this picks a weapon the character CAN use from the inventory (or gives one), then equips every copy of it.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S


def inventory():
    reply = S.controls("list", {}, timeout=40)
    return (reply.get("inventory") if isinstance(reply, dict) else reply) or []


def show(rows, label):
    equipped = [row for row in rows if row.get("equipped")]
    weapons = [row for row in rows if str(row.get("code", "")).startswith("00")]
    print(f"{label}: {len(rows)} rows | equipped {len(equipped)} | weapons {len(weapons)} "
          f"(equipped {len([w for w in weapons if w.get('equipped')])})")
    for row in rows:
        mark = "E" if row.get("equipped") else " "
        print(f"   [{mark}] slot {row.get('slot')} {row.get('name')!r} {row.get('code')}")
    return weapons


rows = inventory()
weapons = show(rows, "current")

# prefer a Saber (0 ATP requirement) because it is usable at any level; otherwise take the first non-equipped weapon
sabers = [row for row in weapons if str(row.get("code")) == "000100"]
candidates = sabers or [row for row in weapons if not row.get("equipped")]
print(f"\nchosen weapon family: {candidates[0].get('name') if candidates else 'none'} "
      f"({len(candidates)} copies in the inventory)")

# make sure there are at least five copies
if len(candidates) < 5:
    need = 5 - len(candidates)
    try:
        reply = S.controls("give", {"code": "000100", "count": need}, timeout=60)
        print(f"give {need} Saber(s): {json.dumps(reply)[:160]}")
    except Exception as exc:                                      # noqa: BLE001
        print("give refused:", str(exc)[:110])
    time.sleep(0.6)
    rows = inventory()
    weapons = show(rows, "after give")
    candidates = [row for row in weapons if str(row.get("code")) == "000100"]

# equip each copy that is not yet equipped, one call per slot
for row in candidates:
    if row.get("equipped"):
        continue
    try:
        reply = S.controls("multi_equip", {"target": str(row.get("slot")), "on": True}, timeout=60)
        message = reply.get("message") if isinstance(reply, dict) else str(reply)[:60]
    except Exception as exc:                                      # noqa: BLE001
        message = f"refused {str(exc)[:80]}"
    print(f"   equip slot {row.get('slot')}: {message}")
    time.sleep(0.35)

rows = inventory()
equipped_weapons = [row for row in rows if row.get("equipped") and str(row.get("code", "")).startswith("00")]
print(f"\nRESULT: {len(equipped_weapons)} weapons equipped "
      f"({', '.join(sorted({str(r.get('name')) for r in equipped_weapons}))})")
