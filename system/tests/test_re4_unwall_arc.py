"""#9560: the unwall step on RE4's tank controls turns AND walks (an arc along the wall) instead of a pure sideways stick."""
import math

from gbox.mercs.titles import re4_switch as D


def _bot():
    cls = next(c for c in vars(D).values() if isinstance(c, type) and "_unwall_keys" in vars(c))
    b = cls.__new__(cls)
    return b


class Map:
    def __init__(self, blocked):
        self.blocked = blocked

    def walk_block(self, *a, **k):
        return "wall" if self.blocked else None


def keys(err, blocked=False):
    b = _bot()
    b._room_map = lambda snap: Map(blocked)
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    goal = (math.sin(err) * 1000, 0.0, math.cos(err) * 1000)
    return b._unwall_keys(p, goal, {})


def test_sideways_goal_turns_and_walks():
    k = keys(math.pi / 2)
    assert "lup" in k and len(k) == 2


def test_ahead_goal_walks():
    assert "lup" in keys(0.0)


def test_behind_goal_quick_turn_no_forward():
    assert "lup" not in keys(3.0)


def test_never_pure_sideways_below_quick_turn():
    for e in (0.9, 1.2, 1.57, 1.7):
        assert "lup" in keys(e) and "lup" in keys(-e)


def test_wall_right_ahead_turns_only():
    assert "lup" not in keys(math.pi / 2, blocked=True)
