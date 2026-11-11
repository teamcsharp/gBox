"""Boot the docked game: select OFFLINE GAME with the closed-loop D-pad navigator, then walk the offline flow.

The docked layout is 1030x579 with the four title rows at 382/420/458/496 - exactly what menu_select was built for - so this uses its
closed-loop navigator (D-pad steps one row, and the highlighted row is confirmed from the screen) rather than the analog stick that jumped
two or three rows.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import game_input as G                                             # noqa: E402
import menu_select as M                                            # noqa: E402
import session as S                                                # noqa: E402

TITLE_ROWS = (382, 420, 458, 496)
LOG = r"D:\gBox\pso-ds\boot_docked.log"


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def tap(key, settle=1.2):
    G.send([{"key": key, "down": True}])
    time.sleep(0.1)
    G.send([{"key": key, "down": False}])
    time.sleep(settle)


def supported():
    try:
        caps = S.controls("capabilities", {})
    except Exception as exc:                                      # noqa: BLE001
        log(f"  capabilities failed: {str(exc)[:70]}")
        return False
    return isinstance(caps, dict) and caps.get("supported") is True


def main():
    G.raise_window()
    time.sleep(0.8)
    log(f"session {S.session_id()}")
    if supported():
        log("already playable")
        return 0
    ok = M.navigate(1, TITLE_ROWS, label="offline")
    log(f"navigate to OFFLINE GAME: {ok}")
    if not ok:
        return 2
    tap("a", settle=2.4)
    for step in range(9):
        if supported():
            log("PLAYABLE: capabilities.supported == true")
            return 0
        log(f"  step {step}: advancing")
        tap("a", settle=1.8)
    log("not playable after the flow")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
