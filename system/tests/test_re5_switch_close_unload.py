"""Operator 2026-11-10: gun up + someone within 5 m = unload; more mines in RE5."""
import math

from gbox.mercs.titles import re5_switch as sw
from gbox.mercs.titles import re5_switch_mines as mines


def test_close_unload_knobs():
    assert sw.CLOSE_UNLOAD is True
    assert sw.CLOSE_UNLOAD_R == 500.0
    assert 0 < sw.CLOSE_UNLOAD_YAW <= math.radians(30)


def test_mines_dropped_more_often():
    assert sw.MINE_EVERY_S <= 15.0
    assert mines.EVERY_S <= 15.0
