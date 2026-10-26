"""Round-2 navigation learning regression: exercise the real Learning state machine.

Covers checkpoint-route outcome recording (start/arrive), damage-risk learning
with duplicate-incident suppression, mine-site recording and the defer
heuristic, and the save/load persistence round-trip that keeps damage risk,
mine sites and route outcomes across an engine restart.
"""
import json
from pathlib import Path

from gbox.mercs.titles.re5_nav import Learning, NavMesh


def open_mesh():
    # Same two-triangle fixture the rest of the RE5 nav suite uses.
    return NavMesh([(-1000., 0., -1000.), (1000., 0., -1000.), (1000., 0., 1000.), (-1000., 0., 1000.)],
                   [(0, 1, 2), (0, 2, 3)], [[(1, 2, 1.)], [(0, 0, 1.)]])


def _learning(mesh, path=None):
    learn = Learning(path)
    learn._stage(mesh)  # populate self.key so begin_route can close the route
    return learn


def test_checkpoint_route_records_start_and_arrival(tmp_path):
    mesh = open_mesh()
    learn = _learning(mesh)
    start, goal = (100., 0., 0.), (-300., 0., 0.)
    learn.begin_route(mesh, start, goal)
    learn.observe(mesh, start, 10.0)
    learn.observe(mesh, goal, 10.4)
    learn.observe(mesh, goal, 10.8)  # within 140cm of goal -> "arrived"
    stage = learn.stages[mesh.learning_sig]
    assert stage["routes"] == {"0:1": {"started": 1, "arrived": 1, "timed_out": 0,
                                       "unreachable": 0, "blocked": 0, "interrupted": 0}}
    # A clean arrival yields no additive route penalty.
    assert learn.route_penalty(mesh, start, goal) == 0.0
    summary = learn.summary()
    assert summary["nav_route_arrivals"] == 1
    assert summary["nav_geometry"] == mesh.learning_sig


def test_route_penalty_grows_with_failures_and_is_bounded(tmp_path):
    mesh = open_mesh()
    learn = _learning(mesh)
    start, goal = (100., 0., 0.), (-300., 0., 0.)
    # Three blocked attempts with no arrival -> bounded additive cost.
    for _ in range(3):
        learn.begin_route(mesh, start, goal)
        learn.finish_route("blocked")
    penalty = learn.route_penalty(mesh, start, goal)
    assert 0.0 < penalty <= 500.0
    # An arrival dilutes the failure cost.
    learn.begin_route(mesh, start, goal)
    learn.observe(mesh, start, 20.0)
    learn.observe(mesh, goal, 20.4)
    learn.observe(mesh, goal, 20.8)
    assert learn.route_penalty(mesh, start, goal) < penalty


def test_damage_risk_learns_and_suppresses_duplicate_incidents(tmp_path):
    mesh = open_mesh()
    learn = _learning(mesh)
    pos = (100., 0., 0.)  # node 0
    incident = "a" * 32
    assert learn.note_damage(mesh, pos, incident, observed_at=100.0) is True
    assert learn.note_damage(mesh, pos, incident, observed_at=120.0) is False  # duplicate incident
    stage = learn.stages[mesh.learning_sig]
    risk = stage["damage_risk"]["0"]
    assert risk["weight"] == 1.0 and risk["at"] == 100.0
    # A later incident on the same floor raises the weight (decay-inclusive).
    assert learn.note_damage(mesh, pos, "b" * 32, observed_at=1900.0) is True
    assert learn.stages[mesh.learning_sig]["damage_risk"]["0"]["weight"] > 1.0
    # Off-floor positions cannot train a nearby floor.
    assert learn.note_damage(mesh, (0., 0., 0.), "c" * 32, observed_at=10.0) is False
    # Malformed incident ids and negative timestamps are rejected.
    assert learn.note_damage(mesh, pos, "nothex", observed_at=10.0) is False
    assert learn.note_damage(mesh, pos, "d" * 32, observed_at=-1.0) is False
    assert learn.summary()["nav_damage_risk_nodes"] == 1


def test_mine_site_records_and_derives_defer_heuristic(tmp_path):
    mesh = open_mesh()
    learn = _learning(mesh)
    pos = (100., 0., 0.)  # node 0
    assert learn.note_mine(mesh, pos, "placements", 2) is True
    assert learn.note_mine(mesh, pos, "damage_windows", 2) is True
    assert learn.note_mine(mesh, pos, "candidate_deaths", 1) is True
    # A bad counter is rejected; off-floor returns False.
    assert learn.note_mine(mesh, pos, "not_a_counter") is False
    assert learn.note_mine(mesh, (0., 0., 0.), "placements") is False
    site = learn.mine_site(mesh, pos)
    assert site["placements"] == 2 and site["damage_windows"] == 2
    # 2 placements / 2 damage windows / 0.5 ratio meets the defer threshold.
    assert site["defer"] is True
    assert "native attribution" in site["evidence"]
    assert learn.summary()["mine_sites_learned"] == 1


def test_persistence_roundtrip_retains_damage_mine_and_routes(tmp_path):
    mesh = open_mesh()
    path = Path(tmp_path) / "atlas.json"
    learn = _learning(mesh, path)
    start, goal = (100., 0., 0.), (-300., 0., 0.)
    learn.begin_route(mesh, start, goal)
    learn.observe(mesh, start, 10.0)
    learn.observe(mesh, goal, 10.4)
    learn.observe(mesh, goal, 10.8)
    learn.note_damage(mesh, start, "e" * 32, observed_at=10.0)
    learn.note_mine(mesh, start, "placements", 1)
    learn.save()
    assert path.exists() and path.stat().st_size > 0
    # A fresh instance from disk recovers every round-2 field.
    relearn = _learning(mesh, path)
    stage = relearn.stages[mesh.learning_sig]
    assert stage["routes"]["0:1"]["arrived"] == 1
    assert stage["damage_risk"]["0"]["weight"] == 1.0
    assert stage["mine_sites"]["0"]["placements"] == 1
    # Duplicate damage from the loaded file is still suppressed.
    assert relearn.note_damage(mesh, start, "e" * 32, observed_at=99.0) is False
    assert relearn.mine_site(mesh, start)["placements"] == 1
    # Raw file is versioned JSON with the expected top-level shape.
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1 and mesh.learning_sig in raw["stages"]
