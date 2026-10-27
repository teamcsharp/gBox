"""The universal Mercenaries combat brain's foundations (gbox.mercs.brain): the shared anatomy and ray geometry (the RE5
PS3 combat layer's, re-exported there unchanged), the knowledge hook's default and a registered provider, the normalized
snapshot's checks and the enemy tracker, and the abstract actions on both pads."""
import math

import pytest

from gbox.mercs.brain import actions, body, knowledge, snapshot
from gbox.mercs.titles import re5_combat as C


@pytest.fixture(autouse=True)
def _no_provider():
    knowledge.set_provider(None)
    knowledge.last_error[0] = None
    yield
    knowledge.set_provider(None)


def test_the_ps3_combat_layer_uses_the_brains_geometry_unchanged():
    for name in ("dot_on", "ray_error", "line_to", "line_of_sight_aim", "valid_ray", "steering_ray", "bow_tolerance",
                 "wrap", "heading", "HEAD_H", "HEAD_R", "BODY_R", "KNEE_H", "SHOULDER_H", "CHEST_H", "FIRE_CONE",
                 "FIRE_SLACK", "STEER_RAY_CM", "AIM_FIRE_YAW", "AIM_FIRE_PITCH"):
        assert getattr(C, name) is getattr(body, name), name
    foot = (0.0, 0.0, 400.0)
    assert body.dot_on((0, 160, 400), foot) == "head" and body.dot_on((0, 70, 400), foot) == "leg"
    assert body.dot_on((20, 120, 390), foot) == "body" and body.dot_on((0, 20, 400), foot) is None
    assert body.aim_point(foot) == (0.0, body.CHEST_H, 400.0)
    assert body.aim_point(foot, (5.0, 150.0, -3.0)) == (5.0, 150.0, 397.0)


def test_the_default_dispatch_plan_is_todays_constants():
    plan = knowledge.dispatch_plan("010018100CD46000", "uEm10", 0, 250.0, 0x02)
    assert plan == knowledge.DispatchPlan(aim_offset=(0.0, body.CHEST_H, 0.0), range_band="close", fire_mode="hold",
                                          danger=round(1 - 250 / 800, 3), source="default")
    assert [knowledge.range_band(d) for d in (100, 300, 500, 2000, 3000, None)] == \
        ["point_blank", "close", "mid", "far", "beyond", "mid"]
    assert knowledge.dispatch_plan("BLUS30491", distance=5000).danger == 0.0
    knowledge.record({"kind": "shot", "hit": True})                     # nobody registered: dropped


def test_a_registered_database_answers_and_learns_and_its_errors_fall_back():
    seen = []

    class Db:
        def dispatch_plan(self, title, enemy_class, state, distance, weapon):
            return knowledge.DispatchPlan(aim_offset=(0.0, 150.0, 0.0), range_band="mid", fire_mode="tap",
                                          danger=0.9, source=f"db:{title}:{enemy_class}:{state}")

        def record(self, outcome):
            seen.append(outcome)

    knowledge.set_provider(Db())
    plan = knowledge.dispatch_plan("010018100CD46000", "uEm11", 7, 400.0, 0x02)
    assert plan.aim_offset == (0.0, 150.0, 0.0) and plan.source == "db:010018100CD46000:uEm11:7"
    outcome = {"kind": "shot", "title": "010018100CD46000", "hit": True, "hp_delta": -250}
    knowledge.record(outcome)
    assert seen == [outcome] and seen[0] is not outcome                 # a copy: the brain keeps its own

    class Broken:
        def dispatch_plan(self, *a):
            raise KeyError("no such class")

        def record(self, outcome):
            raise OSError("disk full")

    knowledge.set_provider(Broken())
    assert knowledge.dispatch_plan("BLUS30491", "uEm10", 0, 100.0, 2).source == "default"
    assert knowledge.last_error[0] == "KeyError: 'no such class'"
    knowledge.record({"kind": "damage"})
    assert knowledge.last_error[0] == "OSError: disk full"
    assert "_PROVIDER" in knowledge.RELOAD_KEEP


def test_the_normalized_snapshot_is_checked_and_the_tracker_gives_velocities():
    snap = snapshot.blank("010018100CD46000", 10.0)
    snap["player"] = {"id": 1, "pos": (0.0, 0.0, 0.0), "heading": 0.0, "pitch": None, "hp": 1000, "hp_max": 1000,
                      "state": "aiming", "raw_state": 26, "weapon": None}
    snap["enemies"] = [{"id": 7, "pos": (0.0, 0.0, 500.0), "vel": None, "hp": 800, "hp_max": 800, "class": None,
                        "state": None, "boss": False, "threat": {"grab": False, "attacking": False}}]
    assert snapshot.check(snap) == []
    tr = snapshot.Tracker()
    tr.update(snap)
    assert snap["enemies"][0]["vel"] is None
    nxt = dict(snap, t=10.25, enemies=[dict(snap["enemies"][0], pos=(50.0, 0.0, 450.0), vel=None)])
    tr.update(nxt)
    assert nxt["enemies"][0]["vel"] == pytest.approx((200.0, 0.0, -200.0))
    assert snapshot.lead(nxt["enemies"][0], 0.5) == pytest.approx((150.0, 0.0, 350.0))
    late = dict(nxt, t=11.0, enemies=[dict(nxt["enemies"][0], pos=(60.0, 0.0, 440.0), vel=None)])
    tr.update(late)
    assert late["enemies"][0]["vel"] is None                            # 0.75 s on: too old for a velocity
    bad = dict(snap, player=dict(snap["player"], state="sprinting", heading=math.nan),
               aim={"up": True, "ray": ((0, 0, 0), (1, 2)), "fresh": True},
               enemies=[dict(snap["enemies"][0], hp=800.5)])
    assert snapshot.check(bad) == ["player.heading", "player.state", "aim.ray", "enemies[0].hp"]


@pytest.mark.parametrize("pad,want", [
    ("re5_ps3", {"fire": ("l1", "r1"), "steer": ("l1", "rdown", "rleft"), "run": ("cross", "lup"),
                 "quick": ("cross", "ldown"), "item": ("square",), "press": "square"}),
    ("switch_type_d", {"fire": ("zl", "zr"), "steer": ("rdown", "rleft", "zl"), "run": ("b", "lup"),
                       "quick": ("b", "ldown"), "item": ("y",), "press": "a"})])
def test_abstract_actions_map_to_each_pad(pad, want):
    cm = actions.CONTROLS[pad]
    assert actions.keys({"raise": True, "fire": True}, cm)["hold"] == want["fire"]
    assert actions.keys({"raise": True, "aim": (1, -1)}, cm)["hold"] == want["steer"]
    assert actions.keys({"move": "forward", "run": True}, cm)["hold"] == want["run"]
    assert actions.keys({"quick_turn": True}, cm)["hold"] == want["quick"]
    assert actions.keys({"use_item": True}, cm)["hold"] == want["item"]
    assert actions.keys({"press": "action", "fire": True}, cm) == {"tap": want["press"]}
    assert actions.keys({}, cm) == {"hold": ()} and actions.keys(None, cm) == {"hold": ()}
    assert actions.keys({"turn": -1}, cm)["hold"] == ("rright",)
    assert actions.keys({"wiggle": 2}, cm)["hold"] == ("lright",)
