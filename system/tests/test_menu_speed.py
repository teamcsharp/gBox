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


# --- per screen, the jump records and the transitions (2026-11-09) --------------------------------------------------
class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _speed(path=None):
    clock = Clock()
    return (menu_speed.Speed.load(path, clock=clock) if path else menu_speed.Speed(clock=clock)), clock


def _taken(speed, clock, where, key="a", cursor=None, after=0.05, unit=1):
    """A press on `where` that RAM shows taken `after` seconds later (the cursor moves, or the screen changes)."""
    speed.press(where, key)
    clock.t += after
    if cursor is not None:
        speed.seen(where, (where, unit, cursor))
    else:
        speed.seen(where + "_next", (where + "_next", unit + 1, None))
        speed.seen(where, (where, unit, None))                          # back on the screen for the next press


def test_each_screen_learns_its_own_settle_faster_on_every_taken_press():
    speed, clock = _speed()
    speed.seen("results", ("results", 1, None))
    start = speed.hints("results")["settle_s"]
    assert start == menu_speed.SCREEN_KNOBS["settle_s"][0]
    for _ in range(10):
        _taken(speed, clock, "results")
    rec = speed.screen("results")
    assert rec["settle_s"] < start * 0.92 ** 5 and rec["hits"] == 10 and rec["misses"] == 0
    assert speed.screen("select_stage")["settle_s"] == start          # another screen keeps its own
    assert 40 <= rec["confirm_ms"] <= 60


def test_a_press_ram_never_showed_slows_its_screen_and_its_value_becomes_the_floor():
    speed, clock = _speed()
    speed.seen("alert_ok", ("alert_ok", 1, None))
    for _ in range(25):
        _taken(speed, clock, "alert_ok")
    fast = speed.screen("alert_ok")["settle_s"]
    speed.press("alert_ok", "a")
    clock.t += menu_speed.CONFIRM_MISS_S + 0.1
    speed.seen("alert_ok", ("alert_ok", 1, None))                     # nothing changed: not taken
    rec = speed.screen("alert_ok")
    assert rec["misses"] == 1 and rec["settle_s"] > fast * 1.4
    assert rec["floors"]["settle_s"] == round(fast, 4)
    for _ in range(40):
        _taken(speed, clock, "alert_ok")
    assert speed.screen("alert_ok")["settle_s"] >= fast * 1.1 * menu_speed.FLOOR_DECAY ** 40 - 1e-6
    lo, hi = menu_speed.SCREEN_KNOBS["settle_s"][1:]
    assert lo <= speed.screen("alert_ok")["settle_s"] <= hi


def test_a_second_press_on_an_unchanged_screen_counts_the_first_as_missed_and_dpad_learns_its_own_knobs():
    speed, clock = _speed()
    speed.seen("select_stage", ("select_stage", 7, 0))
    speed.press("select_stage", "dright")
    clock.t += 0.3
    speed.press("select_stage", "dright")                             # the Navigator's retry: the first was not taken
    rec = speed.screen("select_stage")
    assert rec["misses"] == 1 and rec["dir_hold_s"] == menu_speed.SCREEN_KNOBS["dir_hold_s"][2]
    clock.t += 0.04
    speed.seen("select_stage", ("select_stage", 7, 1))                # the cursor moved: the retry was taken
    assert rec["hits"] == 1 and speed.change_kind == "step"
    speed.press("select_stage", "dright")
    assert set(speed.pending["knobs"]) == {"step_s", "dir_hold_s", "retry_s"}   # after a cursor move: its step wait


def test_hints_never_exceed_the_navigators_own_waits_and_skip_loading():
    speed, _ = _speed()
    speed.seen("results", ("results", 1, None))
    for _ in range(30):
        speed.press("results", "a")                                   # every one missed
    h = speed.hints("results")
    assert h["settle_s"] <= 0.5 and h["hold_s"] <= 0.30 and h["dir_hold_s"] <= 0.18 and h["retry_s"] <= 1.2
    assert h["poll_s"] == menu_speed.FAST_POLL_S
    assert speed.hints("loading") == {} and speed.hints("playing") == {}


def test_the_screens_and_their_jump_records_round_trip_through_disk(tmp_path):
    path = tmp_path / "menu_speed.json"
    speed, clock = _speed(path)
    speed.seen("select_stage", ("select_stage", 1, 0))
    _taken(speed, clock, "select_stage", key="dright", cursor=1)
    speed.jump_result("select_stage", "wrote")
    speed.jump_result("select_stage", "proven")
    speed.note_cursor("select_player", 9)
    speed.save()
    loaded = menu_speed.Speed.load(path)
    rec = loaded.screen("select_stage")
    assert rec["jumps"] == 1 and rec["jump_proven"] == 1 and rec["hits"] == 1
    assert loaded.screen("select_player")["max_cursor"] == 9
    assert loaded.profile() == speed.profile()                         # the old cadence beside it, unchanged


def test_a_screen_that_fails_its_jumps_goes_back_to_stepping_until_reset():
    speed, _ = _speed()
    assert speed.jump_allowed("select_stage") and not speed.jump_direct("select_stage", 3)
    for _ in range(3):
        speed.jump_result("select_stage", "proven")
    assert speed.jump_direct("select_stage", 3)
    speed.jump_result("select_stage", "failed", 2)
    speed.jump_result("select_stage", "failed", 2)
    assert speed.jump_allowed("select_stage")                         # 2 failures, 3 proofs: still trusted
    speed.jump_result("select_player", "failed", 2)
    speed.jump_result("select_player", "failed", 2)
    assert not speed.jump_allowed("select_player")
    speed.jumps_reset()
    assert speed.jump_allowed("select_player")


def _walk(speed, clock, screens, each=0.5):
    for where in screens:
        speed.seen(where, (where, hash(where) & 0xFFFF, None))
        speed.press(where, "a")
        clock.t += each


def test_a_transition_times_the_menus_and_the_seconds_to_gameplay_with_a_best_and_a_trend():
    speed, clock = _speed()
    speed.begin_run()
    _walk(speed, clock, ["alert_ok", "main_menu", "play_game", "extra_content", "mercs_title", "mercs_mode",
                         "select_stage", "select_player"])
    speed.seen("loading", ("loading", 0, None))                         # the last select confirmed: menus done
    clock.t += 12.0
    speed.seen("intro", ("intro", None, None))
    clock.t += 8.0
    boot = speed.gameplay()
    assert boot["kind"] == "boot" and boot["menu_s"] == 4.0 and boot["play_s"] == 24.0 and boot["presses"] == 8
    assert "select_stage 0.5s/1p" in boot["screens"] and "loading 12.0s/0p" in boot["screens"]
    for menu_each in (1.0, 0.6, 0.3):                                   # three rounds, each walk faster
        clock.t += 60.0                                                  # the round
        speed.round_end()                                                # its death / results
        clock.t += 2.0                                                   # the engine's tail
        _walk(speed, clock, ["alert_ok", "results", "select_stage", "select_player"], menu_each)
        speed.seen("loading", ("loading", 0, None))
        clock.t += 10.0
        speed.gameplay()
    view = speed.stats_view()
    assert view["menu_seconds"] == 3.2 and view["menu_seconds_best"] == 3.2
    assert view["menu_seconds_trend"] == "6, 4.4, 3.2" and view["menu_play_trend"] == "16, 14.4, 13.2"
    assert view["menu_boot_seconds"] == 4.0 and view["menu_last_kind"] == "next"
    assert speed.status()["text"] == "menus: 3.2 s (best 3.2 s) · to play 13.2 s"
    assert speed.status()["trend"] == [6.0, 4.4, 3.2]


def test_a_round_end_counts_only_after_a_clock_ran_and_continue_yes_is_a_retry():
    speed, clock = _speed()
    speed.round_end()                                                  # a round's first frames read as results
    assert speed.open is None
    speed.gameplay()                                                   # the run began inside a round
    clock.t += 30
    speed.round_end()
    speed.round_end()                                                  # every dead tick after the first: nothing new
    clock.t += 5.5
    rec = speed.gameplay()                                             # Continue? Yes: the clock runs again, no menus
    assert rec["kind"] == "retry" and rec["play_s"] == 5.5
    assert "menu_seconds" not in speed.stats_view()                    # no round-to-round walk timed yet


def test_a_preparation_never_counts_in_the_best_and_stale_transitions_are_dropped():
    speed, clock = _speed()
    speed.begin_run(prepare=True)
    _walk(speed, clock, ["main_menu", "select_stage", "select_player"], 0.1)
    speed.seen("intro", ("intro", None, None))
    clock.t += 300                                                       # paused in the background
    speed.begin_run()                                                    # the switch: the real autoplay starts
    assert speed.data["transitions"][-1]["kind"] == "prepare" and speed.data["transitions"][-1]["play_s"] is None
    assert not speed.data.get("best")
    assert speed.gameplay() is None and speed.in_round
    speed.round_end()
    clock.t += menu_speed.MAX_TRANSITION_S + 1
    assert speed.gameplay() is None                                      # a parked game, not a menu walk


def test_an_instance_from_before_the_screens_learner_gets_its_state_on_first_use(monkeypatch):
    speed = menu_speed.Speed()
    for name in ("pending", "sig", "open", "in_round"):
        delattr(speed, name)
    monkeypatch.setitem(menu_speed._CACHE, "X", speed)
    assert menu_speed.for_title("X") is speed and speed.open is None and speed.hints("results")["settle_s"] > 0
