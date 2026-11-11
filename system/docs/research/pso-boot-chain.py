"""Boot PSO from a fresh launch to a controllable character, using the sequence measured this round.

Verified path: SEGA logo -> title -> START -> stick DOWN (the menu uses the STICK, not the D-pad) -> A -> SINGLE MODE (A) ->
character select (A) -> Confirm (A) -> Episode 1 (A) -> area load -> intro dialogs (A x N). Captures at the milestones so the caller can
confirm each screen instead of trusting the sequence blindly.
"""
import sys
import time

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import boot_game as B                                              # noqa: E402
import game_input as G                                             # noqa: E402


def tap(key, hold=0.10, settle=1.2):
    G.send([{"key": key, "down": True}])
    time.sleep(hold)
    G.send([{"key": key, "down": False}])
    time.sleep(settle)


def main(start_delay=20.0):
    print(f"waiting {start_delay:.0f}s for the title", flush=True)
    time.sleep(start_delay)
    B.shot("b0-title")
    tap("start", settle=2.5)
    B.shot("b1-menu")
    tap("down", hold=0.10, settle=1.0)                             # stick down: one step
    B.shot("b2-offline-selected")
    tap("a", settle=3.5)
    B.shot("b3-mode")
    tap("a", settle=3.5)                                           # SINGLE MODE
    B.shot("b4-character")
    tap("a", settle=1.6)                                           # open the Confirm submenu
    B.shot("b5-confirm-menu")
    tap("a", settle=3.5)                                           # Confirm
    B.shot("b6-episode")
    tap("a", settle=14.0)                                          # Episode 1 -> area load
    B.shot("b7-area")
    for index in range(16):                                        # intro dialogs
        tap("a", settle=0.75)
    B.shot("b8-done")
    print("boot sequence complete", flush=True)
    return 0


if __name__ == "__main__":
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    raise SystemExit(main(delay))
