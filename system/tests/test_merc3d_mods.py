import struct

import pytest

from gbox.mercs.titles import merc3d_3ds as T, merc3d_mods as M


class Ad:
    def __init__(self):
        self.b = {}
        self.w32(T.S_MISSION, 0x09000000)
        self.f32(0x09000000 + T.M_LEFT, 100.0)
        self.w32(T.S_PLAYER, 0x09100000)
        self.w32(0x09100000 + T.SP_FIRST, 0x09200000)
        self.w32(0x09200000 + T.NODE_OWNER, 0x09300000)
        self.f32(0x09300000 + T.P_VIT, 400.0)
        self.f32(0x09300000 + T.P_VIT_MAX, 1000.0)

    def w32(self, a, v):
        self.write_memory(a, struct.pack("<I", v))

    def f32(self, a, v):
        self.write_memory(a, struct.pack("<f", v))

    def read_memory(self, a, n):
        return bytes(self.b.get(a + i, 0) for i in range(n))

    def write_memory(self, a, d):
        for i, v in enumerate(d):
            self.b[a + i] = v


def test_is_merc3d():
    assert M.is_merc3d({"game_id": "0ed22ae742e1b56b"})
    assert M.is_merc3d({"title_id": T.TITLE_ID.lower()})
    assert not M.is_merc3d({"game_id": "52d15709be0fda1a"}) and not M.is_merc3d(None)


def test_status_reads_clock_and_hp():
    s = M.run(Ad())
    assert s["in_round"] and s["timer"] == 100.0 and s["hp"] == 400.0 and s["hp_max"] == 1000.0


def test_time_ops_clamped_and_verified():
    ad = Ad()
    assert M.run(ad, "add_time", seconds=30)["timer"] == 130.0
    assert M.run(ad, "add_time", seconds=-3000)["timer"] == 1.0
    assert M.run(ad, "set_time", seconds=99999)["timer"] == 3600.0
    assert M.run(ad, "set_time", seconds=5)["verified"] is True
    assert M.status(ad)["timer"] == 5.0
    assert M.run(ad, "set_time")["verified"] is False
    assert M.run(ad, "add_time", seconds=float("nan"))["verified"] is False


def test_heal_and_no_round():
    ad = Ad()
    assert M.run(ad, "heal")["hp"] == 1000.0 and M.status(ad)["hp"] == 1000.0
    empty = Ad()
    empty.w32(T.S_MISSION, 0)
    assert M.run(empty, "set_time", seconds=5)["verified"] is False


def test_unlimited_health_refills_never_revives():
    import time
    ad = Ad()
    M.run(ad, "unlimited_health", on=True)
    time.sleep(0.4)
    assert M.status(ad)["hp"] == 1000.0
    ad.f32(0x09300000 + T.P_VIT, 0.0)
    time.sleep(0.4)
    assert M.status(ad)["hp"] == 0.0
    assert M.run(ad, "revert_all")["status"]["unlimited_health"] is False


def test_unknown_op():
    assert M.run(Ad(), "infinite_ammo")["verified"] is False


def test_routed_by_re5_mods_tool():
    import inspect
    from gbox import re5_mods_tool
    assert "merc3d_mods" in inspect.getsource(re5_mods_tool.re5_mods)
