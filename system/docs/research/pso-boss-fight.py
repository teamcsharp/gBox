"""Boss backup: keep attacking while the operator is not on the controller, and stop the moment they are.

The operator fights with the pad; this only acts when they have been idle for the full window (pso_input enforces that), then it presses
attack repeatedly and dodges periodically. It watches the entity table for the boss class and stops when the boss disappears - the defeat
signal.

Usage: python boss_fight.py [boss_class_fragment] [max_minutes]
  python boss_fight.py TBoss1Dragon 20
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import learn_live as L                                             # noqa: E402
import pso_input                                                   # noqa: E402

LOG = r"D:\gBox\pso-ds\boss_fight.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def boss_present(fragment):
    return [e for e in L.entities() if fragment in e["c"]]


def main(fragment="TBoss", max_minutes=20.0):
    log(f"=== boss backup watching for '{fragment}'")
    started = time.time()
    attacks = 0
    seen_boss = False
    while time.time() - started < max_minutes * 60:
        boss = boss_present(fragment)
        if boss:
            seen_boss = True
        elif seen_boss:
            log(f"boss '{fragment}' is gone - defeated (or the area changed); {attacks} attacks landed while on backup")
            return 0
        if pso_input.allowed():
            # the operator is idle: keep pressure on the boss
            pso_input.tap("a", gap=0.32)
            attacks += 1
            if attacks % 12 == 0:
                pso_input.hold("b", 0.25)                      # a dodge keeps the character moving
                log(f"  {attacks} attacks, boss present: {bool(boss)}, "
                    f"player hp {None if L.player() is None else L.player()['hp']}")
        else:
            time.sleep(0.4)
    log(f"time budget reached after {attacks} attacks")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "TBoss",
                          float(sys.argv[2]) if len(sys.argv) > 2 else 20.0))
