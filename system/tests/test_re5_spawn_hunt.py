"""A quiet stand hunts the spawn points (operator 2026-10-26: "why does enemies stop spawning? ... they are getting 78
enemies by the end and having long swaths of time where enemies are not spawning"; round maps Experimental_Facility
11:22 / 11:49: 491 s and 585 s standing at the stand with no Majini)."""
import json
from gbox.mercs.titles import re5_ps3 as R
from test_re5_checkpoint_departure import scene


def quiet_bot(tmp_path, clock):
    bot = R.Bot(learn_dir=tmp_path, clock=clock)
    bot.round_input_ready = True
    bot.stats["stage"] = "Experimental_Facility"
    return bot                                               # m=None: no combat layer, the decision alone


def test_a_quiet_stand_hunts_the_farthest_known_spawn_point_then_the_next(tmp_path):
    t = [0.0]
    snap, bot = scene(), quiet_bot(tmp_path, lambda: t[0])
    snap["bonuses"] = []
    snap["enemies"] = [{"ptr": 11, "slot": 0, "hp": 800, "hp_max": 800, "pos": (3000.0, 0.0, 0.0)},
                       {"ptr": 12, "slot": 1, "hp": 800, "hp_max": 800, "pos": (-3000.0, 0.0, 500.0)}]
    bot._observed_snap = snap
    bot._tick(dict(snap))                                   # two Majini seen: two spawn points, the lull clock running
    assert bot.stats["spawns"] == 2 and bot.stats["enemies"] == 2
    snap["enemies"] = []
    for t[0] in (1.0, 5.0, 8.5):
        bot._observed_snap = snap
        action = bot._tick(dict(snap))
    assert bot.stats["phase"] == "hunt_spawns" and bot.stats["spawn_hunts"] == 1, bot.stats
    assert bot.plan_target["kind"] == "hunt" and bot.plan_target["pos"][0] == -3000.0   # the farthest first
    assert action["hold"], action                           # walking, not standing
    snap["player"]["pos"] = (-2800.0, 0.0, 450.0)         # there: visited, the next one is the other point
    t[0] = 12.0
    bot._observed_snap = snap
    bot._tick(dict(snap))
    assert bot.plan_target["pos"][0] == 3000.0 and bot.stats["spawn_hunts"] == 2
    assert "hunt" in bot.stats and "away" in bot.stats["hunt"]


def test_a_majini_showing_ends_the_hunt_and_a_round_reset_keeps_the_stage_points_in_the_learn_dir(tmp_path):
    t = [0.0]
    snap, bot = scene(), quiet_bot(tmp_path, lambda: t[0])
    snap["bonuses"] = []
    snap["enemies"] = [{"ptr": 11, "slot": 0, "hp": 800, "hp_max": 800, "pos": (3000.0, 0.0, 0.0)}]
    bot._observed_snap = snap
    bot._tick(dict(snap))
    snap["enemies"] = []
    t[0] = 9.0
    bot._observed_snap = snap
    bot._tick(dict(snap))
    assert bot.stats["phase"] == "hunt_spawns"
    snap["enemies"] = [{"ptr": 13, "slot": 2, "hp": 800, "hp_max": 800, "pos": (200.0, 0.0, 0.0)}]
    t[0] = 9.5
    bot._observed_snap = snap
    bot._tick(dict(snap))
    assert bot.stats["phase"] != "hunt_spawns"              # a Majini: the fight has him
    assert bot.stats["spawns"] == 2
    bot.trace_finish()                                       # a stop / the next round: the stage remembers
    saved = json.loads((tmp_path / R.SPAWNS_FILE).read_text())
    assert [pt[0] for pt in saved["Experimental_Facility"]] == [3000.0, 200.0]
    again = quiet_bot(tmp_path, lambda: 30.0)
    assert [pt[0] for pt in again._stage_spawns()] == [3000.0, 200.0]


def test_the_first_round_on_a_stage_with_no_spawn_point_known_stands_as_before(tmp_path):
    t = [0.0]
    snap, bot = scene(), quiet_bot(tmp_path, lambda: t[0])
    snap["bonuses"], snap["enemies"] = [], []
    for t[0] in (0.0, 9.0):
        bot._observed_snap = snap
        action = bot._tick(dict(snap))
    assert bot.stats["phase"] in ("stand", "idle") and action == {"hold": set()}
    assert bot.stats["hunt"] == "no spawn point known for this stage yet"
