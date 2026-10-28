"""The operator's live bot logic (gbox.mercs.bot_logic): the PiP sidebar's settings set on the running bot module at
once, bounded, saved, and put back after a hot reload."""
import pytest

from gbox.mercs import bot_logic as BL
from gbox.mercs.titles import re6_switch as R6


@pytest.fixture
def path(tmp_path, monkeypatch):
    saved = {n: getattr(R6, n) for n in ("FLASH_GAP_S", "NADES", "FLASH_N")}
    yield tmp_path / "bot-logic.json"
    for n, v in saved.items():
        setattr(R6, n, v)


def test_status_lists_the_live_knobs_with_their_values(path):
    st = BL.status("re6", path)
    names = {k["name"]: k for k in st["knobs"]}
    assert st["title"] == "re6" and "FLASH_GAP_S" in names and names["FLASH_GAP_S"]["value"] == R6.FLASH_GAP_S
    assert BL.status("01002A000CD48000", path)["title"] == "re6"          # a map id works too


def test_a_setting_lands_on_the_bot_at_once_bounded_and_saved(path):
    out = BL.handle("re6", {"FLASH_GAP_S": 2.5, "NADES": False, "FLASH_N": 99}, path=path)
    assert R6.FLASH_GAP_S == 2.5 and R6.NADES is False and R6.FLASH_N == 8          # 99 clamped to its maximum
    assert {k["name"]: k["set"] for k in out["knobs"]}["FLASH_GAP_S"] is True
    with pytest.raises(ValueError):
        BL.handle("re6", {"NOT_A_KNOB": 1}, path=path)
    R6.FLASH_GAP_S = 5.0                                                          # a hot reload: the shipped value back
    assert BL.apply_saved("re6", path)["FLASH_GAP_S"] == 2.5 and R6.FLASH_GAP_S == 2.5


def test_reset_puts_the_shipped_values_back(path):
    shipped = R6.FLASH_GAP_S
    BL.handle("re6", {"FLASH_GAP_S": 9.0}, path=path)
    BL.handle("re6", reset=["FLASH_GAP_S"], path=path)
    assert R6.FLASH_GAP_S == shipped and BL.apply_saved("re6", path) == {}
