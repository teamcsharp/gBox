"""Apply the operator's build to a freshly loaded character.

1. unlimited TP: max + current set high and then frozen so the bar cannot drain
2. HP safety: current HP written to max and frozen (the same write path that healed 8/54 before)
3. combat: crit + always_hit, so every hit lands and crits
4. weapons: give 4 extra copies of the equipped weapon's code and multi_equip each so the same weapon is equipped FIVE times

Everything goes through the desktop session API (port 18765), which is the channel that actually reaches the emulator.
"""
import json
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S

TP, TP_MAX = 0x32E, 0x2BA
HP, HP_MAX = 0x32C, 0x2B8
BIG_TP = 999


def actor():
    raw = S.read_memory(0x8050EA10, 4)
    return int.from_bytes(raw, "big") if raw else 0


def read_u16(address):
    blob = S.read_memory(address, 2)
    return struct.unpack(">H", blob)[0] if len(blob) == 2 else None


def job(tool, payload, timeout=90):
    return S.job(tool, payload, timeout=timeout)


def write_u16(address, value):
    return job("write_memory", {"session_id": S.session_id(), "address": address, "hex_bytes": struct.pack(">H", value).hex()})


def freeze_u16(address, value, interval_ms=50):
    return job("freeze_memory", {"session_id": S.session_id(), "address": address,
                                 "hex_bytes": struct.pack(">H", value).hex(), "enabled": True,
                                 "interval_ms": interval_ms})


def controls(op, fields=None):
    try:
        return S.controls(op, fields, timeout=90)
    except Exception as exc:                                     # noqa: BLE001
        return {"error": getattr(exc, "code", 0),
                "detail": getattr(exc, "read", lambda: b"")().decode()[:200] if hasattr(exc, "read") else str(exc)[:120]}


def main():
    pointer = actor()
    if not pointer:
        print("no player yet")
        return 2
    print(f"player {pointer:#x}")
    print("tp before:", read_u16(pointer + TP), "/", read_u16(pointer + TP_MAX))
    print(" hp before:", read_u16(pointer + HP), "/", read_u16(pointer + HP_MAX))
    print("set tp:", write_u16(pointer + TP_MAX, BIG_TP)[0], write_u16(pointer + TP, BIG_TP)[0])
    hpmax = read_u16(pointer + HP_MAX) or 40
    print("set hp:", write_u16(pointer + HP, hpmax)[0])
    print("freeze tp:", freeze_u16(pointer + TP, BIG_TP)[0])
    print("freeze hp:", freeze_u16(pointer + HP, hpmax, interval_ms=120)[0])
    print("after tp:", read_u16(pointer + TP), " hp:", read_u16(pointer + HP))
    print("crit:", json.dumps(controls("crit", {}).get("crit_always")))
    print("always_hit:", json.dumps(controls("always_hit", {}).get("always_hit")))
    print("equip_any:", json.dumps(controls("equip_any", {}).get("equip_any")))
    inventory = controls("list", {})
    rows = inventory.get("inventory") or []
    equipped_weapons = [r for r in rows if r.get("equipped") and r.get("name") not in (None, "") and
                        any(token in str(r.get("name")).upper() for token in
                            ("SABER", "BLADE", "KNUCKLE", "SWORD", "J-CUTTER", "CUTTER", "CLAW", "DAGGER", "RIFLE",
                             "HANDGUN", "GUN", "ROD", "WAND", "CANE", "PARTISAN", "SHOT", "MECH", "LAUNCHER", "CARD"))]
    if not equipped_weapons:
        print("no equipped weapon found; skipping the 5x stack")
        return 0
    weapon = equipped_weapons[0]
    code = weapon.get("code")
    print(f"weapon to stack x5: slot {weapon.get('slot')} {code} {weapon.get('name')}")
    for index in range(4):
        created = controls("give", {"code": code, "count": 1})
        print(f"  give copy {index + 2}: {json.dumps(created)[:120]}")
        time.sleep(0.3)
    rows = (controls("list", {}).get("inventory") or [])
    same = [r for r in rows if r.get("code") == code]
    print(f"copies of {code} in the pack: {len(same)}")
    for row in same:
        result = controls("multi_equip", {"target": str(row.get("slot")), "on": True})
        print(f"  multi_equip slot {row.get('slot')}: {str(result.get('error') or result.get('message'))[:80]}")
        time.sleep(0.25)
    final = controls("list", {}).get("inventory") or []
    equipped = [r for r in final if r.get("equipped")]
    print(f"equipped now: {len(equipped)}")
    for row in equipped:
        print(f"  {row.get('code')} {row.get('name')}")
    print("stats:", json.dumps(controls("status", {}).get("stats"))[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
