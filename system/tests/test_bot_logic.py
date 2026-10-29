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


def test_weapon_menu_lists_re6_most_powerful_first_and_equips_through_live_weapon(monkeypatch):
    from gbox.mercs import bot_logic
    from gbox.mercs.titles import re6_switch_mods as R6
    calls = []

    def run(ad, op, *a, **kw):
        calls.append((op, kw))
        if op == "weapons":
            return {"verified": True, "next_weapon": "0x108",
                    "weapons": [{"id": i, "name": n, "kind": R6.WEAPON_KIND.get(i, "weapon"), "loaded": i == 4}
                                for i, n in R6.WEAPON_NAMES.items()]}
        return {"verified": True, "weapon": R6.WEAPON_NAMES[kw["weapon"]], "loaded": False, "next_round": True}
    monkeypatch.setattr(R6, "run", run)
    out = bot_logic.weapon_menu(object(), "re6", 7)
    assert calls[0] == ("live_weapon", {"weapon": 7})
    assert out["weapon_result"]["weapon"] == "Lightning Hawk"
    ids = [w["id"] for w in out["weapons"]]
    assert ids[:4] == [27, 11, 8, 7] and ids[-1] == 0 and 40 not in ids
    assert next(w for w in out["weapons"] if w["id"] == 4)["loaded"] is True
    assert out["weapon_current"] == 8


def test_weapon_menu_re5_overrides_for_next_round_and_selects_when_loaded(monkeypatch):
    from gbox.mercs import bot_logic
    from gbox.mercs.titles import re5_switch_mods as SW
    calls = []

    def tool_run(ad, op, *a, **kw):
        calls.append(op)
        if op == "weapon_override":
            return {"weapon_override": {"item": kw["weapon"], "weapon": "S&W M500"}}
        return {"queued": True}
    monkeypatch.setattr(SW, "tool_run", tool_run)
    monkeypatch.setattr(bot_logic, "_weapon_rows", lambda ad, t: {"weapons": [], "weapon_current": 0x1B})
    out = bot_logic.weapon_menu(object(), "re5", 0x1B)
    assert calls == ["weapon_override", "select_weapon"]
    assert out["weapon_result"]["loaded"] is True and "in hand now" in out["weapon_result"]["note"]
    with pytest.raises(ValueError):
        bot_logic.weapon_menu(object(), "re5", 0x15)                 # the Gatling gun: not a player weapon here


def test_weapon_menu_reading_failure_never_fails_the_settings(monkeypatch):
    from gbox.mercs import bot_logic

    def boom(ad, t):
        raise OSError("no RAM")
    monkeypatch.setattr(bot_logic, "_weapon_rows", boom)
    out = bot_logic.weapon_menu(object(), "re6")
    assert out["weapons"] == [] and "no RAM" in out["weapon_error"]
