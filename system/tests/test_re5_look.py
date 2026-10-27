"""RE5 "look at the bot" (gbox.mercs.bot_look in the RE5 driver): stats look, every shot with what the dot was on and
what it did, every decision change, the idle streak among foes, the round's behaviour block (gbox.mercs.behavior_metrics)
and audit flags (operator 2026-10-26:
"when i say 'look at the bot' i want you able to see the last things and results of the last bullets being fired by
the bot. They are shooting at walls and just sitting here amongst foes")."""
import json
import math

from gbox.mercs import ballistics as B
from gbox.mercs.bot_look import BotLook
from gbox.mercs.round_audit import RoundAudit
from gbox.mercs.round_map import RoundTrace
from gbox.mercs.titles import re5_combat as C, re5_ps3 as R
from tests.test_re5_combat import ACT, ENEMY, PL, snap, supported_laserless, world

SHOT_KEYS = {"t", "weapon", "gate", "target", "aim_err_deg", "dot_on", "outcome", "hp_delta"}


def bot_at(tmp_path, now, **kw):
    m = world(**kw)
    return m, R.Bot(m, clock=lambda: now[0], learn_dir=tmp_path, lessons=lambda e: None)


def test_stats_look_has_the_shared_schema_and_follows_a_shot_to_its_hit(tmp_path, monkeypatch):
    from gbox.mercs.titles import re5_mines
    monkeypatch.setattr(re5_mines, "ground_mines", lambda m: {})           # a verified empty mine scan: a solo hit
    now = [10.0]
    m, bot = bot_at(tmp_path, now, laser_dot=(0.0, 110.0, 400.0))

    def frame(**kw):
        s = snap(m, **kw)
        s.update(ground_mines={}, player=dict(s["player"], pitch=0.0))  # the snapshot's own verified mine scan
        return s
    assert {"l1", "r1"} <= bot.tick(frame())["hold"]                    # the dot on him: the trigger
    m.put(ACT, ">I", C.FIRE_VT)                                         # the game fires
    m.put(ACT + C.ACT_FRAMES, ">f", 1.0)
    now[0] = 10.05
    bot.tick(frame())
    now[0] = 10.1
    bot.tick(frame(hp=600))                                             # his health falls
    look = bot.stats["look"]
    assert set(look) == {"shots", "decisions", "idle_among_foes_s", "walls_shot"}
    shot = look["shots"][-1]
    assert set(shot) == SHOT_KEYS and set(shot["target"]) == {"id", "kind", "dist_m", "bearing_deg"}
    assert shot["weapon"] == "Samurai Edge (0x12)" and shot["gate"] == "on him" and shot["dot_on"] == "target"
    assert shot["target"] == {"id": hex(ENEMY), "kind": "majini", "dist_m": 4.0, "bearing_deg": 0.0}
    assert shot["outcome"] == "hit:majini" and shot["hp_delta"] == -200 and shot["t"] == 10.05
    assert isinstance(shot["aim_err_deg"], float) and abs(shot["aim_err_deg"]) < 1.0
    assert look["decisions"][-1]["phase"] == "fight" and look["decisions"][-1]["decision"] == "fire"   # 4 m: fight
    assert len(json.dumps(look, separators=(",", ":"))) <= 40 * 1024    # gbox.tools.TELEMETRY_BLOCK_MAX: posted as is
    behavior = bot.metrics.summary()                                    # the round's behaviour block
    assert behavior["shot_lines"] == {"target": 1} and behavior["shot_outcomes"] == {"hit": 1}
    assert behavior["aim"]["shots_on_target"] == 1 and behavior["aim"]["shots_off_target"] == 0


def test_a_shot_into_a_wall_is_counted_and_resolved_as_a_wall_miss(tmp_path):
    m = world(laser_dot=(60.0, 120.0, 150.0))                           # a wall 1 m off, 30 deg beside him
    combat = C.Combat(m, {}, clock=lambda: 0.0, learn_dir=tmp_path, lessons=lambda e: None)
    combat.look = BotLook(epoch=lambda: 0.0)
    s = snap(m)
    combat.tick(s, s["player"], s["enemies"][0], 1.0)
    combat.observe(dict(s), 1.05)
    combat._on_shot(1.05)                                               # a shot leaves with the dot on the wall
    for k in range(10):                                                 # nothing lost health: a miss
        combat.observe(dict(s), 1.1 + k * 0.05)
    shot = combat.look.snapshot()["shots"][-1]
    assert shot["dot_on"] == "wall" and shot["outcome"] == "miss:wall" and combat.look.walls_shot == 1
    assert combat.round_dots == {"wall": 1} and combat.round_shots[-1]["dot_on"] == "wall"


def test_idle_among_foes_grows_standing_without_a_shot_and_ends_with_a_shot(tmp_path):
    now = [10.0]
    m, bot = bot_at(tmp_path, now)
    s = snap(m, enemy=(0.0, 0.0, 300.0))
    for k in range(11):                                                 # 1 s: a Majini 3 m off, no step, no shot
        now[0] = 10.0 + k * 0.1
        bot._look_tick(s, {"hold": {"l1"}}, bot.combat.decisions_n)
    assert abs(bot.look.idle_s - 1.0) < 0.06 and abs(bot.look_round["idle_among_foes_s"] - 1.0) < 0.06
    now[0] = 11.1
    bot._look_tick(s, {"hold": {"l1", "r1"}}, bot.combat.decisions_n)  # the gun up (aiming), the trigger: busy
    assert bot.look.idle_s == 0.0 and bot.look_round["idle_max_s"] >= 0.95
    far = snap(m, enemy=(0.0, 0.0, 900.0))                              # nobody within 4 m: not "among foes"
    for k in range(5):
        now[0] = 11.2 + k * 0.1
        bot._look_tick(far, {"hold": set()}, bot.combat.decisions_n)
    assert bot.look.idle_s == 0.0
    assert bot.stats["round_idle_among_foes_s"] == round(bot.look_round["idle_among_foes_s"], 1)


def test_walking_is_not_idle(tmp_path):
    now = [10.0]
    m, bot = bot_at(tmp_path, now)
    for k in range(6):
        now[0] = 10.0 + k * 0.1
        s = snap(m, enemy=(0.0, 0.0, 300.0))
        s["player"]["pos"] = (k * 20.0, 0.0, 0.0)                        # 2 m/s
        bot._look_tick(s, {"hold": {"lup"}}, bot.combat.decisions_n)
    assert bot.look.idle_s == 0.0 and bot.look_round["idle_among_foes_s"] == 0.0


def test_turning_gun_down_with_a_majini_close_is_counted_per_round(tmp_path):
    now = [10.0]
    m, bot = bot_at(tmp_path, now, aiming=False, act_vt=0)
    for k in range(6):
        now[0] = 10.0 + k * 0.1
        s = snap(m, enemy=(300.0, 0.0, 0.0))                              # 3 m off, 90 deg to his left: the swing
        s["laser"] = None
        act = bot.tick(s)
        assert "rleft" in act["hold"] and not act["hold"] & {"l1", "r1"}
    assert abs(bot.look_round["gun_down_close_s"] - 0.5) < 0.06
    assert bot.stats["look"]["decisions"][-1]["decision"] == "swing (gun down)"


def test_a_full_look_fits_the_telemetry_block_bound():
    """gbox.tools posts stats["look"] when it encodes within TELEMETRY_BLOCK_MAX (40 KB): full rings of the longest RE5
    entries (the gate and the reason capped at bot_look.REASON_MAX) stay well under it."""
    look = BotLook(epoch=lambda: 1793064177.67)
    for k in range(40):
        look.record_shot("Lightning Hawk (0x1a)", "x" * 300, {"id": hex(0x30800000 + k), "kind": "majini",
                                                                "dist_m": 12.34, "bearing_deg": -123.4},
                         aim_err_deg=-12.3, dot_on="target", outcome="miss:off_target", hp_delta=-331)
        look.record_decision("clear_nearby", f"swing (gun down) {k}", "y" * 300)
    assert len(json.dumps(look.snapshot(), separators=(",", ":"))) < 25 * 1024


def test_the_round_audit_flags_the_floor_shot_and_gun_down_turning_close_and_keeps_the_look_metrics():
    audit, stats = RoundAudit("BLUS30491"), {"rounds": 1, "character": "Chris"}
    audit.start(stats)
    trace = RoundTrace(None, "BLUS30491", "Village", "r1", 400.0)
    for k in range(120):
        trace.add(k * 0.25, k * 30.0, 0.0, 0.0, {"phase": "clear_nearby"})
    trace.annex["combat_look"] = {"walls_shot": 3, "floor_shots": 6, "idle_among_foes_s": 12.5, "idle_max_s": 6.0,
                                  "gun_down_close_s": 9.0, "foes_close_s": 30.0}
    trace.annex["behavior"] = {"shot_lines": {"target": 20, "wall": 3, "floor": 6}}
    trace.auditor = lambda summary, tr: audit.finish(summary, tr, stats)
    a = trace.finish()["audit"]
    probs = " | ".join(a["problems"])
    assert "shooting the floor: 6 of 29 shots" in probs
    assert "gun-down turning with a Majini within 4 m: 9 s of 30 s" in probs
    assert a["metrics"]["walls_shot"] == 3 and a["metrics"]["gun_down_close_s"] == 9.0
    assert a["metrics"]["idle_among_foes_s"] == 12.5 and a["metrics"]["floor_shots"] == 6
    clean = RoundAudit("BLUS30491")
    clean.start(stats)
    trace.annex["combat_look"] = {"walls_shot": 0, "floor_shots": 0, "idle_among_foes_s": 2.0, "idle_max_s": 1.0,
                                  "gun_down_close_s": 1.5, "foes_close_s": 30.0}
    trace.auditor = lambda summary, tr: clean.finish(summary, tr, stats)
    probs = " | ".join(trace.finish()["audit"]["problems"])
    assert "floor" not in probs and "gun-down turning with" not in probs


def test_the_driver_keeps_the_rounds_look_flags_and_behaviour_block_in_its_round_map(tmp_path):
    now = [10.0]
    m, bot = bot_at(tmp_path, now)
    bot._trace = RoundTrace(None, "BLUS30491", "stage", "r1", 400.0)
    bot._look_tick(snap(m, enemy=(0.0, 0.0, 300.0)), {"hold": set()}, bot.combat.decisions_n)
    assert set(bot._trace.annex["combat_look"]) == {"walls_shot", "floor_shots", "idle_among_foes_s", "idle_max_s",
                                                    "gun_down_close_s", "foes_close_s"}
    assert set(bot._trace.annex["behavior"]) >= {"aim", "shot_lines", "walls_shot", "shot_outcomes", "idle_among_foes"}


def test_the_rounds_behaviour_block_flags_walls_and_sitting_among_foes_as_for_every_title():
    """The RE5 bot feeds gbox.mercs.behavior_metrics: the shared audit (RoundAudit._behavior) flags the walls shot and
    the idle streak among foes for RE5 as for RE4."""
    from gbox.mercs.behavior_metrics import BehaviorMetrics
    metrics = BehaviorMetrics()
    for k in range(20):
        metrics.shot_line("wall" if k < 6 else "target")
        metrics.shot_result("miss:wall" if k < 6 else "hit:majini")
    for k in range(40):                                                   # 4 s among foes, no step, no shot
        metrics.idle_tick(0.1, True)
    audit, stats = RoundAudit("BLUS30491"), {"rounds": 1, "character": "Chris"}
    audit.start(stats)
    trace = RoundTrace(None, "BLUS30491", "Village", "r1", 400.0)
    for k in range(120):
        trace.add(k * 0.25, k * 30.0, 0.0, 0.0, {"phase": "clear_nearby"})
    trace.annex["behavior"] = metrics.summary()
    trace.auditor = lambda summary, tr: audit.finish(summary, tr, stats)
    probs = " | ".join(trace.finish()["audit"]["problems"])
    assert "shooting walls: 6 of 20 shots" in probs and "sat among foes: 4 s" in probs


def test_the_driver_drops_an_implausible_laser_read_from_the_snapshot(tmp_path):
    m, bot = bot_at(tmp_path, [10.0])
    s = snap(m)
    s["laser"] = {"from": (900.0, 149.0, 46.0), "at": (900.0, 110.0, 400.0)}   # 9 m from him: not his gun
    bot._sanitize_laser(s)
    assert s["laser"] is None and s["laser_raw"]["from"][0] == 900.0 and bot.stats["laser_rejected"] == 1
    s = snap(m)
    s["laser"] = {"from": (0.0, 149.0, 46.0), "at": (0.0, 110.0, 400.0)}
    bot._sanitize_laser(s)
    assert s["laser"] is not None and bot.stats["laser_rejected"] == 1


def test_a_gun_down_laser_gun_engages_a_majini_within_two_metres_without_a_floor_corridor(tmp_path):
    """The old "no ray right now = laserless" rule dropped him (no straight floor segment) while close_foes kept him close:
    the bot turned to face him without raising the gun."""
    from gbox.mercs.titles.re5_nav import NavMesh
    now = [10.0]
    m, bot = bot_at(tmp_path, now, aiming=False, act_vt=0)
    s = snap(m, enemy=(0.0, 0.0, 180.0))
    s["laser"] = None
    s["nav"] = NavMesh([(-500., 0., -500.), (500., 0., -500.), (500., 0., 1000.), (-500., 0., 1000.)],
                       [(0, 1, 2), (0, 2, 3)], [[], []])                 # no link: no straight floor segment
    s["player"]["pitch"] = 0.0
    act = bot.tick(s)
    assert "l1" in act["hold"] and bot.stats["phase"] == "clear_nearby"


def test_the_dot_on_another_majini_is_no_lost_sight_of_the_target(tmp_path):
    now = [10.0]
    m, bot = bot_at(tmp_path, now)
    s = snap(m, enemy=(0.0, 0.0, 700.0))
    s["enemies"].append({"slot": 1, "ptr": ENEMY + 0x40, "pos": (0.0, 0.0, 300.0), "hp": 800, "hp_max": 800})
    s["laser"] = {"from": (0.0, 149.0, 46.0), "at": (0.0, 110.0, 300.0)}   # on the one in front: short of the target
    p, tgt = s["player"], s["enemies"][0]
    for k in range(8):
        now[0] = 10.0 + k * 0.25
        assert not bot._lost_sight(s, p, tgt, now[0])
    assert bot.stats["unsighted"] == 0


def test_a_new_round_clears_last_rounds_aim_lines(tmp_path):
    now = [10.0]
    m, bot = bot_at(tmp_path, now)
    bot.stats.update(aim_guard="wild: yaw +49 pitch +4: face him, level the gun",
                     laserless_visibility="corridor only; projectile cover unconfirmed",
                     last_shot="miss: the dot beside him (aim)")
    bot.observe_round(snap(m), "playing", 10.0)
    assert not {"aim_guard", "laserless_visibility", "last_shot"} & set(bot.stats)


def test_the_ballistic_report_counts_shots_into_walls_and_the_floor():
    recs = [{"result": "miss", "dot_on": "wall", "state": "aim", "yaw_err": 9.0, "pitch_err": 1.0, "reach": "short"},
            {"result": "miss", "dot_on": "wall", "state": "aim", "yaw_err": 7.0, "pitch_err": 1.0, "reach": "short"},
            {"result": "miss", "dot_on": "floor", "state": "aim", "yaw_err": 2.0, "pitch_err": -20.0, "reach": "short"},
            {"result": "hit", "dot_on": "target", "state": "aim", "where": "body", "yaw_err": 0.5, "pitch_err": 0.0}]
    rep = B.report(recs)
    assert rep["walls_shot"] == 2 and rep["floor_shots"] == 1 and rep["by_dot_on"]["wall"]["shots"] == 2
    assert "into walls 2, floor 1" in rep["line"] and "What the dot was on" in rep["markdown"]
    assert any("dot on a wall" in a for a in rep["advice"])
    assert B.aim_state("aim by the camera: yaw +1.0 pitch -2.0 FIRE") == "estimate"


def test_every_decision_change_is_kept_with_its_reason(tmp_path):
    now = [10.0]
    m, bot = bot_at(tmp_path, now, aiming=False, act_vt=0)
    s = supported_laserless(snap(m, enemy=(300.0, 0.0, 0.0)))             # 90 deg off: the gun-down swing
    s["laser"] = None
    bot.tick(s)
    now[0] = 10.1
    s = supported_laserless(snap(m, enemy=(0.0, 0.0, 300.0)))             # straight ahead: the gun comes up
    s["laser"] = None
    bot.tick(s)
    decisions = bot.stats["look"]["decisions"]
    assert [d["decision"] for d in decisions[-2:]] == ["swing (gun down)", "raise the gun"]
    assert decisions[-1]["reason"].startswith(f"Majini {hex(ENEMY)} 3.0 m +0 deg")
    assert all(d["phase"] == "clear_nearby" for d in decisions[-2:])
    assert math.isclose(decisions[-1]["t"], 10.1)


def test_a_dropped_laser_read_guards_only_its_own_tick(tmp_path):
    """The driver drops a torn read from the snapshot (laser_dropped says why): that tick's aim says so (aim_guard
    "wild: ray dropped ..."), the next tick without a read does not carry it on."""
    now = [10.0]
    m, bot = bot_at(tmp_path, now)

    def frame(laser):
        s = snap(m, enemy=(0.0, 0.0, 300.0))
        s.update(ground_mines={}, laser=laser, player=dict(s["player"], pitch=0.0))
        return s
    bot.tick(frame({"from": (900.0, 149.0, 46.0), "at": (900.0, 110.0, 400.0)}))
    assert bot.stats["aim_guard"].startswith("wild: ray dropped (origin")
    now[0] = 10.05
    bot.tick(frame(None))
    assert "aim_guard" not in bot.stats and bot.stats["laser_rejected"] == 1
