"""The endless Survival loop every fighting title shares: always in a fight, never on a title screen.

A title module / object `t` gives:
    state(rd) -> {"fighting", "demo", "p1", "p2", ...}    where the game is, from RAM
    WATCH = (address, n)        RAM that changes every frame while the game runs (hang check)
    STILL_FOR, NUDGE_WAIT       seconds of still RAM before a nudge (NUDGE_KEYS), and after it before calling a hang
    menus, one of:
      ROUTE = ((key, wait), ...)  the presses from the title to a fight (DOA2), run when no jump state exists
      menu_key(st) -> key | None  the next press for the screen RAM shows (DOA3), tapped every MENU_GAP seconds
    jump states (when the adapter has save_state / load_state): OUT_JUMP, JUMP_REFRESH, JUMP_LAND, MAX_FAILED_JUMPS
    safety (optional): SAFETY_HP, HP_MAX, P1_HP: P1 below SAFETY_HP is written back to HP_MAX (needs write_memory)
    fighting, one of:
      reflex(rd, send, stats) -> obj with step(now): polled on its own thread (~100 Hz) while a fight is on (DOA2)
      fight(ad, rd, send, stopped, stats) -> str: the frame-synced engine, returns when the fight screen ends (DOA3)

DOA2 LE (titles/doa2_dc.py) is the first title: the loop is its former doa2_bot.play, unchanged in behavior."""
from __future__ import annotations

import struct
import threading
import time


def play(t, ad, send, stopped, style=None, clock=time.time, sleep=time.sleep, stats: dict | None = None,
         holds: bool | None = None) -> dict:
    """stats (optional, filled live for the watch panel): fights_s, jumps, routes, saves, safety, hung, plus the
    current p1/p2 health and whether a fight is on."""
    lock = threading.Lock()                       # the reflex thread shares the emulator's memory and input link
    base_read = t.reader(ad) if callable(getattr(t, "reader", None)) else ad.read_memory   # DOA3: the fast channel

    def rd(a, n):
        with lock:
            return bytes(base_read(a, n))

    raw_send = send                                # send_locked must reach the emulator, not itself (send is rebound below)

    def send_locked(rows):
        with lock:
            raw_send(rows)
    stats = stats if stats is not None else {}
    stats.update({"fights_s": 0.0, "jumps": 0, "routes": 0, "saves": 0, "safety": 0, "hung": False})
    fighting = threading.Event()
    frame_synced = callable(getattr(t, "fight", None))
    if holds is None:
        holds = clock is time.time                    # real time only: the reflex polls on its own thread
    if holds and not frame_synced and callable(getattr(t, "reflex", None)):
        reflex = t.reflex(rd, send_locked, stats)

        def reflex_loop():
            while not stopped() and not stats["hung"]:
                if fighting.wait(0.5):
                    try:
                        reflex.step(time.time())
                    except Exception:                  # noqa: BLE001 - a read during a load: next poll
                        pass
                    time.sleep(0.008)
        threading.Thread(target=reflex_loop, daemon=True, name="fightbot-reflex").start()
        send = send_locked

    def tap(key):
        send([{"key": key, "down": True}])
        sleep(0.3)
        send([{"key": key, "down": False}])
    route = getattr(t, "ROUTE", None)
    menu_key = getattr(t, "menu_key", None)
    menu_gap = getattr(t, "MENU_GAP", 0.6)
    safety_hp = getattr(t, "SAFETY_HP", None)
    jump_ok, fight_since, out_since, last_ram, still_since, nudged_at = False, None, None, None, None, None
    saved_at, jumped_at, failed_jumps, menu_at = None, None, 0, None
    stats.update(jumps_dropped=0, nudges=0)
    while not stopped():
        now = clock()
        try:
            st = t.state(rd)
            ram = rd(*t.WATCH)
        except Exception:                          # noqa: BLE001 - a read during a load: try again
            sleep(0.5)
            continue
        if ram == last_ram:
            still_since = still_since or now
            if now - still_since > t.STILL_FOR:
                if nudged_at is None:              # a prompt or a still menu: press through it once
                    for key in getattr(t, "NUDGE_KEYS", ("start", "b")):
                        tap(key)
                    nudged_at = clock()
                    stats["nudges"] += 1
                elif now - nudged_at > t.NUDGE_WAIT:
                    stats["hung"] = True           # the caller relaunches the game
                    break
        else:
            still_since = nudged_at = None
        last_ram = ram
        if jumped_at is not None and now - jumped_at > t.JUMP_LAND:
            jumped_at = None                       # the jump showed no fight
            failed_jumps += 1
            if failed_jumps >= t.MAX_FAILED_JUMPS:
                jump_ok, failed_jumps = False, 0
                stats["jumps_dropped"] += 1
        stats.update(fighting=st["fighting"], p1_hp=st["p1"], p2_hp=st["p2"],
                     **({"screen": st["screen"]} if "screen" in st else {}))
        (fighting.set if st["fighting"] else fighting.clear)()
        if st["fighting"]:
            out_since, jumped_at, failed_jumps = None, None, 0
            fight_since = fight_since or now
            if safety_hp is not None and st["p1"] < safety_hp:
                ad.write_memory(t.P1_HP, struct.pack("<H", t.HP_MAX))
                stats["safety"] += 1
            if hasattr(t, "JUMP_REFRESH") and now - fight_since > 6 \
                    and (saved_at is None or now - saved_at > t.JUMP_REFRESH):
                saved_at = now                     # this fight becomes the jump state (a newer one later)
                try:
                    ad.save_state()
                    jump_ok = True
                    stats["saves"] += 1
                except Exception:                  # noqa: BLE001 - no save state: menus it is
                    pass
            if frame_synced:
                stats["fight_end"] = t.fight(ad, rd, send, stopped, stats)
            elif style is not None:
                from ..imitate import play_style
                play_style(style, send=send, stopped=stopped, sleep=sleep, limit=2)
            else:
                sleep(0.3)
            continue
        if fight_since is not None:
            stats["fights_s"] = round(stats["fights_s"] + now - fight_since, 1)
        fight_since = None
        out_since = out_since or now
        title = st["demo"] == 1                    # the title / attract demo: never worth watching
        if jump_ok and jumped_at is None and (title and now - out_since > 1.5 or now - out_since > t.OUT_JUMP):
            try:
                ad.load_state()
                stats["jumps"] += 1
                jumped_at, out_since = clock(), None
                sleep(2.0)
                continue
            except Exception:                      # noqa: BLE001
                jump_ok = False
        if menu_key is not None:                   # the screen RAM shows says what to press
            key = menu_key(st)
            if key and (menu_at is None or now - menu_at >= menu_gap):
                tap(key)
                menu_at = clock()
                stats["menu_presses"] = stats.get("menu_presses", 0) + 1
                continue
            if key is None and now - (menu_at or out_since) > getattr(t, "MENU_IDLE", 30.0):
                for k in getattr(t, "NUDGE_KEYS", ("start", "b")):   # a screen nothing maps: push it along
                    tap(k)
                menu_at = clock()
                stats["menu_nudges"] = stats.get("menu_nudges", 0) + 1
                continue
            sleep(0.1)
            continue
        if route and not jump_ok and now - out_since > 3 and (title or now - out_since > t.OUT_JUMP):
            for key, wait in route:
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
    fighting.clear()
    if fight_since is not None:
        stats["fights_s"] = round(stats["fights_s"] + clock() - fight_since, 1)
    return stats
