"""Heal deferral follows the melee range (request #5130, 19763d7aef4edc39): a Majini within 2.5 m (RE5's own melee
reach, IMPACT_MELEE_R) defers the heal; one at 3 m or more no longer does. The old 4 m radius deferred heals in the
2.5-4 m band where the bot could fight safely."""
from gbox.mercs.titles import re5_ps3 as R


def test_melee_range_matches_the_melee_impact_radius():
    # The deferral radius must be RE5's own melee reach: a Majini at this distance can actually land the hit.
    assert R.HEAL_SAFE_R == R.IMPACT_MELEE_R == 250.0
    assert R.HEAL_CRITICAL == 0.25


def test_a_majini_within_melee_still_defers_the_heal(tmp_path):
    # 200 cm < 250 cm: a Majini within actual melee reach still wins, the fight comes first.
    bot = R.Bot(learn_dir=tmp_path)
    player = {'pos': (0., 0., 0.), 'hp': 300, 'hp_max': 1000, 'action': 0}
    snap = {'player': player, 'inventory': [], 'enemies': [
        {'ptr': 0x30700000, 'slot': 0, 'pos': (0., 0., 200.), 'hp': 800, 'hp_max': 800}]}
    assert bot._heal_safe(player, snap, 300, 1000) is False
    assert bot.stats['heal_deferred'].startswith('1 Majini within 2 m at 30%')
    assert bot.stats['heal_deferred_ticks'] == 1


def test_the_2_4_m_band_is_now_healable(tmp_path):
    # The cluster example: "heal deferred 2.5 m, Majini 240.0 cm" with a 160-200 HP loss.
    # Under the old 400 cm radius, 240-400 cm all deferred. Under the new 250 cm radius,
    # only < 250 cm defers; 300 cm and beyond are now healable.
    bot = R.Bot(learn_dir=tmp_path)
    player = {'pos': (0., 0., 0.), 'hp': 300, 'hp_max': 1000, 'action': 0}
    # 300 cm: was deferred under the old 400 cm radius, now heals
    snap = {'player': player, 'inventory': [], 'enemies': [
        {'ptr': 0x30700000, 'slot': 0, 'pos': (0., 0., 300.), 'hp': 800, 'hp_max': 800}]}
    assert bot._heal_safe(player, snap, 300, 1000) is True
    assert 'heal_deferred' not in bot.stats
    # 240 cm: still within melee range, still defers (correct: the Majini can land a hit)
    bot2 = R.Bot(learn_dir=tmp_path)
    snap2 = {'player': player, 'inventory': [], 'enemies': [
        {'ptr': 0x30700000, 'slot': 0, 'pos': (0., 0., 240.), 'hp': 800, 'hp_max': 800}]}
    assert bot2._heal_safe(player, snap2, 300, 1000) is False
    assert 'heal_deferred' in bot2.stats


def test_a_majini_at_4_m_no_longer_defers_the_heal(tmp_path):
    # The old radius was 400 cm; a Majini at exactly 4 m used to defer. Now it heals.
    bot = R.Bot(learn_dir=tmp_path)
    player = {'pos': (0., 0., 0.), 'hp': 300, 'hp_max': 1000, 'action': 0}
    snap = {'player': player, 'inventory': [], 'enemies': [
        {'ptr': 0x30700000, 'slot': 0, 'pos': (0., 0., 400.), 'hp': 800, 'hp_max': 800}]}
    assert bot._heal_safe(player, snap, 300, 1000) is True
    assert 'heal_deferred' not in bot.stats


def test_critical_hp_heals_anyway_within_melee(tmp_path):
    # Even a Majini within melee reach does not block a heal when health is under HEAL_CRITICAL (25 %).
    bot = R.Bot(learn_dir=tmp_path)
    player = {'pos': (0., 0., 0.), 'hp': 100, 'hp_max': 1000, 'action': 0}
    snap = {'player': player, 'inventory': [], 'enemies': [
        {'ptr': 0x30700000, 'slot': 0, 'pos': (0., 0., 100.), 'hp': 800, 'hp_max': 800}]}
    assert bot._heal_safe(player, snap, 100, 1000) is True
    assert 'heal_deferred' not in bot.stats


def test_dead_enemies_do_not_defer_the_heal(tmp_path):
    # A dead Majini (hp=0) at melee range does not count as a threat: the heal proceeds.
    bot = R.Bot(learn_dir=tmp_path)
    player = {'pos': (0., 0., 0.), 'hp': 300, 'hp_max': 1000, 'action': 0}
    snap = {'player': player, 'inventory': [], 'enemies': [
        {'ptr': 0x30700000, 'slot': 0, 'pos': (0., 0., 100.), 'hp': 0, 'hp_max': 800}]}
    assert bot._heal_safe(player, snap, 300, 1000) is True
    assert 'heal_deferred' not in bot.stats


def test_no_enemies_near_heals(tmp_path):
    # No enemies at all: the heal proceeds.
    bot = R.Bot(learn_dir=tmp_path)
    player = {'pos': (0., 0., 0.), 'hp': 300, 'hp_max': 1000, 'action': 0}
    snap = {'player': player, 'inventory': [], 'enemies': []}
    assert bot._heal_safe(player, snap, 300, 1000) is True
    assert 'heal_deferred' not in bot.stats
