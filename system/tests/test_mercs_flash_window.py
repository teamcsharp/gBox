"""The flash on the crowd and its window (gbox.mercs.core.flash_window), RE5 Switch's use of them (re5_switch
FLASH_PLACE / FLASH_WINDOW), and the flash ring under the same minute - synthetic state only."""
import math
import time
from types import SimpleNamespace

import pytest

from gbox.mercs.core import flash_window as W
from gbox.mercs import grenade_ring as G
from gbox.mercs import interventions
from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_mines as MN


# --- the placement ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("foes", [[(100.0, 0.0, 0.0)], [(50.0, 0.0, 50.0), (-60.0, 0.0, 40.0), (0.0, 0.0, -80.0)],
                                  [(800.0, 0.0, 300.0), (900.0, 0.0, -200.0)], [(0.0, 0.0, 0.0)]])
def test_the_flash_never_goes_off_within_his_reach_and_stays_on_his_floor(foes):
    me = (0.0, 50.0, 0.0)
    pt = W.place(me, foes, 400.0, 900.0, 1200.0)
    d = math.hypot(pt[0] - me[0], pt[2] - me[2])
    assert 400.0 - 1e-6 <= d <= 900.0 + 1e-6 and pt[1] == me[1]


def test_the_flash_goes_toward_the_crowd():
    pt = W.place((0.0, 0.0, 0.0), [(300.0, 0.0, 0.0), (350.0, 0.0, 50.0), (-100.0, 0.0, 1100.0)])
    assert pt[0] > 300.0 and abs(pt[2]) < pt[0], "the near pack weighs more than the far one"


def test_no_one_near_no_flash():
    assert W.place((0.0, 0.0, 0.0), []) is None
    assert W.place((0.0, 0.0, 0.0), [(5000.0, 0.0, 0.0)]) is None
    assert W.place((0.0, 0.0, 0.0), [(100.0, 600.0, 0.0)]) is None, "another floor"


# --- the window ------------------------------------------------------------------------------------------------------
def test_the_window_plans_a_mine_then_a_grenade_then_a_step_then_fire():
    stats = {}
    w = W.Window(stats, window_s=3.5, move_s=0.9)
    w.open(10.0, kills=5)
    me = (0.0, 0.0, 0.0)
    stunned = [(100.0, 0.0, 50.0), (600.0, 0.0, 100.0), (650.0, 0.0, -100.0)]
    kinds = []
    for t in (10.0, 10.1, 10.2, 10.3, 11.5):
        kinds.append(w.plan(t, me, stunned, mine_ready=True, throw_ready=True, blast_cm=400.0).kind)
    assert kinds[:3] == ["mine", "throw", "move"] and kinds[-1] == "fire"
    assert stats["flash_window_mines"] == 1 and stats["flash_window_throws"] == 1 and stats["flash_window_moves"] == 1
    w.observe(11.0, 8)
    assert stats["flash_window_kills"] == 3
    assert w.plan(20.0, me, stunned, True, True) is None, "the window closed"


def test_the_step_goes_only_where_the_floor_allows_and_never_stands():
    w = W.Window({}, 3.5, 0.9)
    w.open(0.0)
    step = w.plan(0.1, (0.0, 0.0, 0.0), [(100.0, 0.0, 0.0)], False, False, clear=lambda a, b: False)
    assert step.kind == "fire", "walled in: he fires instead of walking into the wall"
    s = W.spot((0.0, 0.0, 0.0), [(100.0, 0.0, 0.0)])
    assert math.hypot(s[0] - 100.0, s[2]) == pytest.approx(W.FIRE_SPOT_CM)


# --- RE5: the flash on the crowd -------------------------------------------------------------------------------------
def crowd_snap():
    return {"mercenaries_phase": R.PHASE_PLAYING,
            "player": {"hp": 1000, "hp_max": 1000, "pos": (0.0, 0.0, 0.0), "motion": 0, "rot": 0.0},
            "enemies": [{"ptr": 10 + i, "hp": 800, "pos": (40.0 * i, 0.0, 150.0)} for i in range(3)]}


def flash_bot(monkeypatch):
    calls = []
    monkeypatch.setattr(interventions, "native_controller", lambda ad: SimpleNamespace(
        flash=lambda: calls.append(("feet",)) or {"state": "confirmed"},
        flash_at=lambda x, y, z: calls.append(("at", x, y, z)) or {"state": "confirmed",
                                                                    "from_player_cm": math.hypot(x, z)}))
    monkeypatch.setattr(R.threading, "Thread", lambda **kw: SimpleNamespace(start=kw["target"]))
    b = R.Bot(stats={}, clock=lambda: 0.0)
    b._m = SimpleNamespace(adapter=object())
    return b, calls


def test_every_bot_flash_goes_off_on_the_crowd_never_at_his_feet(monkeypatch):
    b, calls = flash_bot(monkeypatch)
    assert b._native_flash(crowd_snap(), 1.0, "test", "threat_flashes")
    assert calls and calls[0][0] == "at"
    _k, x, y, z = calls[0]
    assert math.hypot(x, z) >= R.FLASH_PLACE_MIN_CM - 1e-6 and y == 0.0
    assert b.stats["flash_placed"] == 1 and b.stats["threat_flashes"] == 1


def test_one_flash_a_minute_whoever_fired_the_last(monkeypatch):
    b, calls = flash_bot(monkeypatch)
    b.stats["native_flash_confirmed_at"] = time.time()           # the ring's or the operator's, just now
    assert not b._native_flash(crowd_snap(), 1.0, "test", "threat_flashes") and not calls
    assert b._native_flash(crowd_snap(), 1.0 + R.FLASH_MIN_GAP_S + 0.1, "test", "threat_flashes")


def test_nobody_near_means_no_flash_rather_than_one_at_his_feet(monkeypatch):
    b, calls = flash_bot(monkeypatch)
    s = crowd_snap()
    s["enemies"] = [{"ptr": 1, "hp": 800, "pos": (5000.0, 0.0, 0.0)}]
    assert not b._native_flash(s, 1.0, "test", "threat_flashes") and not calls
    assert b.stats["flash_place_none"] == 1


def test_a_controller_that_cannot_place_never_flashes_at_his_feet(monkeypatch):
    b, calls = flash_bot(monkeypatch)
    monkeypatch.setattr(interventions, "native_controller", lambda ad: SimpleNamespace(
        flash=lambda: calls.append(("feet",)) or {"state": "confirmed"}))
    b._native_flash(crowd_snap(), 1.0, "test", "threat_flashes")
    assert not calls and b.stats["bot_grenade_state"] == "failed"


def test_his_own_motion_after_a_flash_is_measured_by_where_it_went_off(monkeypatch):
    b, _calls = flash_bot(monkeypatch)
    b._native_flash(crowd_snap(), 1.0, "test", "threat_flashes")
    s = crowd_snap()
    t = 1.0
    for motion in (0, 61, 61, 61, 61, 0, 0, 0):                    # 61: a reaction motion (not a free one)
        s["player"]["motion"] = motion
        b._flash_self_tick(s, t)
        t += 0.1
    b._flash_self_tick(s, t + R.FLASH_STUN_S)
    assert b.stats["flash_self_n_crowd"] == 1 and b.stats["flash_self_stun_s_crowd"] >= 0.3
    assert b.stats["flash_self_stunned_crowd"] == 1 and "61x" in b.stats["flash_self_motions"]


def test_the_window_after_a_flash_urges_a_mine_then_fights(monkeypatch):
    b, _calls = flash_bot(monkeypatch)
    b.mines = MN.Mines(b.stats)
    urged = []
    b.mines.urge = lambda now, secs=None: urged.append(now)
    b.mines.stack = lambda inv: {"item": 0x09}
    b.stats["native_flash_confirmed_at"] = time.time()
    s = crowd_snap()
    act = b._flash_window(s, {"hold": ("zl", "zr")}, 5.0)
    assert urged == [5.0] and act == {"hold": ("zl", "zr")} and b.stats["flash_window_mines"] == 1
    assert b.mines.flash_until >= 5.0 + R.FLASH_WINDOW_S - 1e-6, "the reeling ones block no plant"
    act = b._flash_window(s, {"hold": ("zl", "zr")}, 5.1)
    assert b.stats["flash_window_windows"] == 1 and (act.get("hold") or ())


# --- the flash ring under the same minute ----------------------------------------------------------------------------
def test_a_flash_ring_waits_out_the_minute_and_starts_outside_his_reach():
    pol = G.policy(R)
    assert pol["inner_cm"] >= R.FLASH_PLACE_MIN_CM and pol["flash_gap_s"] == R.FLASH_MIN_GAP_S
    s = {"player": {"pos": (0.0, 0.0, 0.0)}, "enemies": [{"hp": 800, "pos": (50.0 * i, 0.0, 50.0)} for i in range(6)]}
    stats = {"native_flash_confirmed_at": time.time() - 5.0}
    d = G.decide(s, stats, 100.0, pol)
    assert not d["fire"] and "FLASH_MIN_GAP_S" in d["reason"]
    stats["native_flash_confirmed_at"] = time.time() - R.FLASH_MIN_GAP_S - 1.0
    assert G.decide(s, stats, 100.0, pol)["fire"]
