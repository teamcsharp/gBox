"""The universal Mercenaries doctrine (gbox.mercs.core.doctrine): the operator's standing goals for every title
(2026-11-09), weighed every half second, measured every tick, and issued as the commands every bot already takes."""
import math

from gbox.mercs import directives
from gbox.mercs.core import doctrine as D


def foe(d, deg=0.0, hp=800, hp_max=800, **kw):
    a = math.radians(deg)
    return {"pos": (d * 100 * math.sin(a), 0.0, d * 100 * math.cos(a)), "hp": hp, "hp_max": hp_max, **kw}


def snap(foes=(), pos=(0.0, 0.0, 0.0), kills=0, combo=0):
    return {"player": {"pos": pos, "hp": 1000, "hp_max": 1000}, "enemies": list(foes), "kills": kills, "combo": combo}


def run(director, frames, start=1000.0, dt=1 / 30):
    """frames: an iterable of (snapshot, action); ticked dt apart. -> the clock after the last one."""
    now = start
    for s, act in frames:
        director.observe(D.view(s), act, now)
        now += dt
    return now


def test_the_view_reads_the_common_snapshot_in_metres_and_names_bosses_and_windups():
    class Mod:
        WINDUP_MOTIONS = frozenset({80})
        E_ATTACKING = 0x80
    v = D.view(snap([foe(2.0), foe(10.0, hp_max=5000), foe(3.0, motion=80), foe(4.0, act=0x80), foe(1.0, hp=0)]),
               module=Mod)
    assert v["pos"] == (0.0, 0.0) and [round(f["d"], 1) for f in v["foes"]] == [2.0, 10.0, 3.0, 4.0]   # the dead one is gone
    assert [f["boss"] for f in v["foes"]] == [False, True, False, False]
    assert [f["windup"] for f in v["foes"]] == [False, False, True, True]
    assert D.view({"player": None}) is None and D.view({}) is None
    # another title's units (RE4 is in mm) and position key
    class Mm:
        units_per_m = 1000.0
    v = D.view({"player": {"r": (1000.0, 0.0, 0.0)}, "enemies": [{"r": (4000.0, 0.0, 0.0), "hp": 5}]}, drv=Mm())
    assert v["pos"] == (1.0, 0.0) and round(v["foes"][0]["d"], 3) == 3.0


def test_standing_among_enemies_without_attacking_is_a_violation_and_fight_goes_out_at_once():
    """The operator's floor: "it's unacceptable for the bot to let enemies close in on him without dispatching them
    with a weapon ... I do not like seeing the bot idle in any title"."""
    stats = {}
    d = D.Director(stats)
    d.reset(1000.0)
    crowd = snap([foe(2.0), foe(3.0, 90)])
    now = run(d, [(crowd, {"hold": ()})] * 70)                          # 2.3 s of nothing, two Majini in reach
    assert stats["doctrine_violations"] >= 1 and stats["doctrine_goal"] == "engage"
    assert stats["doctrine_directive"] == "fight" and stats["doctrine_directive_until"] > now
    assert stats["doctrine_idle_s"] > 2.0 and stats["doctrine_passive_s"] > 2.0
    assert stats["doctrine_longest_idle_s"] > 2.0 and stats["doctrine_engaged_pct"] < 10
    # the same crowd with the gun up and firing: engaged, nothing idle accrues
    stats2 = {}
    d2 = D.Director(stats2)
    d2.reset(1000.0)
    run(d2, [(crowd, {"hold": ("zl", "zr")})] * 70)
    assert stats2["doctrine_violations"] == 0 and stats2["doctrine_idle_s"] == 0 and stats2["doctrine_passive_s"] == 0
    assert stats2["doctrine_engaged_pct"] == 100.0


def test_the_combo_window_asks_for_a_kill_between_two_and_five_seconds():
    """"Every 2-5 seconds the player needs to be extending the combo never letting it drop.\""""
    stats = {}
    d = D.Director(stats)
    d.reset(1000.0)
    far = snap([foe(9.0)], kills=3, combo=3)                             # in sight, not in his way, and he is firing
    firing = {"hold": ("zl", "zr", "lup")}
    now = run(d, [(far, firing)] * 45)                                   # 1.5 s since the round began: nothing owed yet
    assert stats["doctrine_directive"] != "score" if "doctrine_directive" in stats else True
    now = run(d, [(far, firing)] * 120, start=now)                       # 5.5 s without a kill
    assert stats["doctrine_goal"] == "combo" and stats["doctrine_directive"] == "score"
    assert stats["doctrine_since_kill_s"] > 5.0
    killed = snap([foe(9.0)], kills=4, combo=4)
    run(d, [(killed, firing)] * 20, start=now)                           # a kill: the window starts again
    assert stats["doctrine_since_kill_s"] < 1.0 and stats["doctrine_goal"] != "combo"


def test_posturing_in_one_place_sends_him_on_and_new_ground_counts_as_explored():
    """"The bot spends too much time in the same place and needs to have the goal of exploring the entire level.\""""
    stats = {}
    d = D.Director(stats, weights_of=lambda: dict(D.WEIGHTS, combo=0.0))  # (the combo aside: only the anchor here)
    d.reset(1000.0)
    far = snap([foe(12.0)])
    now = run(d, [(far, {"hold": ("zl", "zr")})] * int(30 * (D.ANCHOR_MAX_S + 1)))   # 21 s firing from one spot
    assert stats["doctrine_goal"] == "explore" and stats["doctrine_directive"] == "hunt"
    assert stats["doctrine_anchor_s"] >= D.ANCHOR_MAX_S and stats["doctrine_cells"] == 1
    # he runs: 30 m in 5 s - the anchor moves with him and the squares add up
    frames = [(snap([foe(12.0)], pos=(i * 20.0, 0.0, 0.0)), {"hold": ("lup", "b")}) for i in range(150)]
    run(d, frames, start=now)
    assert stats["doctrine_anchor_s"] < 2.0 and stats["doctrine_cells"] >= 6 and stats["doctrine_goal"] != "explore"


def test_a_mob_gets_explosives_with_a_gap_between_them():
    """"Spam grenades / grenade launcher / mines / remote mines to mobs.\""""
    stats = {}
    d = D.Director(stats, weights_of=lambda: {"engage": 0.3, "combo": 0.0, "explore": 0.0, "explosives": 1.0, "boss": 0.0})
    d.reset(1000.0)
    mob = snap([foe(4.5, a) for a in (0, 60, 120, 180, 240, 300)])
    now = run(d, [(mob, {"hold": ("zl", "zr")})] * 5)                    # the first decision
    assert stats["doctrine_goal"] == "explosives" and stats["doctrine_directive"] == "mine"
    assert directives.Reader().current(stats, now) == ("mine", True)     # a one-shot: the bot takes it on its next tick
    now = run(d, [(mob, {"hold": ("zl", "zr")})] * 60, start=now)        # 2 s on: no second one inside the gap
    assert stats["doctrine_commands"] == 1 and stats.get("doctrine_directive") != "mine"
    run(d, [(mob, {"hold": ("zl", "zr")})] * int(30 * D.EXPLOSIVE_GAP_S), start=now)
    assert stats["doctrine_commands"] == 2                                # ... and the next one after it


def test_the_weights_decide_between_goals_and_a_title_module_can_carry_its_own():
    class Title:
        GOAL_EXPLORE, GOAL_COMBO = 0.1, 2.5          # (clamped to 0..1)
        GOAL_ENGAGE = True                            # not a number: the default stands
    w = D.weights(Title)
    assert w["explore"] == 0.1 and w["combo"] == 1.0 and w["engage"] == D.WEIGHTS["engage"]
    assert D.weights(None) == D.WEIGHTS
    stats = {}
    d = D.Director(stats, weights_of=lambda: {"engage": 0.0, "combo": 0.0, "explore": 0.0, "explosives": 0.0, "boss": 0.0})
    d.reset(1000.0)
    run(d, [(snap([foe(9.0)]), {"hold": ("zl", "zr", "lup")})] * 200)   # every weight at zero: no command at all
    assert stats["doctrine_goal"] is None and "doctrine_directive" not in stats
    assert "no goal pressing" in stats["doctrine_status"]


def test_the_operators_own_command_always_wins_and_the_doctrine_only_measures():
    stats = {"directive": "explore", "directive_seq": 7, "directive_until": 2000.0}
    d = D.Director(stats)
    d.reset(1000.0)
    run(d, [(snap([foe(2.0)]), {"hold": ()})] * 90)
    assert "doctrine_directive" not in stats and "operator" in stats["doctrine_status"]
    assert stats["doctrine_passive_s"] > 2.0                             # still measured
    reader = directives.Reader()
    assert reader.current(stats, 1003.0) == ("explore", True)            # theirs, fresh once
    assert reader.current(stats, 1003.1) == ("explore", False)


def test_every_bot_reads_a_doctrine_command_like_a_typed_one():
    """directives.Reader: the operator's first; with none in force, the doctrine's - fresh once per issue."""
    reader = directives.Reader()
    stats = {}
    assert reader.current(stats, 10.0) == (None, False)
    stats.update(doctrine_directive="fight", doctrine_directive_seq="d1", doctrine_directive_until=14.0)
    assert reader.current(stats, 10.0) == ("fight", True)
    assert reader.current(stats, 11.0) == ("fight", False)
    stats.update(doctrine_directive_until=18.0)                          # extended while its goal still wins: not fresh
    assert reader.current(stats, 15.0) == ("fight", False)
    assert reader.current(stats, 19.0) == (None, False)                  # lapsed
    stats.update(doctrine_directive="score", doctrine_directive_seq="d2", doctrine_directive_until=25.0)
    assert reader.current(stats, 20.0) == ("score", True)
    stats.update(directive="hunt", directive_seq=3, directive_until=30.0)   # the operator types one: theirs now
    assert reader.current(stats, 21.0) == ("hunt", True)
    stats.update(doctrine_directive="not-a-command", doctrine_directive_seq="d3", doctrine_directive_until=99.0)
    assert reader.current(stats, 31.0) == (None, False)                  # an unknown word is never a command


def test_every_rule_has_a_weight_and_only_known_commands_are_issued():
    assert set(D.WEIGHTS) == set(D.GOALS) == {"engage", "combo", "explore", "explosives", "interrupt", "boss"}
    assert all(cmd is None or cmd in directives.COMMANDS for cmd in D.COMMAND.values())
    for title in ("re5", "re6"):                                          # both Switch titles carry the wheel's dots
        from gbox.mercs import bot_logic
        from gbox.mercs.core import control_axes as AX
        import importlib
        mod = importlib.import_module(bot_logic.MODULES[title])
        knobs = {k[0] for k in bot_logic.KNOBS[title]}
        for goal in ("engage", "combo", "explore", "explosives", "boss"):
            assert hasattr(mod, "GOAL_" + goal.upper()) and "GOAL_" + goal.upper() in knobs
            assert AX.MAPS[title]["goal_" + goal] == (("behavior.GOAL_" + goal.upper(), "pass"),)
        assert D.weights(mod) == D.WEIGHTS                                # shipped at the operator's stated priorities


def test_a_gap_between_ticks_never_counts_as_idle_time():
    stats = {}
    d = D.Director(stats)
    d.reset(1000.0)
    crowd = snap([foe(2.0)])
    d.observe(D.view(crowd), {"hold": ("zl", "zr")}, 1000.0)
    d.observe(None, None, 1001.0)                                        # a menu / loading: no player
    d.observe(D.view(crowd), {"hold": ("zl", "zr")}, 1060.0)             # back a minute later
    assert stats["doctrine_played_s"] == 0.0 and stats["doctrine_idle_s"] == 0.0


def test_the_doctrines_own_reader_works_over_a_directives_reader_from_before_the_doctrine():
    """directives is never hot-reloaded: a worker that has not restarted keeps a Reader that knows only the operator's
    commands. The bots build doctrine.Reader, which adds the doctrine's on top and never hands one over twice."""
    class Old:                                                            # directives.Reader as it was before today
        def __init__(self):
            self.seen = None

        def current(self, stats, now=None):
            cmd, seq = stats.get('directive'), stats.get('directive_seq')
            if not cmd or seq is None:
                return None, False
            fresh = seq != self.seen
            self.seen = seq
            if fresh or now < float(stats.get('directive_until') or 0):
                return cmd, fresh
            return None, False
    for base in (Old, directives.Reader):
        r = D.Reader()
        r.base = base()
        stats = {}
        assert r.current(stats, 10.0) == (None, False)
        stats.update(doctrine_directive="fight", doctrine_directive_seq="d1", doctrine_directive_until=14.0)
        assert r.current(stats, 10.0) == ("fight", True), base.__name__
        assert r.current(stats, 11.0) == ("fight", False), base.__name__
        stats.update(directive="explore", directive_seq=4, directive_until=30.0)      # the operator's wins
        assert r.current(stats, 12.0) == ("explore", True), base.__name__
        assert r.current(stats, 13.0) == ("explore", False), base.__name__
        stats.update(doctrine_directive="score", doctrine_directive_seq="d2", doctrine_directive_until=50.0)
        assert r.current(stats, 20.0) == ("explore", False), base.__name__            # still theirs
        assert r.current(stats, 31.0) == ("score", True), base.__name__               # theirs lapsed: the doctrine's
        assert r.current(stats, 32.0) == ("score", False), base.__name__
