"""Brain step 4 (Hermes #4484): the RE5 Switch fight uses the enemy knowledge database's learned plan for its target
(gbox.mercs.brain.knowledge.dispatch_plan): the aim height for his class at this distance and weapon in place of
CHEST_H, and the range where that class's shots do the most preferred in the target choice; a field only at
K_MIN_CONF and K_MIN_SAMPLES; the plan it used in stats k_plan and the round counters k_aim_ticks / k_range_picks."""
import math

import pytest

from gbox.mercs.brain import knowledge
from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    yield
    knowledge.set_provider(None)


class Provider:
    def __init__(self, conf=0.9, samples=100, aim=130.0, rng=(150.0, 500.0)):
        self.conf, self.samples, self.aim, self.rng, self.asked = conf, samples, aim, rng, []

    def dispatch_plan(self, title, cls, state, distance, weapon):
        self.asked.append((title, cls, round(distance), weapon))
        return knowledge.DispatchPlan(aim_offset=(0.0, self.aim, 0.0), range_band="mid", source="enemy_db: aim_offset, range_cm",
                                      zone="chest", range_cm=self.rng, confidence=self.conf,
                                      field_confidence=(("aim_offset", self.conf), ("range_cm", self.conf)),
                                      field_samples=(("aim_offset", self.samples), ("range_cm", self.samples)))

    def record(self, outcome):
        pass


def at(dist, deg):
    a = math.radians(deg)
    return (dist * math.sin(a), 0.0, dist * math.cos(a))


def snap(enemies, dot=None):
    return {"player": {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0},
            "enemies": [{"ptr": 10 + i, "pos": pos, "hp": 800, "hp_max": 800, "class": "uEm10"}
                        for i, pos in enumerate(enemies)],
            "inventory": [{"slot": 3, "id": 0x102, "type": 1, "item": 0x02, "rounds": 50, "cap": 50, "grid": 3,
                           "hand": True}],
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def test_the_fight_aims_at_the_learned_height_when_the_database_is_sure():
    prov = Provider()
    knowledge.set_provider(prov)
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    foe = at(500, 0)
    b.tick(snap([foe]))
    clock[0] = 0.3
    b.tick(snap([foe], dot=(foe[0], 110.0, foe[2])))                # the dot at CHEST_H: the old aim point
    assert b.stats["k_aim_ticks"] >= 1 and b.stats["k_plan"]["aim_h_cm"] == 130
    assert b.stats["k_plan"]["fields"] == ["aim_offset", "range_cm"] and prov.asked[0][1] == "uEm10"
    assert prov.asked[0][3] == 0x02                                  # per weapon
    assert "rup" in b.stats["aim"].split("keys ")[1] or "zr" in b.stats["aim"]   # steering up to 130 (or on him)


def test_an_unsure_or_thin_field_keeps_the_chest_and_no_class_asks_nothing():
    for prov in (Provider(conf=0.3), Provider(samples=5)):
        knowledge.set_provider(prov)
        b = R.Bot(stats={}, clock=lambda: 0.0)
        assert b._aim_h({"ptr": 10, "pos": at(500, 0), "class": "uEm10"}, 500.0, 0.0) == R.CHEST_H
        assert b.stats["k_aim_ticks"] == 0
    prov = Provider()
    knowledge.set_provider(prov)
    b = R.Bot(stats={}, clock=lambda: 0.0)
    assert b._aim_h({"ptr": 10, "pos": at(500, 0)}, 500.0, 0.0) == R.CHEST_H and prov.asked == []


def test_the_learned_range_is_preferred_in_the_target_choice_and_counted():
    knowledge.set_provider(Provider(rng=(150.0, 500.0)))
    b = R.Bot(stats={}, clock=lambda: 0.0)
    p = {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0}
    inside = {"ptr": 10, "pos": at(480, 100), "class": "uEm10", "hp": 800}    # inside the learned 1.5-5 m: cost 747
    outside = {"ptr": 11, "pos": at(600, -40), "class": "uEm10", "hp": 800}   # past it: cost 733, a little cheaper
    assert b._choose(p, [inside, outside], 0.0)["ptr"] == 10 and b.stats["k_range_picks"] == 1
    knowledge.set_provider(Provider(conf=0.2))                       # unsure: the plain cost decides
    b2 = R.Bot(stats={}, clock=lambda: 0.0)
    assert b2._choose(p, [inside, outside], 0.0)["ptr"] == 11 and b2.stats["k_range_picks"] == 0
    for k in R.K_COUNTERS:
        assert k in R.RE5Switch.round_counters
