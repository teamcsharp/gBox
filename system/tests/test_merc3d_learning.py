"""Native mission identity reaches existing round evidence; no invented stage labels or action policy."""
import json
import sqlite3

import pytest

from gbox.mercs import engine, lessons, run_capture
from gbox.mercs.notebook import Notebook
from gbox.mercs.titles import merc3d_3ds as M
from test_merc3d_menus import Guest, STAGE


def native(mission_id=0, chara_id=3):
    g = Guest()
    area = g.area("aS0000", STAGE, 2)
    g.stack(g.obj("aGame"), g.obj("aMerceArea"), area)
    player = g.player()
    sm = g.obj("sMission", 0x130)
    g.u32(M.S_MISSION, sm)
    g.u32(sm + M.M_MISSION, mission_id)
    g.u32(sm + M.M_CHARA, chara_id)
    g.f32(sm + M.M_LEFT, 90.)
    return g, area, player, sm


@pytest.mark.parametrize("mission_id", [0, 2, 0x0102, 0x0402])
def test_native_mission_identity_reaches_stage_and_json_telemetry(mission_id):
    g, _, _, _ = native(mission_id)
    snap = M.snapshot(g)
    stage = f"mission-0x{mission_id:04x}"
    assert snap["stage"].key == stage
    assert M.Merc3D().learning_stage(snap) == stage
    stats = json.loads(json.dumps(M.Merc3D().progress(snap)))
    assert stats["mission_id"] == mission_id and stats["chara_id"] == 3
    assert stats["stage"] == stage
    assert run_capture.stage_of(stats, snap) == stage


@pytest.mark.parametrize("mission_id", [-1, 0x10000, None])
def test_unreadable_or_invalid_mission_does_not_reuse_previous_identity(mission_id):
    g, _, _, _ = native(mission_id or 0)
    if mission_id is None:
        g.u32(M.S_MISSION, 0)
    snap = M.snapshot(g)
    assert snap.get("stage") is None
    assert M.Merc3D().learning_stage(snap) is None
    stats = {"stage": "mission-0x0002", "mission_id": 2, "chara_id": 3}
    stats.update(M.Merc3D().progress(snap))
    assert stats["stage"] is None
    assert run_capture.stage_of(stats, snap) is None


@pytest.mark.parametrize("unreadable_round", [False, True])
def test_engine_waits_for_native_identity_and_recalls_only_that_missions_evidence(tmp_path, monkeypatch, unreadable_round):
    monkeypatch.setattr(lessons, "ROOT", tmp_path / "mercs" / "lessons")
    monkeypatch.setattr(run_capture, "THREADED", False)
    # The enemy DB is unrelated to this contract, and must not use the operator's data directory.
    monkeypatch.setattr(engine, "_enemy_round", lambda *args: {})
    book = Notebook(tmp_path / "mercs", M.MAP_ID)
    own = book.finish("mission-0x0102", "mercenaries", "unknown", "died", {"score": 900})
    book.finish("mission-0x0002", "mercenaries", "unknown", "completed", {"score": 3000})
    book.finish("unknown", "mercenaries", "unknown", "died", {"score": 900})
    g, area, player, sm = native(0x0102)
    # Reused autoplay stats can still name the preceding round on entry.
    stats = {"stage": "mission-0x0002", "mission_id": 2, "chara_id": 3}
    logged, ticks = [], [-1]

    class Brain:
        def __init__(self):
            self.recalls, self.played = [], 0

        def recall(self, rows):
            self.recalls.append((ticks[0], rows))

        def tick(self, snap):
            self.played += 1
            return {"hold": ()}

        def prompt_ok(self, *args):
            return True

        def save(self):
            pass

    def stopped():
        ticks[0] += 1
        # The first playing sample has no sMission yet. Combat may continue,
        # but evidence must wait rather than latch the legacy "unknown" bucket.
        g.u32(M.S_MISSION, 0 if unreadable_round or ticks[0] == 0 else sm)
        if ticks[0] == 12:
            g.u32(area + M.AREA_FLOW + M.FLOW_CUR, 3)  # native objective complete
        return ticks[0] > 12

    brain = Brain()
    engine.play_round({"map_id": M.MAP_ID}, g, lambda rows: None, stopped, stats, logged.append,
                      driver=M.Merc3D(), brain=brain, clock=lambda: ticks[0] * .25, sleep=lambda _: None)
    assert brain.played == 12  # unavailable identity does not delay gameplay
    maps = list((tmp_path / "mercs" / "round_maps" / M.MAP_ID).rglob("*.json"))
    records = [json.loads(path.read_text()) for path in maps if path.name != "extent.json"]
    assert len(records) == 1
    if unreadable_round:
        assert not brain.recalls and "round_memory_saved" not in stats
        assert stats["stage"] is None and stats["mission_id"] is None and stats["chara_id"] is None
        assert records[0]["stage"] == "unknown"  # never reuse the previous mission's map bucket
        return
    assert len(brain.recalls) == 1 and brain.recalls[0][0] == 1
    assert [row["id"] for row in brain.recalls[0][1]] == [own["id"]]
    assert stats["mission_id"] == 0x0102 and stats["chara_id"] == 3
    with sqlite3.connect(book.path) as db:
        stage, outcome, raw = db.execute("select stage,outcome,data from rounds where id=?",
                                        (stats["round_memory_saved"],)).fetchone()
    data = json.loads(raw)
    assert stage == "mission-0x0102" and outcome == "completed"
    assert data["mission_id"] == 0x0102 and data["chara_id"] == 3
    assert data["round_map_stage"] == stage
    assert records[0]["stage"] == stage


def test_fast_next_mission_keeps_each_rounds_native_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(lessons, "ROOT", tmp_path / "mercs" / "lessons")
    monkeypatch.setattr(run_capture, "THREADED", False)
    monkeypatch.setattr(engine, "_enemy_round", lambda *args: {})
    g, area, _, sm = native(2)
    stats, logged, ticks = {}, [], [-1]

    def stopped():
        ticks[0] += 1
        second = ticks[0] >= 13
        g.u32(sm + M.M_MISSION, 0x0102 if second else 2)
        g.u32(sm + M.M_CHARA, 7 if second else 3)
        g.u32(M.S_MISSION, 0 if ticks[0] == 13 else sm)
        g.u32(area + M.AREA_FLOW + M.FLOW_CUR, 3 if ticks[0] in (12, 25) else 2)
        return ticks[0] > 25

    engine.play_round({"map_id": M.MAP_ID}, g, lambda rows: None, stopped, stats, logged.append,
                      driver=M.Merc3D(), clock=lambda: ticks[0] * .25, sleep=lambda _: None)
    book = Notebook(tmp_path / "mercs", M.MAP_ID)
    with sqlite3.connect(book.path) as db:
        rows = db.execute("select stage,outcome,data from rounds order by rowid").fetchall()
    expected = ["mission-0x0002", "mission-0x0102"]
    assert [row[0] for row in rows] == expected
    assert [row[1] for row in rows] == ["completed", "completed"]
    assert [json.loads(row[2])["mission_id"] for row in rows] == [2, 0x0102]
    assert [json.loads(row[2])["chara_id"] for row in rows] == [3, 7]
    recalls = [row for row in logged if row["kind"] == "round_recall"]
    assert [row["stage"] for row in recalls] == expected
    assert all(not row["lessons"] for row in recalls)  # first mission's success is not second mission's lesson
    maps = list((tmp_path / "mercs" / "round_maps" / M.MAP_ID).rglob("*.json"))
    records = [json.loads(path.read_text()) for path in maps if path.name != "extent.json"]
    assert sorted(row["stage"] for row in records) == expected
