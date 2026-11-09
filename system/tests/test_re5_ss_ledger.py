"""The RE5 Switch No Mercy SS campaign ledger (gbox.mercs.ss_ledger): fragments stitched into game rounds, the rank from
the game's own No Mercy table, the board, the tuner's objective, the MercMode queue planner and the bot's round clock."""
import json
import sqlite3

import pytest

from gbox.mercs import ss_ledger as L

PA = "1636-2187-d3a75164ca01dcaa-e1163f7867c9"          # Public Assembly's navigation signature
MINES = "1152-1565-d7cf9f4b54c4a7fb-1624cb963fc4"


def row(rid, ts, outcome, stage=PA, character="unknown", **data):
    data.setdefault("source_session_id", "s1")
    return {"id": rid, "ts": ts, "stage": stage, "mode": "mercenaries", "character": character, "outcome": outcome,
            "data": data}


def test_the_names_are_the_drivers():
    from gbox.mercs.titles import re5_switch as R
    assert L.STAGE_NAMES == R.STAGE_NAMES and L.CHARACTERS == R.CHARACTERS
    assert sorted(L.SIGNATURES.values()) == sorted(R.STAGE_NAMES)        # one signature per stage


def test_the_no_mercy_rank_table():
    assert [L.rank_of(s) for s in (499_288, 400_000, 399_999, 335_260, 150_000, 60_000, 59_999, 30_000, 0)] == \
        ["SS", "SS", "S", "S", "A", "B", "C", "C", "D"]
    assert L.rank_of(None) is None and L.rank_of(True) is None and L.rank_of(-1) is None
    assert [L.rank_name(i) for i in (0, 1, 5, 6, -1, None)] == ["SS", "S", "D", None, None, None]
    assert L.better_rank("A", "SS") == "SS" and L.better_rank(None, "C") == "C" and L.better_rank("S", None) == "S"


def test_a_win_split_by_a_bot_reload_is_one_round_with_its_stage_character_and_time():
    # tonight's second win: a42dda7d (interrupted, 393 kills, the selects' character) then 5b2ac874 (the 400th kill)
    rows = [row("a" * 32, 10_000.0, "interrupted", character="Chris (BSAA)", kills=393, score=232_190,
                max_combo=40, timer=990.22, round_combo_breaks=30, explore_seconds=1114.6),
            row("b" * 32, 10_143.0, "completed", stage="unknown", kills=400, score=499_288, max_combo=40,
                timer=883.05, round_combo_breaks=4, explore_seconds=140.6)]
    rows[0]["data"]["stage"] = "Public Assembly"            # the selects confirmed it; the second fragment never saw them
    maps = {"a" * 32: {"round_id": "a" * 32, "play_s": 1114.6, "t0_kills": 0, "t0_timer": 120.0, "t1_timer": 991.2},
            "b" * 32: {"round_id": "b" * 32, "play_s": 140.6, "t0_kills": 393, "t0_timer": 988.85, "t1_timer": 878.2}}
    [r] = L.ledger(rows, maps)
    assert (r["stage"], r["character"], r["outcome"], r["kills"], r["score"], r["max_combo"]) == \
        ("Public Assembly", "Chris (BSAA)", "won", 400, 499_288, 40)
    assert r["fragments"] == ["a" * 32, "b" * 32] and r["combo_breaks"] == 34 and r["deaths"] == 0
    assert r["play_s"] == pytest.approx(1114.6 + (991.2 - 988.85) + 140.6, abs=0.1) and r["to_400_s"] == r["play_s"]
    assert (r["rank"], r["rank_source"]) == ("SS", "derived")


def test_stitching_without_the_run_maps_needs_a_short_gap():
    near = [row("a" * 32, 1000.0, "interrupted", kills=100, explore_seconds=300.0),
            row("b" * 32, 1100.0, "died", kills=150, explore_seconds=80.0)]          # started 20 s after a ended
    far = [row("c" * 32, 1000.0, "interrupted", kills=100, explore_seconds=300.0),
           row("d" * 32, 3000.0, "died", kills=150, explore_seconds=80.0)]           # half an hour later
    assert [len(r["fragments"]) for r in L.ledger(near)] == [2]
    assert [r["outcome"] for r in L.ledger(far)] == ["unfinished", "died"]
    other = [row("e" * 32, 1000.0, "interrupted", kills=100, explore_seconds=300.0),
             row("f" * 32, 1100.0, "died", kills=150, explore_seconds=80.0, source_session_id="s2")]
    assert len(L.ledger(other)) == 2                                                  # another session


def test_a_new_round_after_an_interrupted_one_is_not_joined_to_it():
    rows = [row("a" * 32, 1000.0, "interrupted", kills=50, ss_t0_kills=0, ss_round_key="k1"),
            row("b" * 32, 1060.0, "died", kills=80, ss_t0_kills=0, ss_round_key="k2")]
    assert [r["outcome"] for r in L.ledger(rows)] == ["unfinished", "died"]
    rows[1]["data"].update(ss_round_key="k1", ss_t0_kills=50)                         # the same player object
    assert [r["outcome"] for r in L.ledger(rows)] == ["died"]


def test_outcomes_ranks_and_the_bot_clock():
    rows = [row("a" * 32, 1000.0, "died", kills=135, score=78_500, ss_round_play_s=297.2),
            row("b" * 32, 2000.0, "completed", kills=393, score=253_980, ss_round_play_s=1411.0),
            row("c" * 32, 3000.0, "completed", kills=400, score=520_000, ss_round_play_s=1200.0, ss_kill400_s=1199.5,
                result_rank="SS", result_rank_verified=True),
            row("d" * 32, 4000.0, "lost", kills=398, score=228_070, explore_seconds=1387.0)]
    died, timeout, won, lost = L.ledger(rows)
    assert (died["outcome"], died["rank"], died["deaths"], died["play_s"]) == ("died", None, 1, 297.2)
    assert (timeout["outcome"], timeout["rank"], timeout["rank_source"]) == ("timeout", "A", "derived")
    assert (won["outcome"], won["rank"], won["rank_source"], won["to_400_s"], won["time_source"]) == \
        ("won", "SS", "ram", 1199.5, "bot clock")
    assert (lost["outcome"], lost["rank"]) == ("unfinished", None)


def test_the_board_covers_every_stage_and_character():
    rows = [row("a" * 32, 1000.0, "completed", character="Chris (BSAA)", kills=400, score=499_288,
                ss_round_play_s=1258.8),
            row("b" * 32, 2000.0, "completed", character="Chris (BSAA)", kills=400, score=563_822,
                ss_round_play_s=1255.0),
            row("c" * 32, 3000.0, "died", stage=MINES, character="Jill (BSAA)", kills=120, score=60_000,
                explore_seconds=300.0)]
    cells = L.board(L.ledger(rows))
    assert len([k for k in cells if k[0] in L.STAGE_NAMES]) == 8 * 14
    pa = cells[("Public Assembly", "Chris (BSAA)")]
    assert (pa["attempts"], pa["wins"], pa["best_rank"], pa["best_to_400_s"], pa["best_score"]) == \
        (2, 2, "SS", 1255.0, 563_822)
    mines = cells[("The Mines", "Jill (BSAA)")]
    assert (mines["attempts"], mines["deaths"], mines["best_rank"]) == (1, 1, None)
    text = L.report(L.ledger(rows), cells)
    assert "SS on 1 of 112" in text and "fastest 400: 20:55" in text and "Public Assembly" in text


def test_the_objective_orders_a_win_before_a_timeout_before_a_death():
    won = {"outcome": "won", "to_400_s": 1255.0, "play_s": 1255.0, "kills": 400, "combo_breaks": 21, "max_combo": 86}
    slow = dict(won, to_400_s=1500.0, play_s=1500.0)
    timeout = {"outcome": "timeout", "play_s": 1400.0, "kills": 393, "combo_breaks": 19, "max_combo": 78}
    died = {"outcome": "died", "play_s": 180.0, "kills": 100, "combo_breaks": 3, "max_combo": 40}
    died_fast = dict(died, play_s=60.0)
    costs = [L.round_cost(x) for x in (won, slow, timeout, died)]
    assert costs == sorted(costs) and L.round_cost(died_fast) < L.round_cost(died)
    assert L.round_cost(dict(won, combo_breaks=30)) > L.round_cost(won)            # a broken combo costs time
    assert L.round_cost(dict(won, max_combo=40)) > L.round_cost(won)               # a longer combo earns some back
    assert L.round_cost({"outcome": "unfinished", "play_s": 100.0, "kills": 50}) is None
    rounds = [dict(won, stage="Public Assembly", deaths=0), dict(died, stage="The Mines", deaths=1)]
    base = L.stage_baselines(rounds)
    assert set(base) == {"Public Assembly", "The Mines", "*"}
    same = L.objective(rounds, base)
    assert same["ratio"] == pytest.approx(1.0) and same["wins"] == 1 and same["deaths"] == 1
    faster = L.objective([dict(won, stage="Public Assembly", to_400_s=1000.0, deaths=0)], base)
    assert faster["ratio"] < 1.0 and list(faster["per_stage"]) == ["Public Assembly"]


def test_the_planner_fills_holes_first_and_mixes_stages_and_characters():
    rows = [row(f"{i:032x}", 1000.0 + i * 100, "died", character="Chris (BSAA)", kills=50, score=20_000,
                explore_seconds=120.0) for i in range(3)]
    rows.append(row("f" * 32, 9000.0, "completed", character="Sheva (BSAA)", kills=400, score=450_000,
                    ss_round_play_s=1500.0))
    cells = L.board(L.ledger(rows))
    plan = L.plan_queue(cells, build="re5_stock")
    assert len(plan) == L.QUEUE_MAX == 20
    assert all(e["title"] == "re5" and e["mode"] == "no_mercy" and e["mod"] == "re5_stock" for e in plan)
    pairs = [(L.STAGE_NAMES[e["stage"]], e["character"]) for e in plan]
    assert len(set(pairs)) == len(pairs)
    assert all(a[0] != b[0] and a[1] != b[1] for a, b in zip(pairs, pairs[1:]))
    assert ("Public Assembly", "Sheva (BSAA)") not in pairs                        # SS already: after every hole
    assert ("Public Assembly", "Chris (BSAA)") not in pairs                        # tried three times: after the never-tried
    assert len({s for s, _c in pairs}) == 8 and len({c for _s, c in pairs}) >= 10
    assert "mod" not in L.plan_queue(cells)[0] and len(L.plan_queue(cells, n=5)) == 5
    everything = {(s, c): dict(L._cell(s, c), attempts=1, best_rank="SS", best_to_400_s=1000.0 + i)
                  for i, (s, c) in enumerate((s, c) for s in L.STAGE_NAMES for c in L.CHARACTERS)}
    slowest = L.plan_queue(everything, n=1)[0]
    assert (L.STAGE_NAMES[slowest["stage"]], slowest["character"]) == (L.STAGE_NAMES[-1], L.CHARACTERS[-1])


def test_a_character_no_round_was_played_with_is_only_probed():
    # the select's second page has never been reached (re5-switch-cycle.json: only entries 0-9 counted): one entry
    # of each such character per plan, the rest from the characters the board knows
    cells = {(s, c): dict(L._cell(s, c), attempts=12, best_rank="A", best_score=200_000)
             for s in L.STAGE_NAMES for c in L.CHARACTERS[:10]}
    plan = L.plan_queue(cells)
    names = [e["character"] for e in plan]
    assert len(plan) == L.QUEUE_MAX and names[:4] and set(names[:4]) == set(L.CHARACTERS[10:])
    assert all(names.count(c) == 1 for c in L.CHARACTERS[10:])
    assert len(L.plan_queue({}, probes=3)) == L.QUEUE_MAX and len(L.plan_queue({})) == len(L.CHARACTERS)


def snap(ptr=0x5000, kills=0, timer=120.0, score=0, **extra):
    return {"module_base": 0x3CA89C3000, "player": {"ptr": ptr, "hp": 1000}, "kills": kills, "timer": timer,
            "score": score, **extra}


def test_the_round_clock_counts_play_not_pauses_and_carries_over_a_fragment():
    L._CLOCKS.clear()
    stats = {"round_evidence_id": "e1"}
    t, timer = 0.0, 120.0
    for _ in range(300):                                 # 10 s of ticks at 30 Hz, the clock running
        L.clock_tick(stats, snap(timer=timer, kills=5), "playing", t)
        t, timer = t + 1 / 30, timer - 1 / 30
    assert stats["ss_round_play_s"] == pytest.approx(10.0, abs=0.1) and stats["ss_t0_kills"] == 5
    L.clock_tick(stats, snap(timer=timer, kills=5), "playing", t + 30.0)      # 30 s frozen (a pause): nothing
    assert stats["ss_round_play_s"] == pytest.approx(10.0, abs=0.1)
    t += 30.0
    L.clock_tick(stats, snap(timer=timer - 4.0, kills=5), "playing", t + 5.0)  # a 5 s gap the clock fell 4 s over
    assert stats["ss_round_play_s"] == pytest.approx(14.0, abs=0.1)
    t, timer = t + 5.0, timer - 4.0
    new = {"round_evidence_id": "e2", "result_rank_ram": 3}                    # a bot reload: a new evidence row
    L.clock_tick(new, snap(timer=timer - 2.0, kills=393), "playing", t + 2.0)
    assert new["ss_round_play_s"] == pytest.approx(16.0, abs=0.1) and new["ss_fragments"] == 2
    assert new["ss_fragment_play_s"] == pytest.approx(2.0, abs=0.1) and "result_rank_ram" not in new
    assert new["ss_round_key"] == stats["ss_round_key"] and new["ss_kill400_s"] is None
    L.clock_tick(new, snap(timer=timer - 2.5, kills=400, score=499_288), "results", t + 2.6)
    assert new["ss_kill400_s"] == pytest.approx(16.0, abs=0.1)
    other = {"round_evidence_id": "e3"}                                        # the next round: its own clock
    L.clock_tick(other, snap(ptr=0x6000, kills=0), "playing", t + 60.0)
    assert other["ss_round_play_s"] == 0.0 and other["ss_round_key"] != new["ss_round_key"]
    assert L.clock_tick(None, {"player": None}, "playing", 0.0) is None


def test_the_results_rank_is_kept_only_when_the_ram_and_the_table_agree():
    stats = {}
    L.result_rank(stats, {"score": 499_288, "rank_index": 0, "no_mercy": True})
    assert (stats["result_rank"], stats["result_rank_verified"], stats["result_rank_derived"]) == ("SS", True, "SS")
    stats = {"result_rank": "SS"}
    L.result_rank(stats, {"score": 335_260, "rank_index": 0, "no_mercy": True})       # the table says S
    assert "result_rank" not in stats and stats["result_rank_verified"] is False
    assert (stats["result_rank_ram"], stats["result_rank_derived"]) == (0, "S")
    stats = {}
    L.result_rank(stats, {"score": 335_260, "rank_index": None})
    assert "result_rank" not in stats and stats["result_rank_derived"] == "S" and stats["result_rank_ram"] is None
    stats = {}
    L.result_rank(stats, {"score": 95_000, "rank_index": 0, "no_mercy": False})       # not No Mercy: no table here
    assert stats["result_rank_derived"] is None and "result_rank" not in stats


def test_the_cli_reads_the_notebook_read_only(tmp_path, capsys):
    db = tmp_path / "rounds.sqlite"
    with sqlite3.connect(db) as c:
        c.execute("create table rounds(id text primary key, ts real, stage text, mode text, character text, "
                  "outcome text, data text, vector text)")
        for r in (row("a" * 32, 1000.0, "completed", character="Chris (BSAA)", kills=400, score=499_288,
                      ss_round_play_s=1258.8),
                  row("b" * 32, 2000.0, "died", stage=MINES, character="Jill (BSAA)", kills=90, score=40_000,
                      explore_seconds=200.0)):
            c.execute("insert into rounds values(?,?,?,?,?,?,?,?)", (r["id"], r["ts"], r["stage"], r["mode"],
                                                                     r["character"], r["outcome"],
                                                                     json.dumps(r["data"]), "[]"))
    assert len(L.read_rows(db)) == 2 and L.read_rows(tmp_path / "missing.sqlite") == []
    assert L.main(["--db", str(db), "--maps", "none", "--rounds", "2", "--plan", "re5_stock"]) == 0
    out = capsys.readouterr().out
    assert "SS on 1 of 112" in out and "the last 2 game rounds" in out and '"mod": "re5_stock"' in out
    assert L.main(["--db", str(db), "--maps", "none", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["rounds"]) == 2 and any(c["best_rank"] == "SS" for c in data["board"])


def test_map_summaries_give_the_first_kills_and_both_clocks(tmp_path):
    folder = tmp_path / PA
    folder.mkdir()
    rec = {"format": "gbox.run_map/1", "round_id": "b" * 32,
           "route": [[100.0, 0, 0, 0], [100.2, 0, 0, 0], [110.0, 0, 0, 0], [110.2, 0, 0, 0]],
           "clock": [[0, 988.85, 232190, 0, 393], [3, 878.21, 234080, 0, 399]]}
    (folder / "20261109-161102-bbbbbbbb.json").write_text(json.dumps(rec))
    (folder / "20261109-161102-cccccccc.json").write_text("{broken")
    got = L.load_maps(tmp_path)
    assert list(got) == ["b" * 32]
    s = got["b" * 32]
    assert (s["t0_kills"], s["t0_timer"], s["t1_timer"]) == (393, 988.85, 878.21)
    assert s["play_s"] == pytest.approx(0.2 + L.MAP_GAP_CAP_S + 0.2)               # the 9.8 s hole counts 2.5 s
    assert L.load_maps(tmp_path, ids=["a" * 32]) == {}
