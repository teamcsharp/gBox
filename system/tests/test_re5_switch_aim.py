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


def test_turning_on_a_slope_preserves_tilt_and_unit_rotation():
    g = guest()
    # A 30-degree slope plus yaw: changing heading must retain the tilt.
    tilt, yaw = math.radians(30) / 2, .5 / 2
    q = (math.cos(yaw)*math.sin(tilt), math.sin(yaw)*math.cos(tilt),
         -math.sin(yaw)*math.sin(tilt), math.cos(yaw)*math.cos(tilt))
    g.put(PLAYER + A.P_ROT, struct.pack('<4f', *q))
    writer = A.aim_writer(Session(g))
    for heading in (1.2, -2.9, 3.1, .8, .8):
        assert writer(A.aim_state(g, BASE, PLAYER), None, heading)
        x, y, z, w = struct.unpack('<4f', g.rd(PLAYER + A.P_ROT, 16))
        assert x*x+y*y+z*z+w*w == pytest.approx(1., abs=1e-6)
        assert math.hypot(x, z) == pytest.approx(math.sin(tilt), abs=1e-6)
        assert A.wrap(2*math.atan2(y, w)-heading) == pytest.approx(0., abs=1e-6)


@pytest.mark.parametrize('changed', ['life', 'camera', 'stale', 'nan'])
def test_writer_revalidates_owner_and_freshness_before_any_write(changed):
    g = guest(); st = A.aim_state(g, BASE, PLAYER)
    if changed == 'life': g.q(PLAYER + 0x1A00, 2)
    if changed == 'camera': g.q(CTRL + A.CTRL_ACTIVE, 0)
    if changed == 'stale': st['sampled_at'] -= 1
    assert not A.aim_writer(Session(g))(st, float('nan') if changed == 'nan' else .1, .2)
    assert not g.writes


def test_no_writer_without_an_adapter_or_with_modifications_off():
    assert A.aim_writer(object()) is None
    s = Session(guest())
    s.mercs_no_modifications = True
    assert A.aim_writer(s) is None


def test_camera_sample_age_starts_before_its_first_read(monkeypatch):
    g, clock = guest(), [1.]
    monkeypatch.setattr(A.time, 'monotonic', lambda: clock[0])
    rd = g.rd
    def delayed(addr, size):
        result = rd(addr, size)
        clock[0] += .02
        return result
    g.rd = delayed
    st = A.aim_state(g, BASE, PLAYER)
    assert st['sampled_at'] == 1.
    assert st['sample_completed_at'] - st['sampled_at'] > A.MAX_SAMPLE_AGE
    assert not A.aim_writer(Session(g))(st, .1, .2)
    assert not g.writes


def test_writer_refuses_if_ownership_validation_itself_uses_freshness_budget(monkeypatch):
    g, clock = guest(), [1.]
    monkeypatch.setattr(A.time, 'monotonic', lambda: clock[0])
    st = A.aim_state(g, BASE, PLAYER)
    lookup = A.player_qfps
    def delayed(*args):
        clock[0] += .2
        return lookup(*args)
    monkeypatch.setattr(A, 'player_qfps', delayed)
    assert not A.aim_writer(Session(g))(st, .1, .2)
    assert not g.writes


def final_read_scene(monkeypatch):
    g = guest(pitch=.1, heading=.2)
    enemy, sp, se, arr, main, gs, item = (0x5D40000000 + i*0x10000 for i in range(7))
    g.q(BASE + R.S_PLAYER, sp); g.q(sp + R.P_FIRST, PLAYER)
    g.q(BASE + R.S_ENEMY, se); g.q(se + R.E_ARRAY, arr)
    g.put(se + R.E_COUNT, struct.pack('<I', 1)); g.q(arr, enemy)
    g.q(BASE + R.S_MAIN, main); g.q(main + R.MAIN_GAMESYS, gs)
    g.put(gs + R.GS_PHASE, struct.pack('<i', R.PHASE_PLAYING))
    g.q(PLAYER + 0x1A00, 12); g.q(enemy + 0x1A00, 42); g.q(enemy, BASE+0x1234)
    g.put(PLAYER + R.P_POS, struct.pack('<4f', 20., 10., 30., 0.))
    g.put(PLAYER + R.P_HP, struct.pack('<hh', 800, 1000))
    g.put(PLAYER + R.P_MOTION, bytes([R.MOTION_AIMED]))
    g.put(enemy + R.E_POS, struct.pack('<3f', 40., 10., 330.))
    g.put(enemy + R.E_HP, struct.pack('<hh', 700, 800))
    g.put(enemy + R.E_MOTION, bytes([4]))
    slot_addr = PLAYER + R.P_INV
    g.put(slot_addr + R.INV_ID, struct.pack('<I', 0x11b))
    g.put(slot_addr + R.INV_HAND, struct.pack('<i', 1))
    g.q(slot_addr + R.INV_OBJ, item)
    current_ray = {'up': True, 'from': (20., 150., 30.), 'at': (40., 120., 330.)}
    monkeypatch.setattr(R, 'enemy_class', lambda *a: 'uEm10')
    monkeypatch.setattr(R, 'laser', lambda *a: dict(current_ray))
    old = {'module_base': BASE, 'mercenaries_phase': R.PHASE_PLAYING,
           'player': {'ptr': PLAYER, 'generation': 12, 'pos': (0., 0., 0.), 'hp': 1000, 'motion': 26},
           'enemies': [{'ptr': enemy, 'slot': 0, 'pos': (0., 0., 300.), 'hp': 800, 'motion': 4}],
           'inventory': R.inventory(g, PLAYER), 'aim_cam': A.aim_state(g, BASE, PLAYER),
           'laser': {'up': True, 'from': (0., 140., 0.), 'at': (0., 110., 300.)}}
    return g, old, {'enemy': enemy, 'sp': sp, 'se': se, 'arr': arr, 'gs': gs, 'ray': current_ray}


def test_final_read_refreshes_target_and_player_before_camera_and_laser(monkeypatch):
    g, old, locations = final_read_scene(monkeypatch)
    reads, rd = [], g.rd
    def observe(addr, size):
        reads.append(addr)
        return rd(addr, size)
    g.rd = observe
    fresh, target, reason = A.refresh_target(g, old, old['enemies'][0])
    assert reason is None
    assert fresh['player']['pos'] == (20., 10., 30.) and fresh['player']['hp'] == 800
    assert target['pos'] == (40., 10., 330.) and target['generation'] == 42 and target['hp'] == 700
    assert fresh['aim_cam']['generation'] == 12
    assert fresh['laser'] == locations['ray']
    assert reads.index(PLAYER + R.P_POS) < reads.index(CTRL + A.CTRL_QFPS + A.QF_PITCH)
    assert reads.index(locations['enemy'] + R.E_POS) < reads.index(CTRL + A.CTRL_QFPS + A.QF_PITCH)
    assert old['player']['pos'] == (0., 0., 0.) and old['enemies'][0]['pos'] == (0., 0., 300.)


@pytest.mark.parametrize('changed', ['player_life', 'player_slot', 'target_slot', 'target_count', 'target_life',
                                     'phase', 'weapon', 'held_flag', 'dead_target', 'nonfinite', 'slow'])
def test_final_read_rejects_reused_or_changed_actors_and_slow_reads(monkeypatch, changed):
    g, old, where = final_read_scene(monkeypatch)
    ray_reader = R.laser
    clock = [1.]
    monkeypatch.setattr(A.time, 'monotonic', lambda: clock[0])
    if changed == 'dead_target': g.put(where['enemy'] + R.E_HP, struct.pack('<h', 0))
    if changed == 'nonfinite': g.put(where['enemy'] + R.E_POS, struct.pack('<f', float('nan')))
    def changing(*args):
        result = ray_reader(*args)
        if changed == 'player_life': g.q(PLAYER + 0x1A00, 13)
        elif changed == 'player_slot': g.q(where['sp'] + R.P_FIRST, PLAYER+0x100000)
        elif changed == 'target_slot': g.q(where['arr'], where['enemy']+0x100000)
        elif changed == 'target_count': g.put(where['se'] + R.E_COUNT, struct.pack('<I', 0))
        elif changed == 'target_life': g.q(where['enemy'] + 0x1A00, 43)
        elif changed == 'phase': g.put(where['gs'] + R.GS_PHASE, struct.pack('<i', R.PHASE_OVER))
        elif changed == 'weapon': g.put(PLAYER + R.P_INV + R.INV_ID, struct.pack('<I', 0x104))
        elif changed == 'held_flag': g.put(PLAYER + R.P_INV + R.INV_HAND, struct.pack('<i', 0))
        elif changed == 'slow': clock[0] += .2
        return result
    monkeypatch.setattr(R, 'laser', changing)
    fresh, target, reason = A.refresh_target(g, old, old['enemies'][0])
    assert fresh is target is None and reason
    assert not g.writes


def test_firing_gate_uses_the_refreshed_obstruction_not_the_old_clear_ray(monkeypatch):
    from tests.test_re5_target_feedback import controller
    g, old, where = final_read_scene(monkeypatch)
    # The old ray ends on him; at the final gate a wall stops the new ray short.
    where['ray']['at'] = (20., 150., 80.)
    bot, writes = controller()
    bot._m, bot.target = g, where['enemy']
    out = A.apply(bot, old, {'hold': ('zl', 'zr')}, .15)
    assert writes and 'zr' not in out['hold']
    assert bot.stats['target_feedback_refresh_error'] is None
    assert bot.stats['target_feedback_gate'] == 'ray misses or stops before target'


def test_rejected_late_read_releases_fire_and_discards_correction_budget(monkeypatch):
    from tests.test_re5_target_feedback import controller
    g, old, where = final_read_scene(monkeypatch)
    g.q(PLAYER + 0x1A00, 13)
    bot, writes = controller()
    bot._m, bot.target = g, where['enemy']
    out = A.apply(bot, old, {'hold': ('zl', 'zr', 'rleft')}, .15)
    assert out['hold'] == ('zl',) and not writes
    assert bot._feedback_at is bot._feedback_context is None
    assert bot.stats['target_feedback_refresh_rejections'] == 1
    assert 'life' in bot.stats['target_feedback_refresh_error']


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


def _graze(item, dot_y, cam_pitch):
    """Moment e868adee806d44ce: one Majini 2.8 m ahead, the ray crossing his legs, the dot on the wall behind."""
    from tests.test_re5_switch_weapon_mastery import _feedback_bot
    bot, snap = _feedback_bot(item, at(280, 0), (0.0, dot_y, 730.0))
    snap["aim_cam"]["pitch"] = cam_pitch
    return bot, snap


def test_a_grazing_close_segment_with_a_large_pitch_error_holds_fire():
    bot, snap = _graze(0x1A, 20.0, 0.25)                # camera ~21 deg off the chest, ray grazing his legs
    out = A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.0)
    assert "zr" not in out["hold"] and bot.stats["target_feedback_pitch_holds"] == 1


def test_a_close_segment_with_the_pitch_near_still_fires():
    bot, snap = _graze(0x1A, 120.0, -0.25)              # ~7 deg off: inside SEGMENT_PITCH_MAX
    assert "zr" in A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.0)["hold"]
    assert bot.stats.get("target_feedback_pitch_holds", 0) == 0


def test_the_grazing_pitch_hold_is_bounded_and_then_fires():
    """It stops wasting pulls at a wall while the pitch corrects, but it must not withhold the trigger for a whole round.

    Live 2026-11-12: doing=aim, act=['rleft','zl'], blk=ray=False up=False d=1.5m yaw=+8.0 pitch=-14.5 - a Majini at
    1.5 m, on target in bearing, no shot, and RE5 reports at 0-1 kills where it once ran 13.8-19.6.
    """
    bot, snap = _graze(0x1A, 20.0, 0.25)
    assert "zr" not in A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.0)["hold"]      # the correction window opens
    late = A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.0 + A.SEGMENT_PITCH_HOLD_S + 0.05)
    assert "zr" in late["hold"]                                                     # ... and then he fires anyway
    assert bot.stats["target_feedback_pitch_hold_lapses"] == 1


def test_a_clear_shot_reopens_the_pitch_hold_window():
    bot, snap = _graze(0x1A, 20.0, 0.25)
    A.apply(bot, snap, {"hold": ("zl", "zr")}, 1.0)            # holding
    _, clear = _graze(0x1A, 120.0, -0.25)                     # the same bot, a shot the pitch allows
    A.apply(bot, clear, {"hold": ("zl", "zr")}, 1.1)
    assert bot.__dict__.get("_pitch_hold_since") is None       # window closed: a later graze gets its own window
