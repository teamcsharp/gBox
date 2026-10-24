"""Mercenaries 3D (3DS) menus module (gbox.mercs.titles.merc3d_3ds): an honest stub for a title with no
measured RAM map. Every read is `unknown` / None, BOOT_KEY is the neutral `start` (never A, whose title
action is unconfirmed), and nothing registers a roster or stage list — the mission-select automation and
`playable: True` flip are gated on a live Citra/Azahara RAM measurement that has not happened yet."""
import pytest

from gbox import mercmode
from gbox.mercs.titles import merc3d_3ds as M


class Mem:
    def __init__(self):
        self.b = {}

    def rd(self, a, n):
        return bytes(n)

    def put(self, a, fmt, *v):
        pass


def test_declares_nothing_measured():
    assert M.STAGES == () and M.CHARACTERS == () and M.STEPS == {} and M.CURSORED == ()
    assert M.player(Mem()) is None
    assert M.unlocked(Mem()) is None
    assert M.menu_state(Mem()) is None


def test_screen_is_honestly_unknown_out_of_round():
    assert M.screen(Mem()) == {"where": "unknown", "cursor": None, "target": None}


def test_boot_key_is_start_never_a():
    # A's title action is unconfirmed on 3DS, so a blind advance must use the neutral start key.
    assert M.BOOT_KEY == "start"
    assert M.step(Mem()) is None
    assert M.step({"where": "unknown"}) is None


def test_no_step_wander_or_press_without_a_measured_cursor():
    assert M.wandered(Mem()) is None
    assert M.wandered({"where": "unknown"}) is None
    assert M.pressed(Mem(), "a") is None
    assert M.pressed({"where": "unknown"}, "dright") is None


def test_menu_state_hook_falls_through_without_inventing_a_screen(monkeypatch):
    # even if menu_state later reports something, only a real 'where' is surfaced; offsets stay unmeasured
    monkeypatch.setattr(M, "menu_state", lambda m: {"where": "select_stage", "cursor": 3})
    scr = M.screen(Mem())
    assert scr == {"where": "select_stage", "cursor": 3, "target": None}


def test_merc3d_is_registered_but_not_playable():
    t = mercmode.TITLES["merc3d"]
    assert t["map_id"] == "CTR-ABRE" and t["platform"] == "3ds"
    assert t["game_ids"] == ("0ed22ae742e1b56b",)
    assert t["playable"] is False
    assert "reason" in t and "no measured offsets" in t["reason"]
    assert t["modes"] == ["mercenaries"]


def test_no_fabricated_roster_or_stage_list():
    # catalog() only names verified titles; merc3d must not expose a guessed roster for the DJ queue.
    assert mercmode.catalog().get("merc3d") is None
    with pytest.raises(ValueError, match="no verified roster or stage list"):
        mercmode.queue_entry({"title": "merc3d", "mode": "mercenaries"})
    assert mercmode.queue_entry({"title": "merc3d"}) == {"title": "merc3d", "mode": None,
                                                         "character": None, "stage": None}


def test_normalize_accepts_the_title_and_rejects_duplicates():
    assert mercmode.normalize({"titles": ["merc3d"]})["titles"] == ["merc3d"]
    with pytest.raises(ValueError):
        mercmode.normalize({"titles": ["merc3d", "merc3d"]})
