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
def test_story_screens_end_the_run(name):
    scr = S.classify(png_of(from_thumb(S.refs()["refs"][name])))
    assert scr["where"] == "story" and D.wandered(scr) == "story game"


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
            "enemies": [{"pos": (500.0, 0.0, 0.0), "hp": 100, "ptr": 1}]}
    assert bot.tick(snap)["hold"] == {"lright"}
