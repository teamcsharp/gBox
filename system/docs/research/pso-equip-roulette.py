"""Equipment roulette: a random weapon, frame, shield and mag every two minutes, with a randomly built mag each time.

The plane's own `randomized` op swaps the four categories (weapon / armor / shield / mag) from the owned disc's rare pool, but it deliberately
does NOT touch mag stats - it only records them. So this drives both halves:

  * `pso_controls op=randomized` with categories [weapon, armor, shield, mag] and interval 120 does the swaps;
  * after each swap this picks a random MAG ARCHETYPE (power, mind, dexterity, defence or balanced) and calls `mag_set` with a random
    distribution of the 200-point budget, so the mag changes character every cycle - heavy on magic one time, on strength the next,
    defence another.

`mag_set` accepts def / pow / dex / mind / iq / synchro / color / form, each <= 200, the four stats summing to <= 200, synchro <= 120.

Usage:
  python equip_roulette.py --once     one random mag build now (and report the response)
  python equip_roulette.py --loop     re-roll the mag every 120 s, forever
"""
import random
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import session as S                                                # noqa: E402

INTERVAL = 120
ARCHETYPES = ("power", "mind", "dexterity", "defence", "balanced", "hybrid")


def log(line):
    print(f"{time.strftime('%H:%M:%S')} {line}", flush=True)


def random_build(rng=random, archetype=None):
    """A random 200-point mag build, respecting mag_set's caps."""
    archetype = archetype or rng.choice(ARCHETYPES)
    budget = 200

    def share(main_low, main_high, others):
        main = rng.randint(main_low, min(main_high, budget - sum(others)))
        return main

    if archetype == "power":
        def_stat = rng.randint(0, 20)
        mind = rng.randint(0, 30)
        dex = rng.randint(15, 60)
        pow_stat = max(0, budget - def_stat - mind - dex)
    elif archetype == "mind":
        def_stat = rng.randint(0, 20)
        pow_stat = rng.randint(0, 30)
        dex = rng.randint(15, 60)
        mind = max(0, budget - def_stat - pow_stat - dex)
    elif archetype == "dexterity":
        def_stat = rng.randint(0, 20)
        pow_stat = rng.randint(10, 50)
        mind = rng.randint(0, 30)
        dex = max(0, budget - def_stat - pow_stat - mind)
    elif archetype == "defence":
        pow_stat = rng.randint(0, 30)
        mind = rng.randint(0, 30)
        dex = rng.randint(0, 30)
        def_stat = max(0, budget - pow_stat - mind - dex)
    elif archetype == "balanced":
        each = budget // 4
        def_stat = rng.randint(each - 15, each + 15)
        pow_stat = rng.randint(each - 15, each + 15)
        dex = rng.randint(each - 15, each + 15)
        mind = max(0, budget - def_stat - pow_stat - dex)
    else:                                                       # hybrid: two stats carry it
        first, second = rng.sample(("pow", "dex", "mind", "def"), 2)
        halves = {first: rng.randint(60, 110), second: rng.randint(60, 110)}
        def_stat = halves.get("def", rng.randint(0, 20))
        pow_stat = halves.get("pow", rng.randint(0, 20))
        dex = halves.get("dex", rng.randint(0, 20))
        mind = max(0, budget - def_stat - pow_stat - dex)
    total = def_stat + pow_stat + dex + mind
    scale = min(1.0, 200.0 / total) if total > 200 else 1.0
    return {"archetype": archetype,
            "def": int(def_stat * scale), "pow": int(pow_stat * scale),
            "dex": int(dex * scale), "mind": int(mind * scale),
            "iq": rng.randint(0, 200), "synchro": rng.randint(0, 120),
            "color": rng.randint(0, 18)}


def current_mag():
    reply = S.controls("mag", {})
    if isinstance(reply, dict) and reply.get("mag"):
        return reply["mag"]
    return None


def roll_mag(archetype=None):
    mag = current_mag()
    if not mag or not mag.get("id"):
        log("no equipped mag to re-roll")
        return None
    build = random_build(archetype=archetype)
    properties = {key: build[key] for key in ("def", "pow", "dex", "mind", "iq", "synchro", "color")}
    log(f"mag {mag.get('id')} ({mag.get('stage')} stage), build {build['archetype']}: "
        f"def {properties['def']} pow {properties['pow']} dex {properties['dex']} mind {properties['mind']} "
        f"(sum {properties['def'] + properties['pow'] + properties['dex'] + properties['mind']})")
    reply = S.controls("mag_set", {"item_id": mag["id"], "properties": properties})
    if isinstance(reply, dict):
        after = reply.get("mag") or {}
        log(f"  applied: {reply.get('message', 'set')} -> "
            f"def {after.get('def')} pow {after.get('pow')} dex {after.get('dex')} mind {after.get('mind')} "
            f"level {after.get('level')}")
    else:
        log(f"  response: {str(reply)[:200]}")
    return build


def enable_swaps():
    reply = S.controls("randomized", {"on": True, "interval": INTERVAL,
                                      "categories": ["weapon", "armor", "shield", "mag"],
                                      "character_class": "HUmar"})
    if isinstance(reply, dict):
        log(f"randomizer on: interval {reply.get('interval')}s, categories {reply.get('categories')}, "
            f"cycles {reply.get('cycles')}, {reply.get('message')}")
    else:
        log(f"randomizer response: {str(reply)[:200]}")
    return reply


def main():
    if "--once" in sys.argv:
        enable_swaps()
        roll_mag()
        return 0
    if "--loop" in sys.argv:
        enable_swaps()
        while True:
            time.sleep(INTERVAL)
            roll_mag()
    enable_swaps()
    log("randomizer enabled; run with --loop to re-roll mag stats every cycle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
