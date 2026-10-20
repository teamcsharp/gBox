"""Dead or Alive 2 Limited Edition (Dreamcast, Flycast) autoplay playbook: always in a fight, never on a title screen.

Game state from RAM (found 2026-10-20 by diffing RAM in the attract demo vs a fight the player controls):
  0x8C200848  u8   1 = attract demo / title, 0 = a fight the player controls
  0x8C2376D8  u16  P1 health (0..240 in a fight; the attract demo shows 320)
  0x8C237740  u16  P2 health
The loop: in a fight, the operator's learned style plays P1 (imitate.Style), with P1's health topped up when it runs low
so autoplay never loses on screen; out of a fight (round over, the demo, a title), it loads the jump state saved in an
earlier confirmed fight (emulator save state) and is back in a fight in about two seconds - until that state exists it
presses through the menus (Start, Start, Time Attack, fighter). RAM that stops changing for 8 s = a hang: the run ends
so the caller relaunches. Works on any build of this disc (the operator's MarioVSonic cast build included).
"""
from __future__ import annotations

import struct
import time

GAME_IDS = {"1de2e7634f3161ff"}                 # Dead or Alive 2 - Limited Edition (Japan)
DEMO, P1_HP, P2_HP, HP_MAX = 0x8C200848, 0x8C2376D8, 0x8C237740, 240
SAFETY_HP = 100                                   # P1 below this is topped up to HP_MAX
WATCH = (0x8C237000, 4096)                        # fighter data: changes every frame in play (hang check)
ROUTE = (("start", 3.0), ("start", 3.0), ("right", 1.5), ("b", 3.0), ("b", 3.0))   # title -> Time Attack -> fighter


def matches(ad, g: dict) -> bool:
    return g.get("game_id") in GAME_IDS and g.get("platform") == "dreamcast"


def setup(ad) -> list[str]:
    return []


def state(rd) -> dict:
    """{'fighting', 'demo', 'p1', 'p2'} from RAM (rd(address, length) -> bytes)."""
    demo = rd(DEMO, 1)[0]
    p1, p2 = (struct.unpack("<H", rd(a, 2))[0] for a in (P1_HP, P2_HP))
    return {"demo": demo, "p1": p1, "p2": p2,
            "fighting": demo == 0 and 0 < p1 <= HP_MAX and 0 < p2 <= HP_MAX}


def play(ad, send, stopped, style=None, clock=time.time, sleep=time.sleep, stats: dict | None = None) -> dict:
    """stats (optional, filled live for the watch panel): fights_s, jumps, routes, saves, safety, hung, plus the
    current p1/p2 health and whether a fight is on."""
    rd = lambda a, n: bytes(ad.read_memory(a, n))
    stats = stats if stats is not None else {}
    stats.update({"fights_s": 0.0, "jumps": 0, "routes": 0, "saves": 0, "safety": 0, "hung": False})
    jump_ok, fight_since, out_since, last_ram, frozen_since = False, None, None, None, None
    while not stopped():
        now = clock()
        try:
            st = state(rd)
            ram = rd(*WATCH)
        except Exception:                          # noqa: BLE001 - a read during a load: try again
            sleep(0.5)
            continue
        if ram == last_ram:
            frozen_since = frozen_since or now
            if now - frozen_since > 8:
                stats["hung"] = True               # the caller relaunches the game
                break
        else:
            frozen_since = None
        last_ram = ram
        stats.update(fighting=st["fighting"], p1_hp=st["p1"], p2_hp=st["p2"])
        if st["fighting"]:
            out_since = None
            fight_since = fight_since or now
            if st["p1"] < SAFETY_HP:
                ad.write_memory(P1_HP, struct.pack("<H", HP_MAX))
                stats["safety"] += 1
            if not jump_ok and now - fight_since > 6:
                try:
                    ad.save_state()
                    jump_ok = True
                    stats["saves"] += 1
                except Exception:                  # noqa: BLE001 - no save state: menus it is
                    pass
            if style is not None:
                from .imitate import play_style
                play_style(style, send=send, stopped=stopped, sleep=sleep, limit=2)
            else:
                sleep(0.3)
            continue
        if fight_since is not None:
            stats["fights_s"] = round(stats["fights_s"] + now - fight_since, 1)
        fight_since = None
        out_since = out_since or now
        if jump_ok and now - out_since > 1.5:      # straight back into a fight: no demo, title or menus
            try:
                ad.load_state()
                stats["jumps"] += 1
                out_since = None
                sleep(2.0)
                continue
            except Exception:                      # noqa: BLE001
                jump_ok = False
        if now - out_since > 3:
            for key, wait in ROUTE:
                if stopped():
                    break
                send([{"key": key, "down": True}])
                sleep(0.3)
                send([{"key": key, "down": False}])
                sleep(wait)
            stats["routes"] += 1
            out_since = None
            continue
        sleep(0.5)
    if fight_since is not None:
        stats["fights_s"] = round(stats["fights_s"] + clock() - fight_since, 1)
    return stats
