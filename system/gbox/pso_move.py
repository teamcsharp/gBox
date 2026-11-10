"""P1/P3: walk the character by closed loop on its own RAM position.

The guide's P1 needs the party to reach Forest 1 "by real presses", and P3 needs it to walk the areas by their map.
Both start with the same primitive: hold a direction, read the position back, and correct. This module is that
primitive, with no emulator in it -- the caller supplies ``position()`` and ``hold(key, seconds)``, so it is testable
against a model and reusable live.

What the live session showed (i9-NUC, 2026-11-10, session ``dbc5ff9be4ca416c-c91e5802a9844b37``):

* Buttons reach PSO through the **virtual pad** even with the Dolphin window minimised, which is what the adapter's
  ``_setup_vpad`` is for.
* The **analog stick did not reach the game** in that session: ``left_joystick`` holds produced no camera rotation and
  no position change, while the same pad's buttons worked. The keyboard path (``win_send_keys`` with Dolphin focused)
  did move the character -- measured, not assumed: holding the down key moved the player from ``(-5.9, -1965.7)`` to
  ``(16.6, -1936.2)``, and holding right from there to ``(33.4, -1968.3)``.
* Once the position is readable, movement is measurable and a loop can correct it, which is what makes this module
  worth having before the stick question is settled: :meth:`Walker.walk_to` works with whichever hold path moves.

Two live traps are encoded as refusals rather than retries: a hold that produces no movement is reported (a stuck
menu, a dropped pad or a wall all look the same, and the guide's note "a dead autobot looks like a standing character"
is the same failure), and the walk gives up instead of pressing forever.
"""
from __future__ import annotations

import math

from . import pso_ram

TOLERANCE = 6.0            # world units; PSO's own interact range is about this
STUCK_LIMIT = 4            # consecutive holds with no progress before giving up


class MoveError(RuntimeError):
    pass


def position(reader, slot: int = 0):
    """(x, y, z) of a player, or None when that slot holds no player."""
    p = pso_ram.player(reader, slot)
    return None if p is None else (p["x"], p["y"], p["z"])


def distance(a, b) -> float:
    """Planar (XZ) distance -- PSO's vertical axis is not what walking covers."""
    return math.hypot(a[0] - b[0], a[2] - b[2])


def direction_to(start, target) -> tuple[str, str]:
    """The two axis keys that move ``start`` toward ``target``, dominant axis first."""
    dx, dz = target[0] - start[0], target[2] - start[2]
    keys = []
    if abs(dz) >= abs(dx):
        keys.append(# vertical axis first
            "down" if dz > 0 else "up")
        if abs(dx) > 1e-6:
            keys.append("right" if dx > 0 else "left")
    else:
        keys.append("right" if dx > 0 else "left")
        if abs(dz) > 1e-6:
            keys.append("down" if dz > 0 else "up")
    return tuple(keys)


class Walker:
    """Closed-loop movement over an injected ``position()`` and ``hold(key, seconds)``.

    ``hold`` must move the character in the *screen/camera* frame the keys act in, so the walker corrects by
    re-reading rather than trusting a direction: it takes the axis whose movement helped and drops the one that did not.
    """

    def __init__(self, position_fn, hold_fn, *, sleep=None, log=None):
        self._position = position_fn
        self._hold = hold_fn
        self._sleep = sleep
        self._log = log or (lambda _m: None)

    def walk_to(self, target, *, tolerance=TOLERANCE, max_holds=40, step=0.8) -> dict:
        """Walk until within ``tolerance`` of ``target`` (XZ). Returns a trace; ``ok`` only when it arrived."""
        trace = []
        stuck = 0
        here = self._position()
        if here is None:
            return {"ok": False, "why": "no player in slot 0", "trace": trace}
        start_distance = distance(here, target)
        for i in range(max_holds):
            before = self._position()
            if before is None:
                return {"ok": False, "why": "the player disappeared", "trace": trace}
            d = distance(before, target)
            trace.append({"hold": i, "at": [round(v, 1) for v in before], "distance": round(d, 1)})
            if d <= tolerance:
                return {"ok": True, "holds": i, "distance": round(d, 2),
                        "start_distance": round(start_distance, 1), "trace": trace}
            moved = False
            for key in direction_to(before, target):
                self._hold(key, step)
                after = self._position()
                if after is None:
                    break
                if distance(after, target) < d - 0.5:
                    moved = True
                    break
            stuck = 0 if moved else stuck + 1
            if stuck >= STUCK_LIMIT:
                return {"ok": False, "why": f"no progress in {stuck} holds (a menu open, a wall, or no input)",
                        "holds": i + 1, "distance": round(distance(before, target), 1), "trace": trace}
        return {"ok": False, "why": f"did not arrive in {max_holds} holds",
                "distance": round(distance(self._position() or target, target), 1), "trace": trace}
