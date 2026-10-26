"""Each Mercenaries round's route on a 2D map: where the time went, and whether that was a wall."""
import json

from gbox.mercs.round_map import RoundTrace
from gbox import re4_merc_bot as B


def test_most_of_a_round_against_a_wall_is_named_and_drawn(tmp_path):
    t = RoundTrace(tmp_path, "G4BE08", "r400", "a" * 32, 400.0)
    now = 0.0
    for i in range(20):                                    # a short run across the yard
        t.add(now, i * 300.0, 0.0); now += 0.3
    for _ in range(120):                                   # then 30 s running in place at x=6100
        t.add(now, 6100.0, 50.0); now += 0.25
    t.event(now, "stuck", 6100.0, 50.0, action="detour")
    s = t.finish(walked={(0, 0): 3, (15, 0): 9}, blocked={(16, 0): 2})
    top = s["hotspots"][0]
    assert top["cell"] == [15, 0] and top["share"] > 0.8 and top["touches_wall"] and not top["wall"]
    assert "against a learned wall" in s["verdict"] and s["stuck_events"] == 1
    js, sv = s["files"]
    assert json.loads(open(js).read())["route"] and "<svg" in open(sv).read()


def test_the_bot_traces_a_round_into_round_maps(tmp_path):
    bot = B.Bot(None, clock=lambda: 0.0, nav=False, learn_dir=tmp_path / "re4_learned")
    bot._round(0x400)
    bot.trace_start("b" * 32)
    for i in range(10):
        bot.trace.add(i * 0.3, i * 100.0, 0.0)
    bot.trace_finish()
    # RE5's layout since 2026-10-26: round_maps/<title>/<room>/ (the deployment: gbox-data/mercs/round_maps/G4BE08/r400/)
    assert bot.stats["last_round_map"].endswith(".svg") and (tmp_path / "round_maps" / "G4BE08" / "r400").is_dir()
    assert not (tmp_path / "round_maps" / "r400").exists()


def test_standing_on_a_planted_mine_is_found_with_its_phase_and_code(tmp_path):
    # operator 2026-10-24: "trace the round information to find out that he just planted a mine and then stood on it
    # and then also stood still for a period of time ... and be able to see the code that was being executed"
    t = RoundTrace(tmp_path, "BLUS30491", "Village", "c" * 32, 400.0,
                   code={"leave_proximity_bomb": "re5_ps3.py:3003 Bot._mine_retreat"})
    now = 0.0
    for i in range(12):
        t.add(now, i * 250.0, 0.0, state={"phase": "gather_time"}); now += 0.3
    for _ in range(40):                                           # 10 s on the bomb he just planted
        t.add(now, 3000.0, 20.0, state={"phase": "leave_proximity_bomb",
                                        "mine_retreat_status": "blocked: no measured escape"}, mines=[(3010.0, 0.0, 15.0)])
        now += 0.25
    s = t.finish()
    still = s["standstills"][0]
    assert still["phase"] == "leave_proximity_bomb" and still["on_mine"] and still["seconds"] >= 9
    assert still["code"] == "re5_ps3.py:3003 Bot._mine_retreat" and "blocked" in still["mine_retreat_status"]
    assert "ON A MINE" in s["verdict"] and s["time_by_phase"]["leave_proximity_bomb"] >= 9


def test_re5_bot_writes_a_round_map_with_code_locations(tmp_path):
    from gbox.mercs.titles import re5_ps3 as R
    bot = R.Bot(learn_dir=tmp_path / "lessons", clock=lambda: 0.0)
    m = __import__("gbox.mercs.round_map", fromlist=["code_map"]).code_map(R.PHASE_CODE, R.Bot, R.re5_combat.Combat)
    assert m["leave_proximity_bomb"].startswith("re5_ps3.py:") and "Bot._mine_retreat" in m["leave_proximity_bomb"]


def test_the_last_shots_carry_the_aim_the_gate_and_the_result():
    t = RoundTrace(None, "BLUS30491", "Village", "d" * 32, 400.0)
    now, shots = 0.0, 0
    for i in range(30):
        aim = "yaw +2.0 pitch -1.0 FIRE" if i % 3 else "yaw -24.0 pitch -18.0 swing"
        if i % 3 == 1:
            shots += 1
        t.add(now, 100.0 + i, 0.0, state={"shots": shots, "combat": aim, "fire_gate": "threat: blasting",
                                          "last_shot": "miss: the ray passed him" if i % 2 else "hit"})
        now += 0.3
    s = t.summary()
    assert len(s["last_shots"]) == 10 and s["last_shots"][-1]["combat"].startswith("yaw")
    assert all("aim_before" in x and x["fire_gate"] == "threat: blasting" for x in s["last_shots"])
