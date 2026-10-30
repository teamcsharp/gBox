"""Aimed fire requires the measured laser segment; camera writes are not hit evidence."""
import pytest

from gbox.mercs.titles import re6_switch as R
from test_re6_switch import _fresh_caches, brain, lock_brain, round_guest, run


@pytest.mark.parametrize("height", [0.0, 600.0])
def test_a_laser_stopped_before_the_body_never_confirms_a_hit(height):
    bot = R.Bot(stats={})
    bot._ppos = (0.0, 0.0, 0.0)
    enemy = {"ptr": 123, "pos": (0.0, height, 900.0), "hp": 700}
    origin = (0.0, height + R.CHEST_H, 0.0)
    # The old same-floor slack extends 50 cm, and the off-floor line has no endpoint limit.
    dot = (0.0, height + R.CHEST_H, 850.0)
    assert bot._on_line(origin, dot, "laser", [enemy], 1.0) is None
    assert not bot.laser_seen


def test_an_off_floor_dot_at_the_feet_is_not_a_body_hit():
    bot = R.Bot(stats={})
    bot._ppos = (0.0, 0.0, 0.0)
    enemy = {"ptr": 123, "pos": (0.0, 600.0, 300.0), "hp": 700}
    assert bot._on_line((0.0, 145.0, 30.0), enemy["pos"], "laser", [enemy], 1.0) is None
    assert not bot.laser_seen


@pytest.mark.parametrize("height", [0.0, 600.0])
@pytest.mark.parametrize("end_z", [880.0, 900.0, 1100.0])
def test_measured_body_hits_and_segments_through_the_body_still_fire(height, end_z):
    bot = R.Bot(stats={})
    bot._ppos = (0.0, 0.0, 0.0)
    enemy = {"ptr": 123, "pos": (0.0, height, 900.0), "hp": 700}
    origin, dot = (0.0, height + R.CHEST_H, 0.0), (0.0, height + R.CHEST_H, end_z)
    assert bot._on_line(origin, dot, "laser", [enemy], 1.0) is enemy
    assert bot.laser_seen[123] == 1.0


@pytest.mark.parametrize("pos", [(0.0, 0.0, 700.0), (0.0, 0.0, 1500.0), (0.0, 600.0, 300.0)])
def test_camera_alignment_and_old_hit_evidence_cannot_authorize_aimed_fire(pos):
    bot = R.Bot(stats={})
    bot._ppos = (0.0, 0.0, 0.0)
    enemy = {"ptr": 123, "pos": pos, "hp": 700}
    bot.seen[123] = bot.laser_seen[123] = 1.0
    assert bot._on_line((0.0, 145.0, 0.0), R.aim_point(enemy, bot._ppos), "camera", [enemy], 1.0) is None


@pytest.mark.parametrize("dot, correction", [((0.0, -300.0, 900.0), "rup"), ((500.0, 115.0, 900.0), "rright")])
def test_a_successful_ram_write_with_a_misaligned_laser_yields_to_stick_correction(dot, correction):
    wrong = (dot, (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),), laser=wrong)
    acts = run(bot, snap, clock, 16)
    assert bot.stats["lock_write_ok"] > 0
    assert bot.stats["lock_fallbacks"] == 1
    assert bot.lock_off_until > clock[0]
    assert any(correction in act.get("hold", ()) for act in acts)
    assert all("zr" not in act.get("hold", ()) for act in acts)
    count = len(writes)
    run(bot, snap, clock, 5)
    assert len(writes) == count


def test_lock_reacquisition_gets_a_new_grace_then_fires_when_the_laser_converges():
    wrong = ((0.0, -300.0, 900.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),), laser=wrong)
    run(bot, snap, clock, 16)
    assert bot.lock_off_until > clock[0]
    count = len(writes)
    clock[0] = bot.lock_off_until + 0.01
    run(bot, snap, clock, 2)
    assert len(writes) > count
    assert bot.stats["lock_fallbacks"] == 1
    snap["laser"]["at"] = (0.0, R.CHEST_H, 900.0)
    acts = run(bot, snap, clock, 10)
    assert any("zr" in act.get("hold", ()) for act in acts)
    assert bot.stats["lock_fallbacks"] == 1


def test_lost_laser_holds_aimed_fire_and_reappearing_laser_resumes_it():
    on = ((0.0, R.CHEST_H, 900.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),), laser=on)
    assert any("zr" in a.get("hold", ()) for a in run(bot, snap, clock, 8))
    laser, snap["laser"] = snap["laser"], None
    assert all("zr" not in a.get("hold", ()) for a in run(bot, snap, clock, 16))
    snap["laser"] = laser
    assert any("zr" in a.get("hold", ()) for a in run(bot, snap, clock, 8))
    assert bot.stats["lock_fallbacks"] == 0


def test_point_blank_emergency_quick_shots_survive_without_a_laser():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 150.0, 700),), cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, int(2 * R.CC_QSHOT_GAP_S / 0.05))
    assert bot.stats["cc_quick_shots"] >= 2
    assert any("zr" in act.get("hold", ()) for act in acts)


def test_a_material_camera_redirect_cannot_fire_using_the_pre_write_ray():
    on = ((0.0, R.CHEST_H, 900.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700), (700.0, 0.0, 900.0, 700)), laser=on)
    bot._ppos = snap["player"]["pos"]
    old, target = snap["enemies"]
    origin, dot = snap["laser"]["from"], snap["laser"]["at"]
    assert bot._on_line(origin, dot, "laser", [old], 1.0) is old
    assert bot._lock(snap["player"], target, snap, 1.0)
    assert writes
    assert bot._on_line(origin, dot, "laser", [old], 1.0) is None
    # A new frame with a ray on the redirected target can authorize fire again.
    dot = R.aim_point(target, bot._ppos)
    assert bot._on_line(origin, dot, "laser", [target], 1.05) is target


def test_an_off_floor_threat_stays_targetable_during_stick_correction(monkeypatch):
    monkeypatch.setattr(R, "CEILING_R", 400.0)  # exercise the supported vertical-target policy (disabled by default)
    wrong = ((0.0, 100.0, 900.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap, writes = lock_brain(((0.0, 600.0, 300.0, 700),), laser=wrong)
    acts = run(bot, snap, clock, 16)
    assert bot.stats["lock_fallbacks"] == 1
    assert snap["enemies"][0] in bot._off_floor(snap["player"], snap, clock[0])
    assert any("rup" in act.get("hold", ()) for act in acts)
    assert all("zr" not in act.get("hold", ()) for act in acts)
