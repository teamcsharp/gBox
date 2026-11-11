"""Offline proof of the doorway strafe recovery, with no game input at all.

Simulates a room whose exit is a narrow gap: motion along the direct bearing is blocked unless the character's y (z in world) is inside the
gap, while moving perpendicular is always allowed. The bot must therefore feel along the wall, find the gap and pass through.

The simulation replaces the position reader and the key handler, so nothing is sent to the game and the operator lock is irrelevant.
"""
import math
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import door_pass                                                   # noqa: E402
import map_exit as ME                                              # noqa: E402
import steer2 as STEER                                             # noqa: E402

GAP_Z = 10.0                                                       # the doorway spans z in [-10, +10]
WALL_X = -40.0                                                     # the wall sits at this x
STATE = {"x": 0.0, "z": 40.0}                                     # start OUTSIDE the gap so the straight line jams on the wall


def simulated_pos():
    return (STATE["x"], STATE["z"])


def simulated_hold(key, seconds, log=None, wait_for_operator=False, timeout=180.0):
    """A hand-rolled physics step: the four directions move in fixed world terms, but crossing the wall needs the gap."""
    speed = 14.0 * seconds
    moves = {"up": (0.0, -speed), "down": (0.0, speed), "left": (-speed, 0.0), "right": (speed, 0.0)}
    dx, dz = moves.get(key, (0.0, 0.0))
    nx, nz = STATE["x"] + dx, STATE["z"] + dz
    # a wall at WALL_X: crossing it (westwards) is only possible inside the gap
    if nx < WALL_X <= STATE["x"] and abs(STATE["z"]) > GAP_Z:
        nx = WALL_X                                           # jammed against the wall
    if STATE["x"] < WALL_X and nx > WALL_X and abs(STATE["z"]) > GAP_Z:
        nx = WALL_X
    STATE["x"], STATE["z"] = nx, nz
    return True


def run():
    ME.read_pos = simulated_pos
    door_pass.ME.read_pos = simulated_pos
    steer2_pos = simulated_pos
    # the steering module calls the read_pos it is given, and hold through pso_input; patch both
    import pso_input
    pso_input.hold = simulated_hold
    door_pass.pso_input.hold = simulated_hold
    door_pass.pso_input.allowed = lambda: True
    door_pass.pso_input.wait_until_ready = lambda timeout=120.0: True

    target = (WALL_X - 40.0, GAP_Z)                                # the doorway opening on the far side of the wall
    print(f"simulating: start (0,0), wall at x={WALL_X}, gap z in [-{GAP_Z},{GAP_Z}], target {target}")
    through, position, reason = door_pass.approach(target, straight_steps=6, attempts=8, min_travel=45.0)
    print(f"result: through={through} at ({position[0]:.1f},{position[1]:.1f}) reason={reason}")
    crossed = position[0] < WALL_X
    print(f"crossed the wall: {crossed}")
    return 0 if through and crossed else 2


if __name__ == "__main__":
    raise SystemExit(run())
