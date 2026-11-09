"""RE5 Switch No Mercy, the SS campaign's bot side (gbox.mercs.titles.re5_switch with gbox.mercs.ss_ledger): the results'
rank read from RAM, the round clock and the identity a mid-round fragment gets, the round's own stage for what the bot
learned, and the emergency flash (CRIT_FLASH) with the bomb guard's run out."""
import struct
from types import SimpleNamespace

import pytest

from gbox.mercs import interventions, ss_ledger
from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_mines as MN
from test_re5_switch import round_guest

PA = "1636-2187-d3a75164ca01dcaa-e1163f7867c9"


@pytest.fixture(autouse=True)
def _clean():
    ss_ledger._CLOCKS.clear()
    saved = dict(R._CYCLE)
    R._CYCLE.clear()
    yield
    R._CYCLE.clear()
    R._CYCLE.update(saved)
    ss_ledger._CLOCKS.clear()


def results_guest(score, rank, no_mercy=1):
    g = round_guest(phase=R.PHASE_OVER, player=False, units=((2, "uIdMerceEd00"),))
    main = R.u64(g, R.module_base(g) + R.S_MAIN)
    gs = R.u64(g, main + R.MAIN_GAMESYS)
    g.i32(gs + R.GS_SCORE, score)
    g.put(gs + R.GS_RANK, struct.pack("<ii", rank, 5000))
    g.put(gs + R.GS_NO_MERCY, bytes([no_mercy]))
    return g


def test_the_results_rank_comes_from_ram_and_is_kept_when_the_score_agrees():
    g = results_guest(499_288, 0)
    s = R.snapshot(g)
    assert (s["rank_index"], s["rank_points"], s["no_mercy"]) == (0, 5000, True)
    d = R.RE5Switch()
    d.stats = {}
    assert d.screen(g, None) == "results"
    assert (d.stats["result_rank"], d.stats["result_rank_verified"], d.stats["result_rank_ram"]) == ("SS", True, 0)
    bad = results_guest(335_260, 0)                                    # RAM says SS, the No Mercy table says S
    d.stats = {}
    d.screen(bad, None)
    assert "result_rank" not in d.stats and d.stats["result_rank_derived"] == "S"
    assert R.snapshot(round_guest()).get("rank_index") is None          # playing: not read


def test_a_playing_tick_runs_the_rounds_clock_into_the_stats():
    clock = [100.0]
    d = R.RE5Switch(clock=lambda: clock[0])
    d.stats = {"round_evidence_id": "e1"}
    g = round_guest(timer=97.5)
    d.screen(g, None)
    clock[0] = 100.5
    d.screen(g, None)
    assert d.stats["ss_round_play_s"] == pytest.approx(0.5) and d.stats["ss_t0_kills"] == 9
    assert d.stats["ss_round_key"] and d.stats["ss_fragments"] == 1


def test_a_fragment_that_starts_mid_round_names_its_character_and_stage():
    g = round_guest()
    d = R.RE5Switch()
    d.stats = {}
    c = R.StageCycle(path=None)
    c.last = (0, 0)                                                     # the cycle's last start: PA, Chris (BSAA)
    R._CYCLE["c"] = c
    snap = dict(R.snapshot(g), nav=SimpleNamespace(learning_sig=PA))
    d._identity(g, snap)
    assert (d.stats["stage"], d.stats["ss_stage"], d.stats["ss_stage_source"]) == \
        ("Public Assembly", "Public Assembly", "navigation signature")
    assert d.stats["character"] == "Chris (BSAA)" and "cycle" in d.stats["ss_character_source"]
    assert d.stats["player_class"] == "uPl00ChrisNormal"
    # the cycle's last start was Sheva: the player object is Chris - the class names the character, not the cycle
    d.stats, c.last = {}, (0, 3)
    d._player_class = (None, None)
    d._identity(g, snap)
    assert d.stats["character"] == "Chris" and d.stats["ss_character_source"].startswith("player class")
    # a character the selects confirmed is never replaced; a stage left over from another round is
    d.stats = {"character": "Chris (Safari)", "stage": "Village"}
    d._identity(g, snap)
    assert d.stats["character"] == "Chris (Safari)" and d.stats["stage"] == "Public Assembly"
    assert d.stats["ss_character_check"] == "class agrees"


def test_the_bots_learning_is_the_stage_being_played_not_the_next_target(monkeypatch):
    seen = []
    monkeypatch.setattr(R.tuning, "apply", lambda title, stage, stats=None, base=None: seen.append(stage) or {})
    monkeypatch.setattr(R, "stage_target", lambda m=None: 6)              # the cycle has drawn the next one: Ship Deck
    b = R.Bot(stats={"ss_stage": "Village"}, clock=lambda: 0.0)
    b._new_round(0.0)
    assert seen == ["Village"] and b._nav.grid.stage == R.STAGE_KEY.format("Village") == "Village#round"
    b._stage_sync()
    assert seen == ["Village"]                                           # nothing changed: no resync
    b.stats["ss_stage"] = "Prison"                                       # the signature corrected it
    b._stage_sync()
    assert seen == ["Village", "Prison"] and b.stats["stage_learning_resync"] == 1
    b2 = R.Bot(stats={}, clock=lambda: 0.0)
    b2._new_round(0.0)
    assert seen[-1] is None and b2._nav.grid.stage == "unknown#round"     # unknown: only the pooled values
    monkeypatch.setitem(R.SELECTION, "stage", 1)                          # the operator pinned The Mines
    b3 = R.Bot(stats={}, clock=lambda: 0.0)
    b3._new_round(0.0)
    assert seen[-1] == "The Mines"                                       # nothing read yet: the pin
    b4 = R.Bot(stats={"ss_stage": "Prison"}, clock=lambda: 0.0)
    b4._new_round(0.0)
    assert seen[-1] == "Prison"                                          # what the round is played on wins


def enemies(*dists):
    return [{"ptr": 10 + i, "hp": 800, "pos": (d, 0.0, 0.0)} for i, d in enumerate(dists)]


def flash_bot(monkeypatch, confirm=True):
    calls = []
    monkeypatch.setattr(interventions, "native_controller", lambda ad: SimpleNamespace(
        flash=lambda: calls.append(1) or {"state": "confirmed" if confirm else "refused"}))
    monkeypatch.setattr(R.threading, "Thread", lambda **kw: SimpleNamespace(start=kw["target"]))
    b = R.Bot(stats={}, clock=lambda: 0.0)
    b._m = SimpleNamespace(adapter=object())
    b.mines = MN.Mines(b.stats)
    return b, calls


def snap(hp=1000, motion=0, near=()):
    return {"mercenaries_phase": R.PHASE_PLAYING, "enemies": enemies(*near),
            "player": {"hp": hp, "hp_max": 1000, "pos": (0.0, 0.0, 0.0), "motion": motion}}


def test_the_emergency_flash_when_held_or_low_in_a_crowd(monkeypatch):
    b, calls = flash_bot(monkeypatch)
    b._critical_flash(snap(motion=106, near=(10.0, 150.0)), 1.0)       # held, and one more within 3 m
    assert len(calls) == 1 and b.stats["crit_flashes"] == 1 and "held" in b.stats["crit_flash_reason"]
    b._critical_flash(snap(motion=106, near=(10.0, 150.0)), 1.1)       # the confirmation: the guard's FLASH_S
    assert b.mines.flash_until == pytest.approx(1.0 + MN.FLASH_S)
    b._critical_flash(snap(motion=106, near=(10.0, 150.0)), 2.0)       # within CRIT_FLASH_GAP_S: no other
    assert len(calls) == 1
    b._critical_flash(snap(hp=250, near=(100.0, 250.0)), 5.5)          # a quarter of his health, two within 3 m
    assert len(calls) == 2 and "health" in b.stats["crit_flash_reason"]
    b._critical_flash(snap(hp=R.DYING_HP, near=(10.0, 100.0)), 20.0)   # dying: the controller refuses it
    b._critical_flash(snap(hp=900, near=(100.0, 250.0)), 30.0)         # healthy and free: the fight's own business
    b._critical_flash(snap(motion=106, near=(10.0,)), 40.0)            # held by one with nobody else near
    assert len(calls) == 2 and b.stats["crit_flash_requests"] == 2
    b.mines.close_in_blast_at = 50.0                                   # his bomb guard gave the run up just now
    b._critical_flash(snap(hp=900, near=(200.0,)), 50.0)
    assert len(calls) == 3 and "bomb" in b.stats["crit_flash_reason"]
    for k in R.CRIT_FLASH_COUNTERS:
        assert k in R.RE5Switch.round_counters


def test_an_unconfirmed_flash_gives_the_guard_nothing(monkeypatch):
    b, calls = flash_bot(monkeypatch, confirm=False)
    b._critical_flash(snap(motion=106, near=(10.0, 150.0)), 1.0)
    b._critical_flash(snap(motion=106, near=(10.0, 150.0)), 1.2)
    b._critical_flash(snap(motion=106, near=(10.0, 150.0)), 3.0)
    assert len(calls) == 1 and b.stats["crit_flashes"] == 0 and b.mines.flash_until < 0


def test_with_the_crowd_reeling_from_his_flash_he_runs_out_of_his_own_blast():
    from test_re5_switch_mines import p, snap as msnap
    m = MN.Mines({})
    m.new_round(0.0)
    bomb = {"ptr": 0x77, "pos": (0.0, 0.0, 300.0)}
    m.bombs = {0x77: bomb["pos"]}
    m.last_pos = (0.0, 0.0, -2000.0)
    live = [{"ptr": 10, "pos": (200.0, 0.0, 100.0), "hp": 800}]          # 2.2 m from him, in the blast
    assert m.tick(p(), msnap(ground=[bomb]), live, 1.0) is None          # no flash: the gun up, as before
    assert m.close_in_blast_at == 1.0
    m.flash_until = 4.5                                                 # a confirmed flash: they reel
    act = m.tick(p(), msnap(ground=[bomb]), live, 1.2)
    assert act is not None and act["hold"][:2] == MN.RUN
    assert m.stats["mine_status"] != "in the blast and a close Majini first: the gun up"
