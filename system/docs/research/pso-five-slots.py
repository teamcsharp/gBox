"""Equip one weapon in all five slots, with no leftover sabres.

The operator's requirement: when the equipped weapon is replaced, it must be equipped five times, so the other weapon slots hold the SAME
item rather than the old sabres.

The GameCube plane supports exactly the pieces needed:

  * `give` accepts `count` up to 20 - it creates real inventory items through the game's own create-item routine;
  * `multi_equip` with `target` equips one item into the weapon slots (verified earlier: "Weapon effects stacked");
  * `list` returns the live inventory in menu order, so the equipped weapon's code can be identified instead of assumed.

Sequence: read `list` -> take the equipped weapon's code (or the one passed with --code) -> give `count` copies -> multi_equip -> read `list`
again and report how many copies of that code are equipped.

Usage:
  python five_slots.py                 dry run: report what it would do
  python five_slots.py --apply         do it
  python five_slots.py --code 000100 --apply    use a specific weapon code
"""
import json
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S


def log(line):
    print(line, flush=True)


def inventory():
    try:
        reply = S.controls("list", {})
    except Exception as exc:                                      # noqa: BLE001
        log(f"  list failed: {str(exc)[:100]}")
        return []
    if isinstance(reply, dict):
        for key in ("items", "inventory", "rows"):
            if isinstance(reply.get(key), list):
                return reply[key]
        return [reply]
    return reply if isinstance(reply, list) else []


def equipped_weapons(rows):
    """Rows that look like weapons and are equipped."""
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "")
        if len(code) != 6 or not code.startswith("00"):
            continue
        if row.get("equipped"):
            out.append(row)
    return out


def main(argv):
    want = argv[argv.index("--code") + 1] if "--code" in argv else None
    apply_it = "--apply" in argv
    rows = inventory()
    log(f"inventory rows: {len(rows)}")
    weapons = equipped_weapons(rows)
    for row in weapons[:8]:
        log(f"  equipped weapon: slot {row.get('slot')} code {row.get('code')} id {row.get('id')}")
    code = want or (weapons[0]["code"] if weapons else None)
    if not code:
        log("no equipped weapon found and no --code given")
        return 2
    log(f"target weapon code: {code}")
    if not apply_it:
        log("dry run: would give 5 copies and multi_equip them; pass --apply to do it")
        return 0
    reply = S.controls("give", {"code": code, "count": 5})
    log(f"give x5: {json.dumps(reply)[:220] if reply else 'no reply'}")
    reply = S.controls("multi_equip", {"target": "0", "on": True})
    log(f"multi_equip: {json.dumps(reply)[:220] if reply else 'no reply'}")
    rows = inventory()
    same = [row for row in rows if str(row.get("code")) == code and row.get("equipped")]
    log(f"equipped copies of {code} after: {len(same)}")
    for row in same:
        log(f"  slot {row.get('slot')} id {row.get('id')}")
    return 0 if len(same) >= 5 else 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
