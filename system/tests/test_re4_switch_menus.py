"""RE4 Switch's walk from the title to a round: the frame classifier and the rules that keep a confirm off the wrong row."""
import io

import numpy as np
import pytest
from PIL import Image

from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_switch_screens as S


def png_of(rgb) -> bytes:
    out = io.BytesIO()
    Image.fromarray(np.asarray(rgb, dtype=np.uint8), "RGB").save(out, "PNG")
    return out.getvalue()


def from_thumb(thumb, size=(S.W, S.H)):
    grey = np.asarray(Image.fromarray(np.asarray(thumb, dtype=np.uint8), "L").resize(size, Image.BILINEAR))
    return np.stack([grey] * 3, axis=2)


def menu_frame(row_y: int, size=(S.W, S.H)):
    """The logo's reference with one row of red text at that height."""
    rgb = from_thumb(S.refs()["logo_ref"], size).copy()
    scale = size[1] / S.H
    y0, y1 = int((row_y - 6) * scale), int((row_y + 6) * scale)
    x0, x1 = int(440 * scale), int(620 * scale)
    rgb[y0:y1, x0:x1] = (200, 60, 50)
    return rgb


@pytest.fixture(autouse=True)
def fresh_walk():
    D.begin_run()
    yield
    D.begin_run()


@pytest.mark.parametrize("name", ["title", "mercs_title", "select_player", "select_stage"])
def test_fixed_screens_are_named_by_their_reference(name, monkeypatch):
    """The thresholds were scored on 114 real frames on the Spark (docs/research/re4-switch-menu-walk.md); upscaling a
    thumbnail for a test frame blurs it past them, so this feeds the thumbnail straight in."""
    monkeypatch.setattr(S, "thumbnail", lambda _rgb: S.refs()["refs"][name])
    assert S.classify(png_of(np.zeros((S.H, S.W, 3))))["where"] == name


@pytest.mark.parametrize("name", ["story_load_list", "story_buy", "story_case"])
def test_the_story_screens_are_recognised_and_cancelled_out_of_first(name):
    """These used to end the run outright. Measured 2026-11-07: the walk strayed onto LOAD and the bot sat there for
    260 s with the walk still able to reach THE MERCENARIES - so a story SCREEN now cancels out, and only an
    un-cancellable one ends the run (see test_the_cancel_budget_is_spent_then_the_run_ends)."""
    scr = S.classify(png_of(from_thumb(S.refs()["refs"][name])))
    assert scr["where"] == "story"
    assert D.wandered(scr) is None
    assert D.step(scr) == D.STORY_RECOVER_KEY


@pytest.mark.parametrize("menu,rows", [("main_menu", S.MAIN_ROWS), ("extras_menu", S.EXTRAS_ROWS)])
def test_each_menu_row_reads_as_itself(menu, rows):
    for i, y in enumerate(rows):
        assert S.classify(png_of(menu_frame(y))) == {"where": menu, "cursor": i}


def test_the_session_display_size_reads_the_same():
    """The worker grabs 1280x720 from the display, the API serves 960x540."""
    scr = S.classify(png_of(menu_frame(S.MAIN_ROWS[5], (1280, 720))))
    assert scr == {"where": "main_menu", "cursor": 5}


def test_a_flat_or_unseen_picture_names_nothing_a_press_could_act_on():
    assert S.classify(png_of(np.zeros((S.H, S.W, 3))))["where"] == "loading"
    assert D.step({"where": "loading"}) is None
    noise = np.random.default_rng(1).integers(0, 255, (S.H, S.W, 3))
    assert S.classify(png_of(noise))["where"] == "unknown"
    assert D.step({"where": "unknown"}) is None


def test_the_driver_never_presses_blind_on_an_unnamed_boot_screen():
    """mercs_bot.Boot presses BOOT_KEY on "unknown": RE4 must not have one."""
    assert not hasattr(D, "BOOT_KEY")


@pytest.mark.parametrize("cur,tgt,key", [(1, 5, "ddown"), (4, 5, "ddown"), (6, 5, "dup"), (5, 5, "a")])
def test_the_main_menu_confirms_only_on_extras(cur, tgt, key):
    assert D.step({"where": "main_menu", "cursor": cur, "target": tgt}) == key


def test_an_unread_cursor_is_not_confirmed():
    assert D.step({"where": "main_menu", "cursor": None, "target": 5}) is None


def test_a_confirm_is_not_repeated_while_the_screen_fades():
    """A second A during the title's fade lands on the main menu's LOAD and loads a story save."""
    scr = {"where": "title"}
    assert D._confirm("title", now=100.0) == "a"
    D.pressed(scr, "a", now=100.0)
    assert D._confirm("title", now=104.9) is None
    assert D._confirm("title", now=105.1) == "a"
    D.begin_run()
    assert D._confirm("title", now=100.1) == "a"


def test_moving_the_cursor_does_not_start_a_confirm_gap():
    D.pressed({"where": "main_menu", "cursor": 1, "target": 5}, "ddown", now=100.0)
    assert D._confirm("main_menu", now=100.1) == "a"


def test_the_intro_is_only_named_after_this_walk_picked_a_stage(monkeypatch):
    seq = iter(["unknown", "select_stage", "unknown", "loading", "unknown", "playing", "unknown"])
    monkeypatch.setattr(S, "classify", lambda _png: {"where": next(seq)})
    r = S.Reader()
    seen = [r.read(b"")["where"] for _ in range(7)]
    assert seen == ["unknown", "select_stage", "unknown", "loading", "round_intro", "playing", "unknown"]


def test_intro_presses_are_bounded(monkeypatch):
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "unknown"})
    r = S.Reader()
    r.stage_picked = r.armed = True
    for _ in range(S.Reader.INTRO_MAX_PRESSES):
        assert r.read(b"")["where"] == "round_intro"
        r.press_went_in("round_intro", "a")
    assert r.read(b"")["where"] == "unknown"


def test_a_pulsing_cursor_keeps_its_row(monkeypatch):
    seq = iter([{"where": "main_menu", "cursor": 3}, {"where": "menu"}])
    monkeypatch.setattr(S, "classify", lambda _png: next(seq))
    r = S.Reader()
    assert r.read(b"")["cursor"] == 3
    held = r.read(b"")
    assert held["where"] == "main_menu" and held["cursor"] == 3


def test_a_menu_with_no_row_read_yet_names_nothing(monkeypatch):
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "menu"})
    assert S.Reader().read(b"")["where"] == "unknown"


def test_the_screen_reader_needs_a_frame():
    class NoFrame:
        adapter = None

    assert D.screen(NoFrame(), merc={})["where"] == "unknown"


def test_the_measured_constants_are_present():
    """A scaffold port once dropped all of these (307317e1); decrypt_lab and the walk read them."""
    assert D.SIG_OFF == 0x100000 and len(D.SIGNATURE) == 64
    assert D.BUILD_ID == "82C2A04A21D3E0B850F273D4149C9003"
    assert (D.AIM_BTN, D.FIRE_BTN) == ("zl", "zr") and D.CONTROLS_READY is True
    assert D.INTRO_PRESSES == 3 and D.round_entry_events()[0] == {"key": "a", "down": True}


def test_the_brain_turns_with_the_stick_not_the_item_dpad():
    bot = D.Bot(stats={})
    snap = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0},
            "enemies": [{"pos": (5000.0, 0.0, 0.0), "hp": 100, "ptr": 1}]}
    assert bot.tick(snap)["hold"] == {"lleft"}, "the left stick, never the d-pad (+x is a left turn: GameCube sign)"


# ---------------------------------------------------------------- straying into the story save list

def test_a_story_screen_is_cancelled_out_of_instead_of_ending_the_run():
    """2026-11-07: a stray confirm landed the walk on LOAD and the bot sat there (identical frames for 260 s).

    The story save list is not a story game: cancel out of it and keep walking. Ending the run there wasted the whole
    boot when the walk was still perfectly able to reach THE MERCENARIES.
    """
    scr = {"where": "story"}
    assert D.wandered(scr) is None, "a story SCREEN must not end the run while the recovery budget lasts"
    assert D.step(scr) == D.STORY_RECOVER_KEY
    D.pressed(scr, D.STORY_RECOVER_KEY)
    # the gap keeps the cancels from being spammed at the emulator
    assert D.step(scr) is None
    assert D.step(scr, ) is None


def test_the_cancel_budget_is_spent_then_the_run_ends():
    scr = {"where": "story"}
    now = 0.0
    for _ in range(D.STORY_RECOVER_MAX):
        assert D.step(scr, now) == D.STORY_RECOVER_KEY
        D.pressed(scr, D.STORY_RECOVER_KEY, now)
        now += D.STORY_GAP_S + 0.1
    assert D.step(scr, now) is None, "no more cancels once the budget is spent"
    assert D.wandered(scr) == "story game", "a title that will not leave the list ends the run"


def test_a_new_walk_resets_the_cancel_budget():
    scr = {"where": "story"}
    now = 0.0
    for _ in range(D.STORY_RECOVER_MAX):
        D.step(scr, now)
        D.pressed(scr, D.STORY_RECOVER_KEY, now)
        now += D.STORY_GAP_S + 0.1
    assert D.wandered(scr) == "story game"
    D.begin_run()
    assert D.wandered(scr) is None and D.step(scr, now) == D.STORY_RECOVER_KEY

def test_the_story_confirm_dialog_is_never_confirmed(monkeypatch):
    """2026-11-07: the "Load data? Yes / No" overlay matches no reference, so it read as unknown and a press meant for an
    unnamed screen loaded a story save (the merchant's TUNE UP came up). After a story screen an unnamed frame is that
    dialog, and it is cancelled."""
    r = S.Reader()
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "story", "story": "story_load_list"})
    assert r.read(b"")["where"] == "story"
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "unknown"})
    scr = r.read(b"")
    assert scr["where"] == "story_prompt"
    assert D.step(scr) == D.STORY_RECOVER_KEY             # cancel, never confirm
    # a named screen clears the arming, so an unrelated unknown is not mistaken for the dialog
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "mercs_title"})
    r.read(b"")
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "unknown"})
    assert r.read(b"")["where"] == "unknown"

def test_the_second_appearance_of_the_save_list_is_named_as_the_story_list():
    """2026-11-07: the walk sat on the save list for 255 s because that appearance read as `unknown` - 18.0 from the
    only reference against a 12.0 threshold, and >= 28.7 from every other screen. It is now a reference of its own, and
    this test pins both halves: it reads as the story list, and it is not close enough to any other screen to be
    confused with it."""
    assert "story_load_list_2" in S.STORY and "story_load_list_2" in S.refs()["refs"]
    r = S.refs()
    thumb = r["refs"]["story_load_list_2"]
    for name, ref in r["refs"].items():
        if name == "story_load_list_2":
            continue
        assert S.rmse(thumb, ref) > S.STORY_MAX, f"too close to {name}"
    assert S.rmse(thumb, r["logo_ref"], r["logo_mask"]) > S.LOGO_MAX
    assert S.classify(png_of(from_thumb(thumb)))["where"] == "story"

# ---------------------------------------------------------------- MercMode's DJ pick on the selects

def test_a_dj_pick_is_taken_by_name_or_index_and_refused_when_unknown():
    D.begin_run()
    assert D.request("Krauser", "Base") == {"character": "Krauser", "stage": "Base", "player_index": 2, "stage_index": 2}
    assert D.SELECTION == {"player": 2, "stage": 2}
    assert D.request(4, 3)["character"] == "Wesker"
    with pytest.raises(ValueError):
        D.request("Chris")
    with pytest.raises(ValueError):
        D.request(None, 7)
    D.begin_run()
    assert D.SELECTION == {"player": None, "stage": None}, "a new walk without a pick confirms the defaults"


def test_a_walk_takes_the_launch_selection():
    D.begin_run(selection={"title": "re4", "mode": "mercenaries", "character": "Ada", "stage": 3,
                           "stage_name": "Waterworld"})
    assert D.SELECTION == {"player": 1, "stage": 3}
    D.begin_run(selection={"title": "re4", "character": "HUNK", "stage": None, "stage_name": "Castle"})
    assert D.SELECTION == {"player": 3, "stage": 1}
    D.begin_run()


@pytest.mark.parametrize("stage,moves", [(0, ()), (1, ("dright",)), (2, ("ddown",)), (3, ("dright", "ddown"))])
def test_the_stage_grid_is_walked_to_the_picked_cell_then_confirmed(stage, moves):
    D.begin_run(selection={"character": None, "stage": stage})
    keys = [D.step({"where": "select_stage", "moved": n}, now=1000.0) for n in range(len(moves))]
    assert tuple(keys) == moves
    assert D.step({"where": "select_stage", "moved": len(moves)}, now=1000.0) == "a"
    D.begin_run()


def test_the_select_player_cursor_steps_right_once_per_portrait():
    D.begin_run(selection={"character": "Wesker", "stage": 0})
    assert [D.step({"where": "select_player", "moved": n}, now=1000.0) for n in range(4)] == ["dright"] * 4
    assert D.step({"where": "select_player", "moved": 4}, now=1000.0) == "a"
    assert D.press_gap({"where": "select_player", "moved": 2}) == D.STEER_GAP_S
    assert D.press_gap({"where": "select_player", "moved": 4}) == D.CONFIRM_GAP_S["select_player"]
    D.begin_run()
    assert D.step({"where": "select_player"}, now=2000.0) == "a", "no pick: Leon, the default portrait, is confirmed"


def test_the_reader_keeps_a_steered_select_screen_named(monkeypatch):
    """The references are the default cursor: once the walk moved it the picture reads unknown, and the reader must
    still call it the select screen (with the moves counted), or the walk would stop on it."""
    r = S.Reader()
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "select_player"})
    assert r.read(b"")["where"] == "select_player"
    r.press_went_in("select_player", "dright")
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "unknown"})
    scr = r.read(b"")
    assert scr == {"where": "select_player", "moved": 1, "steering": True}
    r.press_went_in("select_player", "dright")
    assert r.read(b"")["moved"] == 2
    r.press_went_in("select_player", "a")                    # confirmed: the next unknown is not the select any more
    assert r.read(b"")["where"] == "unknown"


def test_a_steer_ends_when_another_screen_comes_up(monkeypatch):
    r = S.Reader()
    r.press_went_in("select_stage", "ddown")
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "loading"})
    assert r.read(b"")["where"] == "loading" and r.steer is None


# ---------------------------------------------------------------- the walk's pace (re4switch_bot)

def test_a_cursor_move_waits_for_the_last_one_to_show():
    pace, scr = D.Pace(), {"where": "main_menu", "cursor": 1, "target": 5}
    pace.observe(scr, 0.0)
    assert pace.ready(scr, 0.0)
    pace.pressed(scr, "ddown", 0.0)
    assert not pace.ready(scr, D.MOVE_GAP_S + 0.1), "the cursor still reads 1: the move has not shown"
    assert pace.ready(scr, D.MOVE_RETRY_S + 0.1), "never shown by MOVE_RETRY_S: the move goes in again"
    moved = dict(scr, cursor=2)
    pace.observe(moved, 0.5)
    assert not pace.ready(moved, 0.5) and pace.ready(moved, D.MOVE_GAP_S + 0.01)


def test_a_menu_confirm_needs_two_reads_on_the_target_and_a_settled_screen():
    pace, scr = D.Pace(), {"where": "main_menu", "cursor": 5, "target": 5}
    pace.observe(scr, 0.0)
    assert not pace.ready(scr, D.SETTLE_S + 0.1), "one read on EXTRAS is not two"
    pace.observe(scr, 0.2)
    assert pace.ready(scr, D.SETTLE_S + 0.1)
    pace.observe(dict(scr, cursor=4), 0.3)
    assert not pace.ready(dict(scr, cursor=5), D.SETTLE_S + 0.2), "a read off the target starts the count again"


def test_a_fixed_screen_confirms_once_it_has_settled():
    pace, title = D.Pace(), {"where": "title"}
    pace.observe(title, 10.0)
    assert not pace.ready(title, 10.0 + D.SETTLE_S - 0.1) and pace.ready(title, 10.0 + D.SETTLE_S)


# ---------------------------------------------------------------- You Are Dead - Continue

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


# The two live frames are gameplay screenshots, so they stay out of git (the publish guard refuses them here): they
# are in the control plane's artifact store, and a checkout that has fetched them into tests/fixtures/ runs the check.
#   re4sw_dead_continue.jpg  0c0a88732908d1a8b82d786c7fa76007fb6ec01241ed89823e797fc82ebe360e
#   re4sw_round_hud.jpg      b0c729a2cf45e3854bae6f53e9ab771edb0e4d3a9321eadcbaccc3c94950527e
LIVE_FRAMES = [FIXTURES / "re4sw_dead_continue.jpg", FIXTURES / "re4sw_round_hud.jpg"]


@__import__("pytest").mark.skipif(not all(p.exists() for p in LIVE_FRAMES), reason="the live RE4 frames are not fetched")
def test_the_recorded_death_and_round_frames_are_named():
    """Recorded 2026-11-10: the death frame is almost black (mean 6.5) and read as loading, so nothing answered it."""
    assert S.classify(LIVE_FRAMES[0].read_bytes()) == {"where": "dead_continue"}
    assert S.classify(LIVE_FRAMES[1].read_bytes()) == {"where": "playing"}


def test_the_death_screen_is_named_not_taken_for_a_load():
    black = png_of(np.zeros((S.H, S.W, 3), dtype=np.uint8))
    assert S.classify(black)["where"] == "loading"


def test_continue_is_answered_yes_and_the_stage_intro_is_armed_again():
    D.begin_run()
    scr = {"where": "dead_continue"}
    assert D.step(scr, now=500.0) == "a"
    D.pressed(scr, "a", now=500.0)
    assert D.step(scr, now=501.0) is None, "one confirm per gap"
    r = S.Reader()
    r.press_went_in("dead_continue", "a")
    assert r.stage_picked is True and r.intro_presses == 0



def _prompt_frame(boxes):
    import numpy as np
    g = np.full((540, 960), 30.0)
    for x0, y0, x1, y1 in boxes:
        g[y0:y1, x0:x0 + max(2, (x1 - x0) // 10)] = 220.0          # a few bright columns: text
    return g


def test_the_two_save_list_prompts_are_told_apart():
    """Measured 2026-11-10: "Cancel loading?" stacks Yes / No with the cursor beside one; "Load data?" puts them on one
    line lower down. The first is left by Yes (up, then A); the second is cancelled (B) and never loads."""
    B = S.PROMPT_BOXES
    cancel_no = _prompt_frame([B["cancel_title"], B["cancel_yes"], B["cancel_no"], (385, 318, 408, 343)])
    cancel_no[318:343, 385:408] = 220.0
    assert S.prompt_kind(cancel_no) == {"prompt": "cancel", "cursor": "no"}
    cancel_yes = _prompt_frame([B["cancel_title"], B["cancel_yes"], B["cancel_no"]])
    cancel_yes[283:307, 385:408] = 220.0
    assert S.prompt_kind(cancel_yes) == {"prompt": "cancel", "cursor": "yes"}
    load = _prompt_frame([B["load_title"], B["load_opts"]])
    assert S.prompt_kind(load) == {"prompt": "load"}
    assert S.prompt_kind(_prompt_frame([])) is None


def test_cancel_loading_is_answered_yes_and_load_data_is_cancelled():
    D.begin_run()
    now = 100.0
    assert D.step({"where": "story_prompt", "prompt": "cancel", "cursor": "no"}, now) == D.STORY_UP_KEY
    assert D.step({"where": "story_prompt", "prompt": "cancel", "cursor": "yes"}, now + 0.1) is None, "paced"
    assert D.step({"where": "story_prompt", "prompt": "cancel", "cursor": "yes"}, now + 1.0) == "a"
    assert D.step({"where": "story_prompt", "prompt": "load"}, now + 4.0) == D.STORY_RECOVER_KEY
    assert D.step({"where": "story_prompt"}, now + 8.0) == D.STORY_RECOVER_KEY, "an unread prompt is still cancelled"


def test_a_named_prompt_keeps_its_kind_through_the_reader(monkeypatch):
    r = S.Reader()
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "story_prompt", "prompt": "cancel", "cursor": "no"})
    assert r.read(b"") == {"where": "story_prompt", "prompt": "cancel", "cursor": "no"}


def test_a_load_prompt_reading_without_the_list_before_it_is_not_the_prompt(monkeypatch):
    """Live 2026-11-10 21:42: Select Player lit the Load data? boxes and the walk cancelled out of it. Load data? only
    ever follows the save list."""
    r = S.Reader()
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "story_prompt", "prompt": "load"})
    assert r.read(b"")["where"] == "unknown"
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "story", "story": "story_load_list"})
    r.read(b"")
    monkeypatch.setattr(S, "classify", lambda _png: {"where": "story_prompt", "prompt": "load"})
    assert r.read(b"") == {"where": "story_prompt", "prompt": "load"}
