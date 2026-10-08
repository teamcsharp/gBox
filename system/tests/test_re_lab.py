"""gbox.re_lab: playbooks + dossiers the in-app agent reads before and writes after reverse-engineering tasks."""
from gbox import re_lab, re_seeds


class Store:
    def __init__(self):
        self.d = {}

    def put(self, kind, id, body):
        self.d[(kind, id)] = body

    def get(self, kind, id):
        return self.d.get((kind, id))

    def all(self, kind):
        return [v for (k, _i), v in self.d.items() if k == kind]


RE4 = {"game_id": "78ab9efa2e310db4", "title": "Resident Evil 4 (USA) (Disc 1)", "platform": "gamecube"}


def test_playbooks_seeded_ranked_and_learn_keeps_lessons():
    s = Store()
    ranked = re_lab.playbooks(s, "find the code that writes the player's health")
    assert ranked and ranked[0]["id"] == "find-value-writer"
    r = re_lab.learn(s, "find-value-writer", "On GameCube set the watchpoint after the room loads.", "worked", "RE4")
    assert r["lessons"] == 1
    pb = s.get("playbook", "find-value-writer")
    pb["seed_version"] = 0                                     # an older stored seed: re-seeding keeps the lessons
    s.put("playbook", "find-value-writer", pb)
    re_lab.seed_playbooks(s)
    assert len(s.get("playbook", "find-value-writer")["lessons"]) == 1
    assert "Lessons learned" in re_lab.render_playbook(s.get("playbook", "find-value-writer"))


def test_dossier_seeded_with_documented_facts():
    s = Store()
    d = re_lab.dossier(s, RE4)
    assert any(f["status"] == "documented" and f["address"] == "0x802B2280" for f in d["findings"])
    assert "pG" in re_lab.render_dossier(d)


def test_validated_needs_existing_evidence_and_no_self_documented():
    s = Store()
    sha = "a" * 64
    r = re_lab.record(s, RE4, "function", "0x80001234", "hp_write", "writes player HP", "validated", [sha])
    assert r["finding"]["status"] == "hypothesis"              # the artifact doesn't exist
    s.put("artifact", sha, {"name": "trace.json"})
    r = re_lab.record(s, RE4, "function", "0x80001234", "hp_write", "writes player HP", "validated", [sha])
    assert r["finding"]["status"] == "validated"
    assert re_lab.record(s, RE4, "global", "0x1", "x", "y", "documented")["finding"]["status"] == "hypothesis"
    d = s.get("dossier", RE4["game_id"])
    assert sum(1 for f in d["findings"] if f["address"] == "0x80001234") == 1   # same address = update, not a duplicate
    re_lab.record(s, RE4, question="Where is the Leon model loaded from?")
    assert "Open questions" in re_lab.render_dossier(s.get("dossier", RE4["game_id"]))


def test_seeds_are_well_formed():
    ids = [p["id"] for p in re_seeds.PLAYBOOKS]
    assert len(ids) == len(set(ids))
    for p in re_seeds.PLAYBOOKS:
        assert p["steps"] and all("do" in st for st in p["steps"])


def test_analysis_summary():
    a = {"functions": [{"name": "FUN_80001000"}, {"name": "PlayerUpdate"}], "strings": [{"value": "player.dat"}, {"value": "zzz"}]}
    s = re_lab.summarize_analysis(a, "b" * 64)
    assert s["named"] == ["PlayerUpdate"] and s["strings_sample"] == ["player.dat"] and s["functions"] == 2
