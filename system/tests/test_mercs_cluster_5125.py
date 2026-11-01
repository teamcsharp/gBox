"""RE5 Mercenaries cluster #5125: torn (zero) laser at point-blank range must still fire."""
import pytest
from gbox.mercs.titles import re5_combat as C
from tests.test_re5_combat import world, snap, PL


@pytest.mark.parametrize("enemy_z", [90, 60, 100])
def test_torn_laser_at_point_blank_still_fires(tmp_path, enemy_z, monkeypatch):
    """Laser read is all-zeros (torn): _raw_ray returns None. Enemy within POINT_BLANK
    and player facing aligned -> bot fires (hold l1+r1) instead of seeking/turning."""
    m = world()
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m, enemy=(0.0, 0.0, float(enemy_z)))
    s["laser"] = {"from": [0.0, 0.0, 0.0], "at": [0.0, 0.0, 0.0]}  # torn read
    action = bot.tick(s, s["player"], s["enemies"][0], 1.0)
    assert "l1" in action["hold"], f"gun must stay up: {action['hold']}"
    assert "r1" in action["hold"], f"must fire at point-blank with torn laser: {action['hold']}"
    assert bot.stats.get("fire_gate") == "point blank", f"gate: {bot.stats.get('fire_gate')}"


def test_torn_laser_beyond_point_blank_does_not_fire(tmp_path):
    """Torn laser but enemy beyond POINT_BLANK: no blind fire."""
    m = world()
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m, enemy=(0.0, 0.0, 300.0))
    s["laser"] = {"from": [0.0, 0.0, 0.0], "at": [0.0, 0.0, 0.0]}
    action = bot.tick(s, s["player"], s["enemies"][0], 1.0)
    assert "r1" not in action["hold"], f"must NOT blind-fire beyond POINT_BLANK: {action['hold']}"
