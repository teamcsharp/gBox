"""RE5 PS3 Mercs: the damage cluster "low_hp_heal_unused" (request #5129): the bot sat holding the heal while the
Majini kept hitting him, and died to hits of 86 or more. Example from the cluster: 14 Majini, one on top, and at
1-3 HP the bot was still pressing Y. The fix: a heal already under way keeps its bounded use while health is above
the (learned) critical threshold; only under it does the fight win and the heal is dropped."""
import math

from gbox.mercs import impact_lessons as IL
from gbox.mercs.titles import re5_ps3 as R


def _bot(tmp_path, stage="Prison"):
    bot = R.Bot(learn_dir=tmp_path)
    bot.stats["stage"] = stage
    return bot


def _teach_heavy_hit(bot, hp_before, hp_after):
    """Two _impact_watch ticks that teach the stage a (hp_before - hp_after) HP blow."""
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp_before, "hp_max": 1000}
    boss = {"ptr": 9, "slot": 2, "pos": (0.0, 0.0, 400.0), "hp": 4000, "hp_max": 4000}
    bot._impact_watch({"player": p, "enemies": [boss]})
    bot._impact_watch({"player": dict(p, hp=hp_after), "enemies": [boss]})


def test_heavy_stage_raises_its_heal_critical_to_cover_the_blows(tmp_path):
    """A stage whose Majini land 420 HP blows (42% of 1000): the learned threshold is 0.42 * 1.25, capped at
    HEAL_CRITICAL_MAX (35%). At 300 HP (30%, under 35%) a heal starts even with two Majini 3 m away; at 400 HP
    (40%, above 35%) the fight still wins first on the base rule."""
    bot = _bot(tmp_path)
    _teach_heavy_hit(bot, 1000, 580)
    assert bot._heal_critical() == IL.HEAL_CRITICAL_MAX
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 300, "hp_max": 1000}
    s = {"player": p, "enemies": [
        {"ptr": 2, "slot": 0, "pos": (0.0, 0.0, 300.0), "hp": 800, "hp_max": 800},
        {"ptr": 3, "slot": 1, "pos": (0.0, 0.0, 350.0), "hp": 700, "hp_max": 700}]}
    assert bot._heal_safe(p, s, 300, 1000)                               # 30%: under the learned 35%: heal now
    assert not bot._heal_safe(p, s, 400, 1000)                            # 40%: above it: fight first


def test_ordinary_hits_do_not_raise_the_threshold(tmp_path):
    """A stage hit for 150 (15%): 0.15 * 1.25 = 0.1875 is below the base 0.25, so the base still rules - no heal
    spam in a crowd an ordinary hit does not threaten to finish."""
    bot = _bot(tmp_path)
    _teach_heavy_hit(bot, 1000, 850)
    assert abs(bot._heal_critical() - R.HEAL_CRITICAL) < 1e-9
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 300, "hp_max": 1000}
    s = {"player": p, "enemies": [{"ptr": 2, "slot": 0, "pos": (0.0, 0.0, 300.0), "hp": 800, "hp_max": 800}]}
    assert not bot._heal_safe(p, s, 300, 1000)                            # base 25%: 30% still defers


def test_a_started_heal_keeps_its_bounded_use_above_the_threshold(tmp_path):
    """Heal in progress: above the (learned) critical threshold the Square use continues to its bounded end; under
    it with a Majini on top (within contact range) the fight wins and the caller drops the heal (the cluster's
    deaths: 1-3 HP, pressing Y, the heal interrupted)."""
    bot = _bot(tmp_path)
    _teach_heavy_hit(bot, 1000, 580)                                      # learned: 35%
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 400, "hp_max": 1000}
    s = {"player": p, "enemies": [
        {"ptr": 2, "slot": 0, "pos": (0.0, 0.0, 300.0), "hp": 800, "hp_max": 800},
        {"ptr": 3, "slot": 1, "pos": (0.0, 0.0, 350.0), "hp": 700, "hp_max": 700}]}
    bot.healing = {"player": p["ptr"], "id": 0x304, "count": 2, "hp": 900, "at": 0.0,
                   "last_use": -math.inf, "uses": 0, "equip_at": 0.0, "equips": 1, "ready_at": -math.inf, "return": None}
    assert bot._heal_in_progress(p, s, 400, 1000)                          # 40% > 35% learned: keep using
    p_low = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 300, "hp_max": 1000}
    s_low = {"player": p_low, "enemies": [
        {"ptr": 2, "slot": 0, "pos": (0.0, 0.0, 50.0), "hp": 800, "hp_max": 800}]}  # 0.5 m: on top
    assert not bot._heal_in_progress(p_low, s_low, 300, 1000)              # 30% < 35% learned, on top: fight
    bot2 = _bot(tmp_path)                                                 # base rule still 25% on an unknown stage
    bot2.healing = {"player": p["ptr"], "id": 0x304, "count": 2, "hp": 900, "at": 0.0,
                    "last_use": -math.inf, "uses": 0, "equip_at": 0.0, "equips": 1, "ready_at": -math.inf, "return": None}
    assert bot2._heal_in_progress(p, s, 300, 1000)                         # 30% > 25% base: keep using
    p_base = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 200, "hp_max": 1000}
    s_base = {"player": p_base, "enemies": [
        {"ptr": 2, "slot": 0, "pos": (0.0, 0.0, 80.0), "hp": 800, "hp_max": 800}]}  # 0.8 m: on top
    assert not bot2._heal_in_progress(p_base, s_base, 200, 1000)           # 20% < 25% base, on top: fight
