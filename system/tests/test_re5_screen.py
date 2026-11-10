"""RE5 Mercenaries screen names and the operator's clock controls (operator 2026-10-26: stalemates).

screen() names the menus and round states from RAM (gbox/mercs/titles/re5_ps3.py); the clock controls
(add_time / set_time, gbox/re5_mods_tool.py) write the authoritative aGame countdown through the same verified
owner path the bots' stalemate cut uses. This test builds a fake guest memory laid out the way the live game
keeps its tables (found 2026-10-21: the executable dump + the Spark's RPCS3) and checks both.
"""
import struct

import pytest

from gbox import re5_mods_tool as T
from gbox.mercs.titles import re5_ps3 as R
from test_re5_mods import FakeRE5, fresh_originals  # noqa: F401
from test_re5_mods_time import GAME, GS, MAIN, SU, AREA, with_round


class Mem(FakeRE5):
    """The fake memory under the RE5 module's adapter interface (rd/wr -> read_memory/write_memory)."""

    def rd(self, a, n):
        return self.read_memory(a, n)

    def wr(self, a, data):
        return self.write_memory(a, data)

# UI unit vtables (gbox/mercs/titles/re5_ps3.py UI_VTABLES)
VT = {v: k for k, v in R.UI_VTABLES.items()}
STARTUP20 = VT["uIdStartUp20"]       # Original Mercenaries title / solo selector
STARTUP22 = VT["uIdStartUp22"]       # CHARACTER SELECT (Reunion)
STARTUP21 = VT["uIdStartUp21"]       # STAGE SELECT (Reunion)
STARTUP29 = VT["uIdStartUp29"]       # Reunion's title
STARTUP01 = VT["uIdStartUp01"]       # PLAY GAME
STARTUP00 = VT["uIdStartUp00"]       # main menu
NOWLOADING = VT["uIdNowLoading00"]   # NOW LOADING
TITLE = VT["uIdTitle00"]             # PRESS START
CURSOR = VT["uIdCursor"]             # menus' cursors
GAMEOVER = VT["uIdGameover00"]       # Continue: state byte +0x17, Yes/No u32 +0x178

MENU_SUB = R.MENU_SUB                # +0x174: 1 = the sub-screen (SOLO / DUO)
SELECT_CURSOR = R.SELECT_CURSOR      # +0x180: CHARACTER SELECT cursor
MENU_CURSOR = R.MENU_CURSOR          # +0x44: cursor on the menus
EXTRA_CURSOR = R.EXTRA_CURSOR        # +0x188: EXTRA CONTENT cursor
TITLE_STEP = R.TITLE_STEP            # +0x1F8: 0x48 on PRESS START
TITLE_PRESS_START = R.TITLE_PRESS_START

PLAYER = 0x303F_89E0                 # the scoped P1 actor (test_re5_mods.py)


def _unit(m, vt, line, sub=0, cursor=0, extra=0):
    """One interface unit in the sUnit move line `line`, its vtable `vt`, chained from the line's first slot."""
    addr = 0x3110_0000 + line * 0x1000 + (sub << 8) + (cursor << 4) + extra
    m.u32(addr, vt)
    m.u32(addr + R.UNIT_NEXT, 0)      # no next unit in this line
    m.u32(addr + MENU_SUB, sub)
    m.u32(addr + SELECT_CURSOR, cursor)
    m.u32(addr + MENU_CURSOR, cursor)
    m.u32(addr + EXTRA_CURSOR, extra)
    m.u32(addr + TITLE_STEP, TITLE_PRESS_START if vt == TITLE else 0)
    return addr


def _line(m, line, units):
    """Chain `units` (addresses) into sUnit move line `line`: +0x24 + 0x20*line -> +0xC the line's first unit."""
    su = SU
    first = units[0]
    m.u32(su + R.UNIT_LINES + R.LINE_STRIDE * line + R.LINE_FIRST, first)
    for a, nxt in zip(units, units[1:] + [0]):
        m.u32(a + R.UNIT_NEXT, nxt)


def _no_units(m):
    """All interface lines empty."""
    for line in range(R.N_LINES):
        m.u32(SU + R.UNIT_LINES + R.LINE_STRIDE * line + R.LINE_FIRST, 0)


def _playing(m, clock=90.0, hp=1000):
    """A live round: the player up with health and time left."""
    with_round(m, clock=clock)
    m.u32(T.S_PLAYER, 0x3883_69C0)
    m.u32(0x3883_69C0 + 0x28, PLAYER)
    m.put(PLAYER + R.P_POS, struct.pack(">3f", 0.0, 0.0, 0.0))
    m.put(PLAYER + R.P_ROT, struct.pack(">4f", 0.0, 0.0, 0.0, 1.0))
    m.put(PLAYER + R.P_PITCH, struct.pack(">f", 0.0))
    m.put(PLAYER + R.P_HP, struct.pack(">hh", hp, 1000))
    m.put(PLAYER + R.P_ACTION, bytes([0]))
    return m


def _menus(m):
    """Out of a round: no player pointer, the interface units name the screen."""
    with_round(m, clock=0.0)
    m.u32(T.S_PLAYER, 0x3883_69C0)
    m.u32(0x3883_69C0 + 0x28, 0)      # no player: the round fields are gone
    return m


def test_screen_names_the_round_states_and_the_menus():
    # a live round: playing
    m = _playing(Mem(), clock=90.0)
    _no_units(m)
    assert R.screen(m)["where"] == "playing"

    # the clock at 0 with a cursor unit up: results
    m = _menus(Mem())
    u = _unit(m, CURSOR, 0)
    _line(m, 0, [u])
    m.f32(GS + T.GS_CLOCK, 0.0)
    assert R.screen(m)["where"] == "results"

    # the Original Mercenaries title (START first) and its SOLO sub-screen
    m = _menus(Mem())
    u = _unit(m, STARTUP20, 0, sub=0)
    _line(m, 0, [u])
    assert R.screen(m)["where"] == "mercs_title"
    m = _menus(Mem())
    u = _unit(m, STARTUP20, 0, sub=1)
    _line(m, 0, [u])
    assert R.screen(m)["where"] == "mercs_solo"

    # Reunion's title and its SOLO sub-screen
    m = _menus(Mem())
    u = _unit(m, STARTUP29, 0, sub=0)
    _line(m, 0, [u])
    assert R.screen(m)["where"] == "reunion_title"
    m = _menus(Mem())
    u = _unit(m, STARTUP29, 0, sub=1)
    _line(m, 0, [u])
    assert R.screen(m)["where"] == "reunion_solo"

    # NOW LOADING
    m = _menus(Mem())
    u = _unit(m, NOWLOADING, 0)
    _line(m, 0, [u])
    assert R.screen(m)["where"] == "loading"

    # PRESS START (the title screen, no top menu over it)
    m = _menus(Mem())
    u = _unit(m, TITLE, 0)
    _line(m, 0, [u])
    assert R.screen(m)["where"] == "title"


def test_screen_names_the_character_and_stage_selects_with_the_roster():
    # CHARACTER SELECT: the cursor names the character, the roster is the Reunion row
    m = _menus(Mem())
    u = _unit(m, STARTUP22, 0, cursor=2)
    _line(m, 0, [u])
    scr = R.screen(m)
    assert scr["where"] == "select_player"
    assert scr["mercenaries_mode"] in ("reunion", "mercenaries")          # no round mode: the roster stays where it was
    assert scr["character_roster"] == list(R.ROSTER.characters)
    assert scr["character_cursor"] == R.ROSTER.characters[2]

    # STAGE SELECT: the cursor names the stage
    m = _menus(Mem())
    u = _unit(m, STARTUP21, 0, cursor=3)
    _line(m, 0, [u])
    scr = R.screen(m)
    assert scr["where"] == "select_stage"
    assert scr["cursor"] == 3

    # PLAY GAME -> EXTRA CONTENT (the Mercenaries Reunion list)
    m = _menus(Mem())
    u = _unit(m, STARTUP01, 0, sub=1, extra=3)
    _line(m, 0, [u])
    scr = R.screen(m)
    assert scr["where"] == "extra_content"
    assert scr["cursor"] == 3


def test_the_operator_clock_controls_write_the_authoritative_countdown():
    # the stalemate cut's owner path (set_clock) and the panel's controls (add_time / set_time) all write the
    # authoritative aGame countdown; a cut never leaves less than MIN_CLOCK_S and shows no "+NN Sec." notice
    m = with_round(Mem(), clock=120.0)
    r = T.set_clock(m, 5)
    assert r["verified"] and r["clock_after"] == 5.0 and r["clock_before"] == 120.0
    assert (GS + T.GS_SHOW_BONUS, 1) not in m.writes        # a cut shows no bonus notice

    m = with_round(Mem(), clock=60.0)
    r = T.run(m, "add_time", seconds=-30)                    # the operator's slider: take time away
    assert r["verified"] and r["clock_after"] == 30.0 and r["added_seconds"] == -30
    assert (GS + T.GS_SHOW_BONUS, 1) not in m.writes        # a cut shows no bonus notice

    m = with_round(Mem(), clock=60.0)
    r = T.run(m, "add_time", seconds=30)                     # add time: the HUD shows the native bonus
    assert r["verified"] and r["clock_after"] == 90.0 and r["added_seconds"] == 30
    assert (GS + T.GS_SHOW_BONUS, 1) in m.writes

    m = with_round(Mem(), clock=60.0)
    r = T.run(m, "set_time", multiplier=5)                   # set the countdown to a custom time (5 s)
    assert r["verified"] and r["clock_after"] == 5.0 and r["set_seconds"] == 5

    # a cut never leaves less than MIN_CLOCK_S on the clock
    m = with_round(Mem(), clock=3.0)
    r = T.set_clock(m, 0)
    assert r["verified"] and r["clock_after"] == T.MIN_CLOCK_S