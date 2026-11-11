"""RE5 Switch: never idle among foes (operator #6810: surrounded, he stopped shooting, planting mines, everything)."""
import math

from gbox.mercs.titles import re5_switch as R


def at(d, deg):
    a = math.radians(deg)
    return (d * math.sin(a), 0.0, d * math.cos(a))


def make():
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    live = [{"ptr": 10 + i, "pos": x, "hp": 800} for i, x in enumerate([at(250, 5), at(350, 60), at(300, -100)])]
    flat = lambda e: math.hypot(e["pos"][0], e["pos"][2])
    return b, p, live, flat


def run(b, p, live, flat, act, seconds, doing="none"):
    """The first tick's output the guard changed, else the last one."""
    out, t = None, 0.0
    while t <= seconds:
        b.doing = doing
        out = b._surround_guard(p, live, flat, act, t)
        if out != act:
            return out
        t += 0.1
    return out


def test_idle_among_foes_fires():
    b, p, live, flat = make()
    out = run(b, p, live, flat, {"hold": ()}, 1.5)
    assert "zr" in out["hold"] and "zl" in out["hold"]
    assert b.stats["surround_idle_breaks"] >= 1 and b.doing == "surround_fire"


def test_aim_without_trigger_is_idle():
    b, p, live, flat = make()
    assert "zr" in run(b, p, live, flat, {"hold": ("zl",)}, 1.5)["hold"]


def test_mine_work_is_not_interrupted():
    b, p, live, flat = make()
    out = run(b, p, live, flat, {"hold": ()}, 3.0, doing="mine")
    assert out == {"hold": ()} and not b.stats.get("surround_idle_breaks")


def test_firing_or_moving_is_not_idle():
    b, p, live, flat = make()
    for act in ({"hold": ("zl", "zr")}, {"hold": ("lup", "b")}):
        assert run(b, p, live, flat, act, 3.0) == act
    assert not b.stats.get("surround_idle_breaks")


def test_nobody_near_no_break():
    b, p, live, flat = make()
    far = [{"ptr": 1, "pos": at(900, 0), "hp": 800}]
    assert run(b, p, far, flat, {"hold": ()}, 3.0) == {"hold": ()}
