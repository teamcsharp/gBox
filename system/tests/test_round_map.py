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
    assert bot.stats["last_round_map"].endswith(".svg") and (tmp_path / "round_maps" / "r400").is_dir()
