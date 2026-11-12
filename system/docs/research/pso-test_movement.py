"""Verify the movement chain: calibration table -> direction choice -> approach closes the distance.

The scanner test proved the bot can see. This proves it can act on what it sees, and it tests the part that is pure logic rather than hardware:

  * `Pad.best(dx, dz)` - given a measured table of "this stick direction moved the character this way", pick the stick direction that actually moves
    toward the target. PSO is camera-relative, so this table is the only thing that makes movement possible, and a wrong choice means walking away from
    the enemy while attacking it.
  * `approach(pad, me, target)` - one step toward a target, returning the new distance, using that choice.

The test uses a table whose directions are deliberately **not** the naive mapping (pushing the stick "up" moves the character toward *negative* Z here),
which is exactly what a rotated camera produces. A `best()` that hard-coded a mapping instead of reading the table would fail these checks.

A fake pad applies each command to a fake player, so `approach` is exercised with real arithmetic and no emulator.
"""
import math
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import vpad                                                        # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + label + (" - " + detail if detail else ""))
    if not condition:
        failures.append(label)


def logic_only():
    """`best()` reads the measured table rather than assuming a mapping."""
    pad = object.__new__(vpad.Pad)                     # no ViGEm device needed
    pad.table = {
        "up": (0.0, -10.0),                            # stick up moved the character toward -Z
        "down": (0.0, 10.0),
        "left": (-10.0, 0.0),
        "right": (10.0, 0.0),
    }
    check("toward -Z picks 'up'", pad.best(0.0, -5.0) == "up", str(pad.best(0.0, -5.0)))
    check("toward +Z picks 'down'", pad.best(0.0, 5.0) == "down", str(pad.best(0.0, 5.0)))
    check("toward -X picks 'left'", pad.best(-5.0, 0.0) == "left", str(pad.best(-5.0, 0.0)))
    check("toward +X picks 'right'", pad.best(5.0, 0.0) == "right", str(pad.best(5.0, 0.0)))
    check("diagonal +X/-Z picks a positive-X or -Z direction",
          pad.best(5.0, -5.0) in ("right", "up"), str(pad.best(5.0, -5.0)))
    check("zero target picks nothing", pad.best(0.0, 0.0) is None)
    empty = object.__new__(vpad.Pad)
    empty.table = {}
    check("no calibration picks nothing", empty.best(1.0, 1.0) is None)


class FakePad:
    """A pad whose `move` shifts a fake player by a fixed step in the commanded direction."""

    def __init__(self):
        self.player = [0.0, 0.0, 0.0]
        self.commands = []

    def best(self, dx, dz):
        return "toward" if (dx or dz) else None

    def move(self, dx, dz, seconds=0.3):
        length = math.hypot(dx, dz)
        if length < 1e-6:
            return None
        step = 4.0
        self.player[0] += step * dx / length
        self.player[2] += step * dz / length
        self.commands.append((round(dx, 2), round(dz, 2)))
        return "toward"

    def press(self, key, seconds=0.25):
        return True


def approach_test():
    """`approach` steps toward the target and reduces the distance each time."""
    fake = FakePad()
    target = (20.0, 0.0)

    original_player = vpad and None
    import play_pad

    def fake_player():
        return (fake.player[0], fake.player[1], fake.player[2])

    play_pad.player = fake_player
    start = math.dist((fake.player[0], fake.player[2]), target)
    distances = [start]
    for _ in range(3):
        gap = play_pad.approach(fake, fake_player(), target, tolerance=2.0)
        distances.append(gap)
    check("approach reduced the distance each step",
          all(b <= a + 1e-6 for a, b in zip(distances, distances[1:])),
          " -> ".join(f"{d:.1f}" for d in distances))
    check("three steps of 4 closed 12 of the 20 units",
          abs(distances[-1] - 8.0) < 0.6, f"ended at {distances[-1]:.1f}")
    check("the pad was asked to move toward +X",
          fake.commands and all(dx > 0 for dx, _dz in fake.commands), str(fake.commands))


if __name__ == "__main__":
    logic_only()
    approach_test()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        raise SystemExit(1)
    print("all movement checks passed")
