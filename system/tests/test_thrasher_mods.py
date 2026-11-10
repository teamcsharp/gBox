import pytest
from gbox import thrasher_mods as t


def test_all_requested_commands_present_and_unique():
    ids = [c.id for c in t.COMMANDS]
    assert len(ids) == len(set(ids)) == 20
    assert all(c.kind in t.KINDS and c.needs for c in t.COMMANDS)


def test_nothing_dispatchable_without_verified_addresses():
    assert not any(t.dispatchable(c.id) for c in t.COMMANDS)
    assert all(not c["resolved"] for c in t.manifest()["commands"])


def test_resolve_records_addresses_and_rejects_bad():
    c = t.resolve("reset_score", {"score": 0x80091234})
    assert c.resolved and c.addresses["score"] == 0x80091234
    with pytest.raises(ValueError):
        t.resolve("reset_score", {})
    with pytest.raises(ValueError):
        t.resolve("reset_score", {"score": -1})


def test_validate_defaults_ranges_and_enums():
    assert t.validate("gravity", {"scale": 2.0}) == {"scale": 2.0}
    assert t.validate("spawn_two_cops", {}) == {"count": 2}
    assert t.validate("camera_mode", {"mode": "cinematic"}) == {"mode": "cinematic"}
    for cmd, args in [("gravity", {"scale": 99}), ("camera_mode", {"mode": "x"}),
                      ("trick_score_multiplier", {"x": True}), ("reset_score", {"a": 1}),
                      ("nope", {}), ("camera_mode", {})]:
        with pytest.raises(ValueError):
            t.validate(cmd, args)
