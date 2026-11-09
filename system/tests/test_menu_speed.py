"""Learned menu cadence: faster after confirmed steps, slower after misses, persisted per title."""
import json

from gbox.mercs import menu_speed


def _step(speed, where, latency):
    speed.pressed(speed.last_where)
    speed.observed(where, now=speed.clock() + latency)


def test_confirmed_fast_steps_lower_the_cadence_and_record_the_latency():
    speed = menu_speed.Speed()
    start = speed.profile()["stable_s"]
    where = "main_menu"
    for index in range(8):
        nxt = "play_game" if index % 2 == 0 else "main_menu"
        _step(speed, nxt, 0.11)
        where = nxt
    assert speed.profile()["stable_s"] < start
    assert speed.stats()["fast_steps"] >= 6
    assert speed.data["confirm_ms"] is not None and 80 <= speed.data["confirm_ms"] <= 160


def test_a_missed_confirmation_slows_the_cadence_again():
    speed = menu_speed.Speed()
    before = speed.profile()["stable_s"]
    _step(speed, "play_game", 0.12)          # first observation only initialises
    _step(speed, "extra_content", 0.12)
    fast = speed.profile()["stable_s"]
    _step(speed, "main_menu", 2.5)           # a slow/missed confirmation
    assert speed.profile()["stable_s"] > fast
    assert speed.stats()["misses"] == 1
    assert speed.profile()["stable_s"] <= menu_speed.MAX_STABLE_S
    assert before == menu_speed.default_profile()["stable_s"]


def test_the_profile_round_trips_through_disk(tmp_path):
    path = tmp_path / "menu_speed.json"
    speed = menu_speed.Speed.load(path)
    _step(speed, "play_game", 0.12)
    _step(speed, "extra_content", 0.12)
    assert path.is_file()
    loaded = menu_speed.Speed.load(path)
    assert loaded.profile() == speed.profile()
    assert json.loads(path.read_text(encoding="utf-8"))["steps"] >= 1


def test_the_cadence_is_bounded_both_ways():
    speed = menu_speed.Speed()
    for index in range(200):
        _step(speed, "s%d" % (index % 2), 0.0)
    assert speed.profile()["stable_s"] >= menu_speed.MIN_STABLE_S
    for index in range(200):
        _step(speed, "slow%d" % (index % 2), 5.0)
    assert speed.profile()["stable_s"] <= menu_speed.MAX_STABLE_S
