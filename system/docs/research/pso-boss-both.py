"""CP18 observation for BOTH players: watch the boss's HP and every player's HP in one series.

The accept test is "the boss's HP reaches 0 from RAM, with both players alive". Last round's tool watched player slot 0 only, which leaves
half the condition unmeasured in co-op. This enumerates every `TObjPlayer` in the entity table, so the series carries each player's HP
alongside the boss's, and the moment the boss reaches 0 is stamped with all the players' HP at that instant.

Usage:
  python boss_both.py TBoss1Dragon 180
"""
import json
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
HP, HP_MAX = 0x32C, 0x2B8
OUT = r"D:\gBox\pso-ds\boss-both.jsonl"
LOG = r"D:\gBox\pso-ds\boss_both.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def actors():
    """Every entity's class, pointer and HP fields, from one table pass."""
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    rows = []
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 28).split(b"\x00")[0].decode("ascii", "replace")
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
        except Exception:                                        # noqa: BLE001
            continue
        rows.append({"index": index, "class": name, "pointer": pointer,
                     "hp": struct.unpack(">H", blob[HP:HP + 2])[0],
                     "hpmax": struct.unpack(">H", blob[HP_MAX:HP_MAX + 2])[0],
                     "x": round(struct.unpack(">f", blob[POS:POS + 4])[0], 1),
                     "z": round(struct.unpack(">f", blob[POS + 8:POS + 12])[0], 1)})
    return rows


def main(fragment="TBoss", seconds=180.0):
    handle = open(OUT, "a", encoding="utf-8")                         # noqa: SIM115
    log(f"=== watching boss '{fragment}' and every player for {seconds:.0f}s -> {OUT}")
    started = time.time()
    players_seen = set()
    last_boss_hp = None
    while time.time() - started < seconds:
        rows = actors()
        boss = next((row for row in rows if fragment in row["class"]), None)
        players = [row for row in rows if row["class"] == "TObjPlayer"]
        for player in players:
            players_seen.add(player["pointer"])
        if boss is None:
            if last_boss_hp is not None:
                log("boss entity gone")
                handle.write(json.dumps({"t": round(time.time(), 3), "gone": True,
                                         "players": [{k: p[k] for k in ("pointer", "hp", "hpmax")} for p in players]}) + "\n")
                handle.flush()
                handle.close()
                return 0
            time.sleep(1.0)
            continue
        record = {"t": round(time.time(), 3), "boss": {k: boss[k] for k in ("class", "hp", "hpmax", "x", "z")},
                  "players": [{"pointer": p["pointer"], "hp": p["hp"], "hpmax": p["hpmax"]} for p in players],
                  "player_count": len(players)}
        handle.write(json.dumps(record) + "\n")
        handle.flush()
        if boss["hp"] != last_boss_hp:
            log(f"  boss hp {boss['hp']}/{boss['hpmax']}  players alive: "
                f"{[p['hp'] for p in players]} (count {len(players)})")
            last_boss_hp = boss["hp"]
        if boss["hp"] == 0 and boss["hpmax"]:
            alive = [p for p in players if p["hp"] > 0]
            log(f"BOSS HP REACHED 0 ({boss['class']}); players with hp>0: {len(alive)} of {len(players)}")
            log(f"  accept condition 'both players alive': "
                f"{'MET' if len(players) >= 2 and len(alive) == len(players) else 'NOT MET (single player or a death)'}")
            handle.close()
            return 0
        time.sleep(1.0)
    handle.close()
    log(f"window ended; players seen: {len(players_seen)}, boss hp last {last_boss_hp}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "TBoss",
                          float(sys.argv[2]) if len(sys.argv) > 2 else 180.0))
