"""Tests for the PSO per-boss weak-point advisor (gbox.pso_boss_strategy).

Fake big-endian GameCube memory (same technique as gbox.semantic._selftest): a sparse
byte store plus the real `pso-gc-plus-us` profile, so the advisor runs its true entity
enumeration against synthetic boss arenas. No live session required.
"""
import struct

import pytest

from gbox import pso_boss_strategy as B
from gbox.pso_gc_live import PHASE, FLOOR, ENTITY_TABLE
from gbox.pso_coop_native import EPISODE, TRAVELLING, DIFFICULTY

OBJ_BASE = 0x80700000      # fake object storage (0x400 apart; struct is 0x340)
STR_BASE = 0x80600000      # fake class-name string storage


class FakeAd:
    def __init__(self, mem):
        self._mem = mem
    def read_memory(self, address, length):
        return bytes(self._mem.get(address + i, 0) for i in range(length))


def _obj(mem, index, class_name, pos, hp=None, hp_max=None, entity_id=0x1001, room=1):
    ptr = OBJ_BASE + index * 0x400
    sper = STR_BASE + index * 0x40
    for i, b in enumerate(class_name.encode() + b"\0"):
        mem[sper + i] = b
    blob = bytearray(0x340)
    struct.pack_into(">I", blob, 0x00, sper)              # class name pointer (TObject type_name)
    struct.pack_into(">H", blob, 0x1C, entity_id)
    struct.pack_into(">H", blob, 0x28, room)
    struct.pack_into(">3f", blob, 0x38, pos[0], pos[1], pos[2])
    struct.pack_into(">i", blob, 0x60, 0)
    if hp_max is not None:
        struct.pack_into(">H", blob, 0x2B8, hp_max)
    if hp is not None:
        struct.pack_into(">H", blob, 0x32C, hp)
    for i, b in enumerate(bytes(blob)):
        mem[ptr + i] = b
    return ptr


def build(episode=0, floor=11, difficulty=0, phase=14, travelling=0,
          disc=b"GPOE8P\0\x02", enemies=(), with_player=True):
    """enemies: list of (class, hp, hp_max, (x,y,z)). Returns a FakeAd."""
    mem = {}
    for i, b in enumerate(disc):
        mem[0x80000000 + i] = b
    for addr, val in ((PHASE, phase), (TRAVELLING, travelling), (EPISODE, episode),
                      (FLOOR, floor), (DIFFICULTY, difficulty)):
        for i, b in enumerate(struct.pack(">I", val)):
            mem[addr + i] = b
    ptrs = []
    idx = 0
    if with_player:
        ptrs.append(_obj(mem, idx, "TObjPlayer", (0.0, 0.0, 0.0), hp=100, hp_max=100, entity_id=0))
        idx += 1
    for (cls, hp, hp_max, pos) in enemies:
        ptrs.append(_obj(mem, idx, cls, pos, hp=hp, hp_max=hp_max))
        idx += 1
    table = b"".join(struct.pack(">I", p) for p in ptrs) + b"\0\0\0\0"
    for i, b in enumerate(table):
        mem[ENTITY_TABLE + i] = b
    ad = FakeAd(mem)
    ad.player_ptr = OBJ_BASE
    return ad


def set_table(ad, ptrs):
    """Rewrite the live entity table (to simulate the boss arena emptying/filling)."""
    if ad is None:
        return
    # clear the old table region, then write the new null-terminated pointer list
    for i in range(256 * 4):
        ad._mem.pop(ENTITY_TABLE + i, None)
    table = b"".join(struct.pack(">I", p) for p in ptrs) + b"\0\0\0\0"
    for i, b in enumerate(table):
        ad._mem[ENTITY_TABLE + i] = b


# --------------------------------------------------------------------------- active detection + weak point
def test_dragon_head_weakpoint():
    ad = build(episode=0, floor=11, enemies=[("TObjEneDragon", 2000, 2000, (10.0, 1.0, 20.0))])
    r = B.boss_target(ad)
    assert r["active"] and r["boss"] == "Dragon"
    assert r["phase"] == "head" and r["action"] == "aim_head"
    assert r["element"] is None
    assert r["weakpoint_pos"] == {"x": 10.0, "z": 20.0, "y": 1.0}
    assert r["boss_active"] and r["boss_weakpoint_locked"]
    assert r["boss_weakpoint_x"] == 10.0 and r["boss_weakpoint_z"] == 20.0
    assert "fire_breath_cone" in r["hazard"]
    assert r["boss_floor"] is True and r["boss_alive"] is True and r["boss_cleared"] is False
    assert r["boss_hp_frac"] == 1.0
    assert r["boss_weakpoint_dist"] == 22.4   # planar dist from P1 at origin to (10,_,20)


def test_main_body_pick_prefers_largest_hp():
    # two segments; _pick_main chooses the larger HP pool (the main body).
    ad = build(episode=0, floor=11, enemies=[
        ("TObjEneDragonTail", 300, 300, (5.0, 0.0, 5.0)),
        ("TObjEneDragon", 2500, 2500, (40.0, 0.0, 40.0))])
    r = B.boss_target(ad)
    assert r["weakpoint"]["hp_max"] == 2500 and r["weakpoint_pos"]["x"] == 40.0


def test_derolle_targets_surfaced_part_and_excludes_mines():
    # Live layout: head above the water line (max y), submerged joints (negative y), mine adds.
    # Aim the surfaced head; exclude the TBoss2Mine adds from the weak point.
    r = B.boss_target(build(episode=0, floor=12, enemies=[
        ("TBoss2DeRolLe", 20000, 20000, (175.0, 7.0, 25.0)),     # head, surfaced
        ("TBoss2Joint", 20000, 20000, (175.0, -13.0, 9.7)),       # submerged body segment
        ("TBoss2Joint", 20000, 20000, (183.0, -9.0, -71.0)),
        ("TBoss2Mine", 330, 330, (44.0, 2.0, 35.0))]))            # add -> must be excluded
    assert r["boss"] == "De Rol Le" and r["phase"] == "exposed_body_segment"
    assert r["weakpoint"]["class"] == "TBoss2DeRolLe"
    assert r["weakpoint_pos"] == {"x": 175.0, "z": 25.0, "y": 7.0}
    assert r["boss_entity_count"] == 3 and r["boss_add_count"] == 1    # 3 body parts, 1 mine filtered
    assert "mines" in r["hazard"]


def test_derolle_picks_the_highest_surfaced_segment():
    # When a body joint rises above the (submerged) head, THAT segment is the weak point.
    r = B.boss_target(build(episode=0, floor=12, enemies=[
        ("TBoss2DeRolLe", 20000, 20000, (175.0, -5.0, 25.0)),     # head submerged
        ("TBoss2Joint", 20000, 20000, (100.0, 9.0, -20.0))]))      # a segment surfaced higher
    assert r["weakpoint"]["class"] == "TBoss2Joint" and r["weakpoint_pos"]["y"] == 9.0


# --------------------------------------------------------------------------- phased bosses
def test_volopt_phase1_aims_monitors_not_core():
    # Phase 1: monitors + pillars present AND the core already exists -> still aim the nearest
    # monitor/pillar, defer the core. The far-parked P02 cube and the root are ignored.
    p1 = B.boss_target(build(episode=0, floor=13, enemies=[
        ("TBoss3Volopt", 0, 0, (0.0, 0.0, 0.0)),               # root, excluded (origin + no hp)
        ("TBoss3VoloptMonitor", 420, 420, (0.0, 0.0, -110.0)),
        ("TBoss3VoloptMonitor", 350, 350, (3.0, 0.0, 2.0)),    # nearest monitor to P1 at origin
        ("TBoss3VoloptP01", 500, 500, (76.0, 0.0, 0.0)),
        ("TBoss3VoloptCore", 3000, 3000, (-116.0, 50.0, 66.0)),  # exists but deferred in P1
        ("TBoss3VoloptP02", 9500, 9500, (0.0, 0.0, -5000.0))]))  # parked cube, deferred
    assert p1["boss"] == "Vol Opt" and p1["phase"] == "phase1_monitors"
    assert p1["action"] == "aim_monitors"
    assert p1["weakpoint"]["class"] == "TBoss3VoloptMonitor" and p1["weakpoint_pos"]["x"] == 3.0
    assert "electric_floor" in p1["hazard"]


def test_volopt_phase2_aims_core_when_monitors_gone():
    p2 = B.boss_target(build(episode=0, floor=13, enemies=[
        ("TBoss3VoloptCore", 3000, 3000, (-116.0, 50.0, 66.0)),
        ("TBoss3VoloptP02", 9500, 9500, (0.0, 0.0, -5000.0)),
        ("TBoss3VoloptHiraisin", 450, 450, (0.0, 50.0, 0.0))]))
    assert p2["phase"] == "phase2_core" and p2["action"] == "aim_core_panel"
    assert p2["weakpoint"]["class"] == "TBoss3VoloptCore"


def test_darkfalz_form_elements():
    base = dict(episode=0, floor=14, difficulty=3)
    f1 = B.boss_target(build(**base, enemies=[("TObjEneDarkFalz", 1000, 1000, (0.0, 0.0, 30.0))]))
    assert f1["boss"] == "Dark Falz" and f1["phase"] == "form1" and f1["element"] == "zonde"
    f2 = B.boss_target(build(**base, enemies=[("TObjEneDarkFalz", 500, 1000, (0.0, 0.0, 30.0))]))
    assert f2["phase"] == "form2" and f2["element"] == "barta"
    f3 = B.boss_target(build(**base, enemies=[("TObjEneDarkFalz", 100, 1000, (0.0, 0.0, 30.0))]))
    assert f3["phase"] == "form3" and f3["element"] == "foie"
    assert f3["elements"] == ["zonde", "barta", "foie"]


def test_darkfalz_no_form3_on_normal():
    # On Normal (difficulty 0) there is no third form: low HP still advises Barta, not Foie.
    r = B.boss_target(build(episode=0, floor=14, difficulty=0,
                            enemies=[("TObjEneDarkFalz", 50, 1000, (0.0, 0.0, 30.0))]))
    assert r["phase"] == "form2" and r["element"] == "barta"


def test_episode2_olga_flow():
    r = B.boss_target(build(episode=1, floor=13, enemies=[
        ("TObjEneOlgaFlow", 3000, 3000, (0.0, 0.0, 0.0)),
        ("TObjEneGael", 400, 400, (12.0, 0.0, 4.0))]))
    assert r["active"] and r["boss"] == "Olga Flow" and r["episode"] == 2
    assert r["phase"] == "phase2_with_adds"


def test_episode2_floor_map():
    assert B.boss_target(build(episode=1, floor=14, enemies=[("TObjEneBarbaRay", 2000, 2000, (1.0, 0.0, 2.0))]))["boss"] == "Barba Ray"
    assert B.boss_target(build(episode=1, floor=15, enemies=[("TObjEneGolDragon", 2000, 2000, (1.0, 0.0, 2.0))]))["boss"] == "Gol Dragon"
    assert B.boss_target(build(episode=1, floor=12, enemies=[("TObjEneGalGryphon", 2000, 2000, (1.0, 0.0, 2.0))]))["boss"] == "Gal Gryphon"


# --------------------------------------------------------------------------- HP robustness (unverified boss offset)
def test_invalid_hp_still_counts_as_alive():
    # hp > hp_max (garbage from an unverified boss offset) -> advisor keeps the boss, uses position.
    r = B.boss_target(build(episode=0, floor=11, enemies=[("TObjEneDragon", 9999, 0, (7.0, 0.0, 8.0))]))
    assert r["active"] and r["weakpoint_pos"]["x"] == 7.0


def test_zero_hp_entity_still_targeted():
    # HP offset is unverified, so a 0/garbage HP read must NOT drop a present boss entity:
    # it stays an aim candidate and the boss is still considered alive (conservative).
    r = B.boss_target(build(episode=0, floor=11, enemies=[("TObjEneDragon", 0, 2000, (7.0, 0.0, 8.0))]))
    assert r["active"] is True and r["weakpoint_pos"]["x"] == 7.0
    assert r["boss_alive"] is True and r["boss_cleared"] is False


def test_collision_helpers_excluded_from_aim():
    # Live Dragon layout: real body (HP bar + position) + TBoss1DragonColli_C helpers parked at
    # (0,0,0) with hp_max=0. The helpers must NOT be aim targets; the body is.
    r = B.boss_target(build(episode=0, floor=11, enemies=[
        ("TBoss1Dragon", 2500, 2500, (27.0, 0.0, 10.0)),
        ("TBoss1DragonColli_C", 65535, 0, (0.0, 0.0, 0.0)),
        ("TBoss1DragonColli_C", 9, 0, (0.0, 0.0, 0.0)),
        ("TBoss1DragonColli_C", 32987, 0, (0.0, 0.0, 0.0))]))
    assert r["active"] is True and r["boss"] == "Dragon"
    assert r["weakpoint"]["class"] == "TBoss1Dragon"
    assert r["weakpoint_pos"] == {"x": 27.0, "z": 10.0, "y": 0.0}
    assert r["boss_entity_count"] == 1          # the 3 collision helpers are excluded


def test_dragon_action_state_marks_attacking():
    # +0x326 action-state (build-agent ELF confirm): {21,22} = grounded-attack / fire-breath /
    # eruption window -> phase '<aim>_attacking' and boss_special_state True.
    ad = build(episode=0, floor=11, enemies=[("TBoss1Dragon", 2500, 2500, (27.0, 0.0, 10.0))])
    r0 = B.boss_target(ad)
    assert r0["phase"] == "head" and r0["boss_special_state"] is False and r0["action_state"] == 0
    dragon_ptr = OBJ_BASE + 0x400                 # player idx0, dragon idx1
    for i, b in enumerate(struct.pack(">H", 22)):
        ad._mem[dragon_ptr + 0x326 + i] = b
    r1 = B.boss_target(ad)
    assert r1["phase"] == "head_attacking" and r1["boss_special_state"] is True
    assert r1["action_state"] == 22 and r1["boss_action_state"] == 22
    assert r1["boss_phase"] == "head_attacking"


def test_only_collision_helpers_is_not_a_live_boss():
    # Only origin collision helpers present (no real body yet) -> no aim target, boss not "seen",
    # so boss_alive stays True (not spawned) and active is False.
    r = B.boss_target(build(episode=0, floor=11, enemies=[
        ("TBoss1DragonColli_C", 65535, 0, (0.0, 0.0, 0.0))]))
    assert r["active"] is False and r["boss_floor"] is True
    assert r["boss_alive"] is True and r["boss_cleared"] is False


# --------------------------------------------------------------------------- conservative alive signal (nav warp gate)
def test_boss_not_spawned_yet_stays_alive():
    # Boss floor, arena not yet populated, boss never seen -> alive True (do NOT warp), no lock.
    r = B.boss_target(build(episode=0, floor=11, enemies=[]))
    assert r["active"] is False and r["boss_floor"] is True
    assert r["boss_alive"] is True and r["boss_cleared"] is False
    assert r["reason"] == "boss_floor_no_boss_entity" and r["boss_name"] == "Dragon"


def test_boss_cleared_only_after_sustained_absence():
    clock = [1000.0]
    ad = build(episode=0, floor=11, enemies=[("TObjEneDragon", 2000, 2000, (10.0, 0.0, 20.0))])
    ad._pso_boss_clock = lambda: clock[0]

    r1 = B.boss_target(ad)                      # boss present -> seen, alive
    assert r1["active"] is True and r1["boss_alive"] is True

    set_table(ad, [ad.player_ptr])              # arena empties (only the player remains)
    clock[0] += 2.0                             # a short gap (dive / phase swap)
    r2 = B.boss_target(ad)
    assert r2["active"] is False and r2["boss_alive"] is True and r2["boss_cleared"] is False

    clock[0] += B.DEAD_GRACE_S                   # sustained absence beyond the grace window
    r3 = B.boss_target(ad)
    assert r3["boss_alive"] is False and r3["boss_cleared"] is True
    assert r3["active"] is False and r3["boss_floor"] is True

    # the defeat latches for this visit even if a stray entity flickers back
    set_table(ad, [ad.player_ptr, OBJ_BASE + 0x400])
    assert B.boss_target(ad)["boss_alive"] is False


def test_floor_change_rearms_alive_state():
    clock = [500.0]
    ad = build(episode=0, floor=11, enemies=[("TObjEneDragon", 2000, 2000, (10.0, 0.0, 20.0))])
    ad._pso_boss_clock = lambda: clock[0]
    B.boss_target(ad)
    set_table(ad, [ad.player_ptr]); clock[0] += B.DEAD_GRACE_S + 1
    assert B.boss_target(ad)["boss_cleared"] is True
    # leave the boss floor and come back next loop -> state resets, boss_alive re-arms
    for i, b in enumerate(struct.pack(">I", 8)):
        ad._mem[FLOOR + i] = b                   # floor 8 (non-boss)
    assert B.boss_target(ad)["active"] is False and B.boss_target(ad)["boss_floor"] is False
    for i, b in enumerate(struct.pack(">I", 11)):
        ad._mem[FLOOR + i] = b                   # back to Dragon floor
    set_table(ad, [ad.player_ptr, OBJ_BASE + 0x400])  # the boss is present again this visit
    r = B.boss_target(ad)
    assert r["active"] is True and r["boss_alive"] is True and r["boss_cleared"] is False


def test_boss_alive_convenience():
    assert B.boss_alive(build(episode=0, floor=11, enemies=[("TObjEneDragon", 2000, 2000, (1.0, 0.0, 2.0))])) is True
    assert B.boss_alive(build(episode=0, floor=3)) is None    # off a boss floor


# --------------------------------------------------------------------------- fail-soft / inactive paths
def test_not_a_boss_floor():
    r = B.boss_target(build(episode=0, floor=3, enemies=[("TObjEneBeast", 60, 60, (1.0, 0.0, 2.0))]))
    assert r["active"] is False and r["reason"] == "not_a_boss_floor"
    assert r["boss_active"] is False


def test_travelling_is_inactive():
    r = B.boss_target(build(episode=0, floor=11, travelling=1,
                            enemies=[("TObjEneDragon", 2000, 2000, (1.0, 0.0, 2.0))]))
    assert r["active"] is False and r["reason"] == "travelling"


def test_not_free_play_is_inactive():
    r = B.boss_target(build(episode=0, floor=11, phase=5,
                            enemies=[("TObjEneDragon", 2000, 2000, (1.0, 0.0, 2.0))]))
    assert r["active"] is False and r["reason"] == "not_free_play"


def test_wrong_disc_is_inactive():
    r = B.boss_target(build(disc=b"GEZE8P\0\x02", floor=11,
                            enemies=[("TObjEneDragon", 2000, 2000, (1.0, 0.0, 2.0))]))
    assert r["active"] is False and r["reason"] == "not_pso_gc_plus_us"


def test_read_error_is_inactive():
    class Boom:
        def read_memory(self, a, n):
            raise OSError("session gone")
    r = B.boss_target(Boom())
    assert r["active"] is False and r["reason"] == "read_error"


def test_never_raises_on_garbage():
    class Garbage:
        def read_memory(self, a, n):
            return b"\xff" * n
    assert B.boss_target(Garbage())["active"] is False


# --------------------------------------------------------------------------- telemetry shape
def test_boss_telemetry_flat_scalars_only():
    ad = build(episode=0, floor=11, enemies=[("TObjEneDragon", 2000, 2000, (10.0, 1.0, 20.0))])
    t = B.boss_telemetry(ad)
    assert set(t) == {"boss_active", "boss_name", "boss_phase", "boss_weakpoint_locked",
                      "boss_weakpoint_x", "boss_weakpoint_z", "boss_alive", "boss_cleared",
                      "boss_floor", "boss_hp_frac", "boss_action_state", "boss_add_count",
                      "boss_weakpoint_dist"}
    assert t["boss_active"] is True and t["boss_name"] == "Dragon"
    assert t["boss_alive"] is True and t["boss_floor"] is True and t["boss_hp_frac"] == 1.0
    assert all(not isinstance(v, (dict, list)) for v in t.values())


def test_boss_telemetry_inactive():
    t = B.boss_telemetry(build(episode=0, floor=3))
    assert t["boss_active"] is False and t["boss_name"] is None and t["boss_weakpoint_locked"] is False
    assert t["boss_alive"] is None and t["boss_floor"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
