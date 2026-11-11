"""Find a firearm by scanning weapon class codes and reading the names the game returns.

`000200` turned out to be a Sword, so the class byte is not what I assumed. This gives one item from a spread of class codes and reads back the
name from the inventory, then reports which are guns so one can be equipped for ranged combat against the circling wolves.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

CODES = [f"00{c:02x}00" for c in range(1, 16)]


def inventory():
    reply = S.controls("list", {}, timeout=40)
    return (reply.get("inventory") if isinstance(reply, dict) else reply) or []


before = {row.get("id") for row in inventory()}
print(f"inventory rows before: {len(before)}")
for code in CODES:
    try:
        reply = S.controls("give", {"code": code, "count": 1}, timeout=45)
        ok = bool((reply or {}).get("created"))
    except Exception as exc:                                      # noqa: BLE001
        ok = f"refused {str(exc)[:60]}"
    print(f"  give {code}: {ok}")
    time.sleep(0.2)

rows = inventory()
new = [row for row in rows if row.get("id") not in before]
print(f"\nnew items ({len(new)}):")
for row in new:
    print(f"  slot {row.get('slot')} {str(row.get('name')):<24} code {row.get('code')}")
guns = [row for row in new if any(word in str(row.get("name", "")).lower()
                                  for word in ("handgun", "rifle", "gun", "shot", "launcher", "mechgun", "cannon"))]
print(f"\nguns found: {[(r.get('name'), r.get('code'), r.get('slot')) for r in guns]}")
