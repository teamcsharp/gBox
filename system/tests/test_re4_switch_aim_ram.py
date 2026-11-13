"""RE4 Switch's steady aim from RAM (re4_switch AIM_RAM / re4_switch_mods._steady) and the aim book's hookup, on
synthetic memory and synthetic snapshots. The offsets are static (main.bin against the GameCube decompilation); nothing
here is a claim about a live round."""
import math
import struct
import time

import pytest

from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_switch_mods as M
from gbox.mercs.core import aim_book as A

BASE = 0x3CA7C04000
PLAYER, WEP, OBJ, GANADO = 0x5D50100000, 0x5D50200000, 0x5D50300000, 0x5D50400000
SWAY = (0.1, 0.05, 0.005, 0.005)                    # setAbility(5.73, 2.86, 0.2864, 0.2864) in radians


class Mem:
    def __init__(self):
        self.at = {}
        self.writes = []

    def put(self, addr, data):
        self.at[addr] = bytearray(data)

    def rd(self, addr, n):
        for a, d in self.at.items():
            if a <= addr and addr + n <= a + len(d):
                return bytes(d[addr - a:addr - a + n])
        raise ValueError("unmapped")

    read_memory = rd

    def write_memory(self, addr, data):
        for a, d in self.at.items():
            if a <= addr and addr + len(data) <= a + len(d):
                d[addr - a:addr - a + len(data)] = data
                self.writes.append((addr, bytes(data)))
                return
        raise ValueError("unmapped")


def world(sight=0, sway=SWAY, waist=0.08, center=0.08, pitch=0.2, lpos=(0.0, 1450.0, 500.0),
          lcross=(0.0, 1450.0, 6000.0), stat=1):
    m = Mem()
    unit = bytearray(D.UNIT_SIZE)
    struct.pack_into("<Q", unit, D.PL_WEP, WEP)
    struct.pack_into("<f", unit, D.PL_WAIST_YAW, waist)
    m.put(PLAYER, unit)
    wep = bytearray(0x60)
    struct.pack_into("<2f", wep, D.WEP_PITCH, pitch, center)
    struct.pack_into("<Q", wep, D.WEP_OBJ, OBJ)
    m.put(WEP, wep)
    obj = bytearray(0x500)
    struct.pack_into("<4f", obj, D.OBJ_SWAY, *sway)
    struct.pack_into("<H", obj, D.OBJ_ITEM, 0x35)
    obj[D.OBJ_STAT] = stat
    struct.pack_into("<Q", obj, D.OBJ_SIGHT_EM, sight)
    m.put(OBJ, obj)
    laser = bytearray(0x1C)
    struct.pack_into("<3f", laser, 4, *lpos)
    struct.pack_into("<3f", laser, 0x10, *lcross)
    m.put(BASE + D.LASER_STATIC, laser)
    m.put(BASE + D.M3R, struct.pack("<3f", pitch / (math.pi / 2), pitch / (math.pi / 2), 0.0))
    return m


def test_the_aim_reads_the_weapon_control_the_sway_the_waist_and_the_laser():
    aim = D.aim_state(world(sight=GANADO), BASE, PLAYER)
    assert aim["wep"] == WEP and aim["obj"] == OBJ and aim["sight"] == GANADO
    assert aim["sway"] == pytest.approx(SWAY) and aim["waist"] == pytest.approx(0.08)
    assert aim["pitch"] == pytest.approx(0.2) and aim["stat"] == 1 and aim["item"] == 0x35
    assert aim["lpos"] == pytest.approx((0.0, 1450.0, 500.0)) and "m3r" in aim


@pytest.mark.parametrize("bad", [{"sway": (0.9, 0.0, 0.0, 0.0)}, {"waist": 2.0}, {"pitch": 3.0},
                                 {"sway": (float("nan"), 0, 0, 0)}, {"sight": 0x10}])
def test_a_value_out_of_its_range_is_not_the_field(bad):
    assert D.aim_state(world(**bad), BASE, PLAYER) is None


def test_the_laser_is_a_line_only_from_beside_him_at_a_guns_height():
    p = {"pos": (0.0, 0.0, 0.0)}
    aim = D.aim_state(world(), BASE, PLAYER)
    line = D.laser_of(aim, p)
    assert line["up"] and line["from"] == pytest.approx((0.0, 1450.0, 500.0))
    assert D.laser_of(aim, {"pos": (9000.0, 0.0, 0.0)}) is None, "a stale line from where he stood"
    assert D.laser_of(D.aim_state(world(stat=0), BASE, PLAYER), p)["up"] is False


def snap_of(m, aim=True):
    s = {"module_base": BASE, "enemies": [], "player": {"ptr": PLAYER, "pos": (0.0, 0.0, 0.0), "rot": 0.0}}
    if aim:
        s["aim"] = D.aim_state(m, BASE, PLAYER)
    return s


def test_the_steady_aim_zeroes_the_sway_and_the_waist_and_puts_the_pitch_on_the_centre():
    m = world()
    M.run(m, "aim_lock", on=True)
    D.AIM_REQUEST.update(ptr=PLAYER, yaw=0.5, pitch=-0.12, steady=True, wep=WEP, at=time.monotonic())
    out = M.maintain(m, snap_of(m))
    assert out.get("aim_writes") == 1 and out.get("aim_sway_zeroed") == 1 and out.get("aim_ram_writes") >= 3
    assert struct.unpack("<4f", m.rd(OBJ + D.OBJ_SWAY, 16)) == (0.0, 0.0, 0.0, 0.0)
    assert struct.unpack("<f", m.rd(PLAYER + D.PL_WAIST_YAW, 4))[0] == 0.0
    assert struct.unpack("<f", m.rd(WEP + D.WEP_CENTER_Y, 4))[0] == 0.0
    assert struct.unpack("<f", m.rd(WEP + D.WEP_PITCH, 4))[0] == pytest.approx(-0.12)
    # the facing turns toward the request in a smoothed step (operator 2026-11-11: no per-tick jerk), not 0.5 at once
    assert struct.unpack("<f", m.rd(PLAYER + D.U_YAW, 4))[0] == pytest.approx(M.AIM_WRITE_MAX_STEP, abs=1e-6)
    n = len(m.writes)
    M.maintain(m, snap_of(m))                         # another step of the facing (the gun's parts are already set)
    assert len(m.writes) - n == 1


def test_a_changed_chain_or_a_gun_down_request_writes_nothing_of_the_gun():
    m = world()
    M.run(m, "aim_lock", on=True)
    s = snap_of(m)
    struct.pack_into("<Q", m.at[WEP], D.WEP_OBJ, OBJ + 0x1000)    # a new weapon object since the snapshot
    D.AIM_REQUEST.update(ptr=PLAYER, yaw=0.5, pitch=0.3, steady=True, wep=WEP, at=time.monotonic())
    M.maintain(m, s)
    assert struct.unpack("<4f", m.rd(OBJ + D.OBJ_SWAY, 16)) == pytest.approx(SWAY)
    assert M.status(m)["aim_ram_refused"] >= 1
    m2 = world()
    M.run(m2, "aim_lock", on=True)
    D.AIM_REQUEST.update(ptr=PLAYER, yaw=0.5, steady=False, pitch=None, at=time.monotonic())
    M.maintain(m2, snap_of(m2))
    assert struct.unpack("<4f", m2.rd(OBJ + D.OBJ_SWAY, 16)) == pytest.approx(SWAY), "the gun down: no steady writes"


# --- the bot's steady aim ------------------------------------------------------------------------------------------------
def fight_snap(sight=None, lcross=None, ganado_z=5000.0, rot=0.0, pitch=0.0):
    e = {"ptr": GANADO, "pos": (0.0, 0.0, ganado_z), "hp": 400, "hp_max": 400, "class": 0xAE7050}
    lp = (0.0, 1450.0, 500.0)
    lc = lcross or (0.0, 1100.0, ganado_z)
    aim = {"wep": WEP, "obj": OBJ, "pitch": pitch, "center": 0.0, "waist": 0.0, "sway": (0.0,) * 4, "item": 0x35,
           "stat": 1, "sight": sight, "lpos": lp, "lcross": lc, "donfire": 0}
    return {"player": {"pos": (0.0, 0.0, 0.0), "rot": rot, "hp": 1000, "ptr": PLAYER}, "enemies": [e], "aim": aim,
            "laser": {"from": lp, "at": lc, "up": True, "source": "ram"}, "weapon_class": 0x05}


class RamBot:
    """A Bot whose aim lock writes every request (re4_switch_mods' count rises each snapshot, as live)."""

    def __init__(self):
        self.b = D.Bot(stats={"mods_aim_writes": 0}, director=False)

    def tick(self, s, now):
        self.b.stats["mods_aim_writes"] += 1
        return self.b.tick(s, now=now)

    def __getattr__(self, k):
        return getattr(self.b, k)


def ram_bot():
    return RamBot()


def test_a_laser_that_never_comes_up_does_not_hold_the_trigger_for_ever():
    """Live 2026-11-12, Waterworld r404: laser_gate stat=0 up=False for the whole round, so the steady aim's `fresh` was
    never true and it held AIM_BTN from the first tick to the last - kills 0, aimbook_shots 0, aim_ram_holds 119, why
    "the steady aim: the gun comes up onto the book's point". The sight-stall branch always had a timeout; this one had
    none, so a laser that never read meant a bot that never fired."""
    b = ram_bot()
    s = fight_snap(sight=GANADO)
    s["laser"]["up"] = False
    act = b.tick(s, now=10.0)
    assert act == {"hold": {D.AIM_BTN}} and "comes up onto the book" in b.why, "it does try the rise first"
    assert not b.stats.get("aim_rise_fallbacks"), "not yet: the raise is still running"
    act = b.tick(s, now=10.0 + D.AIM_READY_S + 0.01)
    assert act.get('tap') == D.FIRE_BTN, 'ready gun fires while the absent laser is reacquired'


def test_the_steady_aim_corrects_while_firing_before_sight_contact():
    b = ram_bot()
    b.tick(fight_snap(), now=10.0)                      # the gun up
    assert D.AIM_REQUEST.get("steady") is True and D.AIM_REQUEST.get("wep") == WEP
    act = b.tick(fight_snap(sight=None), now=10.5)
    assert act.get('tap') == D.FIRE_BTN and b.doing == 'fire' and b.stats['spray_shots'] == 1
    assert not set(act.get("hold") or ()) & set(D.AIM_TURN.values()), "no right-stick taps: the RAM holds the aim"
    act = b.tick(fight_snap(sight=GANADO), now=10.6)
    assert act.get("tap") == D.FIRE_BTN and b.stats["aim_ram_shots"] == 1
    assert b.stats["aimbook_shots"] == 2


def test_the_pitch_closes_on_the_books_point_through_the_line():
    b = ram_bot()
    b.tick(fight_snap(), now=10.0)
    high = (0.0, 1800.0, 5000.0)                         # the line 70 cm over his chest
    b.tick(fight_snap(lcross=high, pitch=0.1), now=10.5)
    lp = (0.0, 1450.0, 500.0)
    want = A.angles(lp, (0.0, D.combat.HUMAN.chest * 10.0, 5000.0))[1]
    have = A.angles(lp, high)[1]
    assert D.AIM_REQUEST["pitch"] == pytest.approx(0.1 + D.AIM_PITCH_GAIN * (want - have), abs=0.02)
    assert D.AIM_REQUEST["pitch"] < 0.1, "the line high: the pitch comes down"


def test_a_sight_that_never_reads_does_not_delay_a_twenty_request_burst():
    b = ram_bot()
    b.tick(fight_snap(), now=10.0)
    t, taps = 10.3, []
    while t < 10.3 + D.AIM_SIGHT_STALL_S + 0.5:
        taps.append(b.tick(fight_snap(sight=None), now=t).get("tap"))
        t += 0.05
    assert taps.count(D.FIRE_BTN) >= 20
    assert taps[0] == D.FIRE_BTN, 'aim correction must not wait for a sight stall'


def test_the_sight_on_another_ganado_shoots_him():
    b = ram_bot()
    s = fight_snap()
    other = {"ptr": GANADO + 0x2000, "pos": (300.0, 0.0, 7000.0), "hp": 400, "hp_max": 400, "class": 0xAE7050}
    s["enemies"].append(other)
    b.tick(s, now=10.0)
    s2 = fight_snap(sight=other["ptr"])
    s2["enemies"].append(other)
    act = b.tick(s2, now=10.6)
    assert act.get("tap") == D.FIRE_BTN and b.target == other["ptr"] and b.stats["aim_ram_sight_switches"] == 1


def test_without_the_lock_writing_the_old_aim_runs():
    b = D.Bot(stats={}, director=False)
    b.tick(fight_snap(), now=10.0)
    act = b.tick(fight_snap(sight=None), now=10.0 + D.AIM_READY_S)
    assert act.get("tap") == D.FIRE_BTN and "aim_ram_shots" not in b.stats


def test_a_census_hp_drop_cannot_train_aim_without_native_discharge_proof():
    b = ram_bot()
    b.tick(fight_snap(), now=10.0)
    b.tick(fight_snap(sight=GANADO), now=10.6)
    s = fight_snap(sight=GANADO)
    s["enemies"][0]["hp"] = 100                         # his health fell: the shot's hit
    b.tick(s, now=10.7)
    b.tick(s, now=10.7 + A.HIT_S + 0.1)
    assert b.stats['aimbook_hits'] == 0 and b.stats['aimbook_unconfirmed'] >= 1
    core = b._aim_core()
    assert not core.book.cells


def test_a_close_sight_stall_keeps_correcting_and_firing():
    """Operator 2026-11-11: "the bot just sits there instead of firing on the enemies ... watching him just watch them
    come up." A Ganado already inside 3 m must get the old body-angle gate after AIM_SIGHT_STALL_CLOSE_S, not 1.5 s."""
    b = ram_bot()
    b.tick(fight_snap(ganado_z=2500.0), now=10.0)
    t, taps = 10.3, []
    while t < 10.3 + D.AIM_SIGHT_STALL_CLOSE_S + 0.9:
        taps.append(b.tick(fight_snap(sight=None, ganado_z=2500.0), now=t).get("tap"))
        t += 0.05
    assert b.stats['spray_shots'] >= 1 and D.FIRE_BTN in taps
