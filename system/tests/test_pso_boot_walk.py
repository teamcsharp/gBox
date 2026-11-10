"""gbox.pso_boot_walk: the cold-boot press script and its RAM checkpoints, on a model game."""
import pytest

from gbox import pso_boot_walk as W


class Model:
    """A model of the boot: each press moves it one screen on, and RAM reports the same mode/floor the real game does."""

    SCREENS = ["title", "main_menu", "game_mode", "character_select", "editor", "episode", "town", "field"]
    MODES = {"title": 4, "main_menu": 1, "game_mode": 9, "character_select": 1,
             "editor": 1, "episode": 4, "town": 0, "field": 1}

    def __init__(self, screen="title", player_at="town"):
        self.at = self.SCREENS.index(screen)
        self.player_at = self.SCREENS.index(player_at)
        self.presses = []
        self.wrong = None                     # a step name to make the press a no-op, to test a failure

    def state(self):
        screen = self.SCREENS[self.at]
        playing = self.at >= self.player_at
        return {"mode": self.MODES[screen], "floor": 0 if screen == "town" else (1 if screen == "field" else 0),
                "episode": 1, "player": {"x": 0.0, "z": -2015.0, "room": 41} if playing else None,
                "entities": 29 if playing else 0}

    def press(self, keys):
        self.presses.append(tuple(keys))
        if self.wrong and self.wrong in self.presses[-1]:
            return
        self.at = min(self.at + 1, len(self.SCREENS) - 1)


def test_the_script_presses_through_to_pioneer_2():
    g = Model()
    out = W.walk(g.state, g.press, settle=0.0, sleep=lambda _s: None)
    assert out["ok"] is True and out["arrived"] is True
    assert [s["step"] for s in out["steps"]][0] == "start"
    assert g.presses[0] == ("start",) and ("ddown", "a") in g.presses
    # it stops the moment a player exists in Pioneer 2, it does not keep pressing
    assert g.presses[-1] == ("a",)


def test_a_title_that_does_not_advance_is_reported_not_retried():
    g = Model()
    g.wrong = "start"

    def press(keys):
        g.presses.append(tuple(keys))

    out = W.walk(g.state, press, settle=0.0, sleep=lambda _s: None)
    assert out["ok"] is False
    assert "still on the title" in out["why"]
    assert len(g.presses) == 1                     # one press, then it stopped


def test_a_walk_that_stalls_before_the_town_is_named():
    g = Model()
    presses = []

    def press(keys):
        presses.append(tuple(keys))
        if g.SCREENS[g.at] == "game_mode":
            return                                  # A does nothing on SELECT GAME MODE
        g.at += 1

    out = W.walk(g.state, press, settle=0.0, sleep=lambda _s: None)
    assert out["ok"] is False
    # with the verified step list, a stalled A is caught at the arrival checkpoint (only `offline_game` and the
    # arrival have unambiguous RAM signals; the menus in between all read mode 1)
    assert "no player in Pioneer 2" in out["why"]


def test_in_field_reports_town_and_field_from_floor_alone():
    g = Model()
    assert W.in_field(g.state)["in_town"] is True and W.in_field(g.state)["in_field"] is False
    g.at = Model.SCREENS.index("field")
    assert W.in_field(g.state)["in_field"] is True and W.in_field(g.state)["floor"] == 1


def test_the_checkpoints_name_what_ram_can_prove():
    assert W.TITLE_MODES == (0, 4, 22) and W.GAME_MODE_SELECT == 9
    assert [s[0] for s in W.BOOT_STEPS] == ["press_start", "offline_game", "single_mode", "character_slot",
                                           "confirm_character", "episode_one"]
    assert W.BOOT_STEPS[0][2] == "left_title"
    assert W.BOOT_STEPS[-1][2] == "in_town"


def test_the_attract_skip_presses_start_until_the_menu_appears():
    class Attract(Model):
        MODES = dict(Model.MODES, title=0, main_menu=1)

        def __init__(self):
            super().__init__()
            self.at = 0                      # mode 0 = attract
            self.left = 3                    # three START presses before the menu shows

        def press(self, keys):
            self.presses.append(tuple(keys))
            if self.left > 0:
                self.left -= 1
                return                       # still the attract: START skips the movie but does not open a menu
            self.at = 1

    g = Attract()
    out = W.reach_title(g.state, g.press, settle=0.0, sleep=lambda _s: None)
    assert out["ok"] is True and out["presses"] == 4 and out["state"]["mode"] == 1


def test_the_attract_skip_gives_up_and_says_how_long_it_tried():
    class Stuck(Model):
        MODES = dict(Model.MODES, title=0)

        def __init__(self):
            super().__init__()
            self.at = 0

        def press(self, keys):
            self.presses.append(tuple(keys))

    g = Stuck()
    out = W.reach_title(g.state, g.press, tries=5, settle=0.0, sleep=lambda _s: None)
    assert out["ok"] is False and out["presses"] == 5 and "attract" in out["why"]


def test_the_offline_step_must_reach_select_game_mode():
    """The one unambiguous checkpoint on the way in: mode 9 appears nowhere else."""
    class NoGameMode(Model):
        def press(self, keys):
            self.presses.append(tuple(keys))

    g = NoGameMode()
    g.at = Model.SCREENS.index("main_menu")
    out = W.walk(g.state, g.press, settle=0.0, sleep=lambda _s: None, start_at="offline_game")
    assert out["ok"] is False and "SELECT GAME MODE" in out["why"]
    assert g.presses == [("ddown", "a")]          # it stopped rather than pressing on blindly


def test_the_verified_path_arrives_with_six_presses():
    g = Model()
    out = W.walk(g.state, g.press, settle=0.0, sleep=lambda _s: None)
    assert out["ok"] is True and out["arrived"] is True
    assert len(g.presses) == 6
    assert g.presses[0] == ("start",) and g.presses[1] == ("ddown", "a")


def test_the_multi_mode_path_is_the_two_controller_branch():
    """MULTI MODE skips the single-player intro that nothing can exit; its presses were verified against frames."""
    assert [s[0] for s in W.MULTI_STEPS] == ["press_start", "offline_game", "multi_mode",
                                            "confirm_player1", "accept_player1"]
    assert W.MULTI_STEPS[1][2] == "game_mode_select"        # the one provable checkpoint, same as the single path
    assert W.MULTI_STEPS[2][1] == ("ddown", "a")            # SINGLE -> MULTI is one move down
    assert W.MULTI_STEPS[0][1] == ("start",)
