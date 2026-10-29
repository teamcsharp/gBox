"""RE5 Switch RAM aim lock (re5_switch_aim; AIM_LOCK off by default until a live round shows the writes hold): the
player's uCameraQFPS found and read, the writer's read-back, and the bot moving the aim by RAM at a capped rate."""
import math
import struct

import pytest

from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_aim as A

BASE, SU, CTRL, PLAYER = 0x3CA7C04000, 0x5D10000000, 0x5D20000000, 0x5D30000000


class Guest:
    def __init__(self, sticky=True):
        self.mem, self.sticky, self.writes = {}, sticky, []

    def put(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def q(self, a, v):
        self.put(a, struct.pack("<Q", v))

    def rd(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    read_memory = rd

    def write_memory(self, a, data):
        self.writes.append((a, bytes(data)))
        if self.sticky:
            self.put(a, data)


def guest(pitch=0.3, heading=0.5, active=True, sticky=True):
    g = Guest(sticky)
    g.q(BASE + A.S_UNIT, SU)
    g.q(SU + A.UNIT_LINES + A.LINE_STRIDE * A.CAM_LINE, CTRL)
    g.q(CTRL, BASE + A.CTRL_VT)
    g.q(CTRL + A.CTRL_PLAYER, PLAYER)
    g.q(CTRL + A.CTRL_QFPS, BASE + A.QFPS_VT)
    g.q(CTRL + A.CTRL_ACTIVE, CTRL + A.CTRL_QFPS if active else 0x5D99999999)
    g.put(CTRL + A.CTRL_QFPS + A.QF_PITCH, struct.pack("<f", pitch))
    g.put(PLAYER + A.P_ROT, struct.pack("<4f", 0.0, math.sin(heading / 2), 0.0, math.cos(heading / 2)))
    return g


class Session:
    def __init__(self, g):
        self.adapter, self.rd = g, g.rd


def test_the_players_camera_is_found_and_read():
    st = A.aim_state(guest(), BASE, PLAYER)
    assert st["qfps"] == CTRL + A.CTRL_QFPS and abs(st["pitch"] - 0.3) < 1e-6 and abs(st["heading"] - 0.5) < 1e-6


def test_another_players_or_an_inactive_camera_is_none():
    assert A.aim_state(guest(active=False), BASE, PLAYER) is None
    assert A.aim_state(guest(), BASE, 0x5D40000000) is None


def test_the_writer_reads_back_and_clamps_the_pitch():
    g = guest()
    st = A.aim_state(g, BASE, PLAYER)
    w = A.aim_writer(Session(g))
    assert w(st, 1.4, 0.7)
    st2 = A.aim_state(g, BASE, PLAYER)
    assert abs(st2["pitch"] - 1.0) < 1e-6 and abs(st2["heading"] - 0.7) < 1e-5


def test_a_write_that_does_not_hold_is_a_failure():
    g = guest(sticky=False)
    assert not A.aim_writer(Session(g))(A.aim_state(g, BASE, PLAYER), 0.1, None)


def test_no_writer_without_an_adapter_or_with_modifications_off():
    assert A.aim_writer(object()) is None
    s = Session(guest())
    s.mercs_no_modifications = True
    assert A.aim_writer(s) is None


# --- the bot -----------------------------------------------------------------------------------------------------------
MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def snap(enemies, dot=None, motion=26, cam=None):
    return {"player": {"ptr": PLAYER, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": motion, "aim_pitch": None},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": [], "kills": 0, "aim_cam": cam,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot(writes, ok=True):
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])

    def w(st, pitch, heading):
        writes.append((pitch, heading))
        return ok
    b._ram = w
    return b, clock


CAM = {"qfps": CTRL + A.CTRL_QFPS, "player": PLAYER, "pitch": 0.0, "heading": 0.0}


def test_on_live_and_off_means_no_writes(monkeypatch):
    assert R.AIM_LOCK is False                     # off 2026-10-28: its heading writes snapped the view (operator)
    monkeypatch.setattr(R, "AIM_LOCK", False)
    writes = []
    b, clock = bot(writes)
    foe = at(800, 0)
    b.tick(snap([foe], cam=CAM))
    clock[0] = 0.3
    b.tick(snap([foe], dot=(-400.0, 140.0, 2000.0), cam=CAM))
    assert writes == [] and b.stats["aim_lock_ticks"] == 0


def test_on_the_aim_moves_by_ram_at_its_capped_rate_and_the_stick_rests(monkeypatch):
    monkeypatch.setattr(R, "AIM_LOCK", True)
    writes = []
    b, clock = bot(writes)
    foe = at(800, 0)
    b.tick(snap([foe], cam=CAM))
    clock[0] = 0.3
    act = b.tick(snap([foe], dot=(-500.0, 140.0, 2000.0), cam=CAM))   # the dot 14 deg right of him
    assert not {"rleft", "rright", "rup", "rdown"} & set(act["hold"]) and b.stats["aim_lock_ticks"] >= 1
    pitch, head = writes[-1]
    assert 0 < head <= math.radians(R.AIM_LOCK_YAW_DEG_S) * R.LOOK_STEP_MAX_S + 1e-6   # toward him, capped


def test_a_failed_read_back_leaves_the_stick(monkeypatch):
    monkeypatch.setattr(R, "AIM_LOCK", True)
    writes = []
    b, clock = bot(writes, ok=False)
    foe = at(800, 0)
    b.tick(snap([foe], cam=CAM))
    clock[0] = 0.3
    act = b.tick(snap([foe], dot=(-500.0, 140.0, 2000.0), cam=CAM))
    assert "rleft" in act["hold"] and b.stats["aim_lock_fails"] >= 1


def test_while_the_gun_comes_up_the_camera_pitch_goes_to_the_target_first(monkeypatch):
    monkeypatch.setattr(R, "AIM_LOCK", True)
    writes = []
    b, clock = bot(writes)
    foe = at(300, 0)
    up = dict(CAM, pitch=0.99)                                     # an old +57 deg
    b.tick(snap([foe], motion=22, cam=up))
    clock[0] = 0.2
    b.tick(snap([foe], motion=22, cam=up))
    assert b.stats["aim_lock_prepitch"] >= 1 and writes and writes[-1][0] < 0.99 and writes[-1][1] is None


def test_writes_the_game_overwrites_stand_the_lock_down_for_the_round(monkeypatch):
    monkeypatch.setattr(R, "AIM_LOCK", True)
    writes = []
    b, clock = bot(writes)
    foe = at(800, 0)
    b.tick(snap([foe], cam=CAM))
    for k in range(1, 12):                                         # the state never follows the writes
        clock[0] = 0.2 + 0.05 * k
        act = b.tick(snap([foe], dot=(-500.0, 140.0, 2000.0), cam=CAM))
    assert b.stats["aim_lock_unheld"] == 1 and b._lock_off
    n = len(writes)
    clock[0] = 1.0
    b.tick(snap([foe], dot=(-450.0, 140.0, 2000.0), cam=CAM))
    assert len(writes) == n                                        # no more writes this round: the stick aims


# --- close-range pitch-only: the heading write snaps the view, the pitch write does not -------------------------------


def test_close_range_pitch_only_writes_never_touch_the_heading(monkeypatch):
    """dist < AIM_LOCK_PITCH_ONLY_CM and abs(yaw_err) < AIM_LOCK_PITCH_ONLY_YAW: pitch-only, heading is None."""
    monkeypatch.setattr(R, "AIM_LOCK", True)
    writes = []
    b, clock = bot(writes)
    foe = at(300, 0)                                               # 3.0 m: inside the pitch-only band
    b.tick(snap([foe], cam=CAM))
    clock[0] = 0.3
    # the dot nearly on the target's bearing: yaw_err ~ 0 (< AIM_LOCK_PITCH_ONLY_YAW)
    act = b.tick(snap([foe], dot=(0.0, 140.0, 2000.0), cam=CAM))
    assert b.stats["aim_lock_ticks"] >= 1
    pitch, head = writes[-1]
    assert pitch is not None and head is None                      # pitch-only: the player quaternion is untouched


def test_close_range_pitch_only_drops_the_stick(monkeypatch):
    """The pitch-only write still drops the right-stick keys (the RAM write replaced the stick)."""
    monkeypatch.setattr(R, "AIM_LOCK", True)
    writes = []
    b, clock = bot(writes)
    foe = at(300, 0)
    b.tick(snap([foe], cam=CAM))
    clock[0] = 0.3
    act = b.tick(snap([foe], dot=(0.0, 140.0, 2000.0), cam=CAM))
    assert not {"rleft", "rright", "rup", "rdown"} & set(act["hold"])


def test_beyond_pitch_only_range_the_heading_is_written(monkeypatch):
    """dist >= AIM_LOCK_PITCH_ONLY_CM: the full lock-on writes heading and pitch as before."""
    monkeypatch.setattr(R, "AIM_LOCK", True)
    writes = []
    b, clock = bot(writes)
    foe = at(800, 0)                                               # 8.0 m: outside the pitch-only band
    b.tick(snap([foe], cam=CAM))
    clock[0] = 0.3
    act = b.tick(snap([foe], dot=(-500.0, 140.0, 2000.0), cam=CAM))
    assert b.stats["aim_lock_ticks"] >= 1
    pitch, head = writes[-1]
    assert pitch is not None and head is not None                  # the full lock-on: heading + pitch


def test_close_range_but_large_yaw_error_still_writes_the_heading(monkeypatch):
    """Close but abs(yaw_err) >= AIM_LOCK_PITCH_ONLY_YAW: the body still needs the turn, heading is written."""
    monkeypatch.setattr(R, "AIM_LOCK", True)
    writes = []
    b, clock = bot(writes)
    foe = at(300, 0)                                               # 3.0 m: inside the pitch-only distance band
    b.tick(snap([foe], cam=CAM))
    clock[0] = 0.3
    # the dot 14 deg off the target's bearing: yaw_err > AIM_LOCK_PITCH_ONLY_YAW
    act = b.tick(snap([foe], dot=(-500.0, 140.0, 2000.0), cam=CAM))
    assert b.stats["aim_lock_ticks"] >= 1
    pitch, head = writes[-1]
    assert head is not None                                        # the heading write turns the body


# --- downed / kneeling targets: the aim tracks the real body height --------------------

def test_a_downed_majini_is_aimed_at_the_ground_not_the_air(monkeypatch):
    monkeypatch.setattr(R, "DOWNED_MOTIONS", frozenset({2, 85, 86, 87}))
    monkeypatch.setattr(R, "KNEELING_MOTIONS", frozenset({12, 30}))   # (off in play until measured)
    b, _ = bot([])
    downed = {"ptr": 99, "pos": (0.0, 0.0, 800.0), "hp": 800, "hp_max": 800, "motion": 2}
    assert b._aim_h(downed, 800.0, 0.0) == R.DOWNED_AIM_H


def test_a_kneeling_majini_is_aimed_lower_than_standing(monkeypatch):
    monkeypatch.setattr(R, "DOWNED_MOTIONS", frozenset({2, 85, 86, 87}))
    monkeypatch.setattr(R, "KNEELING_MOTIONS", frozenset({12, 30}))   # (off in play until measured)
    b, _ = bot([])
    kneeling = {"ptr": 98, "pos": (0.0, 0.0, 800.0), "hp": 800, "hp_max": 800, "motion": 30}
    assert b._aim_h(kneeling, 800.0, 0.0) == R.KNEELING_AIM_H
    standing = {"ptr": 97, "pos": (0.0, 0.0, 800.0), "hp": 800, "hp_max": 800, "motion": 4}
    assert b._aim_h(standing, 800.0, 0.0) == R.CHEST_H


def test_a_downed_majini_in_crowd_fire_gets_the_ground_aim(monkeypatch):
    monkeypatch.setattr(R, "DOWNED_MOTIONS", frozenset({2, 85, 86, 87}))
    monkeypatch.setattr(R, "KNEELING_MOTIONS", frozenset({12, 30}))   # (off in play until measured)
    """The rampage / crowd-fire path uses _aim_h, not a hardcoded CHEST_H."""
    b, clock = bot([])
    downed = (0.0, 0.0, 300.0)
    standing = (0.0, 0.0, 400.0)
    foes = [downed, standing]
    snap_d = {"player": {"ptr": PLAYER, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                         "motion": 26, "aim_pitch": None},
              "enemies": [{"ptr": 10, "pos": downed, "hp": 800, "hp_max": 800, "motion": 2},
                          {"ptr": 11, "pos": standing, "hp": 800, "hp_max": 800, "motion": 4}],
              "inventory": [], "kills": 0, "aim_cam": None,
              "laser": {"from": MUZZLE, "at": (0.0, 25.0, 300.0), "up": True}}
    b.tick(snap_d)
    clock[0] = 0.3
    act = b.tick(snap_d)
    # the aim context should carry the downed target's low aim height
    assert b._aimctx["foot"][1] + R.DOWNED_AIM_H <= 25.0 + 1e-6
