"""Master-build layer: codes are real 3-byte items, templates/mag distribution are
valid, and the entry point is fail-soft (never raises) and idempotent on live RAM."""
import struct

import pytest

from gbox import pso_master_build as MB
from gbox import pso_gc_live as G
from test_pso_gc_live import RAM


def test_boss_floors_use_ranged_weapons():
    assert all(MB._is_hex3(c) for c in MB.RANGED_WEAPON_CODES)
    assert all(c.startswith("00") for c in MB.RANGED_WEAPON_CODES)
    # Boss floors force a gun per floor: Shot (000900) by default, Rifle (000700) on the Dragon floor.
    assert MB.BOSS_WEAPON_CODE == "000900" and MB._is_hex3(MB.BOSS_WEAPON_CODE)
    assert MB.BOSS_WEAPON_CODE in MB.RANGED_WEAPON_CODES
    assert MB.BOSS_WEAPON_BY_FLOOR.get(11) == "000700"       # Dragon: Rifle covers the full orbit from center
    assert all(c in MB.RANGED_WEAPON_CODES for c in MB.BOSS_WEAPON_BY_FLOOR.values())

    class WpM:
        def __init__(self, floor): self.floor = floor
        def u32(self, a):
            from gbox.pso_fence import FLOOR
            return self.floor if a == FLOOR else 0
    assert MB._boss_weapon_code(WpM(11)) == "000700"         # Dragon floor -> Rifle
    assert MB._boss_weapon_code(WpM(12)) == "000900"         # De Rol Le -> Shot
    assert MB._boss_weapon_code(WpM(13)) == "000900"         # Vol Opt -> Shot

    class M:
        def __init__(self, floor, ep): self.floor, self.ep = floor, ep
        def u32(self, a):
            from gbox.pso_fence import FLOOR, EPISODE_FLOOR
            return {FLOOR: self.floor, EPISODE_FLOOR: self.ep}.get(a, 0)
    assert MB._boss_floor(M(12, 0)) is True       # Ep1 De Rol Le
    assert MB._boss_floor(M(3, 0)) is False       # Ep1 Cave1 (normal)
    assert MB._boss_floor(M(15, 1)) is True       # Ep2 Gol Dragon
    assert MB._boss_floor(M(11, 1)) is False      # 11 is not an Ep2 boss floor


def test_item_codes_are_well_formed_three_byte_codes():
    assert all(MB._is_hex3(c) for c in MB.WEAPON_CODES)
    assert all(MB._is_hex3(c) for c in MB.UNIT_CODES)
    assert MB._is_hex3(MB.FRAME_CODE) and MB._is_hex3(MB.MAG_CODE)
    # Full randomized build: armor / shield / mag code pools are well-formed with the right class.
    assert all(MB._is_hex3(c) and c.startswith("0101") for c in MB.FRAME_CODES)    # armor
    assert all(MB._is_hex3(c) and c.startswith("0102") for c in MB.BARRIER_CODES)  # shields
    assert all(MB._is_hex3(c) and c.startswith("02") for c in MB.MAG_CODES)        # mags
    assert MB.FRAME_CODES and MB.BARRIER_CODES and MB.MAG_CODES
    # family prefixes match gbox.psoitems: weapon 00, frame 0101, unit 0103, mag 02
    assert all(c.startswith("00") for c in MB.WEAPON_CODES)
    assert MB.FRAME_CODE.startswith("0101")
    assert all(c.startswith("0103") for c in MB.UNIT_CODES)
    assert MB.MAG_CODE.startswith("02")
    assert len(MB.WEAPON_CODES) >= 4 and len(MB.UNIT_CODES) >= MB.UNIT_SLOTS


def test_frame_template_carries_code_slots_and_id():
    item = MB.frame_template("010100", 4, 0x00F00042)
    assert len(item) == 20
    assert item[:3] == bytes.fromhex("010100")
    assert item[4] == 4                                   # four unit slots (data1[4])
    assert struct.unpack_from(">I", item, 12)[0] == 0x00F00042
    # a lower slot request is honoured and bounded to a byte
    assert MB.frame_template("010100", 1, 0)[4] == 1


def test_mag_distribution_is_maxed_random_and_within_caps():
    import random
    for seed in range(20):
        ch = MB.mag_max_changes(random.Random(seed))
        assert ch["def"] + ch["pow"] + ch["dex"] + ch["mind"] == MB.MAG_TOTAL
        assert all(0 <= ch[k] <= 200 for k in ("def", "pow", "dex", "mind"))
        assert ch["iq"] == 200 and ch["synchro"] == MB.MAG_SYNCHRO
        assert 0 <= ch["color"] < MB.MAG_COLORS
    # the distribution actually varies between seeds (it is random, not fixed)
    a = MB.mag_max_changes(random.Random(1))
    b = MB.mag_max_changes(random.Random(2))
    assert (a["def"], a["pow"], a["dex"], a["mind"]) != (b["def"], b["pow"], b["dex"], b["mind"])


def test_apply_is_fail_soft_on_a_blank_or_wrong_game_and_never_writes():
    class Blank:
        def __init__(self):
            self.writes = []

        def read_memory(self, address, length):
            return b"\0" * length

        def write_memory(self, address, data):
            self.writes.append((address, data))
    ad = Blank()
    report = MB.apply_master_build(ad)                    # wrong disc -> every feature fails soft
    assert isinstance(report, dict)
    assert report["ok"] is False
    assert report["errors"]                               # at least the player/accuracy guards tripped
    assert ad.writes == []                                # nothing poked into a non-PSO game


def test_apply_does_not_raise_when_globals_apply_but_player_build_cannot(monkeypatch):
    # A correctly fingerprinted, hooked game with accuracy guards present, but the
    # native command queue is faked out, so the real item/stat work no-ops safely.
    from gbox import pso_accuracy as A, pso_gc_extras as E, pso_gc_adventure as D
    ram = RAM()
    for a, b in A.GUARDS.items():
        ram.put(a, b)
    for a, _, _, original in A.SITES:
        ram.put(a, original)
    for a, b in E.EXTRA_GUARDS.items():
        ram.put(a, b)
    ram.query_runtime = lambda: {"state": "RUNNING"}
    # the local player must look initialised for check()
    ram.word(ram.player + 0x1C, 0)
    monkeypatch.setattr(G.GC, "call", lambda self, calls, timeout=2: [0] * len(calls))
    report = MB.apply_master_build(ram)
    assert isinstance(report, dict) and "errors" in report
    # never-miss and equip-anything are player-independent and should have applied
    assert report.get("never_miss") is True
    assert report.get("equip_any") is True


def test_state_is_tracked_per_player_and_apply_all_covers_both():
    # On a wrong-disc adapter every player fails soft before any state is created.
    class Blank:
        def read_memory(self, address, length):
            return b"\0" * length

        def write_memory(self, address, data):
            pass
    ad = Blank()
    out = MB.apply_master_build_all(ad)
    assert set(out) == {0, 1}
    assert out[0]["player_index"] == 0 and out[1]["player_index"] == 1
    assert out[0]["ok"] is False and out[1]["ok"] is False
    assert getattr(ad, "_master_build_state", {}) == {}      # no state for a non-PSO game

    # The per-player state helper keys independently once a player is valid.
    class Live:
        def read_memory(self, address, length):
            return b"\0" * length
    live = Live()
    MB._state(live, 0)["weapon_id"] = 0xF00001
    MB._state(live, 1)["weapon_id"] = 0xF00002
    assert MB._state(live, 0)["weapon_id"] != MB._state(live, 1)["weapon_id"]


def test_notes_document_shipped_and_outstanding_work():
    for key in ("never_miss", "crit_always", "crit_rate", "attack_speed_todo"):
        assert key in MB.MASTER_BUILD_NOTES and MB.MASTER_BUILD_NOTES[key]
    # never-miss and crit-always now cover both players; 3x-speed is the only to-do.
    assert "slot 1" in MB.MASTER_BUILD_NOTES["never_miss"]
    assert "0x8001468C" in MB.MASTER_BUILD_NOTES["crit_always"]
