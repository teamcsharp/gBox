"""Advance the offline intro and character select with A until the game is playable.

The intro plays several pages of story text (each answered with A), then the character list (A selects), then the confirm prompt and the
area load. This presses A at a steady cadence, checks `capabilities.supported` between presses, and stops the moment the game reports a
playable offline session.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import session as S                                                # noqa: E402

LOG = r"D:\gBox\pso-ds\advance_intro.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def supported():
    try:
        caps = S.controls("capabilities", {})
    except Exception:                                            # noqa: BLE001
        return None
    return caps.get("supported") if isinstance(caps, dict) else None


def tap(key="a", settle=1.15):
    G.send([{"key": key, "down": True}])
    time.sleep(0.08)
    G.send([{"key": key, "down": False}])
    time.sleep(settle)


def main(presses=40):
    G.raise_window()
    time.sleep(0.6)
    for index in range(presses):
        state = supported()
        if state is True:
            log(f"PLAYABLE after {index} presses")
            pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
            log(f"  player actor {hex(pointer)} floor {int.from_bytes(S.read_memory(0x805D5FC0, 4), 'big')}")
            return 0
        if index % 5 == 0:
            log(f"  press {index}: supported={state}")
        tap()
    log("still not playable")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 40))
