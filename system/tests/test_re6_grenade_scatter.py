"""RE6 Switch: the scatter barrage (operator 2026-11-10 ~07:00: "spray a scatter shot of grenades from his postion at
threats at will ... a rapid barrage of random grenades ... without equipping it ... whenever the going gets tough").

No live game: main's fake native controller (test_re6_grenade_ring.ring_controller) records every round's point."""
import math
import random
import struct

import pytest

from gbox.mercs import grenade_ring as G
from gbox.mercs import interventions as I
from gbox import merc_live_controls as LC
from gbox.mercs.titles import re6_switch as R6
from gbox.mercs.titles import re6_switch_native as N
from tests.test_re6_grenade_ring import ring_controller, _flash_resources   # noqa: F401 - the fixture

R = N.R


def points(ctl):
    """The (x, z) each round was moved to before its explosion (the ring's +0x60 writes)."""
    out = []
    for at, data in ctl.writes:
        if at - 0x230000000 >= 0 and (at - 0x230000000) % 0x10000 == N.RING_UNIT_POS and len(data) == 12:
            x, y, z = struct.unpack("<3f", data)
            out.append((x, y, z))
    return out


def test_the_barrage_sprays_a_cone_toward_the_threats_near_to_far_nothing_equipped(monkeypatch):
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    me = (1000.0, 800.0, -2000.0)
    ctl = ring_controller(position=me)
    toward = [(me[0], me[2] + 900.0), (me[0] + 150.0, me[2] + 1000.0)]        # ahead (+z)
    out = ctl.grenade_scatter("random", count=8, toward=toward, rng=random.Random(4))
    assert out["state"] == "confirmed" and out["verified"] and out["detonated"] == 8
    assert out["effect"] == "native_flash_scatter" and all(r["kind"] == "flash" for r in out["rounds"])
    pts = points(ctl)
    assert len(pts) == 8
    axis = R.heading(toward[0][0] + 75.0 - me[0], (toward[0][1] + toward[1][1]) / 2 - me[2])
    for x, y, z in pts:
        d, h = math.hypot(x - me[0], z - me[2]), R.heading(x - me[0], z - me[2])
        assert N.SCATTER_MIN_CM - 1 <= d <= 1000.0 + 200.0 + 1 and abs(R.wrap(h - axis)) <= math.radians(N.SCATTER_SPREAD_DEG) + 0.01
        assert y == pytest.approx(me[1] + N.SCATTER_CHEST_CM)                 # about chest height
    dists = [r["dist_cm"] for r in out["rounds"]]
    assert dists == sorted(dists)                                             # near to far
    assert not any(call for call in ctl.writes if call[0] == ctl.player + 0x5064)   # nothing equipped


def test_the_barrage_is_rapid_and_refuses_unverified_kinds(monkeypatch):
    gaps = []
    monkeypatch.setattr(N.time, "sleep", lambda s: gaps.append(s))
    ctl = ring_controller()
    ctl.grenade_scatter(count=5, rng=random.Random(1))
    assert len(gaps) == 4 and all(0.1 <= g <= 0.2 for g in gaps)              # 0.1-0.2 s apart
    # a hand probe reaches the resource gate now: the class is implemented, and this character carries the flash only
    with pytest.raises(N.Unavailable, match="hand resources are not loaded"):
        ring_controller().grenade_scatter("hand")


def test_a_lost_round_is_an_uncertain_partial_never_replayed(monkeypatch):
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    ctl = ring_controller(spawn_fail_at=3)
    out = ctl.grenade_scatter(count=6, rng=random.Random(2))
    assert out["state"] == "uncertain" and out["detonated"] == 3 and ctl.failed and ctl.recoverable


# --- checkpoint 0.2 / 0.3: no round lands inside its own blast --------------------------------------------------------

def test_a_flash_barrage_never_places_a_round_under_400_cm():
    """The operator: "never let the bot get stunned by their own flash grenades" - even with the threat at 120 cm."""
    me = (1000.0, 800.0, -2000.0)
    ctl = ring_controller(position=me)
    out = ctl.grenade_scatter("random", count=4, toward=[(me[0], me[2] + 120.0)], rng=random.Random(9))
    assert out["state"] == "confirmed" and out["kinds"] == ["flash"]
    dists = [r["dist_cm"] for r in out["rounds"]]
    assert min(dists) >= N.flash_place_min_cm() == 400.0
    assert min(math.hypot(x - me[0], z - me[2]) for x, _y, z in points(ctl)) >= 400.0
    assert out["floor_cm"] == 400.0 and out["floors_cm"]["flash"] == 400.0


def test_an_explosive_barrage_keeps_the_600_cm_ring_floor_without_a_learned_reach(monkeypatch):
    """Checkpoint 0.2: the hand/incendiary probe used to be placed at 300 cm - inside its own blast."""
    from tests.test_re6_class_images import class_controller
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: {0x113, 0x114, 0x115})
    me = (1000.0, 800.0, -2000.0)
    ctl = class_controller(position=me)
    out = ctl.grenade_scatter("hand", count=3, toward=[(me[0], me[2] + 200.0)])
    assert out["state"] == "confirmed" and out["kinds"] == ["hand"]
    dists = [r["dist_cm"] for r in out["rounds"]]
    assert min(dists) >= N.RING_EXPLOSIVE_CLEAR_CM == 600.0
    assert min(math.hypot(x - me[0], z - me[2]) for x, _y, z in points(ctl)) >= 600.0
    assert out["floor_cm"] == 600.0 and out["floors_cm"]["explosive"] == 600.0


# --- the rule: whenever the going gets tough -------------------------------------------------------------------------

def snap_with(enemies, hp=900, kills=10):
    return {"player": {"pos": (0.0, 0.0, 0.0), "hp": hp}, "kills": kills, "screen": "playing",
            "enemies": [{"pos": p, "hp": 300, "hp_max": hm, "class": c} for p, hm, c in enemies]}


def test_tough_moments_fire_the_barrage_and_the_cooldown_holds():
    G.reset()
    stats = {"bomb_safe_cm": 700}
    sp = G.scatter_policy(R6, stats)
    assert sp["enabled"] and sp["cooldown_s"] == R6.SCATTER_EVERY_S and sp["count"] == R6.SCATTER_N
    ring4 = [((300.0 * math.sin(a), 0.0, 300.0 * math.cos(a)), 300, "uEm1000") for a in (0, 1.5, 3.0, 4.5)]
    d = G.decide_scatter(snap_with(ring4), stats, 10.0, sp, title=R6.TITLE_ID)
    assert d["fire"] and "surrounded" in d["reason"] and d["toward"] and d["safe_cm"] == 700
    stats["scatter_last_at"] = 10.0
    assert not G.decide_scatter(snap_with(ring4), stats, 15.0, sp, title=R6.TITLE_ID)["fire"]   # the cooldown
    heavy = [((0.0, 0.0, 1100.0), 1500, "uEm1370")]
    # since 2026-11-10 14:3x every round of RE6's barrage is a flash (SCATTER_FLASH_ONLY): only a tight surround, never
    # for the big ones (a flash does not stop them), and one flash a minute from any source
    d = G.decide_scatter(snap_with(heavy), {}, 100.0, sp, title=R6.TITLE_ID)
    assert not d["fire"] and "not tight" in d["reason"]
    assert not G.decide_scatter(snap_with(ring4), {"native_flash_confirmed_at": __import__("time").time()}, 30.0, sp,
                                title=R6.TITLE_ID)["fire"], "a flash went off just now"
    sp = dict(sp, flash_only=False)                                            # a barrage of other kinds: as before
    d = G.decide_scatter(snap_with(heavy), {}, 100.0, sp, title=R6.TITLE_ID)
    assert d["fire"] and "dangerous" in d["reason"]
    one = [((0.0, 0.0, 450.0), 300, "uEm1000")]
    stats = {}
    G.observe_scatter(stats, snap_with(one, hp=900), 200.0, sp)
    G.observe_scatter(stats, snap_with(one, hp=600), 201.0, sp)                # hurt now
    d = G.decide_scatter(snap_with(one, hp=600), stats, 202.0, sp, title=R6.TITLE_ID)
    assert d["fire"] and "hurt" in d["reason"]
    below = [((0.0, -400.0, 600.0), 1500, "uEm1370")]                          # off his floor: never the void
    assert not G.decide_scatter(snap_with(below), {}, 300.0, sp, title=R6.TITLE_ID)["fire"]


def test_fire_scatter_keeps_the_stats_and_counts_kills_in_its_window():
    class Ctl:
        def __init__(self):
            self.calls = []

        def grenade_scatter(self, kind, **kw):
            self.calls.append((kind, kw))
            return {"state": "confirmed", "detonated": kw["count"]}
    ctl, stats = Ctl(), {"kills": 10}
    receipt = G.fire_scatter(None, {"count": 8, "toward": [(1.0, 2.0)], "safe_cm": 700.0}, stats, 50.0, ring=ctl)
    assert receipt["state"] == "confirmed" and ctl.calls[0][0] == "random" and ctl.calls[0][1]["safe_cm"] == 700.0
    assert stats["scatters_fired"] == 1 and stats["scatter_rounds"] == 8
    G.observe_scatter(stats, {"kills": 14, "player": None}, 53.0)
    assert stats["scatter_kills"] == 4
    assert G.fire_scatter(None, {"count": 8}, stats, 60.0, ring=object())["state"] == "unavailable"
    assert stats["scatter_failures"] == 1


def test_the_engine_step_runs_the_barrage_when_no_ring_fires(monkeypatch):
    G.reset()
    fired = []

    class Ctl:
        def grenade_ring(self, *a, **kw):
            raise AssertionError("no ring this tick")

        def grenade_scatter(self, kind, **kw):
            fired.append(kw)
            return {"state": "confirmed", "detonated": kw["count"]}
    step = G.control(None, {"map_id": R6.TITLE_ID, "menus": "gbox.mercs.titles.re6_switch"}, ring=Ctl())
    heavy = [((0.0, 0.0, 1100.0), 1500, "uEm1370")]                           # past the ring's 8 m danger reach
    out = step(snap_with(heavy), {"bomb_safe_cm": 700}, 10.0)
    assert not out.get("fired") and not fired, "an all-flash barrage at a heavy: never (weapons for him)"
    monkeypatch.setattr(R6, "SCATTER_FLASH_ONLY", False)                      # a barrage of other kinds
    G.reset()
    step = G.control(None, {"map_id": R6.TITLE_ID, "menus": "gbox.mercs.titles.re6_switch"}, ring=Ctl())
    out = step(snap_with(heavy), {"bomb_safe_cm": 700}, 10.0)
    assert out.get("fired") and fired and fired[0]["count"] == R6.SCATTER_N


# --- at will: the op ------------------------------------------------------------------------------------------------

def test_the_op_is_an_intervention_and_a_live_control():
    assert "grenade_scatter" in I.OPERATIONS and "random" in I.GRENADE_SCATTER_KINDS
    assert "grenade_scatter" in LC.ALLOWED
    import uuid
    assert LC.validate_request({"session_id": "s1", "op": "grenade_scatter", "request_id": str(uuid.uuid4()),
                                "kind": "random"}) == "grenade_scatter"
    with pytest.raises(ValueError):
        LC.validate_request({"session_id": "s1", "op": "grenade_scatter", "request_id": str(uuid.uuid4()),
                             "kind": "rocket"})
    assert {"bomb_drop", "bomb_detonate", "detonate"} <= set(LC.ALLOWED)


def test_grenade_scatter_now_never_raises():
    class Ad:
        address_mode = "direct"

        def _guest(self):
            raise OSError("no emulator")
    out = N.grenade_scatter_now(Ad())
    assert out["state"] in ("unavailable", "failed") and not out["verified"]


# --- checkpoint A3: the random draw follows the character's loaded resources -----------------------------------------

def test_a_random_barrage_draws_only_the_loaded_kinds(monkeypatch):
    from tests.test_re6_class_images import class_controller
    monkeypatch.setattr(N, "SCATTER_KINDS", ("flash", "hand"))
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    flash_item = N.CLASSES.class_for("flash").item
    hand_item = N.CLASSES.class_for("hand").item
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: {flash_item})
    ctl = class_controller()
    out = ctl.grenade_scatter("random", count=4, toward=[(1000.0, 0.0)])
    assert out["state"] == "confirmed" and out["kinds"] == ["flash"]      # the hand he does not carry is left out
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: set())
    with pytest.raises(N.Unavailable, match="none of this build's barrage kinds"):
        ctl.grenade_scatter("random", count=2)


def test_a_random_barrage_with_both_loaded_can_draw_either(monkeypatch):
    from tests.test_re6_class_images import class_controller
    monkeypatch.setattr(N, "SCATTER_KINDS", ("flash", "hand"))
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    both = {N.CLASSES.class_for("flash").item, N.CLASSES.class_for("hand").item}
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: both)
    ctl = class_controller()
    out = ctl.grenade_scatter("random", count=8, toward=[(1000.0, 0.0)], rng=random.Random(2))
    assert out["state"] == "confirmed" and set(out["kinds"]) <= {"flash", "hand"}


def test_a_narrowed_draw_still_refuses_a_kind_he_cannot_carry(monkeypatch):
    from tests.test_re6_class_images import class_controller
    monkeypatch.setattr(N, "SCATTER_KINDS", ("flash", "hand"))
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    flash_item = N.CLASSES.class_for("flash").item
    monkeypatch.setattr(N.R, "inventory_items", lambda m, p: {flash_item})
    ctl = class_controller()
    with pytest.raises(N.Unavailable, match="hand resources are not loaded"):
        ctl.grenade_scatter("random", count=2, kinds=("hand",))
