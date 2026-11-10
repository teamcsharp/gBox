import pytest
from gbox import thrasher_plan as t


def setup_function(_):
    t._state.clear()


def test_catalog_covers_all_twenty_requested_controls_pending():
    c = t.catalog()
    assert len(c) == 20 and len({x["key"] for x in c}) == 20
    assert all(x["status"] == t.PENDING and x["needs"] for x in c)
    assert t.GAME_ID is None


def test_unmapped_commands_are_refused():
    ok, why = t.validate_command("gravity", 1.0)
    assert not ok and "research_pending" in why
    assert t.validate_command("nope")[0] is False


def test_promote_requires_evidence_and_enables_range_checks():
    with pytest.raises(ValueError):
        t.promote("gravity", "0x80", "x")
    with pytest.raises(ValueError):
        t.promote("gravity", "0x80123456", " ")
    t.promote("gravity", "0x80123456", "frozen value changed arc in emulator")
    assert t.validate_command("gravity", 1.5) == (True, "ok")
    assert not t.validate_command("gravity", 99)[0]
    assert not t.validate_command("gravity", True)[0]


def test_choice_and_toggle_validation():
    t.promote("camera_mode", "0x80010000", "e")
    t.promote("no_fall", "0x80010004", "e")
    assert t.validate_command("camera_mode", "pursuit")[0]
    assert not t.validate_command("camera_mode", "top")[0]
    assert t.validate_command("no_fall", True)[0]
    assert not t.validate_command("no_fall", 1)[0]
