"""RE6 Switch's flash policy on a replayed minute (synthetic: a static crowd round him, the game's item wheel answered by
a stand-in): the old one (a flash every FLASH_GAP_S and its flurry, grenade cycles at the ones in sight) against the
operator's of 2026-11-10 14:30 (one flash a minute, a tight situation only, the gun first at one in sight). The numbers
the tests print are the replay's flashes per minute, shots, the seconds spent firing and in grenade cycles."""
import pytest

from gbox.mercs.titles import re6_switch as R
from tests.test_re6_switch import round_guest
from tests.test_re6_switch_equip import NativeBridge

FLASH, FRAG = 11, 9


def replay(monkeypatch, old: bool, crowd, seconds: float = 60.0, dt: float = 0.05):
    monkeypatch.setattr(R, "NADES", True)
    monkeypatch.setattr(R, "FLASH", True)
    if old:
        monkeypatch.setattr(R, "FLASH_MIN_GAP_S", 0.0)
        monkeypatch.setattr(R, "FLASH_TIGHT", False)
        monkeypatch.setattr(R, "FIRE_FIRST", False)
    clock = [0.0]
    bridge = NativeBridge()
    bot = R.Bot(stats={}, clock=lambda: clock[0], equip=bridge)
    bot.held = lambda p, now: False
    snap = R.snapshot(round_guest(enemies=crowd, cam_yaw=0.0))
    p = snap["player"]
    p.update(equipped=0, nades={0x113: (FRAG, 50), 0x115: (FLASH, 50)}, guns={0x107: 0}, gun_ammo={0: 99}, ammo=99)
    seen = 0
    while clock[0] < seconds:
        clock[0] += dt
        bot.tick(snap)
        if len(bridge.targets) > seen:                    # the game puts what was asked in his hand
            p["equipped"] = bridge.targets[-1]
            seen = len(bridge.targets)
    st = bot.stats
    return {"flashes": st.get("flashes", 0), "frags": st.get("frags", 0), "shots": st.get("shots", 0),
            "t_fire": round(st.get("t_fire", 0.0), 1), "t_nade": round(st.get("t_nade", 0.0), 1),
            "skips": st.get("flash_gap_skips", 0) + st.get("flash_untight_skips", 0), "stats": st}


SURROUND = ((0.0, 0.0, 200.0, 700), (150.0, 0.0, 180.0, 700), (-150.0, 0.0, 190.0, 700), (100.0, 0.0, -200.0, 700),
            (0.0, 0.0, 450.0, 700))                     # four within 3 m and one behind them: tight
NEAR = ((0.0, 0.0, 250.0, 700), (120.0, 0.0, 350.0, 700), (-120.0, 0.0, 380.0, 700))   # three near: a crowd, not tight


def test_a_surrounded_minute_gets_one_flash_and_the_gun_does_the_rest(monkeypatch):
    before = replay(monkeypatch, True, SURROUND)
    monkeypatch.undo()
    after = replay(monkeypatch, False, SURROUND)
    print(f"\nsurrounded, 60 s - before: {before['flashes']} flashes, {before['shots']} shots, t_fire {before['t_fire']} s, "
          f"t_nade {before['t_nade']} s; after: {after['flashes']} flashes, {after['shots']} shots, t_fire "
          f"{after['t_fire']} s, t_nade {after['t_nade']} s ({after['skips']} flash asks held)")
    assert before["flashes"] >= 4, "the old policy flashed the crowd again and again"
    assert after["flashes"] <= 1, "one flash a minute at most"
    assert after["t_nade"] < before["t_nade"] and after["shots"] >= before["shots"]
    if after["flashes"]:
        assert after["stats"]["flash_reasons"].get("surrounded"), "the flash's tight reason is logged"


def test_a_crowd_that_is_not_tight_gets_no_flash_at_all(monkeypatch):
    before = replay(monkeypatch, True, NEAR)
    monkeypatch.undo()
    after = replay(monkeypatch, False, NEAR)
    print(f"\nthree near, 60 s - before: {before['flashes']} flashes, {before['shots']} shots, t_fire {before['t_fire']} s, "
          f"t_nade {before['t_nade']} s; after: {after['flashes']} flashes, {after['shots']} shots, t_fire "
          f"{after['t_fire']} s, t_nade {after['t_nade']} s")
    assert before["flashes"] >= 2 and after["flashes"] == 0
    assert after["t_fire"] >= before["t_fire"] and after["t_nade"] <= before["t_nade"]
