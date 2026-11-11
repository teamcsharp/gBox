"""Player 1's pad decision for a PSO launch: gBox's virtual pad by default, the operator's controller when the vpad is off.

`_want_vpad` is the switch that decides whether Player 1 is gBox's ViGEm pad (focus-free bot input) or the operator's own controller.
For PSO it used to be unconditional; `GBOX_DOLPHIN_VPAD=off` is the documented way to give Player 1 to the operator, and these tests
pin both directions so the operator's setting cannot silently regress.
"""
import os
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gbox import adapters, vpad_win                              # noqa: E402


def adapter(gecko: str = "GPOE8P", capture: bool = False):
    """The smallest object `_want_vpad` reads; no emulator, no session."""
    return types.SimpleNamespace(gecko_id=gecko, capture_backend="x" if capture else None)


@pytest.fixture(autouse=True)
def _vpad_available(monkeypatch):
    monkeypatch.setattr(vpad_win, "available", lambda: True, raising=False)


@pytest.mark.skipif(os.name != "nt", reason="the Windows Dolphin adapter's virtual pad is a Windows path")
def test_psos_player_one_is_the_virtual_pad_by_default(monkeypatch):
    monkeypatch.delenv("GBOX_DOLPHIN_VPAD", raising=False)
    assert adapters.DolphinWinAdapter._want_vpad(adapter()) is True


@pytest.mark.skipif(os.name != "nt", reason="the Windows Dolphin adapter's virtual pad is a Windows path")
def test_off_gives_player_one_to_the_operator(monkeypatch):
    monkeypatch.setenv("GBOX_DOLPHIN_VPAD", "off")
    assert adapters.DolphinWinAdapter._want_vpad(adapter()) is False


@pytest.mark.skipif(os.name != "nt", reason="the Windows Dolphin adapter's virtual pad is a Windows path")
def test_other_titles_keep_the_keyboard_unless_asked(monkeypatch):
    monkeypatch.delenv("GBOX_DOLPHIN_VPAD", raising=False)
    assert adapters.DolphinWinAdapter._want_vpad(adapter(gecko="GALE01")) is False   # not a GPO* disc
    monkeypatch.setenv("GBOX_DOLPHIN_VPAD", "all")
    assert adapters.DolphinWinAdapter._want_vpad(adapter(gecko="GALE01")) is True    # explicit opt-in for every title


@pytest.mark.skipif(os.name != "nt", reason="the Windows Dolphin adapter's virtual pad is a Windows path")
def test_a_capture_session_never_takes_the_virtual_pad(monkeypatch):
    monkeypatch.delenv("GBOX_DOLPHIN_VPAD", raising=False)
    assert adapters.DolphinWinAdapter._want_vpad(adapter(capture=True)) is False


@pytest.mark.skipif(os.name != "nt", reason="the Windows Dolphin adapter's virtual pad is a Windows path")
def test_without_vigem_there_is_no_virtual_pad(monkeypatch):
    monkeypatch.delenv("GBOX_DOLPHIN_VPAD", raising=False)
    monkeypatch.setattr(vpad_win, "available", lambda: False, raising=False)
    assert adapters.DolphinWinAdapter._want_vpad(adapter()) is False
