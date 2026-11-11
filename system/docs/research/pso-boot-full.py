"""Boot PSO from launch to a controllable character using the verified closed-loop menu navigation.

Steps: START -> closed-loop select OFFLINE GAME -> A (single mode, default) -> A (character, default BQF) -> A (Confirm submenu) ->
A (episode 1, default) -> wait for the area -> advance the intro dialogs. Reports capabilities before and after so "supported" is
objective evidence that the game reached offline free-play.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import boot_game as B                                              # noqa: E402
import game_input as G                                             # noqa: E402
import menu_select as M                                            # noqa: E402
import session as S                                                # noqa: E402

TITLE_ROWS = (382, 420, 458, 496)


def tap(key, hold=0.1, settle=1.2):
    G.send([{"key": key, "down": True}])
    time.sleep(hold)
    G.send([{"key": key, "down": False}])
    time.sleep(settle)


def capabilities():
    try:
        result = S.controls("capabilities", timeout=45)
        return result.get("supported"), result.get("reason", "")
    except Exception as exc:                                     # noqa: BLE001
        code = getattr(exc, "code", 0)
        detail = getattr(exc, "read", lambda: b"")().decode()[:120] if hasattr(exc, "read") else str(exc)[:100]
        return None, f"{code} {detail}"


def main():
    print("before:", capabilities(), flush=True)
    tap("start", settle=2.6)
    B.shot("g1-menu")
    print("navigate to OFFLINE GAME:", M.navigate(1, TITLE_ROWS, label="title"), flush=True)
    tap("a", settle=3.5)
    B.shot("g2-mode")
    tap("a", settle=3.5)                                           # SINGLE MODE (default selection)
    B.shot("g3-character")
    tap("a", settle=1.8)                                           # open Confirm submenu
    tap("a", settle=4.0)                                           # Confirm
    B.shot("g4-episode")
    tap("a", settle=16.0)                                          # Episode 1 -> area
    B.shot("g5-area")
    for _ in range(40):                                            # intro dialogs
        tap("a", settle=0.6)
    B.shot("g6-play")
    print("after:", capabilities(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
