"""The grenade ring's honest per-title/per-kind status (gbox.mercs.grenade_status).

Each row must say what the session can actually do: the title's built/verified kinds, the live controller's own
gate (RE4 GameCube's hand grenades need its verified unlimited life), and this moment's reason (no living player).
"""
from types import SimpleNamespace

import pytest

from gbox.mercs import grenade_status as G


class Ctl:
    """A controller stand-in: does it have a ring, and what do its kinds say?"""

    def __init__(self, kinds=None, ring=True, raises=False):
        self._kinds = kinds
        self._raises = raises
        if ring:
            self.grenade_ring = lambda *a, **k: {"state": "confirmed"}

    def grenade_kinds(self):
        if self._raises:
            raise RuntimeError("the round's status could not be read")
        return self._kinds


def rows_by_kind(game, controller=None, ready_error=""):
    rows = G.rows(game, controller, ready_error)
    assert rows is not None
    return {r["kind"]: r for r in rows}


def test_every_known_title_names_all_three_kinds():
    for key, title in G.TITLES.items():
        rows = G.rows({"game_id": next(iter(title.ids))}, None)
        assert [r["kind"] for r in rows] == list(G.KINDS), key
        # every kind is named; one served by the bot itself (RE4's mine-thrower ring) is offered without a controller
        assert all(r["available"] is False for r in rows if r["source"] != "bot"), key
        assert all(r["reason"] for r in rows if not r["available"]), key
        assert all((r["available"] is True) == (r["source"] == "bot") for r in rows), key


def test_an_unknown_session_gets_no_rows():
    assert G.rows({"game_id": "ffffffffffffffff", "title": "Some Other Game", "platform": "nes"}, None) is None
    assert G.identify(None, None) is None


def test_re4_switch_flash_and_hand_are_built_but_not_yet_verified():
    rows = rows_by_kind({"game_id": "270a15eb98dab4d7"})
    assert rows["flash"]["available"] is False and rows["flash"]["source"] == "title"
    assert "built on the RE4 Switch native harness" in rows["flash"]["reason"]
    assert "no live receipt" in rows["flash"]["reason"]
    assert rows["hand"]["available"] is False and "hand-grenade ring is built" in rows["hand"]["reason"]
    assert rows["incendiary"]["available"] is False and "does not offer" in rows["incendiary"]["reason"]


def test_re4_gc_uses_the_controllers_own_gate_and_names_the_missing_kind():
    game = {"game_id": "78ab9efa2e310db4"}
    ctl = Ctl([{"kind": "flash", "available": True},
               {"kind": "hand", "available": False, "reason": "verified unlimited health required"}])
    rows = rows_by_kind(game, ctl)
    assert rows["flash"]["available"] is True and rows["flash"]["source"] == "native"
    assert rows["hand"]["available"] is False and "unlimited health" in rows["hand"]["reason"]
    assert rows["incendiary"]["available"] is False and "does not offer" in rows["incendiary"]["reason"]
    # The controller says hand is safe: the row follows it, never the table.
    safe = Ctl([{"kind": "flash", "available": True}, {"kind": "hand", "available": True}])
    assert rows_by_kind(game, safe)["hand"]["available"] is True


def test_a_verified_kind_is_not_advertised_without_a_controller():
    rows = rows_by_kind({"game_id": "52d15709be0fda1a"})                 # RE5 Switch, no native controller
    assert rows["flash"]["available"] is False
    assert "controller is not available" in rows["flash"]["reason"]
    assert rows["hand"]["available"] is False and "not yet verified" in rows["hand"]["reason"]


def test_a_failed_controller_status_read_never_becomes_permission():
    ctl = Ctl([{"kind": "flash", "available": True}], raises=True)
    rows = rows_by_kind({"game_id": "78ab9efa2e310db4"}, ctl)
    assert rows["flash"]["available"] is False
    assert "could not be read" in rows["flash"]["reason"]


def test_no_living_player_replaces_the_reason_of_the_kinds_that_would_work():
    ctl = Ctl([{"kind": "flash", "available": True}])
    rows = rows_by_kind({"game_id": "115f9cdbba115432"}, ctl, G.NO_PLAYER)
    assert rows["flash"]["available"] is False and rows["flash"]["reason"] == G.NO_PLAYER
    # A kind that is refused for its own reason keeps it: the round is not what blocks a hand-grenade ring.
    assert "not yet verified" in rows["hand"]["reason"]


def test_re5_switch_flash_is_verified_and_the_others_are_not():
    ctl = Ctl([{"kind": "flash", "available": True, "reason": ""},
               {"kind": "hand", "available": False, "reason": "hand not verified"}])
    rows = rows_by_kind({"map_id": "010018100CD46000"}, ctl)
    assert rows["flash"]["available"] is True
    assert rows["hand"]["reason"] == "hand not verified"
    assert rows["incendiary"]["available"] is False


def test_re6_switch_ring_is_built_with_flash_verified():
    ctl = Ctl([{"kind": "flash", "available": True},
               {"kind": "hand", "available": False, "reason": "hand refused"},
               {"kind": "incendiary", "available": False, "reason": "incendiary refused"}])
    rows = rows_by_kind({"game_id": "115f9cdbba115432"}, ctl)
    assert rows["flash"]["available"] is True
    assert rows["flash"]["source"] == "native"
    assert rows["hand"]["reason"] == "hand refused"


@pytest.mark.parametrize("game,key", [
    ({"game_id": "115f9cdbba115432"}, "re6_switch"),
    ({"title_id": "01002A000CD48000"}, "re6_switch"),
    ({"map_id": "BLUS30491"}, "re5_ps3"),
    ({"game_id": "0ed22ae742e1b56b"}, "merc3d"),
    ({"serial": "SLUS-00923"}, "re3_psx"),
])
def test_identify_by_session_record(game, key):
    assert G.identify(game) == key


def test_identify_falls_back_to_the_controller_module():
    assert G.identify({}, Ctl()) is None                      # a bare stand-in names no module
    import gbox.mercs.titles.re6_switch_native as N6
    ctl = N6.Controller.__new__(N6.Controller)
    assert G.identify({}, ctl) == "re6_switch"


def test_identify_by_platform_and_name_as_a_last_resort():
    assert G.identify({"platform": "switch", "title": "Resident Evil 5"}) == "re5_switch"
    assert G.identify({"platform": "switch", "title": "Resident Evil 4"}) == "re4_switch"


def test_ring_available_needs_a_ready_controller_and_a_live_kind():
    ctl = Ctl([{"kind": "flash", "available": True}])
    game = {"game_id": "115f9cdbba115432"}
    assert G.ring_available(game, ctl) is True
    assert G.ring_available(game, ctl, G.NO_PLAYER) is False
    assert G.ring_available(game, None) is False
    assert G.ring_available({"game_id": "361337431d93bd1b"}, ctl) is False   # RE3: no ring at all


def test_summary_speaks_for_the_button():
    ctl = Ctl([{"kind": "flash", "available": True}])
    game = {"game_id": "115f9cdbba115432"}
    working = G.summary(game, ctl)
    assert working["available"] is True and working["verified"] == ["flash"]
    blocked = G.summary(game, ctl, G.NO_PLAYER)
    assert blocked["available"] is False and blocked["reason"] == G.NO_PLAYER
    assert G.summary({"game_id": "ffff"}, object()) == {}       # nothing to say: no title, no rows


def test_an_unknown_title_publishes_only_what_its_controller_reports():
    ctl = Ctl([{"kind": "flash", "available": True, "reason": ""},
               {"kind": "hand", "available": False, "reason": "no hand ring"}])
    rows = G.rows({"game_id": "ffff"}, ctl)
    assert [r["kind"] for r in rows] == ["flash", "hand"]      # no incendiary row invented
    assert rows[0]["available"] is True and rows[1]["reason"] == "no hand ring"
    error = G.rows({"game_id": "ffff"}, ctl, G.NO_PLAYER)
    assert error[0]["available"] is False and error[0]["reason"] == G.NO_PLAYER


def test_a_controller_that_attaches_on_demand_is_advertised_not_refused():
    """RE4 Switch: the status path only BINDS the player, so its kinds read "the harness is not attached" until a
    native op attaches it. The click itself attaches (Controller.ensure_attached), so the PiP must offer the kinds -
    otherwise the queue refuses every click and the operator never sees a ring on RE4."""
    class Attaches:
        def grenade_ring(self, *a, **k):
            return {"state": "confirmed"}

        def ensure_attached(self):
            return None

        def grenade_kinds(self):
            why = "the harness is not attached to the player"
            rows = [{"kind": k, "available": False, "reason": why} for k in ("flash", "hand", "mine")]
            rows.append({"kind": "incendiary", "available": False,
                         "reason": "the incendiary blast is not identified on this build yet"})
            return rows

    class NoAttach(Attaches):
        ensure_attached = None

    game = {"game_id": "270a15eb98dab4d7"}
    rows = {r["kind"]: r for r in G.rows(game, Attaches())}
    assert rows["flash"]["available"] is True and rows["hand"]["available"] is True
    assert rows["mine"]["available"] is True and rows["mine"]["source"] == "bot", \
        "the mine ring is served by the bot itself, so a native controller's attach state cannot park it"
    assert rows["incendiary"]["available"] is False, "a real refusal keeps its reason"
    other = {r["kind"]: r for r in G.rows(game, NoAttach())}
    assert other["flash"]["available"] is False and "not attached" in other["flash"]["reason"]


def test_a_probe_kind_keeps_its_source_even_when_the_controller_reports_it_available():
    # Live 2026-11-13: the launcher-shell rows reached the PiP without their source, so the Nitrogen click was sent
    # without allow_unverified and hit the native refusal instead of the research barrage.
    ctl = Ctl([{"kind": "shell1304", "available": True, "reason": ""},
               {"kind": "shell1302", "available": True, "reason": ""},
               {"kind": "flash", "available": True, "reason": ""}])
    rows = rows_by_kind({"game_id": "115f9cdbba115432"}, ctl)
    assert rows["shell1304"]["source"] == "probe" and rows["shell1304"]["available"] is True
    assert rows["shell1304"]["reason"].startswith("probe:")
    assert rows["shell1302"]["source"] == "probe"
    assert rows["flash"]["source"] == "native"

