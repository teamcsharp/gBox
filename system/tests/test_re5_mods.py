"""`re5_mods`: RE5 Gold (PS3) live mods on a fake guest memory laid out the way the live game keeps its tables
(found 2026-10-21: the executable dump + the Spark's RPCS3), and the Mercenaries playbook applying its package."""
import struct

import pytest

from gbox import mercs_bot as MB, re5_mods_tool as T
from gbox.registry import Unsupported

PARAM, SPLAYER, PLAYER = 0x3883_63D0, 0x3883_69C0, 0x303F_89E0


class FakeRE5:
    """Sparse guest memory with the weapon tables, sParameter, the fire-timer constant and an inventory; counts writes."""

    def __init__(self, build_ok=True):
        self.b: dict[int, int] = {}
        self.writes: list[tuple[int, int]] = []
        if build_ok:
            self.u32(T.DEF_TABLE, T.DEF_SIGNATURE[0])
            self.u32(T.DEF_TABLE + 4, T.DEF_SIGNATURE[1])
        self.u32(T.UPG_TABLE, T.UPG_SIGNATURE)
        for wid in range(T.N_WEAPONS):
            r = T.DEF_TABLE + wid * T.DEF_STRIDE
            self.u32(r + T.DEF_NOAMMO, 1 if wid == T.GATLING else 0)
            self.f32(r + T.DEF_INTERVAL_OFS, -10.0 if wid == 0x02 else 5.0)
            u = T.UPG_TABLE + wid * T.UPG_STRIDE
            for grp, base in ((T.G_DAMAGE, 150.0 if wid == 0x02 else 150.0 + 10 * wid), (T.G_FIRE, 26.0 if wid != 0x15 else 5.0), (T.G_RELOAD, 1.0)):
                at = u + T.UPG_GROUP0 + grp * T.UPG_GROUP
                self.u32(at, 0x0157C578)
                self.put(at + 4, struct.pack(f">{T.UPG_LEVELS}f", *[base + lvl for lvl in range(T.UPG_LEVELS)]))
        self.f32(T.FIRE_TIMER_FPS, 60.0)
        self.u32(T.S_PARAM_PTR, PARAM)
        for o, (_, v) in T.TURN.items():
            self.f32(PARAM + o, v)
        self.u32(T.S_PLAYER, SPLAYER)
        self.u32(SPLAYER + 0x28, PLAYER)
        inv = PLAYER + T.INV_OFS
        for k, (idw, rounds, cap, hand) in enumerate(((0x112, 26, 30, 1), (0x10B, 12, 12, 0), (0x209, 6, 12, 0))):
            s = inv + k * T.SLOT
            self.u32(s + 8, idw)
            self.u32(s + 0xC, rounds)
            self.u32(s + 0x10, cap)
            self.u32(s + 0x20, hand)
            self.b[s + 0x2D] = 1

    def put(self, a, data):
        for i, x in enumerate(data):
            self.b[a + i] = x

    def u32(self, a, v):
        self.put(a, struct.pack(">I", v))

    def f32(self, a, v):
        self.put(a, struct.pack(">f", v))

    def read_memory(self, a, n):
        return bytes(self.b.get(a + i, 0) for i in range(n))

    def write_memory(self, a, data):
        self.writes.append((a, len(data)))
        self.put(a, bytes(data))
        return {"written": len(data)}

    def rf(self, a):
        return struct.unpack(">f", self.read_memory(a, 4))[0]


@pytest.fixture(autouse=True)
def fresh_originals():
    T.ORIG.clear()
    yield
    T.ORIG.clear()


def test_it_refuses_another_build():
    with pytest.raises(Unsupported, match="weapon tables"):
        T.run(FakeRE5(build_ok=False), "status")


def test_status_reads_the_game_as_it_is():
    st = T.run(FakeRE5(), "status")["status"]
    assert st["fire_rate_x"] == 1.0 and st["turn_speed_x"] == 1.0 and st["bullet_damage_x"] == 1.0
    assert st["no_ammo_weapons"] == ["Gatling gun"] and st["infinite_ammo"] is False
    assert st["in_hand"] == {"slot": 0, "id": "0x112", "weapon": "Barry's handgun", "rounds": 26, "capacity": 30,
                             "in_hand": True}
    assert [x["weapon"] for x in st["inventory"]] == ["Barry's handgun", "S&W M29", None]


def test_turn_speed_scales_the_five_rates_and_restores_them():
    m = FakeRE5()
    r = T.run(m, "turn_speed", multiplier=2)
    assert r["verified"] and r["turn_speed_x"] == 2 and r["values"]["aim_yaw_deg_s"] == pytest.approx(115.8)
    assert m.rf(PARAM + 0x2C) == pytest.approx(220.0) and m.rf(PARAM + 0x68) == pytest.approx(0.4)
    assert r["status"]["turn_speed_x"] == 2.0
    assert T.run(m, "turn_speed", multiplier="max")["values"]["aim_yaw_deg_s"] == pytest.approx(579.0)
    r = T.run(m, "turn_speed", multiplier=1)
    assert all(m.rf(PARAM + o) == pytest.approx(v) for o, (_, v) in T.TURN.items()) and r["status"]["turn_speed_x"] == 1.0
    with pytest.raises(ValueError):
        T.run(m, "turn_speed", multiplier=100)


def test_fire_rate_scales_the_tables_and_the_timer_for_every_gun_but_the_knives():
    m = FakeRE5()
    r = T.run(m, "fire_rate", multiplier=80)
    assert r["verified"] and r["fire_timer_fps"] == 4800.0 and r["m92f_frames_between_shots"] == pytest.approx(26 / 80, abs=1e-4)
    at, vals = T._upg_group(bytearray(m.read_memory(T.UPG_TABLE, T.N_WEAPONS * T.UPG_STRIDE)), 0x15, T.G_FIRE)
    assert vals[0] == pytest.approx(5 / 80) and vals[13] == pytest.approx(18 / 80)
    assert m.rf(T.DEF_TABLE + 0x02 * T.DEF_STRIDE + T.DEF_INTERVAL_OFS) == 0.0              # the -10 offset gone
    assert m.rf(T.DEF_TABLE + 0x01 * T.DEF_STRIDE + T.DEF_INTERVAL_OFS) == 5.0              # the knife untouched
    assert r["status"]["fire_rate_x"] == 80.0
    assert T.run(m, "fire_rate", on=False)["status"]["fire_rate_x"] == 1.0                   # off = the game's
    assert m.rf(T.DEF_TABLE + 0x02 * T.DEF_STRIDE + T.DEF_INTERVAL_OFS) == -10.0
    _, vals = T._upg_group(bytearray(m.read_memory(T.UPG_TABLE, T.N_WEAPONS * T.UPG_STRIDE)), 0x02, T.G_FIRE)
    assert vals == [26.0 + i for i in range(14)]


def test_infinite_ammo_is_the_gatlings_flag_on_every_gun():
    m = FakeRE5()
    r = T.run(m, "infinite_ammo", on=True)
    assert r["verified"] and r["status"]["infinite_ammo"] is True
    assert "Barry's handgun" in r["status"]["no_ammo_weapons"] and "knife" not in r["status"]["no_ammo_weapons"]
    r = T.run(m, "infinite_ammo", on=False)
    assert r["status"]["no_ammo_weapons"] == ["Gatling gun"]


def test_bullet_damage_scales_the_firepower_at_every_level():
    m = FakeRE5()
    r = T.run(m, "bullet_damage", multiplier=10)
    assert r["verified"] and r["m92f_firepower_level0"] == 1500.0 and r["status"]["bullet_damage_x"] == 10.0
    assert T.run(m, "bullet_damage", multiplier=1)["status"]["bullet_damage_x"] == 1.0


def test_revert_all_puts_everything_back_and_a_foreign_timer_is_refused():
    m = FakeRE5()
    T.run(m, "fire_rate", multiplier=80)
    T.run(m, "infinite_ammo")
    T.run(m, "turn_speed", multiplier=3)
    r = T.run(m, "revert_all")
    assert r["verified"] and r["reverted"] == {"definitions": True, "upgrades": True, "fire_timer": True, "turn": True}
    st = r["status"]
    assert st["fire_rate_x"] == 1.0 and st["turn_speed_x"] == 1.0 and st["no_ammo_weapons"] == ["Gatling gun"]
    m2 = FakeRE5()
    m2.f32(T.FIRE_TIMER_FPS, 30.0)
    with pytest.raises(RuntimeError, match="not 60.0"):
        T.run(m2, "fire_rate", multiplier=2)


def test_the_playbook_applies_the_re5_package_through_re5_mods(monkeypatch):
    m = FakeRE5()
    prof = {"platform": "ps3", "map_id": "BLUS30491"}
    failed = MB.apply_ops(m, [["turn_speed", {"multiplier": 2}], ["fire_rate", {"multiplier": 80}],
                             ["infinite_ammo", {"on": True}], ["no_such_op", {}]], prof)
    assert failed == ["no_such_op: op: status | turn_speed | fire_rate | infinite_ammo | bullet_damage | revert_all | addresses"]
    st = T.run(m, "status")["status"]
    assert st["turn_speed_x"] == 2.0 and st["fire_rate_x"] == 80.0 and st["infinite_ammo"] is True


def test_the_re5_profile_package_is_the_operators_three():
    import json
    from pathlib import Path
    prof = json.loads(Path(__file__).resolve().parents[1].joinpath("profiles/gamedata/BLUS30491-ram.json").read_text())["mercs"]
    assert [op for op, _ in prof["package"]] == ["turn_speed", "fire_rate", "infinite_ammo"]
    assert dict(prof["package"])["fire_rate"] == {"multiplier": 80} and dict(prof["package"])["turn_speed"] == {"multiplier": 2}
