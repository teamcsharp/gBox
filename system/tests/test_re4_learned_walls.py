"""RE4 Mercenaries: the learned walls as an obstruction database (operator 2026-10-24: "map the world like a Roomba").
A wall he runs into is learned at the right cell (never his own), honoured by every plan - the disc's map included -
and explained (stats stuck_reason, r<room>-stuck.jsonl)."""
import json
import math

from gbox import re4_merc_bot as B
from tests.test_re4_merc_bot import FakeNav, PL, facing, item, turn_done, world


def stuck_until(bot, m, now, events, t_max=8.0):
    """Tick with Leon never moving (his turns on the spot do turn him) until stats["stuck_events"] reaches events; the
    acts, in order."""
    acts, t = [], 0
    while bot.stats["stuck_events"] < events and t < t_max * 10:
        t += 1
        now[0] = t * 0.1
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        acts.append(bot.tick(B.snapshot(m)))
        turn_done(bot, m, acts[-1])
    return acts


def test_stuck_with_the_disc_map_learns_the_wall_and_the_next_plan_goes_round_it(tmp_path):
    now = [0.0]
    m = world([], room=0x400, leon=(100.0, 7.0, 200.0), timer_s=100.0)
    bonus = item("time_bonus", 0.0, 5000.0)                               # its stand point: (0, 4700), straight up +z
    bot = B.Bot(m, clock=lambda: now[0], nav=FakeNav([bonus]), learn_dir=tmp_path)
    facing(m, 0.0)
    acts = stuck_until(bot, m, now, 1)
    assert acts[-1] == {"tap": "a"} and bot.stats["stuck_events"] == 1    # the first stuck: JUMP OVER
    lm = bot.learned
    assert lm.wall((0, 1)) and (0, 0) not in lm.blocked                   # the cell ahead is wall; his own never is
    assert bot.stats["replans"] == 1 and bot.stats["wall_detours"] >= 1   # the disc map's path went round it
    way = bot.goal["path"]
    assert len(way) > 1 and way[-1] == (0.0, 4700.0, None)                # the stand point kept, corners before it
    assert lm.crosses((100.0, 200.0), way[0][:2]) is None                 # the first leg clears the learned wall
    assert all(not lm.wall(lm.cell(w[0], w[1])) for w in way[:-1])
    acts = stuck_until(bot, m, now, 2)
    assert bot.stats["stuck_events"] == 2 and bot.stats["detours"] == 1   # still blocked: the detour
    assert any({"up", "b"} <= a.get("hold", set()) and ({"left", "right"} & a["hold"]) for a in acts[:-1]), \
        "after the replan he steers to the corner, not straight into the wall"
    # (a turn on the spot is never a stuck: the second one is a run that did not move, wherever it pointed) the first
    # wall is kept, and neither stuck marked the cell he stands on
    assert lm.wall((0, 1)) and len(way) > 1 and (0, 0) not in lm.blocked
    second = bot.stuck_log[1]
    assert second["cells"] and [0, 0] not in second["cells"]
    r = bot.stats["stuck_reason"]
    assert f"cell {tuple(second['cells'][0])}" in r and "room r400" in r and f"heading {second['heading_deg']}" in r \
        and "detour" in r and "replanned" in r
    assert bot.stats["learned_map"].endswith("r400.json") and bot.stats["learned_floor_cells"] >= 1
    assert len(bot.stuck_log) == 2 and bot.stuck_log[0]["action"] == "vault" and bot.stuck_log[1]["action"] == "detour"
    bot.save()
    lines = (tmp_path / "r400-stuck.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["cell"] == [0, 1] and first["room"] == "r400" and first["heading_deg"] == 0 and first["pos"] == [100, 7, 200]
    assert first["goal"] == [0, 4700] and first["replanned"] >= 2 and first["action"] == "vault"
    bot.save()                                                            # nothing new: nothing appended twice
    assert len((tmp_path / "r400-stuck.jsonl").read_text().splitlines()) == 2
    assert B.LearnedMap(tmp_path / "r400.json").blocked == lm.blocked      # the next round starts with the wall


def test_the_cell_he_stands_on_is_never_a_wall(tmp_path):
    bot = B.Bot(world([]), nav=False, learn_dir=tmp_path)
    bot._round(0x400)
    cases = [((10.0, 0.0, 10.0), math.pi / 2, [(1, 0)]),                  # facing +x at the near edge: the cell in front
             ((390.0, 0.0, 390.0), math.pi, [(0, -1)]),                   # facing -z: half a cell ahead is still his own
             ((200.0, 0.0, 200.0), math.pi / 4, [(1, 1)]),                # a diagonal
             ((200.0, 0.0, 390.0), 0.0, [(0, 1)])]                        # ahead and in front agree: one cell, once
    for pos, rot, want in cases:
        bot.learned.blocked.clear()
        assert bot._learn_wall({"pos": pos, "rot": rot}) == want
        assert (0, 0) not in bot.learned.blocked and all(bot.learned.blocked[k] == 1 for k in want)
    assert bot._new_walls == 4


def test_a_straight_run_honours_a_learned_wall(tmp_path):
    now = [0.0]
    bot = B.Bot(world([]), clock=lambda: now[0], nav=False, learn_dir=tmp_path)
    bot._round(0x400)
    lm = bot.learned
    assert lm.cells_between((100.0, 200.0), (100.0, 2200.0)) == [(0, j) for j in range(6)]
    for _ in range(2):
        lm.block_cell((0, 1))
    assert lm.crosses((100.0, 200.0), (100.0, 2200.0)) == (0, 1)
    assert lm.crosses((100.0, 200.0), (100.0, 600.0)) is None             # the goal's own cell is not in the way
    assert lm.crosses((100.0, 200.0), (2100.0, 200.0)) is None
    p = {"pos": (100.0, 0.0, 200.0), "rot": 0.0}
    act = bot._go(p, (100.0, 2200.0), now[0])                             # a Ganado behind the learned wall
    assert {"up", "b"} <= act["hold"] and ({"left", "right"} & act["hold"]), act
    assert bot.stats["wall_detours"] == 1 and bot._detour is not None
    assert bot._go(p, (100.0, 2200.0), now[0])["hold"] == act["hold"]     # the detour is kept, not planned again
    assert bot.stats["wall_detours"] == 1
    # a clear line, 2 m away at 90 degrees: inside his turning circle, so he turns on the spot first (no orbit)
    assert bot._go(p, (2100.0, 200.0), now[0]) == {"hold": {"left"}} and bot._detour is None
    assert bot.stats["wall_detours"] == 1                                 # (+x is +heading: the stick's left)


def test_the_learned_map_is_saved_every_few_new_walls(tmp_path):
    now = [0.0]
    m = world([], room=0x400, leon=(100.0, 7.0, 200.0), timer_s=100.0)
    bot = B.Bot(m, clock=lambda: now[0], nav=False, learn_dir=tmp_path)
    t, seen = 0, -1
    while bot.stats["learned_walls"] < B.WALLS_PER_SAVE:
        t += 1
        now[0] = t * 0.1
        if bot.stats["stuck_events"] != seen:                             # a new direction after every stuck
            seen = bot.stats["stuck_events"]
            facing(m, 0.9 * seen)
        m.put(B.MERC_TIMER, ">I", int((100 - now[0]) * 30))
        turn_done(bot, m, bot.tick(B.snapshot(m)))                        # (his turns on the spot do turn him)
        assert t < 300
    assert (tmp_path / "r400.json").is_file() and bot._new_walls == 0     # saved by the stuck itself, not save()
    assert (tmp_path / "r400-stuck.jsonl").is_file()
    saved = B.LearnedMap(tmp_path / "r400.json")
    assert len(saved.blocked) >= B.WALLS_PER_SAVE and (0, 0) not in saved.blocked


def test_the_stuck_log_is_capped_and_the_count_is_not():
    bot = B.Bot(world([]), nav=False)
    bot._round(0x400)
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    for i in range(B.STUCK_LOG_MAX + 5):
        bot._stuck_event(p, float(i), (0.0, 1000.0), [(0, 1)], "detour", 3)
    assert len(bot.stuck_log) == B.STUCK_LOG_MAX and bot.stats["stuck_events"] == B.STUCK_LOG_MAX + 5
    assert bot.stuck_log[0]["at"] == 5.0
    assert bot.stats["stuck_reason"] == "wall learned at cell (0, 1) room r400 heading 0°: detour, replanned 3 waypoints"
    bot.save()                                                            # no learn_dir: nothing to write, nothing kept
    assert bot._stuck_pending == []
