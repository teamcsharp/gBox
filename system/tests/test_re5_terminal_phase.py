"""Native quota completion and delayed result totals must close real round evidence."""
import json
import sqlite3
import struct

import pytest

from gbox.mercs import engine, lessons
from gbox.mercs.titles import re5_ps3 as R
from test_re5_mercs import GAMESYS, PLAYER, world


@pytest.mark.parametrize("phase,kills,expected",[(0,149,"playing"),(2,150,"playing"),(3,150,"results"),(99,150,"playing")])
def test_native_terminal_phase_not_kill_count_alone_ends_round_with_time_remaining(phase,kills,expected):
    m = world(timer=440.,kills=kills)
    m.u32(GAMESYS+R.GS_PHASE,phase)
    snap = R.snapshot(m)
    assert snap["mercenaries_phase"]==phase
    assert R.own_screen(snap)==expected
    assert R.RE5PS3(clock=lambda:0.).screen(m,snap)==expected


def test_terminal_score_rank_is_derived_and_only_updates_for_the_observed_round(tmp_path):
    bot = R.Bot(learn_dir=tmp_path)
    live = R.snapshot(world(timer=440.,kills=149,score=59900))
    bot.observe_round(live,"playing",1.)
    assert "completed_score_rank" not in bot.stats and "result_rank" not in bot.stats
    ended = live | {"timer":430.,"kills":150,"score":60100,"mercenaries_phase":3}
    bot.observe_round(ended,"results",2.)
    assert bot.stats["timer"]==430. and bot.stats["finished_naturally"] is True
    assert bot.stats["completed_score_rank"]=="S"
    bot.observe_round(ended | {"score":90100},"results",3.)
    assert bot.stats["completed_score_rank"]=="SS"
    bot.observe_round(ended | {"score":0,"kills":0},"results",4.)
    assert bot.stats["score"]==90100 and bot.stats["kills"]==150
    bot.observe_round(ended | {"score":999999,"player":ended["player"] | {"ptr":PLAYER+0x1000}},"results",5.)
    assert bot.stats["score"]==90100
    assert "result_rank" not in bot.stats and not bot.stats.get("rank_verified")


def test_native_results_wait_for_late_countup_before_database_finalization(tmp_path,monkeypatch):
    monkeypatch.setattr(lessons,"ROOT",tmp_path/"mercs"/"lessons")
    monkeypatch.setattr(R,"ROSTER",R.Roster())
    m = world(timer=440.,kills=149,score=59900)
    n,stats,sent = [0],{},[]
    def stopped():
        n[0]+=1
        if n[0]==3:
            m.u32(GAMESYS+R.GS_PHASE,3)
            m.put(GAMESYS+R.GS_KILLS,struct.pack(">i",150))
        if n[0] in (5,6):
            m.put(GAMESYS+R.GS_SCORE,struct.pack(">i",60100 if n[0]==5 else 90100))
        return n[0]>30
    clock = lambda:n[0]*.5
    bot,driver = R.Bot(stats=stats,learn_dir=tmp_path,clock=clock),R.RE5PS3(clock=clock)
    why = engine.play_round({"map_id":"BLUS30491"},m,sent.extend,stopped,stats,
                            brain=bot,driver=driver,clock=clock,sleep=lambda _:None)
    assert why=="round" and stats["score"]==90100 and stats["kills"]==150 and stats["timer"]==440.
    assert stats["completed_score_rank"]=="SS"
    assert stats["round_evidence_finalized"]==1
    with sqlite3.connect(tmp_path/"mercs/curriculum/BLUS30491/rounds.sqlite") as db:
        outcome,data = db.execute("select outcome,data from rounds").fetchone()
    observed = json.loads(data)
    assert outcome=="completed" and observed["score"]==90100 and observed["completed_score_rank"]=="SS"
    assert observed["result_rank_observed"] is None and observed["s_rank_verified"] is False
    assert not any(row["down"] for row in sent)  # no active enemy/movement or result-menu guesses


def test_result_settling_has_a_finite_bound_when_score_keeps_changing():
    driver = R.RE5PS3()
    for second in range(15):
        assert driver.result_ready({"player":{"ptr":PLAYER},"score":second,"kills":150},float(second)) is False
    assert driver.result_ready({"player":{"ptr":PLAYER},"score":15,"kills":150},15.) is True
