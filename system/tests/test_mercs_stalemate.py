"""The Mercenaries stalemate rule (gbox.mercs.stalemate): no enemies for 15 s with time on the clock -> the clock is cut
to the configured seconds once per round, in the RE5 bot through the verified aGame owner write; its settings ride the
MercMode launch block like rounds_per_title (operator 2026-10-26)."""
from types import SimpleNamespace

import pytest

from gbox import mercmode as M, re5_mods_tool as T
from gbox.mercs import stalemate as S
from gbox.mercs.titles import re5_ps3 as R
from test_re5_mods import FakeRE5, fresh_originals  # noqa: F401
from test_re5_mods_time import GAME, GS, with_round


def test_defaults_and_launch_settings():
    assert S.settings(None) == {"enabled": True, "seconds": 5}
    assert S.settings({"stalemate_cut": False, "stalemate_cut_s": 12}) == {"enabled": False, "seconds": 12}
    assert S.settings({"stalemate_cut": "no", "stalemate_cut_s": 999}) == {"enabled": True, "seconds": 5}
    stats = {}
    assert S.configure(stats, {"launch": {"mercmode": {"stalemate_cut": True, "stalemate_cut_s": 30}}}) == {"enabled": True, "seconds": 30}
    assert stats == {"stalemate_cut_enabled": True, "stalemate_cut_s": 30}
    S.configure(stats, None)
    assert stats == {"stalemate_cut_enabled": True, "stalemate_cut_s": 5}


def test_rule_waits_fifteen_seconds_without_enemies_after_seeing_one_and_cuts_once():
    stats = {}
    rule = S.Rule(stats)
    assert rule.observe(0.0, 0, 100.0) is None                    # never saw an enemy: a slow start is not a stalemate
    assert rule.observe(20.0, 0, 100.0) is None
    assert rule.observe(21.0, 2, 100.0) is None                   # Majini out
    assert rule.observe(22.0, 0, 100.0) is None                   # all gone at 22
    assert rule.observe(36.9, 0, 100.0) is None and stats["stalemate_idle_s"] == 14.9
    assert rule.observe(37.0, 0, 9.0) is None                     # not with 9 s left: the round ends on its own
    assert rule.observe(37.0, 0, 100.0) == 5
    row = rule.record(37.0, {"verified": True, "clock_before": 100.0, "clock_after": 5.0})
    assert row == {"at": 37.0, "idle_s": 15.0, "target_s": 5, "clock_before": 100.0, "clock_after": 5.0,
                   "verified": True, "attempt": 1}
    assert stats["stalemate_cut"] == row and stats["stalemate_cuts"] == 1
    assert "clock cut 100.0 -> 5.0" in stats["stalemate_status"]
    assert rule.observe(60.0, 0, 100.0) is None                   # once per round
    rule.new_round()
    assert rule.observe(61.0, 0, 100.0) is None                   # the new round has not shown an enemy yet


def test_rule_settings_retries_and_the_target_never_adds_time():
    stats = {"stalemate_cut_enabled": False}
    rule = S.Rule(lambda: stats)                                  # the engines rebind bot.stats: a getter follows it
    rule.observe(0.0, 1, 100.0)
    assert rule.observe(0.0, 0, 100.0) is None and rule.observe(30.0, 0, 100.0) is None    # switched off
    stats["stalemate_cut_enabled"], stats["stalemate_cut_s"] = True, 20
    assert rule.observe(30.0, 0, 100.0) == 20
    rule.record(30.0, {"verified": False, "reason": "owner changed"})
    assert stats["stalemate_cut"]["reason"] == "owner changed" and "stalemate_cuts" not in stats
    assert "not verified" in stats["stalemate_status"]
    assert rule.observe(31.0, 0, 100.0) is None                   # RETRY_S apart
    assert rule.observe(32.5, 0, 12.0) == 12                      # the clock under the target: never raised
    rule.record(32.5, {"verified": False})
    assert rule.observe(35.0, 0, 100.0) == 20
    rule.record(35.0, {"verified": False})
    assert rule.observe(40.0, 0, 100.0) is None and rule.done    # three attempts a round, then it rests
    trace = SimpleNamespace(events=[])
    trace.event = lambda now, kind, x, z, **info: trace.events.append((kind, x, z, info))
    rule.new_round()
    rule.observe(50.0, 1, 100.0)
    rule.observe(51.0, 0, 100.0)
    assert rule.observe(66.0, 0, 100.0) == 20
    rule.record(66.0, {"verified": True, "clock_before": 90.0, "clock_after": 20.0}, trace=trace, pos=(1.0, 2.0, 3.0))
    assert trace.events == [("stalemate_cut", 1.0, 3.0, {"clock_before": 90.0, "clock_after": 20.0, "target_s": 20,
                                                          "idle_s": 15.0, "verified": True})]
    assert S.cut_seconds("61") == 5 and S.cut_seconds(" 7 ") == 7 and S.cut_seconds(None) == 5


def test_the_re5_bot_cuts_the_authoritative_countdown_after_a_stalemate(tmp_path):
    now = [100.0]
    bot = R.Bot(learn_dir=tmp_path, clock=lambda: now[0])
    m = with_round(FakeRE5(), clock=120.0)
    bot.m = SimpleNamespace(adapter=m)
    majini = {"ptr": 0x30A00000, "pos": (0., 0., 0.), "hp": 500, "hp_max": 500}
    crow = {"ptr": 0x30A00100, "pos": (0., 0., 0.), "hp": 1, "hp_max": 1}
    p = {"ptr": 0x303F89E0, "pos": (10., 0., 20.)}
    bot._stalemate_watch({"enemies": [majini], "timer": 120.0}, p, now[0])
    now[0] = 101.0
    bot._stalemate_watch({"enemies": [crow], "timer": 119.0}, p, now[0])       # a crow is no enemy (as in combat)
    now[0] = 115.9
    bot._stalemate_watch({"enemies": [], "timer": 105.0}, p, now[0])
    assert m.rf(GAME + T.GAME_CLOCK) == 120.0 and "stalemate_cut" not in bot.stats
    now[0] = 116.0
    bot._stalemate_watch({"enemies": [], "timer": 105.0}, p, now[0])
    assert m.rf(GAME + T.GAME_CLOCK) == 5.0                                      # the owner's countdown: 5 s
    cut = bot.stats["stalemate_cut"]
    assert cut["verified"] and cut["clock_before"] == 120.0 and cut["clock_after"] == 5.0
    assert cut["target_s"] == 5 and cut["idle_s"] == 15.0 and bot.stats["stalemate_cuts"] == 1
    assert (GS + T.GS_SHOW_BONUS, 1) not in m.writes                             # a cut shows no "+NN Sec."
    now[0] = 140.0
    bot._stalemate_watch({"enemies": [], "timer": 100.0}, p, now[0])             # once per round
    assert bot.stats["stalemate_cuts"] == 1 and (GAME + T.GAME_CLOCK, 4) in m.writes
    assert sum(1 for w in m.writes if w == (GAME + T.GAME_CLOCK, 4)) == 1


def test_the_re5_bot_honours_the_launch_settings_and_reports_an_unverified_write(tmp_path):
    now = [0.0]
    stats = {}
    S.configure(stats, {"launch": {"mercmode": {"stalemate_cut_s": 9}}})      # as mercs_bot.play does from the launch
    bot = R.Bot(learn_dir=tmp_path, clock=lambda: now[0], stats=stats)
    m = with_round(FakeRE5(), clock=60.0)
    bot.m = SimpleNamespace(adapter=m)
    p = {"ptr": 1, "pos": (0., 0., 0.)}
    bot._stalemate_watch({"enemies": [{"hp": 9, "hp_max": 9}], "timer": 60.0}, p, 0.0)
    bot._stalemate_watch({"enemies": [], "timer": 59.0}, p, 1.0)
    bot._stalemate_watch({"enemies": [], "timer": 44.0}, p, 16.0)
    assert m.rf(GAME + T.GAME_CLOCK) == 9.0 and bot.stats["stalemate_cut"]["target_s"] == 9
    off = R.Bot(learn_dir=tmp_path, clock=lambda: now[0], stats={"stalemate_cut_enabled": False})
    m2 = with_round(FakeRE5(), clock=60.0)
    off.m = SimpleNamespace(adapter=m2)
    off._stalemate_watch({"enemies": [{"hp": 9, "hp_max": 9}], "timer": 60.0}, p, 0.0)
    off._stalemate_watch({"enemies": [], "timer": 59.0}, p, 1.0)
    off._stalemate_watch({"enemies": [], "timer": 44.0}, p, 16.0)
    assert m2.rf(GAME + T.GAME_CLOCK) == 60.0 and "stalemate_cut" not in off.stats and off.stats["stalemate_idle_s"] == 15.0
    broken = R.Bot(learn_dir=tmp_path, clock=lambda: now[0])
    m3 = with_round(FakeRE5(), clock=60.0)
    m3.u32(GAME, 0x1234)                                                          # the timer owner is not the aGame
    broken.m = SimpleNamespace(adapter=m3)
    broken._stalemate_watch({"enemies": [{"hp": 9, "hp_max": 9}], "timer": 60.0}, p, 0.0)
    broken._stalemate_watch({"enemies": [], "timer": 59.0}, p, 1.0)
    broken._stalemate_watch({"enemies": [], "timer": 44.0}, p, 16.0)
    cut = broken.stats["stalemate_cut"]
    assert cut["verified"] is False and "clock write unavailable" in cut["reason"] and "stalemate_cuts" not in broken.stats
    assert (GAME + T.GAME_CLOCK, 4) not in m3.writes                             # nothing written to a doubtful owner


def test_the_re5_cut_waits_for_the_spawn_hunt_where_spawn_points_are_known(tmp_path):
    """The spawn hunt (re5_ps3 LULL_S / _hunt_spawns) walks to the stage's known spawn points after a lull; the clock is
    cut only once it has had its chance (HUNT_STALEMATE_S), at STALEMATE_S where nothing is known to hunt."""
    now = [0.0]
    bot = R.Bot(learn_dir=tmp_path, clock=lambda: now[0])
    m = with_round(FakeRE5(), clock=200.0)
    bot.m = SimpleNamespace(adapter=m)
    bot._stage_spawns = lambda: [(100.0, 0.0, 200.0)]                           # spawn points known for this stage
    p = {"ptr": 1, "pos": (0., 0., 0.)}
    bot._stalemate_watch({"enemies": [{"hp": 9, "hp_max": 9}], "timer": 200.0}, p, 0.0)
    bot._stalemate_watch({"enemies": [], "timer": 199.0}, p, 1.0)
    bot._stalemate_watch({"enemies": [], "timer": 184.0}, p, 16.0)
    assert m.rf(GAME + T.GAME_CLOCK) == 200.0 and bot.stats["stalemate_patience_s"] == 45.0   # the hunt goes first
    bot._stalemate_watch({"enemies": [], "timer": 155.0}, p, 45.9)
    assert "stalemate_cut" not in bot.stats
    bot._stalemate_watch({"enemies": [], "timer": 154.0}, p, 46.0)
    assert m.rf(GAME + T.GAME_CLOCK) == 5.0 and bot.stats["stalemate_cut"]["idle_s"] == 45.0
    hunting = R.Bot(learn_dir=tmp_path, clock=lambda: now[0])
    hunting._stage_spawns = lambda: []                                          # nothing learned yet ...
    hunting._hunt = {"key": 0, "pos": (1., 0., 1.), "since": 0.0}               # ... but a hunt is under way
    assert hunting._can_hunt() is True
    hunting._hunt = None
    assert hunting._can_hunt() is False
    bare = R.Bot(learn_dir=tmp_path, clock=lambda: now[0])
    for attr in ("_stage_spawns", "_hunt"):
        if attr in vars(bare):
            delattr(bare, attr)                                                 # a tree without the hunt: 15 s flat
    bare.m = SimpleNamespace(adapter=with_round(FakeRE5(), clock=200.0))
    bare._stalemate_watch({"enemies": [{"hp": 9, "hp_max": 9}], "timer": 200.0}, p, 0.0)
    bare._stalemate_watch({"enemies": [], "timer": 199.0}, p, 1.0)
    bare._stalemate_watch({"enemies": [], "timer": 184.0}, p, 16.0)
    assert bare.stats["stalemate_patience_s"] == 15.0 and bare.stats["stalemate_cut"]["clock_after"] == 5.0


def test_observe_round_starts_the_watch_afresh_at_a_new_round(tmp_path):
    now = [0.0]
    bot = R.Bot(learn_dir=tmp_path, clock=lambda: now[0])
    bot.m = SimpleNamespace(adapter=object(), mercs_no_modifications=True)       # no maintenance writes in this test
    bot.stalemate.observe(0.0, 1, 100.0)
    bot.stalemate.observe(1.0, 0, 100.0)
    assert bot.stalemate.seen_enemy and bot.stalemate.no_enemy_since == 1.0
    snap = {"player": {"ptr": 1, "pos": (0., 0., 0.), "rot": 0.0, "hp": 1000, "hp_max": 1000, "action": 0},
            "timer": 100.0, "timer_start": 120.0, "enemies": [], "combo": 0}
    bot.observe_round(snap, "playing", 2.0)
    assert bot.round_active and not bot.stalemate.seen_enemy and bot.stalemate.no_enemy_since is None


def test_mercmode_settings_validate_and_ride_in_the_launch_block():
    cfg = M.normalize({})
    assert cfg["stalemate_cut"] is True and cfg["stalemate_cut_s"] == 5
    assert M.normalize({"stalemate_cut": False, "stalemate_cut_s": 30})["stalemate_cut_s"] == 30
    for patch in ({"stalemate_cut": 1}, {"stalemate_cut_s": 0}, {"stalemate_cut_s": 61}, {"stalemate_cut_s": 5.5}):
        with pytest.raises(ValueError, match="stalemate"):
            M.normalize(patch)
    block = M.launch_block(cfg, {"title": "re5", "mode": "reunion"})
    assert block == {"random_characters": True, "random_stages": True, "selection": {"title": "re5", "mode": "reunion"},
                     "stalemate_cut": True, "stalemate_cut_s": 5}
    assert S.settings(block) == {"enabled": True, "seconds": 5}
    stats = {}
    S.configure(stats, {"launch": {"mercmode": M.launch_block(M.normalize({"stalemate_cut_s": 9, "stalemate_cut": False}))}})
    assert stats == {"stalemate_cut_enabled": False, "stalemate_cut_s": 9}
    # the scheduler's presentation check still recognises its own launch with the rule in the block
    launch = {"game_id": M.TITLES["re4"]["game_ids"][0], "launch": {"mercmode": block}}
    assert {k: v for k, v in launch["launch"]["mercmode"].items() if k != "selection" and k not in M.STALEMATE_KEYS} \
        == {"random_characters": True, "random_stages": True}
