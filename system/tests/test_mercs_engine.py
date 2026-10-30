"""The Mercenaries engine (gbox/mercs): the vocabulary on RE4's map, the world read, threats from signatures, prompts,
lessons, and play_round over the RE4 driver on a built RAM image."""
import math
import struct

import pytest

from gbox import re4_merc_bot as B
from gbox.mercs import aim, engine, lessons, reactions, threat, vocab, world
from gbox.mercs.titles import re4_gc


class FakeMem:
    def __init__(self):
        self.b = bytearray(0x1800000)

    def rd(self, a, n):
        o = a - 0x80000000
        return bytes(self.b[o:o + n])

    read = rd

    def put(self, a, fmt, *v):
        o = a - 0x80000000
        struct.pack_into(fmt, self.b, o, *v)


PG, PL, EM, STRIDE = 0x80300000, 0x81000000, 0x81000000, 0xDE0


def re4(enemies=(), room=0x400, timer_s=100.0, hp=1000, leon=(0.0, 0.0, 0.0), rot=0.0, leon_r=(0, 0, 0, 0)):
    m = FakeMem()
    m.b[:6] = b"G4BE08"
    m.put(B.P_GLOBAL, ">I", PG)
    m.put(PG + 0x20, ">4B", 3, 0, 0, 0)
    m.put(PG + B.G_ROOM, ">H", room)
    m.put(PG + B.G_HP, ">h", hp)
    m.put(B.P_PLAYER, ">I", PL)
    m.put(PL + 0x94, ">3f", *leon)
    m.put(PL + 0xA4, ">f", rot)
    m.put(PL + 0xFC, ">4B", *leon_r)
    m.put(B.EMMGR, ">3I", EM, len(enemies) + 1, STRIDE)
    m.put(EM, ">I", 0x601)
    for k, (pos, r) in enumerate(enemies, start=1):
        o = EM + k * STRIDE
        m.put(o, ">I", 0x601)
        m.put(o + 0x94, ">3f", *pos)
        m.put(o + 0x320, ">hh", 1000, 1000)
        m.put(o + 0x398, ">B", 3)
        m.put(o + 0xFC, ">4B", *r)
        m.put(o + 0x100, ">B", 0x16)
    m.put(B.MERC_TIMER, ">I", int(timer_s * 30))
    return m


def test_re4_fills_the_vocabulary():
    prof = vocab.profile("G4BE08")
    assert prof.field("projectiles") == "thrown" and prof.field("screen") == "driver"
    assert vocab.check(prof) == []
    assert prof.aim["gun_gap_s"] == pytest.approx(1.167) and prof.units_per_m == 1000


def test_the_world_carries_each_enemys_attack_signature():
    m = re4([((0.0, 0.0, 1500.0), (1, 0x26, 1, 0)), ((800.0, 0.0, 0.0), (3, 1, 0, 0)), ((0.0, 0.0, 4000.0), (1, 0x03, 0, 0))])
    prof = vocab.profile("G4BE08")
    w = world.read(prof, m, driver=re4_gc.DRIVER(), now=1.0)
    by = {e.id: e for e in w.enemies}
    assert by[1].sig["attack"] == "melee" and by[1].sig["lead_s"] == 0.5
    assert "dying" in by[2].tags and by[2].dying and by[3].sig is None and "acting" in by[3].tags
    assert w.screen == "playing" and w.timer == pytest.approx(100.0) and w.player.pos == (0.0, 0.0, 0.0)


def test_the_threat_engine_ranks_by_signature_and_skips_the_dying():
    m = re4([((0.0, 0.0, 1500.0), (1, 0x26, 1, 0)), ((300.0, 0.0, 300.0), (3, 1, 0, 0)), ((0.0, 0.0, 900.0), (1, 0x03, 0, 0))])
    w = world.read(vocab.profile("G4BE08"), m, driver=re4_gc.DRIVER(), now=0.0)
    te = threat.ThreatEngine()
    out = te.update(w.player, w.enemies, w.projectiles, 0.0)
    assert [t.slot for t in out] == [1, 3] and out[0].kind == "melee" and out[0].eta == pytest.approx(0.5)
    later = te.update(w.player, w.enemies, w.projectiles, 0.3)
    assert later[0].eta == pytest.approx(0.2)                           # lead_s minus the time in the swing


def test_prompts_burst_then_rest_and_wait_while_an_attack_lands():
    stats = {}
    shown = {"b": "a"}
    pp = reactions.PromptPresser(source=lambda: shown["b"], stats=stats)
    presses = [t for t in [x * 0.1 for x in range(40)] if pp.step(t)]
    assert presses[:3] == pytest.approx([0.0, 0.6, 1.2]) and stats["prompt_presses"] == 3   # then resting
    assert pp.step(10.0, ok=lambda b: False) is None                    # held: an attack lands first
    assert pp.step(10.1) == [("a",)]


def test_a_grab_is_shaken_off_every_step_even_while_prompts_rest():
    """SHAKE OFF drains 10 hp a frame until enough new presses come (live 2026-10-21): no gap, no rest, no hold."""
    stats, shown = {}, {"b": "a"}
    pp = reactions.PromptPresser(source=lambda: shown["b"], stats=stats,
                                 keys=lambda b: [("left", "a"), ("right", "b")] if b == "wiggle" else [(b,)])
    for t in (0.0, 0.6, 1.2, 1.8):                                      # a stuck A prompt: three presses, then rest
        pp.step(t)
    assert pp.step(2.0) is None and pp.rest_until > 2.0
    shown["b"] = "wiggle"                                               # grabbed while resting
    steps = [pp.step(2.0 + k * 0.05, ok=lambda b: False) for k in range(10)]
    assert all(s == [("left", "a"), ("right", "b")] for s in steps) and pp.mashing
    assert stats["mash_presses"] == 10


def test_extended_mash_requires_a_title_resolved_chord_and_bypasses_burst_rest():
    from gbox.mercs.titles.re5_ps3 import RE5PS3
    shown, driver = {"button": "mash:cross+circle"}, RE5PS3()
    pp = reactions.PromptPresser(source=lambda: shown["button"], keys=driver.prompt_keys)
    pp.rest_until = 100.0
    for i in range(8):
        assert pp.step(i * 0.08, ok=lambda button: False) == [("cross", "circle")]
    assert pp.mashing and pp.stats["mash_presses"] == 8
    shown["button"] = "mash:unsupported"
    assert pp.step(1.0) is None and not pp.mashing
    generic = reactions.PromptPresser(source=lambda: "mash:circle")
    assert generic.step(0.0) is None and not generic.mashing


def test_lessons_go_where_the_deployment_expects(tmp_path):
    lessons.configure(tmp_path)
    p = lessons.append("G4BE08", {"kind": "coach", "text": "shoot the axe man first", "session_id": "s1"})
    assert p == tmp_path / "mercs" / "lessons" / "G4BE08.jsonl" and lessons.read("G4BE08")[0]["kind"] == "coach"
    run = lessons.Run("G4BE08", clock=lambda: 5.0)
    for _ in range(3):
        run.log("hit_taken", attackers=[{"act": 0x12, "in_value_s": 0.1, "dist": 950}])
    cands = lessons.analyze("G4BE08", known={"act": {0x26}})
    assert cands and cands[0]["field"] == "act" and cands[0]["value"] == 0x12 and cands[0]["confidence"] == "candidate"


def test_shots_are_scored_from_health(tmp_path):
    sh = aim.Shots()
    en = [{"slot": 1, "hp": 1000}, {"slot": 2, "hp": 1000}]
    sh.update(en, 0.0)
    sh.fired(0.1)
    sh.update([{"slot": 1, "hp": 1000}, {"slot": 2, "hp": 300}], 0.15)
    sh.fired(1.5)
    sh.update(en[:1], 2.1)
    assert sh.stats["hits"] == 1 and sh.stats["misses"] == 1 and sh.stats["accuracy"] == 0.5
    r = aim.AimRates.from_profile({"gun_gap_s": 1.0, "turn_rad_s": 2.0})
    assert r.ready_in(0.5, False, 0.25, 0.0) == pytest.approx(0.5 / 2.0 + 0.25 + 0.1)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_play_round_plays_until_the_round_is_over_and_says_why(tmp_path):
    m = re4([((0.0, 0.0, 1500.0), (1, 0x03, 0, 0))])
    clk, sent, stats, logged = Clock(), [], {}, []
    n = [0]

    def stopped():
        n[0] += 1
        if n[0] == 40:
            m.put(PG + B.G_ROOM, ">H", 0x120)                              # a story room: the round is over
        return n[0] > 400
    why = engine.play_round({"driver": "gbox.mercs.titles.re4_gc"}, m, sent.append, stopped, stats, logged.append,
                            sleep=clk.sleep, clock=clk, learn_dir=tmp_path)
    assert why == "round" and stats["ram_progress"] > 10 and stats["timer"] == pytest.approx(100.0)
    assert any(r[0]["key"] == "r" and r[0]["down"] for r in sent if r)  # it aimed at the Ganado
    assert not any(r["down"] for r in sent[-1])                          # everything let go
    assert logged and logged[-1]["kind"] == "round"


def test_stop_cleanup_runs_even_if_releasing_input_fails(tmp_path):
    m, clk = re4([]), Clock()
    calls, saved = [], []

    class Brain:
        def tick(self, snap):
            return {"hold": {"r"}}

        def prompt_ok(self, button, snap, now):
            return True

        def save(self):
            saved.append(True)

    def send(rows):
        calls.append(rows)
        if any(not row["down"] for row in rows):
            raise OSError("input release failed")

    with pytest.raises(OSError, match="input release failed"):
        engine.play_round({"driver": "gbox.mercs.titles.re4_gc"}, m, send, lambda: bool(calls), {},
                          brain=Brain(), sleep=clk.sleep, clock=clk, learn_dir=tmp_path)
    assert saved == [True]


def test_weapon_handover_releases_held_input_before_ack_and_skips_decisions(tmp_path):
    from gbox.mercs.titles import re4_gc
    m, clk, stats, sent = re4([]), Clock(), {}, []
    driver = re4_gc.DRIVER()
    original_snapshot = driver.snapshot
    def snapshot(memory):
        snap = original_snapshot(memory)
        snap['player'].update(ptr=123, generation=4)
        return snap
    driver.snapshot = snapshot
    pending = {'player':123, 'generation':4, 'until':float('inf')}
    class Brain:
        def tick(self, snap):
            assert not stats.get('native_weapon_pending')
            return {'hold': {'r'}}
        def prompt_ok(self, *args): return True
        def save(self): pass
    def send(rows):
        sent.extend(rows)
        if any(row['down'] for row in rows):
            stats['native_weapon_pending'] = pending
        else:
            assert not pending.get('released')
    engine.play_round({'driver':'gbox.mercs.titles.re4_gc'}, m, send,
        lambda: bool(pending.get('released')), stats, driver=driver, brain=Brain(),
        sleep=clk.sleep, clock=clk, learn_dir=tmp_path)
    assert sent == [{'key':'r','down':True}, {'key':'r','down':False}]
    assert pending['released']


def test_play_round_reports_a_lost_game_and_a_stop(tmp_path):
    m = re4([])
    m.put(B.P_PLAYER, ">I", 0)                                         # no Leon: a black screen
    clk = Clock()
    why = engine.play_round({"driver": "gbox.mercs.titles.re4_gc"}, m, lambda rows: None, lambda: clk.t > 60, {},
                            sleep=clk.sleep, clock=clk, learn_dir=tmp_path)
    assert why == "lost" and clk.t > engine.LOST_S
    m2 = re4([])
    why2 = engine.play_round({"driver": "gbox.mercs.titles.re4_gc"}, m2, lambda rows: None, lambda: True, {},
                             sleep=clk.sleep, clock=clk, learn_dir=tmp_path)
    assert why2 == "stopped"


def test_play_round_is_frame_synced_and_measures_its_reactions(tmp_path):
    clk = Clock()

    class Live(FakeMem):                                                # the VI count and the clock run with time
        def rd(self, a, n):
            if a == 0x802B2D2C:
                return int(clk.t * 60).to_bytes(4, "big")
            if a == B.MERC_TIMER:
                return int((100 - clk.t) * 30).to_bytes(4, "big")
            return super().rd(a, n)
    m = re4([((0.0, 0.0, 1500.0), (1, 0x26, 1, 0))])                    # straight ahead, swinging
    m.__class__ = Live
    stats, n = {}, [0]

    def stopped():
        n[0] += 1
        return n[0] > 60
    engine.play_round({"driver": "gbox.mercs.titles.re4_gc"}, m, lambda rows: None, stopped, stats,
                      sleep=clk.sleep, clock=clk, learn_dir=tmp_path)
    assert stats.get("react_vi_med") is not None and 0 <= stats["react_vi_med"] <= 30   # answered within 0.5 s
    assert clk.t < 60 * 0.05                                            # ticks follow the game's frames, not a timer


def test_the_engine_is_not_ready_until_a_live_run_says_so():
    assert engine.READY is False                                         # the deployment waits for the live check


@pytest.mark.parametrize('work', [.010, .080])
def test_title_decision_budget_subtracts_work_and_does_not_catch_up(work, monkeypatch, tmp_path):
    clk = Clock(); sleeps = []; driver = re4_gc.DRIVER()
    monkeypatch.setattr(type(driver), 'frame', None)
    driver.decision_interval_s = 1/30
    monkeypatch.setattr(engine.time, 'perf_counter', clk)
    class Brain:
        def tick(self, snap):
            clk.t += work
            return {'hold': ()}
        def prompt_ok(self, *args): return True
        def save(self): pass
    def sleep(dt):
        sleeps.append(dt); clk.sleep(dt)
    stats = {}
    engine.play_round({'driver':'gbox.mercs.titles.re4_gc'}, re4([]), lambda rows: None,
                      lambda: len(sleeps) >= 50, stats, driver=driver, brain=Brain(),
                      sleep=sleep, clock=clk, learn_dir=tmp_path)
    assert sleeps == pytest.approx([max(.001, 1/30-work)]*50)
    assert stats['decision_work_p95_ms'] == pytest.approx(work*1000)
    assert stats['decision_hz'] <= 31
