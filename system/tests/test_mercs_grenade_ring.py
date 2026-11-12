"""The bot's own grenade-ring rule (gbox.mercs.grenade_ring) and the enemy tiers it uses.

Synthetic snapshots only: when it fires, when it refuses, the learned-blast-reach guard, the cooldown and the
rings_deployed / ring_kills stats.
"""
import pytest

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


# ---- the shared tiers it consults ------------------------------------------------------------------------------------------

def test_dangerous_comes_from_the_shared_enemy_identity_table():
    # uEm20 is the Executioner Majini in gbox.mercs.enemy_identity's RE5 table: a boss, so worth a ring on its own.
    assert GR.dangerous({"class": "uEm20", "hp_max": 300}, "010018100CD46000") is True
    assert GR.dangerous({"class": "uEm10", "hp_max": 300}, "010018100CD46000") is False
    # An unknown class is tiered by its maximum health on that title (RE6: boss at 3000 and up).
    assert GR.dangerous({"hp_max": 4000}, "01002A000CD48000") is True
    assert GR.dangerous({"hp_max": 300}, "01002A000CD48000") is False
    assert GR.dangerous({}, None) is False
    assert GR.dangerous("not a dict") is False


# ---- decide ----------------------------------------------------------------------------------------------------------------

def test_surrounded_fires_and_an_ordinary_crowd_does_not():
    crowd = [enemy(100 + i * 50) for i in range(4)]
    decision = GR.decide(snap(crowd), stats(), 100.0)
    assert decision["fire"] is True and "surrounded" in decision["reason"] and decision["near"] == 4
    thin = [enemy(100 + i * 50) for i in range(3)]
    ordinary = GR.decide(snap(thin), stats(), 100.0)
    # not "surrounded" - but the operator's periodic rule (a ring at least every two minutes with a group on him)
    # fires it; a ring just fired stops it
    assert ordinary["fire"] is True and "periodic" in ordinary["reason"]
    assert GR.decide(snap(thin), stats(ring_last_at=95.0), 100.0)["fire"] is False


def test_a_boss_or_dangerous_class_alone_is_worth_the_ring():
    decision = GR.decide(snap([enemy(200, hp=9000, hp_max=9000)]), stats(), 100.0, title="010018100CD46000")
    assert decision["fire"] is True and "boss/dangerous" in decision["reason"]
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
    # the same crowd gone and back does not count as pressure (a ring 20 s ago keeps the periodic rule out of it)
    GR.reset()
    assert GR.decide(snap(crowd), stats(ring_last_at=now + 12 - 20), now + 12, GR.policy())["fire"] is False


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


def test_the_engine_hook_fires_once_and_reports_the_receipt(monkeypatch):
    monkeypatch.setattr(GR, "SCATTER_TITLES", frozenset())   # the scatter's own rule has its tests; keep this the ring's
    ring = FakeRing()
    crowd = [enemy(100 + i * 50) for i in range(5)]
    live = stats()
    step = GR.control(None, {"menus": "gbox.mercs.titles.re5_switch", "map_id": "010018100CD46000"}, ring=ring)
    held = []
    out = step(snap(crowd), live, 100.0, lambda keys: held.append(set(keys)) or True)
    assert out["fire"] is False and "waits" in out["reason"]        # the round-start guard
    out = step(snap(crowd), live, 100.0 + GR.RING_START_GUARD_S + 0.1, lambda keys: held.append(set(keys)) or True)
    assert out["fired"] is True and ring.calls and held == [set()]
    assert live["rings_deployed"] == 1 and live["ring_last_reason"].startswith("surrounded")
    # the cooldown stops the next tick from firing again
    again = step(snap(crowd), live, 100.0 + GR.RING_START_GUARD_S + 1.1, lambda keys: True)
    assert again["fire"] is False and "cooldown" in live["ring_decision"]
    # a held input that cannot be released blocks the ring instead of firing over it
    live2 = stats()
    step2 = GR.control(None, {"map_id": "010018100CD46000"}, ring=ring)
    step2(snap(crowd), live2, 100.0, lambda keys: True)             # the guard tick
    blocked = step2(snap(crowd), live2, 100.0 + GR.RING_START_GUARD_S + 0.1, lambda keys: False)
    assert blocked["fire"] is False and "keys did not release" in blocked["reason"]


def test_the_hook_is_quiet_when_nothing_is_happening(monkeypatch):
    monkeypatch.setattr(GR, "SCATTER_TITLES", frozenset())
    live = stats()
    step = GR.control(None, {"map_id": "010018100CD46000"}, ring=FakeRing())
    out = step(snap([]), live, 100.0, lambda keys: True)
    assert out["fire"] is False and "waits" in out["reason"]        # the round-start guard first
    out = step(snap([]), live, 100.0 + GR.RING_START_GUARD_S + 0.1, lambda keys: True)
    assert out["fire"] is False and "nothing worth a ring" in live["ring_decision"]


def test_the_rule_is_switch_only():
    # the operator retired the PS3/GameCube/Wii editions (2026-11-10): their sessions get no auto ring
    assert GR.control(None, {"map_id": "BLUS30491"}) is None
    assert GR.control(None, {"map_id": "G4BE08"}) is None
    assert GR.control(None, {}) is None
    assert callable(GR.control(None, {"map_id": "010099A00BC1E000"}))

def test_a_group_earns_a_random_ring_at_least_every_ninety_seconds():
    """Operator 2026-11-11 17:50: "they need to be ejecting a ring of grenades or grenade launcher shots in a 360 blast
    from their area every minute and a half at least", random ammunition type. The periodic rule fires on a group even
    when the crowd tests above do not, once the ninety seconds have passed since the last ring."""
    group = [enemy(100), enemy(160), enemy(220)]
    decision = GR.decide(snap(group), stats(), 100.0)
    assert decision["fire"] is True and decision["kind"] == "random"
    assert "periodic" in decision["reason"] and decision["flash_ok"] is True
    assert decision["near"] == 3
    # inside the ninety seconds it does not fire on its own
    assert GR.decide(snap(group), stats(ring_last_at=50.0), 100.0)["fire"] is False
    # past ninety seconds it does
    assert GR.decide(snap(group), stats(ring_last_at=50.0), 141.0)["fire"] is True


def test_the_periodic_ring_needs_a_group_and_honours_the_switch():
    assert GR.decide(snap([enemy(100)]), stats(), 100.0)["fire"] is False
    assert GR.decide(snap([enemy(100), enemy(160)]), stats(ring={"enabled": False}), 100.0)["fire"] is False


class RandomRing(FakeRing):
    def grenade_kinds(self):
        return [{"kind": "flash", "available": True},
                {"kind": "hand", "available": False, "reason": "not verified"},
                {"kind": "incendiary", "available": False, "reason": "not verified"}]


def test_fire_random_draws_an_available_kind():
    ring = RandomRing()
    receipt = GR.fire(None, {"kind": "random", "flash_ok": True, "count": 10}, stats(), 100.0, ring=ring)
    assert ring.calls and ring.calls[0][0] == "flash"
    assert receipt["state"] == "confirmed" and receipt["kind"] == "flash"


def test_fire_random_never_uses_a_flash_the_gate_closed():
    ring = RandomRing()
    receipt = GR.fire(None, {"kind": "random", "flash_ok": False}, stats(), 100.0, ring=ring)
    assert receipt["state"] == "refused" and ring.calls == []
    assert "no grenade kind is available" in receipt["reason"]


def test_no_ring_in_the_first_seconds_of_a_round():
    """Live 2026-11-11: the RE5 auto-ring's first attempt at the round's start froze the session twice (15:52, 16:35);
    the crowd triggers wait RING_START_GUARD_S while the round settles."""
    crowd = [enemy(100 + i * 50) for i in range(5)]
    live = stats()
    GR.observe(live, snap(crowd), 100.0, GR.policy())
    early = GR.decide(snap(crowd), live, 101.0)
    assert early["fire"] is False and "waits" in early["reason"]
    later = GR.decide(snap(crowd), live, 100.0 + GR.RING_START_GUARD_S + 0.1)
    assert later["fire"] is True


def test_a_dead_player_gets_no_ring_and_no_error():
    """Live 2026-11-11 (RE6 block): one ring attempt failed with "Unavailable: player is not alive" - a wasted call on a
    snapshot where the player had already died. The rule now declines it before the controller."""

    def dead(s):
        s["player"]["hp"] = 0
        return s

    crowd = [enemy(100 + i * 50) for i in range(5)]
    live = stats()
    GR.observe(live, snap(crowd), 100.0, GR.policy())
    d = GR.decide(dead(snap(crowd)), live, 100.0 + GR.RING_START_GUARD_S + 0.1)
    assert d["fire"] is False and "not alive" in d["reason"]


def test_the_launcher_kind_fires_the_shell_round_ring():
    """Operator 2026-11-11 18:12: the 360 launcher-shot ring. The policy's kind "launcher" draws one of the launcher's
    shell rounds at random and fires the ring with allow_unverified (a research kind until it has a live receipt)."""
    calls = []

    class ShellRing(FakeRing):
        def grenade_kinds(self):
            return [{"kind": "flash", "available": True},
                    {"kind": "shell1302", "available": False, "reason": "unverified"},
                    {"kind": "shell1303", "available": False, "reason": "unverified"},
                    {"kind": "shell1304", "available": False, "reason": "unverified"}]

        def grenade_ring(self, kind, **kw):
            calls.append((kind, kw.get("allow_unverified")))
            return {"state": "confirmed", "verified": False, "kind": kind, "detonated": 1, "requested": 1}

    live = stats()
    out = GR.fire(None, {"kind": "launcher", "count": 8}, live, 100.0, ring=ShellRing())
    assert out.get("state") == "confirmed" and calls and calls[0][0] in GR.SHELL_KINDS
    assert calls[0][1] is True, "the launcher ring takes the unverified path: the spawn is the receipt"
    assert live["ring_kind_fired"] in GR.SHELL_KINDS
    assert live["rings_deployed"] == 1
