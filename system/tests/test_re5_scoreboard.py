from gbox.mercs.titles import re5_scoreboard as sb


def row(score, stage="1638-2187-abc-def", hg=9, end="results", **kw):
    d = {"stage": stage, "hourglasses": hg, "end_reason": end, "score": score, "character": "Chris",
         "idle_s": 60.0, "wall_s": 40.0, "bonus_s": 0.0, "idle_causes": {}}
    d.update(kw)
    return d


def test_rank_thresholds():
    assert sb.rank_of(59999) == "A" and sb.rank_of(60000) == "S" and sb.rank_of(90000) == "SS"
    assert sb.rank_of(5) == "D" and sb.rank_of(None) is None


def test_groups_by_stage_and_counts_incomplete():
    rows = [row(10000), row(40450, bonus_s=239.0), row(0, end="lost (emulator gone)"),
            row(65000, stage="9999-1111-x", hg=6)]
    s = sb.summarize(rows)
    assert set(s) == {"1638-2187/9", "9999-1111/6"}
    a = s["1638-2187/9"]
    assert (a["rounds"], a["incomplete"], a["best"], a["best_rank"], a["gap_to_s"], a["bonus_rounds"]) == (2, 1, 40450, "A", 19550, 1)
    assert a["median"] == 25225 and a["s_rounds"] == 0
    assert s["9999-1111/6"]["s_rounds"] == 1 and s["9999-1111/6"]["gap_to_s"] == 0


def test_idle_cause_aggregation_drops_per_round_noise():
    r1 = row(1, idle_causes={"gather_time | vt0x1 w0x16 leg  | front candidate; visibility unconfirmed": 20.0,
                             "gather_time | barry w0x1a | front candidate; visibility unconfirmed": 4.0,
                             "clear_nearby | x | nearest immediate threat; acquiring clear shot": 6.0})
    e = sb.summarize([r1])["1638-2187/9"]
    assert e["top_idle_causes"][0] == ("gather_time: front candidate; visibility unconfirmed", 24.0)


def test_render_reports_unmeasured_stages_and_bad_lines():
    rows = sb.load_rounds(["", "not json", '{"stage": "1-2-3", "hourglasses": 9, "end_reason": "results", "score": 7}', "[1]"])
    assert len(rows) == 1
    txt = sb.render(sb.summarize(rows))
    assert "Stages measured: 1 of 8" in txt and "7 Reunion stage(s) have no measured round" in txt
