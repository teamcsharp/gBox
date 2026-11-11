"""Choose the weapon type for the situation, from the researched weapon rules.

The Ephinea weapons reference gives three categories and a clear intent for each type:

  * **Sword / Partisan / Slicer** - wide melee arcs, for several enemies in front;
  * **Saber / Dagger** - fast single-target melee, for one tough enemy close in;
  * **Handgun / Rifle / Mechgun / Shot** - ranged, and the only answer to a **flying** enemy, which melee cannot reach;
  * **Cane / Rod / Wand** - technique weapons, which boost the techniques the bot already casts with B.

The bot's earlier failures were partly situational: it kept a melee weapon against enemies it could not reach, and never switched when a group
appeared. This reads the live entity table and equips the type the situation calls for, using the plane's item operations (which work without the
game being focused, since they are not keyboard input).

Weapon selection is by inventory code class, measured earlier:
  0001 Saber   0002 Sword   0003 Dagger  0004 Partisan  0005 Slicer
  0006 Handgun 0007 Rifle   0008 Mechgun 0009 Shot
  000b Rod     000c Wand
"""
import json
import math
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS, HP = 0x8050D460, 256, 0x38, 0x32C
PLAYER = 0x8050EA10
LOG = r"D:\gBox\pso-ds\weapon_advisor.log"

CLASSES = {
    "0001": "Saber", "0002": "Sword", "0003": "Dagger", "0004": "Partisan", "0005": "Slicer",
    "0006": "Handgun", "0007": "Rifle", "0008": "Mechgun", "0009": "Shot",
    "000b": "Rod", "000c": "Wand",
}
WIDE = {"0002", "0004", "0005"}
FAST = {"0001", "0003"}
RANGED = {"0006", "0007", "0008", "0009"}
TECH = {"000b", "000c"}


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def player():
    pointer = int.from_bytes(S.read_memory(PLAYER, 4), "big")
    blob = S.read_memory(pointer + POS, 12)
    return struct.unpack(">fff", blob) if len(blob) == 12 else None


def enemies(limit=80.0):
    me = player()
    if me is None:
        return []
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    out = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 32).split(b"\x00")[0].decode("ascii", "replace")
            if not name.startswith(("TObjEne", "TEne", "TBoss")):
                continue
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            x, y, z = struct.unpack(">fff", blob[POS:POS + 12])
            hp = struct.unpack(">H", blob[HP:HP + 2])[0]
        except Exception:                                        # noqa: BLE001
            continue
        if hp <= 0:
            continue
        distance = math.dist((me[0], me[2]), (x, z))
        if distance <= limit:
            out.append({"class": name, "x": x, "y": y, "z": z, "hp": hp, "distance": distance})
    return sorted(out, key=lambda row: row["distance"])


def inventory():
    reply = S.controls("list", {}, timeout=40)
    return (reply.get("inventory") if isinstance(reply, dict) else reply) or []


def choose(targets, me):
    """Which weapon class the situation calls for."""
    if not targets:
        return None, "nothing to fight"
    nearest = targets[0]
    close = [row for row in targets if row["distance"] <= 14.0]
    flying = any(abs(row["y"] - me[1]) > 6.0 for row in targets)
    if len(close) >= 3:
        return WIDE, f"{len(close)} enemies in melee range -> wide weapon"
    if flying:
        return RANGED, "enemy is well above the player -> ranged weapon (melee cannot reach)"
    if nearest["distance"] > 12.0:
        return RANGED, f"nearest enemy {nearest['distance']:.0f} units away -> ranged weapon"
    if len(close) == 2:
        return WIDE, "two enemies in range -> wide weapon"
    return FAST, "single enemy in range -> fast single-target weapon"


def equip_class(wanted):
    """Equip the first inventory weapon of one of the wanted classes. Returns the name or None."""
    rows = inventory()
    for row in rows:
        code = str(row.get("code", ""))
        if code[:4] in wanted:
            try:
                reply = S.controls("multi_equip", {"target": str(row.get("slot")), "on": True}, timeout=60)
            except Exception as exc:                              # noqa: BLE001
                log(f"  equip {row.get('name')} refused: {str(exc)[:70]}")
                continue
            for other in rows:
                other_code = str(other.get("code", ""))
                if other is row or other_code[:4] not in CLASSES or not other.get("equipped"):
                    continue
                try:
                    S.controls("multi_equip", {"target": str(other.get("slot")), "on": False}, timeout=60)
                except Exception:                                # noqa: BLE001
                    pass
            return row.get("name")
    return None


if __name__ == "__main__":
    me = player()
    targets = enemies()
    log(f"player {tuple(round(v, 1) for v in me)} | enemies {len(targets)}")
    for row in targets[:5]:
        log(f"  {row['class']} hp {row['hp']} at {row['distance']:.0f} units, height {row['y'] - me[1]:+.1f}")
    wanted, reason = choose(targets, me)
    log(f"advice: {reason}")
    if wanted:
        names = ", ".join(CLASSES.get(code, code) for code in sorted(wanted))
        log(f"  weapon classes for this: {names}")
        equipped = equip_class(wanted)
        log(f"  equipped: {equipped}")
    rows = inventory()
    log("  current weapons: " + json.dumps(
        [{"name": r.get("name"), "code": r.get("code"), "equipped": r.get("equipped")}
         for r in rows if str(r.get("code", ""))[:4] in CLASSES]))
