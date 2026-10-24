"""Instant operator commands (gbox.mercs.directives): matching typed words, the server store, the worker poll, the stats the
bots read, and what the RE4 bot does with each command."""
import math

import pytest
from fastapi.testclient import TestClient

from gbox import re4_merc_bot as B
from gbox.config import Config
from gbox import server
from gbox.mercs import directives as D
from tests.test_re4_merc_bot import FakeNav, facing, world


@pytest.mark.parametrize("text,command", [
    ("fight!", "fight"), ("fight them", "fight"), ("stop standing there", "fight"), ("get away from the line", "fight"),
    ("go to the next time bonus", "next_area"), ("go to the next area", "next_area"), ("move on", "next_area"),
    ("go after the enemies", "hunt"), ("seek the zombies", "hunt"), ("hunt them", "hunt"),
    ("navigate more of the level", "explore"), ("explore", "explore"),
    ("go for score increases", "score"), ("build the combo", "score"), ("increase the score", "score"),
    ("you are doing a repetitive action", "repetitive"), ("you keep going in circles", "repetitive"),
    ("drop a mine and flee", "mine"), ("plant a mine", "mine"),
    ("you are missing", "missing"), ("your aim is off", "missing"),
])
def test_typed_words_match_their_command(text, command):
    assert D.match(text) == command


@pytest.mark.parametrize("text", ["", "x", "nice run", "the wall is ugly", "stop getting hit", "a" * 200,
                                  "I think the fight scene looks great in the trailer, wonderful graphics overall"])
def test_ordinary_notes_stay_plain_coaching_notes(text):
    assert D.match(text) is None


def test_reader_acts_on_a_fresh_command_then_for_its_hold_window_only():
    r = D.Reader()
    stats = {}
    D.apply_to_stats(stats, D.post("w-1", "fight", now=100.0))
    assert r.current(stats, 100.5) == ("fight", True)
    assert r.current(stats, 110.0) == ("fight", False)                     # standing mode: 15 s
    assert r.current(stats, 116.0) == (None, False)
    D.apply_to_stats(stats, D.post("w-1", "next_area", now=200.0))
    assert r.current(stats, 200.1) == ("next_area", True)
    assert r.current(stats, 200.2) == (None, False)                        # a one-shot is done after its tick
    D.apply_to_stats(stats, D.latest("w-1"))                               # the same command polled again changes nothing
    assert r.current(stats, 200.3) == (None, False)
    with pytest.raises(ValueError):
        D.post("w-1", "dance")


def test_endpoints_and_typed_chat_words_post_the_command(tmp_path):
    cfg = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c")
    app = server.create_app(cfg)
    app.state.store.put("session", "w-s", {"session_id": "w-s", "state": "running", "game_id": "g"})
    with TestClient(app, headers={"Authorization": "Bearer " + cfg.token()}) as c:
        assert c.get("/api/sessions/w-s/directive").json()["directive"] is None
        assert c.post("/api/sessions/w-s/directive", json={"command": "dance"}).status_code == 422
        r = c.post("/api/sessions/w-s/directive", json={"command": "hunt"}).json()["directive"]
        assert r["command"] == "hunt" and r["until"] > r["at"]
        assert c.get("/api/sessions/w-s/directive").json()["directive"]["seq"] == r["seq"]


def at(m, now, hold=None):
    m.put(B.MERC_TIMER, ">I", int((100 - now) * 30))


def drive(bot, m, now, ticks=3):
    out = None
    for i in range(ticks):
        now[0] += 0.1
        at(m, now[0])
        out = bot.tick(B.snapshot(m))
    return out


def command(bot, name):
    D.apply_to_stats(bot.stats, D.post("w-test", name, now=__import__("time").time()))


def test_re4_hunt_goes_after_a_far_enemy_ahead_of_the_time_bonus():
    now = [0.0]
    m = world([((0.0, 0.0, 6000.0), True)], leon=(0.0, 0.0, 0.0), timer_s=100.0)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=None)
    bot.bonus = [(8000.0, -8000.0)]
    command(bot, "hunt")
    act = drive(bot, m, now)
    assert {"up", "b"} <= act["hold"] and "status" not in act
    assert "going after the nearest enemy" in bot.stats["directive_status"] and bot.stats["directive_active"] == "hunt"


def test_re4_next_area_rotates_to_the_next_time_bonus_once():
    now = [0.0]
    m = world([], leon=(0.0, 0.0, 0.0), timer_s=100.0)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=None)
    bot._round(0x400)                                                       # (a new room resets the round's lists)
    bot.bonus = [(0.0, 3000.0), (3000.0, 0.0)]
    bot.goal = {"pos": (0.0, 3000.0), "since": 0.0, "path": [(0.0, 3000.0)]}
    command(bot, "next_area")
    drive(bot, m, now, 1)
    assert bot.bonus[0] == (3000.0, 0.0) and bot.stats["directive_status"] == "skipped to the next time bonus"
    drive(bot, m, now, 3)
    assert bot.bonus[0] == (3000.0, 0.0)                                   # a one-shot: not rotated again


def test_re4_repetitive_backs_off_then_explores_forward_and_forgets_the_target():
    now = [0.0]
    m = world([((0.0, 0.0, 3500.0), True)], leon=(0.0, 0.0, 0.0), timer_s=100.0)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=None)
    command(bot, "repetitive")
    first = drive(bot, m, now, 1)
    assert first == {"hold": {"down"}} and bot.skip[1] > now[0]
    later = drive(bot, m, now, 12)                                           # the back-off ends: a forward leg
    assert {"up", "b"} <= later["hold"] and bot.explore is not None


def test_re4_explore_picks_the_heading_with_the_least_walked_ground_and_never_through_a_learned_wall():
    now = [0.0]
    m = world([], leon=(0.0, 0.0, 0.0), timer_s=100.0)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=None)
    bot._round(0x400)
    for i in range(0, 6):
        bot.learned.walked[(0, i)] = 5                                       # +z is well walked
    bot.learned.block_cell((1, 0))                                           # a wall to the +x side
    command(bot, "explore")
    drive(bot, m, now, 1)
    gx, gz = bot.explore["goal"]
    assert not (abs(gx) < 600 and gz > 1500)                                 # not straight up the walked +z corridor
    assert bot.learned.crosses((0.0, 0.0), (gx, gz)) is None                 # and not through the learned wall


def test_re4_missing_moves_the_aim_height_offset_and_mine_is_honestly_unavailable():
    now = [0.0]
    m = world([], leon=(0.0, 0.0, 0.0), timer_s=100.0)
    facing(m, 0.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=None)
    before = bot.pitch_i
    command(bot, "missing")
    drive(bot, m, now, 1)
    assert bot.pitch_i == (before + 1) % len(B.PITCH_STEPS) and "aim height offset" in bot.stats["directive_status"]
    command(bot, "mine")
    drive(bot, m, now, 1)
    assert "no mines" in bot.stats["directive_status"]
