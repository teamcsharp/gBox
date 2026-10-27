"""RE5 Switch in MercMode's warm pool (gbox.mercs.warm_boot + gbox.mercs.titles.re5_switch.warm_probe): the title's own
reader is found from the catalog, it reads only native menus of this exact build, the boot observer pauses on a stable
one and the receipt names the Switch title; the menus' screen calls the round's intro "playing" so a prepare parks
there, before the round clock runs."""
import struct
from types import SimpleNamespace

import pytest

from gbox import mercs_bot, re_switch
from gbox.mercs import warm_boot as W
from gbox.mercs.titles import re5_switch as R
from tests.test_re5_switch import BASE, Guest, round_guest

SWITCH = {"game_id": re_switch.RE5_GAME_ID, "platform": "switch"}


@pytest.fixture(autouse=True)
def _fresh_laser_caches():
    for cache in (R._LASER, R._LASER_MISS, R._NOT_LASER):
        cache.clear()
    yield


class Emulator:
    def __init__(self):
        self.proc = SimpleNamespace(poll=lambda: None)
        self.generation = 0
        self.pauses = 0

    def pause(self):
        self.pauses += 1
        return {"paused": True, "via": "SIGSTOP"}

    def resume(self):
        return {"paused": False}


def menu_guest(*units, alert=None):
    g = round_guest(phase=R.PHASE_OVER, player=False, units=tuple((i + 1, n) for i, n in enumerate(units)),
                    cursors={"uIdAlert00": {R.ALERT_UP: 0xC0, R.ALERT_ID: alert}} if alert else None)
    return g


def test_the_title_s_own_reader_is_found_from_the_catalog_for_its_platform_only():
    assert W.title_probe(None, SWITCH) is R.warm_probe
    assert W.title_probe(None, {"game_id": re_switch.RE5_GAME_ID, "platform": "ps3"}) is None   # another edition
    assert W.title_probe(None, {"game_id": W.RE5_ID, "platform": "ps3"}) is None               # its reader is built in
    assert W.title_probe(None, {"game_id": "unknown", "platform": "switch"}) is None
    assert W.title_probe(None, {}) is None


@pytest.mark.parametrize("unit,screen", [("uIdStartUp00", "main_menu"), ("uIdStartUp01", "play_game"),
                                         ("uIdStartUp29", "mercs_title"), ("uIdStartUp21", "select_stage"),
                                         ("uIdStartUp22", "select_player")])
def test_warm_probe_calls_a_native_menu_ready_with_its_unit_as_token(unit, screen):
    g = menu_guest(unit)
    out = R.warm_probe(g)
    assert out["ready"] is True and out["screen"] == screen and out["title"] == R.MAP_ID == re_switch.RE5_TITLE_ID
    assert out["token"] == (unit, R.ui_units(g)[unit])


def test_warm_probe_waits_out_loading_and_answers_only_load_successful():
    assert R.warm_probe(menu_guest("uIdStartUp00", "uIdNowLoading00")) == {"ready": False, "screen": "loading",
                                                                            "title": R.MAP_ID}
    ok = R.warm_probe(menu_guest("uIdAlert00", alert=0x08))
    assert ok["ready"] is True and ok["screen"] == "alert_ok" and ok["token"][0] == "alert"
    assert R.warm_probe(menu_guest("uIdAlert00", alert=0x33))["ready"] is False      # the Leaderboards prompt


def test_the_title_is_ready_once_its_state_pointer_is_up():
    g = menu_guest("uIdAlert00", "uIdTitle00")
    assert R.warm_probe(g) == {"ready": False, "screen": "title", "title": R.MAP_ID}   # the unit alone: black screen
    unit = R.ui_units(g)["uIdTitle00"]
    state = g.alloc(0x100)
    g.q(unit + R.TITLE_READY, state)
    out = R.warm_probe(g)
    assert out["ready"] is True and out["screen"] == "title" and out["token"] == ("uIdTitle00", unit, state)
    g.q(unit + R.TITLE_READY, 0x1234)                                            # not a pointer: not ready
    assert R.warm_probe(g)["ready"] is False


def test_warm_probe_needs_this_build_and_rescans_for_it_sparingly(monkeypatch):
    g = Guest()
    g.put(BASE + R.SIG_OFF, bytes(len(R.SIGNATURE)))                              # another build (or main not mapped)
    calls = []
    real = R.module_base
    monkeypatch.setattr(R, "module_base", lambda m: calls.append(1) or real(m))
    assert R.warm_probe(g) == {"ready": False, "screen": "unknown", "title": R.MAP_ID}
    assert R.warm_probe(g)["ready"] is False and len(calls) == 1                   # inside WARM_RESCAN_S: no new scan
    g._warm_miss -= R.WARM_RESCAN_S + 1
    R.warm_probe(g)
    assert len(calls) == 2


def test_the_boot_observer_pauses_on_a_stable_switch_menu_and_the_receipt_names_the_switch_title(monkeypatch):
    g = menu_guest("uIdStartUp00")
    monkeypatch.setattr(mercs_bot, "_memory", lambda _ad: g)
    ad, now = Emulator(), [0.0]
    prep = W.Preparation(ad, SWITCH, lambda: True, clock=lambda: now[0])
    assert prep.tick() and not ad.pauses                                          # first sight: wait for it to hold
    now[0] = 2.0
    assert not prep.tick() and ad.pauses == 1 and ad.gbox_warm is True
    receipt = prep.snapshot()
    assert receipt["state"] == "ready" and receipt["screen"] == "main_menu" and receipt["source"] == "native_menu"
    session = {"detail": {"warm": receipt}}
    assert W.prepared(session, {}, re_switch.RE5_TITLE_ID) and not W.prepared(session, {}, "BLUS30491")


def test_an_unsupported_game_still_never_opens_memory(monkeypatch):
    monkeypatch.setattr(mercs_bot, "_memory", lambda _: pytest.fail("must not open unsupported memory"))
    assert W.native_probe(Emulator(), {"game_id": re_switch.RE5_GAME_ID, "platform": "gamecube"})()["unsupported"]


def test_the_round_intro_is_playing_for_the_menus_and_loading_for_the_engine():
    g = round_guest(phase=R.PHASE_INTRO)
    scr = R.screen(g)
    assert scr["where"] == "playing" and scr["intro"] is True                    # the walk (and a prepare) stops here
    assert R.own_screen(R.snapshot(g)) == "loading" and R.RE5Switch().screen(g, None) == "loading"   # the engine waits
    loading = round_guest(phase=R.PHASE_INTRO, units=((29, "uIdNowLoading00"),))
    assert R.screen(loading)["where"] == "loading"
    assert "intro" not in R.screen(round_guest())                                 # the clock running: plain "playing"
