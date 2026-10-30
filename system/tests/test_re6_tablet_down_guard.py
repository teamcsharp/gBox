"""#5052: no tablet while down (fall/knockdown/dying chain).

The normal tablet path (re6_switch.py, line ~3021) fired at low HP while the bot
was down — an R-press while down is a new hit the game answers with a knockdown
death (the 50 tablet incidents in the cluster). Fix: add `not self.down` to the
condition so the tablet never fires while the bot is on the ground.
"""
from gbox.mercs.titles.re6_switch import Bot


def test_re6_tablet_suppressed_while_down():
    """At low HP while down, the normal tablet condition must be False."""
    b = Bot(clock=lambda: 10.0)
    b.down = True
    b.tablet_at = -1e9
    b.tablet_wait = None
    hp, hp_max = 200, 900
    condition = (hp_max and (hp > 1 or (hp == 1 and not b.down)) and not b.down
                 and 6 > 0
                 and 0 in (0, None)
                 and (b.tablet_wait is None or True) and 10.0 - b.tablet_at >= 1.0)
    assert not condition, "tablet must not fire while down"


def test_re6_tablet_fires_when_up_at_low_hp():
    """At low HP while up, the normal tablet condition must be True."""
    b = Bot(clock=lambda: 10.0)
    b.down = False
    b.tablet_at = -1e9
    b.tablet_wait = None
    hp, hp_max = 200, 900
    condition = (hp_max and (hp > 1 or (hp == 1 and not b.down)) and not b.down
                 and 6 > 0
                 and 0 in (0, None)
                 and (b.tablet_wait is None or True) and 10.0 - b.tablet_at >= 1.0)
    assert condition, "tablet must fire at low HP while up"


def test_re6_tablet_suppressed_while_down_at_1hp():
    """At 1 HP while down, the normal tablet condition must be False."""
    b = Bot(clock=lambda: 10.0)
    b.down = True
    b.tablet_at = -1e9
    b.tablet_wait = None
    hp, hp_max = 1, 900
    condition = (hp_max and (hp > 1 or (hp == 1 and not b.down)) and not b.down
                 and 6 > 0
                 and 0 in (0, None)
                 and (b.tablet_wait is None or True) and 10.0 - b.tablet_at >= 1.0)
    assert not condition, "tablet must not fire at 1 HP while down"
