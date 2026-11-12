"""The aim book (gbox.mercs.core.aim_book): per-shot truth and the learning that closes on every miss, on synthetic shot
sequences and synthetic census reads. Nothing here is a claim about a live round."""
import math
import random

import pytest

from gbox.mercs.core import aim_book as A
from gbox.mercs.core import combat


def prof(title="re5_switch", title_id="010018100CD46000", units=1.0, classes=None):
    return combat.TitleProfile(title=title, title_id=title_id, units_per_cm=units,
                               bodies=combat.BodyTable(classes=classes or {}))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def shoot(core, clock, e, origin, bias=(0.0, 0.0), noise=0.0, rng=None, los=True, family="magnum", hp_fall=True):
    """One shot through the plant: the gun goes where it is asked plus bias plus noise; a hit when the line crosses his
    body within its radius / half span (the census then shows his health falling)."""
    plan = core.plan(e, origin, family, clock.t)
    o = core.prof.pos_cm(origin)
    p1 = tuple(v / core.prof.units_per_cm for v in plan.point)
    yaw, pitch = A.angles(o, p1)
    rng = rng or random.Random(1)
    yaw += bias[0] + rng.gauss(0.0, noise)
    pitch += bias[1] + rng.gauss(0.0, noise)
    d = 2000.0
    at = (o[0] + d * math.sin(yaw) * math.cos(pitch), o[1] + d * math.sin(pitch), o[2] + d * math.cos(yaw) * math.cos(pitch))
    k = core.prof.units_per_cm
    b = core.prof.body(e)
    uv = A.crossing(o, at, core.prof.pos_cm(e["pos"]), b)
    on = uv is not None and abs(uv[0]) <= 1.0 and abs(uv[1]) <= 1.0
    s = core.shot(clock.t, e, plan, origin=origin, at=tuple(v * k for v in at), los=los, family=family)
    clock.t += 0.05
    core.tick(clock.t, [e])
    if on and los and hp_fall:
        e["hp"] -= 10
    clock.t += 0.05
    core.tick(clock.t, [e])
    clock.t += A.HIT_S + 0.05
    core.tick(clock.t, [e])
    return s, on


def target(x=0.0, z=500.0, hp=100000, ptr=1, cls="uEm10"):
    return {"ptr": ptr, "pos": (x, 0.0, z), "hp": hp, "hp_max": hp, "class": cls}


def test_the_book_converges_on_a_constant_offset_and_the_hit_rate_rises(tmp_path):
    clock = Clock()
    core = A.AimCore(prof(), {}, root=tmp_path, clock=clock)
    e = target(z=700.0)
    rng = random.Random(7)
    bias = (math.radians(3.0), math.radians(-2.5))
    outcomes = []
    for _ in range(80):
        _s, on = shoot(core, clock, e, (0.0, 140.0, 0.0), bias=bias, noise=math.radians(0.6), rng=rng)
        outcomes.append(on)
    corr = core.book.correction("magnum", "uEm10", "human", A.band(700.0))
    assert corr.yaw == pytest.approx(-bias[0], abs=math.radians(0.5))
    assert corr.pitch == pytest.approx(-bias[1], abs=math.radians(0.5))
    assert sum(outcomes[:15]) < sum(outcomes[-15:])
    assert sum(outcomes[-20:]) >= 18
    assert core.stats["aimbook_hit_rate"] > 0.5 and core.stats["aimbook_shots"] == 80


def test_the_book_does_not_drift_on_zero_mean_noise(tmp_path):
    clock = Clock()
    core = A.AimCore(prof(), {}, root=tmp_path, clock=clock)
    e = target(z=500.0)
    rng = random.Random(3)
    for _ in range(300):
        shoot(core, clock, e, (0.0, 140.0, 0.0), noise=math.radians(1.5), rng=rng)
    c = core.book.cells[core.book.key("magnum", "uEm10", A.band(500.0))]
    assert abs(c["bias"][0]) < math.radians(0.5) and abs(c["bias"][1]) < math.radians(0.5)
    assert abs(c["pt"][0]) < 0.3 and abs(c["pt"][1]) < 0.3


def test_a_shot_with_no_line_of_sight_is_never_learned(tmp_path):
    clock = Clock()
    core = A.AimCore(prof(), {}, root=tmp_path, clock=clock)
    e = target()
    for _ in range(40):
        shoot(core, clock, e, (0.0, 140.0, 0.0), bias=(math.radians(6), 0.0), los=False)
    assert not core.book.cells and not core.book.mine
    assert core.stats["aimbook_miss_no_los"] == 40 and core.stats["aimbook_learned"] == 0


def test_the_bias_is_bounded_a_step_a_shot():
    c = A.new_cell()
    for _ in range(3):
        A.learn_cell(c, {"outcome": "miss", "resid": (math.radians(40), 0.0)}, 0.0)
    assert c["bias"][0] <= A.BIAS_STEP * 3 + 1e-9
    for _ in range(200):
        A.learn_cell(c, {"outcome": "miss", "resid": (math.radians(40), 0.0)}, 0.0)
    assert c["bias"][0] == pytest.approx(A.BIAS_MAX, abs=1e-4)


def test_the_bias_decays_to_zero_when_the_evidence_stops_supporting_it():
    c = A.new_cell()
    for _ in range(40):
        A.learn_cell(c, {"outcome": "miss", "resid": (math.radians(4), 0.0)}, 0.0)
    assert c["bias"][0] > math.radians(3)
    rng = random.Random(5)
    for _ in range(120):
        A.learn_cell(c, {"outcome": "hit", "resid": (rng.gauss(0, math.radians(1.0)), 0.0)}, 0.0)
    assert abs(c["bias"][0]) < math.radians(0.6)


def test_hits_pull_the_body_point_and_a_miss_on_him_pushes_it_away():
    c = A.new_cell()
    for _ in range(40):
        A.learn_cell(c, {"outcome": "hit", "contact": True, "uv": (0.0, 0.4)}, 0.0)
    assert c["pt"][1] == pytest.approx(0.4, abs=0.05)
    before = c["pt"][1]
    for _ in range(5):
        A.learn_cell(c, {"outcome": "miss", "contact": True, "uv": (0.0, -0.6)}, 0.0)
    assert c["pt"][1] > before                         # away from the miss (low on him)
    assert c["tol"] <= A.TOL_MAX


def test_a_mover_missed_behind_teaches_more_lead_and_ahead_less():
    c = A.new_cell()
    for _ in range(10):
        A.learn_cell(c, {"outcome": "miss", "contact": True, "uv": (-0.8, 0.0), "vlat": 200.0, "lead_s": 0.08}, 0.0)
    assert c["lead_s"] == pytest.approx(A.LEAD_MAX, abs=1e-6)     # clamped: 10 x +0.01 from 0.08 would pass 0.12
    for _ in range(5):
        A.learn_cell(c, {"outcome": "miss", "contact": True, "uv": (0.9, 0.0), "vlat": 200.0}, 0.0)
    assert c["lead_s"] == pytest.approx(0.13, abs=1e-6)
    for _ in range(100):
        A.learn_cell(c, {"outcome": "miss", "contact": True, "uv": (-0.8, 0.0), "vlat": -200.0}, 0.0)
    assert 0.0 <= c["lead_s"] <= A.LEAD_MAX


def test_the_ledger_resolves_hits_kills_by_vanishing_lost_and_miss_causes():
    stats = {}
    led = A.Ledger(stats, "aimbook", 0.4)
    e1, e2, e3, e4 = (target(ptr=k, hp=500) for k in (1, 2, 3, 4))
    led.observe(0.0, [e1, e2, e3, e4], kills=10)
    for k, extra in ((1, {"contact": True}), (2, {"contact": True}), (3, {"contact": None}),
                     (4, {"contact": False, "err": (0.2, 0.0)})):
        led.fired({"t": 0.0, "target": k, "band": "3-8m", **extra})
    e1["hp"] = 300                                       # a hit
    led.observe(0.1, [e1, e3, e4], kills=11)             # e2 left the census while the kill count rose: a kill
    done = led.observe(0.5, [e1, e3, e4], kills=11)
    out = {s["target"]: s["outcome"] for s in done}
    assert out == {1: "hit", 2: "kill", 3: "miss", 4: "miss"}
    assert stats["aimbook_hits"] == 2 and stats["aimbook_kills"] == 1 and stats["aimbook_misses"] == 2
    assert stats["aimbook_miss_unmeasured"] == 1 and stats["aimbook_miss_off_body"] == 1
    assert stats["aimbook_hit_rate"] == 0.5
    led.fired({"t": 1.0, "target": 3})
    led.observe(1.1, [e1, e4], kills=11)                 # gone with no kill counted: lost, not a miss
    led.observe(1.6, [e1, e4], kills=11)
    assert stats["aimbook_lost"] == 1 and stats["aimbook_misses"] == 2


def test_the_cross_title_prior_seeds_a_fresh_title_and_yields_to_its_own_evidence(tmp_path):
    clock = Clock()
    re5 = A.AimCore(prof(), {}, root=tmp_path, clock=clock)
    e = target(z=600.0)
    for _ in range(60):
        re5.book.learn({"outcome": "hit", "los": True, "family": "magnum", "cls": "uEm10", "kind": "human",
                        "band": "3-8m", "contact": True, "uv": (0.0, 0.5), "resid": (0.0, 0.0)})
    re5.save()
    re4p = prof("re4_switch", "010099A00BC1E000", units=10.0)
    re4 = A.AimCore(re4p, {}, root=tmp_path, clock=clock)
    c0 = re4.book.correction("magnum", "0xae7050:400", "human", "3-8m")
    assert c0.pv == pytest.approx(re5.book.cells[re5.book.key("magnum", "uEm10", "3-8m")]["pt"][1], abs=1e-6)
    assert "010018100CD46000" in c0.source and c0.n == 0
    for _ in range(60):
        re4.book.learn({"outcome": "hit", "los": True, "family": "magnum", "cls": "0xae7050:400", "kind": "human",
                        "band": "3-8m", "contact": True, "uv": (0.0, -0.2), "resid": (0.0, 0.0)})
    c1 = re4.book.correction("magnum", "0xae7050:400", "human", "3-8m")
    own = re4.book.cells[re4.book.key("magnum", "0xae7050:400", "3-8m")]["pt"][1]
    assert abs(c1.pv - own) < abs(c0.pv - own)          # its own evidence weighs in as it grows
    w_prior = A.PRIOR_N["point"]
    assert c1.pv == pytest.approx((60 * own + w_prior * c0.pv) / (60 + w_prior), abs=1e-6)
    # the plan in mm puts the point v of the half span above his chest
    plan = re4.plan({"ptr": 9, "pos": (0.0, 0.0, 6000.0), "hp": 400, "class": "0xae7050:400"}, (0.0, 0.0, 0.0),
                     "magnum")
    assert plan.point0[1] == pytest.approx((combat.HUMAN.chest + c1.pv * A.half_span(combat.HUMAN)) * 10.0, abs=1.0)


def test_the_book_persists_and_reloads(tmp_path):
    clock = Clock()
    core = A.AimCore(prof(), {}, root=tmp_path, clock=clock)
    e = target()
    for _ in range(20):
        shoot(core, clock, e, (0.0, 140.0, 0.0), bias=(math.radians(2), 0.0))
    assert core.save()
    again = A.AimBook("010018100CD46000", tmp_path)
    k = core.book.key("magnum", "uEm10", A.band(500.0))
    assert again.cells[k]["bias"] == core.book.cells[k]["bias"]
    assert (tmp_path / A.UNIVERSAL / A.FILE).exists()


def test_a_corrupt_book_is_an_empty_one(tmp_path):
    (tmp_path / "010018100CD46000").mkdir()
    (tmp_path / "010018100CD46000" / A.FILE).write_text("{not json", encoding="utf-8")
    assert A.AimBook("010018100CD46000", tmp_path).cells == {}


def test_the_crossing_names_where_the_line_meets_his_body():
    b = combat.HUMAN
    o, foot = (0.0, 140.0, 0.0), (0.0, 0.0, 500.0)
    chest = (0.0, b.chest, 500.0)
    assert A.crossing(o, chest, foot, b) == pytest.approx((0.0, 0.0), abs=1e-6)
    up = A.crossing(o, (0.0, b.chest + A.half_span(b), 500.0), foot, b)
    assert up[1] == pytest.approx(1.0, abs=1e-6)
    side = A.crossing(o, (b.r, b.chest, 500.0), foot, b)   # +x at +z is the larger heading: + u
    assert side[0] == pytest.approx(1.0, abs=1e-3)
    assert A.crossing(o, (0.0, 140.0, -500.0), foot, b) is None


def test_the_kind_of_a_class_is_the_same_in_every_title():
    p = prof(classes={"uEm32": "crawler", "uEm0b": "dog", "big": combat.measured(250, 180, 70, 220, 60)})
    assert A.kind_of(p, {"class": "uEm32"}) == "crawler"
    assert A.kind_of(p, {"class": "uEm0b"}) == "dog"
    assert A.kind_of(p, {"class": "big"}) == "big"
    assert A.kind_of(p, {"class": "uEm10"}) == "human"


def test_every_resolved_shot_is_a_line_of_the_rounds_shot_log(tmp_path):
    import json as _json
    clock = Clock()
    stats = {"round_evidence_id": "r42"}
    core = A.AimCore(prof(), stats, root=tmp_path, clock=clock)
    e = target()
    shoot(core, clock, e, (0.0, 140.0, 0.0), bias=(math.radians(1.0), 0.0))
    core.save()                                           # (the lines are kept until a flush: at save, or 32 of them)
    files = list((tmp_path / "_shots" / "010018100CD46000").glob("*.jsonl"))
    assert len(files) == 1
    row = _json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert row["round"] == "r42" and row["outcome"] in ("hit", "kill", "miss") and row["source"] == "line"
    assert row["err_deg"][0] == pytest.approx(1.0, abs=0.05) and row["band"] == A.band(500.0)


def test_the_gate_takes_a_line_through_his_torso_and_refuses_one_through_his_knees(tmp_path):
    core = A.AimCore(prof(), {}, root=tmp_path)
    e = target(z=120.0)                                   # arm's length: the 2026-11-10 misses' range
    o = (0.0, 140.0, 0.0)
    plan = core.plan(e, o, "magnum")
    b = combat.HUMAN
    assert core.contact_ok(plan, o, (0.0, b.chest, 120.0), e) is True
    assert core.contact_ok(plan, o, (0.0, b.knee - 5.0, 120.0), e) is False, "through his knees"
    assert core.contact_ok(plan, o, (0.0, b.head + 15.0, 120.0), e) is False, "over his head"
    assert core.contact_ok(plan, o, (0.0, 140.0, -100.0), e) is None, "a line away from him: not measured"


def test_a_shot_whose_pitch_was_not_read_teaches_the_yaw_only():
    c = A.new_cell()
    for _ in range(30):
        A.learn_cell(c, {"outcome": "miss", "resid": (math.radians(3), None)}, 0.0)
    assert c["bias"][0] > math.radians(2.5) and c["bias"][1] == 0.0
    row = A.shot_row({"err": (0.01, None), "outcome": "miss"}, "x")
    assert row["err_deg"][1] is None


def test_a_bias_pinned_at_the_cap_with_a_failing_window_probes_back():
    """RE4's close cell live 2026-11-11: 386 shots, 58 hits, the yaw bias pinned at +9 deg - a saturated bias is not
    learning, so it resets to neutral and lets the other terms take over. A window with at most BIAS_PROBE_HITS hits
    counts as failing; a healthier window keeps the bias (it is being confirmed)."""
    c = A.new_cell()
    c["bias"] = [A.BIAS_MAX, 0.0]
    c["recent"] = "M" * A.BIAS_WINDOW
    changes = A.learn_cell(c, {"outcome": "miss", "resid": (A.BIAS_MAX, 0.0)}, 1000.0)
    assert c.get("bias_probes") == 1 and c["bias"] == [0.0, 0.0]
    assert any("bias probe" in ch for ch in changes)
    # one hit in the window is still a failing cell: it probes too
    c2 = A.new_cell()
    c2["bias"] = [A.BIAS_MAX, 0.0]
    c2["recent"] = "M" * (A.BIAS_WINDOW - 6) + "H" + "M" * 5
    A.learn_cell(c2, {"outcome": "miss", "resid": (A.BIAS_MAX, 0.0)}, 1000.0)
    assert c2.get("bias_probes") == 1
    # a healthy window (more than BIAS_PROBE_HITS hits) keeps the bias: it is being confirmed
    c3 = A.new_cell()
    c3["bias"] = [A.BIAS_MAX, 0.0]
    c3["recent"] = "H" * 6 + "M" * (A.BIAS_WINDOW - 6)
    A.learn_cell(c3, {"outcome": "miss", "resid": (A.BIAS_MAX, 0.0)}, 1000.0)
    assert not c3.get("bias_probes")
