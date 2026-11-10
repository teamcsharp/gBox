"""The menus' learned pace and the walk's clock (gbox.mercs.core.menu_pace), and the title screens that go at once.

Operator 2026-11-10 ~12:30: "I need all of these Resident Evil games training the bot to race through these menu screens
as fast as possible to get to the matches without wasting any time. It is absolutely unacceptable and boring to sit on
title screens and not do anything."

Synthetic screens and clocks only: the latencies here are the tests', not the games'."""
import json
from types import SimpleNamespace

import pytest

from gbox import mercs_bot as MB
from gbox.mercs import menu_speed
from gbox.mercs.core import menu_pace as P

KNOBS = {"settle": (1.0, 0.06), "move": (0.8, 0.08)}


def table(tmp_path, **kw):
    return P.Table(tmp_path / "menu_pace.json", KNOBS, **kw)


# --- the per-screen table ----------------------------------------------------------------------------------------------
def test_a_screens_wait_shrinks_with_every_taken_press_and_never_goes_under_its_floor(tmp_path):
    t = table(tmp_path)
    seen = [t.value("main_menu", "settle")]
    for k in range(30):
        t.learn("main_menu", ("settle",), True, now=float(k))
        seen.append(t.value("main_menu", "settle"))
    assert seen[0] == 1.0, "an unlearned screen keeps the hand-set wait"
    assert all(b <= a for a, b in zip(seen, seen[1:])) and seen[1] == pytest.approx(P.FAST)
    assert seen[-1] == KNOBS["settle"][1], "the floor keeps a press from going in before the game can take it"
    assert t.value("title", "settle") == 1.0 and t.value("main_menu", "move") == 0.8, "only what was learned moves"
    assert t.counts() == (30, 0)


def test_a_dropped_press_backs_the_screens_wait_off_but_never_past_the_hand_set_value(tmp_path):
    t = table(tmp_path)
    for k in range(10):
        t.learn("select_stage", ("settle", "move"), True, now=float(k))
    fast = t.value("select_stage", "settle")
    t.learn("select_stage", ("settle",), False, now=20.0)
    assert t.value("select_stage", "settle") == pytest.approx(min(1.0, fast * P.SLOW), abs=1e-4)
    for k in range(20):
        t.learn("select_stage", ("settle",), False, now=30.0 + k)
    assert t.value("select_stage", "settle") == 1.0, "never slower than the old walk"
    assert t.screens()["select_stage"]["missed"] == 21 and t.screens()["select_stage"]["taken"] == 10


def test_a_screens_own_floor_holds(tmp_path):
    t = table(tmp_path, floor=lambda where, knob, floor: 0.3 if where == "select_player" and knob == "move" else floor)
    for k in range(40):
        t.learn("select_player", ("move",), True, now=float(k))
        t.learn("main_menu", ("move",), True, now=float(k))
    assert t.value("select_player", "move") == 0.3 and t.value("main_menu", "move") == 0.08


def test_the_learned_waits_and_the_walks_persist_across_boots(tmp_path):
    t = table(tmp_path)
    t.learn("title", ("settle",), True, now=0.0)          # saved at once (the first save is never throttled)
    t.doc()["walks"] = [{"kind": "boot", "menu_s": 30.0}]
    t.learn("title", ("settle",), True, now=0.5)          # within SAVE_S: kept in memory only
    t.save(now=0.6, force=True)
    data = json.loads((tmp_path / "menu_pace.json").read_text(encoding="utf-8"))
    assert data["screens"]["title"]["taken"] == 2 and data["walks"] == [{"kind": "boot", "menu_s": 30.0}]
    again = table(tmp_path)                               # the next boot: a fresh process state, the same file
    assert again.value("title", "settle") == pytest.approx(1.0 * P.FAST * P.FAST, abs=1e-4)
    assert again.doc()["walks"][0]["menu_s"] == 30.0
    assert not (tmp_path / "menu_pace.tmp").exists(), "written whole, then moved into place"


def test_the_re4_learned_file_reads_unchanged_through_the_shared_table():
    """The live RE4 file (lilspark 2026-11-10 11:24, screens only) keeps every learned value: the move to the shared table
    must not slow RE4 down again."""
    from gbox.mercs.titles import re4_switch as D
    live = {"screens": {
        "main_menu": {"confirm_after": 0.1, "move_gap": 0.08, "settle": 0.06, "taken": 124},
        "select_stage": {"confirm_after": 0.1, "move_gap": 0.225, "settle": 0.06, "taken": 35},
        "round_intro": {"confirm_after": 0.8, "missed": 11, "settle": 1.0},
        "title": {"confirm_after": 0.1, "settle": 0.06, "taken": 11}}}
    D.PACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    D.PACE_FILE.write_text(json.dumps(live), encoding="utf-8")
    assert D.pace_value("main_menu", "settle") == 0.06 and D.pace_value("main_menu", "move_gap") == 0.08
    assert D.pace_value("title", "confirm_after") == 0.1 and D.pace_value("round_intro", "settle") == 1.0
    assert D.pace_value("select_stage", "move_gap") == D.PACE_SELECT_MOVE_FLOOR, "the open-loop select floor holds"
    D._pace_learn("title", ("settle",), True, 100.0)
    D.pace_save(force=True)
    saved = json.loads(D.PACE_FILE.read_text(encoding="utf-8"))["screens"]
    assert saved["main_menu"] == live["screens"]["main_menu"] and saved["round_intro"] == live["screens"]["round_intro"]
    assert saved["title"]["taken"] == 12 and saved["title"]["settle"] == 0.06
    assert "main_menu settle 0.06 confirm 0.10 move 0.08 (124 ok / 0 miss)" in D.pace_summary()


# --- the walk's clock --------------------------------------------------------------------------------------------------
class Wall:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_a_boot_walk_is_timed_from_the_launch_with_each_screens_seconds_presses_and_misses(tmp_path):
    wall = Wall()
    clock = P.Clock(table(tmp_path), wall=wall, pace=lambda: "title settle 0.00")
    launched, up = wall.t - 25.0, wall.t - 2.0             # booted 23 s, then 2 s with no bot (the scheduler's)
    clock.begin("boot", launched_at=launched, up_at=up)
    for where, dt, keys, missed in (("unknown", 1.0, 0, 0), ("title", 0.4, 2, 1), ("main_menu", 1.5, 5, 0),
                                    ("loading", 4.0, 0, 0)):
        clock.screen(where)
        for k in range(keys):
            clock.press(where, "a")
            if k < missed:
                clock.miss(where)
        wall.t += dt
    rec = clock.round_start()
    assert rec["kind"] == "boot" and rec["from"] == "launch" and rec["menu_s"] == pytest.approx(25.0 + 6.9)
    assert rec["bot_s"] == pytest.approx(6.9) and rec["wait_s"] == pytest.approx(2.0)
    assert rec["presses"] == 7 and rec["misses"] == 1
    assert rec["screens"].startswith("unknown 1.0s/0p, title 0.4s/2p/1miss, main_menu 1.5s/5p, loading 4.0s/0p")
    s = clock.stats()
    assert s["menu_s"] == rec["menu_s"] and s["menu_walk_kind"] == "boot" and s["menu_walk_presses"] == 7
    assert s["menu_misses"] == 1 and s["menu_walk_misses"] == 1 and s["menu_launch_wait_s"] == 2.0
    assert s["menu_walk_bot_s"] == pytest.approx(6.9) and s["menu_pace"] == "title settle 0.00"
    assert s["menu_boot_s_best"] == rec["menu_s"] and s["menu_walk_screens"] == rec["screens"]
    assert not {"menu_screens", "menu_boot_best", "menu_open_s"} & s.keys(), "RE5's menu_speed stats keep theirs"
    kept = json.loads((tmp_path / "menu_pace.json").read_text(encoding="utf-8"))
    assert kept["walks"][-1]["menu_s"] == rec["menu_s"] and kept["best"]["boot"] == rec["menu_s"]


def test_round_after_round_the_trend_and_the_best_show_the_walk_getting_faster(tmp_path):
    wall = Wall()
    clock = P.Clock(table(tmp_path), wall=wall)
    clock.begin("boot")                                    # no launch time: the walk counts from the bot's start
    clock.round_start()                                    # a bot that came in mid-round: nothing walked, nothing kept
    assert clock.last is None and "menu_s" not in clock.stats()
    for seconds in (14.0, 9.0, 6.5, 5.0, 4.2):
        clock.round_end()
        clock.screen("results")
        clock.press("results", "plus")
        wall.t += seconds
        clock.round_start()
    s = clock.stats()
    assert s["menu_s_trend"] == "14, 9, 6.5, 5, 4.2" and s["menu_s_best"] == 4.2 and s["menu_s"] == 4.2
    line = P.status(tmp_path / "menu_pace.json")           # the sidebar's line, read from the file (another process)
    assert line["text"] == "menus: 4.2 s (best 4.2 s)" and line["trend"] == [14.0, 9.0, 6.5, 5.0, 4.2]
    assert P.status(tmp_path / "none.json")["text"] == "menus: not timed yet"
    clock.begin("prepare")                                 # a MercMode background walk: kept, never the best
    clock.screen("select_stage")
    wall.t += 1.0
    assert clock.round_start()["kind"] == "prepare" and clock.stats()["menu_s_best"] == 4.2
    clock.round_end()
    clock.screen("dead")
    wall.t += P.MAX_WALK_S + 1                             # a parked game, not a walk
    assert clock.round_start() is None


# --- the title screens: confirmed on the first read ------------------------------------------------------------------
def test_a_title_screen_the_game_names_is_confirmed_on_its_first_read():
    now = [0.0]
    nav = MB.Navigator(lambda rows: {"sent": 1}, lambda scr: "a", sleep=lambda s: None, clock=lambda: now[0])
    assert nav.tick({"where": "title", **P.title_hints("title")}) == "a", "no settle wait on PRESS ANY BUTTON"
    other = MB.Navigator(lambda rows: {"sent": 1}, lambda scr: "a", sleep=lambda s: None, clock=lambda: now[0])
    assert other.tick({"where": "main_menu", **P.title_hints("main_menu")}) is None, "a menu still settles"
    assert P.title_hints("main_menu") == {}


def test_re5_names_press_any_button_from_its_own_state_and_confirms_it_at_once():
    import test_re5_switch as T5
    from gbox.mercs.titles import re5_switch as R
    g = T5.round_guest(phase=R.PHASE_OVER, player=False, units=((0, "uIdTitle00"),))
    unit = R.ui_units(g)["uIdTitle00"]
    assert R.screen(g)["where"] == "unknown", "the title still loading: the Boot's BOOT_KEY, as before"
    g.q(unit + R.TITLE_READY, g.obj("cTitleState", 0x100))   # PRESS ANY BUTTON's state is up (warm_probe's reading)
    scr = R.screen(g)
    assert scr["where"] == "title" and R.step(scr) == "a" and scr["settle_s"] == 0.0
    assert scr["confirmation_token"][:2] == ["title", unit]
    now = [0.0]
    nav = MB.Navigator(lambda rows: {"sent": 1}, R.step, sleep=lambda s: None, clock=lambda: now[0])
    assert nav.tick(scr) == "a"


def test_the_boot_keeps_its_long_limit_after_naming_a_title():
    now, sent = [0.0], []
    screens = iter(["title"] + ["unknown"] * 10)
    menus = SimpleNamespace(screen=lambda m, merc=None: {"where": next(screens), **P.title_hints("title")},
                            step=lambda scr: "a" if scr["where"] == "title" else None, wandered=lambda scr: None)
    boot = MB.Boot(menus, None, sent.append, sleep=lambda s: None, clock=lambda: now[0])
    assert boot.tick() is None and sent, "PRESS ANY BUTTON confirmed on its first read"
    now[0] += MB.MENU_LOST_S + 5                           # the save loads behind an unnamed screen for a while
    assert boot.tick() is None and boot.tick() is None


def test_re6_press_any_button_goes_at_once_and_its_menus_learn_their_waits(monkeypatch):
    from gbox.mercs.titles import re6_switch as R6
    m = SimpleNamespace()                                  # no adapter: the learner keeps no file
    script = {"where": "press_any_button", "cursor": None, "target": None}
    monkeypatch.setattr(R6, "_screen", lambda m, merc=None, now=None: dict(script))
    scr = R6.screen(m)
    assert scr["settle_s"] == 0.0 and R6.step(scr) == "a"
    script.update(where="title_locked")
    locked = R6.screen(m)
    assert R6.step(locked) is None and locked.get("settle_s") != 0.0, "the locked title is waited out, never pressed"
    script.update(where="main_menu", cursor=0, target=0)
    first = R6.screen(m)["settle_s"]
    for _ in range(25):                                    # the main menu's A taken every time: PLAY GAME comes up
        script.update(where="main_menu", cursor=0, target=0)
        R6.pressed(R6.screen(m), "a")
        script.update(where="play_game", cursor=0, target=3)
        R6.screen(m)
    script.update(where="main_menu", cursor=0, target=0)
    learned = R6.screen(m)
    assert learned["settle_s"] < first * 0.5 and learned["hold_s"] < MB.Navigator.HOLD_S
    assert learned["poll_s"] == menu_speed.FAST_POLL_S
    assert "main_menu settle" in R6.menu_pace_line()


# --- the runners' stats -------------------------------------------------------------------------------------------------
def test_the_re4_runner_reports_its_walk_in_the_runs_stats(monkeypatch):
    from gbox import re4switch_bot as B
    from gbox.mercs.titles import re4_switch as D

    class Reader:
        def __init__(self):
            self.script = ["select_stage"] + ["unknown"] * 40

        def read(self, frame):
            return {"where": self.script.pop(0) if self.script else "unknown"}

    monkeypatch.setattr(B.screens, "Reader", Reader)
    sent, n = [], {"n": 0}

    def stopped():
        n["n"] += 1
        return n["n"] > 12

    stats = {}
    ad = SimpleNamespace(get_frame=lambda: b"frame")
    B.play(ad, sent.append, stopped, sleep=lambda s: None, stats=stats, game={"_launched_at": None})
    assert stats["rounds"] == 1 and stats["menu_walk_kind"] == "boot"
    assert isinstance(stats["menu_s"], float) and stats["menu_walk_screens"].startswith("select_stage")
    walks = json.loads(D.PACE_FILE.read_text(encoding="utf-8"))["walks"]
    assert walks[-1]["kind"] == "boot" and "menu_misses" in stats
    assert D.menu_status()["text"].startswith("menus: boot "), "the sidebar's menus line (bot_logic.status)"


def test_the_navigator_counts_a_press_ram_never_showed_as_a_miss():
    now = [0.0]
    nav = MB.Navigator(lambda rows: {"sent": 1}, lambda scr: "a", sleep=lambda s: None, clock=lambda: now[0])
    scr = {"where": "results", "settle_s": 0.0}
    assert nav.tick(scr) == "a" and nav.misses == 0
    now[0] += MB.Navigator.RETRY_S + 0.1
    assert nav.tick(scr) == "a" and nav.misses == 1, "the same screen pressed again: the first was dropped"
    nav.tick({"where": "loading"})                         # the screen moved on: taken
    now[0] += 5.0
    assert nav.tick({"where": "select_stage", "settle_s": 0.0}) == "a" and nav.misses == 1
