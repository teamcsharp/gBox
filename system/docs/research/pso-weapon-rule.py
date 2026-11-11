"""Enforce the operator's weapon rule continuously: every weapon slot holds the newest weapon, nothing else.

The rotation (`randomized`, every 120 s) gives ONE new weapon and equips it, which leaves the previous weapons stacked in the other slots. This
script keeps the rule true:

  1. read the inventory and pick the **newest weapon family** - the code whose copies are fewest, which is the one just given;
  2. top the copies up to five;
  3. `multi_equip on=true` for every copy, so all five weapon slots hold it (equip_any is on, so a high requirement cannot block it);
  4. `multi_equip on=false` for every *other* equipped weapon, clearing the leftovers.

Run with `--loop` to re-apply after each rotation.

Usage:
  python weapon_rule.py            one pass
  python weapon_rule.py --loop     keep enforcing, every 120 s
"""
import json
import sys
import time
from collections import Counter

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

LOG = r"D:\gBox\pso-ds\weapon_rule.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def inventory():
    reply = S.controls("list", {}, timeout=40)
    return (reply.get("inventory") if isinstance(reply, dict) else reply) or []


def weapons(rows):
    return [row for row in rows if str(row.get("code", "")).startswith("00")]


def enforce():
    try:
        S.controls("equip_any", {"on": True}, timeout=40)
    except Exception:                                            # noqa: BLE001
        pass
    rows = inventory()
    all_weapons = weapons(rows)
    if not all_weapons:
        log("no weapons in the inventory")
        return 0
    counts = Counter(str(row.get("code")) for row in all_weapons)
    # the newest family is the one with the fewest copies, ignoring the starter Saber unless it is the only option
    candidates = {code: count for code, count in counts.items() if code != "000100"} or counts
    keep = min(candidates, key=lambda code: candidates[code])
    name = next(row.get("name") for row in all_weapons if str(row.get("code")) == keep)
    log(f"target weapon {name} ({keep}) - inventory {dict(counts)}")

    copies = [row for row in all_weapons if str(row.get("code")) == keep]
    if len(copies) < 5:
        try:
            reply = S.controls("give", {"code": keep, "count": 5 - len(copies)}, timeout=60)
            log(f"  give {5 - len(copies)} more: {json.dumps(reply)[:120]}")
        except Exception as exc:                                  # noqa: BLE001
            log(f"  give refused: {str(exc)[:90]}")
        time.sleep(0.5)
        copies = [row for row in weapons(inventory()) if str(row.get("code")) == keep]

    for row in copies:
        if row.get("equipped"):
            continue
        try:
            reply = S.controls("multi_equip", {"target": str(row.get("slot")), "on": True}, timeout=60)
            log(f"  equip slot {row.get('slot')}: {reply.get('message') if isinstance(reply, dict) else reply}")
        except Exception as exc:                                  # noqa: BLE001
            log(f"  equip slot {row.get('slot')} refused: {str(exc)[:80]}")
        time.sleep(0.25)

    for row in weapons(inventory()):
        if str(row.get("code")) == keep or not row.get("equipped"):
            continue
        try:
            reply = S.controls("multi_equip", {"target": str(row.get("slot")), "on": False}, timeout=60)
            log(f"  unequip slot {row.get('slot')} ({row.get('name')}): "
                f"{reply.get('message') if isinstance(reply, dict) else reply}")
        except Exception as exc:                                  # noqa: BLE001
            log(f"  unequip slot {row.get('slot')} refused: {str(exc)[:80]}")
        time.sleep(0.25)

    final = [row for row in weapons(inventory()) if row.get("equipped")]
    codes = {str(row.get("code")) for row in final}
    log(f"  result: {len(final)} equipped {[(r.get('slot'), r.get('name')) for r in final]} "
        f"single family {codes == {keep}}")
    return 0 if codes == {keep} else 3


if __name__ == "__main__":
    if "--loop" in sys.argv:
        log("=== weapon rule loop (every 120 s)")
        while True:
            try:
                enforce()
            except Exception as exc:                              # noqa: BLE001
                log(f"pass failed: {type(exc).__name__}: {str(exc)[:120]}")
            time.sleep(120)
    raise SystemExit(enforce())
