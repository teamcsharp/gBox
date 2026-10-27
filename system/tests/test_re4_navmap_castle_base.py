"""RE4 r402 (Castle) and r403 (Base) level maps, built from the disc like r400 / r404 (gbox.re4_navmap.extract, the same
builder: a rebuilt r400 matches the shipped one but for its source note)."""
import pytest

from gbox import re4_merc_bot as B
from gbox import re4_navmap as N
from tests.test_re4_merc_bot import world


@pytest.mark.parametrize("room", [0x402, 0x403])
def test_the_castle_and_the_base_have_level_maps_now(room):
    """r402 / r403 had no level map: no paths round walls, no line of sight (he fired through walls), no time bonus
    tour - straight runs at the nearest Ganado, face first into the walls (2026-10-26: 51 % of the r402 stucks)."""
    bot = B.Bot(world([], room=room), nav=None)
    bot._round(room)
    assert bot.st is not None and len(bot.items) >= 5 and all(h["kind"] == "time_bonus" for h in bot.items)
    a, b = bot.items[0], bot.items[-1]
    way = bot.nav.path(bot.st, tuple(a["stand"]), tuple(b["stand"]), ladder_cost=B.LADDER_AVOID)
    assert way and all(w.action != "ladder" for w in way)
    order = N.tour(bot.st, tuple(a["stand"]), targets=bot.items)
    assert sorted(order) == list(range(len(bot.items)))                  # every time bonus on the tour
