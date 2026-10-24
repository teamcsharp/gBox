"""RE6 (PS3, RPCS3) Mercenaries menus interface (gbox.mercs.titles.re6_ps3): the honest pre-measurement contract.

The X360 sibling (test_re6_menus.py) names a round from SPLAYER because those offsets were measured. The PS3 build has
no measured offset yet, so this test pins exactly what the driver can promise before a live session: out of a round it
is "unknown" and never guessed, BOOT_KEY is START (never A), the blind stage pick and 9-character roster hold, and the
menu_state() hook — once measured — drives select_stage / select_player the same way as the X360 build.
"""
import random

from gbox import mercs_bot as B
from gbox.mercs.titles import re6_ps3 as R


class Mem:
    def __init__(self):
        self.b = {}

    def rd(self, a, n):
        return bytes(n)          # nothing mapped: out-of-round / pre-boot


def fresh():
    R.ROSTER.__init__(random.Random(1))
    R.STAGE_PICK.__init__(random.Random(2))


def test_player_is_none_until_a_live_session_measures_splayer():
    fresh()
    assert R.player(Mem()) is None            # no fabricated SPLAYER/UPlayer chain


def test_out_of_a_round_it_is_unknown_and_never_guessed():
    fresh()
    assert R.screen(Mem())["where"] == "unknown"
    assert R.menu_state(Mem()) is None


def test_boot_key_is_start_never_a_which_would_start_campaign():
    fresh()
    assert R.BOOT_KEY == "start"
    assert R.BOOT_KEY != "a"            # never the A button (A on the title starts Campaign)
    assert R.step({"where": "unknown"}) is None      # unknown -> no blind A


def test_menu_state_hook_names_screens_once_measured(monkeypatch):
    fresh()
    monkeypatch.setattr(R, "menu_state", lambda m: {"where": "select_stage", "cursor": None})
    assert R.screen(Mem())["where"] == "select_stage"
    monkeypatch.setattr(R, "menu_state", lambda m: {"where": "select_player", "cursor": 4})
    scr = R.screen(Mem())
    assert scr["target"] in range(len(R.CHARACTERS)) and scr["cursor"] == 4


def test_roster_is_the_nine_console_characters():
    fresh()
    assert len(R.CHARACTERS) == 9
    assert R.CHARACTERS[0] == "Leon" and R.CHARACTERS[-1] == "Agent"


def test_stage_pick_is_random_rights_then_a_and_counts_only_reported_presses():
    fresh()
    scr = {"where": "select_stage"}
    seen = set()
    for seed in range(40):
        R.STAGE_PICK.__init__(random.Random(seed))
        n = 0
        while R.step(scr) == "dright":
            R.pressed(scr, "dright")
            n += 1
        assert n <= len(R.STAGES) - 1 and R.step(scr) == "a"
        R.pressed(scr, "a")
        assert R.STAGE_PICK.left is None
        seen.add(n)
    assert seen == set(range(len(R.STAGES)))
    R.STAGE_PICK.__init__(random.Random(0))
    k = R.step(scr)
    left = R.STAGE_PICK.left
    assert R.step(scr) == k and R.STAGE_PICK.left == left      # an unreported press changes nothing


def test_roster_draws_least_played_never_the_last():
    fresh()
    seen = []
    for _ in range(len(R.CHARACTERS)):
        R.ROSTER.want()
        seen.append(R.ROSTER.started())
    assert sorted(seen) == sorted(R.CHARACTERS)
    assert all(a != b for a, b in zip(seen, seen[1:]))


def test_step_covers_title_results_dead_and_never_wanders_into_a_story():
    assert R.step({"where": "title"}) == "start" and R.step({"where": "results"}) == "start"
    assert R.step({"where": "dead"}) == "a"
    assert R.wandered({"where": "select_stage"}) is None
    assert "left The Mercenaries" in R.wandered({"where": "campaign"})
