import json
from pathlib import Path
import sqlite3

from gbox.mercs import engine, lessons
from gbox.mercs.titles.re5_nav import NavMesh


def run_sequence(tmp_path, monkeypatch, sequence):
    monkeypatch.setattr(lessons,"ROOT",tmp_path/"mercs"/"lessons")
    mesh = NavMesh([(0.,0.,0.),(1000.,0.,0.),(0.,0.,1000.)],[(0,1,2)],[[]])
    stats,logged,sent,index,held = {},[],[],[-1],set()
    class Brain:
        _round_started = None
        marker = None
        recalls = []
        def observe_round(self,snap,where,now):
            if where == "playing" and self.marker != snap["round"]:
                self.marker = snap["round"]
                self._round_started = now
                stats["rounds"] = stats.get("rounds",0)+1
        def recall(self,rows): self.recalls.append(rows)
        def plan(self): return {"phase":"gather_time","route":[(300.,0.,100.)]}
        def tick(self,snap): return {"hold":{"lup"}} if snap["where"]=="playing" else {"hold":set()}
        def prompt_ok(self,*a): return True
        def save(self): pass
    class Driver:
        frame = None
        def snapshot(self,m):
            row = sequence[index[0]]
            return dict(row,player={"pos":(100.+index[0]*10.,0.,100.),"hp":0 if row["where"]=="dead" else 100},nav=mesh)
        def screen(self,m,snap): return snap["where"]
        def progress(self,snap):
            return {"bonuses_taken":snap.get("total_bonuses",0),"score":snap.get("score",1000),"kills":10,
                    "timer":snap.get("timer",100.),"character":"Jill","mercenaries_mode":"mercenaries"}
        def prompt_source(self,*a): return lambda:None
        def prompt_keys(self,b): return []
    brain = Brain()
    def stopped():
        index[0] += 1
        return index[0]>=len(sequence)
    def send(rows):
        for row in rows:
            held.add(row["key"]) if row["down"] else held.discard(row["key"])
        sent.extend(rows)
    def log(row):
        if row["kind"]=="round_learning":
            assert not held  # inputs released before map/DB finalization and new-round recall
        logged.append(row)
    why = engine.play_round({"map_id":"BLUS30491"},object(),send,stopped,stats,log,
                            brain=brain,driver=Driver(),clock=lambda:index[0]*.2,sleep=lambda _:None)
    return why,stats,logged,brain


def test_fast_internal_restarts_write_each_round_map_database_and_recall(tmp_path,monkeypatch):
    sequence = [
        {"where":"playing","round":1,"total_bonuses":0},
        {"where":"playing","round":1,"total_bonuses":1},
        {"where":"dead","round":1,"total_bonuses":1},
        {"where":"playing","round":2,"total_bonuses":1},
        {"where":"playing","round":2,"total_bonuses":2},
        {"where":"results","round":2,"total_bonuses":2,"timer":0.,"score":2000},
        {"where":"playing","round":3,"total_bonuses":2},
    ]
    why,stats,logged,brain = run_sequence(tmp_path,monkeypatch,sequence)
    assert why=="stopped" and stats["rounds"]==stats["round_evidence_finalized"]==3
    assert not stats.get("navigation_atlas_error"),stats.get("navigation_atlas_error")
    json.dumps(stats["navigation_atlas_review"])  # no review.metrics -> row -> review reference cycle
    with sqlite3.connect(tmp_path/"mercs"/"curriculum"/"BLUS30491"/"rounds.sqlite") as db:
        rounds = db.execute("SELECT id,outcome,data FROM rounds ORDER BY rowid").fetchall()
    assert [row[1] for row in rounds]==["died","completed","interrupted"]
    assert len({row[0] for row in rounds})==3
    assert [json.loads(row[2])["bonuses_taken"] for row in rounds]==[1,1,0]
    assert [len(rows) for rows in brain.recalls]==[0,1,2]
    with sqlite3.connect(tmp_path/"mercs"/"navigation"/"BLUS30491"/"atlas.sqlite") as db:
        atlases = db.execute("SELECT id,outcome,ended,json_path,map_path FROM rounds ORDER BY rowid").fetchall()
    assert len(atlases)==3 and all(row[2] is not None for row in atlases)
    assert [row[1] for row in atlases]==["died","completed","interrupted"]
    assert all(Path(row[3]).is_file() and Path(row[4]).is_file() for row in atlases)
    assert len([row for row in logged if row["kind"]=="navigation_round_review"])==3


def test_changed_confirmed_start_marker_rotates_without_a_terminal_screen(tmp_path,monkeypatch):
    sequence = [
        {"where":"playing","round":1,"total_bonuses":0},
        {"where":"playing","round":1,"total_bonuses":1},
        {"where":"loading","round":1,"total_bonuses":1},
        {"where":"playing","round":2,"total_bonuses":1},
    ]
    _,stats,_,brain = run_sequence(tmp_path,monkeypatch,sequence)
    assert stats["round_evidence_finalized"]==2 and len(brain.recalls)==2
    with sqlite3.connect(tmp_path/"mercs"/"curriculum"/"BLUS30491"/"rounds.sqlite") as db:
        rounds = db.execute("SELECT outcome,data FROM rounds ORDER BY rowid").fetchall()
    assert [r[0] for r in rounds]==["ended","interrupted"]
    assert [json.loads(r[1])["bonuses_taken"] for r in rounds]==[1,0]


def test_short_loading_gap_with_unchanged_round_marker_does_not_split_run(tmp_path,monkeypatch):
    sequence = [{"where":"playing","round":1}, {"where":"loading","round":1},
                {"where":"playing","round":1}, {"where":"playing","round":1}]
    _,stats,_,brain = run_sequence(tmp_path,monkeypatch,sequence)
    assert stats["round_evidence_finalized"]==1 and len(brain.recalls)==1
