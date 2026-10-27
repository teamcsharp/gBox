"""gbox.mercs.round_audit (every round's own verdict) and gbox.mercs.impact_lessons (every impact learned)."""
import json

from gbox.mercs import impact_lessons as IL
from gbox.mercs.round_audit import RoundAudit
from gbox.mercs.round_map import RoundTrace


def finished(title, stats, audit, moving=True, events=()):
    trace = RoundTrace(None, title, "r400", "r1", 400.0)
    for k in range(240):                                                  # 60 s
        trace.add(k * 0.25, (k * 60.0) if moving else 0.0, 0.0, 0.0, {"phase": "fight", "weapon": "Handcannon (0x37)"})
    for e in events:
        trace.event(10.0, e["kind"], 0.0, 0.0, **{k: v for k, v in e.items() if k != "kind"})
    trace.auditor = lambda summary, tr: audit.finish(summary, tr, stats)
    return trace.finish()["audit"]


def test_wall_bumps_a_death_and_an_unapplied_fire_rate_are_problems():
    audit = RoundAudit("G4BE08")
    stats = {"rounds": 3, "character": "Leon", "stuck_events": 10, "deaths": 1}
    audit.start(stats)
    stats.update(stuck_events=16, deaths=2, trigger_mode="tap: A held for 0.8 s fired nothing",
                 round_loadout={"round": 3, "verified": False, "fire_applied": False, "reason": "fire interval",
                                "fire_interval_frames": [35.0] * 5, "fire_want_frames": 1.0})
    a = finished("G4BE08", stats, audit, events=[{"kind": "death", "cause": "killed by swing slot 4"}])
    probs = " | ".join(a["problems"])
    assert "6.0 wall bumps a minute (6 stuck events)" in probs
    assert "died: killed by swing slot 4" in probs and "fire rate not applied: interval [35.0" in probs
    assert "rapid fire fell back to presses" in probs and a["metrics"]["deaths"] == 1


def test_a_clean_round_is_ok():
    audit = RoundAudit("G4BE08")
    stats = {"rounds": 1, "character": "Ada", "shots": 0, "hits": 0, "misses": 0, "hits_taken": 0,
             "round_loadout": {"round": 1, "verified": True, "fire_applied": True, "equipped_ok": True}}
    audit.start(stats)
    stats.update(shots=30, hits=21, misses=9, hits_taken=3)
    a = finished("G4BE08", stats, audit)
    assert a == {"verdict": "OK", "problems": [], "metrics": a["metrics"]} and a["metrics"]["accuracy"] == 0.7


def test_impact_lessons_persist_and_classify_the_attackers_side(tmp_path):
    f = tmp_path / "impact_lessons.json"
    lessons = IL.ImpactLessons(f)
    row = lessons.record("Village", "melee", dist=120.0, facing_deg=-170.0, doing="clear_nearby: swing", loss=160,
                         hp_max=1000)
    assert row["facing"] == "behind" and row["hits_here"] == 1
    lessons.record("Village", "melee", dist=80.0, facing_deg=20.0, doing="fight: on him", loss=90, hp_max=1000)
    lessons.record("Village", "melee", dist=None, facing_deg=60.0)
    lessons.save()
    again = IL.ImpactLessons(f).summary("Village")["melee"]
    assert again["hits"] == 3 and (again["front"], again["side"], again["behind"]) == (1, 1, 1)
    assert again["mean_dist"] == 100 and again["max_loss"] == 0.16
    assert json.loads(f.read_text())["v"] == 1 and IL.facing_class(None) is None


def test_a_standstill_while_the_operator_drives_is_not_the_bots_problem():
    """A pad takeover (gbox.pad_takeover): the round map marks those standstills "operator"; the audit counts only the
    bot's and names the operator's time."""
    audit, stats = RoundAudit("G4BE08"), {"rounds": 1, "character": "Leon",
                                          "round_loadout": {"round": 1, "verified": True, "fire_applied": True}}
    audit.start(stats)
    trace = RoundTrace(None, "G4BE08", "r400", "r1", 400.0)
    for k in range(80):                                                   # 20 s on one spot, the operator driving
        trace.add(k * 0.25, 0.0, 0.0, 0.0, {"phase": "fight", "operator_control": True, "operator_segment": "seg-1"})
    trace.auditor = lambda summary, tr: audit.finish(summary, tr, stats)
    a = trace.finish()["audit"]
    assert not any("standstill" in p for p in a["problems"]) and a["metrics"]["operator_s"] > 0
