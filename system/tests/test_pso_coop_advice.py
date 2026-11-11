import time
from gbox import pso_coop
from gbox.mercs import directives


def _ctl():
    c = object.__new__(pso_coop.Controller)
    c._advice_reader = None
    c._advice_until = 0.
    class I: stats = {}
    c.inputs = I()
    return c


def test_door_words_match_next_area():
    for t in ("complete the level", "walk through the doors", "go through the door", "finish the stage"):
        assert directives.match(t) == "next_area", t


def test_advice_lifts_dwell_wait_then_expires():
    c = _ctl()
    now = time.time()
    assert c.advice_advance(now) is False
    directives.apply_to_stats(c.inputs.stats, directives.post("s", "next_area", now=now))
    assert c.advice_advance(now) is True
    assert c.inputs.stats["pso_advice"]["state"] == "advancing"
    assert c.advice_advance(now + pso_coop.ADVICE_ADVANCE_S + 1) is False


def test_other_advice_cancels():
    c = _ctl()
    now = time.time()
    directives.apply_to_stats(c.inputs.stats, directives.post("s", "next_area", now=now))
    assert c.advice_advance(now)
    directives.apply_to_stats(c.inputs.stats, directives.post("s", "fight", now=now + 1))
    assert c.advice_advance(now + 1) is False
