"""Focused tests for the GE007 PC-port AllUnlocked profile (#2874). Not gameplay verification."""
from types import SimpleNamespace
from gbox import ge007_unlock as U, game_unlocks as G

INI = "[Video]\nVSync = 0\n[Game]\nAllUnlocked = 0\n[Input]\nNaturalPitch = 0\n"


def test_apply_preserves_settings_and_rolls_back(tmp_path):
    p = tmp_path / "ge007.ini"; p.write_text(INI)
    r = U.apply(p)
    assert r["applied"] and r["state"] == "applied_unverified"
    t = p.read_text()
    assert "AllUnlocked = 1" in t and "VSync = 0" in t and "NaturalPitch = 0" in t
    assert not U.apply(p)["changed"]                      # idempotent
    assert U.rollback(p)["AllUnlocked"] == "0" and p.read_text() == INI


def test_missing_ini_is_pending_build(tmp_path):
    assert U.apply(tmp_path / "none.ini")["state"] == "pending_build"


def test_profile_registered_and_honest():
    pr = G.profile_for({"game_id": U.GAME_ID})
    assert pr["verified"] is False and set(pr["scope"]) == set(U.CATEGORIES)
    assert set(U.INVENTORY) == set(U.CATEGORIES)


def test_pre_launch_hook(tmp_path):
    ini = tmp_path / "ports/ge007/src/data/ge007.ini"; ini.parent.mkdir(parents=True); ini.write_text(INI)
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=str(tmp_path)))
    r = G.pre_launch({"game_id": U.GAME_ID}, ctx)
    assert r["applied"] and r["verified"] is False
