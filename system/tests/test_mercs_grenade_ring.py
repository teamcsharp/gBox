"""The bot's own grenade-ring rule (gbox.mercs.grenade_ring) and the enemy tiers it uses.

Synthetic snapshots only: when it fires, when it refuses, the learned-blast-reach guard, the cooldown and the
rings_deployed / ring_kills stats.
"""
import pytest

from gbox.mercs import enemy_identity as EI
from gbox.mercs import grenade_ring as GR


@pytest.fixture(autouse=True)
def _clean():
    GR.reset()
    yield
    GR.reset()


def enemy(offset, hp=500, hp_max=500, cls=None):
    return {"ptr": 0x1000 + offset, "pos": [offset, 0.0, 0.0], "hp": hp, "hp_max": hp_max, "class": cls}


def snap(enemies, kills=0, player=(0.0, 0.0, 0.0), screen="playing", hp=900):
    return {"player": {"ptr": 0x2000, "pos": list(player), "hp": hp, "generation": 1},
            "enemies": list(enemies), "kills": kills, "screen": screen}


def stats(**kw):
    out = {"round_evidence_id": "round-1", "screen": "playing"}
    out.update(kw)
    return out


# ---- tiers -----------------------------------------------------------------------------------------------------------------

def test_tier_from_health_and_class_table(monkeypatch):
    assert EI.tier({"hp_max": 5000})[0] == "heavy"
    assert EI.tier({"hp_max": 700})[0] == "normal"
    assert EI.tier({})[0] == "unknown"
    assert EI.tier({"hp_max": 900, "class": "uEm9999"}, "01002A000CD48000")[0] == "normal"
    monkeypatch.setitem(EI.CLASS_TIERS, "01002A000CD48000", {"uEm7777": "boss"})
    tier, basis, name = EI.tier({"hp_max": 300, "class": "uEm7777"}, "01002A000CD48000")
    assert (tier, basis) == ("boss", "class_table") and name == "uEm7777"
    assert EI.dangerous({"hp_max": 300, "class": "uEm7777"}, "01002A000CD48000") is True
    assert EI.dangerous({"hp_max": 300}, "01002A000CD48000") is False


# ---- decide ----------------------------------------------------------------------------------------------------------------

def test_surrounded_fires_and_an_ordinary_crowd_does_not():
    crowd = [enemy(100 + i * 50) for i in range(4)]
    decision = GR.decide(snap(crowd), stats(), 100.0)
    assert decision["fire"] is True and "surrounded" in decision["reason"] and decision["near"] == 4
    thin = [enemy(100 + i * 50) for i in range(3)]
    assert GR.decide(snap(thin), stats(), 100.0)["fire"] is False


def test_a_boss_or_heavy_alone_is_worth_the_ring():
    decision = GR.decide(snap([enemy(200, hp=9000, hp_max=9000)]), stats(), 100.0)
    assert decision["fire"] is True and "boss/heavy" in decision["reason"]
    assert decision["dangerous"] == 1


def test_the_cooldown_is_honoured():
    crowd = [enemy(100 + i * 50) for i in range(5)]
    assert GR.decide(snap(crowd), stats(ring_last_at=95.0), 100.0)["fire"] is False
    assert "cooldown" in GR.decide(snap(crowd), stats(ring_last_at=95.0), 100.0)["reason"]
    assert GR.decide(snap(crowd), stats(ring_last_at=79.0), 100.0)["fire"] is True


def test_the_ring_never_lands_inside_the_learned_blast_reach():
    crowd = [enemy(100 + i * 50) for i in range(5)]
    decision = GR.decide(snap(crowd), stats(bomb_safe_cm=1150), 100.0)
    assert decision["fire"] is True
    assert decision["radius_cm"] == pytest.approx(1150 + GR.DEFAULTS["margin_cm"])
    # a blast reach wider than the native ring can place grenades refuses instead of gambling
    far = GR.decide(snap(crowd), stats(bomb_safe_cm=4000), 100.0)
    assert far["fire"] is False and "wider than the ring" in far["reason"]


def test_operator_control_menu_and_switch_off_all_block():
    crowd = [enemy(100 + i * 50) for i in range(5)]
    assert "operator" in GR.decide(snap(crowd), stats(operator_control=True), 100.0)["reason"]
    assert GR.decide(snap(crowd), stats(screen="results"), 100.0)["fire"] is False
    assert GR.decide(snap(crowd, screen="dead"), {"round_evidence_id": "r"}, 100.0)["fire"] is False
    assert "switched off" in GR.decide(snap(crowd), stats(ring={"enabled": False}), 100.0)["reason"]


def test_a_crowd_that_is_not_thinning_eventually_earns_the_ring():
    # three nearby, kept for longer than not_thinning_s: too few for "surrounded", persistent enough to fire
    crowd = [enemy(100 + i * 50) for i in range(3)]
    now = 100.0
    for t in range(0, 12):
        GR.observe(stats(), snap(crowd), now + t, GR.policy())
    decision = GR.decide(snap(crowd), stats(), now + 12, GR.policy())
    assert decision["fire"] is True and "not thinning" in decision["reason"]
    # the same crowd gone and back does not count as pressure
    GR.reset()
    assert GR.decide(snap(crowd), stats(), now + 12, GR.policy())["fire"] is False


def test_policy_reads_the_title_module_constants_and_bounds_them():
    class Title:
        RING = False
        RING_N = 0          # clamped up to 1
        RING_EVERY_S = 0    # clamped up to 1 s
    p = GR.policy(Title())
    assert p["enabled"] is False and p["min_enemies"] == 1 and p["cooldown_s"] == 1.0
    override = GR.policy(Title(), {"ring": {"enabled": True, "min_enemies": 7, "cooldown_s": 9999}})
    assert override["enabled"] is True and override["min_enemies"] == 7 and override["cooldown_s"] == 600.0


# ---- fire / stats ---------------------------------------------------------------------------------------------------------

class FakeRing:
    def __init__(self, state="confirmed", detonated=10):
        self.state, self.detonated, self.calls = state, detonated, []

    def grenade_ring(self, kind, **kw):
        self.calls.append((kind, kw))
        return {"state": self.state, "verified": self.state == "confirmed", "kind": kind,
                "detonated": self.detonated, "requested": kw.get("count") or 10}


def test_fire_counts_deployed_rings_and_attributes_kills_in_its_window():
    ring, live = FakeRing(), stats(kills=10)
    decision = GR.decide(snap([enemy(100)]), live, 100.0)
    receipt = GR.fire(None, decision, live, 100.0, ring=ring)
    assert receipt["state"] == "confirmed"
    assert live["rings_deployed"] == 1 and live["rings_attempted"] == 1
    assert live["ring_last_at"] == 100.0 and live["ring_pending"]["kills"] == 10
    GR.observe(live, snap([enemy(100)], kills=14), 103.0)
    assert live["ring_kills"] == 4 and live["ring_pending"]["kills"] == 14
    GR.observe(live, snap([enemy(100)], kills=16), 105.0)
    assert live["ring_kills"] == 6
    # after the window the pending attribution is dropped, never carried into the rest of the round
    GR.observe(live, snap([enemy(100)], kills=30), 200.0)
    assert "ring_pending" not in live and live["ring_kills"] == 6


def test_a_refused_ring_is_a_stat_and_still_sets_the_cooldown():
    class Broken:
        def grenade_ring(self, kind, **kw):
            raise RuntimeError("native flash allocation refused")
    live = stats()
    receipt = GR.fire(None, {"kind": "flash", "count": 10}, live, 100.0, ring=Broken())
    assert receipt["state"] == "failed"
    assert live["rings_attempted"] == 1 and "rings_deployed" not in live
    assert live["ring_last_at"] == 100.0 and "allocation refused" in live["ring_error"]


def test_the_engine_hook_fires_once_and_reports_the_receipt():
    ring = FakeRing()
    crowd = [enemy(100 + i * 50) for i in range(5)]
    live = stats()
    step = GR.control(None, {"menus": "gbox.mercs.titles.re6_switch", "map_id": "01002A000CD48000"}, ring=ring)
    held = []
    out = step(snap(crowd), live, 100.0, lambda keys: held.append(set(keys)) or True)
    assert out["fired"] is True and ring.calls and held == [set()]
    assert live["rings_deployed"] == 1 and live["ring_last_reason"].startswith("surrounded")
    # the cooldown stops the next tick from firing again
    again = step(snap(crowd), live, 101.0, lambda keys: True)
    assert again["fire"] is False and "cooldown" in live["ring_decision"]
    # a held input that cannot be released blocks the ring instead of firing over it
    live2 = stats()
    blocked = GR.control(None, {}, ring=ring).__call__(snap(crowd), live2, 100.0, lambda keys: False)
    assert blocked["fire"] is False and "keys did not release" in blocked["reason"]


def test_the_hook_is_quiet_when_nothing_is_happening():
    live = stats()
    step = GR.control(None, {}, ring=FakeRing())
    out = step(snap([]), live, 100.0, lambda keys: True)
    assert out["fire"] is False and "nothing worth a ring" in live["ring_decision"]
