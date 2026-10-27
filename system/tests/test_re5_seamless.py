"""RE5 between rounds, the fastest way (gbox.mercs.titles.re5_ps3.Pace and the menus around it; operator 2026-10-26:
"match to match to match without these loading screens and waiting"): the same stage and character again for
SAME_ROUNDS rounds - "Continue? Yes" after a death, cross / cross on the selects after the results - then one change at a
time on its own select screen; never a mode change inside a turn (only in MercMode's preparation between turns); the
DJ's pick at the next round in the turn's mode, the next turn otherwise; presses only while a screen's own state machine
takes input, and at once then; the path and the wait of every round in the stats (round_start_via, round_wait_s)."""
import random
import sys
import types

import pytest

from gbox import mercs_bot as MB
from gbox.mercs import round_map
from gbox.mercs.curriculum import Coverage
from gbox.mercs.titles import re5_ps3 as R
from test_re5_alert_handoff import unlock_notice
from test_re5_mercs import GAMESYS, SPLAYER, with_continue, with_ui, world


@pytest.fixture
def pace(monkeypatch, tmp_path):
    """A fresh Pace over a private coverage curriculum (never the real re5-coverage.json)."""
    cov = Coverage(tmp_path / "coverage.json", R.MODE_ROSTERS, range(8), random.Random(3))
    monkeypatch.setattr(R, "_COVERAGE", cov)
    p = R.Pace()
    monkeypatch.setattr(R, "PACE", p)
    p.cov = cov
    return p


def snap_of(mode, character, stage):
    return {"mercenaries_mode": mode, "character_index": R.MODE_ROSTERS[mode].index(character), "stage_index": stage}


def combo(plan):
    return plan["mode"], plan["character"], plan["stage"]


def between(pace, end, *screens, moves=(), answer=None):
    """A round ended (`end`), the menus showed `screens`, the Navigator sent `moves` ((screen, key) ...)."""
    pace.round_ended(end)
    if answer:
        pace.note_continue(answer)
    for s in screens:
        pace.note_screen(s)
    for where, key in moves:
        pace.note_press({"where": where}, key)


def play(pace, plan, end="results"):
    """The round `plan` played after a results screen and the selects (cursor moves when it changed)."""
    moved = []
    if pace.last is not None and plan["stage"] != pace.last[2]:
        moved.append(("select_stage", "dright"))
    if pace.last is not None and plan["character"] != pace.last[1]:
        moved.append(("select_player", "dleft"))
    between(pace, end, "results", "select_stage", "select_player", "loading", moves=moved)
    return pace.round_started(snap_of(*combo(plan)), count=False)


# --- the plan ------------------------------------------------------------------------------------------------------------
def test_the_same_round_comes_back_then_one_thing_changes_at_a_time(pace):
    pace.begin_run("s1", "job1", turn=True)
    assert pace.round_started(snap_of("reunion", "Barry", 3), count=False) == "start"     # the turn's prepared round
    assert pace.mode == "reunion" and pace.streak == 1
    for n in (2, 3):
        plan = pace.plan()
        assert plan["why"] == "same" and combo(plan) == ("reunion", "Barry", 3)
        assert play(pace, plan) == "results/same" and pace.streak == n
    plan = pace.plan()                                                  # SAME_ROUNDS done: the character changes
    assert R.SAME_ROUNDS == 3 and plan["why"] == "character"
    assert plan["mode"] == "reunion" and plan["stage"] == 3 and plan["character"] != "Barry"
    assert pace.plan() == plan                                          # held until the round starts
    assert play(pace, plan) == "results/character" and pace.streak == 1
    for _ in range(2):
        assert pace.plan()["why"] == "same"
        play(pace, pace.plan())
    plan = pace.plan()                                                  # then the stage, the character kept
    assert plan["why"] == "stage" and plan["character"] == pace.last[1] and plan["stage"] != 3
    assert play(pace, plan) == "results/stage"
    assert pace.next_change == "character" and pace.mode == "reunion"


def test_continue_yes_replays_the_round_inside_the_streak_and_no_comes_at_a_change(pace):
    pace.begin_run("s1", "job1", turn=True)
    pace.round_started(snap_of("reunion", "Josh", 5), count=False)
    between(pace, "dead")
    assert pace.continue_answer() == "yes"
    assert R.step({"where": "dead", "continue_ready": True, "cursor": 1}) == "dleft"   # Left: Yes
    assert pace.path["continue"] is None                                # a cursor move is not the answer
    assert R.step({"where": "dead", "continue_ready": False, "cursor": 0}) is None     # not before RAM says ready
    assert R.step({"where": "dead", "continue_ready": True, "cursor": 0}) == "cross"
    assert pace.round_started(snap_of("reunion", "Josh", 5), count=False) == "dead/retry" and pace.streak == 2
    pace.round_started(snap_of("reunion", "Josh", 5), count=False)     # a third one (from the results, say)
    between(pace, "dead")
    assert pace.continue_answer() == "no"                               # the streak is done: back to the selects
    assert R.step({"where": "dead", "continue_ready": True, "cursor": 0}) == "dright"
    assert R.step({"where": "dead", "continue_ready": True, "cursor": 1}) == "cross"
    assert pace.path["continue"] == "no"


def test_a_retry_round_counts_in_the_coverage_and_the_roster(pace, monkeypatch):
    monkeypatch.setattr(R, "ROSTER", R.Roster())
    pace.begin_run("s1", "job1", turn=True)
    pace.round_started(snap_of("reunion", "Sheva (Business)", 2), count=False)
    between(pace, "dead", answer="yes")
    assert pace.round_started(snap_of("reunion", "Sheva (Business)", 2)) == "dead/retry"
    assert pace.cov.counts == {"reunion/Sheva (Business)/2": 1}         # the selects never saw it: counted here
    assert R.ROSTER.played["Sheva (Business)"] == 1


def test_the_mode_never_changes_inside_a_turn_only_between_turns(pace):
    for who in R.CHARACTERS:                                            # Reunion played more: the balance wants the
        for stage in range(8):                                          # original Mercenaries next
            pace.cov.counts[f"reunion/{who}/{stage}"] = 2
    pace.begin_run("s1", "job1", turn=True)
    pace.round_started(snap_of("reunion", "Excella", 4), count=False)
    for _ in range(4):
        plan = pace.plan()
        assert plan["mode"] == "reunion"                                # same, then a Reunion character: no title walk
        play(pace, plan)
    pace.begin_run("s1", "job1", turn=True)                                        # a bot hot reload restarts the run: same turn
    assert pace.mode == "reunion" and pace.plan()["mode"] == "reunion"
    pace.begin_run("s1", None, prepare=True, turn=True)                            # MercMode's preparation between two turns
    plan = pace.plan()
    assert plan["why"] == "turn" and plan["mode"] == "mercenaries"      # the curriculum's balance may change it here
    pace.observe_mode("reunion")                                        # (a preparation never locks a mode)
    assert pace.mode is None
    pace.begin_run("s1", "job2", turn=True)                                        # the next turn takes the mode RAM shows
    pace.observe_mode("mercenaries")
    assert pace.mode == "mercenaries"


def test_the_djs_pick_comes_next_in_the_turns_mode_and_waits_for_the_next_turn_otherwise(pace):
    pace.begin_run("s1", "job1", turn=True)
    pace.round_started(snap_of("reunion", "Barry", 0), count=False)
    pace.cov.request("reunion", "Rebecca", 6)
    plan = pace.plan()
    assert plan["why"] == "dj" and combo(plan) == ("reunion", "Rebecca", 6)
    assert pace.continue_answer() == "no"                               # another round: through the selects
    pace.cov.started("reunion", "Rebecca", 6)                           # (screen() confirms it at its first frame)
    assert pace.round_started(snap_of("reunion", "Rebecca", 6), count=False) == "start"
    pace.cov.request("mercenaries", "Wesker (Midnight)", 2)             # the other mode: not inside this turn
    plan = pace.plan()
    assert plan["mode"] == "reunion" and plan["why"] == "same"
    assert pace.status()["dj_waits_for_next_turn"] == "dj: mercenaries / Wesker (Midnight) / Village"
    pace.begin_run("s1", None, prepare=True, turn=True)                            # between turns: taken
    assert combo(pace.plan()) == ("mercenaries", "Wesker (Midnight)", 2) and pace.plan()["why"] == "dj"


def test_a_run_without_turns_keeps_the_fast_path_but_its_curriculum_may_change_mode(pace):
    for who in R.CHARACTERS:                                            # Reunion played out: the balance wants the
        for stage in range(8):                                          # original Mercenaries
            pace.cov.counts[f"reunion/{who}/{stage}"] = 2
    pace.begin_run("s1", "plain-autoplay")                              # no MercMode block: no turn
    pace.round_started(snap_of("reunion", "Excella", 4), count=False)
    for _ in range(2):
        assert pace.plan()["why"] == "same"
        play(pace, pace.plan())
    plan = pace.plan()                                                  # one change: a character on the same stage,
    assert plan["why"] == "character" and plan["stage"] == 4           # from the mode the balance wants
    assert plan["mode"] == "mercenaries"
    pace.cov.request("reunion", "Barry", 1)                             # and a DJ pick in any mode comes next
    assert combo(pace.plan()) == ("reunion", "Barry", 1)


def test_the_path_names_how_each_round_came(pace):
    assert R.Pace.via(None) == "start"
    assert R.Pace.via({"end": "dead", "screens": [], "continue": "yes"}) == "dead/retry"
    assert R.Pace.via({"end": "dead", "screens": ["alert_ok", "select_stage", "select_player"], "moves": {},
                       "continue": "no"}) == "dead/same"
    assert R.Pace.via({"end": "results", "screens": ["results", "select_stage", "reunion_title", "main_menu",
                                                     "play_game", "mercs_title", "select_stage", "select_player"],
                       "moves": {}}) == "results/title"
    assert R.Pace.via({"end": "results", "screens": ["select_stage", "select_player"],
                       "moves": {"select_stage": 2, "select_player": 1}}) == "results/stage+character"
    assert R.Pace.via({"end": "results", "screens": ["results"], "moves": {}}) == "results/unknown"


# --- the curriculum's constrained picks ----------------------------------------------------------------------------------
def test_coverage_keeps_the_stage_or_the_character_and_stays_in_the_mode(tmp_path):
    c = Coverage(tmp_path / "cov.json", R.MODE_ROSTERS, range(8), random.Random(11))
    c.started("reunion", "Barry", 4)
    first = c.choose()                                                  # a status call's unconstrained draw...
    pick = c.choose(mode="reunion", keep="stage")                       # ...is drawn again when it does not fit
    assert pick["mode"] == "reunion" and pick["stage"] == 4 and pick["character"] != "Barry"
    assert c.choose(mode="reunion", keep="stage") == pick              # held
    c.started(**pick)
    pick2 = c.choose(mode="reunion", keep="character")
    assert pick2["character"] == pick["character"] and pick2["stage"] != 4 and pick2["mode"] == "reunion"
    assert first["mode"] in R.MODE_ROSTERS
    c.request("mercenaries", "Jill (BSAA)", 1)
    assert c.choose(mode="reunion")["mode"] == "reunion"                # the other mode's DJ pick stays queued...
    assert c.choose() == {"mode": "mercenaries", "character": "Jill (BSAA)", "stage": 1}   # ...for the next turn


def test_one_change_at_a_time_still_plays_every_character_and_stage(tmp_path):
    c = Coverage(tmp_path / "cov.json", R.MODE_ROSTERS, range(8), random.Random(2))
    c.started("reunion", "Josh", 0)
    keep = "stage"
    for _ in range(64):
        pick = c.choose(mode="reunion", keep=keep)
        c.started(**pick)
        keep = "character" if keep == "stage" else "stage"
    played = {k.split("/")[1] for k in c.counts}
    stages = {int(k.split("/")[2]) for k in c.counts}
    assert played == set(R.CHARACTERS) and stages == set(range(8))
    assert all(k.startswith("reunion/") for k in c.counts)


# --- presses only when the screen takes them, and at once then -----------------------------------------------------------
def selects(unit, state, cursor=0):
    mem = world(timer=0.0)
    mem.u32(SPLAYER + 0x28, 0)
    off = R.MENU_CURSOR if unit == "uIdStartUp21" else R.SELECT_CURSOR
    return with_ui(mem, [(unit, {0x14: state, off: cursor}), "uIdTopMenu00"])


@pytest.mark.parametrize("unit,where", [("uIdStartUp21", "select_stage"), ("uIdStartUp22", "select_player")])
def test_the_selects_take_presses_only_in_their_input_state(unit, where):
    for state, ready in ((0, False), (1, False), (2, True), (3, False), (0x5A, False)):
        scr = R.screen(selects(unit, state))
        assert scr["where"] == where and scr["input_ready"] is ready and scr["title_step"] == state
        assert (R.step(scr) is not None) is ready


def test_a_ready_screen_is_pressed_at_once_and_a_passing_one_keeps_the_settle():
    now, sent = [100.0], []
    nav = MB.Navigator(sent.extend, R.step, sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0],
                       cursor=R.NAV_CURSOR)
    ready = {"where": "select_stage", "cursor": 4, "target": 4, "select_state": 2, "title_step": 2, "input_ready": True}
    assert nav.tick(ready) is None                                     # first seen this instant
    now[0] += R.NAV_CURSOR["ready_s"] + 0.01
    assert nav.tick(ready) == "cross"                                  # not after the 0.5 s settle: at once
    fading = dict(ready, select_state=3, title_step=3, input_ready=False)
    now[0] += 2.0
    assert nav.tick(fading) is None                                    # the cross took (state 3): nothing more
    plain = {"where": "alert_ok", "cursor": None, "target": None, "confirmation_token": ["alert", 1, 9, "0100"]}
    assert nav.tick(plain) is None
    now[0] += R.NAV_CURSOR["ready_s"] + 0.01
    assert nav.tick(plain) is None                                     # no input_ready: the settle stands
    now[0] += MB.Navigator.STABLE_S
    assert nav.tick(plain) == "cross"


def test_the_results_final_state_takes_start_at_once():
    memory, unit = unlock_notice(player=False)
    memory.put(unit + 0x16, b"\x04\x0a")                               # outer 10: START is read every frame
    scr = R.screen(memory)
    assert scr["where"] == "results" and scr["input_ready"] is True and R.step(scr) == "start"
    memory.put(unit + 0x16, b"\x00\x05")                               # outer 5: the records' save - no button
    scr = R.screen(memory)
    assert scr["where"] == "results_wait" and not scr.get("input_ready") and R.step(scr) is None


def test_the_engine_hands_the_results_back_at_their_last_page_not_after_the_score_bound():
    memory, unit = unlock_notice(player=True)
    memory.put(unit + 0x16, b"\x00\x05")                               # the tally still running
    driver = R.RE5PS3()
    snap = R.snapshot(memory)
    assert driver.screen(memory, snap) == "results" and driver.result_ready(snap, 0.5) is False
    memory.put(unit + 0x16, b"\x04\x0a")                               # outer 10: the tally is over
    snap = R.snapshot(memory)
    assert driver.screen(memory, snap) == "results" and driver.result_ready(snap, 0.6) is True


def test_a_results_message_waiting_for_confirm_is_answered_only_when_the_code_matches():
    memory, unit = unlock_notice(player=False)
    memory.put(unit + 0x16, b"\x00\x1e")                               # outer 0x1E: waits for the confirm mask
    scr = R.screen(memory)
    assert scr["where"] == "results_wait" and R.step(scr) is None      # its handler's code not verified: no press
    for address, code in R.MERCE_MESSAGE_CODE:
        memory.put(address, code)
    scr = R.screen(memory)
    assert scr["where"] == "results_message" and scr["input_ready"] is True and R.step(scr) == "cross"
    memory.u32(0x38000000 + R.PAD_CONFIRM, 0x2000)                    # confirm is circle on this console: no cross
    assert R.screen(memory)["where"] == "results_wait"


def test_the_continue_dialog_is_ready_only_in_its_input_state():
    mem = with_continue(world(hp=0), state=1)
    scr = R.screen(mem)
    assert scr["input_ready"] is False and scr["title_step"] == 1
    mem = with_continue(world(hp=0), state=2)
    scr = R.screen(mem)
    assert scr["input_ready"] is True and scr["title_step"] == 2


# --- every round's path and wait in the stats ----------------------------------------------------------------------------
def reunion_round(timer, character=6, stage=7):
    mem = world(timer=timer)
    mem.u32(GAMESYS + 0x58, 5)                                         # Reunion
    mem.u32(GAMESYS + 0x348, stage)
    mem.u32(GAMESYS + 0x364, character)
    return R.snapshot(mem)


def test_each_round_carries_its_path_gap_and_wait(pace):
    stats = {}
    first = R.Bot(clock=lambda: 10.0, stats=stats)
    first.observe_round(reunion_round(100.0), "playing", 10.0)        # mid-round: the run began in it
    assert stats["round_start_via"] == "start" and stats["round_gap_s"] is None
    assert stats["turn_mode"] == "reunion" and stats["same_round_streak"] == 1
    first.observe_round(reunion_round(0.0), "results", 100.0)
    R.PACE.note_screen("results")
    R.PACE.note_screen("select_stage")
    R.PACE.note_screen("select_player")
    second = R.Bot(clock=lambda: 125.0, stats=stats)
    second.observe_round(reunion_round(120.0), "playing", 125.0)      # the player shows: the clock still at its start
    assert stats["round_gap_s"] == 25.0 and stats["round_start_via"] == "results/same"
    assert stats["round_input_ready"] is False and stats.get("round_wait_s") is None
    second.observe_round(reunion_round(119.9), "playing", 136.0)      # the load is over, the clock runs
    assert stats["round_input_ready"] is True and stats["round_wait_s"] == 36.0
    assert stats["round_gaps"] == "25 results/same" and stats["round_waits"] == "36 results/same"
    assert stats["same_round_streak"] == 2


def test_gap_play_without_a_gap_tells_nothing():
    stats = {}
    round_map.gap_start(stats, 50.0, "start")
    assert round_map.gap_play(stats, 60.0) is None and "round_waits" not in stats
    round_map.gap_end(stats, 100.0)
    round_map.gap_start(stats, 117.0, "dead/retry")
    assert round_map.gap_play(stats, 128.5) == 28.5 and stats["round_waits"] == "28.5 dead/retry"
    assert round_map.gap_play(stats, 130.0) is None                    # once a round


# --- the deployment tells the menus which run (turn) this is --------------------------------------------------------------
def test_play_tells_the_menus_its_session_job_and_preparation(monkeypatch):
    calls = []
    menus = types.ModuleType("fake_re5_menus")
    menus.screen = lambda m, merc=None: {"where": "unknown"}
    menus.step = lambda scr: None
    menus.wandered = lambda scr: None
    menus.begin_run = lambda **kw: calls.append(kw)
    monkeypatch.setitem(sys.modules, "fake_re5_menus", menus)
    monkeypatch.setattr(MB, "profile_for", lambda ad, game: {"menus": "fake_re5_menus", "map_id": "TEST",
                                                             "platform": "ps3"})
    monkeypatch.setattr(MB, "engine", lambda: types.SimpleNamespace(play_round=lambda *a, **k: "round"))
    MB.play(None, lambda rows: None, lambda: True, m=object(), session_id="s9", source_job_id="job7")
    MB.play(None, lambda rows: None, lambda: True, m=object(), session_id="s9", prepare=True)
    MB.play(None, lambda rows: None, lambda: True, m=object(), session_id="s9", source_job_id="job8",
            game={"launch": {"mercmode": {"random_characters": True, "random_stages": True}}})
    assert calls == [{"session_id": "s9", "job": "job7", "prepare": False, "turn": False},
                     {"session_id": "s9", "job": None, "prepare": True, "turn": False},
                     {"session_id": "s9", "job": "job8", "prepare": False, "turn": True}]   # a MercMode turn
