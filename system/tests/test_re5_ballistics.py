"""Ballistic reports and the aim calibration (operator 2026-10-26: "If they are shooting and missing then i want you
seeing why and how they missed so you can adjust the aimbot ... Every landed shot should better inform and train the
system on how to aim ... longshot foes from across the stage")."""
import json
import math
from pathlib import Path

import pytest

from gbox.mercs import ballistics as B
from gbox.mercs import round_map
from gbox.mercs.round_map import RoundTrace
from gbox.mercs.titles import re5_combat as C
from gbox.mercs.titles.re5_mines import GroundMines
from tests.test_re5_combat import ACT, ENEMY, LASER, PL, snap, world

AIM_LINE = "barry w0x12 body dot body yaw +1.0 pitch -0.5 rapid hold FIRE"


def seeded(tmp_path, cell, **values):
    """A learn dir whose calibration already holds this band (as rounds before would have left it)."""
    cal = B.Calibration(tmp_path)
    cal.d["cells"][cell] = {"yaw": 0.0, "pitch": 0.0, "rounds": 0, "shots": 0, "hits": 0, "recent": "", "hit_err": [],
                            **values}
    cal.dirty = True
    cal.save()
    return tmp_path


def with_weapon(m, item):
    m.put(PL + C.P_INV + 3 * C.INV_SLOT + C.INV_ID, ">I", 0x100 | item)
    return m


# --- the records ------------------------------------------------------------------------------------------------
def test_a_fake_tick_sequence_records_every_shot_with_the_aim_at_the_trigger_and_what_it_did(tmp_path):
    far = (0.0, 0.0, 800.0)                                          # 8 m ahead: no close-threat blast
    m = world(laser_dot=(0.0, 110.0, 800.0), enemy=far)              # the dot on his chest
    got = []
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    bot.shot_sink = got.append
    s = snap(m, enemy=far)
    assert "r1" in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    m.put(ACT, ">I", C.FIRE_VT)                                       # the game fires
    m.put(ACT + C.ACT_FRAMES, ">f", 1.0)
    bot.tick(s, s["player"], s["enemies"][0], 0.1)
    assert [r["result"] for r in bot.round_shots] == ["pending"] and not got
    hurt = snap(m, enemy=far, hp=600)                                 # his health falls 0.1 s later
    bot.tick(hurt, hurt["player"], hurt["enemies"][0], 0.2)
    hit = got[0]
    assert hit["result"] == "hit" and hit["tth"] == pytest.approx(0.1) and hit["t"] == pytest.approx(0.1)
    assert (hit["wid"], hit["character"], hit["weapon"], hit["family"]) == (0x12, "barry", "Samurai Edge", "handgun")
    assert (hit["dist"], hit["dy"], hit["zone"], hit["where"], hit["state"], hit["gate"]) == (800, 0, "body", "body", "aim", "on him")
    assert hit["fire"] is True and abs(hit["yaw_err"]) < 0.5 and abs(hit["pitch_err"]) < 0.5 and B.band(hit["dist"]) == "5-10"
    assert hit["aim"] == [0, 110, 800] and "headshot" not in hit
    m.put(LASER + C.LASER_DOT, ">3f", 70.0, 110.0, 800.0)             # the dot a hand beside him (5 deg)
    bot.tick(hurt, hurt["player"], hurt["enemies"][0], 0.3)
    m.put(ACT + C.ACT_FRAMES, ">f", 0.0)                              # the next shot leaves anyway
    bot.tick(hurt, hurt["player"], hurt["enemies"][0], 0.4)
    for k in range(10):                                               # nothing falls: a miss
        bot.tick(hurt, hurt["player"], hurt["enemies"][0], 0.5 + k * 0.05)
    miss = got[1]
    assert miss["result"] == "miss" and miss["where"] is None and miss["fire"] is False
    assert miss["yaw_err"] == pytest.approx(-5.3, abs=0.2) and miss["causes"][0] == "dot off him"
    assert miss["miss"].startswith("miss:") and miss["gate"] == "no line: hold fire"
    assert bot.round_shots[0] is not got[0]                           # the sink gets a copy


def test_a_shot_long_after_the_last_aim_decision_is_recorded_as_stale(tmp_path):
    bot = C.Combat(world(), {}, learn_dir=tmp_path, lessons=lambda row: None)
    bot.start_round(0.0)
    bot.character, bot.wid = "barry", 0x12
    bot.last_aim = {"at": 0.0, "state": "aim", "dist": 500, "yaw_err": 1.0, "pitch_err": 0.0}
    bot.last_dot = (None, ENEMY, None, None, 0.0)
    bot._on_shot(2.0)
    assert bot.round_shots[-1]["state"] == "stale" and "yaw_err" not in bot.round_shots[-1]


def test_unattributed_impacts_are_recorded_but_never_train_the_calibration(tmp_path):
    bot = C.Combat(world(), {}, learn_dir=tmp_path, lessons=lambda row: None)
    bot.start_round(0.0)
    bot.character, bot.wid = "barry", 0x12
    bot.shots.update([{"slot": 0, "ptr": ENEMY, "hp": 800}], 0.0)
    bot.last_aim = {"at": 0.05, "state": "aim", "dist": 600, "yaw_err": 0.5, "pitch_err": 0.0, "nom_yaw": -1.0,
                    "nom_pitch": 0.0, "gate": "on him"}
    bot.last_dot = ("body", ENEMY, None, None, 0.05)
    bot._on_shot(0.1)
    mines = GroundMines({123: {"detonating": True}})
    mines.verified = True
    bot._update_attribution({"ground_mines": mines}, 0, 0.2)
    bot._observe_impacts([{"slot": 0, "ptr": ENEMY, "hp": 600}], 0.2)
    assert bot.round_shots[0]["result"] == "unattributed" and "impact unattributed" in bot.round_shots[0]["miss"]
    assert bot.cal.d["cells"] == {}


# --- the report -------------------------------------------------------------------------------------------------
def rec(result, dist, **kw):
    return {"wid": 0x12, "weapon": "Samurai Edge", "character": "barry", "state": "aim", "zone": "body",
            "result": result, "dist": dist, **kw}


def test_the_report_counts_hit_rates_errors_miss_causes_longshots_and_time_to_hit():
    hawk = {"wid": 0x1A, "weapon": "Lightning Hawk"}
    recs = [rec("hit", 150, where="body", gate="on him", yaw_err=1.0, pitch_err=-1.0, tth=0.1),
            rec("hit", 150, where="body", gate="on him", yaw_err=3.0, pitch_err=1.0, tth=0.3),
            rec("miss", 300, gate="line to him", yaw_err=6.0, pitch_err=2.0),                     # dot off him
            rec("miss", 320, gate="line to him", yaw_err=-4.0, pitch_err=1.0),                    # dot off him
            rec("miss", 300, gate="threat: blasting", yaw_err=40.0, pitch_err=0.0),               # wild
            rec("hit", 1500, where="body", gate="on him", yaw_err=0.5, pitch_err=0.5, tth=0.2, **hawk),
            rec("miss", 2400, state="swing", facing=80.0, gate="no line: hold fire", **hawk),      # gun down, turning
            rec("hit", 3500, where="body", longshot=True, gate="on him", yaw_err=0.2, pitch_err=0.1, tth=0.25, **hawk),
            rec("miss", 800, turn=90.0, yaw_err=5.0, pitch_err=0.0, **hawk),                      # fired while turning
            rec("unattributed", 600)]
    rep = B.report(recs, meta={"room": "Village", "round_id": "r1"})
    assert (rep["shots"], rep["hits"], rep["misses"], rep["unattributed"], rep["hit_rate"]) == (10, 4, 5, 1, 0.444)
    bands = rep["by_band"]
    assert list(bands) == ["0-2", "2-5", "5-10", "10-20", "20+"]
    assert bands["0-2"] == {"shots": 2, "hits": 2, "misses": 0, "rate": 1.0}
    assert bands["2-5"]["misses"] == 3 and bands["2-5"]["rate"] == 0.0
    assert bands["5-10"] == {"shots": 2, "hits": 0, "misses": 1, "rate": 0.0}
    assert bands["20+"] == {"shots": 2, "hits": 1, "misses": 1, "rate": 0.5}
    assert rep["by_weapon"]["0x12 Samurai Edge"]["shots"] == 6 and rep["by_weapon"]["0x1a Lightning Hawk"]["hits"] == 2
    assert rep["by_dot"]["body"] == {"shots": 4, "hits": 4, "misses": 0, "rate": 1.0}
    assert rep["by_gate"]["on him"]["rate"] == 1.0 and rep["by_gate"]["line to him"]["rate"] == 0.0
    assert rep["by_zone"]["body"]["shots"] == 10 and rep["by_state"]["swing"]["misses"] == 1
    hits, misses = rep["error_deg"]["hits"], rep["error_deg"]["misses"]
    assert (hits["n"], hits["yaw_mean"], hits["yaw_median"], hits["pitch_median"]) == (4, 1.18, 0.75, 0.3)
    assert (misses["n"], misses["yaw_median"], misses["pitch_median"]) == (4, 5.5, 0.5)
    assert rep["miss_causes"][0] == ["dot off him", 2] and len(rep["miss_causes"]) == 3
    assert rep["miss_causes_all"] == {"dot off him": 2, "wild error": 1, "gun down / turning": 1, "fired while turning": 1}
    lo = rep["longshots"]
    assert (lo["shots"], lo["hits"], lo["longest_hit_m"], lo["beyond_engage_shots"], lo["beyond_engage_hits"]) == (3, 2, 35.0, 1, 1)
    assert rep["time_to_hit_s"]["median"] == pytest.approx(0.225) and rep["turning"]["shots_swinging"] == 1
    assert rep["line"].startswith("10 shots 4 hit 44% | 0-2m 2/2") and "miss: dot off him 2" in rep["line"]
    assert rep["markdown"].startswith("### Ballistics - Village - r1") and "| 2-5 m | 3 | 0 | 3 | 0% |" in rep["markdown"]
    assert any("dot off him" in a for a in rep["advice"])


def test_miss_causes_come_in_their_order_and_the_gun_down_turn_is_first():
    assert B.causes({"state": "swing", "facing": 119.0})[0] == "gun down / turning"
    assert B.causes({"state": "aim", "facing": 60.0, "yaw_err": 2.0, "pitch_err": 0.0})[0] == "gun down / turning"
    assert B.causes({"state": "aim", "turn": 120.0, "yaw_err": 2.0, "pitch_err": 0.0}) == ["fired while turning", "dot off him"]
    assert B.causes({"yaw_err": -55.0, "pitch_err": -56.0}) == ["wild error"]
    assert B.causes({"yaw_err": 1.0, "pitch_err": 0.0, "reach": "short"})[0] == "line blocked"
    assert B.causes({"yaw_err": 1.0, "pitch_err": 0.0, "dist": 2500, "rng": 800})[0] == "too far for the weapon"
    assert B.causes({"where": "body", "speed": 400.0}) == ["target moving fast", "dot on him (moved / late)"]
    assert B.causes({"state": "readying"}) == ["no ray at the trigger"]
    assert B.aim_state("laserless gun: lower weapon and turn toward target") == "swing"
    assert B.aim_state("turning toward a front candidate") == "swing"
    assert B.parse_combat(AIM_LINE) == {"state": "aim", "character": "barry", "zone": "body", "yaw_err": 1.0,
                                        "pitch_err": -0.5, "where": "body", "fire": True, "wid": 0x12}
    assert B.parse_combat("swinging round to him (gun down): +119 deg")["facing"] == 119.0


def test_the_round_map_counts_the_hits_he_took_while_turning_with_the_gun_down():
    # the coordinator 2026-10-26: "count how often attacks landed on the player while it was in that state"
    t = RoundTrace(None, "BLUS30491", "Prison", "e" * 32, 400.0)
    now, damage = 0.0, 0
    for i in range(40):
        swinging = 10 <= i < 20
        damage += i in (12, 15, 30)                                   # two hits while swinging, one while aiming
        t.add(now, 100.0, 0.0, state={"phase": "clear_nearby", "player_damage_events": damage,
                                      "combat": "swinging round to him (gun down): -71 deg" if swinging else AIM_LINE})
        now += 0.25
    turn = t.summary()["ballistics"]["turning"]
    assert (turn["hits_taken"], turn["hits_taken_swinging"]) == (3, 2)
    assert turn["swing_s"] == pytest.approx(2.5) and turn["swing_stalled_s"] == pytest.approx(2.25)   # -71 deg: not turning
    assert turn["fight_s"] == pytest.approx(9.75) and turn["swing_share"] == pytest.approx(0.256, abs=1e-3)


def test_a_round_map_without_records_still_gets_an_approximate_report_from_its_samples():
    states = [{"shots": "0", "hits": "0", "misses": "0", "combat": AIM_LINE, "fire_gate": "on him", "phase": "fight"},
              {"shots": "2", "hits": "0", "misses": "0", "combat": AIM_LINE, "fire_gate": "on him", "phase": "fight"},
              {"shots": "2", "hits": "1", "misses": "0"},
              {"shots": "3", "hits": "1", "misses": "1", "combat": "swinging round to him (gun down): +90 deg",
               "last_shot": "miss: the dot beside him (aim)"},
              {"shots": "3", "hits": "1", "misses": "2"}]
    samples = [(k * 0.25, 0.0, 0.0, 0.0) for k in range(5)]
    recs = B.records_from_trace(states, samples, 0.0)
    assert [r["result"] for r in recs] == ["hit", "miss", "miss"] and all(r["approx"] for r in recs)
    assert recs[0]["where"] == "body" and recs[0]["gate"] == "on him" and recs[0]["yaw_err"] == 1.0
    assert recs[2]["state"] == "swing" and B.causes(recs[2])[0] == "gun down / turning"
    rep = B.report([], states=states, samples=samples, started=0.0)
    assert rep["source"].startswith("state samples") and (rep["shots"], rep["hits"]) == (3, 1)
    lessons = [{"kind": "shot", "t": 0.3, "result": "headshot", "dot": "head", "reach": "beside", "dist_cm": 1200,
                "weapon": 0x1A, "character": "barry"},
               {"kind": "shot", "t": 0.8, "result": "miss: the ray passed him (aim)", "dot": None, "reach": "past",
                "dist_cm": 1800, "weapon": 0x1A, "character": "barry"},
               {"kind": "shot", "t": 99.0, "result": "hit"}]                                # another round
    joined = B.report_for_map({"states": states, "route": samples, "started": 0.0}, lessons)
    assert joined["source"].startswith("run lessons") and (joined["shots"], joined["hits"], joined["headshots"]) == (2, 1, 1)
    assert joined["longshots"]["longest_hit_m"] == 12.0


# --- the calibration --------------------------------------------------------------------------------------------
def steady_hit(dist, nom_yaw, nom_pitch, **kw):
    return {"character": "barry", "wid": 0x12, "dist": dist, "result": "hit", "state": "aim", "yaw_err": 0.5,
            "pitch_err": 0.5, "nom_yaw": nom_yaw, "nom_pitch": nom_pitch, **kw}


def test_the_correction_is_the_hits_centre_blended_over_rounds_bounded_and_kept_in_its_own_file(tmp_path):
    cal = B.Calibration(tmp_path)
    # three steady hits 2 deg left of and 1 deg under the nominal point (nominal error = want - have = -2 / +1)
    assert cal.learn([steady_hit(300, -2.0, 1.0)] * 3) == {"barry:0x12:2-5": (0.6, -0.3, 3)}   # EMA 0.3 of (+2, -1)
    cal.learn([steady_hit(300, -2.0, 1.0)] * 3)
    assert cal.correction("barry", 0x12, 300) == pytest.approx((1.02, -0.51))                 # 0.7 * 0.6 + 0.3 * 2
    for _ in range(40):
        cal.learn([steady_hit(300, -20.0, 20.0)] * 3)
        yaw, pitch = cal.correction("barry", 0x12, 300)
        assert abs(yaw) <= 3.0 and abs(pitch) <= 4.0                                         # the +-3 / +-4 deg bounds
    assert (yaw, pitch) == pytest.approx((3.0, -4.0), abs=0.002)
    yaw_near, pitch_near = yaw, pitch
    for _ in range(40):
        cal.learn([steady_hit(2500, -20.0, -20.0)] * 3)
    yaw, pitch = cal.correction("barry", 0x12, 2500)                                         # 20 m+: never off his body
    assert yaw == pytest.approx(math.degrees(math.atan2(36, 2000)), abs=2e-3)
    assert pitch == pytest.approx(math.degrees(math.atan2(50, 2000)), abs=2e-3)
    unsteady = [steady_hit(700, -2.0, 0.0)] * 2 + [steady_hit(700, -2.0, 0.0, turn=90.0),
                                                     steady_hit(700, -2.0, 0.0, state="swing"),
                                                     steady_hit(700, -2.0, 0.0, yaw_err=45.0),
                                                     dict(steady_hit(700, -2.0, 0.0), result="miss")]
    assert cal.learn(unsteady) == {} and cal.correction("barry", 0x12, 700) == (0.0, 0.0)    # two steady hits: nothing
    cal.save()
    saved = json.loads((tmp_path / B.CALIBRATION_FILE).read_text())
    assert saved["cells"]["barry:0x12:2-5"]["yaw"] == yaw_near and saved["cells"]["barry:0x12:2-5"]["rounds"] == 42
    assert not (tmp_path / C.TUNABLES_FILE).exists()
    assert B.Calibration(tmp_path).correction("barry", 0x12, 300) == (yaw_near, pitch_near)


def test_the_band_window_and_hit_errors_skip_the_blast_and_point_blank(tmp_path):
    cal = B.Calibration(tmp_path)
    for k in range(12):
        cal.observe(dict(steady_hit(600, 0.0, 0.0), yaw_err=0.3 * k, pitch_err=0.0, result="hit" if k % 4 else "miss"))
    cal.observe(dict(steady_hit(600, 0.0, 0.0), gate="threat: blasting", result="miss"))
    cal.observe(dict(steady_hit(600, 0.0, 0.0), pb=True, result="miss"))
    cell = cal.get("barry", 0x12, 600)
    assert cell["recent"] == "MHHHMHHHMHHH" and len(cell["hit_err"]) == 9
    assert cal.mode("barry", 0x12, 600) == ("normal", 0.75) and cal.p90("barry", 0x12, 600) is None   # 9 < P90_MIN
    cal.observe(dict(steady_hit(600, 0.0, 0.0), yaw_err=0.1, pitch_err=0.0))
    assert cal.p90("barry", 0x12, 600) == pytest.approx(3.0)


def test_end_of_round_learns_from_the_steady_hits_and_sets_the_one_line_summary(tmp_path):
    bot = C.Combat(world(), {}, learn_dir=tmp_path, lessons=lambda row: None)
    bot.start_round(0.0)
    bot.character, bot.wid = "barry", 0x12
    bot.shots.update([{"slot": 0, "ptr": ENEMY, "hp": 800}], 0.0)
    for k in range(3):
        t = 0.1 + k * 0.5
        bot.last_aim = {"at": t - 0.05, "state": "aim", "dist": 600, "dy": 0, "zone": "body", "yaw_err": 0.5,
                        "pitch_err": 0.2, "nom_yaw": -1.0, "nom_pitch": 0.5, "gate": "on him", "turn": 0.0, "facing": 0.0}
        bot.last_dot = ("body", ENEMY, None, None, t - 0.05)
        bot._on_shot(t)
        bot._observe_impacts([{"slot": 0, "ptr": ENEMY, "hp": 700 - 100 * k}], t + 0.1)
        bot._score(t + 0.1)
    bot.end_round(2.0)
    assert bot.stats["ballistics"].startswith("3 shots 3 hit 100% | 5-10m 3/3")
    assert bot.stats["aim_calibration_learned"].startswith("barry:0x12:5-10 +0.30/-0.15 deg (3 hits)")
    cell = json.loads((tmp_path / B.CALIBRATION_FILE).read_text())["cells"]["barry:0x12:5-10"]
    assert (cell["yaw"], cell["pitch"], cell["recent"], cell["hit_err"]) == (0.3, -0.15, "HHH", [0.54] * 3)
    assert set(json.loads((tmp_path / C.TUNABLES_FILE).read_text())) == {"weapons", "rounds"}   # left alone


# --- the gates --------------------------------------------------------------------------------------------------
def test_the_learned_correction_moves_the_aim_point_and_the_record_carries_it(tmp_path):
    far = (0.0, 0.0, 800.0)
    m = world(laser_dot=(0.0, 110.0, 800.0), enemy=far)              # dead centre on his chest
    bot = C.Combat(m, {}, learn_dir=seeded(tmp_path, "barry:0x12:5-10", yaw=2.0), lessons=lambda row: None)
    s = snap(m, enemy=far)
    keys = bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    assert "rleft" in keys and "r1" in keys                           # still on him: fire while steering the learned 2 deg
    assert bot.last_aim["corr"] == [2.0, 0.0] and bot.last_aim["yaw_err"] == pytest.approx(2.0, abs=0.05)
    assert bot.last_aim["nom_yaw"] == pytest.approx(0.0, abs=0.05)
    assert bot.stats["aim_calibration"].startswith("5-10 m: corr +2.0/+0.0 deg")


def test_a_band_hitting_under_half_of_its_last_shots_fires_only_with_the_dot_on_him(tmp_path):
    far = (0.0, 0.0, 800.0)
    beside = (45.0, 110.0, 800.0)                                     # 3.4 deg beside his chest: a line to him, not on him
    fresh = C.Combat(world(laser_dot=beside, enemy=far), {}, learn_dir=tmp_path / "fresh", lessons=lambda row: None)
    s = snap(fresh.m, enemy=far)
    assert "r1" in fresh.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]   # unlearned: fired down the line
    m = world(laser_dot=beside, enemy=far)
    bot = C.Combat(m, {}, learn_dir=seeded(tmp_path / "learned", "barry:0x12:5-10", recent="HMMMMMMMMMMM"),
                   lessons=lambda row: None)
    s = snap(m, enemy=far)
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    assert bot.stats["fire_gate"] == "calibration: 5-10 m hits 8%, the dot must be on him: hold fire"
    assert bot.last_aim["mode"] == "strict"
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 110.0, 800.0)             # the dot on him
    assert "r1" in bot.tick(s, s["player"], s["enemies"][0], 0.1)["hold"]


def test_a_band_hitting_nine_in_ten_fires_inside_a_slightly_wider_cone(tmp_path):
    far = (0.0, 0.0, 800.0)
    wide = (61.0, 110.0, 800.0)                                       # 4.6 deg beside him: past FIRE_CONE, inside 1.25x
    fresh = C.Combat(world(laser_dot=wide, enemy=far), {}, learn_dir=tmp_path / "fresh", lessons=lambda row: None)
    s = snap(fresh.m, enemy=far)
    assert "r1" not in fresh.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    m = world(laser_dot=wide, enemy=far)
    bot = C.Combat(m, {}, learn_dir=seeded(tmp_path / "learned", "barry:0x12:5-10", recent="H" * 19 + "M"),
                   lessons=lambda row: None)
    s = snap(m, enemy=far)
    assert "r1" in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    assert bot.stats["fire_gate"] == "line to him" and bot.last_aim["mode"] == "wide"


def test_the_p90_gate_holds_a_swing_then_fire_shot_but_never_point_blank_or_the_blast(tmp_path, monkeypatch):
    far = (0.0, 0.0, 800.0)
    learned = seeded(tmp_path, "barry:0x12:5-10", hit_err=[1.0] * 12)
    seeded(learned, "barry:0x12:0-2", hit_err=[1.0] * 12)
    seeded(learned, "barry:0x12:2-5", hit_err=[1.0] * 12)
    m = world(laser_dot=(39.0, 110.0, 800.0), enemy=far)             # 3 deg off him: inside the line-to cone
    bot = C.Combat(m, {}, learn_dir=learned, lessons=lambda row: None)
    s = snap(m, enemy=far)
    assert "r1" not in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    assert bot.stats["fire_gate"] == "calibration: error 3.0 > the hits' p90 1.0 deg: hold fire"
    monkeypatch.setattr(C, "POINT_BLANK", 900.0)                     # the same shot, counted point blank: it leaves
    bot = C.Combat(m, {}, learn_dir=learned, lessons=lambda row: None)
    assert "r1" in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    monkeypatch.undo()
    threat = (0.0, 0.0, 400.0)                                        # 4 m ahead: the blast
    m = world(laser_dot=(40.0, 110.0, 400.0), enemy=threat)
    bot = C.Combat(m, {}, learn_dir=learned, lessons=lambda row: None)
    s = snap(m, enemy=threat)
    assert "r1" in bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"] and bot.stats["fire_gate"] == "threat: blasting"


# --- longshots --------------------------------------------------------------------------------------------------
def test_a_magnum_that_showed_its_laser_aims_beyond_engage_and_fires_only_with_the_dot_on_him(tmp_path):
    far = (0.0, 0.0, 4000.0)                                          # 40 m: past ENGAGE_R, inside the magnum's reach
    m = with_weapon(world(aiming=False, act_vt=0, enemy=far), 0x1A)  # the Lightning Hawk, gun down, no laser seen yet
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m, enemy=far)
    s["laser"] = None
    assert bot.tick(s, s["player"], s["enemies"][0], 0.0) == {"hold": set()}
    assert bot.stats["combat"] == "target outside engagement range"
    bot.laser_weapons.add(0x1A)                                       # it showed its laser in an earlier fight
    assert bot.tick(s, s["player"], s["enemies"][0], 0.1)["hold"] == {"l1"}   # the gun comes up for the longshot
    m = with_weapon(world(laser_dot=(207.0, 110.0, 4000.0), enemy=far), 0x1A)   # up, 3 deg beside him: a line, no dot
    bot = C.Combat(m, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(m, enemy=far)
    keys = bot.tick(s, s["player"], s["enemies"][0], 0.0)["hold"]
    assert "l1" in keys and "r1" not in keys and keys & {"rleft", "rright"}
    assert bot.stats["fire_gate"] == "longshot: the dot must be on him: hold fire" and bot.last_aim["longshot"]
    m.put(LASER + C.LASER_DOT, ">3f", 0.0, 110.0, 4000.0)            # the dot on him: fire
    assert "r1" in bot.tick(s, s["player"], s["enemies"][0], 0.1)["hold"]
    m.put(ACT, ">I", C.FIRE_VT)
    m.put(ACT + C.ACT_FRAMES, ">f", 1.0)
    bot.tick(s, s["player"], s["enemies"][0], 0.2)
    assert bot.round_shots[-1]["longshot"] is True and bot.round_shots[-1]["dist"] == 4000
    pistol = world(laser_dot=(207.0, 110.0, 4000.0), enemy=far)      # a handgun never reaches past ENGAGE_R
    bot = C.Combat(pistol, {}, learn_dir=tmp_path, lessons=lambda row: None)
    s = snap(pistol, enemy=far)
    assert bot.tick(s, s["player"], s["enemies"][0], 0.0) == {"hold": set()}


def test_the_driver_raises_a_longshot_weapon_at_a_far_majini_in_view_once_it_showed_its_laser(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R
    far = (0.0, 0.0, 4000.0)
    m = with_weapon(world(aiming=False, act_vt=0, enemy=far), 0x1A)
    bot = R.Bot(m, clock=lambda: 10.0, learn_dir=tmp_path, lessons=lambda row: None)
    magnum = {"hand": True, "type": 1, "item": 0x1A, "id": 0x11A, "rounds": 6, "cap": 6, "slot": 3, "grid": 1}
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    assert bot._longshot_reach(magnum) == R.ENGAGE and not R.Bot._in_view(p, {"pos": far})
    s = snap(m, enemy=far)
    s.update(laser=None, inventory=[magnum])
    assert "l1" not in bot.tick(s).get("hold", set())                 # no laser seen: past ENGAGE he is not taken on
    bot.combat.laser_weapons.add(0x1A)
    assert bot._longshot_reach(magnum) == 5000.0 and R.Bot._in_view(p, {"pos": far}, 5000.0)
    assert bot._longshot_reach(dict(magnum, item=0x12)) == R.ENGAGE
    s = snap(m, enemy=far)
    s.update(laser=None, inventory=[magnum])
    assert "l1" in bot.tick(s)["hold"]                                # the gun comes up: its dot decides the shot
    assert bot.stats["combat"].startswith("readying")


# --- the round map ----------------------------------------------------------------------------------------------
def test_the_round_map_keeps_every_shot_and_writes_its_ballistic_report_beside_it(tmp_path, monkeypatch):
    t = RoundTrace(tmp_path, "BLUS30491", "Village", "f" * 32, 400.0)
    for i in range(8):
        t.add(100.0 + i * 0.25, 100.0 * i, 0.0, state={"phase": "fight", "combat": AIM_LINE, "shots": i})
    for k in range(25):
        t.shot(rec("hit" if k % 2 else "miss", 600, where="body" if k % 2 else None, yaw_err=1.0, pitch_err=0.0))
    s = t.finish()
    assert len(s["shots"]) == 25 and len(s["last_shots"]) <= round_map.SHOTS_KEPT
    assert len(s["files"]) == 2 and s["files"][1].endswith(".svg")
    report = json.loads(Path(s["ballistics_files"][0]).read_text())
    assert (report["shots"], report["hits"], report["by_band"]["5-10"]["shots"]) == (25, 12, 25)
    assert Path(s["ballistics_files"][1]).read_text(encoding="utf-8").startswith("### Ballistics - Village")
    assert "ballistics: 25 shots, 12 hits (48%)" in Path(s["files"][1]).read_text()
    assert json.loads(Path(s["files"][0]).read_text())["shots"][0]["wid"] == 0x12
    assert round_map.latest(tmp_path)["round_id"] == "f" * 32         # a report is not a round
    monkeypatch.setattr(round_map, "MAX_KEEP", 1)
    later = RoundTrace(tmp_path, "BLUS30491", "Village", "a" * 32, 400.0)
    for i in range(8):
        later.add(5000.0 + i * 0.25, 0.0, 0.0)
    later.finish()                                                    # the older round and its report are pruned
    assert sorted(f.name[16:] if f.is_file() else f.name + "/" for f in tmp_path.iterdir()) == [
        "aaaaaaaa.json", "aaaaaaaa.svg", "ballistics/"]                  # one .json per round in the folder
    assert sorted(f.name[16:] for f in (tmp_path / "ballistics").iterdir()) == ["aaaaaaaa.json", "aaaaaaaa.md"]


def test_the_driver_puts_every_resolved_shot_into_the_round_map_and_its_line_into_stats(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R
    bot = R.Bot(world(), clock=lambda: 10.0, learn_dir=tmp_path / "learned", lessons=lambda row: None)
    assert bot.combat.shot_sink == bot._trace_shot
    bot._trace = RoundTrace(tmp_path / "maps" / "stage", "BLUS30491", "stage", "c" * 32, 400.0)
    for i in range(6):
        bot._trace.add(i * 0.25, 0.0, 0.0, state={"phase": "fight", "combat": AIM_LINE})
    for k in range(4):
        bot.combat.shot_sink(rec("hit" if k else "miss", 1200, where="body" if k else None, yaw_err=0.5, pitch_err=0.0))
    bot.trace_finish()
    assert bot.stats["ballistics"].startswith("4 shots 3 hit 75% | 10-20m 3/4")
    report = Path(bot.stats["last_ballistics"])
    assert report.suffix == ".md" and report.parent == tmp_path / "maps" / "stage" / "ballistics" and report.is_file()
