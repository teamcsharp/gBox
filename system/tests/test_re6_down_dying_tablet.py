"""#5052 batch: dying at 1 HP down with a tablet in the case — a tablet press instead of down_dying_stay.

The cluster's 8 down_dying_stay hits (2 deaths) came from the bot doing nothing at 1 HP while an
enemy at 1 m range finished it.  The fix calls _dying() from the down_dying branch of _down_fight:
while the case holds a tablet, R is pressed every DYING_GAP_S; if the game takes it the bot heals
and survives.  No tablet: the old down_dying_stay is unchanged.
"""
import pytest

from gbox.mercs.titles import re6_switch as R


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    for cache in (R._FOUND, R._MISS, R._ACTION_NAMES):
        cache.clear()
    R._BONUS.update(base=None)
    R.TITLE.since = None
    monkeypatch.setattr(R, "COVERAGE_PATH", str(tmp_path / "re6_coverage.json"))
    R._COVERAGE["data"] = None
    yield
    R._COVERAGE["data"] = None


def _bot_down_dying(tablets, enemies=((0.0, 0.0, 100.0, 700),)):
    """A bot down at 1 HP with the given tablet count and an enemy at 1 m."""
    from test_re6_switch import brain, round_guest
    bot, clock, snap = brain(round_guest(hp=1, tablets=tablets, enemies=enemies))
    snap["player"]["action"] = "cPlAction_pl_act_dying_loop"
    bot.down = True
    bot.down_dying = True
    return bot, clock, snap


def test_down_dying_with_tablet_presses_r():
    """Down at 1 HP with 6 tablets: _dying fires, R is tapped, tablet_dying decision —
    not down_dying_stay.  The 1 m enemy that finished the bot in the cluster now has to
    wait out the tablet's DYING_GAP_S before the next tick."""
    from test_re6_switch import run
    bot, clock, snap = _bot_down_dying(6)
    act = run(bot, snap, clock, 1)[0]
    assert bot.doing == "tablet"
    assert bot.stats["act"] == "tablet_dying"
    assert act.get("tap") == "r"
    assert bot.stats.get("tablet_dying_presses", 0) == 1


def test_down_dying_without_tablet_stays_down():
    """Down at 1 HP with no tablets: the old down_dying_stay decision, no tablet press."""
    from test_re6_switch import run
    bot, clock, snap = _bot_down_dying(0)
    act = run(bot, snap, clock, 1)[0]
    assert bot.doing == "down"
    assert bot.stats["act"] == "down_dying_stay"
    assert act.get("tap") is None
    assert bot.stats.get("tablet_dying_presses", 0) == 0


def test_down_dying_tablet_repeat_gap():
    """Two ticks 0.5 s apart with a tablet: only the first presses (DYING_GAP_S = 1.0 s)."""
    from test_re6_switch import run
    bot, clock, snap = _bot_down_dying(6)
    acts = run(bot, snap, clock, 2, dt=0.5)
    # First tick: the tablet press.
    assert acts[0].get("tap") == "r"
    # Second tick (0.5 s later): within DYING_GAP_S, no second press.
    assert acts[1].get("tap") is None
    assert bot.stats.get("tablet_dying_presses", 0) == 1


def test_down_dying_tablet_confirmed_heals():
    """The tablet count falls after the press: _tablet_check records the heal and
    tablet_dying_taken increments."""
    from test_re6_switch import run
    bot, clock, snap = _bot_down_dying(6)
    run(bot, snap, clock, 1)
    assert bot.tablet_wait is not None
    # The count fell: the game took the tablet.
    snap["player"]["tablets"] = 5
    run(bot, snap, clock, 1)
    assert bot.stats.get("tablet_dying_taken", 0) == 1
    assert bot.tablet_wait is None
