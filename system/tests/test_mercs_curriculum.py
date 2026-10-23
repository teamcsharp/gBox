import json
import random

import pytest

from gbox.mercs.curriculum import Coverage
from gbox.mercs.deployables import Cadence
from gbox.mercs.notebook import Notebook
from gbox.mercs.tour import plan


def test_coverage_visits_every_combination_and_persists_only_started_rounds(tmp_path):
    path = tmp_path / "coverage.json"
    rosters = {"original": ("a", "b"), "reunion": ("c",)}
    c = Coverage(path, rosters, range(3), random.Random(7))
    for _ in range(9):
        selected = c.choose()
        assert c.choose() == selected
        c.started(selected["mode"], selected["character"], selected["stage"])
    assert len(c.counts) == 9 and set(c.counts.values()) == {1}
    assert Coverage(path, rosters, range(3)).counts == c.counts
    assert not c.started("missing", "a", 0)
    assert sum(c.counts.values()) == 9


def test_round_guide_and_vector_recall_do_not_turn_deaths_into_s_ranks(tmp_path):
    n = Notebook(tmp_path, "RE5")
    n.finish("mesh-a", "original", "Jill", "died", {"score": 120000, "kills": 60, "rank": "SS"}, round_id="a")
    n.finish("mesh-b", "reunion", "Barry", "completed", {"score": 70000, "kills": 80, "result_rank": "S"}, round_id="b")
    rows = n.recall("mesh-a", "original", {"kills": 50})
    assert len(rows) == 1 and not rows[0]["observed"]["s_rank_verified"]
    assert n.recall("mesh-a", "reunion") == []
    n.finish("mesh-b", "reunion", "Barry", "completed", {"result_rank": "S"}, round_id="b")
    guide = json.loads((n.root / "guide.json").read_text())
    assert guide["rounds"] == 2 and guide["stages"]["reunion/mesh-b"]["verified_s_ranks"] == 1


def test_round_review_preserves_failure_evidence_and_unknown_acceptance(tmp_path):
    n = Notebook(tmp_path, 'RE5')
    n.finish('geometry', 'original', 'Jill', 'died', {
        'score': 120000, 'rank': 'SS', 'time_bonuses_remaining': 7,
        'player_damage_events': 2, 'stuck': 3, 'nav_oscillations': 2}, round_id='failure')
    review = n.recall('geometry', 'original')[0]['observed']['reflection']
    assert review['acceptance'] == {'completed_s_rank': False, 'all_observed_time_bonuses': False,
                                    'no_sampled_hp_loss': False}
    assert len(review['next_run_actions']) == 4
    assert review['policy']['bonus_commitment'] and not review['policy']['allow_unverified_routes']
    n.finish('other', 'original', 'Chris', 'interrupted', {}, round_id='unknown')
    unknown = n.recall('other', 'original')[0]['observed']['reflection']['acceptance']
    assert unknown['all_observed_time_bonuses'] is None and unknown['no_sampled_hp_loss'] is None


def test_mines_require_acknowledgement_and_resume_after_interruptions():
    c = Cadence(60)
    assert not c.due(0, (0,0,0))
    assert not c.due(61, (300,0,0), busy=True)
    assert c.due(62, (300,0,0))
    assert c.due(63, (300,0,0))  # an attempted input has not acknowledged anything
    c.acknowledge(63, (300,0,0))
    assert not c.due(100, (600,0,0))
    c.entrance = True
    assert c.due(101, (600,0,0))
    c.configure(2, True, False)
    assert not c.due(1000, (900,0,0))
    with pytest.raises(ValueError): c.configure(float("nan"))


def test_tour_uses_time_gained_and_never_invents_a_disconnected_route():
    a={"id":"a","seconds":30}; b={"id":"b","seconds":60}; c={"id":"c","seconds":60}
    start = {"a":100,"b":200,"c":None}
    edges = {("a","b"):500,("b","a"):100}
    result = plan([a,b,c], lambda x,y:edges.get((x["id"],y["id"])),
                  lambda x:start[x["id"]], 4,100)
    assert {g["id"] for g in result} == {"a","b"}
    assert c not in result


def test_tour_can_skip_a_nearest_dead_end_to_collect_every_bonus():
    goals=[{"id":i,"seconds":60} for i in range(3)]
    edges={(1,0):100,(1,2):100,(2,0):100}
    result=plan(goals,lambda a,b:edges.get((a["id"],b["id"])),lambda a:100+a["id"],10,100)
    assert [g["id"] for g in result] == [1,2,0]
