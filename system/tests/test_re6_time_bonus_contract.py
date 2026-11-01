"""Time bonuses require approach and melee, including legacy bot paths."""
from gbox.mercs.titles import re6_switch as R
from test_re6_switch import _fresh_caches, lock_brain, run


def test_time_bonus_is_approached_and_meleed_even_with_lock_and_laser_contact():
    bot, clock, snap, writes = lock_brain(())
    snap["bonuses"] = [{"ptr": 1234, "kind": "time", "pos": (0.0, 0.0, 900.0)}]
    snap["laser"] = {"from": (0.0, R.BONUS_H, 0.0), "at": (0.0, R.BONUS_H, 900.0), "up": True}
    acts = run(bot, snap, clock, 3)
    assert any("lup" in a.get("hold", ()) for a in acts)
    assert all("zl" not in a.get("hold", ()) and "zr" not in a.get("hold", ()) for a in acts)
    assert bot.stats["bonus_shots"] == 0 and not writes
    snap["player"]["pos"] = (0.0, 0.0, 800.0)
    assert {"tap": "zr"} in run(bot, snap, clock, 12)
    assert bot.stats["bonus_melee"] > 0 and bot.stats["bonus_shots"] == 0


def test_direct_and_legacy_bonus_shoot_paths_cannot_shoot_time_bonuses(monkeypatch):
    monkeypatch.setattr(R, "BONUS_PURSUIT", True)
    bot, clock, snap, writes = lock_brain(())
    b = {"ptr": 1234, "kind": "time", "pos": (0.0, 0.0, 900.0)}
    snap["bonuses"] = [b]
    assert bot._bonus_shoot(snap["player"], b, snap, clock[0]) is None
    assert bot._bonus(snap["player"], [], lambda e: 9999, snap, clock[0]) is None
    assert bot.stats["bonus_shots"] == 0 and not writes
