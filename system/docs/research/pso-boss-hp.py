"""CP18 observation: record a boss's HP from RAM until it reaches zero.

The accept test for CP18 is "the boss's HP reaches 0 from RAM, with both players alive". The player actor keeps HP at +0x32C and its maximum
at +0x2B8, and enemies share the same base actor class, so this reads those fields for the boss entity the whole fight and writes the series
to a file. A row is appended every second, plus a row whenever the value changes, so the moment it hits zero is timestamped.

If the actor layout differs for the boss, `--scan` lists candidate offsets whose u16 decreases while the fight is under way, which locates
the real field without guessing.

Usage:
  python boss_hp.py TBoss1Dragon 180        watch for up to 180 s
  python boss_hp.py TBoss1Dragon --scan     list u16 offsets that are falling
"""
import json
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import learn_live as L                                             # noqa: E402
import session as S                                                # noqa: E402

TABLE, MAX_ENTRIES, POS = 0x8050D460, 256, 0x38
HP, HP_MAX = 0x32C, 0x2B8
OUT = r"D:\gBox\pso-ds\boss-hp.jsonl"
LOG = r"D:\gBox\pso-ds\boss_hp.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def boss(fragment):
    raw = S.read_memory(TABLE, MAX_ENTRIES * 4)
    for index in range(MAX_ENTRIES):
        pointer = int.from_bytes(raw[index * 4:index * 4 + 4], "big")
        if not (0x80000000 <= pointer < 0x81800000):
            continue
        try:
            name_pointer = int.from_bytes(S.read_memory(pointer, 4), "big")
            if not (0x80000000 <= name_pointer < 0x81800000):
                continue
            name = S.read_memory(name_pointer, 28).split(b"\x00")[0].decode("ascii", "replace")
        except Exception:                                        # noqa: BLE001
            continue
        if fragment in name:
            blob = S.read_memory(pointer, 0x340)
            if len(blob) < 0x340:
                continue
            return {"index": index, "class": name, "pointer": pointer, "blob": blob,
                    "x": round(struct.unpack(">f", blob[POS:POS + 4])[0], 1),
                    "z": round(struct.unpack(">f", blob[POS + 8:POS + 12])[0], 1)}
    return None


def scan(fragment, seconds=6.0):
    first = boss(fragment)
    if first is None:
        log(f"no entity matching {fragment}")
        return 2
    log(f"boss {first['class']} at {hex(first['pointer'])} ({first['x']},{first['z']})")
    time.sleep(seconds)
    second = boss(fragment)
    if second is None or second["pointer"] != first["pointer"]:
        log("boss went away before the second sample")
        return 2
    falling = []
    for offset in range(0, 0x340 - 1, 2):
        a = struct.unpack(">H", first["blob"][offset:offset + 2])[0]
        b = struct.unpack(">H", second["blob"][offset:offset + 2])[0]
        if 0 < b < a <= 20000:
            falling.append({"offset": hex(offset), "before": a, "after": b})
    log(f"u16 offsets that fell in {seconds:.0f}s: {json.dumps(falling)[:400]}")
    if not falling:
        log("nothing fell - the boss may not have been damaged in that window")
    return 0


def watch(fragment, seconds=180.0):
    path_out = open(OUT, "a", encoding="utf-8")                       # noqa: SIM115
    log(f"=== watching {fragment} for {seconds:.0f}s into {OUT}")
    started = time.time()
    previous = None
    while time.time() - started < seconds:
        current = boss(fragment)
        if current is None:
            if previous is not None:
                log("boss entity is gone")
                path_out.write(json.dumps({"t": round(time.time(), 3), "gone": True}) + "\n")
                path_out.flush()
                path_out.close()
                return 0
            time.sleep(1.0)
            continue
        hp = struct.unpack(">H", current["blob"][HP:HP + 2])[0]
        hpmax = struct.unpack(">H", current["blob"][HP_MAX:HP_MAX + 2])[0]
        row = {"t": round(time.time(), 3), "class": current["class"], "hp": hp, "hpmax": hpmax,
               "x": current["x"], "z": current["z"]}
        if previous is None or hp != previous:
            log(f"  {current['class']} hp {hp}/{hpmax}")
            previous = hp
        path_out.write(json.dumps(row) + "\n")
        path_out.flush()
        if hp == 0 and hpmax:
            log(f"BOSS HP REACHED 0 ({current['class']}) - CP18 accept condition")
            player = L.player()
            log(f"  player alive check: hp {None if player is None else player['hp']}")
            path_out.close()
            return 0
        time.sleep(1.0)
    path_out.close()
    log("watch window ended without reaching 0")
    return 2


if __name__ == "__main__":
    fragment = sys.argv[1] if len(sys.argv) > 1 else "TBoss"
    if "--scan" in sys.argv:
        raise SystemExit(scan(fragment))
    raise SystemExit(watch(fragment, float(sys.argv[2]) if len(sys.argv) > 2 else 180.0))
