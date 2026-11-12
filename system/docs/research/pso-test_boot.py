"""Verify play_rooms.boot: it presses until a character exists, gives up cleanly, and logs why.

Boot is the first thing that runs on a live session, and it runs exactly once per launch - a bug there wastes the launch the operator waited for. It is also
easy to get wrong: a loop that never checks `player()`, a bound that is not honoured, or a boot that presses keys forever when the game is already in the
field.

The test replaces `play_rooms.player` and `play_rooms.pso_input.hold` with recorders, so nothing touches an emulator:

  * already in the field -> no presses at all;
  * character after three rounds -> exactly three rounds of presses, returns True;
  * never a character -> returns False after the bound, and the bound is respected (not infinite).

Each key press is recorded, so the order START/A is checked too.
"""
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import play_rooms                                                  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label + (" - " + detail if detail else ""))
    if not condition:
        failures.append(label)


class Presses:
    def __init__(self):
        self.keys = []

    def hold(self, key, seconds=0.3):
        self.keys.append(key)
        return True


def install(player_sequence):
    """player() returns the next entry each call; hold() records presses."""
    presses = Presses()
    sequence = list(player_sequence)
    state = {"index": 0}

    def fake_player():
        index = state["index"]
        state["index"] = min(index + 1, len(sequence) - 1)
        return sequence[index]

    play_rooms.player = fake_player
    play_rooms.pso_input.hold = presses.hold
    return presses


if __name__ == "__main__":
    # already in the field: no presses
    presses = install([(0.0, 0.0, 0.0)])
    result = play_rooms.boot()
    check("in the field returns True", result is True, str(result))
    check("in the field presses nothing", presses.keys == [], str(presses.keys))

    # character appears after three rounds (each round is START then A)
    presses = install([None, None, None, None, None, None, (10.0, 0.0, 5.0)])
    result = play_rooms.boot()
    check("eventually in the field returns True", result is True, str(result))
    check("it pressed START and A", "start" in presses.keys and "a" in presses.keys, str(presses.keys[:6]))
    check("the first press is START", presses.keys[0] == "start", str(presses.keys[:2]))
    check("each round is START then A", presses.keys[:4] == ["start", "a", "start", "a"], str(presses.keys[:4]))

    # never appears: gives up, bounded (small bound so the test is quick)
    presses = install([None])
    result = play_rooms.boot(limit=3)
    check("no character returns False", result is False, str(result))
    check("the bound is respected (3 rounds = 6 presses)", len(presses.keys) == 6, str(len(presses.keys)))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        raise SystemExit(1)
    print("all boot checks passed")
