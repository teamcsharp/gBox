"""Walk the offline flow one deliberate step at a time, reporting the state after each.

Flow (from the verified boot notes): OFFLINE GAME -> single mode -> character (default) -> confirm -> episode 1 -> the area loads -> intro
dialogs. Each step waits for the game to settle and prints what the game reports, so the exact step that fails is visible instead of being
guessed.
"""
import struct
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import session as S                                                # noqa: E402

LOG = r"D:\gBox\pso-ds\offline_flow.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def state():
    try:
        caps = S.controls("capabilities", {})
    except Exception:                                            # noqa: BLE001
        return {"supported": None}
    if not isinstance(caps, dict):
        return {"supported": None}
    floor = int.from_bytes(S.read_memory(0x805D5FC0, 4), "big")
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    hp = None
    if 0x80000000 <= pointer < 0x81800000:
        hp = struct.unpack(">H", S.read_memory(pointer + 0x32C, 2))[0]
    return {"supported": caps.get("supported"), "floor": floor, "actor": hex(pointer), "hp": hp}


def press(key, settle):
    G.send([{"key": key, "down": True}])
    time.sleep(0.09)
    G.send([{"key": key, "down": False}])
    time.sleep(settle)


def main():
    G.raise_window()
    time.sleep(0.7)
    log(f"start: {state()}")
    press("start", 2.5)
    log(f"after START: {state()}")
    press("ddown", 1.0)                                            # OFFLINE GAME (one row down)
    press("a", 3.0)
    log(f"after OFFLINE: {state()}")
    press("a", 3.0)                                                # single mode / default
    log(f"after mode: {state()}")
    press("a", 3.0)                                                # character (default)
    log(f"after character: {state()}")
    press("a", 3.0)                                                # confirm
    log(f"after confirm: {state()}")
    press("a", 4.0)                                                # episode 1
    log(f"after episode: {state()}")
    for step in range(12):
        current = state()
        if current.get("supported") is True:
            log(f"PLAYABLE at step {step}: {current}")
            return 0
        if current.get("floor", 0) > 0:
            log(f"in the game at step {step}: {current}")
            return 0
        press("a", 2.2)
        if step % 3 == 0:
            log(f"  step {step}: {state()}")
    log(f"end: {state()}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
