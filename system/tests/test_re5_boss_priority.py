"""Bosses first, from a distance (operator 2026-10-26: "she is failing to recognize the threat of the boss and dispatch
them. Bosses are threats that require the remove their HP and dispatch them without delay (preferably from a distance)")."""
from gbox.mercs.titles import re5_ps3 as R
from test_re5_checkpoint_departure import scene


def bot_at(tmp_path, clock):
    bot = R.Bot(learn_dir=tmp_path, clock=clock)          # m=None: no combat layer, the decision alone
    bot.round_input_ready = True
    bot.stats["stage"] = "Public_Assembly"
    return bot


def majini(slot, z, hp=800):
    return {"ptr": 0x30700000 + slot, "slot": slot, "hp": hp, "hp_max": hp, "pos": (0.0, 0.0, z)}


def test_a_boss_in_sight_is_the_target_before_a_nearer_majini_unless_one_is_at_arms_length(tmp_path):
    snap, bot = scene(), bot_at(tmp_path, lambda: 1.0)
    snap["bonuses"] = []
    snap["enemies"] = [majini(0, 600.0), majini(1, 1500.0, hp=9000)]        # the Executioner behind a Majini
    bot._observed_snap = snap
    bot._tick(dict(snap))
    assert bot.plan_target["id"] == 1 and bot.stats["target_evidence"].startswith("boss first"), bot.stats
    snap["enemies"] = [majini(0, 250.0), majini(1, 1500.0, hp=9000)]        # one at arm's length: him first
    bot._observed_snap = snap
    bot._tick(dict(snap))
    assert bot.plan_target["id"] == 0


def test_a_boss_this_close_is_backed_away_from_then_fired_on_then_backed_away_from_again(tmp_path):
    t = [0.0]
    snap, bot = scene(), bot_at(tmp_path, lambda: t[0])
    snap["bonuses"] = []
    snap["enemies"] = [majini(1, 400.0, hp=9000)]                             # inside BOSS_KEEP_R
    bot._observed_snap = snap
    action = bot._tick(dict(snap))
    assert bot.stats["phase"] == "boss_range" and bot.stats["boss_retreats"] == 1, bot.stats
    assert "backing off" in bot.stats["boss"] and action["hold"], action    # walking the retreat route
    t[0] = 3.0                                                              # the back-off over: his turn to shoot
    bot._observed_snap = snap
    bot._tick(dict(snap))
    assert bot.stats["phase"] != "boss_range" and "firing" in bot.stats["boss"] and bot.stats["boss_retreats"] == 1
    t[0] = 5.0                                                              # still on him after the volley: again
    bot._observed_snap = snap
    bot._tick(dict(snap))
    assert bot.stats["phase"] == "boss_range" and bot.stats["boss_retreats"] == 2


def test_without_a_mesh_the_boss_is_fought_where_he_stands(tmp_path):
    snap, bot = scene(), bot_at(tmp_path, lambda: 1.0)
    snap["bonuses"], snap["nav"] = [], None
    snap["enemies"] = [majini(1, 400.0, hp=9000)]
    bot._observed_snap = snap
    bot._tick(dict(snap))
    assert bot.stats["phase"] != "boss_range" and bot.stats.get("boss_retreats", 0) == 0
    assert bot.plan_target["id"] == 1
