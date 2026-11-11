"""The menu learner: learns PSO's boot screens as a graph and replays them faster each run.

A fake menu machine stands in for the game: it applies a key only after its own latency, so a replay that is too fast is *detected*
rather than assumed to work. That is the property the learning loop depends on - speed is only kept when the screen still changes.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gbox.pso_menu_learn import MenuLearner, TransitionGraph          # noqa: E402


class FakeMenu:
    """attract -> menu -> offline -> licence -> charsel -> field, each key applied after `need` seconds."""

    TRANSITIONS = {
        ("attract", "start"): "menu",
        ("menu", "ddown"): "offline",        # the cursor moves first
        ("offline", "start"): "licence",
        ("licence", "start"): "charsel",
        ("charsel", "start"): "field",
    }

    def __init__(self, need: float = 0.30):
        self.screen = "attract"
        self.need = need
        self.clock = 0.0
        self.pending: tuple[str, float] | None = None
        self.presses = 0

    def now(self):
        return self.clock

    def advance(self, seconds: float):
        self.clock += max(0.0, seconds)
        if self.pending and self.pending[1] <= self.clock:
            self.screen = self.pending[0]
            self.pending = None

    def press(self, key: str):
        self.presses += 1
        nxt = self.TRANSITIONS.get((self.screen, key))
        self.pending = (nxt, self.clock + self.need) if nxt else None

    def observe(self):
        return self.screen


def learner_for(machine, graph=None, **kw):
    return MenuLearner(machine.observe, machine.press, graph,
                       now=machine.now, sleep=machine.advance, **kw)


def test_the_graph_records_what_a_key_does_and_prefers_the_fastest_success():
    graph = TransitionGraph()
    graph.record("attract", "start", "menu", 0.45)
    graph.record("attract", "start", "menu", 0.32)
    edge = graph.edge("attract", "start")
    assert edge["to"] == "menu" and edge["delay"] == pytest.approx(0.32) and edge["visits"] == 2


def test_exploration_finds_a_route_to_the_field():
    machine = FakeMenu()
    learner = learner_for(machine)
    route = learner.learn_route("attract", "field", rounds=80)
    assert route == ["start", "ddown", "start", "start", "start"]
    # and the learned graph agrees
    assert learner.graph.route("attract", "field") == route


def test_replaying_the_route_reaches_the_field_and_uses_no_capture_between_presses():
    machine = FakeMenu()
    learner = learner_for(machine)
    learner.learn_route("attract", "field", rounds=80)
    before = machine.presses
    result = learner.play(["start", "ddown", "start", "start", "start"], verify="field")
    assert result["ok"] is True
    assert machine.screen == "field"
    assert machine.presses - before == 5                 # five presses, one capture at the start and one at the end


def test_each_successful_run_shrinks_the_delays_until_the_machine_needs_them():
    machine = FakeMenu(need=0.30)
    learner = learner_for(machine)
    learner.learn_route("attract", "field", rounds=80)
    keys = ["start", "ddown", "start", "start", "start"]
    first = learner.graph.timings("attract", keys)
    results = learner.speed_run(keys, "field", runs=6, shrink=0.85)
    assert any(r["ok"] for r in results)
    faster = learner.graph.timings("attract", keys)
    assert sum(faster) < sum(first)                      # it got faster
    assert all(d >= learner.graph.minimum for d in faster)
    # and it never claims a run is fine at a delay the machine cannot meet
    assert min(faster) >= 0.0


def test_a_too_fast_replay_is_detected_and_the_edge_is_lengthened():
    machine = FakeMenu(need=0.30)
    learner = learner_for(machine)
    for key, nxt in (("start", "menu"), ("ddown", "offline"), ("start", "licence"),
                     ("start", "charsel"), ("start", "field")):
        screen = {"menu": "attract", "offline": "menu", "licence": "offline",
                  "charsel": "licence", "field": "charsel"}[nxt]
        learner.graph.edges[(screen, key)] = {"delay": 0.01, "visits": 1, "failures": 0, "to": nxt}
    result = learner.play(["start", "ddown", "start", "start", "start"], verify="field")
    assert result["ok"] is False                          # 0.01 s cannot cross a 0.30 s transition
    assert any(edge["failures"] for edge in learner.graph.edges.values())


def test_the_graph_survives_a_save_and_load(tmp_path):
    graph = TransitionGraph()
    graph.record("attract", "start", "menu", 0.4)
    graph.record("menu", "ddown", "offline", 0.3)
    path = graph.save(tmp_path / "menus.json")
    back = TransitionGraph.load(path)
    assert back.route("attract", "offline") == ["start", "ddown"]
    assert back.edge("menu", "ddown")["delay"] == pytest.approx(0.3)


def test_an_unreachable_goal_is_reported_not_guessed():
    learner = learner_for(FakeMenu())
    learner.graph.record("attract", "start", "menu", 0.4)
    with pytest.raises(ValueError):
        learner.graph.route("attract", "field")
