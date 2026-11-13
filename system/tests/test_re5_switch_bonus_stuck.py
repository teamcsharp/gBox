"""Request #5710 (operator critique, Ancient Ruins): the bot walked a nav route at a time bonus 18.5 m away and hit
"stuck, breaking free" three times in 10 s (bonuses_seen 17, taken 0). Two stuck-breaks on one run now give the statue up
and the next open one is targeted."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R
from tests.test_re5_switch_bonus_giveup import at, snap, bot, OTHER_PTR, STUCK_PTR  # noqa: F401


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


FAR = at(1000, 0)      # the moment: the statue the route kept ramming a wall for
NEXT = at(1400, 60)


def test_two_stuck_breaks_give_the_far_statue_up_and_take_the_next():
    b, clock = bot()
    b.tick(snap(bonuses=[FAR, NEXT]))
    assert b._bonus["ptr"] == 0x5D4A000000
    b._bonus["stucks"] = R.BONUS_STUCK_GIVEUP
    clock[0] = 0.2
    act = b.tick(snap(bonuses=[FAR, NEXT]))
    assert b._bonus is None and "stuck on the way twice" in b.why
    assert b._bonus_block[0x5D4A000000] > clock[0] + R.BONUS_STUCK_BLOCK_S - 1
    assert b.stats["bonus_stuck_giveups"] == 1
    assert 0x5D4A000001 not in b._bonus_block   # only the statue that rammed the wall is given up


def test_one_stuck_break_keeps_the_run():
    b, clock = bot()
    b.tick(snap(bonuses=[FAR, NEXT]))
    b._bonus["stucks"] = R.BONUS_STUCK_GIVEUP - 1
    clock[0] = 0.2
    b.tick(snap(bonuses=[FAR, NEXT]))
    assert b._bonus is not None and b._bonus["ptr"] == 0x5D4A000000
